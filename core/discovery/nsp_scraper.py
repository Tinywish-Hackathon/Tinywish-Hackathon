"""NSP Scheme Scraper — TinyFish-first discovery with Playwright fallback.

Strategy:
  1. TinyFish (primary) — AI-driven web agent for reliable scheme extraction
  2. Playwright (fallback) — intent-safe browser navigation with smart clicking
  3. Cache — stability layer, always used after first successful extraction

All navigation is intent-safe: discovery mode blocks login/apply/OTR clicks.
"""

import json
import os
from utils.logger import get_logger

logger = get_logger("nsp_scraper")

_CACHE_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_PATH = os.path.join(_CACHE_DIR, "schemes_cache.json")

# Module-level flag for forcing cache refresh (set via --no-cache)
_FORCE_REFRESH = False

# Homepage — always start here, never use deep links
_HOMEPAGE_URL = "https://scholarships.gov.in/"

# Smart navigation candidates (intent-safe, no login/apply keywords)
_SCHEME_NAV_CANDIDATES = [
    "students", "schemes", "schemes on nsp",
    "all scholarships", "scheme list", "view all schemes",
    "list of schemes", "scheme guidelines",
]

# Pagination safety limits
_MAX_PAGES = 20


# ─────────────────────────────────────────────────
# CACHE LAYER
# ─────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────
# STRATEGY 1: TINYFISH (PRIMARY)
# ─────────────────────────────────────────────────

def _try_tinyfish():
    """Use TinyFish AI web agent to extract schemes.

    Returns list of scheme dicts, or None if TinyFish is not available
    or fails.
    """
    try:
        import tinyfish
    except ImportError:
        logger.info("[DISCOVERY] TinyFish not installed — skipping AI strategy")
        return None

    logger.info("[DISCOVERY] Using TinyFish AI agent...")

    try:
        result = tinyfish.run(
            goal="""
            You are a web agent.

            Objective: find all scholarship schemes listed on the National
            Scholarship Portal.

            Start at https://scholarships.gov.in

            DO NOT click login, apply, OTR, or register.

            Navigate like a user:
            - Find student-related section
            - Find schemes listing
            - Open schemes page

            Extract:
            - scheme name
            - eligibility (if visible)

            Return JSON list of objects with keys: "name", "eligibility"
            """,
            max_steps=40,
        )

        if hasattr(result, "data") and result.data:
            schemes = result.data
            # Normalize structure
            if isinstance(schemes, list):
                normalized = []
                for s in schemes:
                    if isinstance(s, dict) and "name" in s:
                        normalized.append({
                            "name": str(s.get("name", "")).strip(),
                            "eligibility": str(s.get("eligibility", "")).strip(),
                        })
                if normalized:
                    logger.info(f"[DISCOVERY] TinyFish extracted {len(normalized)} schemes")
                    return normalized

        logger.warning("[DISCOVERY] TinyFish returned no usable data")
        return None

    except Exception as e:
        logger.error(f"[DISCOVERY] TinyFish failed: {e}")
        return None


# ─────────────────────────────────────────────────
# STRATEGY 2: PLAYWRIGHT FALLBACK (INTENT-SAFE)
# ─────────────────────────────────────────────────

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


def _extract_schemes_from_page(page):
    """Extract scheme data from visible table body rows on the current page."""
    schemes = []
    try:
        rows = page.locator("table tbody tr").all()
        for row in rows:
            try:
                cells = row.locator("td").all()
                if len(cells) < 2:
                    continue

                texts = []
                for cell in cells:
                    try:
                        t = cell.inner_text().strip()
                        if t:
                            texts.append(t)
                    except Exception:
                        continue

                if not texts:
                    continue

                name = texts[0]
                eligibility = " ".join(texts[1:]) if len(texts) > 1 else ""

                # Skip header-like rows
                if name.lower() in ("s.no", "s.no.", "sl.no", "sl.no.",
                                     "scheme name", "name", "#"):
                    continue

                # If first column is a serial number, shift to next column
                if name.replace(".", "").strip().isdigit() and len(texts) > 1:
                    name = texts[1]
                    eligibility = " ".join(texts[2:]) if len(texts) > 2 else ""

                name = name.strip()
                if name and len(name) > 3:
                    schemes.append({
                        "name": name,
                        "eligibility": eligibility.strip(),
                    })
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"[DISCOVERY] Row extraction error: {e}")

    return schemes


def _deduplicate(schemes):
    """Remove duplicate schemes by name, preserving insertion order."""
    unique = {}
    for s in schemes:
        key = s["name"].strip()
        if key not in unique:
            unique[key] = s
    return list(unique.values())


