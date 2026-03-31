from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import quote, urlparse

from fastapi import WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI

from app.agent import PoliceReportAgent
from app.config import Settings
from app.emailer import send_report_email
from app.forwarder import forward_report
from app.storage import save_report_bundle
from app.whatsapp_delivery import send_report_whatsapp


logger = logging.getLogger(__name__)

PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{6,}\d)")


SCAM_BAIT_PROMPT = """
You are a calm, believable phone agent answering suspected scam calls in real time.
Speak naturally like a human, not like a robot.
Speak Arabic by default in a formal Emirati male tone unless the caller clearly prefers another language.
Sound like a respectful Emirati man handling a phone call calmly and confidently.
Use local UAE wording naturally, but keep it polished and measured rather than slang-heavy.
Your job is to keep suspected scammers talking for as long as reasonably possible,
guide the conversation into long, rambling, meandering paths, and quietly collect
details that can later support a non-emergency police report draft.

Rules:
- Start with a brief greeting and one simple opening question.
- Ask only one main question at a time.
- Keep the conversation flowing with polite confusion, clarification questions, repetition,
  digressions, and requests to explain details again in another way.
- Sound cooperative and a little slow, but never hostile.
- Collect these facts when possible: caller name or alias, company or agency claimed,
  callback number, account or payment details requested, websites or apps mentioned,
  threats used, money requested, payment method, and any timing details.
- Give high priority to collecting the exact callback number, claimed organization,
  reason for the call, what the caller wants you to do, how payment would be made,
  and what threat or urgency they use.
- Before the call ends, briefly recap the main details out loud so the transcript
  contains a confirmation of the scammer's story.
- Do not reveal that you are trying to waste time or document the call.
- Do not impersonate law enforcement, emergency services, or a real bank.
- Do not provide private data, passwords, OTP codes, or real financial details.
- If the caller asks for sensitive information, deflect and keep them talking instead of complying.
- If the conversation naturally winds down, end politely and tell the caller you will check the information and return later.
""".strip()


REPORTING_PROMPT = """
You are a transparent scam reporting assistant answering calls from potential victims.
Speak clearly, warmly, and efficiently.
Speak Arabic by default in a formal Emirati male tone that stays warm, respectful, and professional.
Sound like a composed Emirati man helping the caller clearly and patiently.
Use local wording in a polished way, not heavy slang.
Your job is to help the caller document the suspected scam, collect the most important facts,
and prepare a professional non-emergency police report draft.

Rules:
- Introduce yourself clearly as a reporting assistant at the beginning of the call.
- Ask short, direct follow-up questions one at a time.
- Move quickly and efficiently. Do not drag the call out once the core facts are known.
- Do not ask the same question again if the caller already answered it clearly.
- Ask at most four focused follow-up questions unless the caller adds new important details.
- Prioritize collecting: scammer number, claimed company or agency, what was requested,
  any money loss, payment method, links or apps mentioned, threats or urgency used,
  and whether the caller has screenshots, recordings, or messages.
- If important information is missing, ask for it plainly instead of guessing.
- Be supportive, but do not promise law-enforcement action.
- Do not advise retaliation, hacking, or any unlawful conduct.
- Once you have enough information, stop asking questions.
- Before ending, briefly summarize the key facts so the transcript confirms them.
- Then say clearly in Arabic that the police report has been prepared, thank the caller, say goodbye, and end the call.
- Use a closing very close to this wording: تم إعداد البلاغ. شكراً لاتصالك. مع السلامة.
""".strip()


def build_voice_agent_prompt(line_role: str) -> str:
    if line_role == "reporting":
        return REPORTING_PROMPT
    return SCAM_BAIT_PROMPT


def build_opening_instructions(line_role: str) -> str:
    if line_role == "reporting":
        return (
            "Begin the call now in Arabic with a formal Emirati male tone. "
            "Say: السلام عليكم، معاك مساعد بلاغات الاحتيال. أقدر أساعدك في توثيق الواقعة وإعداد تقرير. "
            "Then ask: تفضل، خبرني شو اللي صار وياك؟"
        )
    return (
        "Begin the call now in Arabic with a formal Emirati male tone. "
        "Open with a short believable question such as: السلام عليكم، منو معاي لو سمحت؟ وشو الموضوع؟"
    )


