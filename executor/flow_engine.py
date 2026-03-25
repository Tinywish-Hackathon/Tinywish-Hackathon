from executor.actions import (
    safe_click_in_section, safe_click_fuzzy, find_by_text_fuzzy, safe_click,
    fill_form as execute_fill_form
)
from extractor.dom import detect_iframes, log_page_elements
from extractor.field_extractor import extract_input_fields
from mapper.field_mapper import map_profile_to_fields
from utils.helpers import load_and_validate_profile
from utils.logger import get_logger
import config

logger = get_logger("flow_engine")

# Cache profile across flow steps
_cached_profile = None


def run_flow(page, flow_steps):
    """Execute a list of flow steps on the given page.

    Each step is a dict with:
        - action: "click" | "click_fuzzy" | "detect" | "wait"
        - section: list of section candidate texts (for "click")
        - target: list of target candidate texts (for "click")
        - candidates: list of candidate texts (for "click_fuzzy")
        - label: human-readable step label (optional)
        - max_scroll: scroll attempts (optional, default 10)
        - wait_after: ms to wait after step (optional, default 2000)

    Args:
        page: Playwright page object.
        flow_steps: List of step dicts.

    Returns:
        Dict with results: {"completed": int, "failed": int, "total": int}
    """
    completed = 0
    failed = 0
    total = len(flow_steps)

    logger.info(f"Starting flow with {total} step(s)")

    for i, step in enumerate(flow_steps):
        step_num = i + 1
        action = step.get("action", "click")
        label = step.get("label", f"Step {step_num}")
        max_scroll = step.get("max_scroll", 10)
        wait_after = step.get("wait_after", 2000)

        logger.info(f"━━━ Step {step_num}/{total}: {label} (action={action}) ━━━")

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
                    # No target → just find and click the section element
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
                input(f"\n[MANUAL STEP] {message} → Press Enter...")
                success = True

            elif action == "fill_form":
                global _cached_profile

                # 1. Extract fields
                logger.info("Extracting form fields...")
                fields = extract_input_fields(page)

                if not fields:
                    logger.warning("No form fields found on page")
                else:
                    # 2. Load profile (cached)
                    if _cached_profile is None:
                        profile_path = step.get("profile_path", config.PROFILE_PATH)
                        logger.info("Loading and validating profile...")
                        _cached_profile = load_and_validate_profile(profile_path)

                    # 3. Map fields
                    logger.info("Mapping profile to form fields...")
                    mapped = map_profile_to_fields(_cached_profile, fields)

                    if not mapped:
                        logger.warning("No fields could be mapped to profile")
                    else:
                        # 4. Fill form
                        logger.info("Filling form...")
                        fill_result = execute_fill_form(page, mapped)
                        logger.info(
                            f"Fill result: {fill_result['filled']} filled, "
                            f"{fill_result['skipped']} skipped, "
                            f"{fill_result['failed']} failed"
                        )
                        success = fill_result["filled"] > 0

            else:
                logger.warning(f"Unknown action '{action}' in step {step_num}")

        except Exception as e:
            logger.error(f"Step {step_num} ({label}) raised exception: {e}")

        if success:
            completed += 1
            logger.info(f"Step {step_num}/{total} completed ✔")
        else:
            failed += 1
            logger.warning(f"Step {step_num}/{total} failed ✘")

        # Wait between steps for page to settle
        page.wait_for_timeout(wait_after)

    results = {"completed": completed, "failed": failed, "total": total}
    logger.info(
        f"Flow finished: {completed}/{total} completed, {failed} failed"
    )
    return results