def _navigate_to_schemes(page):
    """Navigate from homepage to the schemes page using smart fuzzy clicks.

    Tries multiple candidate link texts in priority order. Ensures we
    are on the homepage first. Returns True if a table is found.
    """
    logger.info("[DISCOVERY] Navigating via homepage to schemes page")

    # Step 1: ensure we are on homepage
    if "scholarships.gov.in" not in page.url:
        page.goto(_HOMEPAGE_URL)
    else:
        page.goto(_HOMEPAGE_URL)

    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    # Step 2: scan page for best navigation candidate (fuzzy, NOT hardcoded)
    clicked = False
    for candidate in _SCHEME_NAV_CANDIDATES:
        # Strategy A: role-based locator
        try:
            link = page.get_by_role("link", name=candidate)
            if link.count() > 0 and link.first.is_visible():
                link_text = link.first.inner_text().strip().lower()
                # Intent filter: skip login/apply/otr links
                blocked = ["apply", "login", "otr", "register", "sign in"]
                if any(b in link_text for b in blocked):
                    logger.info(f"[DISCOVERY] Skipping blocked link: '{link_text[:40]}'")
                    continue
                logger.info(f"[DISCOVERY] Clicking link: '{candidate}'")
                link.first.click()
                clicked = True
                break
        except Exception:
            pass

        # Strategy B: text-based locator
        try:
            loc = page.locator(f"a:has-text('{candidate}')")
            if loc.count() > 0 and loc.first.is_visible():
                loc_text = loc.first.inner_text().strip().lower()
                blocked = ["apply", "login", "otr", "register", "sign in"]
                if any(b in loc_text for b in blocked):
                    logger.info(f"[DISCOVERY] Skipping blocked link: '{loc_text[:40]}'")
                    continue
                logger.info(f"[DISCOVERY] Clicking link (text match): '{candidate}'")
                loc.first.click()
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        # Last resort: any link containing "scheme" (still intent-filtered)
        try:
            fallback = page.locator("a:has-text('scheme')")
            if fallback.count() > 0:
                for i in range(fallback.count()):
                    el = fallback.nth(i)
                    if el.is_visible():
                        el_text = el.inner_text().strip().lower()
                        blocked = ["apply", "login", "otr", "register"]
                        if any(b in el_text for b in blocked):
                            continue
                        logger.info(f"[DISCOVERY] Clicking fallback: '{el_text[:40]}'")
                        el.click()
                        clicked = True
                        break
        except Exception:
            pass

    if not clicked:
        logger.error("[DISCOVERY] Could not find schemes navigation link")
        return False

    # Wait for schemes page to load
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    # Verify table is present
    if page.locator("table").count() > 0:
        logger.info(f"[DISCOVERY] Schemes page loaded — URL: {page.url}")
        return True

    logger.error("[DISCOVERY] No table found after navigation")
    return False


def _scrape_schemes_playwright():
    """Scrape schemes using Playwright with intent-safe navigation."""
    from playwright.sync_api import sync_playwright

    all_schemes = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()
            page.set_default_timeout(30000)

            # Smart navigation from homepage
            if not _navigate_to_schemes(page):
                logger.error("[DISCOVERY] Failed to reach schemes page")
                browser.close()
                return []

            # Wait for table data rows
            try:
                page.wait_for_selector("table tbody tr", timeout=10000)
                logger.info("[DISCOVERY] Table data loaded")
            except Exception:
                logger.warning("[DISCOVERY] Table rows not found after timeout")

            # Expand entries to maximum
            _set_max_entries(page)

            # Wait for table to re-render
            page.wait_for_timeout(2000)
            try:
                page.wait_for_selector("table tbody tr", timeout=10000)
            except Exception:
                pass

            # Extract with pagination
            page_num = 0
            while page_num < _MAX_PAGES:
                page_num += 1
                logger.info(f"[DISCOVERY] Extracting page {page_num}...")

                page_schemes = _extract_schemes_from_page(page)
                logger.info(
                    f"[DISCOVERY] Extracted {len(page_schemes)} schemes "
                    f"from page {page_num}"
                )

                if page_schemes:
                    all_schemes.extend(page_schemes)

                # Check for Next button (DataTables pagination)
                try:
                    next_btn = page.locator("li.paginate_button.next")
                    if next_btn.count() == 0:
                        logger.info("[DISCOVERY] No pagination found")
                        break

                    classes = (next_btn.first.get_attribute("class") or "").lower()
                    if "disabled" in classes:
                        logger.info("[DISCOVERY] No more pages (Next is disabled)")
                        break

                    next_link = next_btn.first.locator("a")
                    if next_link.count() > 0:
                        next_link.first.click()
                    else:
                        next_btn.first.click()

                    page.wait_for_timeout(1500)
                    try:
                        page.wait_for_selector("table tbody tr", timeout=10000)
                    except Exception:
                        logger.warning("[DISCOVERY] Table did not reload after pagination")
                        break

                except Exception as e:
                    logger.debug(f"[DISCOVERY] Pagination error: {e}")
                    break

            browser.close()

    except Exception as e:
        logger.error(f"[DISCOVERY] Playwright scrape failed: {e}")
        if all_schemes:
            logger.info(f"[DISCOVERY] Returning {len(all_schemes)} partial results")

    all_schemes = _deduplicate(all_schemes)
    logger.info(f"[DISCOVERY] Total schemes collected: {len(all_schemes)}")

    return all_schemes


# ─────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────

def get_nsp_schemes(use_cache=True):
    """Get NSP scheme list using layered strategy.

    Strategy order:
      1. Cache (if available and not force-refreshing)
      2. TinyFish AI agent (primary)
      3. Playwright browser (fallback)

    Args:
        use_cache: If True, load from cache file if it exists.

    Returns:
        List of dicts: [{"name": "...", "eligibility": "..."}]
    """
    global _FORCE_REFRESH

    # Layer 1: Cache
    if use_cache and not _FORCE_REFRESH:
        cached = _load_cache()
        if cached:
            logger.info(f"[DISCOVERY] Loaded {len(cached)} schemes from cache")
            return cached

    logger.info("[DISCOVERY] Starting fresh scheme extraction...")

    # Layer 2: TinyFish (primary)
    schemes = _try_tinyfish()

    # Layer 3: Playwright (fallback)
    if not schemes:
        logger.info("[DISCOVERY] Falling back to Playwright browser...")
        schemes = _scrape_schemes_playwright()

    # Save to cache
    if schemes:
        _save_cache(schemes)
    else:
        logger.warning("[DISCOVERY] No schemes extracted — cache not updated")

    # Reset force flag after use
    _FORCE_REFRESH = False

    return schemes or []
