"""Multi-source scholarship discovery and merge helpers."""

import html
import re
from difflib import SequenceMatcher
from urllib import error, request

from core.discovery.nsp_scraper import get_nsp_schemes
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


def _normalize_scheme(name, source):
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
    }


def _extract_schemes_from_html(html_text, source):
    schemes = []
    seen = set()

    for raw_title in _TITLE_PATTERN.findall(html_text):
        normalized = _normalize_scheme(raw_title, source)
        if not normalized:
            continue

        key = normalized["name"].strip().lower()
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
            name = scheme.get("name", "")
            normalized = _normalize_scheme(name, "NSP")
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
    """Scrape scholarship names from Buddy4Study public pages."""
    urls = [
        "https://www.buddy4study.com/scholarships",
        "https://www.buddy4study.com/article/fully-funded-scholarships",
        "https://www.buddy4study.com/article/buddy4study-scholarship-programme",
    ]
    schemes = []

    for url in urls:
        try:
            schemes.extend(_extract_schemes_from_html(_fetch_html(url), "Buddy4Study"))
        except Exception as e:
            logger.warning(f"[DISCOVERY] Buddy4Study fetch failed for {url}: {e}")

    schemes = merge_schemes([schemes])
    logger.info(f"[DISCOVERY] Buddy4Study: {len(schemes)} schemes")
    return schemes


def scrape_careers360():
    """Scrape scholarship names from Careers360 public scholarship pages."""
    urls = [
        "https://school.careers360.com/articles/scholarships-in-india",
        "https://school.careers360.com/articles/state-scholarships",
        "https://news.careers360.com/cbse-central-sector-scheme-of-scholarship-2025-applications-open-scholarships-gov-in-csss-application",
    ]
    schemes = []

    for url in urls:
        try:
            schemes.extend(_extract_schemes_from_html(_fetch_html(url), "Careers360"))
        except Exception as e:
            logger.warning(f"[DISCOVERY] Careers360 fetch failed for {url}: {e}")

    schemes = merge_schemes([schemes])
    logger.info(f"[DISCOVERY] Careers360: {len(schemes)} schemes")
    return schemes


def _detail_score(entry):
    score = 0
    for key in ("state", "category", "course_level", "source"):
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


def merge_schemes(all_sources):
    """Merge multiple scheme lists, deduplicating by name similarity."""
    merged = []

    for source_list in all_sources:
        for scheme in source_list:
            if not scheme or not scheme.get("name"):
                continue

            existing_index = None
            for index, existing in enumerate(merged):
                if _is_similar_name(existing["name"], scheme["name"]):
                    existing_index = index
                    break

            if existing_index is None:
                merged.append(dict(scheme))
                continue

            existing = merged[existing_index]
            if _detail_score(scheme) > _detail_score(existing):
                merged[existing_index] = dict(scheme)
            else:
                for key, value in scheme.items():
                    if existing.get(key) in ("", None) and value not in ("", None):
                        existing[key] = value

    logger.info(f"[DISCOVERY] TOTAL after merge: {len(merged)} schemes")
    return merged
