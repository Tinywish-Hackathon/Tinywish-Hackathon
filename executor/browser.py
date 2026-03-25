from playwright.sync_api import sync_playwright
from utils.logger import get_logger

logger = get_logger("browser")


def start_browser():
    """Launch Chromium and return (playwright, browser, context, page) tuple."""
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(viewport={'width': 1280, 'height': 800})
    page = context.new_page()
    page.set_default_timeout(60000)
    logger.info("Browser launched (Chromium, headed mode)")
    return p, browser, context, page


def wait_for_user_input(message="Action Required"):
    """Pause automation for manual intervention (OTP, CAPTCHA, etc.)."""
    logger.warning(f"PAUSED: {message}")
    logger.info("Complete the required action in the browser.")
    input("Press ENTER in this terminal when you are ready to resume...")
    logger.info("Resuming automation...")


def fill_field(page, field_info, value):
    """Fill a single form field based on its type."""
    try:
        locator = field_info["locator"]
        if field_info["type"] == "file":
            locator.set_input_files(value)
            logger.info(f"Uploaded file: {value}")
        elif field_info["type"] in ["select-one", "select"]:
            try:
                locator.select_option(label=value)
            except Exception:
                locator.select_option(value=value)
            logger.info(f"Selected option: {value}")
        elif field_info["type"] in ["checkbox", "radio"]:
            if str(value).lower() in ["true", "yes", "1", "male", "female"]:
                locator.check()
                logger.info(f"Checked radio/checkbox")
        else:
            locator.fill(str(value))
            logger.info(f"Filled text: {value}")
    except Exception as e:
        logger.error(f"Failed to fill field {field_info.get('name')}: {e}")