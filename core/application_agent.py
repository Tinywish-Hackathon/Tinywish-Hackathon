"""TinyFish application agent for scheme-specific application guidance."""

import json
import os
from urllib import error, request
from urllib.parse import urlparse

from utils.logger import get_logger

logger = get_logger("application_agent")

_TINYFISH_AUTOMATION_URL = "https://agent.tinyfish.ai/v1/automation/run-sse"
_DEFAULT_APPLICATION_URL = "https://example.com/"
_LOGIN_WALL_KEYWORDS = (
    "login",
    "log in",
    "sign in",
    "signin",
    "otp",
    "one time password",
    "authenticate",
    "authentication",
    "register to continue",
)


def _strip_code_fence(value):
    if not isinstance(value, str):
        return value

    cleaned = value.strip()
    if not cleaned.startswith("```"):
        return cleaned

    lines = cleaned.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    cleaned = "\n".join(lines).strip()
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    return cleaned


def _iter_sse_events(response):
    event_name = None
    data_lines = []

    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").strip()

        if not line:
            if data_lines:
                yield event_name or "message", "\n".join(data_lines)
            event_name = None
            data_lines = []
            continue

        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())

    if data_lines:
        yield event_name or "message", "\n".join(data_lines)


def _normalize_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip("- ").strip() for line in value.splitlines() if line.strip()]
    return [str(value).strip()]


def _normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "detected"}
    return bool(value)


def _safe_json_loads(value):
    if not isinstance(value, str):
        return value

    cleaned = _strip_code_fence(value)
    try:
        return json.loads(cleaned)
    except Exception:
        return value


def _extract_final_event_payload(data):
    final_keys = {"steps", "fields", "documents", "apply_link"}

    if not isinstance(data, dict):
        return None

    if any(key in data for key in final_keys):
        return data

    content = data.get("content")
    content = _safe_json_loads(content)
    if isinstance(content, dict) and any(key in content for key in final_keys):
        return content

    return None


def _canonical_event_result(data):
    if not isinstance(data, dict):
        return _safe_json_loads(data)

    content = data.get("content", data)
    return _safe_json_loads(content)


def _resolve_application_url(apply_link=None):
    candidate = str(apply_link or "").strip()
    return candidate or _DEFAULT_APPLICATION_URL


def _default_application_result(scheme_name="", apply_link=""):
    scheme_label = str(scheme_name or "the selected scheme").strip()
    resolved_link = str(apply_link or "").strip()
    return {
        "apply_link": resolved_link,
        "fields": [],
        "documents": [],
        "steps": [
            f"Open the selected application page for {scheme_label}",
            "Check whether the application form is directly accessible without login",
            "If login or OTP is required, stop there and continue authentication manually",
        ],
        "form_detected": False,
        "strategy": "EXTRACT_ONLY",
        "reason": "Default fallback — no live automation attempted.",
    }


def _url_host(url):
    try:
        return urlparse(str(url or "").strip()).netloc.lower()
    except Exception:
        return ""


def _looks_like_login_wall(result):
    result = result or {}
    parts = [
        result.get("apply_link", ""),
        *result.get("steps", []),
        *result.get("fields", []),
        *result.get("documents", []),
    ]
    combined = " ".join(str(part).strip().lower() for part in parts if part)
    return any(keyword in combined for keyword in _LOGIN_WALL_KEYWORDS)


def _should_prefer_requested_url(result, requested_url):
    if _resolve_application_url(requested_url) == _DEFAULT_APPLICATION_URL:
        return False
    requested_host = _url_host(requested_url)
    result_host = _url_host(result.get("apply_link"))
    if not requested_host or not result_host or requested_host == result_host:
        return False
    return not result.get("form_detected", False)


def open_local_preview(url):
    import webbrowser

    target_url = _resolve_application_url(url)
    logger.info(f"[AGENT] Opening local preview: {target_url}")

    try:
        webbrowser.open(target_url)
        return target_url
    except Exception as e:
        logger.warning(f"[AGENT] Could not open local preview automatically: {e}")
        return None


