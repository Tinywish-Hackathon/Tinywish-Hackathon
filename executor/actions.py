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


def scroll_to_find(page, text, max_attempts=10):
    """Scroll down the page until an element with the given text is visible.
    Returns the locator if found, None otherwise.
    """
    for attempt in range(max_attempts):
        loc = page.locator(f"text={text}")
        try:
            if loc.count() > 0:
                visible = get_visible(loc)
                if visible:
                    logger.info(f"Found '{text}' on attempt {attempt + 1}")
                    return visible
        except Exception:
            pass

        page.mouse.wheel(0, 600)
        page.wait_for_timeout(700)

    logger.warning(f"Could not find '{text}' after {max_attempts} scroll attempts")
    return None


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
