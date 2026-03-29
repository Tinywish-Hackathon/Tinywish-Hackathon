"""Startup India site configuration for portal-driven application flows."""

URL = "https://www.startupindia.gov.in/content/sih/en/government-schemes.html"

INTENT = "apply"

FLOW = [
    {
        "action": "detect",
        "label": "Inspect Startup India scheme hub",
    },
    {
        "action": "click_fuzzy",
        "candidates": [
            "startup india seed fund scheme",
            "credit guarantee scheme for startups",
            "sidbi fund of funds",
            "apply",
            "apply now",
            "know more",
            "view details",
        ],
        "label": "Navigate to selected Startup India scheme",
        "max_scroll": 12,
        "wait_after": 3000,
    },
    {
        "action": "detect",
        "label": "Detect application form or login wall",
    },
    {
        "action": "login_check",
        "label": "Handle login screen and identify OTP/CAPTCHA requirements",
        "wait_after": 2000,
    },
    {
        "action": "fill_form",
        "label": "Auto-fill visible Startup India form fields",
        "wait_after": 1000,
    },
    {
        "action": "wait",
        "label": "Human verification for OTP",
        "message": "Complete OTP, email verification, or any manual confirmation on Startup India",
        "wait_after": 1000,
    },
]