def _resolve_application_stream(events):
    final_payload = None
    last_non_heartbeat_data = None
    parsed_events = []

    for event_name, raw_data in events:
        parsed_data = _safe_json_loads(raw_data)

        logger.info(f"[AGENT] TinyFish event: {event_name}")

        if not parsed_data:
            continue

        if isinstance(parsed_data, dict):
            event_type = str(parsed_data.get("type") or event_name or "").strip().upper()
            logger.info(f"[AGENT] Event type: {event_type or 'UNKNOWN'}")

            if event_type == "HEARTBEAT":
                logger.info("[AGENT] Skipping heartbeat")
                continue

            last_non_heartbeat_data = parsed_data
            parsed_events.append(parsed_data)

            log_text = (
                parsed_data.get("message")
                or parsed_data.get("status")
                or parsed_data.get("step")
                or parsed_data.get("event")
            )
            if log_text:
                logger.info(f"[AGENT] {log_text}")

            if event_type in {"RESULT", "COMPLETED"}:
                final_payload = _canonical_event_result(parsed_data)
                logger.info(f"[AGENT] Result captured from event type: {event_type.lower()}")
                break

            candidate = _extract_final_event_payload(parsed_data)
            if candidate is not None:
                final_payload = candidate
                logger.info("[AGENT] Result detected via keys")
                break
            continue

        logger.info(f"[AGENT] Event type: {str(event_name).strip().upper() or 'UNKNOWN'}")
        last_non_heartbeat_data = parsed_data

        if str(event_name).strip().lower() != "message":
            continue

        parsed_events.append(parsed_data)
        candidate = _extract_final_event_payload(_safe_json_loads(parsed_data))
        if candidate is not None:
            final_payload = candidate
            logger.info("[AGENT] Result captured from event type: message")
            break

    if final_payload is None:
        logger.info(f"[AGENT] Fallback: scanning {len(parsed_events)} stored messages for result")
        for event in parsed_events:
            candidate = _extract_final_event_payload(event)
            if candidate is not None:
                final_payload = candidate
                logger.info("[AGENT] Using fallback parsed result")
                break

    if final_payload is None:
        logger.warning("No final result event found, using last non-heartbeat data")
        final_payload = last_non_heartbeat_data

    if isinstance(final_payload, str):
        final_payload = _safe_json_loads(final_payload)

    return final_payload


def _parse_application_result(result, scheme_name, apply_link=""):
    default = _default_application_result(scheme_name=scheme_name, apply_link=apply_link)

    if isinstance(result, dict):
        structured = dict(default)
        structured["apply_link"] = str(result.get("apply_link", "")).strip() or default["apply_link"]
        structured["fields"] = _normalize_list(result.get("fields", []))
        structured["documents"] = _normalize_list(result.get("documents", []))
        structured["steps"] = _normalize_list(result.get("steps", []))
        structured["form_detected"] = _normalize_bool(result.get("form_detected", False))
        return structured

    def _materialize(value):
        if value is None:
            return None
        if hasattr(value, "data") and value.data:
            return value.data
        if hasattr(value, "output") and value.output:
            return value.output
        if hasattr(value, "result") and value.result:
            return value.result
        return value

    def _walk(value):
        value = _materialize(value)
        if value is None:
            return None

        if isinstance(value, str):
            cleaned = _strip_code_fence(value)
            try:
                return _walk(json.loads(cleaned))
            except json.JSONDecodeError:
                return None

        if isinstance(value, dict):
            for key in ("data", "output", "result", "content", "payload"):
                if key in value:
                    nested = _walk(value[key])
                    if nested:
                        return nested

            apply_link = (
                value.get("apply_link")
                or value.get("applyUrl")
                or value.get("apply_url")
                or value.get("link")
                or value.get("url")
                or ""
            )
            fields = value.get("fields") or value.get("form_fields") or value.get("required_fields") or []
            documents = (
                value.get("documents")
                or value.get("required_documents")
                or value.get("requiredDocuments")
                or []
            )
            steps = (
                value.get("steps")
                or value.get("application_steps")
                or value.get("applicationSteps")
                or []
            )
            form_detected = (
                value.get("form_detected")
                or value.get("formDetected")
                or value.get("has_form")
                or False
            )

            structured = dict(default)
            structured["apply_link"] = str(apply_link).strip()
            structured["fields"] = _normalize_list(fields)
            structured["documents"] = _normalize_list(documents)
            structured["steps"] = _normalize_list(steps)
            structured["form_detected"] = _normalize_bool(form_detected)
            return structured

        return None

    parsed = _walk(result)
    return parsed or default


