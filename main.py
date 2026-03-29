import sys
import argparse
import os
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
logger = get_logger("main")
from config import Config

TINYFISH_AVAILABLE = bool(os.getenv("TINYFISH_API_KEY"))

if not TINYFISH_AVAILABLE:
    logger.warning(
        "[CONFIG] TINYFISH_API_KEY not set. TinyFish ranking and application intelligence "
        "will be unavailable. Running in offline mode."
    )
else:
    print("[CONFIG] TinyFish key loaded:", True)



def wait(msg):
    input(f"\n[MANUAL STEP] {msg} → Press Enter...")


def _build_manual_handoff_payload(selected):
    apply_link = selected.get("apply_link") or config.START_URL
    return {
        "apply_link": apply_link,
        "fields": [],
        "documents": [],
        "steps": [
            "Open the scholarship portal",
            "Complete login or OTP manually",
            f"Search for and continue the application for {selected['name']}",
        ],
        "form_detected": False,
    }


def _run_discovery_handoff(
    selected,
    profile,
    handoff_mode,
    handle_human_handoff,
    open_local_preview,
    run_tinyfish_application_agent,
):
    apply_link = selected.get("apply_link") or config.START_URL
    manual_payload = _build_manual_handoff_payload(selected)
    preview_mode = handoff_mode in {"local", "hybrid"}

    if preview_mode:
        print("Opening local preview...")
        open_local_preview(apply_link)

    if handoff_mode == "local":
        handle_human_handoff(manual_payload, profile, open_browser=False)
        return

    if TINYFISH_AVAILABLE:
        try:
            run_tinyfish_application_agent(
                selected["name"],
                profile=profile,
                apply_link=apply_link,
                open_browser=not preview_mode,
            )
        except Exception as e:
            logger.error(f"[APPLICATION] TinyFish application agent failed: {e}")
            print("Application agent failed. Check logs for details.")
            if preview_mode:
                handle_human_handoff(manual_payload, profile, open_browser=False)
        return

    if preview_mode:
        print("TinyFish application intelligence unavailable. Using local preview with manual continuation.")
    else:
        print("TinyFish application intelligence unavailable. Opening portal directly.")
    handle_human_handoff(manual_payload, profile, open_browser=not preview_mode)


def run_discovery(handoff_mode="agent"):
    """Run scheme discovery mode: scrape → match → rank → display."""
    from core.application_agent import (
        handle_human_handoff,
        open_local_preview,
        run_tinyfish_application_agent,
    )
    from core.discovery.eligibility import find_eligible_schemes
    from core.discovery.multi_source import (
        merge_schemes,
        scrape_buddy4study,
        scrape_international_scholarships,
        scrape_myscheme,
        scrape_nsp,
        scrape_scholarships360,
        scrape_we_make_scholars,
    )
    from core.discovery.ranking import _rule_based_rank, rank_schemes, format_ranked_output

    profile = load_profile(config.PROFILE_PATH)

    logger.info("[DISCOVERY] Starting scheme discovery...")
    source_lists = [
        scrape_nsp(),
        scrape_myscheme(),
        scrape_buddy4study(),
        scrape_we_make_scholars(),
        scrape_scholarships360(),
        scrape_international_scholarships(),
    ]
    schemes = merge_schemes(source_lists)

    if not schemes:
        print("Could not load schemes. Run with --no-cache to retry scrape.")
        return

    eligible = find_eligible_schemes(profile, schemes)

    if not eligible:
        print("No eligible schemes found for your profile.")
        print("Tip: Check state/category spelling in profile.json")
        return

    if TINYFISH_AVAILABLE:
        ranked = rank_schemes(profile, eligible)
    else:
        print("Note: TinyFish ranking unavailable. Using rule-based ranking.")
        ranked = _rule_based_rank(eligible)
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
                _run_discovery_handoff(
                    selected,
                    profile,
                    handoff_mode,
                    handle_human_handoff,
                    open_local_preview,
                    run_tinyfish_application_agent,
                )
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
    parser.add_argument(
        "--mode",
        choices=["agent", "hybrid", "local"],
        default="agent",
        help="Discovery handoff mode: agent uses TinyFish, hybrid opens a local preview first, local uses local preview only",
    )
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
        run_discovery(handoff_mode=args.mode)
    else:
        if args.mode != "agent":
            print("[CONFIG] --mode only affects --discover. Running local apply flow.")
        main()
