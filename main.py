import config
from executor.browser import start_browser, wait_for_user_input, fill_field
from executor.actions import get_visible, scroll_to_find, safe_click
from extractor.dom import detect_iframes, log_page_elements
from extractor.field_extractor import extract_fields
from mapper.form_mapper import map_field
from utils.logger import get_logger
from utils.helpers import load_profile

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

        # --- Debug visibility: detect iframes and page elements ---
        detect_iframes(page)
        log_page_elements(page)

        # -----------------------------
        # STEP 1: STUDENTS (SAFE)
        # -----------------------------
        if "/Students" not in page.url:
            logger.info("Finding Students tile...")

            students = get_visible(page.locator("text=Students"))

            if students:
                safe_click(page, students, label="Students tile")
            else:
                wait("Click 'Students' manually")
        else:
            logger.info("Already in Students section")

        page.wait_for_timeout(3000)

        # --- Re-check page after navigation ---
        detect_iframes(page)
        log_page_elements(page)

        # -----------------------------
        # STEP 2: REVEAL OTR (CRITICAL)
        # -----------------------------
        logger.info("Revealing OTR section...")
        otr_element = scroll_to_find(page, "Get your OTR", max_attempts=10)

        if not otr_element:
            wait("Scroll manually until OTR is visible")

        # -----------------------------
        # STEP 3: CLICK APPLY NOW
        # -----------------------------
        logger.info("Looking for Apply Now button...")
        apply_btn = scroll_to_find(page, "Apply now", max_attempts=8)

        if apply_btn:
            safe_click(page, apply_btn, label="Apply Now")
        else:
            wait("Click Apply Now manually")

        page.wait_for_timeout(4000)
        logger.info(f"Now at: {page.url}")

        # -----------------------------
        # STEP 4: WAIT FOR FORM
        # -----------------------------
        try:
            page.wait_for_selector("input", timeout=15000)
            logger.info("Form detected")
            log_page_elements(page)
        except Exception:
            wait("Ensure form is visible")

        # -----------------------------
        # STEP 5: OTP / CAPTCHA
        # -----------------------------
        wait_for_user_input("Solve OTP / CAPTCHA if required")

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