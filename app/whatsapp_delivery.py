from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from twilio.rest import Client

from app.config import Settings
from app.storage import build_public_report_file_url


def _normalize_whatsapp_number(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.startswith("whatsapp:"):
        return cleaned
    return f"whatsapp:{cleaned}"


def send_report_whatsapp(
    settings: Settings,
    intake: Dict[str, Any],
    report: Dict[str, Any],
    paths: Dict[str, str],
) -> Dict[str, Any]:
    if not settings.auto_whatsapp_reports:
        return {
            "attempted": False,
            "sent": False,
            "reason": "AUTO_WHATSAPP_REPORTS is disabled.",
            "recipient": _normalize_whatsapp_number(settings.whatsapp_report_to_number),
            "message_sid": None,
            "media_url": None,
        }

    sender = _normalize_whatsapp_number(settings.whatsapp_from_number)
    recipient = _normalize_whatsapp_number(settings.whatsapp_report_to_number)
    required = [
        settings.twilio_account_sid,
        settings.twilio_auth_token,
        sender,
        recipient,
    ]
    if not all(required):
        return {
            "attempted": False,
            "sent": False,
            "reason": "WhatsApp delivery settings are incomplete.",
            "recipient": recipient,
            "message_sid": None,
            "media_url": None,
        }

    media_url = None
    pdf_path = paths.get("pdf_path")
    if pdf_path and Path(pdf_path).exists():
        media_url = build_public_report_file_url(settings.public_base_url, pdf_path)

    body = "\n".join(
        [
            "تم إعداد تقرير الاحتيال.",
            f"عنوان التقرير: {report.get('case_title', 'غير متوفر')}",
            f"ملخص مختصر: {report.get('incident_summary', 'غير متوفر')}",
            "تم إرسال نسخة إلى بريدك الإلكتروني إذا كانت إعدادات البريد مكتملة.",
        ]
    )

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    message_kwargs: Dict[str, Any] = {
        "from_": sender,
        "to": recipient,
        "body": body,
    }
    if media_url:
        message_kwargs["media_url"] = [media_url]

    try:
        message = client.messages.create(**message_kwargs)
    except Exception as exc:
        return {
            "attempted": True,
            "sent": False,
            "reason": f"WhatsApp delivery failed: {exc}",
            "recipient": recipient,
            "message_sid": None,
            "media_url": media_url,
        }

    return {
        "attempted": True,
        "sent": True,
        "reason": "Report sent over WhatsApp successfully.",
        "recipient": recipient,
        "message_sid": getattr(message, "sid", None),
        "media_url": media_url,
    }
