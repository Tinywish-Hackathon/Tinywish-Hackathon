from utils.logger import get_logger

logger = get_logger("extractor")


def extract_fields(page):
    """Returns a list of dicts with field information for visible form elements."""
    fields = page.locator("input:not([type='hidden']), select, textarea").all()

    result = []
    for field in fields:
        try:
            if not field.is_visible():
                continue

            name = field.get_attribute("name") or field.get_attribute("id") or ""
            field_type = field.get_attribute("type")
            tag_name = field.evaluate("el => el.tagName.toLowerCase()")

            if tag_name == "select":
                field_type = "select"
            if tag_name == "textarea":
                field_type = "textarea"

            label_text = None

            # 1. Try label element via id
            field_id = field.get_attribute("id")
            if field_id:
                label_loc = page.locator(f'label[for="{field_id}"]')
                if label_loc.count() > 0:
                    label_text = label_loc.first.inner_text()

            # 2. Try aria-label
            if not label_text:
                label_text = field.get_attribute("aria-label")

            # 3. Try generic placeholder
            placeholder = field.get_attribute("placeholder")

            result.append({
                "name": name,
                "type": field_type,
                "label": label_text,
                "placeholder": placeholder,
                "locator": field
            })
        except Exception as e:
            logger.debug(f"Skipping stale/inaccessible field: {e}")
            continue

    logger.info(f"Extracted {len(result)} visible form fields")
    return result