def _finalize_application_result(result, scheme_name, requested_url=""):
    structured = _parse_application_result(result, scheme_name, apply_link=requested_url)
    if not structured.get("apply_link"):
        structured["apply_link"] = str(requested_url or "").strip()

    if _should_prefer_requested_url(structured, requested_url):
        logger.info("[AGENT] Keeping requested portal instead of auth-blocked external redirect")
        structured["apply_link"] = str(requested_url or "").strip()

    if _looks_like_login_wall(structured):
        structured["form_detected"] = False
        structured["strategy"] = "EXTRACT_ONLY"
        structured["reason"] = "Login/OTP wall detected during execution."
        logger.info("[AGENT] Login wall detected → switching to PRE-APPLICATION INTELLIGENCE MODE")
        print("\n[AGENT] Login wall detected → switching to PRE-APPLICATION INTELLIGENCE MODE")
        steps = _normalize_list(structured.get("steps", []))
        stop_step = "Stop here and complete login or OTP manually before continuing."
        if stop_step not in steps:
            steps.append(stop_step)
        structured["steps"] = steps
    else:
        if "strategy" not in structured:
            structured["strategy"] = "FULL_APPLY" if structured.get("form_detected") else "EXTRACT_ONLY"
        if "reason" not in structured:
            structured["reason"] = (
                "Direct form detected — full application possible."
                if structured.get("form_detected")
                else "No direct form detected — extraction mode."
            )

    return structured


def handle_human_handoff(result, profile, open_browser=True):
    import webbrowser

    safe_result = result or {}
    safe_profile = profile or {}
    strategy = safe_result.get("strategy", "")
    reason = safe_result.get("reason", "")

    if strategy == "SKIP":
        mode = "Scheme Skipped"
    elif strategy == "FULL_APPLY" and safe_result.get("form_detected", False):
        mode = "Auto-Fill Ready Mode"
    elif strategy == "EXTRACT_ONLY":
        mode = "Pre-Application Intelligence Mode"
    elif safe_result.get("form_detected", False):
        mode = "Auto-Fill Ready Mode"
    else:
        mode = "Pre-Application Intelligence Mode"

    print(f"\n[MODE] {mode}")
    if strategy:
        print(f"[AGENT] Strategy: {strategy}")
    if reason:
        print(f"[AGENT] Reason: {reason}")
    print("\n==============================")
    print("\U0001f680 APPLICATION READY")
    print("==============================")

    apply_link = str(safe_result.get("apply_link", "")).strip()
    if apply_link:
        if open_browser:
            print(f"\nOpening application portal: {apply_link}")
            logger.info("[AGENT] Opening portal for manual continuation")
            try:
                webbrowser.open(apply_link)
            except Exception as e:
                logger.warning(f"[AGENT] Could not open browser automatically: {e}")
        else:
            print(f"\nApplication portal ready: {apply_link}")
            logger.info("[AGENT] Browser launch skipped for manual continuation")
    else:
        print("\n\u26a0 No direct apply link found. Open manually.")

    if strategy == "SKIP":
        print("\u26a0 This scheme was skipped. See reason above.")
        print("\n==============================")
        return

    if not safe_result.get("form_detected", False):
        print("\u26a0 Form not directly accessible (login required). Showing preparation mode.")

    print("\n------------------------------")
    print("\U0001f9e0 AUTO-FILL GUIDE")
    print("------------------------------")

    preferred_keys = [
        ("full_name", "Name"),
        ("state", "State"),
        ("category", "Category"),
        ("annual_income", "Income"),
        ("course_level", "Course level"),
        ("email", "Email"),
        ("phone", "Phone"),
    ]
    shown_keys = set()

    for key, label in preferred_keys:
        value = safe_profile.get(key)
        if value in (None, "", {}):
            continue
        print(f"{label} \u2192 {value}")
        shown_keys.add(key)

    for key, value in safe_profile.items():
        if key in shown_keys or isinstance(value, (dict, list)):
            continue
        if value in (None, ""):
            continue
        print(f"{key.capitalize()} \u2192 {value}")

    fields = safe_result.get("fields", []) or []
    if fields:
        print("\n------------------------------")
        print("\U0001f9fe FORM FIELDS")
        print("------------------------------")
        for field in fields:
            print(f"- {field}")

    print("\n------------------------------")
    print("\U0001f4c4 REQUIRED DOCUMENTS")
    print("------------------------------")

    documents = safe_result.get("documents", []) or []
    if documents:
        for doc in documents:
            print(f"- {doc}")
    else:
        print("- No document list extracted")

    print("\n------------------------------")
    print("\U0001f4cb APPLICATION STEPS")
    print("------------------------------")

    steps = safe_result.get("steps", []) or []
    if steps:
        for i, step in enumerate(steps, 1):
            print(f"{i}. {step}")
    else:
        print("1. Open the official scholarship portal")
        print("2. Complete login or OTP manually")
        print("3. Review the form and fill fields using the guide above")

    print("\n==============================")
    print("\u26a0 NOTE: Login/OTP must be completed manually.")
    print("==============================")


