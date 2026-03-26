"""Login form handler — detection, auto-fill, two-phase CTA, OTP HITL, CAPTCHA pause.

Orchestrates the full login flow:
  1. Detect login/OTP page (URL + body text heuristics)
  2. Extract and classify input fields
  3. Auto-fill safe fields (Aadhaar, email, phone, name)
  4. CTA Phase 1: click "Get OTP" / "Send OTP"
  5. OTP HITL: prompt user, fill OTP field
  6. CTA Phase 2: click "Login" / "Verify" / "Proceed"
  7. CAPTCHA HITL: pause for manual solve
  8. Domain-scoped state prevents re-triggering

Safety:
  - Never fills OTP, CAPTCHA, or password automatically
  - Never overwrites existing field values
  - Masks Aadhaar in logs (XXXX-XXXX-1234)
"""

import os
from urllib.parse import urlparse
from executor.actions import safe_click_fuzzy
from extractor.field_extractor import extract_input_fields
from utils.logger import get_logger

logger = get_logger("form_handler")

# --- URL keywords that suggest a login/auth page ---
LOGIN_URL_KEYWORDS = ["login", "signin", "auth", "register", "otp"]

# --- Body text keywords (require BOTH input fields AND text match) ---
LOGIN_TEXT_KEYWORDS = [
    "aadhaar", "aadhar", "otp", "captcha",
    "sign in", "login", "log in", "enter your",
]

# --- Field classification keywords ---
FIELD_CLASSIFY = {
    "aadhaar":  ["aadhaar", "aadhar", "aadhaar number", "uid", "uidai"],
    "email":    ["email", "e-mail", "email id", "mail"],
    "phone":    ["phone", "mobile", "contact", "mobile number", "telephone"],
    "name":     ["name", "full name", "applicant name", "student name"],
    "password": ["password", "pass", "pwd"],
    "otp":      ["otp", "one time password", "verification code", "enter otp"],
    "captcha":  ["captcha", "security code", "verify image", "type the text"],
}

# Fields that must NEVER be auto-filled
NEVER_FILL = {"otp", "captcha", "password"}

# CTA candidates for each phase
CTA_PHASE1 = ["get otp", "send otp", "request otp", "continue"]
CTA_PHASE2 = ["login", "verify", "proceed", "submit", "continue", "sign in"]


def _mask_aadhaar(value):
    """Mask Aadhaar number for safe logging: 123456789012 → XXXX-XXXX-9012."""
    if not value or len(value) < 4:
        return "****"
    return f"XXXX-XXXX-{value[-4:]}"


def _get_domain(page):
    """Build a scoped key from domain + first path segment.

    Examples:
        https://nsp.gov.in/login       → nsp.gov.in/login
        https://nsp.gov.in/otp-verify  → nsp.gov.in/otp-verify
        https://example.com/           → example.com/
    """
    try:
        parsed = urlparse(page.url)
        first_segment = parsed.path.strip("/").split("/")[0] if parsed.path.strip("/") else ""
        return f"{parsed.netloc}/{first_segment}"
    except Exception:
        return "unknown"


def _build_context(field_info):
    """Build a lowercase context string from all field metadata."""
    parts = [
        field_info.get("label", ""),
        field_info.get("placeholder", ""),
        field_info.get("name", ""),
    ]
    return " ".join(p.lower().strip() for p in parts if p).strip()


def _classify_field(context):
    """Classify a field by its context string into a known category.

    Returns:
        Tuple of (category, confidence_keyword) or ("unknown", None).
    """
    if not context:
        return "unknown", None

    for category, keywords in FIELD_CLASSIFY.items():
        for kw in keywords:
            if kw in context:
                return category, kw

    return "unknown", None


# ─────────────────────────────────────────────────
# 1. FORM DETECTION
# ─────────────────────────────────────────────────

