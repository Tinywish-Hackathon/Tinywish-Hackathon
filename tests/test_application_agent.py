import sys
import types
import unittest
import os
import subprocess
from unittest.mock import patch

tinyfish_stub = types.ModuleType("tinyfish")
tinyfish_stub.TinyFish = object
sys.modules.setdefault("tinyfish", tinyfish_stub)

from core.application_agent import (
    _build_goal,
    _finalize_application_result,
    _resolve_application_stream,
    _resolve_application_url,
    handle_human_handoff,
    open_local_preview,
    run_tinyfish_application_agent,
)


class ResolveApplicationStreamTests(unittest.TestCase):
    def test_prefers_result_event_over_trailing_heartbeat(self):
        events = [
            ("message", '{"type":"MESSAGE","status":"working"}'),
            ("message", '{"type":"RESULT","content":"{\\"steps\\":[\\"Step 1\\"],\\"fields\\":[\\"Name\\"]}"}'),
            ("message", '{"type":"HEARTBEAT"}'),
        ]

        result = _resolve_application_stream(events)

        self.assertEqual(result["steps"], ["Step 1"])
        self.assertEqual(result["fields"], ["Name"])

    def test_falls_back_to_structured_message_when_no_result_event_exists(self):
        events = [
            ("message", '{"type":"MESSAGE","status":"working"}'),
            ("message", '{"steps":["Step 1"],"documents":["ID Proof"]}'),
            ("message", '{"type":"HEARTBEAT"}'),
        ]

        result = _resolve_application_stream(events)

        self.assertEqual(result["steps"], ["Step 1"])
        self.assertEqual(result["documents"], ["ID Proof"])


class ApplicationUrlSelectionTests(unittest.TestCase):
    def test_prefers_scheme_apply_link_over_default_portal(self):
        url = _resolve_application_url("https://wis.ntu.edu.sg/apply")
        goal = _build_goal("NTU Scholarship", base_url=url)

        self.assertEqual(url, "https://wis.ntu.edu.sg/apply")
        self.assertIn("Start URL: https://wis.ntu.edu.sg/apply", goal)
        self.assertIn("Start from https://wis.ntu.edu.sg/apply", goal)
        self.assertIn("Complete as much of the application workflow as possible.", goal)
        self.assertIn("1. Direct form interaction", goal)
        self.assertIn("2. Extract fields and required documents", goal)
        self.assertIn("3. Avoid dead ends such as closed pages and login walls", goal)
        self.assertIn("Do NOT blindly follow links to external portals", goal)
        self.assertIn("Prefer staying on the same domain", goal)
        self.assertIn("If login is required, extract visible information and stop", goal)
        self.assertIn("Prefer workflows where the application form is directly accessible without login", goal)
        self.assertIn("Avoid redirecting to a different external portal or domain", goal)
        self.assertIn("Stop before the authenticated flow", goal)
        self.assertIn('"apply_link": ""', goal)
        self.assertIn('"fields": []', goal)
        self.assertIn('"documents": []', goal)
        self.assertIn('"steps": []', goal)
        self.assertIn('"form_detected": boolean', goal)

    def test_extract_only_goal_includes_strategy_constraints(self):
        goal = _build_goal(
            "Portal Scholarship",
            base_url="https://example.com/login",
            execution_strategy="extract_only",
        )

        self.assertIn("Execution strategy:", goal)
        self.assertIn("Extract requirements only", goal)
        self.assertIn("Do not attempt a full application flow", goal)
        self.assertIn("Stop immediately when login, registration, or OTP is required", goal)
        self.assertIn("If login is required, extract visible information and stop", goal)

    def test_falls_back_to_neutral_url_when_apply_link_missing(self):
        url = _resolve_application_url("")
        goal = _build_goal("NSP Scheme", base_url=url)

        self.assertEqual(url, "https://example.com/")
        self.assertIn("Start URL: https://example.com/", goal)


class ApplicationResultFinalizationTests(unittest.TestCase):
    def test_keeps_requested_url_when_external_redirect_hits_login_wall(self):
        result = _finalize_application_result(
            {
                "apply_link": "https://scholarships.gov.in/",
                "fields": ["Aadhaar", "DOB"],
                "documents": ["Income Certificate"],
                "steps": ["Login to continue the application", "Enter OTP sent to mobile"],
                "form_detected": False,
            },
            "Buddy Scholarship",
            requested_url="https://www.buddy4study.com/scholarship/demo",
        )

        self.assertEqual(result["apply_link"], "https://www.buddy4study.com/scholarship/demo")
        self.assertEqual(result["fields"], ["Aadhaar", "DOB"])
        self.assertFalse(result["form_detected"])
        self.assertIn("Stop here and complete login or OTP manually before continuing.", result["steps"])

    def test_preserves_direct_form_link_when_form_is_accessible(self):
        result = _finalize_application_result(
            {
                "apply_link": "https://portal.example.com/apply",
                "fields": ["Name"],
                "documents": [],
                "steps": ["Open application form"],
                "form_detected": True,
            },
            "Direct Portal Scheme",
            requested_url="https://listing.example.com/scheme",
        )

        self.assertEqual(result["apply_link"], "https://portal.example.com/apply")
        self.assertTrue(result["form_detected"])


class BrowserLaunchTests(unittest.TestCase):
    @patch("webbrowser.open")
    def test_open_local_preview_uses_resolved_url(self, mock_open):
        result = open_local_preview("")

        self.assertEqual(result, "https://example.com/")
        mock_open.assert_called_once_with("https://example.com/")

    @patch("builtins.print")
    @patch("webbrowser.open")
    def test_handle_human_handoff_skips_browser_when_disabled(self, mock_open, _mock_print):
        handle_human_handoff(
            {
                "apply_link": "https://wis.ntu.edu.sg/apply",
                "fields": [],
                "documents": [],
                "steps": [],
                "form_detected": False,
            },
            {},
            open_browser=False,
        )

        mock_open.assert_not_called()


class AgentFallbackTests(unittest.TestCase):
    def test_run_tinyfish_application_agent_returns_contract_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True), patch("builtins.print"), patch("webbrowser.open"):
            result = run_tinyfish_application_agent(
                "National Scholarship",
                profile={},
                api_key=None,
                apply_link="https://example.com/apply",
                open_browser=False,
            )

        self.assertEqual(result["apply_link"], "https://example.com/apply")
        self.assertEqual(result["fields"], [])
        self.assertEqual(result["documents"], [])
        self.assertIsInstance(result["steps"], list)
        self.assertFalse(result["form_detected"])

    def test_application_agent_imports_without_tinyfish_sdk_installed(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        command = [
            sys.executable,
            "-c",
            "import core.application_agent; print('ok')",
        ]

        completed = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("ok", completed.stdout)


if __name__ == "__main__":
    unittest.main()
