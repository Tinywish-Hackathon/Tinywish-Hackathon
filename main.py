import time
from playwright.sync_api import sync_playwright

START_URL = "https://scholarships.gov.in/"

def wait(msg):
    input(f"\n[MANUAL STEP] {msg} → Press Enter...")

def get_visible(locator):
    for i in range(locator.count()):
        el = locator.nth(i)
        try:
            if el.is_visible():
                return el
        except:
            continue
    return None


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=200)
        context = browser.new_context()
        page = context.new_page()

        print("Opening NSP...")
        page.goto(START_URL)

        page.wait_for_timeout(4000)

        print("URL:", page.url)

        # -----------------------------
        # STEP 1: STUDENTS (SAFE)
        # -----------------------------
        if "/Students" not in page.url:
            print("Finding Students tile...")

            students = get_visible(page.locator("text=Students"))

            if students:
                students.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                students.click(force=True)
                print("Clicked Students")
            else:
                wait("Click 'Students' manually")
        else:
            print("Already in Students section")

        # -----------------------------
        # STEP 2: REVEAL OTR (CRITICAL)
        # -----------------------------
        print("Revealing OTR section...")

        found = False

        for _ in range(10):
            try:
                if page.locator("text=Get your OTR").count() > 0:
                    print("OTR section found")
                    found = True
                    break
            except:
                pass

            page.mouse.wheel(0, 800)
            time.sleep(0.7)

        if not found:
            wait("Scroll manually until OTR is visible")

        # -----------------------------
        # STEP 3: CLICK APPLY NOW
        # -----------------------------
        print("Clicking Apply Now...")

        apply_btn = None

        for _ in range(8):
            loc = page.locator("text=Apply now")

            for i in range(loc.count()):
                el = loc.nth(i)
                try:
                    if el.is_visible():
                        apply_btn = el
                        break
                except:
                    continue

            if apply_btn:
                break

            page.mouse.wheel(0, 600)
            time.sleep(0.5)

        if apply_btn:
            apply_btn.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            apply_btn.click(force=True)
            print("Clicked Apply Now")
        else:
            wait("Click Apply Now manually")

        page.wait_for_timeout(4000)

        print("Now at:", page.url)

        # -----------------------------
        # STEP 4: WAIT FOR FORM
        # -----------------------------
        try:
            page.wait_for_selector("input", timeout=15000)
            print("Form detected")
        except:
            wait("Ensure form is visible")

        # -----------------------------
        # STEP 5: OTP / CAPTCHA
        # -----------------------------
        wait("Solve OTP / CAPTCHA")

        # -----------------------------
        # STEP 6: BASIC FILL
        # -----------------------------
        print("Filling fields...")

        profile = {
            "email": "rahultest123@gmail.com",
            "password": "Test@1234",
            "phone": "9876543210"
        }

        inputs = page.locator("input")

        for i in range(inputs.count()):
            inp = inputs.nth(i)

            try:
                name = (inp.get_attribute("name") or "").lower()
                placeholder = (inp.get_attribute("placeholder") or "").lower()

                field = name + " " + placeholder

                if "email" in field:
                    inp.fill(profile["email"])
                    print("Filled email")

                elif "password" in field:
                    inp.fill(profile["password"])
                    print("Filled password")

                elif "mobile" in field or "phone" in field:
                    inp.fill(profile["phone"])
                    print("Filled phone")

            except:
                continue

        wait("Check fields and submit manually")

        print("\nDONE. Your bot finally behaves like it understands NSP.")
        time.sleep(100000)


if __name__ == "__main__":
    main()