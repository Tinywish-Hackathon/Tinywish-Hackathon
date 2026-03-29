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
_VISIBLE_APPLY_KEYWORDS = (
    "apply",
    "apply now",
    "apply online",
    "register",
    "register now",
    "start application",
    "application form",
    "continue application",
)
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


def _source_key(scheme: SchemeModel) -> str:
    return str(scheme.source or scheme.provider or scheme.source_type or "").strip().lower()


def _format_deadline_value(deadline_value: datetime | date | None) -> str:
    if isinstance(deadline_value, datetime):
        return deadline_value.strftime("%d %b %Y")
    if isinstance(deadline_value, date):
        return datetime.combine(deadline_value, datetime.min.time()).strftime("%d %b %Y")
    return ""


def _deadline_search_text(scheme: SchemeModel) -> str:
    parts = []
    deadline_text = str(scheme.deadline_text or "").strip()
    if deadline_text:
        parts.append(deadline_text)

    formatted_deadline = _format_deadline_value(scheme.deadline)
    if formatted_deadline and formatted_deadline not in parts:
        parts.append(formatted_deadline)

    return " ".join(parts).strip()


def _combined_text(scheme: SchemeModel) -> str:
    parts = [
        scheme.name,
        scheme.eligibility,
        scheme.category,
        scheme.state,
        scheme.course_level,
        scheme.provider,
        _deadline_search_text(scheme),
        scheme.status,
    ]
    return " ".join(str(part).strip() for part in parts if part).lower()


def _metadata_text(scheme: SchemeModel) -> str:
    parts = [
        _deadline_search_text(scheme),
        scheme.status,
        scheme.eligibility,
    ]
    return " ".join(str(part).strip() for part in parts if part).lower()


def _first_date_match(text: str) -> tuple[str, datetime | None]:
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
                return raw_value, datetime.strptime(normalized_value, fmt)
            except ValueError:
                continue

    return "", None


def _extract_deadline_value(scheme: SchemeModel) -> tuple[str, datetime | None]:
    if isinstance(scheme.deadline, datetime):
        explicit_deadline = _deadline_search_text(scheme) or _format_deadline_value(scheme.deadline)
        return explicit_deadline, scheme.deadline

    explicit_deadline = _deadline_search_text(scheme)
    if explicit_deadline:
        raw_value, parsed_value = _first_date_match(explicit_deadline)
        if parsed_value is not None:
            return raw_value or explicit_deadline, parsed_value

    eligibility = str(scheme.eligibility or "").strip()
    lowered = eligibility.lower()
    if any(hint in lowered for hint in _DEADLINE_HINTS):
        return _first_date_match(eligibility)

    return explicit_deadline, None


def _compute_days_left(parsed_deadline: datetime | date | None) -> int | None:
    if parsed_deadline is None:
        return None
    if isinstance(parsed_deadline, date) and not isinstance(parsed_deadline, datetime):
        return (parsed_deadline - date.today()).days
    return (parsed_deadline.date() - date.today()).days


def _compute_deadline_urgency(parsed_deadline: datetime | date | None, is_expired: bool) -> str:
    if parsed_deadline is None or is_expired:
        return "UNKNOWN"

    days_left = _compute_days_left(parsed_deadline)
    if days_left is None:
        return "UNKNOWN"
    if days_left <= 7:
        return "HIGH"
    if days_left <= 30:
        return "MEDIUM"
    return "LOW"


def _detect_deadline_status(scheme: SchemeModel, parsed_deadline: datetime | date | None) -> str:
    metadata_text = _metadata_text(scheme)
    if any(keyword in metadata_text for keyword in _CLOSED_STATUS_KEYWORDS):
        return "closed"
    if parsed_deadline is not None:
        deadline_date = parsed_deadline if isinstance(parsed_deadline, date) and not isinstance(parsed_deadline, datetime) else parsed_deadline.date()
        return "closed" if deadline_date < date.today() else "open"
    if any(keyword in metadata_text for keyword in _OPEN_STATUS_KEYWORDS):
        return "open"
    return "open"


def _format_deadline_summary(scheme: SchemeModel) -> str:
    if not scheme.deadline:
        return "Unknown"

    formatted_deadline = _format_deadline_value(scheme.deadline)
    urgency = str(scheme.urgency or "UNKNOWN").upper()
    if scheme.days_left is None:
        return f"{formatted_deadline} [{urgency}]"

    day_label = "day" if abs(scheme.days_left) == 1 else "days"
    return f"{formatted_deadline} ({scheme.days_left} {day_label} left) [{urgency}]"


