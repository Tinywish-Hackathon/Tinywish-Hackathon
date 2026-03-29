"""NSP scheme scraper.

Current strategy: Cache -> Playwright accordion extraction.
TinyFish integration is preserved but currently disabled pending SDK stability.
"""

import json
import os

from config import PROFILE_PATH
from core.integrations.tinyfish_client import get_tinyfish_client
from utils.logger import get_logger

logger = get_logger("nsp_scraper")

_CACHE_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_PATH = os.path.join(_CACHE_DIR, "schemes_cache.json")

# Module-level flag for forcing cache refresh (set via --no-cache)
_FORCE_REFRESH = False

# Homepage â€” always start here, never use deep links
_HOMEPAGE_URL = "https://scholarships.gov.in/"

# Smart navigation candidates (intent-safe, no login/apply keywords)
_SCHEME_NAV_CANDIDATES = [
    "students", "schemes", "schemes on nsp",
    "all scholarships", "scheme list", "view all schemes",
    "list of schemes", "scheme guidelines",
]

# Pagination safety limits
_MAX_PAGES = 20


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# CACHE LAYER
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load_cache():
    """Load schemes from local JSON cache if valid."""
    try:
        if os.path.exists(_CACHE_PATH) and os.path.getsize(_CACHE_PATH) > 0:
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                return data
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"[DISCOVERY] Cache read error: {e}")
    return None


def _save_cache(schemes):
    """Save schemes list to local JSON cache."""
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(schemes, f, indent=2, ensure_ascii=False)
        logger.info(f"[DISCOVERY] Saved {len(schemes)} schemes to cache")
    except IOError as e:
        logger.error(f"[DISCOVERY] Cache write error: {e}")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# STRATEGY 1: TINYFISH (PRESERVED, CURRENTLY DISABLED)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def parse_tinyfish_result(result):
    """Normalize TinyFish responses into a list of scheme dicts."""

    def _strip_code(value):
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        return cleaned

    def _to_struct(value):
        if isinstance(value, str):
            cleaned = _strip_code(value)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                return cleaned
        return value

    def _normalize(entry):
        if not isinstance(entry, dict):
            return None
        name = (
            entry.get("name")
            or entry.get("schemeName")
            or entry.get("scheme_name")
            or entry.get("title")
        )
        reason = entry.get("reason") or entry.get("why") or entry.get("rationale") or ""
        eligibility = (
            entry.get("eligibility")
            or entry.get("eligibilityText")
            or (f"Derived from reasoning: {reason}" if reason else "")
            or entry.get("description")
            or ""
        )
        if not name:
            return None
        return {
            "name": str(name).strip(),
            "eligibility": str(eligibility).strip(),
        }

    def _walk(value):
        normalized = _to_struct(value)
        if normalized is None:
            return []
        if isinstance(normalized, list):
            result = []
            for item in normalized:
                result.extend(_walk(item))
            return result
        if isinstance(normalized, dict):
            item = _normalize(normalized)
            if item:
                return [item]
            for key in ("data", "output", "result", "response", "content", "items", "results"):
                if key in normalized:
                    result = _walk(normalized[key])
                    if result:
                        return result
        if isinstance(normalized, str):
            return _walk(_to_struct(normalized))
        return []

    extracted = _walk(result)
    deduped = []
    seen = set()
    for item in extracted:
        key = item["name"].strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def try_tinyfish():
    """Currently disabled. Returns None. Re-enable when TinyFish SDK method surface is confirmed stable."""
    return None


def _try_tinyfish():
    """Currently disabled. Returns None. Re-enable when TinyFish SDK method surface is confirmed stable."""
    # DISABLED: uncomment and fix method name when TinyFish SDK is confirmed
    return None


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# STRATEGY 2: PLAYWRIGHT ACCORDION EXTRACTION (ACTIVE)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _set_max_entries(page):
    """Set the DataTables 'Show entries' dropdown to maximum (100)."""
    try:
        length_select = page.locator("select[name$='_length']")
        if length_select.count() > 0 and length_select.first.is_visible():
            length_select.first.select_option("100")
            page.wait_for_timeout(1500)
            logger.info("[DISCOVERY] Set entries to 100")
            return True
    except Exception as e:
        logger.warning(f"[DISCOVERY] Could not expand entries: {e}")

    # Fallback: try any visible select with numeric options > 10
    try:
        selects = page.locator("select").all()
        for select in selects:
            try:
                if not select.is_visible():
                    continue
                options = select.locator("option").all()
                max_val, max_num = None, 0
                for opt in options:
                    val = opt.get_attribute("value") or ""
                    try:
                        num = int(val)
                        if num > max_num:
                            max_num = num
                            max_val = val
                    except ValueError:
                        continue
                if max_val and max_num > 10:
                    select.select_option(value=max_val)
                    page.wait_for_timeout(1500)
                    logger.info(f"[DISCOVERY] Set entries to {max_val} (fallback)")
                    return True
            except Exception:
                continue
    except Exception:
        pass

    logger.warning("[DISCOVERY] No entries dropdown found")
    return False


