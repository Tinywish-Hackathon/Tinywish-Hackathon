"""Ranking Engine - TinyFish-based ranking with deterministic fallback."""

import json
import sys
from collections.abc import Callable

from core.integrations.tinyfish_client import discover_tinyfish_run_method, get_tinyfish_client
from schemas.scheme_model import SchemeModel
from utils.logger import get_logger

logger = get_logger("ranking")

_TOP_N = 5
_MAX_TINYFISH_INPUT = 20
_GOVERNMENT_TOP_N = 7
_PRIVATE_TOP_N = 3
_DEFAULT_TINYFISH_URL = "https://example.com/"

_CATEGORY_KEYWORDS = {
    "obc": ["obc", "backward", "ebc", "dnt", "other backward"],
    "sc": ["sc", "scheduled caste"],
    "st": ["st", "scheduled tribe"],
    "general": ["general", "open", "all", "all category", "all categories"],
}

_COURSE_KEYWORDS = {
    "school": ["school", "class", "matric", "secondary", "pre-matric"],
    "undergraduate": ["undergraduate", "ug", "graduation", "graduate", "degree", "post-matric"],
    "postgraduate": ["postgraduate", "pg", "masters", "post graduate", "phd", "doctoral"],
}


def _copy_scheme_fields(scheme: SchemeModel) -> SchemeModel:
    return scheme.model_copy(deep=True)


def _source_type(scheme: SchemeModel) -> str:
    source_type = str(scheme.source_type or "").strip().lower()
    if source_type:
        return source_type
    if scheme.provider:
        return "private"
    return "government"


def _combined_text(scheme: SchemeModel) -> str:
    parts = [
        scheme.name,
        scheme.eligibility,
        scheme.category,
        scheme.state,
        scheme.course_level,
        scheme.provider,
    ]
    return " ".join(str(part).strip() for part in parts if part).lower()


def _category_match(profile, scheme: SchemeModel, allow_open=False):
    category = str(profile.get("category", "") or "").strip().lower()
    terms = _CATEGORY_KEYWORDS.get(category, [category] if category else [])
    text = _combined_text(scheme)

    if any(term in text for term in terms if term):
        return True

    scheme_category = str(scheme.category or "").strip().lower()
    if scheme_category and any(term in scheme_category for term in terms if term):
        return True

    if allow_open and any(term in text for term in ["open", "all", "all category", "all categories"]):
        return True

    return False


def _state_match(profile, scheme: SchemeModel):
    state = str(profile.get("state", "") or "").strip().lower()
    if not state:
        return False

    text = _combined_text(scheme)
    compact_state = state.replace(" ", "")
    variants = {
        state,
        compact_state,
        state.replace("and", "&"),
        state.replace("&", "and"),
    }

    if "jammu" in state or "kashmir" in state or "j&k" in state:
        variants.update({"jammu", "kashmir", "j&k", "jk"})

    return any(variant and variant in text for variant in variants)


def _course_match(profile, scheme: SchemeModel):
    level = str(profile.get("course_level", "") or "").strip().lower()
    terms = _COURSE_KEYWORDS.get(level, [level] if level else [])
    text = _combined_text(scheme)
    return any(term in text for term in terms if term)


def _income_match(profile, scheme: SchemeModel):
    income_limit = scheme.income_limit
    annual_income = profile.get("annual_income")
    if income_limit in (None, "") or annual_income in (None, ""):
        return False

    try:
        return int(annual_income) <= int(income_limit)
    except (TypeError, ValueError):
        return False


def _ensure_reason_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _government_ranked_entry(profile, scheme: SchemeModel) -> SchemeModel:
    entry = _copy_scheme_fields(scheme)
    score = scheme.match_score or 0
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = 0

    reasons = _ensure_reason_list(scheme.match_reasons)

    if not reasons:
        if _category_match(profile, scheme):
            score += 2
            reasons.append("category")
        if _state_match(profile, scheme):
            score += 2
            reasons.append("state")
        if _course_match(profile, scheme):
            score += 1
            reasons.append("course")

    if _income_match(profile, scheme):
        score += 1
        if "income" not in reasons:
            reasons.append("income")

    entry.source_type = "government"
    entry.match_score = score
    entry.match_reasons = reasons
    return entry


