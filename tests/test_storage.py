from tempfile import TemporaryDirectory
import unittest
from pathlib import Path

from app.config import Settings
from app.emailer import send_report_email
from app.forwarder import forward_report

from app.storage import render_markdown, save_report_bundle


INTAKE = {
    "reporter_name": "Alex Doe",
    "reporter_phone": "+15550001111",
    "reporter_email": "alex@example.com",
    "incident_country": "United Arab Emirates",
    "incident_city": "Dubai",
    "call_received_at": "2026-03-25T14:00:00+04:00",
    "scam_phone_number": "+15559990000",
    "transcript": "Caller claimed my bank account was blocked and asked for the OTP code.",
    "short_notes": "Hung up after refusing to share code.",
}

REPORT = {
    "case_title": "اشتباه في مكالمة احتيال بانتحال صفة بنك",
    "incident_summary": "أفاد المبلغ بأن المتصل زعم أنه يمثل بنكاً وطلب رمز التحقق لمرة واحدة.",
    "suspected_scam_type": "انتحال صفة بنك",
    "threat_level": "medium",
    "should_report_to_police": True,
    "recommended_reporting_channel": "قناة الإبلاغ المحلية غير الطارئة عن جرائم الاحتيال",
    "confidence": 0.88,
    "timeline": ["تلقى المبلغ اتصالاً من شخص طلب رمز تحقق لمرة واحدة."],
    "people_and_numbers": ["رقم المتصل: +15559990000"],
    "requested_money_or_data": ["طلب رمز تحقق لمرة واحدة للوصول إلى الحساب البنكي"],
    "evidence_to_preserve": ["سجل المكالمات", "الرسائل النصية", "تنبيهات البنك"],
    "recommended_next_steps": ["التواصل مع البنك مباشرة", "تقديم بلاغ احتيال للشرطة"],
    "police_narrative": "تلقى المبلغ اتصالاً مشبوهاً من شخص ادعى أنه من البنك وطلب بيانات تحقق حساسة.",
    "victim_impact": "لم يتم الإبلاغ عن خسارة مالية وقت تقديم البلاغ.",
    "legal_caution": "أُعد هذا الملخص استناداً إلى إفادة المبلغ ونص المكالمة ولم يخضع للتحقق المستقل.",
}


class StorageTests(unittest.TestCase):
    def test_render_markdown_contains_key_sections(self) -> None:
        document = render_markdown(INTAKE, REPORT)
        self.assertIn("# اشتباه في مكالمة احتيال بانتحال صفة بنك", document)
        self.assertIn("## السرد الموجز للشرطة", document)
        self.assertIn("رقم المتصل: +15559990000", document)

    def test_save_report_bundle_writes_json_and_markdown(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            result = save_report_bundle(Path(tmp_dir), INTAKE, REPORT)
            self.assertTrue(Path(result["json_path"]).exists())
            self.assertTrue(Path(result["markdown_path"]).exists())
            self.assertTrue(Path(result["pdf_path"]).exists())

    def test_forwarding_requires_positive_ai_recommendation(self) -> None:
        settings = Settings(
            openai_api_key="test-key",
            openai_model="gpt-5.4-mini",
            police_report_webhook_url="https://example.com/report",
            auto_forward_reports=True,
            webhook_auth_header_name=None,
            webhook_auth_header_value=None,
            report_storage_dir=Path("reports"),
        )
        intake = dict(INTAKE)
        intake["wants_forwarding"] = True
        report = dict(REPORT)
        report["should_report_to_police"] = False

        result = forward_report(settings, intake, report)

        self.assertFalse(result["sent"])
        self.assertIn("did not recommend", result["reason"])

    def test_email_returns_not_configured_when_smtp_missing(self) -> None:
        settings = Settings(
            openai_api_key="test-key",
            openai_model="gpt-5.4-mini",
            police_report_webhook_url=None,
            auto_forward_reports=False,
            webhook_auth_header_name=None,
            webhook_auth_header_value=None,
            report_storage_dir=Path("reports"),
            auto_email_reports=True,
            email_to_address="hunterworld@gmail.com",
            smtp_host=None,
            smtp_username=None,
            smtp_password=None,
            smtp_from_email=None,
        )

        with TemporaryDirectory() as tmp_dir:
            paths = save_report_bundle(Path(tmp_dir), INTAKE, REPORT)
            result = send_report_email(settings, INTAKE, REPORT, paths)

        self.assertFalse(result["sent"])
        self.assertIn("SMTP settings are incomplete", result["reason"])


if __name__ == "__main__":
    unittest.main()