def detect_login_form(page):
    """Detect if the current page is a login/OTP form page.

    Returns True only if:
      A) URL contains a login-related keyword, OR
      B) Page has input fields AND body text contains a login keyword.

    This two-pronged check prevents false positives on informational pages.
    """
    url = page.url.lower()

    # Check A: URL keywords
    for kw in LOGIN_URL_KEYWORDS:
        if kw in url:
            logger.info(f"[FORM] Login form detected via URL keyword: '{kw}'")
            return True

    # Check B: input fields + body text
    try:
        input_count = page.locator("input:not([type='hidden'])").count()
        if input_count == 0:
            return False

        body_text = page.locator("body").inner_text().lower()
        for kw in LOGIN_TEXT_KEYWORDS:
            if kw in body_text:
                logger.info(
                    f"[FORM] Login form detected via body text: '{kw}' "
                    f"({input_count} input field(s))"
                )
                return True
    except Exception as e:
        logger.debug(f"[FORM] Detection error: {e}")

    return False


# ─────────────────────────────────────────────────
# 2. FIELD CLASSIFICATION + FILL
# ─────────────────────────────────────────────────

def classify_and_fill_fields(page, profile):
    """Extract, classify, and fill safe form fields.

    Returns:
        Dict with:
            - filled: list of filled field labels
            - skipped: list of skipped field labels
            - otp_detected: bool
            - captcha_detected: bool
            - otp_selector: str or None (CSS selector for OTP field)
    """
    fields = extract_input_fields(page)

    if not fields:
        logger.info("[FORM] No input fields found on page")
        return {
            "filled": [], "skipped": [], "otp_detected": False,
            "captcha_detected": False, "otp_selector": None,
        }

    # Build profile value lookup
    aadhaar_value = os.getenv("AADHAAR_NUMBER", "")
    value_map = {
        "aadhaar": aadhaar_value,
        "email":   profile.get("email", ""),
        "phone":   profile.get("phone", ""),
        "name":    profile.get("full_name", ""),
    }

    filled = []
    skipped = []
    otp_detected = False
    captcha_detected = False
    otp_selector = None

    for field_info in fields:
        context = _build_context(field_info)
        category, matched_kw = _classify_field(context)
        selector = field_info.get("selector", "")
        label = field_info.get("label", "") or field_info.get("name", "") or selector

        # Track OTP / CAPTCHA presence
        if category == "otp":
            otp_detected = True
            otp_selector = selector
            skipped.append(f"{label} (otp — manual)")
            logger.info(f"[FORM] OTP field detected: '{label}'")
            continue

        if category == "captcha":
            captcha_detected = True
            skipped.append(f"{label} (captcha — manual)")
            logger.info(f"[FORM] CAPTCHA field detected: '{label}'")
            continue

        # Skip unsafe categories
        if category in NEVER_FILL:
            skipped.append(f"{label} ({category})")
            continue

        # Skip unknown fields
        if category == "unknown":
            skipped.append(f"{label} (unknown)")
            continue

        # Get value to fill
        value = value_map.get(category, "")
        if not value or not str(value).strip():
            skipped.append(f"{label} ({category} — no value)")
            continue

        # Fill only if field is currently empty
        try:
            locator = page.locator(selector).first

            if not locator.is_visible():
                skipped.append(f"{label} (not visible)")
                continue

            current_value = ""
            try:
                current_value = locator.input_value()
            except Exception:
                pass

            if current_value and current_value.strip():
                skipped.append(f"{label} (pre-filled)")
                logger.debug(f"[FORM] Skipping '{label}': already has value")
                continue

            # Fill the field
            locator.fill(str(value))
            page.wait_for_timeout(300)

            # Log with masking for sensitive data
            if category == "aadhaar":
                log_value = _mask_aadhaar(str(value))
                logger.info(f"[FORM] Aadhaar field mapped: '{label}' (keyword: '{matched_kw}')")
                logger.info(f"[FORM] Filled Aadhaar: {log_value}")
            else:
                logger.info(f"[FORM] Filled '{label}' ({category})")

            filled.append(label)

        except Exception as e:
            logger.error(f"[FORM] Failed to fill '{label}': {e}")
            skipped.append(f"{label} (error)")

    logger.info(
        f"[FORM] Classification complete: {len(filled)} filled, "
        f"{len(skipped)} skipped, otp={otp_detected}, captcha={captcha_detected}"
    )

    return {
        "filled": filled,
        "skipped": skipped,
        "otp_detected": otp_detected,
        "captcha_detected": captcha_detected,
        "otp_selector": otp_selector,
    }


