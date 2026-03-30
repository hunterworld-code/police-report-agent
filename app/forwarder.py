from __future__ import annotations

from typing import Any, Dict

import httpx

from app.config import Settings


def forward_report(
    settings: Settings,
    intake: Dict[str, Any],
    report: Dict[str, Any],
) -> Dict[str, Any]:
    if not intake.get("wants_forwarding"):
        return {
            "attempted": False,
            "sent": False,
            "reason": "Forwarding not requested in this intake.",
            "destination": settings.police_report_webhook_url,
            "status_code": None,
        }

    if not settings.auto_forward_reports:
        return {
            "attempted": False,
            "sent": False,
            "reason": "AUTO_FORWARD_REPORTS is disabled.",
            "destination": settings.police_report_webhook_url,
            "status_code": None,
        }

    if not settings.police_report_webhook_url:
        return {
            "attempted": False,
            "sent": False,
            "reason": "POLICE_REPORT_WEBHOOK_URL is not configured.",
            "destination": None,
            "status_code": None,
        }

    if not report.get("should_report_to_police"):
        return {
            "attempted": False,
            "sent": False,
            "reason": "AI review did not recommend forwarding this report to police.",
            "destination": settings.police_report_webhook_url,
            "status_code": None,
        }

    headers = {"Content-Type": "application/json"}
    if settings.webhook_auth_header_name and settings.webhook_auth_header_value:
        headers[settings.webhook_auth_header_name] = settings.webhook_auth_header_value

    payload = {
        "source": "scam-call-police-agent",
        "intake": intake,
        "report": report,
    }

    try:
        response = httpx.post(
            settings.police_report_webhook_url,
            json=payload,
            headers=headers,
            timeout=20.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        return {
            "attempted": True,
            "sent": False,
            "reason": f"Forwarding failed: {exc}",
            "destination": settings.police_report_webhook_url,
            "status_code": status_code,
        }

    return {
        "attempted": True,
        "sent": True,
        "reason": "Report forwarded successfully.",
        "destination": settings.police_report_webhook_url,
        "status_code": response.status_code,
    }
