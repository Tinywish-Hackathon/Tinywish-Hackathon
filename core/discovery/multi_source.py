"""Multi-source scholarship discovery and merge helpers."""

import html
import re
from difflib import SequenceMatcher
from typing import Any
from urllib import request

from core.discovery.nsp_scraper import get_nsp_schemes
from schemas.scheme_model import SchemeModel
from utils.logger import get_logger

logger = get_logger("multi_source_discovery")

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

_TITLE_PATTERN = re.compile(
    r"<(?:a|h1|h2|h3|h4)[^>]*>(.*?)</(?:a|h1|h2|h3|h4)>",
    re.IGNORECASE | re.DOTALL,
)
_ANCHOR_PATTERN = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_PATTERN = re.compile(r"<[^>]+>")
_SPACE_PATTERN = re.compile(r"\s+")
_INCOME_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*lakh", re.IGNORECASE)

_STATE_KEYWORDS = {
    "Jammu and Kashmir": ["jammu", "kashmir", "j&k"],
    "Delhi": ["delhi", "new delhi"],
    "Punjab": ["punjab"],
    "Rajasthan": ["rajasthan"],
    "Uttar Pradesh": ["uttar pradesh", "up"],
    "West Bengal": ["west bengal", "bengal"],
    "Maharashtra": ["maharashtra"],
    "Karnataka": ["karnataka"],
    "Tamil Nadu": ["tamil nadu", "tn"],
}

_CATEGORY_KEYWORDS = {
    "OBC": ["obc", "backward", "ebc", "dnt"],
    "SC": ["sc", "scheduled caste"],
    "ST": ["st", "scheduled tribe"],
    "Minority": ["minority"],
    "EWS": ["ews", "economically weaker"],
    "Girls": ["girls", "girl", "female", "women"],
}

_COURSE_KEYWORDS = {
    "school": ["pre-matric", "school", "class 9", "class 10", "class 11", "class 12"],
    "undergraduate": ["undergraduate", "graduation", "graduate", "ug", "post-matric"],
    "postgraduate": ["postgraduate", "pg", "masters", "phd", "doctoral"],
}


