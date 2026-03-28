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


def _build_goal(scheme_name, profile=None):
    profile = profile or {}
    name = profile.get("full_name") or profile.get("name") or "Atharv"
    state = profile.get("state") or "J&K"
    category = profile.get("category") or "OBC"
    income = profile.get("annual_income") or profile.get("income") or 250000

    return (
        "You are an autonomous web agent helping a student apply for a scholarship.\n\n"
        f"Target scholarship: {scheme_name}\n\n"
        "Student profile for fill simulation:\n"
        f"- Name: {name}\n"
        f"- State: {state}\n"
        f"- Category: {category}\n"
        f"- Income: {income}\n\n"
        "Goal:\n"
        "Navigate to the official application page and extract:\n"
        "1. Direct apply link\n"
        "2. Form fields required (name, aadhaar, income, etc.)\n"
        "3. Required documents\n"
        "4. Application steps\n\n"
        "Instructions:\n"
        "- Prioritize official government websites (scholarships.gov.in)\n"
        "- Avoid blogs unless necessary\n"
        "- If login is required, still extract form structure if visible\n"
        "- Try to reach the application form and identify fields\n"
        "- If the form is visible, simulate filling it with the student profile but do not submit\n"
        "- Handle redirects, login pages, and dynamic UI\n\n"
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

    try:
        with request.urlopen(req, timeout=180) as response:
            for event_name, raw_data in _iter_sse_events(response):
                parsed_data = raw_data
                try:
                    parsed_data = json.loads(raw_data)
                except Exception:
                    pass

                last_parsed_data = parsed_data

                logger.info(f"[APPLICATION] TinyFish event: {event_name}")
                logger.info(f"[APPLICATION] Event type: {event_name}")

                if isinstance(parsed_data, dict):
                    log_text = (
                        parsed_data.get("message")
                        or parsed_data.get("status")
                        or parsed_data.get("step")
                        or parsed_data.get("event")
                    )
                    if log_text:
                        logger.info(f"[APPLICATION] {log_text}")

                if event_name in ["completed", "result"]:
                    final_payload = parsed_data
                elif event_name == "message":
                    pass

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
    return _parse_application_result(final_payload, scheme_name)