@dataclass
class CallTranscript:
    call_sid: Optional[str] = None
    stream_sid: Optional[str] = None
    caller_number: Optional[str] = None
    called_number: Optional[str] = None
    line_role: str = "scam_bait"
    turns: List[Dict[str, str]] = field(default_factory=list)

    def add_turn(self, role: str, text: str) -> None:
        cleaned = text.strip()
        if cleaned:
            self.turns.append({"role": role, "text": cleaned})

    def has_caller_content(self) -> bool:
        return any(turn["role"] == "caller" for turn in self.turns)

    def has_reportable_data(self) -> bool:
        return bool(
            self.turns
            or self.call_sid
            or self.stream_sid
            or self.caller_number
            or self.called_number
        )

    def transcript_text(self) -> str:
        return "\n".join(f"{turn['role'].title()}: {turn['text']}" for turn in self.turns)


@dataclass
class RealtimeCallState:
    response_active: bool = False
    should_end_call: bool = False


def _normalize_phone_digits(value: str | None) -> Optional[str]:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits or None


def resolve_voice_line_role(called_number: str | None, settings: Settings) -> str:
    called = _normalize_phone_digits(called_number)
    reporting = _normalize_phone_digits(settings.twilio_reporting_phone_number)
    scam_bait = _normalize_phone_digits(settings.twilio_agent_phone_number)

    if called and reporting and called == reporting:
        return "reporting"
    if called and scam_bait and called == scam_bait:
        return "scam_bait"
    if settings.twilio_reporting_phone_number and not settings.twilio_agent_phone_number:
        return "reporting"
    return "scam_bait"


