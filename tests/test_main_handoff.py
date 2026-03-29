import unittest
from unittest.mock import patch

import main
from schemas.scheme_model import SchemeModel


class DiscoveryHandoffModeTests(unittest.TestCase):
    def test_mode_demo_resolves_to_agent_with_demo_bias(self):
        handoff_mode, demo_mode = main._resolve_demo_configuration("demo", False)

        self.assertEqual(handoff_mode, "agent")
        self.assertTrue(demo_mode)

    def test_demo_flag_preserves_requested_handoff_mode(self):
        handoff_mode, demo_mode = main._resolve_demo_configuration("hybrid", True)

        self.assertEqual(handoff_mode, "hybrid")
        self.assertTrue(demo_mode)

    def test_hybrid_opens_preview_before_tinyfish(self):
        calls = []
        selected = SchemeModel(
            name="NTU Scholarship",
            apply_link="https://wis.ntu.edu.sg/apply",
            status="open",
            eligibility="Apply online through the scholarship form",
        )

        with patch.object(main, "TINYFISH_AVAILABLE", True), patch("builtins.print"):
            main._run_discovery_handoff(
                selected,
                {},
                "hybrid",
                lambda result, profile, open_browser=True: calls.append(("handoff", open_browser)),
                lambda url: calls.append(("preview", url)),
                lambda name, profile=None, apply_link=None, execution_strategy="full_apply", open_browser=True: calls.append(
                    ("agent", name, apply_link, execution_strategy, open_browser)
                ),
            )

        self.assertEqual(calls[0], ("preview", "https://wis.ntu.edu.sg/apply"))
        self.assertEqual(
            calls[1],
            ("agent", "NTU Scholarship", "https://wis.ntu.edu.sg/apply", "full_apply", False),
        )

    def test_local_mode_stays_local(self):
        calls = []
        selected = SchemeModel(name="NTU Scholarship", apply_link="https://wis.ntu.edu.sg/apply")

        with patch.object(main, "TINYFISH_AVAILABLE", True), patch("builtins.print"):
            main._run_discovery_handoff(
                selected,
                {},
                "local",
                lambda result, profile, open_browser=True: calls.append(("handoff", open_browser, result["apply_link"])),
                lambda url: calls.append(("preview", url)),
                lambda *args, **kwargs: calls.append(("agent", args, kwargs)),
                lambda selected_scheme: calls.append(("local-flow", selected_scheme.name)),
            )

        self.assertEqual(calls[0], ("preview", "https://wis.ntu.edu.sg/apply"))
        self.assertEqual(calls[1], ("handoff", False, "https://wis.ntu.edu.sg/apply"))
        self.assertEqual(len(calls), 2)

    def test_local_mode_routes_known_portal_to_local_flow(self):
        calls = []
        selected = SchemeModel(
            name="Startup India Seed Fund Scheme",
            source="Startup India",
            apply_link="https://www.startupindia.gov.in/content/sih/en/government-schemes.html",
        )

        with patch.object(main, "TINYFISH_AVAILABLE", False), patch("builtins.print"):
            main._run_discovery_handoff(
                selected,
                {},
                "local",
                lambda result, profile, open_browser=True: calls.append(("handoff", open_browser)),
                lambda url: calls.append(("preview", url)),
                lambda *args, **kwargs: calls.append(("agent", args, kwargs)),
                lambda selected_scheme: calls.append(("local-flow", selected_scheme.name)) or True,
            )

        self.assertEqual(calls, [("local-flow", "Startup India Seed Fund Scheme")])

    def test_choose_execution_strategy_skips_closed_schemes(self):
        strategy, reason = main.choose_execution_strategy(
            SchemeModel(name="Closed Scheme", status="closed", apply_link="https://example.com/apply")
        )

        self.assertEqual(strategy, "skip")
        self.assertIn("closed", reason.lower())

    def test_choose_execution_strategy_extract_only_for_login_wall(self):
        strategy, reason = main.choose_execution_strategy(
            SchemeModel(
                name="Login Scheme",
                status="open",
                apply_link="https://example.com/login",
                eligibility="Login and OTP required before applying",
            )
        )

        self.assertEqual(strategy, "extract_only")
        self.assertIn("login", reason.lower())

    def test_choose_execution_strategy_manual_assist_without_apply_link(self):
        strategy, reason = main.choose_execution_strategy(
            SchemeModel(
                name="Manual Scheme",
                status="unknown",
                eligibility="Scholarship details available on the portal",
            )
        )

        self.assertEqual(strategy, "manual_assist")
        self.assertIn("manual assist", reason.lower())

    def test_login_wall_strategy_calls_agent_in_extract_only_mode(self):
        calls = []
        selected = SchemeModel(
            name="Portal Scheme",
            apply_link="https://example.com/login",
            status="open",
            eligibility="Login and OTP required before applying",
        )

        with patch.object(main, "TINYFISH_AVAILABLE", True), patch("builtins.print"):
            main._run_discovery_handoff(
                selected,
                {},
                "agent",
                lambda result, profile, open_browser=True: calls.append(("handoff", open_browser)),
                lambda url: calls.append(("preview", url)),
                lambda name, profile=None, apply_link=None, execution_strategy="full_apply", open_browser=True: calls.append(
                    ("agent", name, execution_strategy, open_browser)
                ),
            )

        self.assertEqual(calls, [("agent", "Portal Scheme", "extract_only", True)])

    def test_manual_assist_strategy_bypasses_agent_execution(self):
        calls = []
        selected = SchemeModel(
            name="Manual Scheme",
            status="unknown",
            eligibility="Portal details only",
        )

        with patch.object(main, "TINYFISH_AVAILABLE", True), patch("builtins.print"):
            main._run_discovery_handoff(
                selected,
                {},
                "agent",
                lambda result, profile, open_browser=True: calls.append(("handoff", open_browser, result["steps"])),
                lambda url: calls.append(("preview", url)),
                lambda *args, **kwargs: calls.append(("agent", args, kwargs)),
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "handoff")

    def test_execute_ranked_handoff_retries_next_scheme_after_failed_result(self):
        ranked = [
            SchemeModel(
                name="First Scheme",
                apply_link="https://example.com/first",
                status="open",
                eligibility="Apply online through the scholarship form",
                source_type="private",
            ),
            SchemeModel(
                name="Second Scheme",
                apply_link="https://example.com/second",
                status="open",
                eligibility="Apply online through the scholarship form",
                source_type="private",
            ),
        ]
        agent_calls = []

        def fake_agent(name, profile=None, apply_link=None, execution_strategy="full_apply", open_browser=True):
            agent_calls.append(name)
            if name == "First Scheme":
                return {
                    "apply_link": apply_link,
                    "fields": [],
                    "documents": [],
                    "steps": ["Opened page"],
                    "form_detected": False,
                }
            return {
                "apply_link": apply_link,
                "fields": ["Name"],
                "documents": ["ID"],
                "steps": ["Opened form"],
                "form_detected": True,
            }

        with patch.object(main, "TINYFISH_AVAILABLE", True), patch("builtins.print"), patch.object(
            main.logger, "info"
        ) as mock_info, patch.object(main, "log_application"):
            result = main._execute_ranked_handoff_with_retry(
                ranked,
                0,
                {},
                "agent",
                lambda result, profile, open_browser=True: None,
                lambda url: None,
                fake_agent,
            )

        self.assertEqual(agent_calls, ["First Scheme", "Second Scheme"])
        self.assertTrue(result["success"])
        mock_info.assert_any_call("[AGENT] Retry triggered — selecting next scheme")

    def test_execute_ranked_handoff_limits_retries_to_two(self):
        ranked = [
            SchemeModel(
                name=f"Scheme {index}",
                apply_link=f"https://example.com/{index}",
                status="open",
                eligibility="Apply online through the scholarship form",
                source_type="private",
            )
            for index in range(4)
        ]
        agent_calls = []

        def fake_agent(name, profile=None, apply_link=None, execution_strategy="full_apply", open_browser=True):
            agent_calls.append(name)
            return {
                "apply_link": apply_link,
                "fields": [],
                "documents": [],
                "steps": ["Opened page"],
                "form_detected": False,
            }

        with patch.object(main, "TINYFISH_AVAILABLE", True), patch("builtins.print"), patch.object(
            main, "log_application"
        ):
            result = main._execute_ranked_handoff_with_retry(
                ranked,
                0,
                {},
                "agent",
                lambda result, profile, open_browser=True: None,
                lambda url: None,
                fake_agent,
            )

        self.assertEqual(agent_calls, ["Scheme 0", "Scheme 1", "Scheme 2"])
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
