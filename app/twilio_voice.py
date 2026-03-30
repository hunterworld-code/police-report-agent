from __future__ import annotations

from typing import Any, Dict, Mapping
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import Gather, VoiceResponse

from app.config import Settings
from app.realtime_call_agent import build_conversation_twiml, resolve_voice_line_role


def _request_url(request: Request, settings: Settings) -> str:
    if not settings.public_base_url:
        return str(request.url)

    base = settings.public_base_url.rstrip("/")
    return f"{base}{request.url.path}"


async def read_twilio_form(request: Request) -> Dict[str, str]:
    body = await request.body()
    parsed = parse_qsl(body.decode("utf-8"), keep_blank_values=True)
    return {key: value for key, value in parsed}


async def validate_twilio_request(request: Request, settings: Settings) -> None:
    if not settings.twilio_auth_token:
        return

    signature = request.headers.get("X-Twilio-Signature")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing Twilio signature.")

    payload = await read_twilio_form(request)
    validator = RequestValidator(settings.twilio_auth_token)
    if not validator.validate(_request_url(request, settings), payload, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature.")


def incoming_call_twiml(
    settings: Settings,
    caller_number: str | None = None,
    called_number: str | None = None,
) -> str:
    line_role = resolve_voice_line_role(called_number, settings)
    if settings.twilio_voice_mode.strip().lower() == "conversation":
        return build_conversation_twiml(
            settings,
            caller_number=caller_number,
            called_number=called_number,
            line_role=line_role,
        )

    response = VoiceResponse()
    gather = Gather(
        input="speech",
        action="/twilio/voice/process-speech",
        method="POST",
        speech_timeout="auto",
        timeout=4,
        action_on_empty_result=True,
        language=settings.twilio_gather_language,
    )
    if line_role == "reporting":
        gather.say(
            "السلام عليكم، معاك مساعد بلاغات الاحتيال. "
            "بعد النغمة، تفضل خبرني باختصار شو صار، واذكر رقم المحتال إذا تعرفه، "
            "وشو كان يبا منك، وهل خسرت أي مبلغ. "
            "إذا كان في خطر فوري، سكر الخط واتصل بخدمات الطوارئ فوراً.",
            language="ar-SA",
        )
    else:
        gather.say(
            "السلام عليكم، تفضل قل اسمك وسبب اتصالك بعد النغمة.",
            language="ar-SA",
        )
    response.append(gather)
    response.say(
        "تعذر التقاط البلاغ. يرجى الاتصال مرة أخرى عندما تكون جاهزاً، أو استخدم النموذج الإلكتروني.",
        language="ar-SA",
    )
    response.hangup()
    return str(response)


def report_result_twiml(report: Mapping[str, Any], files: Mapping[str, str]) -> str:
    response = VoiceResponse()
    response.say(
        "تم حفظ بلاغ مكالمة الاحتيال الخاصة بك.",
        language="ar-SA",
    )
    response.say(
        (
            f"مستوى التهديد هو {report.get('threat_level', 'غير معروف')}. "
            f"{'يُنصح برفع البلاغ إلى الشرطة.' if report.get('should_report_to_police') else 'يرجى مراجعة التقرير قبل اتخاذ قرار التواصل مع الشرطة.'}"
        ),
        language="ar-SA",
    )
    next_steps = report.get("recommended_next_steps") or []
    if next_steps:
        response.say(f"الخطوة التالية المقترحة: {next_steps[0]}", language="ar-SA")
    response.say("أصبح التقرير المكتوب متاحاً الآن داخل النظام للمراجعة.", language="ar-SA")
    response.hangup()
    return str(response)


def error_twiml(message: str) -> str:
    response = VoiceResponse()
    response.say(message)
    response.hangup()
    return str(response)


def no_speech_twiml() -> str:
    response = VoiceResponse()
    response.say(
        "تعذر التقاط البلاغ الصوتي. يرجى الاتصال مرة أخرى والتحدث بوضوح بعد النغمة، "
        "أو استخدم النموذج الإلكتروني بدلاً من ذلك.",
        language="ar-SA",
    )
    response.hangup()
    return str(response)


def build_twilio_intake(
    form_data: Mapping[str, Any],
    settings: Settings,
) -> Dict[str, Any]:
    speech_result = str(form_data.get("SpeechResult", "")).strip()
    caller_number = str(form_data.get("From", "")).strip() or None
    call_sid = str(form_data.get("CallSid", "")).strip() or None
    confidence_raw = str(form_data.get("Confidence", "")).strip()
    confidence_note = f"Speech confidence: {confidence_raw}" if confidence_raw else None

    notes = []
    if call_sid:
        notes.append(f"Twilio CallSid: {call_sid}")
    if confidence_note:
        notes.append(confidence_note)

    return {
        "reporter_name": None,
        "reporter_phone": caller_number,
        "reporter_email": None,
        "incident_country": settings.twilio_default_country,
        "incident_city": settings.twilio_default_city,
        "call_received_at": None,
        "scam_phone_number": None,
        "suspected_scam_type": "Phone scam reported by inbound call",
        "transcript": speech_result,
        "short_notes": " | ".join(notes) if notes else None,
        "money_requested": None,
        "money_lost_amount": None,
        "payment_method": None,
        "wants_forwarding": settings.twilio_auto_forward_reports,
    }


def build_whatsapp_intake(
    form_data: Mapping[str, Any],
    settings: Settings,
) -> Dict[str, Any]:
    body = str(form_data.get("Body", "")).strip()
    sender = str(form_data.get("From", "")).strip() or None
    wa_sid = str(form_data.get("MessageSid", "")).strip() or None
    num_media = str(form_data.get("NumMedia", "")).strip() or "0"
    media_url = str(form_data.get("MediaUrl0", "")).strip() or None

    notes = []
    if wa_sid:
        notes.append(f"Twilio MessageSid: {wa_sid}")
    if num_media and num_media != "0":
        notes.append(f"عدد المرفقات: {num_media}")
    if media_url:
        notes.append(f"رابط أول مرفق: {media_url}")

    return {
        "reporter_name": None,
        "reporter_phone": sender,
        "reporter_email": None,
        "incident_country": settings.twilio_default_country,
        "incident_city": settings.twilio_default_city,
        "call_received_at": None,
        "scam_phone_number": None,
        "suspected_scam_type": "بلاغ احتيال وارد عبر واتساب",
        "transcript": body,
        "short_notes": " | ".join(notes) if notes else None,
        "money_requested": None,
        "money_lost_amount": None,
        "payment_method": None,
        "wants_forwarding": settings.twilio_auto_forward_reports,
    }


def whatsapp_success_twiml(report: Mapping[str, Any], paths: Mapping[str, str]) -> str:
    response = MessagingResponse()
    response.message(
        "تم استلام البلاغ عبر واتساب وإنشاء تقرير مهني باللغة العربية.\n"
        f"عنوان التقرير: {report.get('case_title', 'غير متوفر')}\n"
        f"الملف المحلي: {paths.get('markdown_path', '')}\n"
        "إذا كنت ترغب بإضافة تفاصيل أخرى، أرسلها في رسالة جديدة."
    )
    return str(response)


def whatsapp_chat_twiml(message: str, media_url: str | None = None) -> str:
    response = MessagingResponse()
    reply = response.message(message)
    if media_url:
        reply.media(media_url)
    return str(response)


def whatsapp_error_twiml(message: str) -> str:
    response = MessagingResponse()
    response.message(message)
    return str(response)
