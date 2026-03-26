"""NSP Scheme Scraper — TinyFish-first discovery with Playwright fallback.

Strategy:
  1. TinyFish (primary) — AI-driven web agent for reliable scheme extraction
  2. Playwright (fallback) — intent-safe browser navigation with smart clicking
  3. Cache — stability layer, always used after first successful extraction

All navigation is intent-safe: discovery mode blocks login/apply/OTR clicks.
"""

import json
import os

from core.integrations.tinyfish_client import get_tinyfish_client
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

def try_tinyfish():
    """Use TinyFish AI web agent to extract schemes.

    Returns list of scheme dicts, or None if TinyFish is not available
    or fails.
    """
    try:
        from tinyfish import TinyFish  # noqa: F401
    except ImportError:
        logger.info("[DISCOVERY] TinyFish not installed — skipping AI strategy")
        return None

    try:
        client = get_tinyfish_client()
    except ValueError as e:
        logger.warning(f"[DISCOVERY] TinyFish unavailable: {e}")
        return None
    except Exception as e:
        logger.error(f"[DISCOVERY] TinyFish client init failed: {e}")
        return None

    print("[DISCOVERY] Using TinyFish...")
    logger.info("[DISCOVERY] Using TinyFish...")

    try:
        result = client.run(
            goal="""
            Go to https://scholarships.gov.in

            Do NOT click login, apply, or OTR.

            Navigate like a user:
            - Click 'Students'
            - Click 'Schemes on NSP'
            - Open schemes list

            Extract:
            - scheme name
            - eligibility (if visible)

            Return JSON list
            """,
            max_steps=40,
        )

        if result and hasattr(result, "data") and result.data:
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
                    print(f"[DISCOVERY] TinyFish success: {len(normalized)} items")
                    logger.info(f"[DISCOVERY] TinyFish extracted {len(normalized)} schemes")
                    return normalized

        print("[DISCOVERY] TinyFish failed -> fallback")
        logger.warning("[DISCOVERY] TinyFish returned no usable data")
        return None

    except Exception as e:
        logger.error(f"[DISCOVERY] TinyFish failed: {e}")
        print("[DISCOVERY] TinyFish failed -> fallback")
        return None


def _try_tinyfish():
    """Backward-compatible wrapper for TinyFish discovery."""
    return try_tinyfish()


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
    """Navigate from homepage to the schemes page using iterative safe clicks."""
    target = ["schemes", "all scholarships"]
    block = ["login", "apply", "otr", "register", "sign in"]
    actions = ["schemes on nsp", "schemes", "students"]

    logger.info("[DISCOVERY] Navigating via homepage to schemes page")
    page.goto(_HOMEPAGE_URL)

    for step in range(5):
        print(f"[NAV] Step {step + 1}: {page.url}")
        logger.info(f"[NAV] Step {step + 1}: {page.url}")

        try:
            page.wait_for_load_state("networkidle")
        except Exception:
            logger.debug("[NAV] networkidle wait timed out; continuing")
        page.wait_for_timeout(1500)

        url = page.url.lower()
        try:
            text = page.inner_text("body").lower()
        except Exception:
            text = ""

        if "all-scholarships" in url or ("schemes" in url and page.locator("table").count() > 0):
            print("[NAV] Reached schemes page")
            logger.info(f"[NAV] Reached schemes page: {page.url}")
            return True

        if any(token in url or token in text for token in target):
            try:
                if page.locator("table").count() > 0:
                    print("[NAV] Reached schemes page")
                    logger.info(f"[NAV] Reached schemes page: {page.url}")
                    return True
            except Exception:
                pass

        clicked = False
        for action in actions:
            if any(blocked in action for blocked in block):
                continue

            if safe_click_fuzzy(page, [action], block):
                print(f"[NAV] Clicked: {action}")
                logger.info(f"[NAV] Clicked: {action}")
                clicked = True
                break

        if not clicked:
            print("[NAV] No valid action found")
            logger.error("[NAV] No valid action found")
            return False

    print("[NAV] Max steps reached")
    logger.error("[NAV] Max steps reached")
    return False


def navigate_to_schemes(page):
    """Public wrapper for fallback navigation."""
    return _navigate_to_schemes(page)


def extract_schemes(page):
    """Extract all schemes from the current NSP schemes page."""
    all_schemes = []

    try:
        page.wait_for_selector("table tbody tr", timeout=10000)
        logger.info("[DISCOVERY] Table data loaded")
    except Exception:
        logger.warning("[DISCOVERY] Table rows not found after timeout")

    _set_max_entries(page)
    page.wait_for_timeout(2000)

    try:
        page.wait_for_selector("table tbody tr", timeout=10000)
    except Exception:
        pass

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

    all_schemes = _deduplicate(all_schemes)
    logger.info(f"[DISCOVERY] Total schemes collected: {len(all_schemes)}")
    return all_schemes


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

            page.goto(_HOMEPAGE_URL)

            if not navigate_to_schemes(page):
                print("[ERROR] Navigation failed")
                logger.error("[DISCOVERY] Failed to reach schemes page")
                browser.close()
                return []

            all_schemes = extract_schemes(page)

            browser.close()

    except Exception as e:
        logger.error(f"[DISCOVERY] Playwright scrape failed: {e}")
        if all_schemes:
            logger.info(f"[DISCOVERY] Returning {len(all_schemes)} partial results")

    return all_schemes


# ─────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────

def get_nsp_schemes(use_cache=True):
    """Get NSP scheme list using layered strategy.

    Strategy order:
      1. TinyFish AI agent (primary)
      2. Playwright browser (fallback)
      3. Cache (last-resort safety net)

    Args:
        use_cache: If True, load from cache file if it exists.

    Returns:
        List of dicts: [{"name": "...", "eligibility": "..."}]
    """
    global _FORCE_REFRESH

    logger.info("[DISCOVERY] Starting fresh scheme extraction...")

    # Layer 1: TinyFish (primary)
    schemes = try_tinyfish()

    # Layer 2: Playwright (fallback)
    if not schemes:
        print("[DISCOVERY] Falling back to Playwright...")
        logger.info("[DISCOVERY] Falling back to Playwright...")
        schemes = _scrape_schemes_playwright()

    # Layer 3: Cache safety net
    if not schemes and use_cache and not _FORCE_REFRESH:
        cached = _load_cache()
        if cached:
            logger.info(f"[DISCOVERY] Loaded {len(cached)} schemes from cache")
            schemes = cached

    # Save to cache
    if schemes:
        _save_cache(schemes)
    else:
        logger.warning("[DISCOVERY] No schemes extracted — cache not updated")

    # Reset force flag after use
    _FORCE_REFRESH = False

    return schemes or []
