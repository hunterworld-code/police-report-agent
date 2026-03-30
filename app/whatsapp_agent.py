from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from app.agent import PoliceReportAgent
from app.config import Settings
from app.emailer import send_report_email
from app.forwarder import forward_report
from app.storage import build_public_report_file_url, ensure_storage_dir, save_report_bundle


WHATSAPP_ASSISTANT_PROMPT = """
أنت مساعد بلاغات احتيال عبر واتساب، وتتحدث بالعربية الفصحى المهنية بطريقة إنسانية ومطمئنة.
مهمتك أن تتحاور مع المستخدم، تجمع المعلومات الأساسية عن واقعة الاحتيال، وتجيب عن أسئلته بإيجاز ووضوح.

قواعد العمل:
- تحدث بالعربية فقط.
- كن ودوداً ومهنياً ومباشراً.
- اسأل سؤالاً رئيسياً واحداً في كل مرة.
- اجمع عند الإمكان: رقم المحتال، ما الذي قاله، ما الذي طلبه، هل تم إرسال مال أو بيانات، هل توجد خسارة مالية، ما وسيلة الدفع، ومتى حدثت الواقعة.
- إذا سأل المستخدم ماذا يفعل، فاقترح خطوات آمنة مثل التواصل مع البنك، حفظ الأدلة، وعدم مشاركة كلمات المرور أو رموز التحقق.
- لا تقدم وعوداً قانونية أو نصائح انتقامية أو تعليمات غير قانونية.
- إذا بدا أن المستخدم في خطر فوري، أخبره بالتواصل مع الطوارئ فوراً.
- عندما يبدو أن المستخدم أعطى معظم التفاصيل، ذكّره أنه يمكنه كتابة كلمة "تم" أو "أرسل التقرير" ليتم إعداد التقرير النهائي.
""".strip()

FINALIZE_PATTERNS = [
    r"\bتم\b",
    r"انتهيت",
    r"أرسل التقرير",
    r"ارسل التقرير",
    r"ارسال التقرير",
    r"send report",
    r"finish",
    r"done",
]


@dataclass
class WhatsAppTurn:
    role: str
    text: str
    created_at: str


@dataclass
class WhatsAppSession:
    sender: str
    last_response_id: Optional[str] = None
    turns: List[WhatsAppTurn] = field(default_factory=list)
    last_report_paths: Dict[str, str] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def transcript_text(self) -> str:
        return "\n".join(f"{turn.role}: {turn.text}" for turn in self.turns)


class WhatsAppChatAgent:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.whatsapp_chat_model

    def reply(self, session: WhatsAppSession, user_message: str) -> tuple[str, str]:
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "instructions": WHATSAPP_ASSISTANT_PROMPT,
            "input": user_message,
        }
        if session.last_response_id:
            kwargs["previous_response_id"] = session.last_response_id

        response = self._client.responses.create(**kwargs)
        reply_text = getattr(response, "output_text", None)
        if not reply_text:
            raise ValueError("Model returned an empty WhatsApp reply.")
        return reply_text.strip(), response.id


def handle_whatsapp_message(settings: Settings, form_data: Dict[str, str]) -> Dict[str, Any]:
    sender = str(form_data.get("From", "")).strip()
    body = str(form_data.get("Body", "")).strip()
    if not sender or not body:
        raise ValueError("WhatsApp sender and message body are required.")

    session = load_whatsapp_session(settings, sender)
    session.turns.append(
        WhatsAppTurn(
            role="user",
            text=body,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )

    agent = WhatsAppChatAgent(settings)
    reply_text, response_id = agent.reply(session, body)
    session.turns.append(
        WhatsAppTurn(
            role="assistant",
            text=reply_text,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )
    session.last_response_id = response_id
    session.updated_at = datetime.now(timezone.utc).isoformat()

    finalized = should_finalize_report(body)
    report_result = None
    if finalized:
        report_result = generate_whatsapp_report(settings, session)
        status_line = "تم إعداد التقرير النهائي."
        if report_result["media_url"]:
            status_line += " وتم إرفاق نسخة PDF على واتساب."
        if report_result["email"]["sent"]:
            status_line += " وتم إرسال نسخة إلى البريد الإلكتروني المطلوب."
        elif report_result["email"]["attempted"]:
            status_line += f" وتعذر إرسال البريد الإلكتروني: {report_result['email']['reason']}"
        else:
            status_line += " ولم يتم إرسال البريد الإلكتروني لأن إعدادات SMTP غير مكتملة."
        reply_text = f"{reply_text}\n\n{status_line}"
    else:
        reply_text = f"{reply_text}\n\nإذا انتهيت من إرسال التفاصيل، اكتب: تم"

    save_whatsapp_session(settings, session)
    return {
        "reply_text": reply_text,
        "session": session,
        "report_result": report_result,
        "media_url": report_result["media_url"] if report_result else None,
    }


def generate_whatsapp_report(settings: Settings, session: WhatsAppSession) -> Dict[str, Any]:
    intake = {
        "reporter_name": None,
        "reporter_phone": session.sender,
        "reporter_email": None,
        "incident_country": settings.twilio_default_country,
        "incident_city": settings.twilio_default_city,
        "call_received_at": datetime.now(timezone.utc).isoformat(),
        "scam_phone_number": None,
        "suspected_scam_type": "بلاغ احتيال عبر واتساب",
        "transcript": session.transcript_text(),
        "short_notes": "تم جمع المعلومات من محادثة واتساب متعددة الرسائل.",
        "money_requested": None,
        "money_lost_amount": None,
        "payment_method": None,
        "wants_forwarding": settings.twilio_auto_forward_reports,
    }
    agent = PoliceReportAgent(settings)
    report = agent.generate_report(intake)
    paths = save_report_bundle(settings.report_storage_dir, intake, report)
    forwarding = forward_report(settings, intake, report)
    email = send_report_email(settings, intake, report, paths)
    media_url = build_public_report_file_url(settings.public_base_url, paths["pdf_path"])
    session.last_report_paths = paths
    return {
        "report": report,
        "paths": paths,
        "forwarding": forwarding,
        "email": email,
        "media_url": media_url,
    }


def should_finalize_report(text: str) -> bool:
    lowered = text.strip().lower()
    return any(re.search(pattern, lowered) for pattern in FINALIZE_PATTERNS)


def load_whatsapp_session(settings: Settings, sender: str) -> WhatsAppSession:
    path = _session_path(settings, sender)
    if not path.exists():
        return WhatsAppSession(sender=sender)

    payload = json.loads(path.read_text(encoding="utf-8"))
    turns = [WhatsAppTurn(**turn) for turn in payload.get("turns", [])]
    return WhatsAppSession(
        sender=payload["sender"],
        last_response_id=payload.get("last_response_id"),
        turns=turns,
        last_report_paths=payload.get("last_report_paths", {}),
        updated_at=payload.get("updated_at", datetime.now(timezone.utc).isoformat()),
    )


def save_whatsapp_session(settings: Settings, session: WhatsAppSession) -> None:
    path = _session_path(settings, session.sender)
    ensure_storage_dir(path.parent)
    path.write_text(
        json.dumps(
            {
                "sender": session.sender,
                "last_response_id": session.last_response_id,
                "turns": [asdict(turn) for turn in session.turns],
                "last_report_paths": session.last_report_paths,
                "updated_at": session.updated_at,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _session_path(settings: Settings, sender: str) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9]+", "_", sender).strip("_") or "unknown_sender"
    return settings.report_storage_dir / "whatsapp_sessions" / f"{safe_name}.json"
