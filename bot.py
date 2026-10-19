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


def close_open_modal(page):
    try:
        modal_backdrop = page.locator("div.fixed.inset-0")
        if modal_backdrop.count() == 0:
            return
        if not modal_backdrop.first.is_visible():
            return
        cancel_btn = page.get_by_role("button", name="Cancel", exact=True).first
        if cancel_btn.count() > 0 and cancel_btn.is_visible():
            cancel_btn.click(timeout=2000)
        else:
            page.keyboard.press("Escape")
        time.sleep(0.8)
        if modal_backdrop.first.is_visible():
            page.locator("div.fixed.inset-0 button").first.click(timeout=2000)
            time.sleep(0.8)
    except Exception:
        pass


def auto_login_renew_session(page):
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

        captcha_code = page.evaluate("() => (window.__captcha_items || []).map(x => x.c).join('')")
        captcha_code = re.sub(r"[^A-Za-z0-9]", "", captcha_code)[-6:]
        print(f"Captcha Read: '{captcha_code}'", flush=True)

        captcha_input = page.locator("input[placeholder*='CODE' i], input[placeholder*='CAPTCHA' i]").first
        if captcha_input.count() > 0:
            captcha_input.fill(captcha_code)
        time.sleep(0.5)

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


def ensure_interview_management(page):
    close_open_modal(page)

    if "auth/login" in page.url:
        if not auto_login_renew_session(page):
            raise Exception("Auto-Login fail hua")

    pending_tab = page.get_by_text("Pending Applications").first
    if not pending_tab.is_visible():
        try:
            page.get_by_text("Interview Management").first.click(timeout=10000)
            pending_tab.wait_for(state="visible", timeout=10000)
            time.sleep(1)
        except Exception:
            page.goto("https://internship.aicte-india.org/employer/dashboard", timeout=60000)
            time.sleep(3)
            if "auth/login" in page.url or not page.get_by_text("Interview Management").first.is_visible():
                if not auto_login_renew_session(page):
                    raise Exception("Session renew nahi ho paya")
            page.get_by_text("Interview Management").first.click(timeout=15000)
            pending_tab.wait_for(state="visible", timeout=15000)
            time.sleep(1)


def set_max_rows_per_page(page):
    try:
        selects = page.locator("select")
        if selects.count() >= 2:
            row_select = selects.nth(1)
            options = row_select.locator("option").all_inner_texts()
            for val in ["100", "50", "25"]:
                if val in [o.strip() for o in options]:
                    row_select.select_option(label=val)
                    time.sleep(1)
                    break
    except Exception:
        pass


def wait_15_mins_keep_alive(page):
    """15 minute wait karega aur har 3 minute mein tab click karega taaki session expire na ho"""
    print("Waiting 15 minutes for new students (Session Keep-Alive Active)...", flush=True)
    for i in range(5):
        time.sleep(180)
        try:
            close_open_modal(page)
            if i % 2 == 0 and page.get_by_text("Pending Applications").first.is_visible():
                page.get_by_text("Pending Applications").first.click(timeout=5000)
            elif page.get_by_text("Shortlisted Applicants").first.is_visible():
                page.get_by_text("Shortlisted Applicants").first.click(timeout=5000)
        except Exception:
            pass


