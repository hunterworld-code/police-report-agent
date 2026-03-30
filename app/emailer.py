from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict

from app.config import Settings


def send_report_email(
    settings: Settings,
    intake: Dict[str, Any],
    report: Dict[str, Any],
    paths: Dict[str, str],
) -> Dict[str, Any]:
    if not settings.auto_email_reports:
        return {
            "attempted": False,
            "sent": False,
            "reason": "AUTO_EMAIL_REPORTS is disabled.",
            "recipient": settings.email_to_address,
        }

    required = [
        settings.smtp_host,
        settings.smtp_username,
        settings.smtp_password,
        settings.smtp_from_email,
        settings.email_to_address,
    ]
    if not all(required):
        return {
            "attempted": False,
            "sent": False,
            "reason": "SMTP settings are incomplete.",
            "recipient": settings.email_to_address,
        }

    subject = report.get("case_title") or "تقرير بلاغ احتيال هاتفي"
    body = _build_email_body(intake, report, paths)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_email
    message["To"] = settings.email_to_address
    message.set_content(body)

    for key in ("pdf_path", "markdown_path", "json_path"):
        file_path = Path(paths[key])
        if file_path.exists():
            if file_path.suffix == ".pdf":
                subtype = "pdf"
            elif file_path.suffix == ".md":
                subtype = "markdown"
            else:
                subtype = "json"
            message.add_attachment(
                file_path.read_bytes(),
                maintype="application",
                subtype=subtype,
                filename=file_path.name,
            )

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            if settings.smtp_use_tls:
                server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    except Exception as exc:
        return {
            "attempted": True,
            "sent": False,
            "reason": f"Email delivery failed: {exc}",
            "recipient": settings.email_to_address,
        }

    return {
        "attempted": True,
        "sent": True,
        "reason": "Report emailed successfully.",
        "recipient": settings.email_to_address,
    }


def _build_email_body(intake: Dict[str, Any], report: Dict[str, Any], paths: Dict[str, str]) -> str:
    return "\n".join(
        [
            "السلام عليكم،",
            "",
            "تم إنشاء تقرير مهني باللغة العربية بشأن بلاغ احتيال هاتفي، وتم إرفاق نسخ PDF وMarkdown وJSON مع هذه الرسالة.",
            "",
            f"عنوان التقرير: {report.get('case_title', 'غير متوفر')}",
            f"ملخص الحادث: {report.get('incident_summary', 'غير متوفر')}",
            f"نوع الاحتيال المشتبه به: {report.get('suspected_scam_type', 'غير متوفر')}",
            f"رقم المبلغ: {intake.get('reporter_phone') or 'غير متوفر'}",
            f"رقم المتصل المحتال: {intake.get('scam_phone_number') or 'غير متوفر'}",
            "",
            "مسارات الملفات المحلية:",
            f"- {paths.get('pdf_path', '')}",
            f"- {paths.get('markdown_path', '')}",
            f"- {paths.get('json_path', '')}",
            "",
            "هذه الرسالة أُرسلت تلقائياً من نظام بلاغات الاحتيال الهاتفي.",
        ]
    )
