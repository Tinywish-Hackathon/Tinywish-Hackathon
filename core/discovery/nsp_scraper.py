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

    attempts = [
        ("client.agent.run", lambda: client.agent.run(goal=prompt)),
        ("client.agent", lambda: client.agent(prompt=prompt)),
        ("client.run", lambda: client.run(prompt=prompt)),
    ]

    last_error = None
    for label, attempt in attempts:
        try:
            logger.info(f"[DISCOVERY] TinyFish attempting {label}")
            response = attempt()
            normalized = parse_tinyfish_result(response)
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
    """Extract scheme data from accordion-based ministry sections."""
    schemes = []
    seen = set()
    max_sections = 30

    def _text(locator):
        try:
            return (locator.inner_text() or "").strip()
        except Exception:
            return ""

    def _add_scheme(name, ministry_name):
        cleaned = " ".join(str(name).split()).strip(" -:\n\t")
        if len(cleaned) < 4:
            return

        lowered = cleaned.lower()
        blocked = ("ministry", "department", "council", "board", "commission")
        if lowered in blocked:
            return

        if cleaned.lower() in seen:
            return

        seen.add(cleaned.lower())
        schemes.append({
            "name": cleaned,
            "eligibility": f"Scheme under {ministry_name}",
        })

    section_entries = []
    try:
        accordion_items = page.locator(".accordion-item")
        count = min(accordion_items.count(), max_sections)
        for index in range(count):
            try:
                item = accordion_items.nth(index)
                if item.is_visible():
                    section_entries.append(("item", index, item))
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"[DISCOVERY] Accordion item scan failed: {e}")

    if not section_entries:
        try:
            toggles = page.locator("[data-bs-toggle='collapse']")
            count = min(toggles.count(), max_sections)
            for index in range(count):
                section_entries.append(("toggle", index, toggles.nth(index)))
        except Exception as e:
            logger.debug(f"[DISCOVERY] Collapse toggle scan failed: {e}")

    if not section_entries:
        try:
            text_headers = page.locator("text=/(Ministry|Department|Council|Board|Commission)/i")
            count = min(text_headers.count(), max_sections)
            for index in range(count):
                section_entries.append(("text", index, text_headers.nth(index)))
        except Exception as e:
            logger.debug(f"[DISCOVERY] Text header scan failed: {e}")

    logger.info(f"[DISCOVERY] Accordion sections found: {len(section_entries)}")

    for entry_type, index, base_locator in section_entries[:max_sections]:
        ministry_name = ""
        header = None
        section_root = base_locator

        try:
            if entry_type == "item":
                section_root = base_locator
                header_candidates = [
                    section_root.locator("[data-bs-toggle='collapse']").first,
                    section_root.locator(".accordion-button").first,
                    section_root.get_by_role("button").first,
                    section_root.locator("text=/(Ministry|Department|Council|Board|Commission)/i").first,
                ]
                for candidate in header_candidates:
                    try:
                        if candidate.count() > 0 and candidate.is_visible():
                            header = candidate
                            break
                    except Exception:
                        continue
            else:
                header = base_locator
                try:
                    section_root = base_locator.locator("xpath=ancestor::*[contains(@class,'accordion-item')][1]").first
                except Exception:
                    section_root = base_locator

            if header is None:
                continue

            ministry_name = _text(header)
            if not ministry_name:
                ministry_name = f"Section {index + 1}"

            expanded_before = False
            try:
                expanded_before = (header.get_attribute("aria-expanded") or "").lower() == "true"
            except Exception:
                expanded_before = False

            try:
                header.click(timeout=3000, force=False)
                page.wait_for_timeout(800)
            except Exception as e:
                logger.debug(f"[DISCOVERY] Accordion click failed for {ministry_name}: {e}")
                continue

            scheme_locators = [
                section_root.locator("a[href*='scheme']"),
                section_root.locator(".scheme-name"),
                section_root.locator(".collapse.show li"),
            ]

            section_count = 0
            for scheme_locator in scheme_locators:
                try:
                    count = scheme_locator.count()
                except Exception:
                    continue

                for scheme_index in range(count):
                    try:
                        scheme_name = _text(scheme_locator.nth(scheme_index))
                        before = len(schemes)
                        _add_scheme(scheme_name, ministry_name)
                        if len(schemes) > before:
                            section_count += 1
                    except Exception:
                        continue

            logger.info(
                f"[DISCOVERY] Extracted {section_count} schemes from accordion: {ministry_name}"
            )

            if not expanded_before:
                try:
                    header.click(timeout=2000, force=False)
                    page.wait_for_timeout(500)
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"[DISCOVERY] Accordion extraction failed at section {index + 1}: {e}")
            continue

    logger.info(f"[DISCOVERY] Accordion schemes extracted: {len(schemes)}")
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
        page.wait_for_timeout(2000)
    except Exception as e:
        logger.error(f"[NAV] Direct navigation failed: {e}")
        return False

    if "All-Scholarships" not in page.url:
        logger.error(f"[NAV] Unexpected URL after direct navigation: {page.url}")
        return False

    try:
        has_title = page.get_by_text("Schemes On NSP").count() > 0
    except Exception:
        has_title = False

    try:
        has_accordion = page.locator(".accordion-item, [data-bs-toggle='collapse']").count() > 0
    except Exception:
        has_accordion = False

    if not has_title and not has_accordion:
        logger.error("[NAV] Schemes page did not expose expected content")
        return False

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
