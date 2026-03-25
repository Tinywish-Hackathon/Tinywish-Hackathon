def extract_fields(page):
    # Returns a list of dicts with field information
    fields = page.locator("input:not([type='hidden']), select, textarea").all()
    
    result = []
    for field in fields:
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
            label_elem = page.locator(f'label[for="{field_id}"]').first
            if label_elem.count() > 0:
                label_text = label_elem.inner_text()
                
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
        
    return result