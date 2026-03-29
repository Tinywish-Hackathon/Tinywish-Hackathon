import unittest
from unittest.mock import patch

import main
from schemas.scheme_model import SchemeModel


class DiscoveryHandoffModeTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
