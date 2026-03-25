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
