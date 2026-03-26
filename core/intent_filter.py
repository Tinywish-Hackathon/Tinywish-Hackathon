"""Global Intent Filter — mode-aware click blocking for discovery vs apply flows.

Controls what the agent is allowed to click based on the current mode:
  - "discover": blocks login/apply/OTR clicks to prevent accidental auth flows
  - "apply": no restrictions (default)

Usage:
    from core.intent_filter import set_mode, should_block_click

    set_mode("discover")
    if should_block_click("Apply Now"):  # → True (blocked in discover mode)
        skip_click()
"""

from utils.logger import get_logger

logger = get_logger("intent_filter")

# --- Global mode state ---
_current_mode = "apply"  # default: no restrictions

# Keywords that must NEVER be clicked during discovery
DISCOVERY_BLOCKED = [
    "apply", "login", "otr", "register", "sign in",
    "sign up", "log in", "one time registration",
]


def set_mode(mode):
    """Set the global agent mode.

    Args:
        mode: "discover" or "apply"
    """
    global _current_mode
    if mode not in ("discover", "apply"):
        logger.warning(f"[INTENT] Unknown mode '{mode}', defaulting to 'apply'")
        mode = "apply"
    _current_mode = mode
    logger.info(f"[INTENT] Agent mode set to: {_current_mode}")


def get_mode():
    """Return the current global agent mode."""
    return _current_mode


def should_block_click(element_text):
    """Check if a click should be blocked based on current mode.

    Args:
        element_text: The text content of the element about to be clicked.

    Returns:
        True if the click should be blocked (discovery mode + blocked keyword).
        False otherwise (apply mode or safe keyword).
    """
    if _current_mode != "discover":
        return False

    if not element_text:
        return False

    text_lower = element_text.lower().strip()
    for blocked in DISCOVERY_BLOCKED:
        if blocked in text_lower:
            logger.info(f"[INTENT] Blocked click on '{element_text[:40]}' (discovery mode)")
            return True

    return False
