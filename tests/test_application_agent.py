import sys
import types
import unittest
from unittest.mock import patch

tinyfish_stub = types.ModuleType("tinyfish")
tinyfish_stub.TinyFish = object
sys.modules.setdefault("tinyfish", tinyfish_stub)

from core.application_agent import (
    _build_goal,
    _resolve_application_stream,
    _resolve_application_url,
    handle_human_handoff,
    open_local_preview,
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
        self.assertIn("Navigate to https://wis.ntu.edu.sg/apply", goal)

    def test_falls_back_to_nsp_when_apply_link_missing(self):
        url = _resolve_application_url("")
        goal = _build_goal("NSP Scheme", base_url=url)

        self.assertEqual(url, "https://scholarships.gov.in/")
        self.assertIn("Start URL: https://scholarships.gov.in/", goal)


class BrowserLaunchTests(unittest.TestCase):
    @patch("webbrowser.open")
    def test_open_local_preview_uses_resolved_url(self, mock_open):
        result = open_local_preview("")

        self.assertEqual(result, "https://scholarships.gov.in/")
        mock_open.assert_called_once_with("https://scholarships.gov.in/")

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


if __name__ == "__main__":
    unittest.main()
