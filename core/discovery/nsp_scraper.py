"""NSP Scheme Scraper — TinyFish-first discovery with Playwright fallback.

Strategy:
  1. TinyFish (primary) — AI-driven web agent for reliable scheme extraction
  2. Playwright (fallback) — intent-safe browser navigation with smart clicking
  3. Cache — stability layer, always used after first successful extraction

All navigation is intent-safe: discovery mode blocks login/apply/OTR clicks.
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
    """Use TinyFish as a reasoning layer for scholarship recommendations."""
    try:
        from tinyfish import TinyFish  # noqa: F401
    except ImportError:
        logger.info("[DISCOVERY] TinyFish not installed - skipping AI strategy")
        return None

    try:
        client = get_tinyfish_client()
    except ValueError as e:
        logger.warning(f"[DISCOVERY] TinyFish unavailable: {e}")
        return None
    except Exception as e:
        logger.error(f"[DISCOVERY] TinyFish client init failed: {e}")
        return None

    print("[DISCOVERY] TinyFish used for intelligent recommendations")
    logger.info("[DISCOVERY] TinyFish used for intelligent recommendations")

    profile = {
        "state": "Unknown",
        "category": "Unknown",
        "income": "Unknown",
        "course": "Unknown",
    }
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as profile_file:
            raw_profile = json.load(profile_file)
        profile["state"] = raw_profile.get("state", profile["state"])
        profile["category"] = raw_profile.get("category", profile["category"])
        profile["income"] = raw_profile.get("annual_income", profile["income"])
        profile["course"] = raw_profile.get("course_level", profile["course"])
    except Exception as e:
        logger.warning(f"[DISCOVERY] TinyFish profile load failed: {e}")

    prompt = f"""
Given this user profile:
- State: {profile['state']}
- Category: {profile['category']}
- Income: {profile['income']}
- Course: {profile['course']}

Suggest relevant scholarship schemes from India's National Scholarship Portal.

