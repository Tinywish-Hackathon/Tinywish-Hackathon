"""NSP (National Scholarship Portal) site configuration."""

URL = "https://scholarships.gov.in/"

# Intent tells the agent what to prioritize scanning for
INTENT = "apply"

FLOW = [
    {
        "action": "detect",
        "label": "Inspect landing page",
    },
    {
        "action": "click",
        "section": ["students", "student corner", "student login"],
        "target": ["students", "student corner", "student login"],
        "label": "Navigate to Students section",
        "wait_after": 3000,
    },
    {
        "action": "detect",
        "label": "Inspect Students page",
    },
    {
        "action": "click",
        "section": ["otr", "one time registration", "get your otr"],
        "target": ["register", "login", "sign in", "new registration", "apply"],
        "label": "OTR / Registration",
        "max_scroll": 12,
    },
    {
        "action": "click_fuzzy",
        "candidates": ["apply now", "apply for scholarship", "apply"],
        "label": "Apply for Scholarship",
        "max_scroll": 10,
    },
    {
        "action": "click_fuzzy",
        "candidates": ["login", "sign in", "proceed"],
        "label": "Login / Sign In",
        "max_scroll": 6,
    },
    {
        "action": "wait",
        "message": "Solve OTP / CAPTCHA if required",
        "label": "Manual: OTP/CAPTCHA",
    },
    {
        "action": "fill_form",
        "label": "Auto-fill form fields",
        "wait_after": 1000,
    },
]