def _has_application_signal(scheme: SchemeModel) -> bool:
    if str(scheme.apply_link or "").strip():
        return True

    source = str(scheme.source or "").strip().lower()
    if source in _KNOWN_PORTAL_SOURCES:
        return True

    text = f"{scheme.eligibility} {scheme.status} {_deadline_search_text(scheme)}".lower()
    return any(keyword in text for keyword in _APPLICATION_HINTS)


def _has_visible_apply_action(scheme: SchemeModel) -> bool:
    text = f"{_combined_text(scheme)} {str(scheme.apply_link or '').strip().lower()}"
    return any(keyword in text for keyword in _VISIBLE_APPLY_KEYWORDS)


def _is_login_heavy(scheme: SchemeModel) -> bool:
    text = _combined_text(scheme)
    link = str(scheme.apply_link or "").strip().lower()
    if any(keyword in text for keyword in _LOGIN_HEAVY_KEYWORDS):
        return True
    return any(keyword in link for keyword in ("login", "signin", "sign-in", "otp", "auth"))


def _is_external_nsp_redirect(scheme: SchemeModel) -> bool:
    apply_link = str(scheme.apply_link or "").strip().lower()
    source = str(scheme.source or "").strip().lower()
    if "scholarships.gov.in" not in apply_link:
        return False
    return source not in {"nsp", "national scholarship portal"}


def _is_nsp_portal_flow(scheme: SchemeModel) -> bool:
    apply_link = str(scheme.apply_link or "").strip().lower()
    source = str(scheme.source or "").strip().lower()
    return source in {"nsp", "national scholarship portal"} or "scholarships.gov.in" in apply_link


_ARTICLE_URL_PATTERNS = (
    "/articles/",
    "/blog/",
    "/news/",
    "/post/",
    "/list/",
    "/search",
    "medium.com",
    "wordpress.com",
    "blogspot.com",
)


def _has_article_link(scheme: SchemeModel) -> bool:
    """Detect if apply_link points to an article/listing page rather than a direct form."""
    link = str(scheme.apply_link or "").strip().lower()
    if not link:
        return False
    return any(pattern in link for pattern in _ARTICLE_URL_PATTERNS)


def _has_direct_form_signal(scheme: SchemeModel) -> bool:
    if not str(scheme.apply_link or "").strip():
        return False
    if _is_login_heavy(scheme):
        return False
    if _has_article_link(scheme):
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


def compute_apply_score(scheme: SchemeModel) -> int:
    normalized = normalize_scheme_deadline_status(scheme)
    score = 0

    if normalized.status == "closed":
        return -10

    if str(normalized.apply_link or "").strip():
        score += 2

    if _source_type(normalized) == "private":
        score += 3  # boosted: private portals have less friction

    if _has_visible_apply_action(normalized):
        score += 1

    if _has_direct_form_signal(normalized):
        score += 3  # boosted: direct forms are highest priority

    if _has_application_signal(normalized):
        score += 1

    if _has_article_link(normalized):
        score -= 2  # penalty: article/listing page, not a direct form

    if _is_login_heavy(normalized):
        score -= 4  # increased penalty: login/OTP friction

    if _is_external_nsp_redirect(normalized):
        score -= 2

    return score


def compute_deadline_score(scheme: SchemeModel) -> int:
    normalized = normalize_scheme_deadline_status(scheme)
    if normalized.status == "closed" or normalized.is_expired:
        return -10
    if normalized.urgency == "HIGH":
        return 2
    if normalized.urgency == "MEDIUM":
        return 1
    return 0


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
    normalized_scheme = normalize_scheme_deadline_status(scheme)
    status = normalized_scheme.status
    has_application_signal = _has_application_signal(normalized_scheme)
    login_heavy = _is_login_heavy(normalized_scheme)
    direct_form_signal = _has_direct_form_signal(normalized_scheme)
    applyability_score = compute_apply_score(normalized_scheme)
    deadline_score = compute_deadline_score(normalized_scheme)

    if str(normalized_scheme.apply_link or "").strip():
        if "apply link" not in reasons:
            reasons.append("apply link")

    if _source_type(normalized_scheme) == "private":
        if "private portal" not in reasons:
            reasons.append("private portal")

    if has_application_signal:
        if "application path" not in reasons:
            reasons.append("application path")

    if _has_visible_apply_action(normalized_scheme):
        if "visible apply action" not in reasons:
            reasons.append("visible apply action")

    if direct_form_signal:
        if "direct form" not in reasons:
            reasons.append("direct form")

    if status == "open":
        if "deadline open" not in reasons:
            reasons.append("deadline open")
    elif status == "closed":
        if "deadline closed" not in reasons:
            reasons.append("deadline closed")

    if normalized_scheme.urgency == "HIGH":
        if "deadline high urgency" not in reasons:
            reasons.append("deadline high urgency")
    elif normalized_scheme.urgency == "MEDIUM":
        if "deadline medium urgency" not in reasons:
            reasons.append("deadline medium urgency")

    if login_heavy:
        if "login wall" not in reasons:
            reasons.append("login wall")

    if _is_external_nsp_redirect(normalized_scheme):
        if "external nsp redirect" not in reasons:
            reasons.append("external nsp redirect")

    entry.deadline = normalized_scheme.deadline or entry.deadline
    entry.deadline_text = normalized_scheme.deadline_text or entry.deadline_text
    entry.status = status
    entry.is_expired = normalized_scheme.is_expired
    entry.days_left = normalized_scheme.days_left
    entry.urgency = normalized_scheme.urgency
    entry.applyability_score = applyability_score
    entry.is_applyable = status != "closed" and not normalized_scheme.is_expired and has_application_signal and not login_heavy
    entry.match_score = base_score + applyability_score + deadline_score
    entry.match_reasons = reasons
    return entry


