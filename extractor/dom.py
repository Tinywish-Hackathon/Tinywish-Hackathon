from utils.logger import get_logger

logger = get_logger("dom")


def detect_iframes(page):
    """Detect and log all iframes on the page. Returns list of iframe info dicts."""
    iframes = page.locator("iframe").all()
    results = []

    for iframe in iframes:
        try:
            info = {
                "src": iframe.get_attribute("src") or "",
                "name": iframe.get_attribute("name") or "",
                "id": iframe.get_attribute("id") or "",
            }
            results.append(info)
        except Exception:
            continue

    if results:
        logger.info(f"Detected {len(results)} iframe(s)")
        for i, info in enumerate(results):
            logger.debug(f"  iframe[{i}]: src={info['src'][:80]}, name={info['name']}")
    else:
        logger.info("No iframes detected on page")

    return results


def log_page_elements(page):
    """Log counts of interactive elements on the current page."""
    counts = {}
    for tag in ["input", "select", "textarea", "button"]:
        try:
            counts[tag] = page.locator(tag).count()
        except Exception:
            counts[tag] = 0

    logger.info(
        f"Page elements → inputs: {counts['input']}, selects: {counts['select']}, "
        f"textareas: {counts['textarea']}, buttons: {counts['button']}"
    )
    return counts
