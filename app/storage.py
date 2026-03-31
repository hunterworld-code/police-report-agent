from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


ARABIC_FONT_CANDIDATES = [
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
]
REGISTERED_PDF_FONT = "ScamReportArabic"


def ensure_storage_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _contains_arabic(text: str) -> bool:
    return any("\u0600" <= char <= "\u08ff" for char in text)


def _shape_for_pdf(text: str) -> str:
    if not text:
        return ""
    if _contains_arabic(text):
        return get_display(arabic_reshaper.reshape(text))
    return text


def _ensure_pdf_font() -> str:
    if REGISTERED_PDF_FONT in pdfmetrics.getRegisteredFontNames():
        return REGISTERED_PDF_FONT

    for candidate in ARABIC_FONT_CANDIDATES:
        if candidate.exists():
            pdfmetrics.registerFont(TTFont(REGISTERED_PDF_FONT, str(candidate)))
            return REGISTERED_PDF_FONT

    raise FileNotFoundError("No supported Arabic PDF font was found on this machine.")


def _paragraph_html(text: str) -> str:
    lines = [escape(line) for line in text.splitlines() if line.strip()]
    return "<br/>".join(lines) if lines else "&nbsp;"


def _transcript_html(text: str) -> str:
    rendered_lines: list[str] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        speaker, separator, remainder = raw_line.partition(":")
        if separator:
            speaker_html = escape(f"{speaker}{separator}")
            remainder_text = remainder.lstrip()
            if _contains_arabic(remainder_text):
                shaped_remainder = escape(_shape_for_pdf(remainder_text))
            else:
                shaped_remainder = escape(remainder_text)
            rendered_lines.append(f"{speaker_html} {shaped_remainder}".rstrip())
            continue

        rendered_lines.append(escape(_shape_for_pdf(raw_line) if _contains_arabic(raw_line) else raw_line))

    return "<br/>".join(rendered_lines) if rendered_lines else "&nbsp;"


def _section_items(intake: Dict[str, Any], report: Dict[str, Any]) -> list[tuple[str, list[str], bool]]:
    return [
        (
            "بيانات البلاغ",
            [
                f"اسم المبلغ: {intake.get('reporter_name') or 'غير معروف'}",
                f"هاتف المبلغ: {intake.get('reporter_phone') or 'غير معروف'}",
                f"بريد المبلغ الإلكتروني: {intake.get('reporter_email') or 'غير معروف'}",
                f"دولة الواقعة: {intake.get('incident_country') or 'غير معروف'}",
                f"مدينة الواقعة: {intake.get('incident_city') or 'غير معروف'}",
                f"وقت المكالمة: {intake.get('call_received_at') or 'غير معروف'}",
                f"رقم المشتبه به: {intake.get('scam_phone_number') or 'غير معروف'}",
            ],
            False,
        ),
        ("الملخص", [report["incident_summary"]], False),
        ("السرد الموجز للشرطة", [report["police_narrative"]], False),
        (
            "تقييم الخطورة",
            [
                f"نوع الاحتيال المشتبه به: {report['suspected_scam_type']}",
                f"مستوى الخطورة: {report['threat_level']}",
                f"هل يُنصح بإبلاغ الشرطة: {report['should_report_to_police']}",
                f"قناة الإبلاغ المقترحة: {report['recommended_reporting_channel']}",
                f"درجة الثقة: {report['confidence']}",
            ],
            False,
        ),
        ("التسلسل الزمني", report.get("timeline") or ["لا توجد بيانات مسجلة"], False),
        ("الأشخاص والأرقام", report.get("people_and_numbers") or ["لا توجد بيانات مسجلة"], False),
        ("الأموال أو البيانات المطلوبة", report.get("requested_money_or_data") or ["لا توجد بيانات مسجلة"], False),
        ("الأدلة الواجب حفظها", report.get("evidence_to_preserve") or ["لا توجد بيانات مسجلة"], False),
        ("الخطوات الموصى بها", report.get("recommended_next_steps") or ["لا توجد بيانات مسجلة"], False),
        ("أثر الواقعة على المبلغ", [report["victim_impact"]], False),
        ("تنبيه قانوني", [report["legal_caution"]], False),
        ("النص الأصلي للمكالمة", [intake["transcript"]], True),
        ("ملاحظات", [intake.get("short_notes") or "لا توجد ملاحظات إضافية."], False),
    ]


