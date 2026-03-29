import os

import config
from utils.logger import get_logger


logger = get_logger("form_mapper")


def _mask_aadhaar(aadhaar_number):
    digits = "".join(ch for ch in str(aadhaar_number or "") if ch.isdigit())
    if len(digits) >= 4:
        return f"XXXX-XXXX-{digits[-4:]}"
    return "XXXX-XXXX-XXXX"


def _is_file_field(field_type):
    return field_type == "file"


def _get_document_path(label):
    if "income_cert" in label or "income certificate" in label or "income cert" in label:
        return getattr(config, "INCOME_CERT_PATH", "")
    if "marksheet" in label or "mark sheet" in label:
        return getattr(config, "MARKSHEET_PATH", "")
    if "certificate" in label:
        return getattr(config, "CERTIFICATE_PATH", getattr(config, "MARKSHEET_PATH", ""))
    return ""


def map_field(field_info, profile):
    """
    Given field_info dictionary and profile data dict, 
    returns a tuple of (mapped_key, value_to_fill) or (None, None)
    """
    label = (field_info.get("label") or field_info.get("placeholder") or field_info.get("name") or "").lower()
    field_type = (field_info.get("type", "text") or "text").lower()
    
    if any(value in label for value in ["aadhaar", "aadhar", "adhar", "adhaar", "uid"]):
        if _is_file_field(field_type):
            return "aadhaar", config.AADHAAR_PATH

        aadhaar_number = os.getenv("AADHAAR_NUMBER", "").strip()
        if aadhaar_number:
            logger.info(f"[MAPPER] Filling Aadhaar number: {_mask_aadhaar(aadhaar_number)}")
        return "aadhaar", aadhaar_number

    if (
        "marksheet" in label
        or "mark sheet" in label
        or "certificate" in label
        or "income_cert" in label
        or "income certificate" in label
        or "income cert" in label
    ):
        if not _is_file_field(field_type):
            return None, None

        document_path = _get_document_path(label)
        if document_path:
            if "income_cert" in label or "income certificate" in label or "income cert" in label:
                return "income_cert", document_path
            return "marksheet", document_path
        return None, None

    # Text mapping
    if "name" in label and not any(value in label for value in ["bank", "scheme", "user", "insti"]):
        return "full_name", profile.get("full_name")
        
    if "email" in label:
        return "email", profile.get("email")
    if "phone" in label or "mobile" in label:
        return "phone", profile.get("phone")
    if "dob" in label or "date of birth" in label:
        return "dob", profile.get("dob")
    if "category" in label or "caste" in label:
        return "category", profile.get("category")
    if "income" in label:
        return "annual_income", profile.get("annual_income")
    if "state" in label:
        return "state", profile.get("state")
    if "gender" in label or "sex" in label:
        return "gender", profile.get("gender")
    if "password" in label:
        return None, None

    return None, None
