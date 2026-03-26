"""Eligibility Engine — multi-criteria scheme matching against user profile.

Matches schemes to a user profile using state, category, income, and course
level. Designed to work with any scheme source (not NSP-specific) as long as
schemes have {"name": str, "eligibility": str} structure.
"""

import re
from utils.logger import get_logger

logger = get_logger("eligibility")

# Required profile fields for eligibility matching
_REQUIRED_FIELDS = ["state", "category", "annual_income", "course_level"]

# Category keyword variants
_CATEGORY_MAP = {
    "sc":      ["sc", "scheduled caste"],
    "st":      ["st", "scheduled tribe"],
    "obc":     ["obc", "other backward"],
    "general": ["general", "all category", "all students"],
}

# Course level keyword variants
_COURSE_MAP = {
    "school":        ["school", "class", "matric", "secondary", "pre-matric"],
    "undergraduate": ["undergraduate", "ug", "graduate", "degree",
                      "post-matric", "postmatric"],
    "postgraduate":  ["postgraduate", "pg", "masters", "post graduate"],
}


def _validate_profile(profile):
    """Ensure all required profile fields are present."""
    for key in _REQUIRED_FIELDS:
        if key not in profile or profile[key] is None:
            logger.error(f"[DISCOVERY] Missing required profile field: {key}")
            raise KeyError(f"Missing required profile field: {key}")


def _check_state(profile, text):
    """Check if profile state matches eligibility text."""
    state = profile["state"].lower()
    variants = [
        state,
        state.replace("and", "&").replace(" ", ""),
        state.replace("&", "and"),
        state.replace(" ", ""),
    ]

    # Universal matches
    if "all states" in text or "all india" in text:
        return True

    return any(v in text for v in variants)


def _check_category(profile, text):
    """Check if profile category matches eligibility text."""
    cat = profile["category"].lower()
    variants = _CATEGORY_MAP.get(cat, [cat])

    # Universal matches
    if "all categories" in text or "all category" in text:
        return True

    return any(v in text for v in variants)


def _extract_income_limit(text):
    """Extract the first income limit from eligibility text.

    Handles:
      "2.5 lakh"     → 250000
      "2,50,000"     → 250000
      "250000"       → 250000
      "rs. 2.5 lakh" → 250000

    Returns:
        float or None if no income limit found.
    """
    # Pattern 1: X lakh / X lakhs
    lakh_match = re.search(r'(\d+\.?\d*)\s*lakh', text)
    if lakh_match:
        return float(lakh_match.group(1)) * 100000

    # Pattern 2: Indian-style comma-separated numbers near income context
    # Look for numbers near "rs" or "income" or "₹"
    income_context = re.search(
        r'(?:rs\.?|₹|income|earning|annual)[\s.:]*'
        r'([\d,]+)',
        text
    )
    if income_context:
        num_str = income_context.group(1).replace(",", "")
        try:
            return float(num_str)
        except ValueError:
            pass

    # Pattern 3: Any large number (>= 10000) as fallback
    large_nums = re.findall(r'([\d,]{5,})', text)
    for num_str in large_nums:
        try:
            val = float(num_str.replace(",", ""))
            if val >= 10000:
                return val
        except ValueError:
            continue

    return None


def _check_income(profile, text):
    """Check if profile income fits within the eligibility limit."""
    limit = _extract_income_limit(text)
    if limit is None:
        return True  # Benefit of doubt if no limit specified

    return float(profile["annual_income"]) <= limit


def _check_course(profile, text):
    """Check if profile course level matches eligibility text."""
    level = profile["course_level"].lower()
    variants = _COURSE_MAP.get(level, [level])
    return any(v in text for v in variants)


def find_eligible_schemes(profile, schemes):
    """Find schemes matching the user profile.

    Args:
        profile: Dict with keys: state, category, annual_income, course_level.
        schemes: List of dicts with keys: name, eligibility.

    Returns:
        List of eligible scheme dicts with match_score and match_reasons.
    """
    _validate_profile(profile)

    results = []

    for scheme in schemes:
        text = scheme.get("eligibility", "").lower()
        name = scheme.get("name", "Unknown")

        # Run all four checks
        state_match = _check_state(profile, text)
        category_match = _check_category(profile, text)
        income_match = _check_income(profile, text)
        course_match = _check_course(profile, text)

        # Eligibility gate: must match state OR category
        eligible = state_match or category_match

        if not eligible:
            continue

        # Compute match score
        score = 0
        reasons = []

        if state_match:
            score += 2
            reasons.append("state")
        if category_match:
            score += 2
            reasons.append("category")
        if income_match:
            score += 1
            reasons.append("income")
        if course_match:
            score += 1
            reasons.append("course")

        results.append({
            "name": name,
            "eligibility": scheme.get("eligibility", ""),
            "match_score": score,
            "match_reasons": reasons,
        })

    logger.info(
        f"[DISCOVERY] Eligibility check: {len(results)} eligible "
        f"out of {len(schemes)} schemes"
    )

    return results
