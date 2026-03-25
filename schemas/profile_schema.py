"""User profile schema with Pydantic validation."""
import re
from typing import Optional
from pydantic import BaseModel, field_validator


class UserProfile(BaseModel):
    """Validated user profile for form filling automation.

    Required fields: full_name, email, phone.
    All other fields are optional and will be skipped during form fill if absent.
    """
    full_name: str
    email: str
    phone: str
    aadhaar: Optional[str] = None
    dob: Optional[str] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    education: Optional[str] = None
    category: Optional[str] = None
    income: Optional[str] = None
    state: Optional[str] = None
    password: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", v):
            raise ValueError(f"Invalid email format: {v}")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        digits = re.sub(r"[^\d]", "", v)
        if len(digits) < 10 or len(digits) > 15:
            raise ValueError(f"Phone must be 10-15 digits, got {len(digits)}: {v}")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, v):
        if len(v.strip()) < 2:
            raise ValueError("Full name must be at least 2 characters")
        return v.strip()
