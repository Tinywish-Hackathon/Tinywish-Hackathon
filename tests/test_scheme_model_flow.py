import sys
import types
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

tinyfish_stub = types.ModuleType("tinyfish")
tinyfish_stub.TinyFish = object
sys.modules.setdefault("tinyfish", tinyfish_stub)

from core.discovery.eligibility import find_eligible_schemes
from core.discovery.multi_source import merge_schemes
from core.discovery.ranking import (
    _rule_based_rank,
    _rule_based_rank_with_profile,
    compute_apply_score,
    compute_deadline_score,
    ensure_source_diversity,
    filter_open_schemes,
    format_ranked_output,
    normalize_scheme_deadline_status,
    rank_schemes,
)
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
        self.assertIsInstance(scheme.deadline, datetime)
        self.assertEqual(scheme.deadline.strftime("%Y-%m-%d"), "2099-12-31")
        self.assertEqual(scheme.deadline_text, "2099-12-31")
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

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].name, "Open Merit Scholarship")
        open_scheme = ranked[0]
        self.assertEqual(open_scheme.status, "open")
        self.assertTrue(open_scheme.is_applyable)
        self.assertFalse(any(item.name == "Closed Merit Scholarship" for item in ranked))

    def test_compute_apply_score_prefers_actionable_direct_private_flows(self):
        direct_private = SchemeModel(
            name="Direct Private Scholarship",
            source="Buddy4Study",
            source_type="private",
            apply_link="https://buddy4study.com/apply-now",
            deadline="2099-12-31",
            eligibility="Apply online now through the application form",
        )
        nsp_redirect = SchemeModel(
            name="NSP Redirect Scholarship",
            source="Buddy4Study",
            source_type="private",
            apply_link="https://scholarships.gov.in/",
            deadline="2099-12-31",
            eligibility="Apply through the scholarship portal",
        )
        login_heavy = SchemeModel(
            name="Login Heavy Scholarship",
            source="Buddy4Study",
            source_type="private",
            apply_link="https://buddy4study.com/login",
            deadline="2099-12-31",
            eligibility="Login and OTP required before you can register and apply",
        )

        self.assertGreater(compute_apply_score(direct_private), compute_apply_score(nsp_redirect))
        self.assertGreater(compute_apply_score(nsp_redirect), compute_apply_score(login_heavy))

    def test_filter_open_schemes_skips_closed_items_and_logs(self):
        with patch("core.discovery.ranking.logger") as mock_logger:
            filtered = filter_open_schemes(
                [
                    SchemeModel(name="Expired Scheme", deadline="2000-01-01"),
                    SchemeModel(name="Open Scheme", deadline="2099-12-31"),
                    SchemeModel(name="Closed Text Scheme", status="expired"),
                ],
                active_logger=mock_logger,
                log_prefix="[DISCOVERY]",
            )

        self.assertEqual([scheme.name for scheme in filtered], ["Open Scheme"])
        mock_logger.info.assert_any_call("[DISCOVERY] Skipping closed scheme: Expired Scheme")
        mock_logger.info.assert_any_call("[DISCOVERY] Skipping closed scheme: Closed Text Scheme")

    def test_normalize_scheme_deadline_status_extracts_deadline_from_scheme_text(self):
        deadline_text = (date.today() + timedelta(days=5)).strftime("%d %b %Y")
        normalized = normalize_scheme_deadline_status(
            SchemeModel(
                name="Urgent Scholarship",
                eligibility=f"Applications close on {deadline_text}. Apply soon.",
            )
        )

        self.assertIsNotNone(normalized.deadline)
        self.assertEqual(normalized.deadline.strftime("%d %b %Y"), deadline_text)
        self.assertEqual(normalized.days_left, 5)
        self.assertEqual(normalized.urgency, "HIGH")
        self.assertFalse(normalized.is_expired)

    def test_filter_open_schemes_removes_past_dates_extracted_from_text(self):
        with patch("core.discovery.ranking.logger") as mock_logger:
            filtered = filter_open_schemes(
                [
                    SchemeModel(
                        name="Past Text Scheme",
                        eligibility="Last date to apply was 15 Jan 2000.",
                    ),
                    SchemeModel(name="Unknown Deadline Scheme"),
                ],
                active_logger=mock_logger,
                log_prefix="[DISCOVERY]",
            )

        self.assertEqual([scheme.name for scheme in filtered], ["Unknown Deadline Scheme"])
        mock_logger.info.assert_any_call("[DISCOVERY] Skipping closed scheme: Past Text Scheme")

    def test_deadline_urgency_increases_ranking_for_near_term_schemes(self):
        ranked = _rule_based_rank(
            [
                SchemeModel(
                    name="Low Urgency Scholarship",
                    source="Buddy4Study",
                    source_type="private",
                    match_score=5,
                    apply_link="https://buddy4study.com/apply-low",
                    deadline=(date.today() + timedelta(days=60)).strftime("%d %b %Y"),
                    eligibility="Apply online now through the application form",
                ),
                SchemeModel(
                    name="High Urgency Scholarship",
                    source="Buddy4Study",
                    source_type="private",
                    match_score=5,
                    apply_link="https://buddy4study.com/apply-high",
                    deadline=(date.today() + timedelta(days=5)).strftime("%d %b %Y"),
                    eligibility="Apply online now through the application form",
                ),
                SchemeModel(
                    name="Medium Urgency Scholarship",
                    source="Buddy4Study",
                    source_type="private",
                    match_score=5,
                    apply_link="https://buddy4study.com/apply-medium",
                    deadline=(date.today() + timedelta(days=20)).strftime("%d %b %Y"),
                    eligibility="Apply online now through the application form",
                ),
            ]
        )

        self.assertEqual(
            [scheme.name for scheme in ranked],
            [
                "High Urgency Scholarship",
                "Medium Urgency Scholarship",
                "Low Urgency Scholarship",
            ],
        )
        self.assertEqual(compute_deadline_score(ranked[0]), 2)
        self.assertEqual(compute_deadline_score(ranked[1]), 1)
        self.assertEqual(compute_deadline_score(ranked[2]), 0)

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
                    name="NSP Portal Scheme",
                    source="NSP",
                    source_type="government",
                    match_score=5,
                    apply_link="https://scholarships.gov.in/",
                    deadline="2099-12-31",
                    eligibility="Apply through the scholarship portal",
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
        self.assertGreater(
            ranked.index(next(item for item in ranked if item.name == "NSP Portal Scheme")),
            ranked.index(next(item for item in ranked if item.name == "Direct Private Scholarship")),
        )

    def test_rule_based_rank_prefers_actionable_scheme_over_nsp_redirect(self):
        ranked = _rule_based_rank(
            [
                SchemeModel(
                    name="NSP Redirect Scholarship",
                    source="Buddy4Study",
                    source_type="private",
                    match_score=4,
                    apply_link="https://scholarships.gov.in/",
                    deadline="2099-12-31",
                    eligibility="Apply through the scholarship portal",
                ),
                SchemeModel(
                    name="Direct Private Scholarship",
                    source="Buddy4Study",
                    source_type="private",
                    match_score=4,
                    apply_link="https://buddy4study.com/apply-now",
                    deadline="2099-12-31",
                    eligibility="Apply online now through the application form",
                ),
            ]
        )

        self.assertEqual(ranked[0].name, "Direct Private Scholarship")
        self.assertIn("external nsp redirect", ranked[1].match_reasons)

    def test_rule_based_rank_ensures_multiple_sources_in_top_results(self):
        ranked = _rule_based_rank(
            [
                SchemeModel(
                    name="NSP Scheme 1",
                    source="NSP",
                    source_type="government",
                    match_score=10,
                    apply_link="https://scholarships.gov.in/s1",
                    deadline="2099-12-31",
                ),
                SchemeModel(
                    name="NSP Scheme 2",
                    source="NSP",
                    source_type="government",
                    match_score=9,
                    apply_link="https://scholarships.gov.in/s2",
                    deadline="2099-12-31",
                ),
                SchemeModel(
                    name="NSP Scheme 3",
                    source="NSP",
                    source_type="government",
                    match_score=8,
                    apply_link="https://scholarships.gov.in/s3",
                    deadline="2099-12-31",
                ),
                SchemeModel(
                    name="NSP Scheme 4",
                    source="NSP",
                    source_type="government",
                    match_score=7,
                    apply_link="https://scholarships.gov.in/s4",
                    deadline="2099-12-31",
                ),
                SchemeModel(
                    name="NSP Scheme 5",
                    source="NSP",
                    source_type="government",
                    match_score=6,
                    apply_link="https://scholarships.gov.in/s5",
                    deadline="2099-12-31",
                ),
                SchemeModel(
                    name="Startup India Seed Fund Scheme",
                    source="Startup India",
                    source_type="government",
                    match_score=5,
                    apply_link="https://startupindia.gov.in/seed-fund",
                    deadline="2099-12-31",
                    eligibility="Apply online now through the application form",
                ),
                SchemeModel(
                    name="Buddy4Study Direct Scholarship",
                    source="Buddy4Study",
                    source_type="private",
                    match_score=4,
                    apply_link="https://buddy4study.com/apply-now",
                    deadline="2099-12-31",
                    eligibility="Apply online now through the application form",
                ),
            ]
        )

        top_sources = {scheme.source for scheme in ranked[:5]}

        self.assertGreaterEqual(len(top_sources), 2)
        self.assertIn("NSP", top_sources)
        self.assertTrue(any(source in {"Startup India", "Buddy4Study"} for source in top_sources))

    def test_ensure_source_diversity_is_noop_for_single_source_results(self):
        ranked = [
            SchemeModel(name="NSP Scheme 1", source="NSP", match_score=5),
            SchemeModel(name="NSP Scheme 2", source="NSP", match_score=4),
            SchemeModel(name="NSP Scheme 3", source="NSP", match_score=3),
        ]

        diversified = ensure_source_diversity(ranked, min_sources=2, window=5)

        self.assertEqual(
            [scheme.name for scheme in diversified],
            ["NSP Scheme 1", "NSP Scheme 2", "NSP Scheme 3"],
        )

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
            self.assertEqual(url, "https://example.com/open")
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

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].name, "Open Merit Scholarship")
        self.assertEqual(ranked[0].status, "open")
        self.assertTrue(ranked[0].is_applyable)
        self.assertFalse(any(item.name == "Closed Merit Scholarship" for item in ranked))

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
        self.assertIn("Avoid NSP and other government portal flows", captured["instructions"])
        self.assertEqual(captured["url"], "https://buddy4study.com/apply-now")
        self.assertEqual(ranked[0].name, "Direct Private Scholarship")
        self.assertTrue(ranked[0].is_applyable)

    def test_format_ranked_output_includes_status_and_deadline(self):
        scheme = normalize_scheme_deadline_status(
            SchemeModel(
                name="National Scholarship",
                source="NSP",
                source_type="government",
                match_score=3,
                match_reasons=["state", "category"],
                status="open",
                deadline=(date.today() + timedelta(days=5)).strftime("%Y-%m-%d"),
                applyability_score=5,
                is_applyable=True,
            )
        )
        output = format_ranked_output([scheme])

        self.assertIn("+", output)
        self.assertIn("-", output)
        self.assertIn("|", output)
        self.assertIn("Status: open", output)
        self.assertIn("Applyable: yes", output)
        self.assertIn("Deadline:", output)
        self.assertIn("days left", output)
        self.assertIn("[HIGH]", output)
        self.assertNotIn("â•", output)
    def test_format_ranked_output_marks_unknown_deadline(self):
        output = format_ranked_output(
            [
                SchemeModel(
                    name="Unknown Deadline Scheme",
                    source="NSP",
                    source_type="government",
                    match_score=1,
                    status="open",
                )
            ]
        )

        self.assertIn("Deadline: Unknown", output)


if __name__ == "__main__":
    unittest.main()
