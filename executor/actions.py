import time
from utils.logger import get_logger

logger = get_logger("actions")

# --- Global Debug Flag ---
DEBUG = True

# --- Clickable element tags/roles for validation ---
CLICKABLE_TAGS = {"a", "button"}
CLICKABLE_ROLES = {"button", "link", "menuitem", "tab"}
CLICKABLE_ATTRS = ["onclick", "href", "ng-click", "data-action"]

# --- Track clicked elements to prevent duplicates ---
_clicked_elements = set()


def _is_clickable(el):
    """Check if an element is a genuinely clickable interactive element."""
    try:
        tag = el.evaluate("el => el.tagName.toLowerCase()")
        role = el.get_attribute("role") or ""

        # Check tag
        if tag in CLICKABLE_TAGS:
            return True

        # Check ARIA role
        if role.lower() in CLICKABLE_ROLES:
            return True

        # Check for onclick or similar attributes
        for attr in CLICKABLE_ATTRS:
            if el.get_attribute(attr) is not None:
                return True

        # Check if it's an input[type=submit] or input[type=button]
        if tag == "input":
            input_type = (el.get_attribute("type") or "").lower()
            if input_type in ("submit", "button"):
                return True

        return False
    except Exception:
        return False


def _get_element_info(el):
    """Get metadata about an element for logging and decision-making."""
    try:
        tag = el.evaluate("el => el.tagName.toLowerCase()")
        text = el.evaluate("el => (el.innerText || el.textContent || '').trim().substring(0, 80)")
        role = el.get_attribute("role") or ""
        href = el.get_attribute("href") or ""
        clickable = _is_clickable(el)
        return {
            "tag": tag,
            "text": text,
            "role": role,
            "href": href[:60],
            "is_clickable": clickable,
        }
    except Exception:
        return {"tag": "?", "text": "?", "role": "", "href": "", "is_clickable": False}


def _element_fingerprint(el):
    """Generate a fingerprint to detect duplicate clicks."""
    try:
        return el.evaluate(
            "el => (el.tagName + '|' + (el.id || '') + '|' + (el.className || '') + '|' + "
            "(el.innerText || '').trim().substring(0, 40))"
        )
    except Exception:
        return None


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


def get_visible_clickable(locator):
    """Return the first visible AND clickable element from a locator, or None.

    Prefers clickable elements (a, button, [role=button]).
    Falls back to first visible if no clickable found.
    """
    first_visible = None
    for i in range(locator.count()):
        el = locator.nth(i)
        try:
            if not el.is_visible():
                continue
            if first_visible is None:
                first_visible = el
            if _is_clickable(el):
                if DEBUG:
                    info = _get_element_info(el)
                    logger.debug(f"  Clickable match: <{info['tag']}> '{info['text'][:40]}'")
                return el
        except Exception:
            continue

    # Log if we only found non-clickable elements
    if first_visible and DEBUG:
        info = _get_element_info(first_visible)
        logger.debug(f"  No clickable match, best visible: <{info['tag']}> '{info['text'][:40]}'")

    return None