def _demo_status_rank(scheme: SchemeModel) -> int:
    status = str(scheme.status or "").strip().lower()
    if status == "open":
        return 0
    return 1


def normalize_scheme_deadline_status(scheme: SchemeModel) -> SchemeModel:
    entry = _copy_scheme_fields(scheme)
    deadline_text, parsed_deadline = _extract_deadline_value(entry)
    entry.deadline = parsed_deadline or entry.deadline
    entry.deadline_text = deadline_text or entry.deadline_text or _format_deadline_value(entry.deadline)
    entry.status = _detect_deadline_status(entry, parsed_deadline or entry.deadline)
    entry.is_expired = entry.status == "closed"
    entry.days_left = _compute_days_left(entry.deadline)
    entry.urgency = _compute_deadline_urgency(entry.deadline, entry.is_expired)
    return entry


def filter_open_schemes(
    schemes: list[SchemeModel],
    active_logger=None,
    log_prefix="[DISCOVERY]",
) -> list[SchemeModel]:
    resolved_logger = active_logger or logger
    open_schemes = []

    for scheme in schemes:
        normalized = normalize_scheme_deadline_status(scheme)
        if normalized.status == "closed" or normalized.is_expired:
            resolved_logger.info(f"{log_prefix} Skipping closed scheme: {normalized.name}")
            continue
        open_schemes.append(normalized)

    return open_schemes


def _finalize_ranked_schemes(ranked_schemes: list[SchemeModel], demo_mode=False) -> list[SchemeModel]:
    def _apply_diversity(sorted_schemes: list[SchemeModel]) -> list[SchemeModel]:
        return ensure_source_diversity(sorted_schemes, min_sources=2, window=5)

    if demo_mode:
        sorted_schemes = sorted(
            ranked_schemes,
            key=lambda scheme: (
                _demo_status_rank(scheme),
                0 if scheme.is_applyable else 1,
                0 if _has_direct_form_signal(scheme) else 1,
                0 if _source_type(scheme) == "private" else 1,
                1 if _is_nsp_portal_flow(scheme) else 0,
                0 if str(scheme.apply_link or "").strip() else 1,
                0 if not _is_login_heavy(scheme) else 1,
                -int(scheme.applyability_score or 0),
                -int(scheme.match_score or 0),
                scheme.name.lower(),
            ),
        )
        return _apply_diversity(sorted_schemes)

    sorted_schemes = sorted(
        ranked_schemes,
        key=lambda scheme: (-scheme.match_score, -int(scheme.applyability_score or 0), scheme.name.lower()),
    )
    return _apply_diversity(sorted_schemes)


def ensure_source_diversity(
    ranked_schemes: list[SchemeModel],
    min_sources=2,
    window=5,
) -> list[SchemeModel]:
    ranked_list = list(ranked_schemes)
    if len(ranked_list) <= 1:
        return ranked_list

    all_sources = [_source_key(scheme) for scheme in ranked_list if _source_key(scheme)]
    if len(set(all_sources)) < min_sources:
        return ranked_list

    top_window_sources = {_source_key(scheme) for scheme in ranked_list[:window] if _source_key(scheme)}
    if len(top_window_sources) >= min_sources:
        return ranked_list

    promoted = []
    seen_sources = set()
    for index, scheme in enumerate(ranked_list):
        source_key = _source_key(scheme)
        if not source_key or source_key in seen_sources:
            continue
        promoted.append((index, scheme))
        seen_sources.add(source_key)
        if len(seen_sources) >= min_sources:
            break

    if len(seen_sources) < min_sources:
        return ranked_list

    promoted_indices = {index for index, _scheme in promoted}
    diversified = [scheme for _index, scheme in promoted]
    diversified.extend(scheme for index, scheme in enumerate(ranked_list) if index not in promoted_indices)
    return diversified


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
    schemes = filter_open_schemes(schemes, active_logger=logger, log_prefix="[RANKING]")
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
    combined = govt_ranked[:_GOVERNMENT_TOP_N] + private_ranked[:_PRIVATE_TOP_N]
    return ensure_source_diversity(combined, min_sources=2, window=5)