def _private_ranked_entry(profile, scheme: SchemeModel) -> SchemeModel:
    entry = _copy_scheme_fields(scheme)
    score = 0
    reasons = []
    text = _combined_text(scheme)

    if _category_match(profile, scheme, allow_open=True):
        score += 2
        reasons.append("category/open")

    if _course_match(profile, scheme):
        score += 1
        reasons.append("course")

    if str(scheme.apply_link or "").strip():
        score += 1
        reasons.append("apply link")

    if "merit" in text or "open" in text:
        score += 1
        reasons.append("merit/open")

    entry.source_type = "private"
    entry.match_score = score
    entry.match_reasons = reasons
    return entry


def _rule_based_rank(schemes: list[SchemeModel]) -> list[SchemeModel]:
    """Fallback deterministic ranking with government-first source balancing."""
    govt_ranked = []
    private_ranked = []

    for scheme in schemes:
        entry = _copy_scheme_fields(scheme)
        entry.source_type = _source_type(scheme)
        entry.match_score = int(scheme.match_score or 0)
        entry.match_reasons = _ensure_reason_list(scheme.match_reasons)

        if entry.source_type == "private":
            text = _combined_text(scheme)
            if str(scheme.apply_link or "").strip():
                entry.match_score += 1
                if "apply link" not in entry.match_reasons:
                    entry.match_reasons.append("apply link")
            if "merit" in text or "open" in text:
                entry.match_score += 1
                if "merit/open" not in entry.match_reasons:
                    entry.match_reasons.append("merit/open")
            private_ranked.append(entry)
        else:
            govt_ranked.append(entry)

    govt_ranked.sort(key=lambda s: (-s.match_score, s.name.lower()))
    private_ranked.sort(key=lambda s: (-s.match_score, s.name.lower()))

    return govt_ranked[:_GOVERNMENT_TOP_N] + private_ranked[:_PRIVATE_TOP_N]


def _rule_based_rank_with_profile(profile, schemes: list[SchemeModel]) -> list[SchemeModel]:
    govt_ranked = [_government_ranked_entry(profile, scheme) for scheme in schemes if _source_type(scheme) == "government"]
    private_ranked = [_private_ranked_entry(profile, scheme) for scheme in schemes if _source_type(scheme) == "private"]

    govt_ranked.sort(key=lambda s: (-s.match_score, s.name.lower()))
    private_ranked.sort(key=lambda s: (-s.match_score, s.name.lower()))

    return govt_ranked[:_GOVERNMENT_TOP_N] + private_ranked[:_PRIVATE_TOP_N]


def _strip_code_fence(value):
    if not isinstance(value, str):
        return value

    cleaned = value.strip()
    if not cleaned.startswith("```"):
        return cleaned

    lines = cleaned.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    cleaned = "\n".join(lines).strip()
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    return cleaned