def _extract_schemes_accordion(page):
    """Scrape NSP schemes from the Select Scheme filter + accordion UI."""
    ignore_texts = {"search", "select scheme", "click here", "view details"}
    boundary_markers = ("scheme open from", "specifications")

    def _clean_text(value):
        return " ".join(str(value or "").split()).strip()

    def _wait_after_action():
        try:
            page.wait_for_load_state("networkidle")
        except Exception:
            logger.debug("[DISCOVERY] networkidle wait timed out")
        page.wait_for_timeout(1000)

    def _click_search(form):
        for _ in range(2):
            try:
                search_btn = form.get_by_role("button", name="Search")
                if search_btn.count() > 0:
                    search_btn.first.click(force=True)
                    _wait_after_action()
                    return True
            except Exception:
                pass

            try:
                submit_btn = form.locator('button[type="submit"]')
                if submit_btn.count() > 0:
                    submit_btn.first.click(force=True)
                    _wait_after_action()
                    return True
            except Exception:
                pass

            page.wait_for_timeout(500)

        return False

    def _extract_names_from_content(content):
        extracted_names = []
        try:
            raw_text = content.inner_text()
        except Exception:
            return extracted_names

        lines = []
        for line in str(raw_text).splitlines():
            cleaned = _clean_text(line)
            if cleaned:
                lines.append(cleaned)

        current_chunk = []

        def _flush_chunk():
            if not current_chunk:
                return
            for item in current_chunk:
                lowered = item.lower()
                if len(item) <= 5:
                    continue
                if lowered in ignore_texts:
                    continue
                if any(marker in lowered for marker in boundary_markers):
                    continue
                extracted_names.append(item)
                return

        for line in lines:
            lowered = line.lower()
            if any(marker in lowered for marker in boundary_markers):
                _flush_chunk()
                current_chunk = []
                continue
            current_chunk.append(line)

        _flush_chunk()
        return extracted_names

    def _extract_for_select_index(select_index):
        local_schemes = []

        def _add_local(name):
            cleaned = _clean_text(name)
            if len(cleaned) <= 5:
                return
            lowered = cleaned.lower()
            if lowered in ignore_texts or lowered.startswith("scheme open from"):
                return
            local_schemes.append({
                "name": cleaned,
                "eligibility": "Extracted from page or fallback: NSP scheme",
            })

        try:
            scheme_select = page.locator("select").nth(select_index)
            scheme_select.wait_for(state="visible", timeout=10000)
            options = scheme_select.locator("option")
            option_count = options.count()
        except Exception as e:
            logger.debug(f"[DISCOVERY] Scheme dropdown at index {select_index} unavailable: {e}")
            return []

        for option_index in range(1, option_count):
            try:
                scheme_select = page.locator("select").nth(select_index)
                form = scheme_select.locator("xpath=ancestor::form[1]")
                options = scheme_select.locator("option")
                if option_index >= options.count():
                    break

                option_label = _clean_text(options.nth(option_index).inner_text())
                if not option_label or option_label.lower() in {"select scheme", "select"}:
                    continue

                scheme_select.scroll_into_view_if_needed()
                scheme_select.select_option(label=option_label)
                page.wait_for_timeout(1000)

                if not _click_search(form):
                    logger.debug(f"[DISCOVERY] Search failed for option '{option_label}'")
                    continue

                try:
                    headers = page.locator('[data-bs-toggle="collapse"]')
                    header_count = headers.count()
                except Exception as e:
                    logger.debug(
                        f"[DISCOVERY] Failed to find accordion headers for '{option_label}': {e}"
                    )
                    continue

                for header_index in range(header_count):
                    try:
                        headers = page.locator('[data-bs-toggle="collapse"]')
                        if header_index >= headers.count():
                            break

                        header = headers.nth(header_index)
                        if not header.is_visible():
                            continue

                        header.scroll_into_view_if_needed()
                        target = header.get_attribute("data-bs-target")
                        if not target:
                            continue

                        header.click(force=True)
                        page.wait_for_timeout(1000)

                        content = page.locator(target)
                        try:
                            content.wait_for(state="visible", timeout=5000)
                        except Exception:
                            page.wait_for_timeout(1000)

                        try:
                            extracted_names = _extract_names_from_content(content)
                            for extracted_name in extracted_names:
                                _add_local(extracted_name)
                        except Exception:
                            continue
                    except Exception as e:
                        logger.debug(
                            f"[DISCOVERY] Accordion extraction failed at header {header_index + 1} "
                            f"for '{option_label}': {e}"
                        )
                        continue
            except Exception as e:
                logger.debug(f"[DISCOVERY] Scheme option loop failed at index {option_index}: {e}")
                continue

        return local_schemes

    try:
        page.goto("https://scholarships.gov.in/All-Scholarships")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
    except Exception as e:
        logger.error(f"[DISCOVERY] Failed to open All-Scholarships page: {e}")
        return []

    schemes = _extract_for_select_index(0)
    if not schemes:
        schemes = _extract_for_select_index(1)

    schemes = list({s["name"]: s for s in schemes}.values())
    logger.info(f"[DISCOVERY] Extracted {len(schemes)} schemes")
    return schemes