Return JSON:
[
  {{
    "name": "...",
    "reason": "...",
    "priority": 1-5
  }}
]
"""

    print(dir(client.agent))

    attempts = [
        ("client.agent.run", lambda: client.agent.run(url="https://scholarships.gov.in", goal=str(prompt))),
        ("client.agent", lambda: client.agent(prompt=prompt)),
        ("client.run", lambda: client.run(prompt=prompt)),
    ]

    last_error = None
    for label, attempt in attempts:
        try:
            logger.info(f"[DISCOVERY] TinyFish attempting {label}")
            response = attempt()
            payload = response
            if hasattr(response, "data") and response.data:
                payload = response.data
            elif hasattr(response, "output") and response.output:
                payload = response.output
            normalized = parse_tinyfish_result(payload)
            if normalized:
                logger.info("[DISCOVERY] TinyFish success")
                return normalized
            logger.warning("[DISCOVERY] TinyFish returned no usable data")
            return None
        except Exception as e:
            last_error = e
            logger.warning(f"[DISCOVERY] TinyFish {label} failed: {e}")

    if last_error:
        logger.error(f"[DISCOVERY] TinyFish failed: {last_error}")
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


def _extract_schemes_accordion(page):
    """Extract schemes using the NSP filter workflow instead of accordion clicks."""
    schemes = []
    seen = set()

    def _clean_text(value):
        return " ".join(str(value).split()).strip()

    def _add_scheme(name):
        cleaned = _clean_text(name)
        if len(cleaned) < 4:
            return False
        key = cleaned.lower()
        if key in seen:
            return False
        seen.add(key)
        schemes.append({
            "name": cleaned,
            "eligibility": "Extracted from NSP filters",
        })
        return True

    def _wait_for_results():
        try:
            page.wait_for_load_state("networkidle")
        except Exception:
            logger.debug("[DISCOVERY] networkidle wait timed out after search")
        page.wait_for_timeout(2000)
        try:
            page.wait_for_selector("text=Scheme", timeout=10000)
        except Exception as e:
            logger.debug(f"[DISCOVERY] Scheme text wait timed out: {e}")

    def _extract_cards():
        extracted = 0
        try:
            cards = page.locator("div:has-text('Scheme Open from')")
            card_count = cards.count()
        except Exception as e:
            logger.debug(f"[DISCOVERY] Card lookup failed: {e}")
            return 0

        for index in range(card_count):
            try:
                card = cards.nth(index)
                name = ""
                try:
                    strongs = card.locator("strong")
                    if strongs.count() > 0:
                        name = _clean_text(strongs.first.inner_text())
                except Exception:
                    name = ""

                card_text = card.inner_text()
                if not card_text:
                    continue
                if not name:
                    lines = [line.strip() for line in card_text.splitlines() if line.strip()]
                    name = lines[0] if lines else ""
                if _add_scheme(name):
                    extracted += 1
            except Exception:
                continue
        return extracted

    try:
        page.goto("https://scholarships.gov.in/All-Scholarships", wait_until="networkidle")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
    except Exception as e:
        logger.error(f"[DISCOVERY] Filter workflow navigation failed: {e}")
        return []

    selects = page.locator("select")
    try:
        if selects.count() < 3:
            logger.error("[DISCOVERY] Expected NSP filter selects were not found")
            return []
    except Exception as e:
        logger.error(f"[DISCOVERY] Failed to access filter selects: {e}")
        return []

    scheme_type_select = selects.nth(0)
    ministry_select = selects.nth(1)
    state_select = selects.nth(2)
    form = ministry_select.locator("xpath=ancestor::form")

    try:
        scheme_type_select.select_option(label="Central Sector Schemes")
        page.wait_for_timeout(1000)
    except Exception as e:
        logger.warning(f"[DISCOVERY] Could not select scheme type: {e}")

    try:
        state_select.select_option(label="UT of Jammu and Kashmir")
        page.wait_for_timeout(1000)
    except Exception as e:
        logger.warning(f"[DISCOVERY] Could not select state filter: {e}")

    try:
        options = ministry_select.locator("option")
        option_count = options.count()
    except Exception as e:
        logger.error(f"[DISCOVERY] Could not read ministry options: {e}")
        return []

    try:
        search_btn = form.get_by_role("button", name="Search")
    except Exception:
        search_btn = None

    processed_ministries = 0
    for option_index in range(1, option_count):
        try:
            option_label = _clean_text(options.nth(option_index).inner_text())
        except Exception:
            continue

        if not option_label or option_label.lower() in {"select", "select ministry", "all"}:
            continue

        try:
            ministry_select.select_option(label=option_label)
            page.wait_for_timeout(1000)
        except Exception as e:
            logger.debug(f"[DISCOVERY] Ministry select failed for {option_label}: {e}")
            continue

        try:
            if search_btn is not None:
                search_btn.click()
            else:
                form.locator('button[type="submit"]').click()
        except Exception as e:
            try:
                form.locator('button[type="submit"]').click()
            except Exception as submit_error:
                logger.debug(
                    f"[DISCOVERY] Search click failed for {option_label}: {e}; fallback failed: {submit_error}"
                )
                continue

        page.wait_for_timeout(2000)
        _wait_for_results()

        extracted = 0
        try:
            cards = page.locator("div:has-text('Scheme Open from')")
            card_count = cards.count()
        except Exception as e:
            logger.debug(f"[DISCOVERY] Card lookup failed for {option_label}: {e}")
            card_count = 0

        for card_index in range(card_count):
            try:
                card = cards.nth(card_index)
                name = ""
                try:
                    strongs = card.locator("strong")
                    if strongs.count() > 0:
                        name = _clean_text(strongs.first.inner_text())
                except Exception:
                    name = ""

                if not name:
                    text = card.inner_text()
                    lines = [line.strip() for line in text.splitlines() if line.strip()]
                    name = lines[0] if lines else ""

                if _add_scheme(name):
                    schemes[-1]["eligibility"] = f"From {option_label}"
                    extracted += 1
            except Exception:
                continue

        processed_ministries += 1
        logger.info(f"[DISCOVERY] Extracted {extracted} schemes for ministry {option_label}")

    schemes = _deduplicate(schemes)
    logger.info(
        f"[DISCOVERY] Filter workflow processed {processed_ministries} ministries and extracted {len(schemes)} schemes"
    )
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
    """Navigate directly to the NSP All-Scholarships page."""
    target_url = "https://scholarships.gov.in/All-Scholarships"

    try:
        page.goto(target_url, wait_until="networkidle")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_load_state("networkidle")
    except Exception as e:
        logger.error(f"[NAV] Direct navigation failed: {e}")
        return False

    if "All-Scholarships" not in page.url:
        logger.error(f"[NAV] Unexpected URL after direct navigation: {page.url}")
        return False

    try:
        page.wait_for_selector("text=Schemes On NSP", timeout=10000)
    except Exception as e:
        logger.error(f"[NAV] Schemes On NSP title not found: {e}")
        return False

    try:
        selects = page.locator("select")
        if selects.count() < 3:
            logger.error("[NAV] Expected filter dropdowns were not found")
            return False

        for index in range(3):
            selects.nth(index).wait_for(state="visible", timeout=10000)
    except Exception as e:
        logger.error(f"[NAV] Filter dropdowns are not interactable: {e}")
        return False

    page.wait_for_timeout(1000)
    print("[NAV] Direct navigation to schemes page successful")
    logger.info("[NAV] Direct navigation to schemes page successful")
    return True


def navigate_to_schemes(page):
    """Public wrapper for fallback navigation."""
    return _navigate_to_schemes(page)


def extract_schemes(page):
    """Extract all schemes from the current NSP schemes page."""
    try:
        page.wait_for_load_state("networkidle")
    except Exception:
        logger.debug("[DISCOVERY] networkidle wait timed out before accordion extraction")

    page.wait_for_timeout(1000)

    schemes = _extract_schemes_accordion(page)
    schemes = _deduplicate(schemes)
    logger.info(f"[DISCOVERY] Total schemes collected: {len(schemes)}")
    return schemes


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
      1. Cache
      2. TinyFish AI agent (primary live strategy)
      3. Playwright browser (fallback)

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

    # Layer 2: TinyFish (primary live strategy)
    schemes = try_tinyfish()

    # Layer 3: Playwright (fallback)
    if not schemes:
        print("[DISCOVERY] Falling back to Playwright...")
        logger.info("[DISCOVERY] Falling back to Playwright...")
        schemes = _scrape_schemes_playwright()

    # Save to cache
    if schemes:
        _save_cache(schemes)
    else:
        logger.warning("[DISCOVERY] No schemes extracted — cache not updated")

    # Reset force flag after use
    _FORCE_REFRESH = False

    return schemes or []
