import sys
import argparse
import os
from importlib.util import find_spec

import config
from utils.logger import get_logger
from utils.helpers import load_profile
from utils.tracker import init_tracker, log_application, print_application_history
from sites.nsp import FLOW as NSP_FLOW, INTENT as NSP_INTENT, URL as NSP_URL
from sites.startup_india import (
    FLOW as STARTUP_INDIA_FLOW,
    INTENT as STARTUP_INDIA_INTENT,
    URL as STARTUP_INDIA_URL,
)

logger = get_logger("main")


def _configure_console_encoding():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            continue


_configure_console_encoding()

_DEPENDENCY_MODULES = {
    "requests": "requests",
    "beautifulsoup4": "bs4",
    "tinyfish": "tinyfish",
    "playwright": "playwright",
}
_REPORTED_MISSING_DEPENDENCIES = set()
_LOGIN_WALL_KEYWORDS = (
    "login",
    "log in",
    "sign in",
    "signin",
    "otp",
    "one time password",
    "register",
)
_APPLY_KEYWORDS = (
    "apply",
    "application",
    "form",
)
_SITE_CONFIGS = {
    "nsp": {
        "label": "NSP",
        "url": NSP_URL,
        "flow": NSP_FLOW,
        "intent": NSP_INTENT,
    },
    "startup_india": {
        "label": "Startup India",
        "url": STARTUP_INDIA_URL,
        "flow": STARTUP_INDIA_FLOW,
        "intent": STARTUP_INDIA_INTENT,
    },
}


def _has_dependency(dependency_name):
    module_name = _DEPENDENCY_MODULES[dependency_name]
    loaded_module = sys.modules.get(module_name)
    if loaded_module is not None:
        return True
    return find_spec(module_name) is not None


def check_dependencies(require_tinyfish=False, require_browser=False, require_scrapers=False):
    required = set()
    if require_scrapers:
        required.update({"requests", "beautifulsoup4"})
    if require_tinyfish:
        required.add("tinyfish")
    if require_browser:
        required.add("playwright")

    missing = sorted(name for name in required if not _has_dependency(name))
    if missing:
        key = tuple(missing)
        if key not in _REPORTED_MISSING_DEPENDENCIES:
            print(f"Missing dependencies: {', '.join(missing)}. Install via pip install -r requirements.txt")
            logger.warning(f"[CONFIG] Missing dependencies: {', '.join(missing)}")
            _REPORTED_MISSING_DEPENDENCIES.add(key)
    return missing


TINYFISH_API_KEY_PRESENT = bool(os.getenv("TINYFISH_API_KEY"))
TINYFISH_SDK_AVAILABLE = _has_dependency("tinyfish")
TINYFISH_AVAILABLE = TINYFISH_API_KEY_PRESENT and TINYFISH_SDK_AVAILABLE

if not TINYFISH_AVAILABLE:
    reasons = []
    if not TINYFISH_API_KEY_PRESENT:
        reasons.append("TINYFISH_API_KEY not set")
    if not TINYFISH_SDK_AVAILABLE:
        reasons.append("tinyfish package not installed")
    logger.warning(
        f"[CONFIG] TinyFish unavailable ({', '.join(reasons)}). "
        "TinyFish ranking and application intelligence "
        "will be unavailable. Running in offline mode."
    )
else:
    print("[CONFIG] TinyFish key loaded:", True)



def wait(msg):
    input(f"\n[MANUAL STEP] {msg} → Press Enter...")


def _site_key_for_scheme(selected):
    source = str(getattr(selected, "source", "") or "").strip().lower()
    apply_link = str(getattr(selected, "apply_link", "") or "").strip().lower()

    if "startup india" in source or "startupindia.gov.in" in apply_link:
        return "startup_india"
    if source in {"nsp", "national scholarship portal"} or "scholarships.gov.in" in apply_link:
        return "nsp"
    return ""


def _site_config_for_scheme(selected):
    return _SITE_CONFIGS.get(_site_key_for_scheme(selected))


def _resolve_portal_url(selected):
    apply_link = str(getattr(selected, "apply_link", "") or "").strip()
    if apply_link:
        return apply_link

    site_config = _site_config_for_scheme(selected)
    if site_config:
        return site_config["url"]

    return ""


def _build_manual_handoff_payload(selected):
    apply_link = _resolve_portal_url(selected)
    return _build_strategy_handoff_payload(selected, "manual_assist", "", apply_link=apply_link)


def _scheme_signal_text(selected):
    parts = [
        getattr(selected, "name", ""),
        getattr(selected, "eligibility", ""),
        getattr(selected, "status", ""),
        getattr(selected, "apply_link", ""),
        getattr(selected, "tinyfish_reason", ""),
    ]
    return " ".join(str(part).strip().lower() for part in parts if part)


