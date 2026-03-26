import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
AADHAAR_PATH = os.path.join(DOCS_DIR, "aadhar.pdf")
MARKSHEET_PATH = os.path.join(DOCS_DIR, "marksheet.pdf")

START_URL = "https://scholarships.gov.in/"
PROFILE_PATH = os.path.join(BASE_DIR, "profile.json")


class Config:
    """Centralized config for API keys and secrets loaded from .env."""
    TINYFISH_API_KEY = os.getenv("TINYFISH_API_KEY")

