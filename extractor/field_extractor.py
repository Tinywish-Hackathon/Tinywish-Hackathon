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


def extract_input_fields(page):
    """Extract structured form field information with CSS selectors.

    Returns a list of dicts:
        [{"label": str, "type": str, "selector": str, "required": bool}]

    Extraction priority for label: label element > aria-label > placeholder > name/id.
    """
    fields = page.locator("input:not([type='hidden']), select, textarea").all()

    result = []
    for idx, field in enumerate(fields):
        try:
            if not field.is_visible():
                continue

            # --- Determine type ---
            tag_name = field.evaluate("el => el.tagName.toLowerCase()")
            field_type = field.get_attribute("type") or tag_name
            if tag_name == "select":
                field_type = "select"
            if tag_name == "textarea":
                field_type = "textarea"

            # --- Build CSS selector ---
            field_id = field.get_attribute("id")
            field_name = field.get_attribute("name")

            if field_id:
                selector = f"#{field_id}"
            elif field_name:
                selector = f"[name='{field_name}']"
            else:
                selector = f"input:not([type='hidden']):visible >> nth={idx}"

            # --- Determine label (priority order) ---
            label_text = None

            # 1. Label element via id
            if field_id:
                label_loc = page.locator(f'label[for="{field_id}"]')
                if label_loc.count() > 0:
                    try:
                        label_text = label_loc.first.inner_text().strip()
                    except Exception:
                        pass

            # 2. aria-label
            if not label_text:
                label_text = (field.get_attribute("aria-label") or "").strip()

            # 3. placeholder
            placeholder = (field.get_attribute("placeholder") or "").strip()
            if not label_text:
                label_text = placeholder

            # 4. name/id fallback
            if not label_text:
                label_text = field_name or field_id or ""

            # --- Required check ---
            required = (
                field.get_attribute("required") is not None
                or field.get_attribute("aria-required") == "true"
            )

            result.append({
                "label": label_text,
                "type": field_type,
                "selector": selector,
                "required": required,
                "placeholder": placeholder,
                "name": field_name or "",
            })

        except Exception as e:
            logger.debug(f"Skipping field {idx}: {e}")
            continue

    logger.info(f"Extracted {len(result)} input fields with selectors")
    for f in result:
        req = " (required)" if f["required"] else ""
        logger.debug(f"  [{f['type']}] {f['label']}{req} → {f['selector']}")

    return result