import json
import os
from utils.logger import get_logger

logger = get_logger("helpers")

def load_profile(path):
    """Load and validate user profile from a JSON file."""
    if not os.path.exists(path):
        logger.error(f"Profile not found: {path}")
        raise FileNotFoundError(f"Profile not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        profile = json.load(f)

    logger.info(f"Loaded profile for: {profile.get('full_name', 'UNKNOWN')}")
    return profile


def load_and_validate_profile(path):
    """Load JSON profile and validate using Pydantic UserProfile schema.

    Args:
        path: Path to the profile JSON file.

    Returns:
        Validated UserProfile instance.

    Raises:
        FileNotFoundError: If file doesn't exist.
        pydantic.ValidationError: If profile data is invalid.
    """
    from schemas.profile_schema import UserProfile

    raw = load_profile(path)

    try:
        profile = UserProfile(**raw)
        logger.info(f"Profile validated: {profile.full_name} ({profile.email})")
        return profile
    except Exception as e:
        logger.error(f"Profile validation failed: {e}")
        raise

