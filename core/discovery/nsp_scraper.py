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

def parse_tinyfish_result(result):
    """Normalize TinyFish responses into a list of scheme dicts."""
    def _get_value(obj, key):
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    def _strip_code_fence(value):
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

    def _decode(value):
        if isinstance(value, str):
            cleaned = _strip_code_fence(value)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                return cleaned
        return value

    def _normalize_item(item):
        if not isinstance(item, dict):
            return None

        name = (
            item.get("name")
            or item.get("scheme_name")
            or item.get("scheme")
            or item.get("title")
        )
        eligibility = (
            item.get("eligibility")
            or item.get("eligibility_criteria")
            or item.get("criteria")
            or item.get("description")
            or ""
        )

        if not name:
            return None

        return {
            "name": str(name).strip(),
            "eligibility": str(eligibility).strip(),
        }

    def _extract(value):
        value = _decode(value)

        if value is None:
            return []

        if isinstance(value, list):
            normalized = []
            for item in value:
                normalized.extend(_extract(item))
            return normalized

        if isinstance(value, dict):
            normalized_item = _normalize_item(value)
            if normalized_item:
                return [normalized_item]

            for key in (
                "data",
                "resultJson",
                "result_json",
                "output",
                "result",
                "final",
                "response",
                "content",
                "text",
                "message",
                "items",
                "results",
                "value",
            ):
                extracted = _extract(value.get(key))
                if extracted:
                    return extracted
            return []

        if isinstance(value, str):
            decoded = _decode(value)
            if decoded is not value:
                return _extract(decoded)
            return []

        for key in (
            "data",
            "resultJson",
            "result_json",
            "output",
            "result",
            "final",
            "response",
            "content",
            "text",
            "message",
            "items",
            "results",
            "value",
        ):
            extracted = _extract(_get_value(value, key))
            if extracted:
                return extracted

        return []

    normalized = _extract(result)
    deduped = []
    seen = set()
    for item in normalized:
        key = item["name"].strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def try_tinyfish():
    """Use TinyFish AI web agent to extract schemes."""
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

    print("[DISCOVERY] Using TinyFish...")
    logger.info("[DISCOVERY] Using TinyFish...")

    goal = """
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
            """

    def _get_value(obj, key):
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    def _call_with_variants(fn):
        last_error = None
        kwargs_attempts = [
            {"goal": goal, "max_steps": 40},
            {"instructions": goal, "max_steps": 40},
            {"prompt": goal, "max_steps": 40},
            {"task": goal, "max_steps": 40},
            {"input": goal, "max_steps": 40},
            {"goal": goal},
            {"instructions": goal},
            {"prompt": goal},
            {"task": goal},
            {"input": goal},
        ]

        for kwargs in kwargs_attempts:
            try:
                return fn(**kwargs)
            except TypeError as e:
                last_error = e

        for args in ((goal, 40), (goal,)):
            try:
                return fn(*args)
            except TypeError as e:
                last_error = e

        if last_error:
            raise last_error
        return fn()

    def _collect_stream(stream_obj):
        final_payload = None

        try:
            iterator = iter(stream_obj)
        except TypeError:
            return stream_obj

        for event in iterator:
            for key in (
                "resultJson",
                "result_json",
                "data",
                "output",
                "result",
                "final",
                "response",
                "content",
                "text",
                "message",
            ):
                value = _get_value(event, key)
                if value is not None:
                    final_payload = value

            if final_payload is None:
                final_payload = event

        for attr in ("get_final_response", "final_response", "response", "result", "output", "data"):
            value = _get_value(stream_obj, attr)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    continue
            if value is not None:
                final_payload = value

        return final_payload

    def _run_tinyfish():
        attempts = [
            ("client.agent.stream", getattr(getattr(client, "agent", None), "stream", None), True),
            ("client.agents.run", getattr(getattr(client, "agents", None), "run", None), False),
            ("client.runs.create", getattr(getattr(client, "runs", None), "create", None), False),
            ("client.execute", getattr(client, "execute", None), False),
        ]

        last_error = None
        for label, fn, is_stream in attempts:
            if not callable(fn):
                continue

            try:
                logger.info(f"[DISCOVERY] TinyFish attempting {label}")
                result = _call_with_variants(fn)
                return _collect_stream(result) if is_stream else result
            except Exception as e:
                last_error = e
                logger.warning(f"[DISCOVERY] TinyFish {label} failed: {e}")

        if last_error:
            raise last_error
        raise AttributeError("No supported TinyFish execution method found")

    try:
        result = _run_tinyfish()
        normalized = parse_tinyfish_result(result)
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

        if (
            "all-scholarships" in url
            or page.locator(".accordion-item").count() > 0
            or page.locator("[data-bs-toggle='collapse']").count() > 0
        ):
            print("[NAV] Reached schemes page")
            logger.info(f"[NAV] Reached schemes page: {page.url}")
            return True

        if any(token in url or token in text for token in target):
            try:
                if (
                    page.locator(".accordion-item").count() > 0
                    or page.locator("[data-bs-toggle='collapse']").count() > 0
                    or page.locator("text=/(Ministry|Department|Council|Board|Commission)/i").count() > 0
                ):
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
