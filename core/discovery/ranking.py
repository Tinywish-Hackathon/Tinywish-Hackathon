"""Ranking Engine - TinyFish-based ranking with deterministic fallback."""

import json
import re
from collections.abc import Callable
from datetime import date, datetime

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

_CLOSED_STATUS_KEYWORDS = (
    "closed",
    "expired",
    "deadline over",
    "applications over",
    "application over",
    "not accepting applications",
    "no longer accepting",
)
_UPCOMING_STATUS_KEYWORDS = (
    "opening soon",
    "opens soon",
    "coming soon",
    "upcoming",
    "not yet open",
)
_OPEN_STATUS_KEYWORDS = (
    "applications open",
    "application open",
    "currently open",
    "ongoing",
    "apply now",
)
_DEADLINE_HINTS = (
    "deadline",
    "last date",
    "closing date",
    "apply by",
    "applications close",
    "application closes",
    "closes on",
    "ends on",
    "end date",
)
_APPLICATION_HINTS = (
    "apply",
    "application",
    "register",
    "portal",
    "submit",
    "login",
)
_KNOWN_PORTAL_SOURCES = {"nsp", "startup india", "myscheme"}
_LOGIN_HEAVY_KEYWORDS = (
    "login",
    "log in",
    "sign in",
    "signin",
    "otp",
    "one time password",
    "authenticate",
    "authentication",
    "register to continue",
)
_DATE_PATTERNS = [
    (re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"), ("%Y-%m-%d",)),
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"), ("%d/%m/%Y", "%m/%d/%Y")),
    (re.compile(r"\b\d{1,2}-\d{1,2}-\d{4}\b"), ("%d-%m-%Y", "%m-%d-%Y")),
    (re.compile(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b"), ("%d %B %Y", "%d %b %Y")),
    (
        re.compile(r"\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\b"),
        ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"),
    ),
]


def _copy_scheme_fields(scheme: SchemeModel) -> SchemeModel:
    return scheme.model_copy(deep=True)


def _source_type(scheme: SchemeModel) -> str:
    source_type = str(scheme.source_type or "").strip().lower()
    if source_type:
        return source_type

    source = str(scheme.source or "").strip().lower()
    if source in _KNOWN_PORTAL_SOURCES:
        return "government"
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
        scheme.deadline,
        scheme.status,
    ]
    return " ".join(str(part).strip() for part in parts if part).lower()


def _metadata_text(scheme: SchemeModel) -> str:
    parts = [
        scheme.deadline,
        scheme.status,
        scheme.eligibility,
    ]
    return " ".join(str(part).strip() for part in parts if part).lower()


def _first_date_match(text: str) -> tuple[str, date | None]:
    cleaned_text = str(text or "").strip()
    if not cleaned_text:
        return "", None

    for pattern, formats in _DATE_PATTERNS:
        match = pattern.search(cleaned_text)
        if not match:
            continue

        raw_value = match.group(0).strip()
        normalized_value = raw_value.replace("  ", " ").strip()
        for fmt in formats:
            try:
                return raw_value, datetime.strptime(normalized_value, fmt).date()
            except ValueError:
                continue

    return "", None


def _extract_deadline_value(scheme: SchemeModel) -> tuple[str, date | None]:
    explicit_deadline = str(scheme.deadline or "").strip()
    if explicit_deadline:
        raw_value, parsed_value = _first_date_match(explicit_deadline)
        return explicit_deadline or raw_value, parsed_value

    eligibility = str(scheme.eligibility or "").strip()
    lowered = eligibility.lower()
    if any(hint in lowered for hint in _DEADLINE_HINTS):
        return _first_date_match(eligibility)

    return "", None


def _detect_deadline_status(scheme: SchemeModel, parsed_deadline: date | None) -> str:
    metadata_text = _metadata_text(scheme)
    if any(keyword in metadata_text for keyword in _UPCOMING_STATUS_KEYWORDS):
        return "upcoming"
    if any(keyword in metadata_text for keyword in _CLOSED_STATUS_KEYWORDS):
        return "closed"
    if parsed_deadline is not None:
        return "closed" if parsed_deadline < date.today() else "open"
    if any(keyword in metadata_text for keyword in _OPEN_STATUS_KEYWORDS):
        return "open"
    return "unknown"


def _has_application_signal(scheme: SchemeModel) -> bool:
    if str(scheme.apply_link or "").strip():
        return True

    source = str(scheme.source or "").strip().lower()
    if source in _KNOWN_PORTAL_SOURCES:
        return True

    text = f"{scheme.eligibility} {scheme.status} {scheme.deadline}".lower()
    return any(keyword in text for keyword in _APPLICATION_HINTS)


def _is_login_heavy(scheme: SchemeModel) -> bool:
    text = _combined_text(scheme)
    link = str(scheme.apply_link or "").strip().lower()
    if any(keyword in text for keyword in _LOGIN_HEAVY_KEYWORDS):
        return True
    return any(keyword in link for keyword in ("login", "signin", "sign-in", "otp", "auth"))


def _has_direct_form_signal(scheme: SchemeModel) -> bool:
    if not str(scheme.apply_link or "").strip():
        return False
    if _is_login_heavy(scheme):
        return False

    text = _combined_text(scheme)
    direct_keywords = (
        "application form",
        "apply online",
        "apply now",
        "start application",
        "fill form",
    )
    if any(keyword in text for keyword in direct_keywords):
        return True

    return _source_type(scheme) == "private"


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


def _apply_application_readiness(entry: SchemeModel, scheme: SchemeModel) -> SchemeModel:
    base_score = int(entry.match_score or 0)
    reasons = _ensure_reason_list(entry.match_reasons)
    deadline_text, parsed_deadline = _extract_deadline_value(scheme)
    status = _detect_deadline_status(scheme, parsed_deadline)
    has_application_signal = _has_application_signal(scheme)
    login_heavy = _is_login_heavy(scheme)
    direct_form_signal = _has_direct_form_signal(scheme)
    applyability_score = 0

    if str(scheme.apply_link or "").strip():
        applyability_score += 2
        if "apply link" not in reasons:
            reasons.append("apply link")

    if _source_type(scheme) == "private":
        applyability_score += 1
        if "private portal" not in reasons:
            reasons.append("private portal")

    if has_application_signal:
        applyability_score += 1
        if "application path" not in reasons:
            reasons.append("application path")

    if direct_form_signal:
        applyability_score += 1
        if "direct form" not in reasons:
            reasons.append("direct form")

    if status == "open":
        applyability_score += 2
        if "deadline open" not in reasons:
            reasons.append("deadline open")
    elif status == "closed":
        applyability_score -= 5
        if "deadline closed" not in reasons:
            reasons.append("deadline closed")
    elif status == "upcoming":
        applyability_score -= 2
        if "not open yet" not in reasons:
            reasons.append("not open yet")

    if login_heavy:
        applyability_score -= 2
        if "login wall" not in reasons:
            reasons.append("login wall")

    entry.deadline = deadline_text or entry.deadline
    entry.status = status
    entry.applyability_score = applyability_score
    entry.is_applyable = status not in {"closed", "upcoming"} and has_application_signal and not login_heavy
    entry.match_score = base_score + applyability_score
    entry.match_reasons = reasons
    return entry


def _demo_status_rank(scheme: SchemeModel) -> int:
    status = str(scheme.status or "").strip().lower()
    if status == "open":
        return 0
    if status == "unknown":
        return 1
    if status == "upcoming":
        return 2
    return 3


def _finalize_ranked_schemes(ranked_schemes: list[SchemeModel], demo_mode=False) -> list[SchemeModel]:
    if demo_mode:
        return sorted(
            ranked_schemes,
            key=lambda scheme: (
                _demo_status_rank(scheme),
                0 if scheme.is_applyable else 1,
                0 if _has_direct_form_signal(scheme) else 1,
                0 if _source_type(scheme) == "private" else 1,
                0 if str(scheme.apply_link or "").strip() else 1,
                0 if not _is_login_heavy(scheme) else 1,
                -int(scheme.applyability_score or 0),
                -int(scheme.match_score or 0),
                scheme.name.lower(),
            ),
        )

    return sorted(ranked_schemes, key=lambda scheme: (-scheme.match_score, scheme.name.lower()))


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
    return _apply_application_readiness(entry, scheme)


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
    return _apply_application_readiness(entry, scheme)


def _rule_based_rank(schemes: list[SchemeModel], demo_mode=False) -> list[SchemeModel]:
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
            private_ranked.append(_apply_application_readiness(entry, scheme))
        else:
            govt_ranked.append(_apply_application_readiness(entry, scheme))

    if demo_mode:
        combined = _finalize_ranked_schemes(govt_ranked + private_ranked, demo_mode=True)
        return combined[: _GOVERNMENT_TOP_N + _PRIVATE_TOP_N]

    govt_ranked = _finalize_ranked_schemes(govt_ranked)
    private_ranked = _finalize_ranked_schemes(private_ranked)
    return govt_ranked[:_GOVERNMENT_TOP_N] + private_ranked[:_PRIVATE_TOP_N]


def _rule_based_rank_with_profile(profile, schemes: list[SchemeModel], demo_mode=False) -> list[SchemeModel]:
    govt_ranked = [_government_ranked_entry(profile, scheme) for scheme in schemes if _source_type(scheme) == "government"]
    private_ranked = [_private_ranked_entry(profile, scheme) for scheme in schemes if _source_type(scheme) == "private"]

    if demo_mode:
        combined = _finalize_ranked_schemes(govt_ranked + private_ranked, demo_mode=True)
        return combined[: _GOVERNMENT_TOP_N + _PRIVATE_TOP_N]

    govt_ranked = _finalize_ranked_schemes(govt_ranked)
    private_ranked = _finalize_ranked_schemes(private_ranked)
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


def _build_tinyfish_prompt(profile, scheme_payload, demo_mode=False):
    state = profile.get("state", "")
    category = profile.get("category", "")
    income = profile.get("annual_income", "")
    course = profile.get("course_level", "")

    schemes_json = json.dumps(scheme_payload, indent=2, ensure_ascii=False)

    demo_block = ""
    if demo_mode:
        demo_block = (
            "Demo mode priorities:\n"
            "- Prefer schemes that are open right now\n"
            "- Prefer direct forms and pre-auth application pages\n"
            "- Prefer private portals when they reduce friction\n"
            "- Penalize login-heavy or OTP-blocked flows\n\n"
        )

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
        "+2 current application deadline still open\n"
        "+2 clear apply link\n"
        "+1 clear application path or portal signal\n"
        "-5 if deadline is closed, expired, or clearly over\n"
        "-2 if applications are not open yet\n\n"
        "Prefer schemes that are still applyable today. Closed schemes should rank lower even if otherwise relevant.\n\n"
        f"{demo_block}"
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


def _resolve_tinyfish_url(schemes: list[SchemeModel], demo_mode=False) -> str:
    ordered_schemes = _finalize_ranked_schemes(schemes, demo_mode=demo_mode) if demo_mode else schemes
    for scheme in ordered_schemes:
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


def _tinyfish_rank(profile, schemes: list[SchemeModel], demo_mode=False) -> list[SchemeModel]:
    """Use TinyFish to rank schemes. Raises on failure."""
    top_candidates = schemes[:_MAX_TINYFISH_INPUT]
    prepared_candidates = [
        _apply_application_readiness(_copy_scheme_fields(candidate), candidate)
        for candidate in top_candidates
    ]
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
            "deadline": scheme.deadline,
            "status": scheme.status,
            "is_applyable": scheme.is_applyable,
            "applyability_score": scheme.applyability_score,
            "login_heavy": _is_login_heavy(scheme),
            "direct_form_signal": _has_direct_form_signal(scheme),
        }
        for scheme in prepared_candidates
    ]

    prompt = _build_tinyfish_prompt(profile, scheme_payload, demo_mode=demo_mode)
    target_url = _resolve_tinyfish_url(prepared_candidates, demo_mode=demo_mode)
    client = get_tinyfish_client()
    run_method = discover_tinyfish_run_method(client, logger, "[RANKING]")
    if run_method is None:
        return _rule_based_rank_with_profile(profile, schemes, demo_mode=demo_mode)

    try:
        response = _invoke_tinyfish_run_method(run_method, prompt, target_url)
    except TypeError as exc:
        logger.warning(f"[RANKING] TinyFish method invocation failed, using fallback: {exc}")
        return _rule_based_rank_with_profile(profile, schemes, demo_mode=demo_mode)

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
            merged_ranked.append(_apply_application_readiness(item, item))
            continue
        source_entry.match_score = item.match_score
        source_entry.match_reasons = item.match_reasons
        source_entry.tinyfish_reason = item.tinyfish_reason
        source_entry.tinyfish_priority = item.tinyfish_priority
        source_entry.source_type = source_entry.source_type or _source_type(source_entry)
        merged_ranked.append(_apply_application_readiness(source_entry, source_entry))

    return _finalize_ranked_schemes(merged_ranked, demo_mode=demo_mode)