def process_all_students(page, iso_date):
    ensure_interview_management(page)

    print(">> Pending Applications check kar raha hu...", flush=True)
    page.get_by_text("Pending Applications").first.click(timeout=15000)
    time.sleep(1)
    set_max_rows_per_page(page)

    shortlisted_count = 0
    skip_shortlist_idx = 0
    empty_checks = 0

    while True:
        close_open_modal(page)
        shortlist_btns = page.get_by_role("button", name="Shortlist", exact=True)
        count = shortlist_btns.count()

        if count <= skip_shortlist_idx:
            empty_checks += 1
            if empty_checks >= 2:
                print(f"Pending check done! Total {shortlisted_count} shortlisted (Skipped stuck: {skip_shortlist_idx}).", flush=True)
                break
            time.sleep(1)
            page.get_by_text("Pending Applications").first.click(timeout=15000)
            time.sleep(1)
            continue

        empty_checks = 0
        try:
            prev_count = count
            shortlist_btns.nth(skip_shortlist_idx).click(timeout=5000)
            time.sleep(0.7)

            new_count = page.get_by_role("button", name="Shortlist", exact=True).count()
            if new_count < prev_count:
                shortlisted_count += 1
                print(f"[SUCCESS] Student #{shortlisted_count} Shortlisted!", flush=True)
            else:
                print(f"[SKIP] Pending Student #{skip_shortlist_idx + 1} portal par stuck hai, skip kiya.", flush=True)
                skip_shortlist_idx += 1
        except Exception:
            skip_shortlist_idx += 1
            time.sleep(1)

    print(">> Shortlisted Applicants tab khol raha hu...", flush=True)
    close_open_modal(page)
    page.get_by_text("Shortlisted Applicants").first.click(timeout=15000)
    time.sleep(1)
    set_max_rows_per_page(page)

    called_count = 0
    skip_call_idx = 0
    empty_call_checks = 0

    while True:
        close_open_modal(page)
        call_btns = page.get_by_role("button", name="Call for Interview", exact=True)
        count = call_btns.count()

        if count <= skip_call_idx:
            empty_call_checks += 1
            if empty_call_checks >= 2:
                print(f"Shortlisted tab done! Total {called_count} calls sent (Skipped stuck: {skip_call_idx}).", flush=True)
                break
            time.sleep(1)
            page.get_by_text("Shortlisted Applicants").first.click(timeout=15000)
            time.sleep(1)
            continue

        empty_call_checks = 0
        try:
            call_btns.nth(skip_call_idx).click(timeout=5000)

            url_input = page.locator("input[placeholder*='meet.google.com' i]").first
            url_input.wait_for(state="visible", timeout=5000)

            try:
                date_input = page.locator("input[type='date']").first
                if date_input.count() > 0 and date_input.is_visible():
                    date_input.fill(iso_date)
                else:
                    alt_date = page.locator("text=DATE OF INTERVIEW").locator("..").locator("input").first
                    alt_date.fill(iso_date)
            except Exception:
                pass

            try:
                time_input = page.locator("input[type='time']").first
                if time_input.count() > 0 and time_input.is_visible():
                    if not time_input.input_value():
                        time_input.fill("11:00")
            except Exception:
                pass

            page.locator("input[placeholder*='Resume' i]").first.fill(DOCUMENTS_REQ)
            url_input.fill(MEETING_URL)
            page.locator("textarea[placeholder*='Anything the candidate' i], textarea").first.fill(INTERVIEW_REMARKS)
            time.sleep(0.3)

            send_btn = page.get_by_role("button", name="Send Interview Call & Link", exact=True).first
            send_btn.click(timeout=5000)

            try:
                send_btn.wait_for(state="hidden", timeout=6000)
                called_count += 1
                print(f"[SUCCESS] Student #{called_count} ko Interview Call bhej diya!", flush=True)
                time.sleep(0.4)
            except Exception:
                print(f"[SKIP] Student #{skip_call_idx + 1} portal par stuck hai, skip kar raha hu...", flush=True)
                close_open_modal(page)
                skip_call_idx += 1

        except Exception:
            print(f"[SKIP] Student #{skip_call_idx + 1} ka button disabled/stuck hai, agle student par ja raha hu...", flush=True)
            close_open_modal(page)
            skip_call_idx += 1
            time.sleep(1)

    return shortlisted_count, called_count


def run_bot():
    print("--- AICTE 24/7 AUTO BOT START (15-MIN INTERVAL) ---", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})

        context.add_init_script("""
            window.__captcha_items = [];
            window.__last_draw = 0;
            function recordChar(text, type) {
                const t = String(text || '').trim();
                if (!/^[A-Za-z0-9]$/.test(t)) return;
                const now = Date.now();
                if (now - window.__last_draw > 50) {
                    window.__captcha_items = [];
                }
                window.__last_draw = now;
                const items = window.__captcha_items;
                const last = items[items.length - 1];
                if (last && last.c === t && !last[type]) {
                    last[type] = true;
                } else {
                    const item = { c: t, fill: false, stroke: false };
                    item[type] = true;
                    items.push(item);
                }
            }
            const origFill = CanvasRenderingContext2D.prototype.fillText;
            CanvasRenderingContext2D.prototype.fillText = function(text, ...args) {
                recordChar(text, 'fill');
                return origFill.apply(this, [text, ...args]);
            };
            const origStroke = CanvasRenderingContext2D.prototype.strokeText;
            CanvasRenderingContext2D.prototype.strokeText = function(text, ...args) {
                recordChar(text, 'stroke');
                return origStroke.apply(this, [text, ...args]);
            };
        """)

        storage_script = build_storage_script(RAW_SECRET)
        if storage_script:
            context.add_init_script(storage_script)

        page = context.new_page()

        print("1. Employer Dashboard khol raha hu...", flush=True)
        page.goto("https://internship.aicte-india.org/employer/dashboard", timeout=60000)

        try:
            page.get_by_text("Interview Management").first.wait_for(state="visible", timeout=12000)
            print("SUCCESS: Token se seedha Dashboard khul gaya!", flush=True)
        except Exception:
            print("Initial Token expire ho chuka hai, Auto-Login se naya session bana raha hu...", flush=True)
            if not auto_login_renew_session(page):
                print("ERROR: Login nahi ho paya.", flush=True)
                browser.close()
                return

        start_time = time.time()
        cycle = 1
        while (time.time() - start_time) < 330 * 60:
            iso_date = get_tomorrow_date()
            print(f"\n=== AUTO-CHECK CYCLE #{cycle} (Interview Date: {iso_date}) ===", flush=True)

            try:
                process_all_students(page, iso_date)
            except Exception as cycle_err:
                print(f"Cycle #{cycle} recovery: {cycle_err}", flush=True)

            wait_15_mins_keep_alive(page)
            cycle += 1

            try:
                close_open_modal(page)
                page.get_by_text("Dashboard").first.click(timeout=10000)
                time.sleep(1)
                page.get_by_text("Interview Management").first.click(timeout=10000)
                time.sleep(1.5)
            except Exception:
                pass

        browser.close()
        print("--- 5.5 HOUR SHIFT COMPLETE (AUTO-STARTING NEXT SHIFT NOW) ---", flush=True)


if __name__ == "__main__":
    run_bot()
