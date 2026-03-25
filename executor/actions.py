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


def find_section_by_text(page, candidates):
    """Find a container element (div, section, article, li) whose text matches a candidate.

    Searches for sections containing the candidate text and returns the
    nearest meaningful container, not just inline text nodes.

    Args:
        page: Playwright page object.
        candidates: List of text strings to match inside containers.

    Returns:
        Tuple of (section_locator, matched_candidate) or (None, None).
    """
    container_tags = ["section", "article", "div.card", "div.tile", "li", "div"]

    for candidate in candidates:
        search = candidate.lower()

        for tag in container_tags:
            try:
                # Find containers that have text containing the candidate
                selector = f"{tag}:has(text='{search}')"
                loc = page.locator(selector)

                if loc.count() > 0:
                    # Prefer the most specific (smallest) visible match
                    for i in range(loc.count()):
                        section = loc.nth(i)
                        try:
                            if section.is_visible():
                                logger.info(
                                    f"Section found: '{candidate}' in <{tag}> "
                                    f"(match {i + 1}/{loc.count()})"
                                )
                                return section, candidate
                        except Exception:
                            continue
            except Exception:
                pass

    logger.debug(f"No section found for candidates {candidates}")
    return None, None


def find_within_section(section, candidates):
    """Search for a clickable element ONLY inside the given section.

    Args:
        section: A Playwright locator scoped to a container element.
        candidates: List of text strings to match within the section.

    Returns:
        Tuple of (element, matched_candidate) or (None, None).
    """
    for candidate in candidates:
        search = candidate.lower()

        # Strategy 1: Links and buttons with matching text
        for role_sel in ["a", "button", "[role='button']", "[role='link']"]:
            try:
                loc = section.locator(f"{role_sel}:has-text('{search}')")
                if loc.count() > 0:
                    el = get_visible(loc)
                    if el:
                        logger.info(f"Scoped match: '{candidate}' via {role_sel} inside section")
                        return el, candidate
            except Exception:
                pass

        # Strategy 2: Any element with that text inside the section
        try:
            loc = section.locator(f"text={search}")
            if loc.count() > 0:
                el = get_visible(loc)
                if el:
                    logger.info(f"Scoped match: '{candidate}' via text inside section")
                    return el, candidate
        except Exception:
            pass

    logger.debug(f"No scoped match inside section for candidates {candidates}")
    return None, None


def safe_click_in_section(page, section_candidates, target_candidates,
                          label="element", max_scroll=10):
    """Find a section by text, then click a target element within it.

    Two-phase search:
        1. Scroll to find a container matching section_candidates
        2. Inside that container, find and click an element matching target_candidates

    Falls back to safe_click_fuzzy if the section is found but
    no specific target is found inside it (clicks the section match directly).

    Args:
        page: Playwright page object.
        section_candidates: Text candidates to identify the section/card.
        target_candidates: Text candidates for the clickable element inside the section.
        label: Human-readable label for logging.
        max_scroll: Maximum scroll attempts.

    Returns:
        True if clicked, False if not found.
    """
    logger.info(
        f"Context search for '{label}': "
        f"section={section_candidates}, target={target_candidates}"
    )

    # Phase 1: Scroll to find the section
    section = None
    section_match = None

    for attempt in range(max_scroll):
        section, section_match = find_section_by_text(page, section_candidates)
        if section:
            logger.info(f"Section '{section_match}' found after {attempt + 1} scroll(s)")
            break

        page.mouse.wheel(0, 400)
        page.wait_for_timeout(800)

    if not section:
        logger.warning(f"Section not found for '{label}', falling back to fuzzy click")
        # Fallback: try direct fuzzy click with all candidates combined
        combined = section_candidates + target_candidates
        return safe_click_fuzzy(page, combined, label=label, max_scroll=3)

    # Phase 2: Find the target inside the section
    section.scroll_into_view_if_needed()
    page.wait_for_timeout(500)

    target, target_match = find_within_section(section, target_candidates)

    if target:
        try:
            target.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            target.click()
            logger.info(
                f"Clicked '{label}': target='{target_match}' inside section='{section_match}'"
            )
            return True
        except Exception as e:
            logger.error(f"Found target '{target_match}' but click failed: {e}")
            return False

    # Fallback: click the section-level match itself (it might be the link)
    logger.info(f"No specific target inside section, attempting section-level click")
    el, matched = find_within_section(section, section_candidates)
    if el:
        try:
            el.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            el.click()
            logger.info(f"Clicked section-level element '{matched}' for '{label}'")
            return True
        except Exception as e:
            logger.error(f"Section-level click failed: {e}")

    logger.warning(f"Could not click any target for '{label}'")
    return False

