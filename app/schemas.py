from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ScamCallIntake(BaseModel):
    reporter_name: Optional[str] = None
    reporter_phone: Optional[str] = None
    reporter_email: Optional[str] = None
    incident_country: Optional[str] = None
    incident_city: Optional[str] = None
    call_received_at: Optional[datetime] = None
    scam_phone_number: Optional[str] = None
    suspected_scam_type: Optional[str] = None
    transcript: str = Field(..., min_length=10)
    short_notes: Optional[str] = None
    money_requested: Optional[bool] = None
    money_lost_amount: Optional[float] = None
    payment_method: Optional[str] = None
    wants_forwarding: bool = False


class ForwardingResult(BaseModel):
    attempted: bool
    sent: bool
    reason: str
    destination: Optional[str] = None
    status_code: Optional[int] = None


class EmailResult(BaseModel):
    attempted: bool
    sent: bool
    reason: str
    recipient: Optional[str] = None


class ReportFiles(BaseModel):
    json_path: str
    markdown_path: str


class ReportResponse(BaseModel):
    report: Dict[str, Any]
    files: ReportFiles
    forwarding: ForwardingResult
    email: EmailResult
    reviewed_by_ai: bool = True
    disclaimer: str


def model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


REPORT_JSON_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "name": "scam_call_police_report",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "case_title": {"type": "string"},
            "incident_summary": {"type": "string"},
            "suspected_scam_type": {"type": "string"},
            "threat_level": {
                "type": "string",
                "enum": ["low", "medium", "high"],
            },
            "should_report_to_police": {"type": "boolean"},
            "recommended_reporting_channel": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "timeline": {
                "type": "array",
                "items": {"type": "string"},
            },
            "people_and_numbers": {
                "type": "array",
                "items": {"type": "string"},
            },
            "requested_money_or_data": {
                "type": "array",
                "items": {"type": "string"},
            },
            "evidence_to_preserve": {
                "type": "array",
                "items": {"type": "string"},
            },
            "recommended_next_steps": {
                "type": "array",
                "items": {"type": "string"},
            },
            "police_narrative": {"type": "string"},
            "victim_impact": {"type": "string"},
            "legal_caution": {"type": "string"},
        },
        "required": [
            "case_title",
            "incident_summary",
            "suspected_scam_type",
            "threat_level",
            "should_report_to_police",
            "recommended_reporting_channel",
            "confidence",
            "timeline",
            "people_and_numbers",
            "requested_money_or_data",
            "evidence_to_preserve",
            "recommended_next_steps",
            "police_narrative",
            "victim_impact",
            "legal_caution",
        ],
        "additionalProperties": False,
    },
}
