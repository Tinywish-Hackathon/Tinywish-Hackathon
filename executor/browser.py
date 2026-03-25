from playwright.sync_api import sync_playwright

def start_browser():
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(viewport={'width': 1280, 'height': 800})
    page = context.new_page()
    page.set_default_timeout(60000)
    return p, browser, context, page

def wait_for_user_input(page, message="Action Required"):
    print(f"\n[!] PAUSED: {message}")
    print("Please complete the required action in the browser (e.g., OTP or CAPTCHA).")
    input("Press ENTER in this terminal when you are ready to resume...")
    print("Resuming automation...\n")

def fill_field(page, field_info, value):
    try:
        locator = field_info["locator"]
        if field_info["type"] == "file":
            locator.set_input_files(value)
            print(f"Uploaded file: {value}")
        elif field_info["type"] in ["select-one", "select"]:
            # Depending on the select options, we might need value or label
            # We will try label first, as usually the value passed is human readable
            try:
                locator.select_option(label=value)
            except:
                # Fallback to value
                locator.select_option(value=value)
            print(f"Selected option: {value}")
        elif field_info["type"] in ["checkbox", "radio"]:
            if str(value).lower() in ["true", "yes", "1", "male", "female"]:
                locator.check()
                print(f"Checked radio/checkbox")
        else:
            locator.fill(str(value))
            print(f"Filled text: {value}")
    except Exception as e:
        print(f"Failed to fill field {field_info.get('name')}: {e}")