def _fetch_html(url):
    req = request.Request(url, headers=_REQUEST_HEADERS)
    with request.urlopen(req, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _clean_text(value):
    stripped = _TAG_PATTERN.sub(" ", html.unescape(str(value or "")))
    return _SPACE_PATTERN.sub(" ", stripped).strip()


def _extract_income_limit(text):
    match = _INCOME_PATTERN.search(text)
    if not match:
        return None
    return int(float(match.group(1)) * 100000)


def _infer_state(name):
    lowered = name.lower()
    for state, keywords in _STATE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return state
    if "all india" in lowered or "national" in lowered:
        return "All India"
    return ""


def _infer_category(name):
    lowered = name.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return ""


def _infer_course_level(name):
    lowered = name.lower()
    for level, keywords in _COURSE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return level
    return ""


def _normalize_government_scheme(name, source):
    cleaned_name = _clean_text(name)
    if len(cleaned_name) < 8:
        return None

    lowered = cleaned_name.lower()
    if "scholarship" not in lowered and "scheme" not in lowered:
        return None

    return {
        "name": cleaned_name,
        "state": _infer_state(cleaned_name),
        "category": _infer_category(cleaned_name),
        "income_limit": _extract_income_limit(cleaned_name),
        "course_level": _infer_course_level(cleaned_name),
        "source": source,
        "source_type": "government",
    }


def _normalize_private_scheme(name, provider, apply_link="", eligibility=""):
    cleaned_name = _clean_text(name)
    if len(cleaned_name) < 8:
        return None

    lowered = cleaned_name.lower()
    if "scholarship" not in lowered and "grant" not in lowered and "fellowship" not in lowered:
        return None

    return {
        "name": cleaned_name,
        "provider": provider,
        "eligibility": _clean_text(eligibility),
        "apply_link": apply_link.strip(),
        "type": "private",
        "source": provider,
        "source_type": "private",
        "state": _infer_state(cleaned_name),
        "category": _infer_category(cleaned_name),
        "income_limit": _extract_income_limit(f"{cleaned_name} {eligibility}"),
        "course_level": _infer_course_level(cleaned_name),
    }


def _extract_schemes_from_html(html_text, source):
    schemes = []
    seen = set()

    for raw_title in _TITLE_PATTERN.findall(html_text):
        normalized = _normalize_government_scheme(raw_title, source)
        if not normalized:
            continue

        key = normalized["name"].strip().lower()
        if key in seen:
            continue

        seen.add(key)
        schemes.append(normalized)

    return schemes


def _absolute_link(base_url, href):
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        parts = base_url.split("/", 3)
        if len(parts) >= 3:
            return f"{parts[0]}//{parts[2]}{href}"
    return ""


def _extract_private_schemes_from_html(html_text, provider, base_url):
    schemes = []
    seen = set()

    for href, anchor_html in _ANCHOR_PATTERN.findall(html_text):
        title = _clean_text(anchor_html)
        apply_link = _absolute_link(base_url, href)
        normalized = _normalize_private_scheme(title, provider, apply_link=apply_link)
        if not normalized:
            continue

        key = normalized["name"].lower()
        if key in seen:
            continue

        seen.add(key)
        schemes.append(normalized)

    return schemes


def scrape_nsp():
    """Scrape scholarship schemes from NSP using the existing scraper."""
    schemes = []
    try:
        raw_schemes = get_nsp_schemes(use_cache=True)
        for scheme in raw_schemes:
            normalized = _normalize_government_scheme(scheme.get("name", ""), "NSP")
            if normalized:
                schemes.append(normalized)
    except Exception as e:
        logger.warning(f"[DISCOVERY] NSP scrape failed: {e}")

    logger.info(f"[DISCOVERY] NSP: {len(schemes)} schemes")
    return schemes


def scrape_myscheme():
    """Scrape scholarship-like scheme names from MyScheme."""
    urls = [
        "https://www.myscheme.gov.in/schemes",
        "https://www.myscheme.gov.in/search",
    ]
    schemes = []

    for url in urls:
        try:
            schemes.extend(_extract_schemes_from_html(_fetch_html(url), "MyScheme"))
        except Exception as e:
            logger.warning(f"[DISCOVERY] MyScheme fetch failed for {url}: {e}")

    schemes = merge_schemes([schemes])
    logger.info(f"[DISCOVERY] MyScheme: {len(schemes)} schemes")
    return schemes


def scrape_buddy4study():
    """Scrape private scholarships from Buddy4Study."""
    urls = [
        "https://www.buddy4study.com/scholarships",
        "https://www.buddy4study.com/article/scholarships-in-india",
    ]
    schemes = []

    for url in urls:
        try:
            schemes.extend(_extract_private_schemes_from_html(_fetch_html(url), "Buddy4Study", url))
        except Exception as e:
            logger.warning(f"[DISCOVERY] Buddy4Study fetch failed for {url}: {e}")

    schemes = merge_schemes([schemes])
    logger.info(f"[DISCOVERY] Buddy4Study: {len(schemes)} schemes")
    return schemes


def scrape_we_make_scholars():
    """Scrape private scholarships from WeMakeScholars."""
    urls = [
        "https://www.wemakescholars.com/scholarships",
        "https://www.wemakescholars.com/other-scholarships",
    ]
    schemes = []

    for url in urls:
        try:
            schemes.extend(_extract_private_schemes_from_html(_fetch_html(url), "WeMakeScholars", url))
        except Exception as e:
            logger.warning(f"[DISCOVERY] WeMakeScholars fetch failed for {url}: {e}")

    schemes = merge_schemes([schemes])
    logger.info(f"[DISCOVERY] WeMakeScholars: {len(schemes)} schemes")
    return schemes


def scrape_scholarships360():
    """Scrape private scholarships from Scholarships360."""
    urls = [
        "https://scholarships360.org/scholarships/",
        "https://scholarships360.org/featured-scholarships/",
    ]
    schemes = []

    for url in urls:
        try:
            schemes.extend(_extract_private_schemes_from_html(_fetch_html(url), "Scholarships360", url))
        except Exception as e:
            logger.warning(f"[DISCOVERY] Scholarships360 fetch failed for {url}: {e}")

    schemes = merge_schemes([schemes])
    logger.info(f"[DISCOVERY] Scholarships360: {len(schemes)} schemes")
    return schemes


def scrape_international_scholarships():
    """Scrape private scholarships from International Scholarships."""
    urls = [
        "https://www.internationalscholarships.com/scholarships",
        "https://www.internationalscholarships.com/resources",
    ]
    schemes = []

    for url in urls:
        try:
            schemes.extend(
                _extract_private_schemes_from_html(_fetch_html(url), "International Scholarships", url)
            )
        except Exception as e:
            logger.warning(f"[DISCOVERY] International Scholarships fetch failed for {url}: {e}")

    schemes = merge_schemes([schemes])
    logger.info(f"[DISCOVERY] International Scholarships: {len(schemes)} schemes")
    return schemes


def _detail_score(entry):
    score = 0
    for key in (
        "state",
        "category",
        "course_level",
        "source",
        "provider",
        "eligibility",
        "apply_link",
        "source_type",
    ):
        if entry.get(key):
            score += 1
    if entry.get("income_limit") is not None:
        score += 1
    score += min(len(entry.get("name", "")) // 30, 2)
    return score


def _is_similar_name(left, right, threshold=0.85):
    left_key = left.strip().lower()
    right_key = right.strip().lower()
    if left_key == right_key:
        return True
    return SequenceMatcher(None, left_key, right_key).ratio() >= threshold


def _scheme_to_dict(scheme: SchemeModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(scheme, SchemeModel):
        return scheme.model_dump()
    return dict(scheme or {})


def merge_and_deduplicate(all_sources) -> list[SchemeModel]:
    """Merge multiple scheme lists, deduplicating by name similarity."""
    merged = []

    for source_list in all_sources:
        for scheme in source_list:
            scheme_copy = _scheme_to_dict(scheme)
            if not scheme_copy or not scheme_copy.get("name"):
                continue

            if scheme_copy.get("type") == "private" or scheme_copy.get("provider"):
                scheme_copy["source_type"] = "private"
            else:
                scheme_copy["source_type"] = scheme_copy.get("source_type", "government")

            existing_index = None
            for index, existing in enumerate(merged):
                if _is_similar_name(existing["name"], scheme_copy["name"]):
                    existing_index = index
                    break

            if existing_index is None:
                merged.append(scheme_copy)
                continue

            existing = merged[existing_index]
            if _detail_score(scheme_copy) > _detail_score(existing):
                merged[existing_index] = scheme_copy
            else:
                for key, value in scheme_copy.items():
                    if existing.get(key) in ("", None) and value not in ("", None):
                        existing[key] = value

    merged_models = [SchemeModel.from_dict(entry) for entry in merged if entry.get("name")]
    logger.info(f"[DISCOVERY] TOTAL after merge: {len(merged_models)} schemes")
    return merged_models


def merge_schemes(all_sources) -> list[SchemeModel]:
    return merge_and_deduplicate(all_sources)
