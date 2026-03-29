import sys
import types
import unittest
from unittest.mock import patch

tinyfish_stub = types.ModuleType("tinyfish")
tinyfish_stub.TinyFish = object
sys.modules.setdefault("tinyfish", tinyfish_stub)

from core.discovery.multi_source import (
    scrape_myscheme,
    scrape_scholarships360,
    scrape_we_make_scholars,
)


class MultiSourceFailureTests(unittest.TestCase):
    @patch("core.discovery.multi_source.logger.warning")
    @patch("core.discovery.multi_source._fetch_html", side_effect=RuntimeError("404"))
    def test_myscheme_failure_returns_empty_without_warning_spam(self, mock_fetch, mock_warning):
        self.assertEqual(scrape_myscheme(), [])
        mock_warning.assert_not_called()

    @patch("core.discovery.multi_source.logger.warning")
    @patch("core.discovery.multi_source._fetch_html", side_effect=RuntimeError("404"))
    def test_we_make_scholars_failure_returns_empty_without_warning_spam(self, mock_fetch, mock_warning):
        self.assertEqual(scrape_we_make_scholars(), [])
        mock_warning.assert_not_called()

    @patch("core.discovery.multi_source.logger.warning")
    @patch("core.discovery.multi_source._fetch_html", side_effect=RuntimeError("404"))
    def test_scholarships360_failure_returns_empty_without_warning_spam(self, mock_fetch, mock_warning):
        self.assertEqual(scrape_scholarships360(), [])
        mock_warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
