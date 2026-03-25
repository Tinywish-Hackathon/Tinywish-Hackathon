import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
AADHAAR_PATH = os.path.join(DOCS_DIR, "aadhaar.pdf")
MARKSHEET_PATH = os.path.join(DOCS_DIR, "marksheet.pdf")

START_URL = "https://scholarships.gov.in/"
PROFILE_PATH = os.path.join(BASE_DIR, "profile.json")
