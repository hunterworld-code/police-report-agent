from __future__ import annotations

import json
from typing import Any, Dict

from openai import OpenAI

from app.config import Settings
from app.schemas import REPORT_JSON_SCHEMA


class PoliceReportAgent:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    def generate_report(self, intake: Dict[str, Any]) -> Dict[str, Any]:
        prompt = (
            "You are a conservative police-report preparation assistant.\n"
            "Turn the provided scam call intake into a non-emergency, police-ready report.\n"
            "Write every string field in professional Modern Standard Arabic.\n"
            "Never present unverified claims as facts. Use Arabic wording equivalent to reported, stated, or suspected where needed.\n"
            "If data is missing, infer carefully from the transcript only when strongly supported; otherwise say the detail is unknown in Arabic.\n"
            "Focus on factual chronology, evidence preservation, and practical next steps.\n"
            "Do not advise retaliation, doxxing, hacking, or any unlawful conduct.\n"
            "Return valid JSON only."
        )

        response = self._client.responses.create(
            model=self._model,
            input=(
                f"{prompt}\n\n"
                "Scam call intake JSON:\n"
                f"{json.dumps(intake, ensure_ascii=False, default=str, indent=2)}"
            ),
            text={"format": REPORT_JSON_SCHEMA},
        )

        content = getattr(response, "output_text", None)
        if not content:
            raise ValueError("Model returned an empty report.")

        return json.loads(content)