def _parse_tinyfish_ranking_response(response):
    """Normalize TinyFish ranking output into existing ranking shape."""

    def _materialize(value):
        if hasattr(value, "data") and value.data:
            return value.data
        if hasattr(value, "output") and value.output:
            return value.output
        if hasattr(value, "result") and value.result:
            return value.result
        return value

    payload = _materialize(response)

    if isinstance(payload, str):
        payload = _strip_code_fence(payload)
        payload = json.loads(payload)

    if isinstance(payload, dict):
        for key in ("data", "output", "result", "items", "results"):
            if key in payload:
                payload = payload[key]
                break

    if not isinstance(payload, list):
        raise ValueError("TinyFish ranking response is not a list")

    ranked: list[SchemeModel] = []
    for item in payload:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        if not name:
            continue

        reason = str(item.get("reason", "")).strip()

        raw_priority = item.get("priority", "")
        tinyfish_priority = str(raw_priority or "").strip().lower()
        try:
            match_score = int(raw_priority)
        except (TypeError, ValueError):
            priority_map = {"low": 1, "medium": 3, "high": 5}
            match_score = priority_map.get(tinyfish_priority, 0)

        if tinyfish_priority.isdigit():
            numeric_priority = int(tinyfish_priority)
            if numeric_priority >= 4:
                tinyfish_priority = "high"
            elif numeric_priority >= 2:
                tinyfish_priority = "medium"
            elif numeric_priority > 0:
                tinyfish_priority = "low"
            else:
                tinyfish_priority = ""

        ranked.append(
            SchemeModel(
                name=name,
                match_score=match_score,
                match_reasons=[reason] if reason else [],
                tinyfish_reason=reason,
                tinyfish_priority=tinyfish_priority,
            )
        )

    ranked.sort(key=lambda s: (-s.match_score, s.name.lower()))
    return ranked[:_TOP_N]


def _build_tinyfish_prompt(profile, scheme_payload):
    state = profile.get("state", "")
    category = profile.get("category", "")
    income = profile.get("annual_income", "")
    course = profile.get("course_level", "")

    schemes_json = json.dumps(scheme_payload, indent=2, ensure_ascii=False)

    return (
        "You are an AI system that ranks scholarship schemes.\n\n"
        f"User profile:\n"
        f"- State: {state}\n"
        f"- Category: {category}\n"
        f"- Income: {income}\n"
        f"- Course: {course}\n\n"
        "Score rules:\n"
        "+2 state match\n"
        "+2 category match\n"
        "+1 income fit\n"
        "+1 course match\n"
        "+1 private scholarship if apply_link exists\n\n"
        "Schemes:\n"
        f"{schemes_json}\n\n"
        "Return ONLY JSON:\n"
        "[\n"
        "  {\n"
        '    "name": "...",\n'
        '    "reason": "...",\n'
        '    "priority": 1-5\n'
        "  }\n"
        "]"
    )


def _resolve_tinyfish_url(schemes: list[SchemeModel]) -> str:
    for scheme in schemes:
        candidate = str(scheme.apply_link or "").strip()
        if candidate:
            return candidate
    return _DEFAULT_TINYFISH_URL


def _invoke_tinyfish_run_method(run_method: Callable, prompt: str, target_url: str):
    attempts = [
        {"url": target_url, "goal": prompt},
        {"url": target_url, "instructions": prompt},
        {"goal": prompt},
        {"instructions": prompt},
    ]
    last_error = None

    for kwargs in attempts:
        try:
            return run_method(**kwargs)
        except TypeError as exc:
            last_error = exc

    raise last_error or TypeError("No compatible TinyFish run signature found")


def _tinyfish_rank(profile, schemes: list[SchemeModel]) -> list[SchemeModel]:
    """Use TinyFish to rank schemes. Raises on failure."""
    top_candidates = schemes[:_MAX_TINYFISH_INPUT]
    scheme_payload = [
        {
            "name": scheme.name,
            "state": scheme.state or profile.get("state", ""),
            "category": scheme.category or profile.get("category", ""),
            "income_limit": scheme.income_limit,
            "course_level": scheme.course_level or profile.get("course_level", ""),
            "provider": scheme.provider,
            "eligibility": scheme.eligibility,
            "apply_link": scheme.apply_link,
            "source_type": _source_type(scheme),
        }
        for scheme in top_candidates
    ]

    prompt = _build_tinyfish_prompt(profile, scheme_payload)
    target_url = _resolve_tinyfish_url(top_candidates)
    client = get_tinyfish_client()
    run_method = discover_tinyfish_run_method(client, logger, "[RANKING]")
    if run_method is None:
        return _rule_based_rank_with_profile(profile, schemes)

    try:
        response = _invoke_tinyfish_run_method(run_method, prompt, target_url)
    except TypeError as e:
        logger.warning(f"[RANKING] TinyFish method invocation failed, using fallback: {e}")
        return _rule_based_rank_with_profile(profile, schemes)

    ranked = _parse_tinyfish_ranking_response(response)
    if not ranked:
        raise ValueError("TinyFish returned no ranked schemes")

    source_lookup = {
        candidate.name.strip().lower(): _copy_scheme_fields(candidate)
        for candidate in top_candidates
        if candidate.name
    }

    merged_ranked = []
    for item in ranked:
        source_entry = source_lookup.get(item.name.strip().lower())
        if not source_entry:
            item.source_type = item.source_type or "government"
            merged_ranked.append(item)
            continue
        source_entry.match_score = item.match_score
        source_entry.match_reasons = item.match_reasons
        source_entry.tinyfish_reason = item.tinyfish_reason
        source_entry.tinyfish_priority = item.tinyfish_priority
        source_entry.source_type = source_entry.source_type or _source_type(source_entry)
        merged_ranked.append(source_entry)

    return merged_ranked