def _rule_based_rank_with_profile(profile, schemes: list[SchemeModel], demo_mode=False) -> list[SchemeModel]:
    schemes = filter_open_schemes(schemes, active_logger=logger, log_prefix="[RANKING]")
    govt_ranked = [_government_ranked_entry(profile, scheme) for scheme in schemes if _source_type(scheme) == "government"]
    private_ranked = [_private_ranked_entry(profile, scheme) for scheme in schemes if _source_type(scheme) == "private"]

    if demo_mode:
        combined = _finalize_ranked_schemes(govt_ranked + private_ranked, demo_mode=True)
        return combined[: _GOVERNMENT_TOP_N + _PRIVATE_TOP_N]

    govt_ranked = _finalize_ranked_schemes(govt_ranked)
    private_ranked = _finalize_ranked_schemes(private_ranked)
    combined = govt_ranked[:_GOVERNMENT_TOP_N] + private_ranked[:_PRIVATE_TOP_N]
    return ensure_source_diversity(combined, min_sources=2, window=5)


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
            "- Avoid NSP and other government portal flows when a private direct-form alternative exists\n"
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
        "+2 if deadline is within 7 days\n"
        "+1 if deadline is within 30 days\n"
        "+2 clear apply link\n"
        "+2 private portal with direct actionability\n"
        "+1 visible apply or register action\n"
        "+1 clear application path or portal signal\n"
        "-2 external redirect to NSP or another higher-friction portal\n"
        "-3 login-heavy or OTP-gated flow\n"
        "-5 if deadline is closed, expired, or clearly over\n"
        "\n"
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
            "deadline": _format_deadline_value(scheme.deadline) or "Unknown",
            "status": scheme.status,
            "is_expired": scheme.is_expired,
            "days_left": scheme.days_left,
            "urgency": scheme.urgency,
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
            logger.info(f"[RANKING] Ignoring unrecognized TinyFish result: {item.name}")
            continue
        source_entry.match_score = item.match_score
        source_entry.match_reasons = item.match_reasons
        source_entry.tinyfish_reason = item.tinyfish_reason
        source_entry.tinyfish_priority = item.tinyfish_priority
        source_entry.source_type = source_entry.source_type or _source_type(source_entry)
        merged_ranked.append(_apply_application_readiness(source_entry, source_entry))

    if not merged_ranked:
        return _rule_based_rank_with_profile(profile, schemes, demo_mode=demo_mode)

    return _finalize_ranked_schemes(merged_ranked, demo_mode=demo_mode)


def rank_schemes(profile, schemes: list[SchemeModel], demo_mode=False) -> list[SchemeModel]:
    """Rank eligible schemes with TinyFish, falling back to source-aware rule-based ranking."""
    if not schemes:
        return []

    open_schemes = filter_open_schemes(schemes, active_logger=logger, log_prefix="[RANKING]")
    if not open_schemes:
        return []

    try:
        return _tinyfish_rank(profile, open_schemes, demo_mode=demo_mode)
    except Exception as exc:
        logger.warning(f"[RANKING] Fallback to rule-based: {exc}")
        return _rule_based_rank_with_profile(profile, open_schemes, demo_mode=demo_mode)


def _recommend_strategy(scheme: SchemeModel) -> str:
    """Recommend an execution strategy for display in ranked output."""
    if scheme.status == "closed" or scheme.is_expired:
        return "SKIP"
    if _is_login_heavy(scheme):
        return "EXTRACT_ONLY"
    if _has_direct_form_signal(scheme):
        return "FULL_APPLY"
    if scheme.is_applyable:
        return "FULL_APPLY"
    return "EXTRACT_ONLY"


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
        deadline_summary = _format_deadline_summary(scheme)
        recommended = _recommend_strategy(scheme)

        name_line = f"{i}. {prefix} {scheme.name.strip()} (score: {scheme.match_score})"
        if i == 1:
            name_line = f"\u2605 BEST MATCH  {name_line}"

        entry_lines = [
            name_line,
            f"   Status: {status} | Applyable: {applyable} | Apply score: {scheme.applyability_score}",
        ]
        entry_lines.append(f"   Deadline: {deadline_summary}")
        entry_lines.append(f"   Recommended: {recommended}")
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
