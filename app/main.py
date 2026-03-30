from __future__ import annotations

from pathlib import Path

import openai
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.agent import PoliceReportAgent
from app.config import get_settings
from app.emailer import send_report_email
from app.forwarder import forward_report
from app.schemas import EmailResult, ForwardingResult, ReportFiles, ReportResponse, ScamCallIntake, model_to_dict
from app.storage import quote_filename, save_report_bundle
from app.realtime_call_agent import run_conversational_call
from app.twilio_voice import (
    build_twilio_intake,
    error_twiml,
    incoming_call_twiml,
    no_speech_twiml,
    read_twilio_form,
    report_result_twiml,
    validate_twilio_request,
    whatsapp_chat_twiml,
    whatsapp_error_twiml,
)
from app.whatsapp_agent import handle_whatsapp_message


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="Scam Call Police Reporting Agent",
    description=(
        "Converts scam-call details into a structured, police-ready report and can "
        "optionally forward that report to a configured non-emergency webhook."
    ),
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _friendly_openai_error(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, openai.AuthenticationError):
        return (
            401,
            "The OpenAI API key was rejected. Add a valid key to .env and restart the server.",
        )

    if isinstance(exc, openai.RateLimitError):
        error_code = None
        if isinstance(getattr(exc, "body", None), dict):
            error_code = exc.body.get("error", {}).get("code")

        if error_code == "insufficient_quota":
            return (
                503,
                "The OpenAI account connected to this API key has no available quota. Check billing and usage, then try again.",
            )

        return (
            429,
            "The OpenAI API rate limit was reached. Wait a moment and try again.",
        )

    if isinstance(exc, openai.BadRequestError):
        return (
            400,
            "OpenAI rejected the request. Check OPENAI_MODEL and the submitted report details, then try again.",
        )

    if isinstance(exc, openai.APIStatusError):
        return (
            502,
            "OpenAI returned an unexpected API error. Try again shortly or review the server configuration.",
        )

    return (500, f"Failed to build report: {exc}")


def _generate_report_bundle(settings, intake_data):
    agent = PoliceReportAgent(settings)
    report = agent.generate_report(intake_data)
    paths = save_report_bundle(settings.report_storage_dir, intake_data, report)
    forwarding = forward_report(settings, intake_data, report)
    email = send_report_email(settings, intake_data, report, paths)
    return report, paths, forwarding, email


def _resolve_report_file_path(settings, filename: str) -> Path:
    safe_name = quote_filename(filename)
    file_path = settings.report_storage_dir / safe_name
    if file_path.suffix.lower() not in {".pdf", ".md", ".json"} or not file_path.exists():
        raise HTTPException(status_code=404, detail="Report file not found.")
    return file_path


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "model": settings.openai_model,
        "auto_forward_reports": settings.auto_forward_reports,
        "webhook_configured": bool(settings.police_report_webhook_url),
        "twilio_voice_mode": settings.twilio_voice_mode,
        "twilio_agent_phone_number": settings.twilio_agent_phone_number,
        "twilio_reporting_phone_number": settings.twilio_reporting_phone_number,
        "email_reports_enabled": settings.auto_email_reports,
        "email_recipient": settings.email_to_address,
    }


@app.post("/reports", response_model=ReportResponse)
def create_report(intake: ScamCallIntake) -> ReportResponse:
    settings = get_settings()

    try:
        intake_data = model_to_dict(intake)
        report, paths, forwarding, email = _generate_report_bundle(settings, intake_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except openai.OpenAIError as exc:
        status_code, detail = _friendly_openai_error(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build report: {exc}") from exc

    return ReportResponse(
        report=report,
        files=ReportFiles(**paths),
        forwarding=ForwardingResult(**forwarding),
        email=EmailResult(**email),
        disclaimer=(
            "هذا النظام يُعد مواد بلاغ غير طارئ. يُرجى مراجعة التقرير قبل إرساله، والاتصال بخدمات الطوارئ مباشرة عند وجود خطر فوري."
        ),
    )


@app.get("/reports/files/{filename}", include_in_schema=False)
def get_report_file(filename: str) -> FileResponse:
    settings = get_settings()
    file_path = _resolve_report_file_path(settings, filename)
    media_types = {
        ".pdf": "application/pdf",
        ".md": "text/markdown; charset=utf-8",
        ".json": "application/json",
    }
    return FileResponse(file_path, media_type=media_types[file_path.suffix.lower()], filename=file_path.name)


@app.api_route("/twilio/voice/incoming", methods=["GET", "POST"], include_in_schema=False)
async def twilio_voice_incoming(request: Request):
    settings = get_settings()
    caller_number = None
    called_number = None
    if request.method == "POST":
        await validate_twilio_request(request, settings)
        form_data = await read_twilio_form(request)
        caller_number = str(form_data.get("From", "")).strip() or None
        called_number = str(form_data.get("To", "")).strip() or None
    try:
        twiml = incoming_call_twiml(
            settings,
            caller_number=caller_number,
            called_number=called_number,
        )
    except ValueError as exc:
        twiml = error_twiml(str(exc))
    return Response(content=twiml, media_type="application/xml")


@app.api_route("/twilio/voice/process-speech", methods=["POST"], include_in_schema=False)
async def twilio_voice_process_speech(request: Request):
    settings = get_settings()
    await validate_twilio_request(request, settings)
    form_data = await read_twilio_form(request)
    transcript = str(form_data.get("SpeechResult", "")).strip()
    if not transcript:
        return Response(content=no_speech_twiml(), media_type="application/xml")

    intake_data = build_twilio_intake(form_data, settings)

    try:
        report, paths, _forwarding, _email = _generate_report_bundle(settings, intake_data)
    except ValueError:
        return Response(
            content=error_twiml(
                "The reporting agent is not configured yet. Please ask the administrator to add the OpenAI API key or use the web form."
            ),
            media_type="application/xml",
        )
    except openai.OpenAIError as exc:
        _status_code, detail = _friendly_openai_error(exc)
        return Response(
            content=error_twiml(detail),
            media_type="application/xml",
        )

    return Response(content=report_result_twiml(report, paths), media_type="application/xml")


@app.api_route("/twilio/whatsapp/incoming", methods=["POST"], include_in_schema=False)
async def twilio_whatsapp_incoming(request: Request):
    settings = get_settings()
    await validate_twilio_request(request, settings)
    form_data = await read_twilio_form(request)
    body = str(form_data.get("Body", "")).strip()
    if not body:
        return Response(
            content=whatsapp_error_twiml("تعذر استلام نص البلاغ. يرجى إرسال وصف مكتوب لواقعة الاحتيال."),
            media_type="application/xml",
        )

    try:
        result = handle_whatsapp_message(settings, form_data)
        reply_text = result["reply_text"]
        media_url = result.get("media_url")
    except ValueError:
        return Response(
            content=whatsapp_error_twiml("النظام غير مهيأ حالياً. يرجى المحاولة لاحقاً."),
            media_type="application/xml",
        )
    except openai.OpenAIError as exc:
        _status_code, detail = _friendly_openai_error(exc)
        return Response(
            content=whatsapp_error_twiml(f"تعذر إنشاء التقرير حالياً: {detail}"),
            media_type="application/xml",
        )

    return Response(content=whatsapp_chat_twiml(reply_text, media_url=media_url), media_type="application/xml")


@app.websocket("/twilio/voice/media-stream")
async def twilio_voice_media_stream(websocket: WebSocket):
    settings = get_settings()
    await run_conversational_call(websocket, settings)
