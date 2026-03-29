"""TinyFish application agent for scheme-specific application guidance."""

import json
import os
from urllib import error, request

from utils.logger import get_logger

logger = get_logger("application_agent")

_TINYFISH_AUTOMATION_URL = "https://agent.tinyfish.ai/v1/automation/run-sse"


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


def _parse_application_result(result, scheme_name):
    default = {
        "apply_link": "",
        "fields": [],
        "documents": [],
        "steps": [],
        "form_detected": False,
    }

    if isinstance(result, dict):
        return {
            "apply_link": result.get("apply_link", ""),
            "fields": _normalize_list(result.get("fields", [])),
            "documents": _normalize_list(result.get("documents", [])),
            "steps": _normalize_list(result.get("steps", [])),
            "form_detected": _normalize_bool(result.get("form_detected", False)),
        }

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


def handle_human_handoff(result, profile):
    import webbrowser

    safe_result = result or {}
    safe_profile = profile or {}
    mode = (
        "Auto-Fill Ready Mode"
        if safe_result.get("form_detected", False)
        else "Pre-Application Intelligence Mode"
    )

    print(f"\n[MODE] {mode}")
    print("\n==============================")
    print("🚀 APPLICATION READY")
    print("==============================")

    apply_link = str(safe_result.get("apply_link", "")).strip()
    if apply_link:
        print(f"\nOpening application portal: {apply_link}")
        logger.info("[APPLICATION] Opening portal for manual continuation")
        try:
            webbrowser.open(apply_link)
        except Exception as e:
            logger.warning(f"[APPLICATION] Could not open browser automatically: {e}")
    else:
        print("\n⚠ No direct apply link found. Open manually.")

    if not safe_result.get("form_detected", False):
        print("⚠ Form not directly accessible (login required). Showing preparation mode.")

    print("\n------------------------------")
    print("🧠 AUTO-FILL GUIDE")
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
        print(f"{label} → {value}")
        shown_keys.add(key)

    for key, value in safe_profile.items():
        if key in shown_keys or isinstance(value, (dict, list)):
            continue
        if value in (None, ""):
            continue
        print(f"{key.capitalize()} → {value}")

    fields = safe_result.get("fields", []) or []
    if fields:
        print("\n------------------------------")
        print("🧾 FORM FIELDS")
        print("------------------------------")
        for field in fields:
            print(f"- {field}")

    print("\n------------------------------")
    print("📄 REQUIRED DOCUMENTS")
    print("------------------------------")

    documents = safe_result.get("documents", []) or []
    if documents:
        for doc in documents:
            print(f"- {doc}")
    else:
        print("- No document list extracted")

    print("\n------------------------------")
    print("📋 APPLICATION STEPS")
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
    print("⚠ NOTE: Login/OTP must be completed manually.")
    print("==============================")


def _build_goal(scheme_name, profile=None):
    profile = profile or {}
    name = profile.get("full_name") or profile.get("name") or "Atharv"
    state = profile.get("state") or "J&K"
    category = profile.get("category") or "OBC"
    income = profile.get("annual_income") or profile.get("income") or 250000

    return (
        "You are an autonomous web agent helping a student prepare for a scholarship application.\n\n"
        f"Target scholarship: {scheme_name}\n\n"
        "Student profile:\n"
        f"- Name: {name}\n"
        f"- State: {state}\n"
        f"- Category: {category}\n"
        f"- Income: {income}\n\n"
        "Instructions:\n"
        "1. Try to access official application page\n"
        "2. If blocked or login required:\n"
        "   - Extract full workflow\n"
        "   - Identify required documents\n"
        "   - Identify required form fields\n"
        "3. Prefer official sources but allow trusted private sources if needed\n"
        "4. Avoid getting stuck on login pages\n"
        "5. Do NOT attempt to bypass authentication\n\n"
        "Goal:\n"
        "- Find the most reliable way to apply and prepare the user\n"
        "- Identify the direct apply link if available\n"
        "- Identify form fields required (name, aadhaar, income, etc.)\n"
        "- Identify required documents\n"
        "- Identify application steps\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "apply_link": "...",\n'
        '  "fields": ["..."],\n'
        '  "documents": [],\n'
        '  "steps": [],\n'
        '  "form_detected": false\n'
        "}"
    )


def run_tinyfish_application_agent(scheme_name, profile=None, api_key=None):
    """Run TinyFish automation for a selected scholarship scheme."""
    resolved_api_key = api_key or os.getenv("TINYFISH_API_KEY")
    if not resolved_api_key:
        raise ValueError("Missing TINYFISH_API_KEY")

    payload = {
        "url": "https://scholarships.gov.in/",
        "goal": _build_goal(scheme_name, profile=profile),
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

    final_payload = None
    last_parsed_data = None
    parsed_events = []

    try:
        with request.urlopen(req, timeout=180) as response:
            for event_name, raw_data in _iter_sse_events(response):
                parsed_data = _safe_json_loads(raw_data)

                last_parsed_data = parsed_data

                logger.info(f"[APPLICATION] TinyFish event: {event_name}")
                logger.info(f"[APPLICATION] Event type: {event_name}")

                if isinstance(parsed_data, dict):
                    event_type = str(parsed_data.get("type", "")).strip().upper()
                    if event_type == "HEARTBEAT":
                        logger.info("[APPLICATION] Skipping heartbeat")
                        continue

                    log_text = (
                        parsed_data.get("message")
                        or parsed_data.get("status")
                        or parsed_data.get("step")
                        or parsed_data.get("event")
                    )
                    if log_text:
                        logger.info(f"[APPLICATION] {log_text}")

                    parsed_events.append(parsed_data)

                    if event_type == "RESULT":
                        final_payload = _safe_json_loads(parsed_data.get("content", parsed_data))
                        logger.info("[APPLICATION] Result captured")
                        break

                    candidate = _extract_final_event_payload(parsed_data)
                    if candidate is not None:
                        final_payload = candidate
                        logger.info("[APPLICATION] Result captured")
                        break
                elif str(event_name).strip().lower() == "message":
                    parsed_events.append(parsed_data)

            if not final_payload:
                for event in reversed(parsed_events):
                    candidate = _extract_final_event_payload(event)
                    if candidate is not None:
                        final_payload = candidate
                        logger.info("[APPLICATION] Using fallback parsed result")
                        break

            if not final_payload:
                logger.warning("No final result event found, using last parsed data")
                final_payload = last_parsed_data
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error(f"[APPLICATION] TinyFish HTTP error {e.code}: {body}")
        raise
    except error.URLError as e:
        logger.error(f"[APPLICATION] TinyFish network error: {e}")
        raise

    logger.info(f"[APPLICATION] FINAL STRUCTURED DATA: {final_payload}")
    parsed_result = _parse_application_result(final_payload, scheme_name)
    handle_human_handoff(parsed_result, profile or {})
    return parsed_result
