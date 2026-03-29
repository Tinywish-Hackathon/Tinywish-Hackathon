import unittest
from unittest.mock import patch

import main


class DiscoveryHandoffModeTests(unittest.TestCase):
    def test_hybrid_opens_preview_before_tinyfish(self):
        calls = []
        selected = {"name": "NTU Scholarship", "apply_link": "https://wis.ntu.edu.sg/apply"}

        with patch.object(main, "TINYFISH_AVAILABLE", True), patch("builtins.print"):
            main._run_discovery_handoff(
                selected,
                {},
                "hybrid",
                lambda result, profile, open_browser=True: calls.append(("handoff", open_browser)),
                lambda url: calls.append(("preview", url)),
                lambda name, profile=None, apply_link=None, open_browser=True: calls.append(
                    ("agent", name, apply_link, open_browser)
                ),
            )

        self.assertEqual(calls[0], ("preview", "https://wis.ntu.edu.sg/apply"))
        self.assertEqual(calls[1], ("agent", "NTU Scholarship", "https://wis.ntu.edu.sg/apply", False))

    def test_local_mode_stays_local(self):
        calls = []
        selected = {"name": "NTU Scholarship", "apply_link": "https://wis.ntu.edu.sg/apply"}

        with patch.object(main, "TINYFISH_AVAILABLE", True), patch("builtins.print"):
            main._run_discovery_handoff(
                selected,
                {},
                "local",
                lambda result, profile, open_browser=True: calls.append(("handoff", open_browser, result["apply_link"])),
                lambda url: calls.append(("preview", url)),
                lambda *args, **kwargs: calls.append(("agent", args, kwargs)),
            )

        self.assertEqual(calls[0], ("preview", "https://wis.ntu.edu.sg/apply"))
        self.assertEqual(calls[1], ("handoff", False, "https://wis.ntu.edu.sg/apply"))
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
