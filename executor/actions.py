import time
from utils.logger import get_logger

logger = get_logger("actions")


def get_visible(locator):
    """Return the first visible element from a locator, or None."""
    for i in range(locator.count()):
        el = locator.nth(i)
        try:
            if el.is_visible():
                return el
        except Exception:
            continue
    return None


def find_by_text_fuzzy(page, candidates, exact=False):
    """Search for the first visible element matching ANY candidate text.

    Args:
        page: Playwright page object.
        candidates: List of text strings to search for (case-insensitive).
        exact: If True, use exact text match. If False, use substring/contains.

    Returns:
        Tuple of (element, matched_candidate) or (None, None).
    """
    for candidate in candidates:
        search = candidate.lower()

        # Strategy 1: Playwright text locator (case-insensitive substring)
        if exact:
            loc = page.locator(f"text='{search}'")
        else:
            loc = page.locator(f"text={search}")

        try:
            if loc.count() > 0:
                el = get_visible(loc)
                if el:
                    logger.info(f"Fuzzy match: found '{candidate}' via text locator")
                    return el, candidate
        except Exception:
            pass

        # Strategy 2: aria-label contains candidate
        try:
            aria_loc = page.locator(f"[aria-label*='{search}' i]")
            if aria_loc.count() > 0:
                el = get_visible(aria_loc)
                if el:
                    logger.info(f"Fuzzy match: found '{candidate}' via aria-label")
                    return el, candidate
        except Exception:
            pass

        # Strategy 3: role=link or role=button with matching name
        for role in ["link", "button"]:
            try:
                role_loc = page.get_by_role(role, name=candidate)
                if role_loc.count() > 0:
                    el = get_visible(role_loc)
                    if el:
                        logger.info(f"Fuzzy match: found '{candidate}' via role={role}")
                        return el, candidate
            except Exception:
                pass

    logger.debug(f"Fuzzy match: no match for candidates {candidates}")
    return None, None


def scroll_to_find(page, text_or_candidates, max_attempts=10):
    """Scroll down the page until an element matching the text is visible.

    Args:
        page: Playwright page object.
        text_or_candidates: A single string OR a list of candidate strings.
        max_attempts: Maximum scroll attempts.

    Returns:
        Tuple of (element, matched_text) if candidates list provided.
        Single element if a plain string was provided (backward compatible).
    """
    # Normalize input — support both old single-string and new list API
    if isinstance(text_or_candidates, str):
        candidates = [text_or_candidates]
        legacy_mode = True
    else:
        candidates = text_or_candidates
        legacy_mode = False

    for attempt in range(max_attempts):
        el, matched = find_by_text_fuzzy(page, candidates)
        if el:
            logger.info(f"Found '{matched}' after {attempt + 1} scroll attempt(s)")
            return el if legacy_mode else (el, matched)

        # Scroll in smaller increments for better coverage
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(800)

    logger.warning(f"Could not find any of {candidates} after {max_attempts} scroll attempts")
    return None if legacy_mode else (None, None)


def safe_click(page, locator, label="element"):
    """Scroll into view and click an element safely."""
    try:
        locator.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        locator.click()
        logger.info(f"Clicked: {label}")
        return True
    except Exception as e:
        logger.error(f"Failed to click {label}: {e}")
        return False


def safe_click_fuzzy(page, candidates, label="element", max_scroll=10):
    """Scroll to find an element by fuzzy text match, then click it.

    Args:
        page: Playwright page object.
        candidates: List of candidate text strings to search for.
        label: Human-readable label for logging.
        max_scroll: Maximum scroll attempts before giving up.

    Returns:
        True if clicked, False if not found.
    """
    logger.info(f"Searching for '{label}' with candidates: {candidates}")

    result = scroll_to_find(page, candidates, max_attempts=max_scroll)

    # scroll_to_find returns (el, matched) for list input
    if isinstance(result, tuple):
        el, matched = result
    else:
        el, matched = result, candidates[0] if result else None

    if el and matched:
        try:
            el.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            el.click()
            logger.info(f"Clicked '{label}' (matched: '{matched}')")
            return True
        except Exception as e:
            logger.error(f"Found '{label}' but click failed: {e}")
            return False

    logger.warning(f"Could not find '{label}' with any candidate")
    return False
