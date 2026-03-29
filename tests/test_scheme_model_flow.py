import sys
import types
import unittest
from unittest.mock import patch

tinyfish_stub = types.ModuleType("tinyfish")
tinyfish_stub.TinyFish = object
sys.modules.setdefault("tinyfish", tinyfish_stub)

from core.discovery.eligibility import find_eligible_schemes
from core.discovery.multi_source import merge_schemes
from core.discovery.ranking import _rule_based_rank, _rule_based_rank_with_profile, format_ranked_output, rank_schemes
from schemas.scheme_model import SchemeModel


class SchemeModelTests(unittest.TestCase):
    def test_from_dict_normalizes_aliases_and_ignores_unknown_keys(self):
        scheme = SchemeModel.from_dict(
            {
                "scheme_name": "National Scholarship",
                "eligibilityText": "For OBC students",
                "income": "250000",
                "type": "private",
                "lastDate": "2099-12-31",
                "deadlineStatus": "open",
                "source": "Buddy4Study",
                "unexpected": "ignored",
            }
        )

        self.assertEqual(scheme.name, "National Scholarship")
        self.assertEqual(scheme.eligibility, "For OBC students")
        self.assertEqual(scheme.income_limit, 250000)
        self.assertEqual(scheme.source_type, "private")
        self.assertEqual(scheme.deadline, "2099-12-31")
        self.assertEqual(scheme.status, "open")
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

        self.assertEqual(len(merged), 2)
        self.assertTrue(all(isinstance(item, SchemeModel) for item in merged))
        self.assertEqual({item.source for item in merged}, {"NSP", "MyScheme"})

    def test_merge_schemes_accumulates_across_multiple_sources(self):
        merged = merge_schemes(
            [
                [{"name": "National Scholarship", "source": "NSP"}],
                [{"name": "Open Merit Scholarship", "source": "Buddy4Study"}],
                [{"name": "Future Leaders Scholarship", "source": "Scholarships360"}],
            ]
        )

        self.assertEqual(len(merged), 3)
        self.assertEqual(
            {scheme.name for scheme in merged},
            {
                "National Scholarship",
                "Open Merit Scholarship",
                "Future Leaders Scholarship",
            },
        )

    def test_merge_preserves_explicit_government_source_type(self):
        merged = merge_schemes(
            [
                [
                    {
                        "name": "Startup India Seed Fund Scheme",
                        "source": "Startup India",
                        "source_type": "government",
                        "provider": "DPIIT",
                    }
                ]
            ]
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source_type, "government")

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

    def test_rule_based_rank_demotes_closed_schemes_and_marks_applyability(self):
        ranked = _rule_based_rank(
            [
                SchemeModel(
                    name="Closed Merit Scholarship",
                    source="NSP",
                    source_type="government",
                    match_score=3,
                    apply_link="https://example.com/closed",
                    deadline="2000-01-01",
                ),
                SchemeModel(
                    name="Open Merit Scholarship",
                    source="NSP",
                    source_type="government",
                    match_score=3,
                    apply_link="https://example.com/open",
                    deadline="2099-12-31",
                ),
            ]
        )

        self.assertEqual(ranked[0].name, "Open Merit Scholarship")
        open_scheme = next(item for item in ranked if item.name == "Open Merit Scholarship")
        closed_scheme = next(item for item in ranked if item.name == "Closed Merit Scholarship")

        self.assertEqual(open_scheme.status, "open")
        self.assertTrue(open_scheme.is_applyable)
        self.assertEqual(closed_scheme.status, "closed")
        self.assertFalse(closed_scheme.is_applyable)
        self.assertLess(closed_scheme.match_score, open_scheme.match_score)

    def test_demo_mode_prioritizes_open_private_direct_forms(self):
        ranked = _rule_based_rank(
            [
                SchemeModel(
                    name="Open Government Scheme",
                    source="NSP",
                    source_type="government",
                    match_score=4,
                    apply_link="https://scholarships.gov.in/apply",
                    deadline="2099-12-31",
                ),
                SchemeModel(
                    name="Direct Private Scholarship",
                    source="Buddy4Study",
                    source_type="private",
                    match_score=3,
                    apply_link="https://buddy4study.com/apply-now",
                    deadline="2099-12-31",
                    eligibility="Apply online now through the application form",
                ),
                SchemeModel(
                    name="Login Heavy Scholarship",
                    source="Buddy4Study",
                    source_type="private",
                    match_score=5,
                    apply_link="https://buddy4study.com/login",
                    deadline="2099-12-31",
                    eligibility="Login and OTP required before applying",
                ),
            ],
            demo_mode=True,
        )

        self.assertEqual(ranked[0].name, "Direct Private Scholarship")
        self.assertTrue(ranked[0].is_applyable)
        self.assertIn("direct form", ranked[0].match_reasons)
        self.assertEqual(ranked[-1].name, "Login Heavy Scholarship")
        self.assertIn("login wall", ranked[-1].match_reasons)
        self.assertFalse(ranked[-1].is_applyable)

    def test_tinyfish_ranking_passes_url_and_supports_instructions_signature(self):
        profile = {
            "state": "Jammu and Kashmir",
            "category": "OBC",
            "annual_income": 200000,
            "course_level": "undergraduate",
        }
        schemes = [
            SchemeModel(
                name="Open Merit Scholarship",
                source="Buddy4Study",
                source_type="private",
                apply_link="https://example.com/apply",
            )
        ]
        captured = {}

        def fake_run(*, url, instructions):
            captured["url"] = url
            captured["instructions"] = instructions
            return [
                {
                    "name": "Open Merit Scholarship",
                    "reason": "Direct application link available",
                    "priority": "high",
                }
            ]

        with patch("core.discovery.ranking.get_tinyfish_client", return_value=object()), patch(
            "core.discovery.ranking.discover_tinyfish_run_method",
            return_value=fake_run,
        ):
            ranked = rank_schemes(profile, schemes)

        self.assertEqual(captured["url"], "https://example.com/apply")
        self.assertIn("User profile:", captured["instructions"])
        self.assertIn("Prefer schemes that are still applyable today", captured["instructions"])
        self.assertEqual(ranked[0].tinyfish_priority, "high")
        self.assertEqual(ranked[0].name, "Open Merit Scholarship")

    def test_tinyfish_ranking_demotes_closed_schemes_after_agent_response(self):
        profile = {
            "state": "Jammu and Kashmir",
            "category": "OBC",
            "annual_income": 200000,
            "course_level": "undergraduate",
        }
        schemes = [
            SchemeModel(
                name="Closed Merit Scholarship",
                source="NSP",
                source_type="government",
                apply_link="https://example.com/closed",
                deadline="2000-01-01",
            ),
            SchemeModel(
                name="Open Merit Scholarship",
                source="NSP",
                source_type="government",
                apply_link="https://example.com/open",
                deadline="2099-12-31",
            ),
        ]

        def fake_run(*, url, instructions):
            self.assertEqual(url, "https://example.com/closed")
            self.assertIn("Prefer schemes that are still applyable today", instructions)
            return [
                {
                    "name": "Closed Merit Scholarship",
                    "reason": "Strong profile match",
                    "priority": "high",
                },
                {
                    "name": "Open Merit Scholarship",
                    "reason": "Still accepting applications",
                    "priority": "medium",
                },
            ]

        with patch("core.discovery.ranking.get_tinyfish_client", return_value=object()), patch(
            "core.discovery.ranking.discover_tinyfish_run_method",
            return_value=fake_run,
        ):
            ranked = rank_schemes(profile, schemes)

        self.assertEqual(ranked[0].name, "Open Merit Scholarship")
        self.assertEqual(ranked[0].status, "open")
        self.assertTrue(ranked[0].is_applyable)
        self.assertEqual(ranked[1].name, "Closed Merit Scholarship")
        self.assertEqual(ranked[1].status, "closed")
        self.assertFalse(ranked[1].is_applyable)

    def test_demo_mode_prompt_and_sort_prioritize_demo_ready_results(self):
        profile = {
            "state": "Jammu and Kashmir",
            "category": "OBC",
            "annual_income": 200000,
            "course_level": "undergraduate",
        }
        schemes = [
            SchemeModel(
                name="Government Portal Scheme",
                source="NSP",
                source_type="government",
                apply_link="https://scholarships.gov.in/",
                deadline="2099-12-31",
            ),
            SchemeModel(
                name="Direct Private Scholarship",
                source="Buddy4Study",
                source_type="private",
                apply_link="https://buddy4study.com/apply-now",
                deadline="2099-12-31",
                eligibility="Apply online now through the application form",
            ),
        ]

        captured = {}

        def fake_run(*, url, instructions):
            captured["url"] = url
            captured["instructions"] = instructions
            return [
                {
                    "name": "Government Portal Scheme",
                    "reason": "Official portal",
                    "priority": "high",
                },
                {
                    "name": "Direct Private Scholarship",
                    "reason": "Direct form",
                    "priority": "medium",
                },
            ]

        with patch("core.discovery.ranking.get_tinyfish_client", return_value=object()), patch(
            "core.discovery.ranking.discover_tinyfish_run_method",
            return_value=fake_run,
        ):
            ranked = rank_schemes(profile, schemes, demo_mode=True)

        self.assertIn("Demo mode priorities:", captured["instructions"])
        self.assertEqual(captured["url"], "https://buddy4study.com/apply-now")
        self.assertEqual(ranked[0].name, "Direct Private Scholarship")
        self.assertTrue(ranked[0].is_applyable)

    def test_format_ranked_output_includes_status_and_deadline(self):
        output = format_ranked_output(
            [
                SchemeModel(
                    name="National Scholarship",
                    source="NSP",
                    source_type="government",
                    match_score=3,
                    match_reasons=["state", "category"],
                    status="open",
                    deadline="2099-12-31",
                    applyability_score=5,
                    is_applyable=True,
                )
            ]
        )

        self.assertIn("+", output)
        self.assertIn("-", output)
        self.assertIn("|", output)
        self.assertIn("Status: open", output)
        self.assertIn("Applyable: yes", output)
        self.assertIn("Deadline: 2099-12-31", output)
        self.assertNotIn("â•", output)


if __name__ == "__main__":
    unittest.main()
