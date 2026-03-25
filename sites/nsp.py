"""NSP (National Scholarship Portal) site configuration."""

URL = "https://scholarships.gov.in/"

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
        "action": "click",
        "section": ["apply for scholarship", "scholarship", "apply"],
        "target": ["login", "sign in", "apply now", "proceed"],
        "label": "Apply / Login",
        "max_scroll": 10,
    },
    {
        "action": "wait",
        "message": "Solve OTP / CAPTCHA if required",
        "label": "Manual: OTP/CAPTCHA",
    },
]
