import config

def map_field(field_info, profile):
    """
    Given field_info dictionary and profile data dict, 
    returns a tuple of (mapped_key, value_to_fill) or (None, None)
    """
    label = (field_info.get("label") or field_info.get("placeholder") or field_info.get("name") or "").lower()
    
    if "aadhaar" in label or "adhar" in label:
        return "aadhaar", config.AADHAAR_PATH
    if "marksheet" in label or "mark sheet" in label or "certificate" in label:
        return "marksheet", config.MARKSHEET_PATH

    # Text mapping
    if "name" in label:
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
        return "income", profile.get("income")
    if "state" in label:
        return "state", profile.get("state")
    if "gender" in label or "sex" in label:
        return "gender", profile.get("gender")
    if "password" in label:
        return "password", profile.get("password")

    return None, None