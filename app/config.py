from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    police_report_webhook_url: str | None
    auto_forward_reports: bool
    webhook_auth_header_name: str | None
    webhook_auth_header_value: str | None
    report_storage_dir: Path
    public_base_url: str | None = None
    twilio_agent_phone_number: str | None = None
    twilio_reporting_phone_number: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_default_country: str | None = None
    twilio_default_city: str | None = None
    twilio_gather_language: str = "ar-SA"
    twilio_auto_forward_reports: bool = False
    twilio_voice_mode: str = "conversation"
    twilio_realtime_model: str = "gpt-realtime-mini"
    twilio_transcription_model: str = "gpt-4o-mini-transcribe"
    twilio_agent_voice: str = "marin"
    twilio_agent_language: str = "ar"
    twilio_agent_speed: float = 1.0
    whatsapp_chat_model: str = "gpt-5.4-mini"
    auto_whatsapp_reports: bool = False
    whatsapp_from_number: str | None = None
    whatsapp_report_to_number: str | None = None
    report_language: str = "ar"
    auto_email_reports: bool = True
    email_to_address: str = "hunterworld@gmail.com"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True


def get_settings() -> Settings:
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        police_report_webhook_url=os.getenv("POLICE_REPORT_WEBHOOK_URL"),
        auto_forward_reports=_parse_bool(os.getenv("AUTO_FORWARD_REPORTS"), default=False),
        webhook_auth_header_name=os.getenv("WEBHOOK_AUTH_HEADER_NAME"),
        webhook_auth_header_value=os.getenv("WEBHOOK_AUTH_HEADER_VALUE"),
        report_storage_dir=Path(os.getenv("REPORT_STORAGE_DIR", "reports")),
        public_base_url=os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL"),
        twilio_agent_phone_number=os.getenv("TWILIO_AGENT_PHONE_NUMBER"),
        twilio_reporting_phone_number=os.getenv("TWILIO_REPORTING_PHONE_NUMBER"),
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
        twilio_default_country=os.getenv("TWILIO_DEFAULT_COUNTRY"),
        twilio_default_city=os.getenv("TWILIO_DEFAULT_CITY"),
        twilio_gather_language=os.getenv("TWILIO_GATHER_LANGUAGE", "ar-SA"),
        twilio_auto_forward_reports=_parse_bool(os.getenv("TWILIO_AUTO_FORWARD_REPORTS"), default=False),
        twilio_voice_mode=os.getenv("TWILIO_VOICE_MODE", "conversation"),
        twilio_realtime_model=os.getenv("TWILIO_REALTIME_MODEL", "gpt-realtime-mini"),
        twilio_transcription_model=os.getenv("TWILIO_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"),
        twilio_agent_voice=os.getenv("TWILIO_AGENT_VOICE", "marin"),
        twilio_agent_language=os.getenv("TWILIO_AGENT_LANGUAGE", "ar"),
        twilio_agent_speed=float(os.getenv("TWILIO_AGENT_SPEED", "1.0")),
        whatsapp_chat_model=os.getenv("WHATSAPP_CHAT_MODEL", "gpt-5.4-mini"),
        auto_whatsapp_reports=_parse_bool(os.getenv("AUTO_WHATSAPP_REPORTS"), default=False),
        whatsapp_from_number=os.getenv("WHATSAPP_FROM_NUMBER"),
        whatsapp_report_to_number=os.getenv("WHATSAPP_REPORT_TO_NUMBER"),
        report_language=os.getenv("REPORT_LANGUAGE", "ar"),
        auto_email_reports=_parse_bool(os.getenv("AUTO_EMAIL_REPORTS"), default=True),
        email_to_address=os.getenv("EMAIL_TO_ADDRESS", "hunterworld@gmail.com"),
        smtp_host=os.getenv("SMTP_HOST"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME"),
        smtp_password=os.getenv("SMTP_PASSWORD"),
        smtp_from_email=os.getenv("SMTP_FROM_EMAIL"),
        smtp_use_tls=_parse_bool(os.getenv("SMTP_USE_TLS"), default=True),
    )
