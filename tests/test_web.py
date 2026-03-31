import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx
import openai
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.realtime_call_agent import (
    CallTranscript,
    build_report_intake_from_call,
    save_call_report,
    build_stream_url,
    build_voice_agent_prompt,
    resolve_voice_line_role,
    should_end_reporting_call,
)


class WebRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.settings = Settings(
            openai_api_key="test-key",
            openai_model="gpt-5.4-mini",
            police_report_webhook_url=None,
            auto_forward_reports=False,
            webhook_auth_header_name=None,
            webhook_auth_header_value=None,
            report_storage_dir=Path("reports"),
            public_base_url="https://example.ngrok-free.app",
            twilio_agent_phone_number="+15550009999",
            twilio_reporting_phone_number="+15550008888",
        )

    def _sample_payload(self) -> dict:
        return {
            "reporter_name": "Alex Doe",
            "incident_country": "United Arab Emirates",
            "incident_city": "Dubai",
            "transcript": "The caller claimed to be from my bank and asked for my OTP code.",
            "wants_forwarding": False,
        }

    def _openai_response(self, status_code: int) -> httpx.Response:
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        return httpx.Response(status_code, request=request)

    def test_home_page_serves_html(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Scam Call Intake", response.text)

    def test_reports_archive_page_serves_html(self) -> None:
        response = self.client.get("/reports/archive")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Browse all reports saved on this server", response.text)

    def test_public_report_file_route_serves_pdf(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            storage_dir = Path(tmp_dir)
            pdf_path = storage_dir / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%test\n")
            settings = Settings(
                openai_api_key="test-key",
                openai_model="gpt-5.4-mini",
                police_report_webhook_url=None,
                auto_forward_reports=False,
                webhook_auth_header_name=None,
                webhook_auth_header_value=None,
                report_storage_dir=storage_dir,
                public_base_url="https://example.ngrok-free.app",
                twilio_agent_phone_number="+15550009999",
                twilio_reporting_phone_number="+15550008888",
            )

            with patch("app.main.get_settings", return_value=settings):
                response = self.client.get("/reports/files/sample.pdf")

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/pdf", response.headers["content-type"])

    def test_reports_list_returns_saved_report_links(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            storage_dir = Path(tmp_dir)
            (storage_dir / "sample.md").write_text("# تقرير اختباري\n", encoding="utf-8")
            (storage_dir / "sample.pdf").write_bytes(b"%PDF-1.4\n%test\n")
            (storage_dir / "sample.json").write_text("{}", encoding="utf-8")
            settings = Settings(
                openai_api_key="test-key",
                openai_model="gpt-5.4-mini",
                police_report_webhook_url=None,
                auto_forward_reports=False,
                webhook_auth_header_name=None,
                webhook_auth_header_value=None,
                report_storage_dir=storage_dir,
                public_base_url="https://example.ngrok-free.app",
                twilio_agent_phone_number="+15550009999",
                twilio_reporting_phone_number="+15550008888",
            )

            with patch("app.main.get_settings", return_value=settings):
                response = self.client.get("/reports/list")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["reports"][0]["title"], "تقرير اختباري")
        self.assertEqual(payload["reports"][0]["files"]["pdf"], "/reports/files/sample.pdf")

    def test_twilio_incoming_returns_voice_twiml(self) -> None:
        with patch("app.main.get_settings", return_value=self.settings):
            response = self.client.get("/twilio/voice/incoming")

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response.headers["content-type"])
        self.assertIn("<Connect>", response.text)
        self.assertIn("wss://example.ngrok-free.app/twilio/voice/media-stream", response.text)

    def test_health_reports_dedicated_agent_number(self) -> None:
        with patch("app.main.get_settings", return_value=self.settings):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["twilio_agent_phone_number"], "+15550009999")
        self.assertEqual(response.json()["twilio_reporting_phone_number"], "+15550008888")

    def test_get_settings_uses_render_external_url_when_public_base_url_missing(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PUBLIC_BASE_URL": "",
                "RENDER_EXTERNAL_URL": "https://police-report-agent.onrender.com",
            },
            clear=False,
        ):
            settings = get_settings()

        self.assertEqual(settings.public_base_url, "https://police-report-agent.onrender.com")

    def test_build_stream_url_uses_wss(self) -> None:
        self.assertEqual(
            build_stream_url("https://example.com"),
            "wss://example.com/twilio/voice/media-stream",
        )

    def test_build_stream_url_includes_caller_number(self) -> None:
        self.assertEqual(
            build_stream_url("https://example.com", caller_number="+15550001111"),
            "wss://example.com/twilio/voice/media-stream?caller_number=%2B15550001111",
        )

    def test_build_stream_url_includes_line_role_and_called_number(self) -> None:
        self.assertEqual(
            build_stream_url(
                "https://example.com",
                caller_number="+15550001111",
                called_number="+15550008888",
                line_role="reporting",
            ),
            "wss://example.com/twilio/voice/media-stream?caller_number=%2B15550001111&called_number=%2B15550008888&line_role=reporting",
        )

    def test_resolve_voice_line_role_prefers_reporting_number(self) -> None:
        self.assertEqual(resolve_voice_line_role("+15550008888", self.settings), "reporting")
        self.assertEqual(resolve_voice_line_role("+15550009999", self.settings), "scam_bait")

    def test_reporting_prompt_is_transparent(self) -> None:
        self.assertIn("transparent scam reporting assistant", build_voice_agent_prompt("reporting"))
        self.assertIn("formal Emirati male tone", build_voice_agent_prompt("reporting"))

    def test_reporting_call_end_detection_matches_final_confirmation(self) -> None:
        self.assertTrue(
            should_end_reporting_call(
                "reporting",
                "تم إعداد البلاغ. شكراً لاتصالك. مع السلامة.",
            )
        )
        self.assertFalse(should_end_reporting_call("reporting", "تفضل، خبرني شو صار."))
        self.assertFalse(should_end_reporting_call("scam_bait", "تم إعداد البلاغ. شكراً لاتصالك."))

    def test_twilio_incoming_returns_error_when_public_url_missing(self) -> None:
        broken_settings = Settings(
            openai_api_key="test-key",
            openai_model="gpt-5.4-mini",
            police_report_webhook_url=None,
            auto_forward_reports=False,
            webhook_auth_header_name=None,
            webhook_auth_header_value=None,
            report_storage_dir=Path("reports"),
            public_base_url=None,
        )

        with patch("app.main.get_settings", return_value=broken_settings):
            response = self.client.get("/twilio/voice/incoming")

        self.assertEqual(response.status_code, 200)
        self.assertIn("PUBLIC_BASE_URL is required", response.text)

    def test_twilio_incoming_post_includes_caller_number_for_stream(self) -> None:
        with patch("app.main.get_settings", return_value=self.settings):
            response = self.client.post(
                "/twilio/voice/incoming",
                data={"From": "+15550001111", "To": "+15550009999", "CallSid": "CA123"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("caller_number=%2B15550001111", response.text)
        self.assertIn("called_number=%2B15550009999", response.text)
        self.assertIn("line_role=scam_bait", response.text)

    def test_twilio_incoming_post_marks_reporting_line(self) -> None:
        with patch("app.main.get_settings", return_value=self.settings):
            response = self.client.post(
                "/twilio/voice/incoming",
                data={"From": "+15550001111", "To": "+15550008888", "CallSid": "CA124"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("line_role=reporting", response.text)

    def test_twilio_media_stream_route_calls_bridge(self) -> None:
        async def fake_bridge(websocket, settings) -> None:
            await websocket.accept()
            await websocket.close()

        with patch("app.main.get_settings", return_value=self.settings), patch(
            "app.main.run_conversational_call",
            AsyncMock(side_effect=fake_bridge),
        ) as bridge:
            with self.client.websocket_connect("/twilio/voice/media-stream"):
                pass

        bridge.assert_awaited_once()

    def test_build_report_intake_from_call_marks_scammer_number(self) -> None:
        state = CallTranscript(
            call_sid="CA123",
            stream_sid="MZ123",
            caller_number="+15550001111",
            turns=[
                {"role": "caller", "text": "I am calling from the bank and need your OTP code."},
                {"role": "assistant", "text": "Which number should I call back?"},
            ],
        )

        intake = build_report_intake_from_call(state, self.settings)

        self.assertEqual(intake["reporter_name"], "Automated scam-call agent")
        self.assertEqual(intake["reporter_phone"], "+15550009999")
        self.assertEqual(intake["scam_phone_number"], "+15550001111")
        self.assertTrue(intake["money_requested"])

    def test_build_report_intake_from_reporting_line_uses_caller_as_reporter(self) -> None:
        state = CallTranscript(
            call_sid="CA456",
            stream_sid="MZ456",
            caller_number="+15550002222",
            called_number="+15550008888",
            line_role="reporting",
            turns=[
                {"role": "caller", "text": "The scammer used number +15556667777 and said he was from my bank."},
                {"role": "assistant", "text": "Did they ask for money or a code?"},
            ],
        )

        intake = build_report_intake_from_call(state, self.settings)

        self.assertIsNone(intake["reporter_name"])
        self.assertEqual(intake["reporter_phone"], "+15550002222")
        self.assertEqual(intake["scam_phone_number"], "+15556667777")

    def test_build_report_intake_from_call_uses_partial_fallback_when_no_transcript(self) -> None:
        state = CallTranscript(
            call_sid="CA789",
            stream_sid="MZ789",
            caller_number="+15550003333",
            called_number="+15550008888",
            line_role="reporting",
        )

        intake = build_report_intake_from_call(state, self.settings)

        self.assertIn("تم إغلاق المكالمة قبل اكتمال جمع التفاصيل", intake["transcript"])
        self.assertIn("partial call data", intake["short_notes"])

    def test_save_call_report_can_create_partial_report_from_call_metadata(self) -> None:
        state = CallTranscript(
            call_sid="CA999",
            stream_sid="MZ999",
            caller_number="+15550004444",
            called_number="+15550008888",
            line_role="reporting",
        )
        fake_report = {
            "case_title": "بلاغ جزئي",
            "incident_summary": "تم إنشاء البلاغ من بيانات مكالمة جزئية.",
            "suspected_scam_type": "بلاغ احتيال هاتفي جزئي",
            "threat_level": "low",
            "should_report_to_police": True,
            "confidence": 0.6,
            "recommended_reporting_channel": "شرطة دبي",
            "timeline": [],
            "people_and_numbers": [],
            "requested_money_or_data": [],
            "evidence_to_preserve": [],
            "recommended_next_steps": [],
            "police_narrative": "ملخص جزئي",
            "victim_impact": "غير معروف",
            "legal_caution": "مبني على بيانات جزئية",
        }

        with patch("app.realtime_call_agent.PoliceReportAgent") as agent_cls, patch(
            "app.realtime_call_agent.save_report_bundle",
            return_value={
                "json_path": "/tmp/report.json",
                "markdown_path": "/tmp/report.md",
                "pdf_path": "/tmp/report.pdf",
            },
        ), patch(
            "app.realtime_call_agent.forward_report",
            return_value={"attempted": False, "sent": False, "reason": "off", "destination": None, "status_code": None},
        ), patch(
            "app.realtime_call_agent.send_report_email",
            return_value={"attempted": False, "sent": False, "reason": "off", "recipient": "hunterworld@gmail.com"},
        ), patch(
            "app.realtime_call_agent.send_report_whatsapp",
            return_value={"attempted": False, "sent": False, "reason": "off", "recipient": None, "message_sid": None, "media_url": None},
        ):
            agent_cls.return_value.generate_report.return_value = fake_report
            result = save_call_report(self.settings, state)

        self.assertIsNotNone(result)
        agent_cls.return_value.generate_report.assert_called_once()

    def test_twilio_process_speech_generates_report_response(self) -> None:
        fake_report = {
            "case_title": "Phone scam",
            "incident_summary": "Caller asked for account access.",
            "suspected_scam_type": "Impersonation",
            "threat_level": "high",
            "should_report_to_police": True,
            "confidence": 0.93,
            "recommended_next_steps": ["Call your bank directly."],
        }
        fake_paths = {
            "json_path": "/tmp/report.json",
            "markdown_path": "/tmp/report.md",
            "pdf_path": "/tmp/report.pdf",
        }
        fake_forwarding = {
            "attempted": False,
            "sent": False,
            "reason": "Not requested",
            "destination": None,
            "status_code": None,
        }
        fake_email = {
            "attempted": False,
            "sent": False,
            "reason": "SMTP settings are incomplete.",
            "recipient": "hunterworld@gmail.com",
        }
        fake_whatsapp = {
            "attempted": False,
            "sent": False,
            "reason": "WhatsApp delivery settings are incomplete.",
            "recipient": None,
            "message_sid": None,
            "media_url": None,
        }

        with patch("app.main.get_settings", return_value=self.settings), patch(
            "app.main._generate_report_bundle",
            return_value=(fake_report, fake_paths, fake_forwarding, fake_email, fake_whatsapp),
        ):
            response = self.client.post(
                "/twilio/voice/process-speech",
                data={
                    "From": "+15550001111",
                    "SpeechResult": "The caller said my bank account was blocked and asked for my OTP.",
                    "CallSid": "CA123",
                    "Confidence": "0.71",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response.headers["content-type"])
        self.assertIn("تم حفظ بلاغ مكالمة الاحتيال الخاصة بك", response.text)
        self.assertIn("مستوى التهديد هو high", response.text)

    def test_twilio_process_speech_handles_missing_speech(self) -> None:
        with patch("app.main.get_settings", return_value=self.settings):
            response = self.client.post("/twilio/voice/process-speech", data={"From": "+15550001111"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("تعذر التقاط البلاغ الصوتي", response.text)

    def test_twilio_whatsapp_incoming_returns_chat_reply(self) -> None:
        fake_result = {
            "reply_text": "أفهم ما حدث. من فضلك ما الرقم الذي تواصل معك؟\n\nإذا انتهيت من إرسال التفاصيل، اكتب: تم",
            "media_url": None,
        }

        with patch("app.main.get_settings", return_value=self.settings), patch(
            "app.main.handle_whatsapp_message",
            return_value=fake_result,
        ):
            response = self.client.post(
                "/twilio/whatsapp/incoming",
                data={
                    "From": "whatsapp:+15550001111",
                    "Body": "تلقيت رسالة من شخص ادعى أنه من البنك وطلب رمز التحقق.",
                    "MessageSid": "SM123",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response.headers["content-type"])
        self.assertIn("ما الرقم الذي تواصل معك", response.text)
        self.assertIn("اكتب: تم", response.text)

    def test_twilio_whatsapp_incoming_can_attach_pdf(self) -> None:
        fake_result = {
            "reply_text": "تم إعداد التقرير النهائي وإرسال نسخة PDF.",
            "media_url": "https://example.ngrok-free.app/reports/files/report.pdf",
        }

        with patch("app.main.get_settings", return_value=self.settings), patch(
            "app.main.handle_whatsapp_message",
            return_value=fake_result,
        ):
            response = self.client.post(
                "/twilio/whatsapp/incoming",
                data={
                    "From": "whatsapp:+15550001111",
                    "Body": "تم",
                    "MessageSid": "SM124",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("<Media>https://example.ngrok-free.app/reports/files/report.pdf</Media>", response.text)

    def test_twilio_whatsapp_incoming_requires_body(self) -> None:
        with patch("app.main.get_settings", return_value=self.settings):
            response = self.client.post(
                "/twilio/whatsapp/incoming",
                data={"From": "whatsapp:+15550001111", "Body": ""},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("يرجى إرسال وصف مكتوب", response.text)

    def test_reports_route_returns_friendly_quota_message(self) -> None:
        quota_error = openai.RateLimitError(
            "quota exceeded",
            response=self._openai_response(429),
            body={"error": {"code": "insufficient_quota"}},
        )

        with patch("app.main.get_settings", return_value=self.settings), patch(
            "app.main.PoliceReportAgent"
        ) as agent_cls:
            agent_cls.return_value.generate_report.side_effect = quota_error
            response = self.client.post("/reports", json=self._sample_payload())

        self.assertEqual(response.status_code, 503)
        self.assertIn("no available quota", response.json()["detail"])

    def test_reports_route_returns_friendly_auth_message(self) -> None:
        auth_error = openai.AuthenticationError(
            "invalid api key",
            response=self._openai_response(401),
            body={"error": {"code": "invalid_api_key"}},
        )

        with patch("app.main.get_settings", return_value=self.settings), patch(
            "app.main.PoliceReportAgent"
        ) as agent_cls:
            agent_cls.return_value.generate_report.side_effect = auth_error
            response = self.client.post("/reports", json=self._sample_payload())

        self.assertEqual(response.status_code, 401)
        self.assertIn("API key was rejected", response.json()["detail"])

    def test_reports_route_returns_config_message_for_missing_key(self) -> None:
        broken_settings = Settings(
            openai_api_key=None,
            openai_model="gpt-5.4-mini",
            police_report_webhook_url=None,
            auto_forward_reports=False,
            webhook_auth_header_name=None,
            webhook_auth_header_value=None,
            report_storage_dir=Path("reports"),
            public_base_url="https://example.ngrok-free.app",
        )

        with patch("app.main.get_settings", return_value=broken_settings):
            response = self.client.post("/reports", json=self._sample_payload())

        self.assertEqual(response.status_code, 400)
        self.assertIn("OPENAI_API_KEY is not configured", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