def rank_schemes(profile, schemes: list[SchemeModel], demo_mode=False) -> list[SchemeModel]:
    """Rank eligible schemes with TinyFish, falling back to source-aware rule-based ranking."""
    if not schemes:
        return []

    try:
        return _tinyfish_rank(profile, schemes, demo_mode=demo_mode)
    except Exception as exc:
        logger.warning(f"[RANKING] Fallback to rule-based: {exc}")
        return _rule_based_rank_with_profile(profile, schemes, demo_mode=demo_mode)


def format_ranked_output(ranked_schemes: list[SchemeModel]) -> str:
    """Format ranked schemes into a styled terminal output."""
    if not ranked_schemes:
        return "No eligible schemes found."

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

    rows = []
    for i, scheme in enumerate(ranked_schemes, 1):
        source_type = _source_type(scheme)
        prefix = "[PVT]" if source_type == "private" else "[GOV]"
        reasons = _ensure_reason_list(scheme.match_reasons)
        status = str(scheme.status or "unknown").strip() or "unknown"
        applyable = "yes" if scheme.is_applyable else "no"
        deadline = str(scheme.deadline or "").strip()

        entry_lines = [
            f"{i}. {prefix} {scheme.name.strip()} (score: {scheme.match_score})",
            f"   Status: {status} | Applyable: {applyable} | Apply score: {scheme.applyability_score}",
        ]
        if deadline:
            entry_lines.append(f"   Deadline: {deadline}")
        if reasons:
            entry_lines.append(f"   Matched: {', '.join(reasons)}")
        rows.append(entry_lines)

    header = "ELIGIBLE SCHEMES FOR YOUR PROFILE"
    content_width = max(
        len(header),
        max(len(line) for row in rows for line in row),
    )
    box_width = content_width + 2

    lines = [
        chars["top_left"] + chars["horizontal"] * box_width + chars["top_right"],
        chars["vertical"] + header.center(box_width) + chars["vertical"],
        chars["mid_left"] + chars["horizontal"] * box_width + chars["mid_right"],
    ]

    for row in rows:
        for line in row:
            lines.append(f"{chars['vertical']} {line.ljust(content_width)} {chars['vertical']}")

    lines.append(chars["bottom_left"] + chars["horizontal"] * box_width + chars["bottom_right"])
    return "\n".join(lines)