def _build_goal(scheme_name, profile=None, base_url=None, execution_strategy="full_apply"):
    profile = profile or {}
    target_url = _resolve_application_url(base_url)
    name = profile.get("full_name") or profile.get("name")
    state = profile.get("state")
    category = profile.get("category")
    income = profile.get("annual_income") or profile.get("income")

    if not name:
        logger.warning("[GOAL] Profile is missing 'full_name'; applicant context will be incomplete.")
        name = "Applicant"
    if not state:
        logger.warning("[GOAL] Profile is missing 'state'; eligibility context will be incomplete.")
        state = "Unknown"
    if not category:
        logger.warning("[GOAL] Profile is missing 'category'; eligibility context will be incomplete.")
        category = "General"
    if not income:
        logger.warning("[GOAL] Profile is missing 'annual_income'; income filter context will be skipped.")
        income = 0

    if execution_strategy == "extract_only":
        strategy_block = (
            "Execution strategy:\n"
            "- Extract requirements only\n"
            "- Do not attempt a full application flow\n"
            "- Stop immediately when login, registration, or OTP is required\n\n"
        )
    elif execution_strategy == "manual_assist":
        strategy_block = (
            "Execution strategy:\n"
            "- Gather high-value visible guidance only\n"
            "- Do not chase deep redirects or authenticated flows\n\n"
        )
    else:
        strategy_block = (
            "Execution strategy:\n"
            "- Prefer full pre-auth application progress when direct form interaction is possible\n\n"
        )

    return (
        "You are an autonomous web agent helping a student prepare for a scholarship application.\n\n"
        f"Target scholarship: {scheme_name}\n\n"
        f"Start URL: {target_url}\n\n"
        "Student profile:\n"
        f"- Name: {name}\n"
        f"- State: {state}\n"
        f"- Category: {category}\n"
        f"- Income: {income}\n\n"
        f"{strategy_block}"
        "Goal:\n"
        "Complete as much of the application workflow as possible.\n\n"
        "Priorities:\n"
        "1. Direct form interaction\n"
        "2. Extract fields and required documents\n"
        "3. Avoid dead ends such as closed pages and login walls\n\n"
        "Rules:\n"
        "- Do NOT blindly follow links to external portals\n"
        "- Prefer staying on the same domain\n"
        "- If login is required, extract visible information and stop\n\n"
        "Instructions:\n"
        f"1. Start from {target_url} and prefer to stay on this site or portal when possible\n"
        "2. Prefer workflows where the application form is directly accessible without login\n"
        "3. Avoid redirecting to a different external portal or domain unless the current page clearly states that the real application must continue there\n"
        "4. Follow visible scheme-specific actions such as Apply, View Details, Register, or Continue only when they help reach a direct pre-auth application page\n"
        "5. Detect whether a form is visible, enumerate its fields, and inspect form structure before authentication walls when possible\n"
        "6. If a visible pre-auth form exists, interact only with safe, non-destructive fields to confirm the workflow\n"
        "7. If login, sign-in, registration, or OTP is required:\n"
        "   - Stop before the authenticated flow\n"
        "   - Extract visible form fields if any\n"
        "   - Extract required documents\n"
        "   - Extract the pre-auth application steps\n"
        "   - Return the most useful pre-auth URL instead of a dead-end login redirect\n"
        "8. Do NOT attempt to bypass authentication\n\n"
        "Output requirements:\n"
        "- Identify the best apply link that is useful before authentication\n"
        "- Identify required form fields\n"
        "- Identify required documents\n"
        "- Identify application steps\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "apply_link": "",\n'
        '  "fields": [],\n'
        '  "documents": [],\n'
        '  "steps": [],\n'
        '  "form_detected": boolean\n'
        "}"
    )