def rank_schemes(profile, schemes: list[SchemeModel]) -> list[SchemeModel]:
    """Rank eligible schemes with TinyFish, falling back to source-aware rule-based ranking."""
    if not schemes:
        return []

    try:
        return _tinyfish_rank(profile, schemes)
    except Exception as e:
        logger.warning(f"[RANKING] Fallback to rule-based: {e}")
        return _rule_based_rank_with_profile(profile, schemes)


def format_ranked_output(ranked_schemes: list[SchemeModel]) -> str:
    """Format ranked schemes into a styled terminal output."""
    if not ranked_schemes:
        return "No eligible schemes found."

    display_names = []
    for scheme in ranked_schemes:
        source_type = _source_type(scheme)
        prefix = "[PVT]" if source_type == "private" else "[GOV]"
        display_names.append(f"{prefix} {scheme.name.strip()}")

    max_name_len = max(len(name) for name in display_names)
    content_width = max(max_name_len + 20, 44)
    box_width = content_width + 2
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"

    try:
        "╔╗╚╝╠╣═║".encode(encoding)
        chars = {
            "top_left": "╔",
            "top_right": "╗",
            "bottom_left": "╚",
            "bottom_right": "╝",
            "mid_left": "╠",
            "mid_right": "╣",
            "horizontal": "═",
            "vertical": "║",
        }
    except Exception:
        chars = {
            "top_left": "+",
            "top_right": "+",
            "bottom_left": "+",
            "bottom_right": "+",
            "mid_left": "+",
            "mid_right": "+",
            "horizontal": "-",
            "vertical": "|",
        }

    lines = []
    lines.append(chars["top_left"] + chars["horizontal"] * box_width + chars["top_right"])
    header = "ELIGIBLE SCHEMES FOR YOUR PROFILE"
    lines.append(chars["vertical"] + header.center(box_width) + chars["vertical"])
    lines.append(chars["mid_left"] + chars["horizontal"] * box_width + chars["mid_right"])

    for i, scheme in enumerate(ranked_schemes, 1):
        source_type = _source_type(scheme)
        prefix = "[PVT]" if source_type == "private" else "[GOV]"
        name = scheme.name.strip()
        score = scheme.match_score
        reasons = _ensure_reason_list(scheme.match_reasons)

        score_str = f"(score: {score})"
        name_line = f" {i}. {prefix} {name}"
        padding = box_width - len(name_line) - len(score_str) - 1
        if padding < 1:
            padding = 1
        lines.append(f"{chars['vertical']}{name_line}{' ' * padding}{score_str} {chars['vertical']}")

        if reasons:
            reasons_str = f"    Matched: {', '.join(reasons)}"
            pad2 = box_width - len(reasons_str)
            if pad2 < 0:
                pad2 = 0
            lines.append(f"{chars['vertical']}{reasons_str}{' ' * pad2}{chars['vertical']}")

    lines.append(chars["bottom_left"] + chars["horizontal"] * box_width + chars["bottom_right"])
    return "\n".join(lines)
