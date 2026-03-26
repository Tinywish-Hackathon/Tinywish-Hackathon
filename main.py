import sys
import argparse
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
from sites.nsp import FLOW as NSP_FLOW, INTENT as NSP_INTENT
from config import Config

if not Config.TINYFISH_API_KEY:
    raise ValueError("Missing TINYFISH_API_KEY in .env file")

print("[CONFIG] TinyFish key loaded:", bool(Config.TINYFISH_API_KEY))

logger = get_logger("main")



def wait(msg):
    input(f"\n[MANUAL STEP] {msg} → Press Enter...")


def run_discovery():
    """Run scheme discovery mode: scrape → match → rank → display."""
    from core.discovery.nsp_scraper import get_nsp_schemes
    from core.discovery.eligibility import find_eligible_schemes
    from core.discovery.ranking import rank_schemes, format_ranked_output

    profile = load_profile(config.PROFILE_PATH)

    logger.info("[DISCOVERY] Starting scheme discovery...")
    schemes = get_nsp_schemes(use_cache=True)

    if not schemes:
        print("Could not load schemes. Run with --no-cache to retry scrape.")
        return

    eligible = find_eligible_schemes(profile, schemes)

    if not eligible:
        print("No eligible schemes found for your profile.")
        print("Tip: Check state/category spelling in profile.json")
        return

    ranked = rank_schemes(profile, eligible)
    print(format_ranked_output(ranked))

    # Selection loop
    while True:
        try:
            choice = input("\nSelect scheme number to apply (0 to exit): ").strip()
            n = int(choice)
            if n == 0:
                print("Exiting.")
                return
            if 1 <= n <= len(ranked):
                selected = ranked[n - 1]
                print(f"\nSelected: {selected['name']}")
                print("Handing off to application agent...")
                # TODO: pass selected["name"] into flow engine
                # main_flow(selected_scheme=selected["name"])
                return
            else:
                print(f"Please enter a number between 1 and {len(ranked)}")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\nCancelled.")
            return


def main():
    # --- Launch browser using executor module ---
    p, browser, context, page = start_browser()

    try:
        logger.info("Opening NSP...")
        page.goto(config.START_URL)
        page.wait_for_load_state("domcontentloaded")
        logger.info(f"Page loaded — URL: {page.url}")

        # --- Run the site-specific navigation flow ---
        results = run_flow(page, NSP_FLOW, flow_intent=NSP_INTENT)
        logger.info(f"Navigation flow: {results['completed']}/{results['total']} steps completed, {results.get('skipped', 0)} skipped")

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
    parser = argparse.ArgumentParser(description="Tinywish Automation Agent")
    parser.add_argument("--discover", action="store_true",
                        help="Run scheme discovery mode")
    parser.add_argument("--apply", action="store_true",
                        help="Run application/login mode (default)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Force fresh scrape (use with --discover)")
    args = parser.parse_args()

    # Set global intent mode
    from core.intent_filter import set_mode
    if args.discover:
        set_mode("discover")
    else:
        set_mode("apply")

    if args.discover:
        if args.no_cache:
            from core.discovery import nsp_scraper
            nsp_scraper._FORCE_REFRESH = True
        run_discovery()
    else:
        main()