import sys
import types
import unittest
from unittest.mock import patch

tinyfish_stub = types.ModuleType("tinyfish")
tinyfish_stub.TinyFish = object
sys.modules.setdefault("tinyfish", tinyfish_stub)

from core.discovery.multi_source import collect_source_lists
from core.discovery.startup_india_scraper import get_startup_india_schemes


class StartupIndiaScraperTests(unittest.TestCase):
    def test_fallback_returns_known_demo_schemes(self):
        with patch(
            "core.discovery.startup_india_scraper._scrape_live_schemes",
            return_value=[],
        ):
            schemes = get_startup_india_schemes(use_cache=False)

        self.assertEqual(len(schemes), 3)
        self.assertEqual(schemes[0]["name"], "Startup India Seed Fund Scheme")
        self.assertEqual(schemes[1]["name"], "SIDBI Fund of Funds")
        self.assertEqual(schemes[2]["name"], "Credit Guarantee Scheme for Startups")
        self.assertTrue(all(item["source"] == "Startup India" for item in schemes))


class StartupIndiaSourceIntegrationTests(unittest.TestCase):
    @patch("core.discovery.multi_source.scrape_startup_india", return_value=[{"name": "Startup India Seed Fund Scheme"}])
    @patch("core.discovery.multi_source.scrape_international_scholarships", return_value=[{"name": "intl"}])
    @patch("core.discovery.multi_source.scrape_scholarships360", return_value=[{"name": "360"}])
    @patch("core.discovery.multi_source.scrape_we_make_scholars", return_value=[{"name": "wms"}])
    @patch("core.discovery.multi_source.scrape_buddy4study", return_value=[{"name": "b4s"}])
    @patch("core.discovery.multi_source.scrape_myscheme", return_value=[{"name": "myscheme"}])
    @patch("core.discovery.multi_source.scrape_nsp", return_value=[{"name": "nsp"}])
    def test_collect_source_lists_adds_startup_source(
        self,
        mock_nsp,
        mock_myscheme,
        mock_buddy4study,
        mock_we_make_scholars,
        mock_scholarships360,
        mock_international,
        mock_startup,
    ):
        source_lists = collect_source_lists({"startup": {"name": "Antigravity AI"}}, use_cache=False)

        self.assertEqual(len(source_lists), 7)
        self.assertEqual(source_lists[-1][0]["name"], "Startup India Seed Fund Scheme")
        mock_startup.assert_called_once_with(use_cache=False)

    @patch("core.discovery.multi_source.scrape_startup_india")
    @patch("core.discovery.multi_source.scrape_international_scholarships", return_value=[{"name": "intl"}])
    @patch("core.discovery.multi_source.scrape_scholarships360", return_value=[{"name": "360"}])
    @patch("core.discovery.multi_source.scrape_we_make_scholars", return_value=[{"name": "wms"}])
    @patch("core.discovery.multi_source.scrape_buddy4study", return_value=[{"name": "b4s"}])
    @patch("core.discovery.multi_source.scrape_myscheme", return_value=[{"name": "myscheme"}])
    @patch("core.discovery.multi_source.scrape_nsp", return_value=[{"name": "nsp"}])
    def test_collect_source_lists_skips_startup_without_profile_section(
        self,
        mock_nsp,
        mock_myscheme,
        mock_buddy4study,
        mock_we_make_scholars,
        mock_scholarships360,
        mock_international,
        mock_startup,
    ):
        source_lists = collect_source_lists({}, use_cache=False)

        self.assertEqual(len(source_lists), 6)
        mock_startup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