def find_by_text_fuzzy(page, candidates, exact=False, clickable_only=False):
    """Search for the first visible element matching ANY candidate text.

    Args:
        page: Playwright page object.
        candidates: List of text strings to search for (case-insensitive).
        exact: If True, use exact text match. If False, use substring/contains.
        clickable_only: If True, only return elements that are clickable (a, button, etc.)

    Returns:
        Tuple of (element, matched_candidate) or (None, None).
    """
    all_matches = []
    getter = get_visible_clickable if clickable_only else get_visible

    for candidate in candidates:
        search = candidate.lower()

        # Strategy 1: role=link or role=button (highest priority - most precise)
        for role in ["link", "button"]:
            try:
                role_loc = page.get_by_role(role, name=candidate)
                if role_loc.count() > 0:
                    el = get_visible(role_loc)  # role already ensures clickable
                    if el:
                        info = _get_element_info(el)
                        if DEBUG:
                            logger.debug(
                                f"  [role={role}] '{candidate}' -> "
                                f"<{info['tag']}> '{info['text'][:40]}' clickable={info['is_clickable']}"
                            )
                        all_matches.append({"el": el, "candidate": candidate, "info": info, "priority": 1})
            except Exception:
                pass

        # Strategy 2: Playwright text locator
        if exact:
            loc = page.locator(f"text='{search}'")
        else:
            loc = page.locator(f"text={search}")

        try:
            if loc.count() > 0:
                el = getter(loc)
                if el:
                    info = _get_element_info(el)
                    if DEBUG:
                        logger.debug(
                            f"  [text] '{candidate}' -> "
                            f"<{info['tag']}> '{info['text'][:40]}' clickable={info['is_clickable']}"
                        )
                    priority = 2 if info["is_clickable"] else 4
                    all_matches.append({"el": el, "candidate": candidate, "info": info, "priority": priority})
        except Exception:
            pass

        # Strategy 3: aria-label contains candidate
        try:
            aria_loc = page.locator(f"[aria-label*='{search}' i]")
            if aria_loc.count() > 0:
                el = getter(aria_loc)
                if el:
                    info = _get_element_info(el)
                    if DEBUG:
                        logger.debug(
                            f"  [aria] '{candidate}' -> "
                            f"<{info['tag']}> '{info['text'][:40]}' clickable={info['is_clickable']}"
                        )
                    priority = 3 if info["is_clickable"] else 5
                    all_matches.append({"el": el, "candidate": candidate, "info": info, "priority": priority})
        except Exception:
            pass

    if not all_matches:
        logger.debug(f"Fuzzy match: no match for candidates {candidates}")
        return None, None

    # Sort: prefer clickable, then by priority, then by shortest text
    all_matches.sort(key=lambda m: (
        0 if m["info"]["is_clickable"] else 1,
        m["priority"],
        len(m["info"]["text"]),
    ))

    if DEBUG:
        logger.debug(f"Fuzzy match: {len(all_matches)} candidate(s) found, selecting best:")
        for i, m in enumerate(all_matches[:5]):
            marker = " << SELECTED" if i == 0 else ""
            logger.debug(
                f"    {i+1}. <{m['info']['tag']}> '{m['info']['text'][:40]}' "
                f"clickable={m['info']['is_clickable']} priority={m['priority']}{marker}"
            )

    best = all_matches[0]
    logger.info(
        f"Fuzzy match: selected '{best['candidate']}' -> "
        f"<{best['info']['tag']}> clickable={best['info']['is_clickable']}"
    )
    return best["el"], best["candidate"]


def scroll_to_find(page, text_or_candidates, max_attempts=10, clickable_only=False):
    """Scroll down the page until an element matching the text is visible.

    Args:
        page: Playwright page object.
        text_or_candidates: A single string OR a list of candidate strings.
        max_attempts: Maximum scroll attempts.
        clickable_only: If True, only return clickable elements.

    Returns:
        Tuple of (element, matched_text) if candidates list provided.
        Single element if a plain string was provided (backward compatible).
    """
    if isinstance(text_or_candidates, str):
        candidates = [text_or_candidates]
        legacy_mode = True
    else:
        candidates = text_or_candidates
        legacy_mode = False

    for attempt in range(max_attempts):
        el, matched = find_by_text_fuzzy(page, candidates, clickable_only=clickable_only)
        if el:
            logger.info(f"Found '{matched}' after {attempt + 1} scroll attempt(s)")
            return el if legacy_mode else (el, matched)

        page.mouse.wheel(0, 400)
        page.wait_for_timeout(800)

        if DEBUG and (attempt + 1) % 3 == 0:
            logger.debug(f"Scroll attempt {attempt + 1}/{max_attempts} - no match yet")

    logger.warning(f"Could not find any of {candidates} after {max_attempts} scroll attempts")
    return None if legacy_mode else (None, None)


def safe_click(page, locator, label="element"):
    """Scroll into view and click an element safely with validation."""
    # Pre-click debug info
    info = _get_element_info(locator)
    if DEBUG:
        logger.debug(
            f"Attempting click on '{label}': "
            f"<{info['tag']}> '{info['text'][:40]}' clickable={info['is_clickable']}"
        )

    # Duplicate check
    fp = _element_fingerprint(locator)
    if fp and fp in _clicked_elements:
        logger.warning(f"Skipping duplicate click on '{label}' (already clicked this element)")
        return False

    try:
        locator.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        locator.click()
        logger.info(f"Click SUCCESS: '{label}' <{info['tag']}>")

        if fp:
            _clicked_elements.add(fp)
        return True
    except Exception as e:
        logger.error(f"Click FAILED: '{label}' <{info['tag']}>: {e}")
        return False


