"""Global Intent Scanner — priority-based action detection.

Before executing rigid flow steps, this module scans the current page
for high-priority direct actions (e.g., "Apply Now") and short-circuits
the navigation when a match is found.
"""
from executor.actions import find_by_text_fuzzy, safe_click, _is_clickable, _get_element_info
from utils.logger import get_logger

logger = get_logger("intent")

# --- Priority tiers (higher number = higher priority) ---
HIGH_PRIORITY = {
    "keywords": [
        "apply now", "apply for scholarship", "start application",
        "register now", "login to apply", "apply",
    ],
    "score": 3,
}

MEDIUM_PRIORITY = {
    "keywords": [
        "otr", "one time registration", "get your otr",
        "new registration", "register",
    ],
    "score": 2,
}

LOW_PRIORITY = {
    "keywords": [
        "students", "student corner", "student login",
        "dashboard", "home", "info",
    ],
    "score": 1,
}

PRIORITY_TIERS = [HIGH_PRIORITY, MEDIUM_PRIORITY, LOW_PRIORITY]


def global_intent_scan(page, intent="apply"):
    """Scan the current page for high-priority direct actions.

    Checks the page for actionable elements matching priority keywords,
    starting from the highest tier. If a clickable match is found, it is
    clicked immediately, short-circuiting multi-step navigation.

    Args:
        page: Playwright page object.
        intent: The broad goal of the agent (e.g., "apply", "register").
                Used to adjust priority scanning order.

    Returns:
        Dict with:
            - "found": bool — whether a direct action was taken
            - "matched_text": str or None — the text of the matched element
            - "priority": int — the priority tier (3=high, 2=med, 1=low)
            - "skipped_steps": list — labels of steps that can be skipped
    """
    logger.info(f"[INTENT] Scanning page for direct actions (intent='{intent}')...")

    # Determine scan order based on intent
    if intent == "register":
        scan_order = [MEDIUM_PRIORITY, HIGH_PRIORITY]
    else:
        scan_order = [HIGH_PRIORITY, MEDIUM_PRIORITY]

    for tier in scan_order:
        keywords = tier["keywords"]
        score = tier["score"]

        logger.debug(f"[INTENT] Checking tier (score={score}): {keywords[:5]}...")

        el, matched = find_by_text_fuzzy(page, keywords, clickable_only=True)

        if el:
            info = _get_element_info(el)

            # Only proceed if element is genuinely clickable
            if not _is_clickable(el):
                logger.debug(
                    f"[INTENT] Found '{matched}' but <{info['tag']}> is not clickable, skipping"
                )
                continue

            logger.info(
                f"[INTENT] Direct action found: '{matched}' "
                f"<{info['tag']}> priority={score}"
            )

            # Click it
            clicked = safe_click(page, el, label=f"[INTENT] Direct: '{matched}'")

            if clicked:
                logger.info(f"[INTENT] Direct action taken: '{matched}' (priority={score})")
                return {
                    "found": True,
                    "matched_text": matched,
                    "priority": score,
                    "skipped_steps": _get_skippable_steps(score),
                }
            else:
                logger.warning(f"[INTENT] Click failed for '{matched}', continuing scan")

    logger.info("[INTENT] No direct action found, proceeding with normal flow")
    return {"found": False, "matched_text": None, "priority": 0, "skipped_steps": []}


def _get_skippable_steps(priority_score):
    """Determine which step types can be skipped based on the priority of the action taken.

    If a HIGH priority action (score=3) like "Apply Now" was clicked directly,
    all navigation steps (Students, OTR, Apply) can be skipped.
    """
    if priority_score >= 3:
        return ["click", "click_fuzzy", "detect"]
    elif priority_score >= 2:
        return ["click", "detect"]
    return []


def should_skip_step(step, intent_result):
    """Determine if a specific flow step should be skipped after an intent action.

    Args:
        step: The flow step dict.
        intent_result: The result dict from global_intent_scan().

    Returns:
        True if the step should be skipped.
    """
    if not intent_result.get("found"):
        return False

    action = step.get("action", "click")
    skippable = intent_result.get("skipped_steps", [])

    # Never skip wait or fill_form steps
    if action in ("wait", "fill_form"):
        return False

    if action in skippable:
        logger.info(f"[INTENT] Skipping step '{step.get('label', '?')}' (action={action})")
        return True

    return False