# ─────────────────────────────────────────────────
# 3. ORCHESTRATOR
# ─────────────────────────────────────────────────

def handle_login_form(page, profile, state):
    """Full login form handler — called after every navigation step.

    Flow:
        1. Check domain state (skip if already handled)
        2. Detect login form
        3. Classify + fill safe fields
        4. CTA Phase 1 (Get OTP)
        5. OTP HITL prompt + fill
        6. CTA Phase 2 (Login / Verify)
        7. CAPTCHA HITL pause
        8. Mark domain as handled

    Args:
        page: Playwright page object.
        profile: Dict with user profile data.
        state: Mutable dict persisted across flow steps.

    Returns:
        Dict with action summary, or None if no login form detected.
    """
    # --- Domain-scoped guard ---
    domain = _get_domain(page)
    state.setdefault("login_handled_domains", set())

    if domain in state["login_handled_domains"]:
        logger.debug(f"[FORM] Skipping — login already handled for domain: {domain}")
        return None

    # --- Step 1: Detect ---
    if not detect_login_form(page):
        return None

    logger.info(f"[FORM] Login form detected on domain: {domain}")

    # --- Step 2: Classify + Fill ---
    result = classify_and_fill_fields(page, profile)

    # --- Step 3: CTA Phase 1 (pre-OTP) ---
    # Click CTA if we filled anything OR if a login form was detected (pre-filled case)
    if result["filled"] or detect_login_form(page):
        logger.info("[FORM] Attempting CTA Phase 1 (Get OTP / Continue)...")
        page.wait_for_timeout(500)
        clicked = safe_click_fuzzy(
            page, CTA_PHASE1, label="[FORM] CTA Phase 1", max_scroll=5
        )
        if clicked:
            logger.info("[FORM] Clicked Get OTP")
            page.wait_for_timeout(3000)  # Wait for OTP to be sent
        else:
            logger.warning("[FORM] CTA Phase 1 button not found")

    # --- Step 4: OTP HITL ---
    if result["otp_detected"] and result["otp_selector"]:
        logger.info("[FORM] OTP field present — requesting user input")
        otp_value = input("\n[OTP] Enter OTP sent to your device: ").strip()

        if otp_value:
            try:
                otp_locator = page.locator(result["otp_selector"]).first
                otp_locator.fill(otp_value)
                page.wait_for_timeout(300)
                logger.info("[FORM] OTP entered via HITL")
            except Exception as e:
                logger.error(f"[FORM] Failed to fill OTP: {e}")
        else:
            logger.warning("[FORM] Empty OTP entered, skipping fill")

        # --- Step 5: CTA Phase 2 (post-OTP) ---
        logger.info("[FORM] Attempting CTA Phase 2 (Login / Verify)...")
        page.wait_for_timeout(500)
        clicked = safe_click_fuzzy(
            page, CTA_PHASE2, label="[FORM] CTA Phase 2", max_scroll=5
        )
        if clicked:
            logger.info("[FORM] Post-OTP CTA clicked")
            page.wait_for_timeout(3000)
        else:
            logger.warning("[FORM] CTA Phase 2 button not found")

    # --- Step 6: CAPTCHA HITL ---
    if result["captcha_detected"]:
        logger.info("[FORM] CAPTCHA detected — pausing for manual solve")
        input("\n[HITL] Solve CAPTCHA in browser → Press Enter...")
        logger.info("[FORM] CAPTCHA pause complete, resuming")

    # --- Step 7: Finalize state ---
    state["login_handled_domains"].add(domain)
    logger.info(f"[FORM] Login handled for domain: {domain}")

    return {
        "domain": domain,
        "filled": result["filled"],
        "otp_handled": result["otp_detected"],
        "captcha_handled": result["captcha_detected"],
    }
