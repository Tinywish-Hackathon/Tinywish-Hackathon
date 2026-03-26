from executor.actions import (
    safe_click_in_section, safe_click_fuzzy, find_by_text_fuzzy, safe_click,
    fill_form as execute_fill_form, reset_click_history
)
from executor.form_handler import handle_login_form
from executor.intent import global_intent_scan, should_skip_step
from extractor.dom import detect_iframes, log_page_elements
from extractor.field_extractor import extract_input_fields
from mapper.field_mapper import map_profile_to_fields
from utils.helpers import load_and_validate_profile, load_profile
from utils.logger import get_logger
import config

logger = get_logger("flow_engine")

# Cache profile and state across flow steps
_cached_profile = None
_flow_state = {}


def run_flow(page, flow_steps, flow_intent="apply"):
    """Execute a list of flow steps with intent-driven short-circuiting.

    Before executing rigid navigation steps, performs a global intent scan
    to detect if a direct high-priority action (e.g., "Apply Now") is
    available on the current page. If found, intermediate steps are skipped.

    Each step is a dict with:
        - action: "click" | "click_fuzzy" | "detect" | "wait" | "fill_form"
        - section: list of section candidate texts (for "click")
        - target: list of target candidate texts (for "click")
        - candidates: list of candidate texts (for "click_fuzzy")
        - label: human-readable step label (optional)
        - max_scroll: scroll attempts (optional, default 10)
        - wait_after: ms to wait after step (optional, default 2000)
        - skip_intent: if True, skip intent scan for this step (optional)

    Args:
        page: Playwright page object.
        flow_steps: List of step dicts.
        flow_intent: The broad goal ("apply", "register", etc.)

    Returns:
        Dict with results: {"completed": int, "failed": int, "skipped": int, "total": int}
    """
    global _cached_profile, _flow_state

    completed = 0
    failed = 0
    skipped = 0
    total = len(flow_steps)

    # Reset click history and state for fresh flow
    reset_click_history()
    _flow_state = {}

    # Load profile once for the entire flow
    if _cached_profile is None:
        try:
            _cached_profile = load_profile(config.PROFILE_PATH)
        except Exception as e:
            logger.warning(f"Could not load profile: {e}")
            _cached_profile = {}

    logger.info(f"Starting flow with {total} step(s), intent='{flow_intent}'")

    # --- Phase 0: Global intent scan BEFORE any steps ---
    intent_result = global_intent_scan(page, intent=flow_intent)

    if intent_result["found"]:
        logger.info(
            f"[INTENT] Short-circuit active: "
            f"matched '{intent_result['matched_text']}' (priority={intent_result['priority']})"
        )
        page.wait_for_timeout(3000)  # Let the page settle after direct action

        # Check if intent action landed on a login page
        handle_login_form(page, _cached_profile, _flow_state)

    for i, step in enumerate(flow_steps):
        step_num = i + 1
        action = step.get("action", "click")
        label = step.get("label", f"Step {step_num}")
        max_scroll = step.get("max_scroll", 10)
        wait_after = step.get("wait_after", 2000)
        skip_intent_check = step.get("skip_intent", False)

        # --- Intent-based skip check ---
        if should_skip_step(step, intent_result):
            skipped += 1
            logger.info(
                f"Step {step_num}/{total}: '{label}' SKIPPED "
                f"(direct action already taken: '{intent_result['matched_text']}')"
            )
            continue

        logger.info(f"--- Step {step_num}/{total}: {label} (action={action}) ---")

        # --- Mid-flow intent re-scan for click steps ---
        if (not skip_intent_check
                and not intent_result["found"]
                and action in ("click", "click_fuzzy")):
            mid_scan = global_intent_scan(page, intent=flow_intent)
            if mid_scan["found"]:
                intent_result = mid_scan
                logger.info(
                    f"[INTENT] Mid-flow shortcut: '{mid_scan['matched_text']}' "
                    f"found at step {step_num}"
                )
                completed += 1
                page.wait_for_timeout(2000)

                # Check if mid-flow action landed on a login page
                handle_login_form(page, _cached_profile, _flow_state)
                continue

        success = False

        try:
            if action == "click":
                section = step.get("section", [])
                target = step.get("target", [])

                if section and target:
                    success = safe_click_in_section(
                        page,
                        section_candidates=section,
                        target_candidates=target,
                        label=label,
                        max_scroll=max_scroll
                    )
                elif section:
                    el, matched = find_by_text_fuzzy(page, section)
                    if el:
                        success = safe_click(page, el, label=label)
                else:
                    logger.warning(f"Step {step_num}: no section or target defined")

            elif action == "click_fuzzy":
                candidates = step.get("candidates", [])
                if candidates:
                    success = safe_click_fuzzy(
                        page, candidates, label=label, max_scroll=max_scroll
                    )

            elif action == "detect":
                detect_iframes(page)
                log_page_elements(page)
                success = True

            elif action == "wait":
                message = step.get("message", "Manual action required")
                logger.warning(f"PAUSED: {message}")
                input(f"\n[MANUAL STEP] {message} -> Press Enter...")
                success = True

            elif action == "fill_form":
                logger.info("Extracting form fields...")
                fields = extract_input_fields(page)

                if not fields:
                    logger.warning("No form fields found on page")
                else:
                    if _cached_profile is None:
                        profile_path = step.get("profile_path", config.PROFILE_PATH)
                        logger.info("Loading and validating profile...")
                        _cached_profile = load_and_validate_profile(profile_path)

                    logger.info("Mapping profile to form fields...")
                    mapped = map_profile_to_fields(_cached_profile, fields)

                    if not mapped:
                        logger.warning("No fields could be mapped to profile")
                    else:
                        logger.info("Filling form...")
                        fill_result = execute_fill_form(page, mapped)
                        logger.info(
                            f"Fill result: {fill_result['filled']} filled, "
                            f"{fill_result['skipped']} skipped, "
                            f"{fill_result['failed']} failed"
                        )
                        success = fill_result["filled"] > 0

            elif action == "login_check":
                login_result = handle_login_form(page, _cached_profile, _flow_state)
                success = login_result is not None

            else:
                logger.warning(f"Unknown action '{action}' in step {step_num}")

        except Exception as e:
            logger.error(f"Step {step_num} ({label}) raised exception: {e}")

        if success:
            completed += 1
            logger.info(f"Step {step_num}/{total} completed")

            # After successful navigation, check for login forms
            if action in ("click", "click_fuzzy"):
                handle_login_form(page, _cached_profile, _flow_state)
        else:
            failed += 1
            logger.warning(f"Step {step_num}/{total} failed")

        page.wait_for_timeout(wait_after)

    results = {"completed": completed, "failed": failed, "skipped": skipped, "total": total}
    logger.info(
        f"Flow finished: {completed}/{total} completed, "
        f"{skipped} skipped, {failed} failed"
    )
    return results