def choose_execution_strategy(scheme):
    status = str(getattr(scheme, "status", "") or "").strip().lower()
    signal_text = _scheme_signal_text(scheme)
    has_apply_link = bool(str(getattr(scheme, "apply_link", "") or "").strip())

    if status in {"closed", "expired"} or "closed" in signal_text or "expired" in signal_text:
        return "skip", "Scheme is marked closed or expired."

    if any(keyword in signal_text for keyword in _LOGIN_WALL_KEYWORDS):
        return "extract_only", "Login or OTP wall detected; extract visible requirements only."

    if has_apply_link and any(keyword in signal_text for keyword in _APPLY_KEYWORDS):
        return "full_apply", "Direct application signal detected from the selected portal."

    if has_apply_link:
        return "full_apply", "Apply link is available and no login wall was detected."

    return "manual_assist", "No direct apply path detected; using manual assist."


def _build_strategy_handoff_payload(selected, strategy, reason, apply_link=""):
    apply_link = str(apply_link or _resolve_portal_url(selected) or "").strip()
    if strategy == "skip":
        steps = [
            f"Skip automation for {selected.name}",
            "The scheme appears closed or expired",
            "Verify deadline and portal status manually before retrying",
        ]
    elif strategy == "extract_only":
        steps = [
            f"Open the selected page for {selected.name}",
            "Inspect visible requirements and form fields before authentication",
            "Stop when login, registration, or OTP is required and continue manually",
        ]
    elif strategy == "full_apply":
        steps = [
            f"Open the selected application page for {selected.name}",
            "Try the direct pre-auth application workflow first",
            "Stop and continue manually if login or OTP becomes mandatory",
        ]
    else:
        steps = [
            "Open the scholarship portal",
            "Review the visible application path manually",
            f"Search for and continue the application for {selected.name}",
        ]

    if reason:
        steps.append(f"Decision reason: {reason}")

    return {
        "apply_link": apply_link,
        "fields": [],
        "documents": [],
        "steps": steps,
        "form_detected": False,
    }


def run_local_apply_flow(site_url=None, site_flow=None, site_intent="apply"):
    site_url = str(site_url or config.START_URL).strip()
    site_flow = site_flow or NSP_FLOW

    if check_dependencies(require_browser=True):
        return False

    try:
        from executor.browser import fill_field, start_browser
        from executor.flow_engine import run_flow
        from extractor.dom import log_page_elements
        from extractor.field_extractor import extract_fields
        from mapper.form_mapper import map_field
    except Exception as e:
        logger.error(f"[CONFIG] Browser automation dependencies unavailable: {e}")
        return False

    p, browser, context, page = start_browser()

    try:
        logger.info(f"[AGENT] Opening portal: {site_url}")
        page.goto(site_url)
        page.wait_for_load_state("domcontentloaded")
        logger.info(f"Page loaded — URL: {page.url}")

        results = run_flow(page, site_flow, flow_intent=site_intent)
        logger.info(
            f"Navigation flow: {results['completed']}/{results['total']} steps completed, "
            f"{results.get('skipped', 0)} skipped"
        )

        if results["failed"] > 0:
            wait(f"{results['failed']} step(s) failed — verify page state manually")

        page.wait_for_timeout(3000)
        logger.info(f"Now at: {page.url}")

        try:
            page.wait_for_selector("input", timeout=15000)
            logger.info("Form detected")
            log_page_elements(page)
        except Exception:
            wait("Ensure form is visible")

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
        logger.info("Local portal flow complete.")
        return True
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return False
    finally:
        input("\nPress Enter to close browser...")
        browser.close()
        p.stop()
        logger.info("Browser closed. Done.")


def _run_local_portal_flow(selected):
    site_config = _site_config_for_scheme(selected)
    if not site_config:
        return False

    portal_url = _resolve_portal_url(selected) or site_config["url"]
    print(f"Launching local {site_config['label']} flow...")
    return run_local_apply_flow(
        site_url=portal_url,
        site_flow=site_config["flow"],
        site_intent=site_config["intent"],
    )


