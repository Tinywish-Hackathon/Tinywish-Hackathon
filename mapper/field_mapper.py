"""Intelligent field mapping: profile data → form fields."""
from utils.logger import get_logger

logger = get_logger("field_mapper")

# Keyword → profile attribute mapping rules
# Each key is a profile field name, value is a list of keywords to match against
FIELD_KEYWORDS = {
    "full_name":  ["name", "full name", "applicant name", "student name", "candidate name"],
    "email":      ["email", "e-mail", "email id", "mail"],
    "phone":      ["phone", "mobile", "contact number", "mobile number", "telephone"],
    "aadhaar":    ["aadhaar", "aadhar", "aadhaar number", "uid"],
    "dob":        ["dob", "date of birth", "birth date", "birthday"],
    "gender":     ["gender", "sex"],
    "address":    ["address", "residential address", "permanent address"],
    "education":  ["education", "qualification", "degree", "course"],
    "category":   ["category", "caste", "social category", "reservation"],
    "income":     ["income", "annual income", "family income"],
    "state":      ["state", "state name", "domicile"],
    "password":   ["password", "pass"],
}

# Fields to NEVER fill automatically
SKIP_FIELDS = {"captcha", "otp", "verification", "security code", "verify"}


def _normalize(text):
    """Lowercase, strip, collapse whitespace."""
    if not text:
        return ""
    return " ".join(text.lower().strip().split())


def _get_field_label(field_info):
    """Extract the best human-readable label from a field info dict."""
    for key in ["label", "placeholder", "name"]:
        val = field_info.get(key)
        if val and val.strip():
            return val
    return ""


def _should_skip(label):
    """Return True if this field should never be auto-filled."""
    normalized = _normalize(label)
    for skip in SKIP_FIELDS:
        if skip in normalized:
            return True
    return False


def _match_profile_key(label, profile_dict):
    """Match a field label to a profile key using keyword rules.

    Returns (profile_key, value) or (None, None).
    """
    normalized = _normalize(label)
    if not normalized:
        return None, None

    for profile_key, keywords in FIELD_KEYWORDS.items():
        for keyword in keywords:
            if keyword in normalized:
                value = profile_dict.get(profile_key)
                if value is not None and str(value).strip():
                    return profile_key, str(value)
                break  # keyword matched but no value in profile

    return None, None


def map_profile_to_fields(profile, fields):
    """Map profile data to extracted form fields.

    Args:
        profile: Dict or UserProfile object with user data.
        fields: List of field info dicts from extract_input_fields().

    Returns:
        List of dicts: [{"selector": str, "value": str, "label": str, "profile_key": str}]
    """
    # Convert Pydantic model to dict if needed
    if hasattr(profile, "model_dump"):
        profile_dict = profile.model_dump()
    elif hasattr(profile, "dict"):
        profile_dict = profile.dict()
    else:
        profile_dict = dict(profile)

    mapped = []
    skipped = []

    for field_info in fields:
        label = _get_field_label(field_info)
        selector = field_info.get("selector", "")

        # Skip unsafe fields
        if _should_skip(label):
            skipped.append(f"{label} (unsafe)")
            continue

        # Skip password fields for safety
        field_type = field_info.get("type", "")
        if field_type == "password":
            skipped.append(f"{label} (password)")
            continue

        # Try to match
        profile_key, value = _match_profile_key(label, profile_dict)

        if profile_key and value:
            mapped.append({
                "selector": selector,
                "value": value,
                "label": label,
                "profile_key": profile_key,
            })
        else:
            skipped.append(label or "(unlabeled)")

    logger.info(f"Mapped {len(mapped)} field(s) to profile data")
    if mapped:
        for m in mapped:
            logger.info(f"  ✔ '{m['label']}' → {m['profile_key']} = '{m['value'][:30]}'")
    if skipped:
        logger.debug(f"  Skipped {len(skipped)} field(s): {skipped[:10]}")

    return mapped