def run_tinyfish_application_agent(
    scheme_name,
    profile=None,
    api_key=None,
    apply_link=None,
    execution_strategy="full_apply",
    open_browser=True,
):
    """Run TinyFish automation for a selected scholarship scheme."""
    resolved_api_key = api_key or os.getenv("TINYFISH_API_KEY")
    target_url = _resolve_application_url(apply_link)
    fallback_result = _default_application_result(scheme_name=scheme_name, apply_link=apply_link)

    if not resolved_api_key:
        logger.warning("[AGENT] Missing TINYFISH_API_KEY, using manual handoff contract")
        handle_human_handoff(fallback_result, profile or {}, open_browser=open_browser)
        return fallback_result

    try:
        from core.integrations.tinyfish_client import (
            discover_tinyfish_run_method,
            get_tinyfish_client,
        )
    except Exception as e:
        logger.warning(f"[AGENT] TinyFish client unavailable, using manual handoff contract: {e}")
        handle_human_handoff(fallback_result, profile or {}, open_browser=open_browser)
        return fallback_result

    try:
        sdk_client = get_tinyfish_client()
        discover_tinyfish_run_method(
            sdk_client,
            logger,
            "[AGENT]",
            warn_on_missing=False,
        )
    except Exception as e:
        logger.info(f"[AGENT] TinyFish SDK method discovery skipped: {e}")

    payload = {
        "url": target_url,
        "goal": _build_goal(
            scheme_name,
            profile=profile,
            base_url=target_url,
            execution_strategy=execution_strategy,
        ),
    }

    request_body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        _TINYFISH_AUTOMATION_URL,
        data=request_body,
        headers={
            "X-API-Key": resolved_api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=180) as response:
            final_payload = _resolve_application_stream(_iter_sse_events(response))
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error(f"[AGENT] TinyFish HTTP error {e.code}: {body}")
        handle_human_handoff(fallback_result, profile or {}, open_browser=open_browser)
        return fallback_result
    except error.URLError as e:
        logger.error(f"[AGENT] TinyFish network error: {e}")
        handle_human_handoff(fallback_result, profile or {}, open_browser=open_browser)
        return fallback_result
    except Exception as e:
        logger.error(f"[AGENT] TinyFish request failed: {e}")
        handle_human_handoff(fallback_result, profile or {}, open_browser=open_browser)
        return fallback_result

    logger.info(f"[AGENT] FINAL STRUCTURED DATA: {final_payload}")
    parsed_result = _finalize_application_result(final_payload, scheme_name, requested_url=target_url)

    # Ensure strategy/reason are always present
    if "strategy" not in parsed_result:
        parsed_result["strategy"] = "FULL_APPLY" if parsed_result.get("form_detected") else "EXTRACT_ONLY"
    if "reason" not in parsed_result:
        parsed_result["reason"] = (
            "Direct form detected — full application possible."
            if parsed_result.get("form_detected")
            else "No direct form detected — extraction mode."
        )

    strategy = parsed_result.get("strategy", "EXTRACT_ONLY")
    logger.info(f"[AGENT] Strategy: {strategy}")
    print(f"\n[AGENT] Strategy: {strategy}")
    if strategy == "EXTRACT_ONLY":
        reason = parsed_result.get("reason", "")
        if reason:
            print(f"[AGENT] Reason: {reason}")

    handle_human_handoff(parsed_result, profile or {}, open_browser=open_browser)
    return parsed_result