def safe_click_fuzzy(page, candidates, label="element", max_scroll=10):
    """Scroll to find a CLICKABLE element by fuzzy text match, then click it.

    Only clicks elements that are genuinely interactive (a, button, role=button).
    """
    logger.info(f"Searching for '{label}' with candidates: {candidates}")

    result = scroll_to_find(page, candidates, max_attempts=max_scroll, clickable_only=True)

    if isinstance(result, tuple):
        el, matched = result
    else:
        el, matched = result, candidates[0] if result else None

    if el and matched:
        # Validate clickability before clicking
        if not _is_clickable(el):
            info = _get_element_info(el)
            logger.warning(
                f"Found '{label}' but element is NOT clickable: "
                f"<{info['tag']}> '{info['text'][:40]}'. Skipping."
            )
            return False

        return safe_click(page, el, label=f"{label} (matched: '{matched}')")

    logger.warning(f"Could not find clickable element for '{label}'")
    return False


def find_section_by_text(page, candidates):
    """Find a container element whose text matches a candidate.

    Uses partial/fuzzy matching and searches across multiple container types.
    """
    container_tags = ["section", "article", "div.card", "div.tile", "li", "div"]

    found_sections = []

    for candidate in candidates:
        search = candidate.lower()

        for tag in container_tags:
            try:
                selector = f"{tag}:has(text='{search}')"
                loc = page.locator(selector)
                count = loc.count()

                if count > 0:
                    for i in range(min(count, 5)):  # Cap at 5 to avoid slowness
                        section = loc.nth(i)
                        try:
                            if section.is_visible():
                                found_sections.append({
                                    "el": section,
                                    "candidate": candidate,
                                    "tag": tag,
                                    "index": i,
                                    "total": count,
                                })
                        except Exception:
                            continue
            except Exception:
                pass

    if not found_sections:
        logger.debug(f"No section found for candidates {candidates}")
        return None, None

    if DEBUG:
        logger.debug(f"Section candidates found: {len(found_sections)}")
        for i, s in enumerate(found_sections[:5]):
            logger.debug(f"  {i+1}. <{s['tag']}> matched '{s['candidate']}' ({s['index']+1}/{s['total']})")

    best = found_sections[0]
    logger.info(
        f"Selected section: '{best['candidate']}' in <{best['tag']}> "
        f"(match {best['index']+1}/{best['total']})"
    )
    return best["el"], best["candidate"]


def find_within_section(section, candidates):
    """Search for a CLICKABLE element inside the given section.

    Prioritizes links and buttons. Only returns genuinely clickable elements.
    """
    all_matches = []

    for candidate in candidates:
        search = candidate.lower()

        # Strategy 1: Links and buttons (highest priority)
        for role_sel in ["a", "button", "[role='button']", "[role='link']"]:
            try:
                loc = section.locator(f"{role_sel}:has-text('{search}')")
                if loc.count() > 0:
                    el = get_visible(loc)
                    if el:
                        info = _get_element_info(el)
                        all_matches.append({
                            "el": el, "candidate": candidate, "via": role_sel,
                            "info": info, "priority": 1,
                        })
            except Exception:
                pass

        # Strategy 2: Any text match (lower priority, must be clickable)
        try:
            loc = section.locator(f"text={search}")
            if loc.count() > 0:
                for i in range(min(loc.count(), 5)):
                    el = loc.nth(i)
                    try:
                        if el.is_visible() and _is_clickable(el):
                            info = _get_element_info(el)
                            all_matches.append({
                                "el": el, "candidate": candidate, "via": "text",
                                "info": info, "priority": 2,
                            })
                    except Exception:
                        continue
        except Exception:
            pass

    if not all_matches:
        logger.debug(f"No clickable match inside section for candidates {candidates}")
        return None, None

    # Sort: clickable first, then priority, then shortest text
    all_matches.sort(key=lambda m: (
        0 if m["info"]["is_clickable"] else 1,
        m["priority"],
        len(m["info"]["text"]),
    ))

    if DEBUG:
        logger.debug(f"Scoped matches inside section: {len(all_matches)}")
        for i, m in enumerate(all_matches[:5]):
            marker = " << SELECTED" if i == 0 else ""
            logger.debug(
                f"    {i+1}. <{m['info']['tag']}> '{m['info']['text'][:40]}' "
                f"via {m['via']} clickable={m['info']['is_clickable']}{marker}"
            )

    best = all_matches[0]
    logger.info(f"Scoped match: '{best['candidate']}' via {best['via']} inside section")
    return best["el"], best["candidate"]