def build_stream_url(
    public_base_url: str,
    caller_number: str | None = None,
    called_number: str | None = None,
    line_role: str | None = None,
) -> str:
    parsed = urlparse(public_base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/")
    stream_url = f"{scheme}://{parsed.netloc}{path}/twilio/voice/media-stream"
    params = []
    if caller_number:
        params.append(f"caller_number={quote(caller_number)}")
    if called_number:
        params.append(f"called_number={quote(called_number)}")
    if line_role:
        params.append(f"line_role={quote(line_role)}")
    if params:
        stream_url = f"{stream_url}?{'&'.join(params)}"
    return stream_url


def build_conversation_twiml(
    settings: Settings,
    caller_number: str | None = None,
    called_number: str | None = None,
    line_role: str | None = None,
) -> str:
    if not settings.public_base_url:
        raise ValueError("PUBLIC_BASE_URL is required for conversational phone mode.")

    from twilio.twiml.voice_response import Connect, VoiceResponse

    response = VoiceResponse()
    connect = Connect()
    connect.stream(
        url=build_stream_url(
            settings.public_base_url,
            caller_number=caller_number,
            called_number=called_number,
            line_role=line_role,
        )
    )
    response.append(connect)
    response.hangup()
    return str(response)


def should_end_reporting_call(line_role: str, assistant_text: str) -> bool:
    if line_role != "reporting":
        return False
    normalized = " ".join(assistant_text.split())
    close_markers = (
        "تم إعداد البلاغ",
        "تم تجهيز البلاغ",
        "تم إعداد التقرير",
        "شكراً لاتصالك",
        "مع السلامة",
    )
    marker_hits = sum(1 for marker in close_markers if marker in normalized)
    return marker_hits >= 2


def _normalize_phone_number(value: str | None) -> Optional[str]:
    if not value:
        return None
    cleaned = value.strip()
    return cleaned or None


def _extract_phone_numbers(text: str) -> List[str]:
    numbers: List[str] = []
    for match in PHONE_PATTERN.findall(text):
        candidate = " ".join(match.split())
        if candidate not in numbers:
            numbers.append(candidate)
    return numbers


def _infer_requested_money(transcript: str) -> Optional[bool]:
    lowered = transcript.lower()
    keywords = (
        "pay",
        "payment",
        "transfer",
        "wire",
        "gift card",
        "crypto",
        "bitcoin",
        "fees",
        "deposit",
        "send money",
        "bank details",
        "card number",
        "otp",
        "verification code",
        "apple gift",
    )
    if any(keyword in lowered for keyword in keywords):
        return True
    return None


def _infer_payment_method(transcript: str) -> Optional[str]:
    lowered = transcript.lower()
    payment_keywords = {
        "bank transfer": "Bank transfer",
        "wire": "Wire transfer",
        "gift card": "Gift card",
        "crypto": "Cryptocurrency",
        "bitcoin": "Bitcoin",
        "paypal": "PayPal",
        "zelle": "Zelle",
        "western union": "Western Union",
        "apple pay": "Apple Pay",
        "cash app": "Cash App",
    }
    for keyword, label in payment_keywords.items():
        if keyword in lowered:
            return label
    return None


def _infer_scam_type(transcript: str) -> str:
    lowered = transcript.lower()
    scam_types = (
        ("bank", "Bank impersonation scam call"),
        ("otp", "Account takeover scam call"),
        ("verification code", "Account takeover scam call"),
        ("gift card", "Gift card scam call"),
        ("crypto", "Cryptocurrency payment scam call"),
        ("bitcoin", "Cryptocurrency payment scam call"),
        ("refund", "Refund scam call"),
        ("technical support", "Technical support scam call"),
        ("irs", "Government impersonation scam call"),
        ("police", "Law-enforcement impersonation scam call"),
        ("customs", "Government impersonation scam call"),
        ("delivery", "Delivery scam call"),
        ("investment", "Investment scam call"),
    )
    for keyword, label in scam_types:
        if keyword in lowered:
            return label
    return "Suspected inbound scam call answered by the automated agent"


def build_report_intake_from_call(state: CallTranscript, settings: Settings) -> Dict[str, object]:
    transcript = state.transcript_text().strip()
    partial_report = False
    if not transcript:
        partial_report = True
        transcript = (
            "تم إغلاق المكالمة قبل اكتمال جمع التفاصيل. "
            "لم يتم التقاط نص واضح من المتصل، ولذلك أُعد هذا البلاغ الجزئي استناداً إلى بيانات الاتصال المتاحة فقط."
        )
    detected_numbers = _extract_phone_numbers(transcript)
    if state.line_role == "reporting":
        scam_phone_number = detected_numbers[0] if detected_numbers else None
        reporter_name = None
        reporter_phone = state.caller_number
        suspected_scam_type = "Phone scam reported by caller to the reporting line"
    else:
        scam_phone_number = _normalize_phone_number(state.caller_number) or (detected_numbers[0] if detected_numbers else None)
        reporter_name = "Automated scam-call agent"
        reporter_phone = settings.twilio_agent_phone_number or state.called_number
        suspected_scam_type = _infer_scam_type(transcript)
    notes = []
    if state.call_sid:
        notes.append(f"Twilio CallSid: {state.call_sid}")
    if state.stream_sid:
        notes.append(f"Twilio StreamSid: {state.stream_sid}")
    if state.called_number:
        notes.append(f"Twilio called number: {state.called_number}")
    if scam_phone_number:
        notes.append(f"Suspected caller number: {scam_phone_number}")
    if partial_report:
        notes.append("Call ended before full information capture; report created from partial call data.")

    return {
        "reporter_name": reporter_name,
        "reporter_phone": reporter_phone,
        "reporter_email": None,
        "incident_country": settings.twilio_default_country,
        "incident_city": settings.twilio_default_city,
        "call_received_at": datetime.now(timezone.utc).isoformat(),
        "scam_phone_number": scam_phone_number,
        "suspected_scam_type": suspected_scam_type,
        "transcript": transcript,
        "short_notes": " | ".join(notes) if notes else None,
        "money_requested": _infer_requested_money(transcript),
        "money_lost_amount": None,
        "payment_method": _infer_payment_method(transcript),
        "wants_forwarding": settings.twilio_auto_forward_reports,
    }


def save_call_report(settings: Settings, state: CallTranscript) -> Optional[Dict[str, object]]:
    if not state.has_reportable_data():
        return None

    intake_data = build_report_intake_from_call(state, settings)
    agent = PoliceReportAgent(settings)
    report = agent.generate_report(intake_data)
    paths = save_report_bundle(settings.report_storage_dir, intake_data, report)
    forwarding = forward_report(settings, intake_data, report)
    email = send_report_email(settings, intake_data, report, paths)
    whatsapp = send_report_whatsapp(settings, intake_data, report, paths)
    return {"report": report, "paths": paths, "forwarding": forwarding, "email": email, "whatsapp": whatsapp}


async def run_conversational_call(websocket: WebSocket, settings: Settings) -> None:
    await websocket.accept()
    state = CallTranscript(
        caller_number=websocket.query_params.get("caller_number"),
        called_number=websocket.query_params.get("called_number"),
        line_role=websocket.query_params.get("line_role") or "scam_bait",
    )
    runtime = RealtimeCallState()

    if not settings.openai_api_key:
        await websocket.close(code=1011, reason="OPENAI_API_KEY is not configured.")
        return

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    try:
        async with client.realtime.connect(model=settings.twilio_realtime_model) as connection:
            await connection.session.update(
                session={
                    "type": "realtime",
                    "instructions": build_voice_agent_prompt(state.line_role),
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcmu"},
                            "noise_reduction": {"type": "near_field"},
                            "transcription": {
                                "model": settings.twilio_transcription_model,
                                "language": settings.twilio_agent_language,
                            },
                            "turn_detection": {
                                "type": "server_vad",
                                "create_response": True,
                                "interrupt_response": True,
                                "silence_duration_ms": 600,
                                "prefix_padding_ms": 300,
                                "idle_timeout_ms": 6000,
                            },
                        },
                        "output": {
                            "format": {"type": "audio/pcmu"},
                            "voice": settings.twilio_agent_voice,
                            "speed": settings.twilio_agent_speed,
                        },
                    },
                    "output_modalities": ["audio"],
                    "max_output_tokens": 350,
                }
            )

            twilio_task = asyncio.create_task(
                _relay_twilio_to_openai(websocket, connection, state, runtime, settings)
            )
            openai_task = asyncio.create_task(_relay_openai_to_twilio(websocket, connection, state, runtime))

            done, pending = await asyncio.wait(
                {twilio_task, openai_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc
    except WebSocketDisconnect:
        logger.info("Twilio websocket disconnected for call %s", state.call_sid)
    except Exception:
        logger.exception("Conversational phone bridge failed for call %s", state.call_sid)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

        if state.has_reportable_data():
            try:
                logger.info(
                    "Saving conversational call report for call %s with %d transcript turns",
                    state.call_sid,
                    len(state.turns),
                )
                result = await asyncio.to_thread(save_call_report, settings, state)
                if result:
                    logger.info(
                        "Saved conversational call report for call %s to %s",
                        state.call_sid,
                        result["paths"]["json_path"],
                    )
            except Exception:
                logger.exception("Failed to save conversational call report for call %s", state.call_sid)
        else:
            logger.info("No reportable call data captured for call %s; skipping report save", state.call_sid)


async def _relay_twilio_to_openai(
    websocket: WebSocket,
    connection,
    state: CallTranscript,
    runtime: RealtimeCallState,
    settings: Settings,
) -> None:
    greeted = False
    while True:
        message = await websocket.receive_text()
        payload = json.loads(message)
        event_type = payload.get("event")

        if event_type == "start":
            start = payload.get("start", {})
            state.stream_sid = payload.get("streamSid") or start.get("streamSid")
            state.call_sid = start.get("callSid")
            state.caller_number = (
                state.caller_number
                or start.get("customParameters", {}).get("caller_number")
                or start.get("from")
            )
            state.called_number = (
                state.called_number
                or start.get("customParameters", {}).get("called_number")
                or start.get("to")
            )
            if not websocket.query_params.get("line_role"):
                state.line_role = resolve_voice_line_role(state.called_number, settings)
            if not greeted:
                greeted = True
                await connection.response.create(
                    response={
                        "instructions": build_opening_instructions(state.line_role)
                    }
                )
                runtime.response_active = True
        elif event_type == "media":
            media = payload.get("media", {})
            audio = media.get("payload")
            if audio:
                await connection.input_audio_buffer.append(audio=audio)
        elif event_type == "dtmf":
            digit = payload.get("dtmf", {}).get("digit")
            if digit:
                await connection.conversation.item.create(
                    item={
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": f"Caller pressed keypad digit {digit}."}],
                    }
                )
                await connection.response.create()
                runtime.response_active = True
        elif event_type == "stop":
            return


async def _relay_openai_to_twilio(
    websocket: WebSocket,
    connection,
    state: CallTranscript,
    runtime: RealtimeCallState,
) -> None:
    async for event in connection:
        if event.type == "response.created":
            runtime.response_active = True
        if event.type == "response.output_audio.delta" and state.stream_sid:
            await websocket.send_text(
                json.dumps(
                    {
                        "event": "media",
                        "streamSid": state.stream_sid,
                        "media": {"payload": event.delta},
                    }
                )
            )
        elif event.type == "response.output_audio_transcript.done":
            state.add_turn("assistant", event.transcript)
            if should_end_reporting_call(state.line_role, event.transcript):
                runtime.should_end_call = True
        elif event.type == "response.done":
            runtime.response_active = False
            if runtime.should_end_call:
                await websocket.close()
                return
        elif event.type == "conversation.item.input_audio_transcription.completed":
            state.add_turn("caller", event.transcript)
        elif event.type == "input_audio_buffer.speech_started" and state.stream_sid:
            if runtime.response_active:
                try:
                    await connection.response.cancel()
                except Exception:
                    logger.debug("No active OpenAI response to cancel", exc_info=True)
                runtime.response_active = False
                await websocket.send_text(json.dumps({"event": "clear", "streamSid": state.stream_sid}))
        elif event.type == "error":
            error_code = getattr(event.error, "code", None)
            if error_code == "response_cancel_not_active":
                logger.debug("Ignoring non-fatal realtime cancel warning for call %s", state.call_sid)
            else:
                logger.warning("Realtime API error during call %s: %s", state.call_sid, event.error)
