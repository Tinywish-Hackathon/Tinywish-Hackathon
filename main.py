import config
from executor.browser import start_browser, wait_for_user_input, fill_field
from executor.actions import (
    get_visible, scroll_to_find, safe_click,
    find_by_text_fuzzy, safe_click_fuzzy, safe_click_in_section
)
from executor.flow_engine import run_flow
from extractor.dom import detect_iframes, log_page_elements
from extractor.field_extractor import extract_fields
from mapper.form_mapper import map_field
from utils.logger import get_logger
from utils.helpers import load_profile
from sites.nsp import FLOW as NSP_FLOW

logger = get_logger("main")


def wait(msg):
    input(f"\n[MANUAL STEP] {msg} → Press Enter...")


def main():
    # --- Launch browser using executor module ---
    p, browser, context, page = start_browser()

    try:
        logger.info("Opening NSP...")
        page.goto(config.START_URL)
        page.wait_for_load_state("domcontentloaded")
        logger.info(f"Page loaded — URL: {page.url}")

        # --- Run the site-specific navigation flow ---
        results = run_flow(page, NSP_FLOW)
        logger.info(f"Navigation flow: {results['completed']}/{results['total']} steps completed")

        # If any navigation steps failed, offer manual fallback
        if results["failed"] > 0:
            wait(f"{results['failed']} step(s) failed — verify page state manually")

        page.wait_for_timeout(3000)
        logger.info(f"Now at: {page.url}")

        # -----------------------------
        # WAIT FOR FORM
        # -----------------------------
        try:
            page.wait_for_selector("input", timeout=15000)
            logger.info("Form detected")
            log_page_elements(page)
        except Exception:
            wait("Ensure form is visible")

        # -----------------------------
        # STEP 6: FORM FILL (MODULAR)
        # -----------------------------
        logger.info("Extracting form fields...")
        profile = load_profile(config.PROFILE_PATH)

        fields = extract_fields(page)

        filled_count = 0
        for field_info in fields:
            key, value = map_field(field_info, profile)
            if key and value:
                fill_field(page, field_info, value)
                filled_count += 1

        logger.info(f"Filled {filled_count} / {len(fields)} fields from profile")

        wait("Check fields and submit manually")

        logger.info("Phase 1 flow complete.")

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        input("\nPress Enter to close browser...")
        browser.close()
        p.stop()
        logger.info("Browser closed. Done.")


if __name__ == "__main__":
    main()