def _run_discovery_handoff(
    selected,
    profile,
    handoff_mode,
    handle_human_handoff,
    open_local_preview,
    run_tinyfish_application_agent,
    run_local_portal_flow=None,
):
    apply_link = _resolve_portal_url(selected)
    strategy, reason = choose_execution_strategy(selected)
    logger.info(f"[AGENT] Strategy selected: {strategy}")
    logger.info(f"[AGENT] Reason: {reason}")
    manual_payload = _build_strategy_handoff_payload(selected, strategy, reason, apply_link=apply_link)

    if strategy == "skip":
        print("Skipping execution because the selected scheme appears closed or expired.")
        handle_human_handoff(manual_payload, profile, open_browser=False)
        return

    if handoff_mode == "local":
        if strategy in {"extract_only", "manual_assist"}:
            if apply_link:
                print("Opening local preview...")
                open_local_preview(apply_link)
            handle_human_handoff(manual_payload, profile, open_browser=False)
            return
        if run_local_portal_flow and _site_config_for_scheme(selected) and run_local_portal_flow(selected):
            return
        if apply_link:
            print("Opening local preview...")
            open_local_preview(apply_link)
        handle_human_handoff(manual_payload, profile, open_browser=False)
        return

    preview_mode = handoff_mode == "hybrid"

    if preview_mode and apply_link:
        print("Opening local preview...")
        open_local_preview(apply_link)

    if strategy == "manual_assist":
        handle_human_handoff(manual_payload, profile, open_browser=False)
        return

    if TINYFISH_AVAILABLE:
        try:
            run_tinyfish_application_agent(
                selected.name,
                profile=profile,
                apply_link=apply_link,
                execution_strategy=strategy,
                open_browser=not preview_mode,
            )
        except Exception as e:
            logger.error(f"[AGENT] TinyFish application agent failed: {e}")
            print("Application agent failed. Check logs for details.")
            if preview_mode:
                handle_human_handoff(manual_payload, profile, open_browser=False)
        return

    if preview_mode:
        print("TinyFish application intelligence unavailable. Using local preview with manual continuation.")
    else:
        print("TinyFish application intelligence unavailable. Opening portal directly.")
    handle_human_handoff(manual_payload, profile, open_browser=not preview_mode)


def run_discovery(handoff_mode="agent", use_cache=True, demo_mode=False):
    """Run scheme discovery mode: scrape → match → rank → display."""
    check_dependencies(
        require_tinyfish=handoff_mode in {"agent", "hybrid"},
        require_scrapers=True,
    )
    from core.application_agent import (
        handle_human_handoff,
        open_local_preview,
        run_tinyfish_application_agent,
    )
    from core.discovery.eligibility import find_eligible_schemes
    from core.discovery.multi_source import (
        collect_source_lists,
        merge_schemes,
    )
    from core.discovery.ranking import _rule_based_rank, rank_schemes, format_ranked_output

    profile = load_profile(config.PROFILE_PATH)
    init_tracker()

    logger.info("[DISCOVERY] Starting scheme discovery...")
    source_lists = collect_source_lists(profile, use_cache=use_cache)
    schemes = merge_schemes(source_lists)

    if not schemes:
        print("Could not load schemes. Run with --no-cache to retry scrape.")
        return

    eligible = find_eligible_schemes(profile, schemes)

    if not eligible:
        print("No eligible schemes found for your profile.")
        print("Tip: Check state/category spelling in profile.json")
        return

    if demo_mode:
        print("[CONFIG] Demo mode enabled: prioritizing open, direct, lower-friction application flows.")

    if TINYFISH_AVAILABLE:
        ranked = rank_schemes(profile, eligible, demo_mode=demo_mode)
    else:
        print("Note: TinyFish ranking unavailable. Using rule-based ranking.")
        ranked = _rule_based_rank(eligible, demo_mode=demo_mode)
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
                portal_url = _resolve_portal_url(selected)
                profile_name = profile.get("full_name") or profile.get("name") or ""
                print(f"\nSelected: {selected.name}")
                print("Handing off to application agent...")
                log_application(
                    selected.name,
                    portal_url,
                    selected.source_type,
                    "handoff_completed",
                    profile_name=profile_name,
                )
                _run_discovery_handoff(
                    selected,
                    profile,
                    handoff_mode,
                    handle_human_handoff,
                    open_local_preview,
                    run_tinyfish_application_agent,
                    _run_local_portal_flow,
                )
                return
            else:
                print(f"Please enter a number between 1 and {len(ranked)}")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except EOFError:
            print("\nInput closed.")
            return
        except KeyboardInterrupt:
            print("\nCancelled.")
            return


def main():
    check_dependencies(require_browser=True)
    run_local_apply_flow()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tinywish Automation Agent")
    parser.add_argument("--discover", action="store_true",
                        help="Run scheme discovery mode")
    parser.add_argument("--apply", action="store_true",
                        help="Run application/login mode (default)")
    parser.add_argument("--history", action="store_true",
                        help="Print recent application history and exit")
    parser.add_argument(
        "--mode",
        choices=["agent", "hybrid", "local"],
        default="agent",
        help="Discovery handoff mode: agent uses TinyFish, hybrid opens a local preview first, local uses local preview only",
    )
    parser.add_argument("--no-cache", action="store_true",
                        help="Force fresh scrape (use with --discover)")
    parser.add_argument(
        "--demo-mode",
        action="store_true",
        help="Prioritize open schemes, private portals, and direct forms for a stronger live demo",
    )
    args = parser.parse_args()

    if args.history:
        init_tracker()
        print_application_history()
        sys.exit(0)

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
        run_discovery(handoff_mode=args.mode, use_cache=not args.no_cache, demo_mode=args.demo_mode)
    else:
        if args.mode != "agent":
            print("[CONFIG] --mode only affects --discover. Running local apply flow.")
        main()
