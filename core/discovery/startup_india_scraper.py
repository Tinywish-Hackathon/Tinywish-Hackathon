"""Startup India government scheme scraper with cache and fallback data."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

from utils.logger import get_logger

logger = get_logger("startup_india_scraper")

_SOURCE_URL = "https://www.startupindia.gov.in/content/sih/en/government-schemes.html"
_CACHE_PATH = Path(__file__).with_name("startup_india_cache.json")
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
_EXCLUDED_TITLES = {
    "dashboard",
    "login",
    "register",
    "filter",
    "reset",
    "related links",
    "startup india investor connect",
    "funding guide",
    "central govt. schemes and policies",
    "startup india regulatory support",
    "women entrepreneurship",
    "incubator schemes",
    "know your state/ut startup policies",
    "programs and challenges",
    "india go-to-market guide",
    "international engagement",
    "procurement by government",
}
_TITLE_KEYWORDS = ("startup", "scheme", "fund", "guarantee", "sidbi", "credit")
_FALLBACK_SCHEMES = [
    {
        "name": "Startup India Seed Fund Scheme",
        "eligibility": (
            "Supports eligible startups with proof of concept, prototype development, "
            "product trials, market entry, and commercialization support."
        ),
        "source": "Startup India",
        "source_type": "government",
        "apply_link": "https://seedfund.startupindia.gov.in/",
        "provider": "DPIIT",
    },
    {
        "name": "SIDBI Fund of Funds",
        "eligibility": (
            "Enables startup financing through SEBI-registered alternative investment "
            "funds backed under the Fund of Funds for Startups initiative."
        ),
        "source": "Startup India",
        "source_type": "government",
        "apply_link": _SOURCE_URL,
        "provider": "DPIIT",
    },
    {
        "name": "Credit Guarantee Scheme for Startups",
        "eligibility": (
            "Offers credit guarantee cover to improve collateral-free debt access for "
            "recognized startups seeking institutional finance."
        ),
        "source": "Startup India",
        "source_type": "government",
        "apply_link": _SOURCE_URL,
        "provider": "DPIIT",
    },
]


def _load_cache() -> list[dict] | None:
    try:
        if _CACHE_PATH.exists() and _CACHE_PATH.stat().st_size > 0:
            with _CACHE_PATH.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, list) and payload:
                return payload
    except Exception as exc:
        logger.warning(f"[DISCOVERY] Startup India cache read failed: {exc}")
    return None


def _save_cache(schemes: list[dict]) -> None:
    try:
        with _CACHE_PATH.open("w", encoding="utf-8") as handle:
            json.dump(schemes, handle, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning(f"[DISCOVERY] Startup India cache write failed: {exc}")


def _clean_text(value) -> str:
    return " ".join(str(value or "").split()).strip()


def _is_scheme_title(title: str) -> bool:
    lowered = title.lower()
    if len(title) < 8 or lowered in _EXCLUDED_TITLES:
        return False
    return any(keyword in lowered for keyword in _TITLE_KEYWORDS)


def _extract_description(container, title: str) -> str:
    for selector in ("p", "small", ".desc", ".description", ".scheme-description", "li"):
        node = container.select_one(selector)
        if node:
            text = _clean_text(node.get_text(" ", strip=True))
            if text and text.lower() != title.lower():
                return text

    text = _clean_text(container.get_text(" ", strip=True))
    if not text:
        return ""

    if text.lower().startswith(title.lower()):
        text = _clean_text(text[len(title):])
    return text[:320]


def _normalize_entry(title: str, description: str, href: str = "") -> dict:
    return {
        "name": title,
        "eligibility": description,
        "source": "Startup India",
        "source_type": "government",
        "apply_link": urljoin(_SOURCE_URL, href) if href else _SOURCE_URL,
        "provider": "DPIIT",
    }


def _parse_scheme_containers(soup) -> list[dict]:
    results = []
    seen = set()

    selectors = [
        ".scheme-card",
        ".scheme-item",
        ".card",
        ".views-row",
        ".gov-scheme",
        ".tile",
        "article",
        "li",
    ]

    for selector in selectors:
        for container in soup.select(selector):
            anchor = container.select_one("a[href]")
            heading = container.select_one("h1, h2, h3, h4, h5, h6, a[href]")
            if not heading:
                continue

            title = _clean_text(heading.get_text(" ", strip=True))
            if not _is_scheme_title(title):
                continue

            key = title.lower()
            if key in seen:
                continue

            description = _extract_description(container, title)
            href = (anchor.get("href") if anchor else "") or ""
            results.append(_normalize_entry(title, description, href))
            seen.add(key)

    return results


def _parse_anchor_fallback(soup) -> list[dict]:
    results = []
    seen = set()

    for anchor in soup.select("a[href]"):
        title = _clean_text(anchor.get_text(" ", strip=True))
        if not _is_scheme_title(title):
            continue

        key = title.lower()
        if key in seen:
            continue

        parent = anchor.parent if getattr(anchor, "parent", None) else anchor
        description = _extract_description(parent, title)
        href = anchor.get("href") or ""
        results.append(_normalize_entry(title, description, href))
        seen.add(key)

    return results


def _deduplicate(schemes: list[dict]) -> list[dict]:
    unique = {}
    for scheme in schemes:
        name = _clean_text(scheme.get("name"))
        if not name:
            continue
        unique.setdefault(name.lower(), {**scheme, "name": name})
    return list(unique.values())


def _scrape_live_schemes() -> list[dict]:
    try:
        from bs4 import BeautifulSoup
    except Exception as exc:
        logger.warning(f"[DISCOVERY] BeautifulSoup unavailable, using Startup India fallback: {exc}")
        return []

    try:
        import requests
    except Exception as exc:
        logger.warning(f"[DISCOVERY] requests unavailable, using Startup India fallback: {exc}")
        return []

    response = requests.get(_SOURCE_URL, headers=_REQUEST_HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    schemes = _parse_scheme_containers(soup)
    if len(schemes) < 3:
        schemes = _deduplicate(schemes + _parse_anchor_fallback(soup))

    return schemes


def get_startup_india_schemes(use_cache=True) -> list[dict]:
    """Return Startup India schemes from cache, live scrape, or fallback data."""
    if use_cache:
        cached = _load_cache()
        if cached:
            logger.info(f"[DISCOVERY] Startup India cache hit: {len(cached)} schemes")
            return cached

    try:
        schemes = _deduplicate(_scrape_live_schemes())
        if len(schemes) >= 3:
            _save_cache(schemes)
            logger.info(f"[DISCOVERY] Startup India live scrape: {len(schemes)} schemes")
            return schemes
        raise ValueError("insufficient Startup India schemes extracted")
    except Exception as exc:
        logger.warning(f"[DISCOVERY] Startup India scrape failed, using fallback: {exc}")
        return [dict(item) for item in _FALLBACK_SCHEMES]