def render_markdown(intake: Dict[str, Any], report: Dict[str, Any]) -> str:
    def block(items: Any) -> str:
        if not items:
            return "- لا توجد بيانات مسجلة"
        return "\n".join(f"- {item}" for item in items)

    lines = [
        f"# {report['case_title']}",
        "",
        "## بيانات البلاغ",
        f"- اسم المبلغ: {intake.get('reporter_name') or 'غير معروف'}",
        f"- هاتف المبلغ: {intake.get('reporter_phone') or 'غير معروف'}",
        f"- بريد المبلغ الإلكتروني: {intake.get('reporter_email') or 'غير معروف'}",
        f"- دولة الواقعة: {intake.get('incident_country') or 'غير معروف'}",
        f"- مدينة الواقعة: {intake.get('incident_city') or 'غير معروف'}",
        f"- وقت المكالمة: {intake.get('call_received_at') or 'غير معروف'}",
        f"- رقم المشتبه به: {intake.get('scam_phone_number') or 'غير معروف'}",
        "",
        "## الملخص",
        report["incident_summary"],
        "",
        "## السرد الموجز للشرطة",
        report["police_narrative"],
        "",
        "## تقييم الخطورة",
        f"- نوع الاحتيال المشتبه به: {report['suspected_scam_type']}",
        f"- مستوى الخطورة: {report['threat_level']}",
        f"- هل يُنصح بإبلاغ الشرطة: {report['should_report_to_police']}",
        f"- قناة الإبلاغ المقترحة: {report['recommended_reporting_channel']}",
        f"- درجة الثقة: {report['confidence']}",
        "",
        "## التسلسل الزمني",
        block(report.get("timeline")),
        "",
        "## الأشخاص والأرقام",
        block(report.get("people_and_numbers")),
        "",
        "## الأموال أو البيانات المطلوبة",
        block(report.get("requested_money_or_data")),
        "",
        "## الأدلة الواجب حفظها",
        block(report.get("evidence_to_preserve")),
        "",
        "## الخطوات الموصى بها",
        block(report.get("recommended_next_steps")),
        "",
        "## أثر الواقعة على المبلغ",
        report["victim_impact"],
        "",
        "## تنبيه قانوني",
        report["legal_caution"],
        "",
        "## النص الأصلي للمكالمة",
        intake["transcript"],
        "",
        "## ملاحظات",
        intake.get("short_notes") or "لا توجد ملاحظات إضافية.",
        "",
    ]
    return "\n".join(lines)


def render_pdf(output_path: Path, intake: Dict[str, Any], report: Dict[str, Any]) -> None:
    font_name = _ensure_pdf_font()
    stylesheet = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ArabicTitle",
        parent=stylesheet["Title"],
        fontName=font_name,
        fontSize=18,
        leading=24,
        alignment=TA_RIGHT,
    )
    heading_style = ParagraphStyle(
        "ArabicHeading",
        parent=stylesheet["Heading2"],
        fontName=font_name,
        fontSize=13,
        leading=18,
        alignment=TA_RIGHT,
        spaceBefore=8,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "ArabicBody",
        parent=stylesheet["BodyText"],
        fontName=font_name,
        fontSize=10.5,
        leading=15,
        alignment=TA_RIGHT,
    )
    transcript_style = ParagraphStyle(
        "TranscriptBody",
        parent=stylesheet["Code"],
        fontName=font_name,
        fontSize=9.5,
        leading=13,
        alignment=TA_RIGHT,
    )

    def add_paragraph(story: list, text: str, style: ParagraphStyle, transcript: bool = False) -> None:
        if transcript:
            html = _transcript_html(text)
        else:
            html = _paragraph_html(_shape_for_pdf(text))
        story.append(Paragraph(html, style))
        story.append(Spacer(1, 4))

    story = []
    add_paragraph(story, report["case_title"], title_style)
    for heading, items, is_transcript in _section_items(intake, report):
        add_paragraph(story, heading, heading_style)
        for item in items:
            prefix = "" if is_transcript else "- "
            add_paragraph(story, f"{prefix}{item}", transcript_style if is_transcript else body_style, transcript=is_transcript)

    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    document.build(story)


def quote_filename(filename: str) -> str:
    base_name = Path(filename).name
    safe_chars = "._-"
    return "".join(char if char.isalnum() or char in safe_chars else "_" for char in base_name)


def build_public_report_file_url(public_base_url: str | None, file_path: str) -> str | None:
    if not public_base_url:
        return None
    return f"{public_base_url.rstrip('/')}/reports/files/{quote_filename(file_path)}"


def save_report_bundle(
    storage_dir: Path,
    intake: Dict[str, Any],
    report: Dict[str, Any],
) -> Dict[str, str]:
    ensure_storage_dir(storage_dir)
    base_name = f"{_now_stamp()}-{uuid4().hex[:8]}"
    json_path = storage_dir / f"{base_name}.json"
    markdown_path = storage_dir / f"{base_name}.md"
    pdf_path = storage_dir / f"{base_name}.pdf"

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "intake": intake,
        "report": report,
    }

    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    markdown_path.write_text(render_markdown(intake=intake, report=report), encoding="utf-8")
    render_pdf(pdf_path, intake=intake, report=report)

    return {
        "json_path": str(json_path.resolve()),
        "markdown_path": str(markdown_path.resolve()),
        "pdf_path": str(pdf_path.resolve()),
    }
