"""Ranking Engine - TinyFish-based ranking with deterministic fallback."""

import json

from core.integrations.tinyfish_client import get_tinyfish_client
from utils.logger import get_logger

logger = get_logger("ranking")

_TOP_N = 5
_MAX_TINYFISH_INPUT = 20


def _rule_based_rank(schemes, top_n=_TOP_N):
    """Fallback deterministic ranking based on existing match score."""
    def _effective_score(scheme):
        score = scheme.get("match_score", 0)
        if scheme.get("source_type") == "private" and scheme.get("apply_link"):
            score += 1
        return score

    sorted_schemes = sorted(
        schemes,
        key=lambda s: (-_effective_score(s), s.get("name", "").lower())
    )
    return sorted_schemes[:top_n]


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

    ranked = []
    for item in payload:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        if not name:
            continue

        priority = item.get("priority", 0)
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            priority = 0

        reason = str(item.get("reason", "")).strip()

        ranked.append({
            "name": name,
            "reason": reason,
            "priority": priority,
            "match_score": priority,
            "match_reasons": [reason] if reason else [],
        })

    ranked.sort(key=lambda s: (-s.get("priority", 0), s.get("name", "").lower()))
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


def _tinyfish_rank(profile, schemes):
    """Use TinyFish to rank schemes. Raises on failure."""
    top_candidates = schemes[:_MAX_TINYFISH_INPUT]
    scheme_payload = [
        {
            "name": scheme.get("name", ""),
            "state": scheme.get("state", profile.get("state", "")),
            "category": scheme.get("category", profile.get("category", "")),
            "income_limit": scheme.get("income_limit"),
            "course_level": scheme.get("course_level", profile.get("course_level", "")),
            "provider": scheme.get("provider", ""),
            "eligibility": scheme.get("eligibility", ""),
            "apply_link": scheme.get("apply_link", ""),
            "type": scheme.get("type", ""),
            "source_type": scheme.get("source_type", ""),
        }
        for scheme in top_candidates
    ]

    prompt = _build_tinyfish_prompt(profile, scheme_payload)
    client = get_tinyfish_client()
    logger.info("[RANKING] Using TinyFish via client.run")
    response = client.run(prompt=prompt)
    ranked = _parse_tinyfish_ranking_response(response)
    if ranked:
        return ranked
    raise ValueError("TinyFish returned no ranked schemes")


def rank_schemes(profile, schemes):
    """Rank eligible schemes with TinyFish, falling back to rule-based ranking."""
    if not schemes:
        return []

    try:
        return _tinyfish_rank(profile, schemes)
    except Exception as e:
        logger.warning(f"[RANKING] Fallback to rule-based: {e}")
        return _rule_based_rank(schemes)


def format_ranked_output(ranked_schemes):
    """Format ranked schemes into a styled terminal output."""
    if not ranked_schemes:
        return "No eligible schemes found."

    max_name_len = max(len(s["name"]) for s in ranked_schemes)
    content_width = max(max_name_len + 20, 44)
    box_width = content_width + 2

    lines = []
    lines.append("╔" + "═" * box_width + "╗")
    header = "ELIGIBLE SCHEMES FOR YOUR PROFILE"
    lines.append("║" + header.center(box_width) + "║")
    lines.append("╠" + "═" * box_width + "╣")

    for i, scheme in enumerate(ranked_schemes, 1):
        name = scheme["name"]
        score = scheme.get("priority", scheme.get("match_score", 0))
        reasons = scheme.get("match_reasons", [])

        score_str = f"(score: {score})"
        name_line = f" {i}. {name}"
        padding = box_width - len(name_line) - len(score_str) - 1
        if padding < 1:
            padding = 1
        lines.append(f"║{name_line}{' ' * padding}{score_str} ║")

        if reasons:
            reasons_str = f"    Matched: {', '.join(reasons)}"
            pad2 = box_width - len(reasons_str)
            if pad2 < 0:
                pad2 = 0
            lines.append(f"║{reasons_str}{' ' * pad2}║")

    lines.append("╚" + "═" * box_width + "╝")
    return "\n".join(lines)
