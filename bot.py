import os
import re
import json
import time
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

RAW_SECRET = (os.environ.get("AICTE_COOKIES") or os.environ.get("AICTE_TOKEN") or "").strip()
EMAIL = (os.environ.get("AICTE_EMAIL") or "").strip()
PASSWORD = (os.environ.get("AICTE_PASSWORD") or "").strip()

MEETING_URL = "https://beeskilled.in/"
DOCUMENTS_REQ = "NA"
INTERVIEW_REMARKS = """Dear Student,

Congratulations! you have been successfully shortlisted for the Beeskilled Internship Program.

Next Steps to Confirm Your Spot:

Visit our official website: www.beeskilled.in
Explore the courses and select your interested Domain.

Click on "Apply Now" and choose your preferred internship pathway to secure your seat.

Please complete your application process as soon as possible so we can generate your onboarding credentials."""

def get_tomorrow_date():
    ist = timezone(timedelta(hours=5, minutes=30))
    tomorrow = datetime.now(ist) + timedelta(days=1)
    return tomorrow.strftime("%Y-%m-%d")

def build_storage_script(raw_data):
    """Sirf tabhi purana token dalega jab browser ke paas naya token na ho"""
    if not raw_data:
        return ""
    try:
        parsed = json.loads(raw_data)
        if isinstance(parsed, dict) and ("ls" in parsed or "ss" in parsed):
            ls_data = json.dumps(parsed.get("ls", {}))
            ss_data = json.dumps(parsed.get("ss", {}))
            return f"""
                try {{
                    if (!window.sessionStorage.getItem('nip:access')) {{
                        const ls = {ls_data};
                        const ss = {ss_data};
                        for (const [k, v] of Object.entries(ls)) window.localStorage.setItem(k, v);
                        for (const [k, v] of Object.entries(ss)) window.sessionStorage.setItem(k, v);
                    }}
                }} catch (e) {{}}
            """
    except Exception:
        pass

    clean_token = raw_data.strip('"').strip("'")
    token_js = json.dumps(clean_token)
    return f"""
        try {{
            if (!window.sessionStorage.getItem('nip:access')) {{
                window.sessionStorage.setItem('nip:access', {token_js});
                window.localStorage.setItem('nip:access', {token_js});
            }}
        }} catch (e) {{}}
    """

def auto_login_renew_session(page):
    """Jab 15-min wala Token expire ho jaye, toh khud Login karke naya Token banata hai"""
    print(">> Token expire ho gaya hai! Auto-Login se naya session bana raha hu...", flush=True)
    if not EMAIL or not PASSWORD:
        print("ERROR: AICTE_EMAIL ya AICTE_PASSWORD GitHub Secret mein nahi mila!", flush=True)
        return False

    page.evaluate("() => { window.__captcha_items = []; window.__last_draw = 0; }")
    page.goto("https://internship.aicte-india.org/auth/login?role=employer&next=%2Femployer%2Fdashboard", timeout=60000)
    page.wait_for_selector("input[type='password']", timeout=30000)
    time.sleep(2.5)

    for attempt in range(1, 10):
        print(f"--- Session Renew Attempt #{attempt} ---", flush=True)
        email_box = page.locator("input[type='email'], input[placeholder*='email' i], input[type='text']").first
        pass_box = page.locator("input[type='password']").first

        email_box.fill(EMAIL)
        pass_box.fill(PASSWORD)
        time.sleep(0.5)

        # Solid (fillText) + Hollow Outline (strokeText) dono se exact 6 akshar nikalna
        captcha_code = page.evaluate("() => (window.__captcha_items || []).map(x => x.c).join('')")
        captcha_code = re.sub(r"[^A-Za-z0-9]", "", captcha_code)[-6:]
        print(f"Captcha Read: '{captcha_code}'", flush=True)

        captcha_input = page.locator("input[placeholder*='CODE' i], input[placeholder*='CAPTCHA' i]").first
        if captcha_input.count() > 0:
            captcha_input.fill(captcha_code)
        time.sleep(0.5)

        # Agar button disabled ho toh enable karke click karna
        page.evaluate("""() => {
            const btn = document.querySelector("button[type='submit']");
            if (btn) btn.removeAttribute('disabled');
        }""")
        login_btn = page.locator("button:has-text('LOGIN TO DASHBOARD'), button[type='submit']").first
        try:
            login_btn.click(timeout=5000)
        except Exception:
            pass

        try:
            page.get_by_text("Interview Management").first.wait_for(state="visible", timeout=10000)
            print("SUCCESS: Naya Session Token ban gaya aur Dashboard khul gaya!", flush=True)
            return True
        except Exception:
            print("Captcha refresh kar raha hu...", flush=True)
            page.evaluate("() => { window.__captcha_items = []; window.__last_draw = 0; }")
            try:
                captcha_section = page.locator("text=SECURITY CHECK").locator("..").locator("..")
                captcha_section.locator("button").first.click(timeout=3000)
                time.sleep(2)
            except Exception:
                page.reload(timeout=60000)
                time.sleep(3)

    return False

def close_open_modal(page):
    try:
        modal_backdrop = page.locator("div.fixed.inset-0")
        if modal_backdrop.count() > 0 and modal_backdrop.first.is_visible():
            cancel_btn = page.get_by_role("button", name="Cancel", exact=True).first