def _try_playwright():
    """Run the Playwright discovery path and return extracted schemes."""
    from playwright.sync_api import sync_playwright

    schemes = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()
            page.set_default_timeout(30000)

            if not _navigate_to_schemes(page):
                browser.close()
                return []

            schemes = _extract_schemes_accordion(page)
            browser.close()
    except Exception as e:
        logger.error(f"[DISCOVERY] Playwright scrape failed: {e}")

    return schemes



def _extract_schemes_from_page(page):
    """Backward-compatible wrapper for scheme extraction."""
    return _extract_schemes_accordion(page)


def _deduplicate(schemes):
    """Remove duplicate schemes by name, preserving insertion order."""
    unique = {}
    for s in schemes:
        key = s["name"].strip()
        if key not in unique:
            unique[key] = s
    return list(unique.values())


def safe_click_fuzzy(page, candidates, blocklist=None):
    """Click the first visible, safe link/button matching any candidate text."""
    blocklist = blocklist or ["login", "apply", "otr", "register", "sign in"]

    for candidate in candidates:
        candidate_text = candidate.strip().lower()
        if not candidate_text or any(blocked in candidate_text for blocked in blocklist):
            continue

        locators = [
            page.get_by_role("link", name=candidate, exact=False),
            page.get_by_role("button", name=candidate, exact=False),
            page.locator(f"a:has-text('{candidate}')"),
            page.locator(f"button:has-text('{candidate}')"),
            page.locator(f"text=/{candidate}/i"),
        ]

        for locator in locators:
            try:
                count = locator.count()
            except Exception:
                continue

            for index in range(count):
                try:
                    element = locator.nth(index)
                    if not element.is_visible():
                        continue

                    text = (element.inner_text() or "").strip().lower()
                    if any(blocked in text for blocked in blocklist):
                        logger.info(f"[NAV] Skipping blocked element: '{text[:40]}'")
                        continue

                    element.click()
                    return True
                except Exception:
                    continue

    return False


def _navigate_to_schemes(page):
    page.goto("https://scholarships.gov.in/All-Scholarships")
    page.wait_for_load_state("networkidle")
    return True


def navigate_to_schemes(page):
    """Public wrapper for fallback navigation."""
    return _navigate_to_schemes(page)