def safe_click_in_section(page, section_candidates, target_candidates,
                          label="element", max_scroll=10):
    """Find a section by text, then click a CLICKABLE target element within it.

    Two-phase search with clickability validation:
        1. Scroll to find a container matching section_candidates
        2. Inside that container, find and click a clickable element matching target_candidates

    Falls back to direct clickable fuzzy search if section not found.
    Does NOT click non-clickable containers.
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
        logger.warning(f"Section not found for '{label}', falling back to clickable fuzzy search")
        combined = target_candidates + section_candidates
        return safe_click_fuzzy(page, combined, label=label, max_scroll=3)

    # Phase 2: Find clickable target inside the section
    section.scroll_into_view_if_needed()
    page.wait_for_timeout(500)

    target, target_match = find_within_section(section, target_candidates)

    if target:
        info = _get_element_info(target)
        if not info["is_clickable"]:
            logger.warning(
                f"Found '{target_match}' inside section but it's NOT clickable "
                f"(<{info['tag']}>). Skipping unsafe click."
            )
        else:
            return safe_click(page, target,
                              label=f"{label}: target='{target_match}' in section='{section_match}'")

    # Fallback: try clicking a clickable element matching section text
    logger.info(f"No target found inside section, trying section-level clickable elements")
    fallback_el, fallback_match = find_within_section(section, section_candidates)

    if fallback_el:
        info = _get_element_info(fallback_el)
        if info["is_clickable"]:
            return safe_click(page, fallback_el,
                              label=f"{label}: section-level '{fallback_match}'")
        else:
            logger.warning(
                f"Section-level element '{fallback_match}' is NOT clickable "
                f"(<{info['tag']}>). Refusing to click."
            )

    logger.warning(f"No clickable target found for '{label}'. No click performed.")
    return False


def fill_form(page, mapped_fields):
    """Fill form fields safely using Playwright.

    Args:
        page: Playwright page object.
        mapped_fields: List of dicts from map_profile_to_fields(), each with:
            - selector: CSS selector for the field
            - value: Value to fill
            - label: Human-readable field label

    Returns:
        Dict with {"filled": int, "skipped": int, "failed": int}
    """
    filled = 0
    skipped = 0
    failed = 0

    logger.info(f"Filling {len(mapped_fields)} mapped field(s)...")

    for field in mapped_fields:
        selector = field.get("selector", "")
        value = field.get("value")
        label = field.get("label", "unknown")

        # Safety: never fill None or empty values
        if not value or not str(value).strip():
            logger.debug(f"Skipping '{label}': empty value")
            skipped += 1
            continue

        if not selector:
            logger.debug(f"Skipping '{label}': no selector")
            skipped += 1
            continue

        try:
            locator = page.locator(selector).first

            # Check if field is visible
            if not locator.is_visible():
                logger.debug(f"Skipping '{label}': not visible")
                skipped += 1
                continue

            # Check if field already has a value (don't overwrite blindly)
            current_value = locator.input_value() if locator.count() > 0 else ""
            if current_value and current_value.strip():
                logger.debug(f"Skipping '{label}': already filled with '{current_value[:20]}'")
                skipped += 1
                continue

            # Fill the field
            locator.fill(str(value))
            filled += 1
            logger.info(f"  Filled '{label}' = '{str(value)[:30]}'")

            # Human-like delay between fills
            page.wait_for_timeout(300)

        except Exception as e:
            failed += 1
            logger.error(f"  Failed to fill '{label}': {e}")

    results = {"filled": filled, "skipped": skipped, "failed": failed}
    logger.info(
        f"Form fill complete: {filled} filled, {skipped} skipped, {failed} failed"
    )
    return results


def reset_click_history():
    """Clear the clicked-elements tracker. Call between flows or page navigations."""
    global _clicked_elements
    _clicked_elements = set()
    logger.debug("Click history cleared")
