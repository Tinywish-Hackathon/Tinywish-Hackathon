import sys
import types
import unittest

tinyfish_stub = types.ModuleType("tinyfish")
tinyfish_stub.TinyFish = object
sys.modules.setdefault("tinyfish", tinyfish_stub)

from core.discovery.eligibility import find_eligible_schemes
from core.discovery.multi_source import merge_schemes
from core.discovery.ranking import _rule_based_rank_with_profile
from schemas.scheme_model import SchemeModel


class SchemeModelTests(unittest.TestCase):
    def test_from_dict_normalizes_aliases_and_ignores_unknown_keys(self):
        scheme = SchemeModel.from_dict(
            {
                "scheme_name": "National Scholarship",
                "eligibilityText": "For OBC students",
                "income": "250000",
                "type": "private",
                "source": "Buddy4Study",
                "unexpected": "ignored",
            }
        )

        self.assertEqual(scheme.name, "National Scholarship")
        self.assertEqual(scheme.eligibility, "For OBC students")
        self.assertEqual(scheme.income_limit, 250000)
        self.assertEqual(scheme.source_type, "private")
        self.assertFalse(hasattr(scheme, "unexpected"))

    def test_to_display_line_includes_tinyfish_priority(self):
        scheme = SchemeModel(
            name="National Scholarship",
            source="NSP",
            match_score=4,
            tinyfish_priority="high",
        )

        self.assertEqual(
            scheme.to_display_line(),
            "National Scholarship [NSP] (score: 4) | Priority: high",
        )


class SchemeModelFlowTests(unittest.TestCase):
    def test_merge_schemes_returns_scheme_models(self):
        merged = merge_schemes(
            [
                [{"name": "National Scholarship", "source": "NSP"}],
                [{"schemeName": "National Scholarship", "source": "MyScheme"}],
            ]
        )

        self.assertEqual(len(merged), 1)
        self.assertIsInstance(merged[0], SchemeModel)
        self.assertEqual(merged[0].name, "National Scholarship")

    def test_eligibility_and_ranking_preserve_scheme_models(self):
        profile = {
            "state": "Jammu and Kashmir",
            "category": "OBC",
            "annual_income": 200000,
            "course_level": "undergraduate",
        }
        schemes = [
            SchemeModel(
                name="Jammu and Kashmir OBC Post Matric Scholarship",
                source="NSP",
                source_type="government",
            ),
            SchemeModel(
                name="Open Merit Scholarship",
                source="Buddy4Study",
                source_type="private",
                apply_link="https://example.com/apply",
            ),
        ]

        eligible = find_eligible_schemes(profile, schemes)
        ranked = _rule_based_rank_with_profile(profile, eligible)

        self.assertTrue(eligible)
        self.assertTrue(all(isinstance(item, SchemeModel) for item in eligible))
        self.assertTrue(all(isinstance(item, SchemeModel) for item in ranked))
        self.assertGreaterEqual(eligible[0].match_score, 1)
        self.assertEqual(ranked[0].name, "Jammu and Kashmir OBC Post Matric Scholarship")


if __name__ == "__main__":
    unittest.main()