def extract_schemes(page):
    """Run the full NSP filter + accordion extraction pipeline."""

    def _click_search(form):
        last_error = None
        for _ in range(2):
            try:
                button = form.get_by_role("button", name="Search")
                if button.count() > 0:
                    button.first.click()
                    return
            except Exception as e:
                last_error = e
            try:
                form.locator('button[type="submit"]').first.click()
                return
            except Exception as e:
                last_error = e
            page.wait_for_timeout(500)
        raise last_error or RuntimeError("Search button not clickable")

    def _wait_for_results():
        try:
            page.wait_for_load_state("networkidle")
        except Exception:
            logger.debug("[DISCOVERY] networkidle wait timed out after search")
        page.wait_for_timeout(2000)
        try:
            page.locator('[data-bs-toggle="collapse"]').first.wait_for(state="visible", timeout=10000)
        except Exception as e:
            logger.debug(f"[DISCOVERY] Accordion results not visible after search: {e}")

    collected = []
    try:
        selects = page.locator("select")
        if selects.count() < 3:
            logger.error("[DISCOVERY] Expected filter dropdowns were not found")
            return []
    except Exception as e:
        logger.error(f"[DISCOVERY] Failed to access filter dropdowns: {e}")
        return []

    try:
        state_select = page.locator("select").nth(2)
        state_select.wait_for(state="visible", timeout=10000)
        state_select.click()
        page.wait_for_timeout(300)
        state_select.select_option(label="UT of Jammu and Kashmir")
        page.wait_for_timeout(1000)
        form = page.locator("select").nth(0).locator("xpath=ancestor::form")
        _click_search(form)
        _wait_for_results()
    except Exception as e:
        logger.warning(f"[DISCOVERY] Initial state-filter application failed: {e}")

    try:
        scheme_select = page.locator("select").nth(0)
        option_count = scheme_select.locator("option").count()
    except Exception as e:
        logger.error(f"[DISCOVERY] Could not read scheme dropdown options: {e}")
        return []

    processed = 0
    for option_index in range(1, option_count):
        try:
            selects = page.locator("select")
            if selects.count() < 3:
                logger.debug("[DISCOVERY] Filter dropdowns unavailable during scheme loop")
                continue

            scheme_select = selects.nth(0)
            state_select = selects.nth(2)
            form = scheme_select.locator("xpath=ancestor::form")
            options = scheme_select.locator("option")
            if option_index >= options.count():
                continue

            option_label = " ".join((options.nth(option_index).inner_text() or "").split()).strip()
            if not option_label or option_label.lower() in {"select scheme", "select", "all"}:
                continue

            for attempt in range(2):
                try:
                    state_select = page.locator("select").nth(2)
                    state_select.select_option(label="UT of Jammu and Kashmir")
                    page.wait_for_timeout(500)

                    scheme_select = page.locator("select").nth(0)
                    scheme_select.select_option(label=option_label)
                    page.wait_for_timeout(1000)

                    form = scheme_select.locator("xpath=ancestor::form")
                    _click_search(form)
                    _wait_for_results()
                    break
                except Exception as e:
                    logger.debug(
                        f"[DISCOVERY] Retry {attempt + 1} failed for scheme option {option_label}: {e}"
                    )
                    if attempt == 1:
                        raise
                    page.wait_for_timeout(1000)

            extracted = _extract_schemes_accordion(page)
            if extracted:
                collected.extend(extracted)
            processed += 1
            logger.info(
                f"[DISCOVERY] Extracted {len(extracted)} schemes for scheme option {option_label}"
            )

        except Exception as e:
            logger.debug(f"[DISCOVERY] Scheme option loop failed at index {option_index}: {e}")
            continue

    collected = _deduplicate(collected)
    logger.info(
        f"[DISCOVERY] Processed {processed} scheme options and collected {len(collected)} schemes"
    )
    return collected


def _scrape_schemes_playwright():
    """Scrape schemes using Playwright with intent-safe navigation."""
    return _try_playwright()


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PUBLIC API
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_nsp_schemes(use_cache=True):
    """Returns schemes from cache if available, otherwise runs Playwright
    accordion scraper on https://scholarships.gov.in/All-Scholarships.

    Args:
        use_cache: If True, load from cache file if it exists.

    Returns:
        List of dicts: [{"name": "...", "eligibility": "..."}]
    """
    global _FORCE_REFRESH

    if use_cache and not _FORCE_REFRESH:
        cached = _load_cache()
        if cached:
            logger.info(f"[DISCOVERY] Loaded {len(cached)} schemes from cache")
            return cached

    logger.info("[DISCOVERY] Starting fresh scheme extraction...")

    # Layer 2: TinyFish integration is preserved but currently disabled.
    schemes = try_tinyfish()

    # Layer 3: Playwright is the active live extraction path.
    if not schemes:
        print("[DISCOVERY] Falling back to Playwright...")
        logger.info("[DISCOVERY] Falling back to Playwright...")
        schemes = _scrape_schemes_playwright()

    # Save to cache
    if schemes:
        _save_cache(schemes)
    else:
        logger.warning("[DISCOVERY] No schemes extracted â€” cache not updated")

    # Reset force flag after use
    _FORCE_REFRESH = False

    return schemes or []
