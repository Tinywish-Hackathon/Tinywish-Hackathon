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
    """Find schemes matching the user profile using scheme-name heuristics."""
    _validate_profile(profile)

    state_name = str(profile.get("state", "")).lower()
    category = str(profile.get("category", "")).lower()
    course_level = str(profile.get("course_level", "")).lower()

    category_terms = {
        "obc": ["obc", "backward", "ebc", "dnt"],
        "sc": ["sc", "scheduled caste"],
        "st": ["st", "scheduled tribe"],
        "general": ["general", "all india", "national"],
    }.get(category, [category])

    if course_level in {"undergraduate", "ug", "graduation", "graduate"}:
        course_terms = ["post matric", "post-matric", "graduation", "undergraduate"]
    else:
        course_terms = _COURSE_MAP.get(course_level, [course_level])

    target_state_terms = ["jammu", "kashmir", "j&k"]
    known_state_terms = [
        "andhra", "arunachal", "assam", "bihar", "chandigarh", "chhattisgarh",
        "dadra", "daman", "delhi", "goa", "gujarat", "haryana", "himachal",
        "jharkhand", "karnataka", "kerala", "ladakh", "lakshadweep", "madhya",
        "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland", "odisha",
        "orissa", "punjab", "rajasthan", "sikkim", "tamil", "telangana",
        "tripura", "uttar", "uttarakhand", "bengal", "west bengal", "puducherry",
        "pondicherry", "state", "union territory",
    ]

    def _normalize_name(scheme):
        return str(scheme.get("name", "")).strip()

    def _is_generic_or_all_india(name_text):
        if "all india" in name_text or "national" in name_text:
            return True
        return not any(term in name_text for term in known_state_terms)

    results = []

    for scheme in schemes:
        name = _normalize_name(scheme)
        if not name:
            continue

        lowered_name = name.lower()

        category_match = any(term in lowered_name for term in category_terms if term)
        state_match = any(term in lowered_name for term in target_state_terms)
        if not state_match and (
            "jammu" in state_name or "kashmir" in state_name or "j&k" in state_name
        ):
            state_match = _is_generic_or_all_india(lowered_name)

        course_match = any(term in lowered_name for term in course_terms if term)

        if not (category_match or state_match):
            continue

        score = 0
        reasons = []

        if category_match:
            score += 2
            reasons.append("category")
        if state_match:
            score += 2
            reasons.append("state")
        if course_match:
            score += 1
            reasons.append("course")

        results.append({
            "name": name,
            "match_score": score,
            "match_reasons": reasons,
        })

    results.sort(key=lambda item: (-item["match_score"], item["name"].lower()))

    logger.info(
        f"[DISCOVERY] Eligibility check: {len(results)} eligible "
        f"out of {len(schemes)} schemes"
    )

    return results
