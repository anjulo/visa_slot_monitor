#!/usr/bin/env python3
"""
US Visa Appointment Slot Checker — Ethiopia (AIS)
Uses Selenium with undetected-chromedriver to log in and monitor slots.
Sends SMS via Twilio when an earlier date is found.

MODES:
  --mode unpaid  → Logged in but fee not paid. Scrapes the earliest available
                   date shown on the post-login page.
  --mode paid    → Fee paid. Calls the appointment JSON API using your
                   schedule ID to check available calendar dates.

SETUP:
  pip install -r requirements.txt

USAGE:
  python3 visa_checker.py --mode unpaid
  python3 visa_checker.py --mode unpaid --current-date 2026-12-31
  python3 visa_checker.py --mode paid --schedule-id 12345678
  python3 visa_checker.py --mode paid --schedule-id 12345678 --current-date 2026-12-31
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime
from typing import Optional

import undetected_chromedriver as uc
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from twilio.rest import Client

# Load environment variables from .env file
load_dotenv()

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION — loaded from .env file
# ─────────────────────────────────────────────────────────────────

BASE_URL    = "https://ais.usvisa-info.com/en-et"
LOGIN_URL   = f"{BASE_URL}/users/sign_in"
NIV_HOME    = f"{BASE_URL}/niv"

# Your AIS account
AIS_EMAIL    = os.getenv("AIS_EMAIL", "")
AIS_PASSWORD = os.getenv("AIS_PASSWORD", "")

# Facility ID for Addis Ababa
FACILITY_ID = int(os.getenv("FACILITY_ID", "95"))

# Twilio — https://console.twilio.com
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM        = os.getenv("TWILIO_FROM_NUMBER", "")
TWILIO_TO          = os.getenv("TWILIO_TO_NUMBER", "")

# Seconds between checks (don't go below 120 — site will block you)
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))

# ─────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("visa_checker.log"),
    ],
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# SMS
# ─────────────────────────────────────────────────────────────────

def send_sms(body: str) -> None:
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(body=body, from_=TWILIO_FROM, to=TWILIO_TO)
        log.info(f"SMS sent — SID: {msg.sid}")
    except Exception as e:
        log.error(f"SMS failed: {e}")


# ─────────────────────────────────────────────────────────────────
# BROWSER SETUP
# ─────────────────────────────────────────────────────────────────

def make_driver(headless: bool = True) -> uc.Chrome:
    """
    Creates an undetected Chrome driver.
    undetected_chromedriver patches Chrome so reCAPTCHA v3 doesn't flag it.
    headless=False is useful for debugging login issues.
    """
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    driver = uc.Chrome(options=options)
    return driver


# ─────────────────────────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────────────────────────

def login(driver: uc.Chrome, email: str, password: str) -> bool:
    """
    Logs into AIS. Returns True on success.
    Selenium handles cookies and CSRF automatically via the real browser session.
    """
    log.info("Navigating to login page...")
    driver.get(LOGIN_URL)
    wait = WebDriverWait(driver, 20)

    try:
        # Fill email
        email_field = wait.until(EC.presence_of_element_located((By.ID, "user_email")))
        email_field.clear()
        email_field.send_keys(email)

        # Fill password
        pw_field = driver.find_element(By.ID, "user_password")
        pw_field.clear()
        pw_field.send_keys(password)

        # Accept policy checkbox if present
        try:
            checkbox = driver.find_element(By.ID, "policy_confirmed")
            if not checkbox.is_selected():
                checkbox.click()
        except Exception:
            pass  # checkbox may not exist

        # Submit
        submit_btn = driver.find_element(By.CSS_SELECTOR, "input[type='submit'], button[type='submit']")
        submit_btn.click()

        # Wait for redirect away from login page
        wait.until(EC.url_changes(LOGIN_URL))
        time.sleep(2)  # small buffer for session to settle

        current = driver.current_url
        if "sign_in" in current:
            log.error("Login failed — still on login page. Check credentials or solve CAPTCHA manually.")
            return False

        log.info(f"Login successful → {current}")
        return True

    except Exception as e:
        log.error(f"Login error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────
# EXTRACT CSRF TOKEN (needed for JSON API calls via requests)
# ─────────────────────────────────────────────────────────────────

def get_csrf_token(driver: uc.Chrome) -> Optional[str]:
    try:
        return driver.execute_script(
            "return document.querySelector('meta[name=\"csrf-token\"]')?.content"
        )
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
# MODE 1 — UNPAID
# After login, the page shows a message with the earliest available date.
# We scrape that text.
# ─────────────────────────────────────────────────────────────────

def check_unpaid(driver: uc.Chrome) -> Optional[str]:
    """
    Navigates to the NIV home / applicant summary after login and looks for
    the 'earliest available date' message that AIS shows to unpaid users.
    Returns a date string (YYYY-MM-DD) if found, else None.
    """
    log.info("[UNPAID] Loading applicant summary page...")
    driver.get(NIV_HOME)
    time.sleep(3)

    page = driver.page_source

    # AIS shows the date in the "First Available Appointments" table like:
    # "11 August, 2026" (day month, year format)
    # We try several patterns to be resilient to wording changes.
    patterns = [
        r"(\d{1,2}\s+\w+,?\s*\d{4})",   # "11 August, 2026" or "11 August 2026"
        r"(?:earliest|first available|available appointment)[^\d]*(\w+ \d{1,2},?\s*\d{4})",  # "August 11, 2026"
        r"(\d{4}-\d{2}-\d{2})",   # ISO date fallback (2026-08-11)
        r"(\d{1,2}/\d{1,2}/\d{4})",  # US format fallback (08/11/2026)
    ]

    for pat in patterns:
        m = re.search(pat, page, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            parsed = parse_date_flexible(raw)
            if parsed:
                log.info(f"[UNPAID] Found date on page: {raw} → {parsed}")
                return str(parsed)

    # If no date found in text, dump a snippet for debugging
    log.warning("[UNPAID] Could not find date on page. Saving page snippet to unpaid_debug.html")
    with open("unpaid_debug.html", "w", encoding="utf-8") as f:
        f.write(page)
    log.warning("Open unpaid_debug.html to inspect the page and update the regex pattern.")
    return None


def parse_date_flexible(raw: str) -> Optional[date]:
    """Tries multiple date formats and returns a date object or None."""
    formats = [
        "%d %B, %Y",   # 11 August, 2026
        "%d %B %Y",    # 11 August 2026
        "%B %d, %Y",   # August 11, 2026
        "%B %d %Y",    # August 11 2026
        "%Y-%m-%d",    # 2026-08-11
        "%m/%d/%Y",    # 08/11/2026
        "%d/%m/%Y",    # 11/08/2026
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


# ─────────────────────────────────────────────────────────────────
# MODE 2 — PAID
# Uses the Selenium session's cookies to call the JSON API that the
# AIS calendar uses. Returns the earliest available date.
# ─────────────────────────────────────────────────────────────────

def check_paid(driver: uc.Chrome, schedule_id: int) -> Optional[str]:
    """
    Calls the AIS appointment days API using the browser's authenticated session.
    We inject a fetch() call into the page via JavaScript so the browser sends
    all the right cookies and headers automatically — no manual cookie extraction needed.
    """
    api_url = (
        f"{BASE_URL}/niv/schedule/{schedule_id}/appointment/"
        f"days/{FACILITY_ID}.json?appointments[expedite]=false"
    )

    # Navigate to the appointment page first so Referer header is correct
    appt_page = f"{BASE_URL}/niv/schedule/{schedule_id}/appointment"
    log.info(f"[PAID] Loading appointment page: {appt_page}")
    driver.get(appt_page)
    time.sleep(2)

    log.info(f"[PAID] Calling API: {api_url}")

    # Execute fetch() in the browser context — it carries all session cookies
    js = f"""
        return new Promise((resolve, reject) => {{
            fetch("{api_url}", {{
                headers: {{
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest"
                }},
                credentials: "include"
            }})
            .then(r => r.text())
            .then(resolve)
            .catch(e => reject(e.toString()));
        }});
    """

    try:
        result = driver.execute_async_script(
            """
            var callback = arguments[arguments.length - 1];
            """ + js.replace("return new Promise", "new Promise") +
            """.then(callback).catch(callback);
            """
        )
    except Exception as e:
        log.error(f"[PAID] JS fetch error: {e}")
        return None

    if not result or not isinstance(result, str):
        log.warning("[PAID] Empty or unexpected API response.")
        return None

    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        log.warning(f"[PAID] Non-JSON response: {result[:200]}")
        return None

    if not isinstance(data, list) or len(data) == 0:
        log.info("[PAID] No available dates in API response.")
        return None

    available = [entry["date"] for entry in data if entry.get("business_day")]
    if not available:
        log.info("[PAID] No business-day slots available.")
        return None

    earliest = min(available)
    log.info(f"[PAID] Earliest available: {earliest}")
    return earliest


# ─────────────────────────────────────────────────────────────────
# EXTRACT SCHEDULE ID FROM PAGE (paid mode helper)
# ─────────────────────────────────────────────────────────────────

def extract_schedule_id(driver: uc.Chrome) -> Optional[int]:
    """Pulls the schedule ID from any link in the dashboard that contains it."""
    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/schedule/']")
    for link in links:
        href = link.get_attribute("href") or ""
        m = re.search(r"/schedule/(\d+)/", href)
        if m:
            sid = int(m.group(1))
            log.info(f"Auto-detected schedule ID: {sid}")
            return sid
    return None


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="US Visa Slot Checker — Ethiopia")
    parser.add_argument("--mode", choices=["unpaid", "paid"], required=True)
    parser.add_argument("--current-date", required=False, default=None,
                        help="Your current appointment date YYYY-MM-DD (only for paid mode)")
    parser.add_argument("--schedule-id", type=int, default=None,
                        help="(Paid mode) Your schedule ID from the AIS URL. "
                             "If omitted, the script tries to auto-detect it after login.")
    parser.add_argument("--interval", type=int, default=CHECK_INTERVAL,
                        help=f"Seconds between checks (default: {CHECK_INTERVAL})")
    parser.add_argument("--no-headless", action="store_true",
                        help="Show the browser window (useful for debugging login)")
    args = parser.parse_args()

    # Validate --current-date (only meaningful for paid mode)
    current_date = None
    if args.current_date:
        try:
            current_date = datetime.strptime(args.current_date, "%Y-%m-%d").date()
        except ValueError:
            log.error("Invalid --current-date. Use YYYY-MM-DD format.")
            sys.exit(1)

    log.info("=" * 60)
    log.info("  US Visa Slot Checker — Ethiopia (AIS)")
    log.info(f"  Mode          : {args.mode.upper()}")
    if current_date:
        log.info(f"  Current appt  : {current_date}")
        log.info(f"  Alert if      : earlier than {current_date}")
    log.info(f"  Check every   : {args.interval}s")
    log.info(f"  SMS to        : {TWILIO_TO}")
    log.info("=" * 60)

    headless = not args.no_headless
    driver = make_driver(headless=headless)
    wait = WebDriverWait(driver, 20)

    # --- LOGIN ---
    if not login(driver, AIS_EMAIL, AIS_PASSWORD):
        driver.quit()
        sys.exit(1)

    # --- AUTO-DETECT SCHEDULE ID (paid mode) ---
    schedule_id = args.schedule_id
    if args.mode == "paid" and not schedule_id:
        schedule_id = extract_schedule_id(driver)
        if not schedule_id:
            log.error(
                "Could not auto-detect schedule ID. "
                "Pass it explicitly with --schedule-id XXXXXXXX\n"
                "Find it in your AIS URL: .../schedule/XXXXXXXX/appointment"
            )
            driver.quit()
            sys.exit(1)

    last_alerted: Optional[str] = None

    # --- MAIN LOOP ---
    while True:
        try:
            # Re-login if session expired (detect redirect to login page)
            if "sign_in" in driver.current_url:
                log.warning("Session expired. Re-logging in...")
                if not login(driver, AIS_EMAIL, AIS_PASSWORD):
                    log.error("Re-login failed. Retrying in 60s.")
                    time.sleep(60)
                    continue

            # Check depending on mode
            if args.mode == "unpaid":
                earliest_str = check_unpaid(driver)
            else:
                earliest_str = check_paid(driver, schedule_id)

            if earliest_str:
                earliest = datetime.strptime(earliest_str, "%Y-%m-%d").date()

                # For unpaid mode, send SMS when date changes
                if args.mode == "unpaid":
                    if earliest_str != last_alerted:
                        message = (
                            f"🚨 VISA APPOINTMENT AVAILABLE — Ethiopia\n"
                            f"Earliest available: {earliest_str}\n"
                            f"Book now → {BASE_URL}/niv"
                        )
                        log.info(f"NEW DATE! {earliest_str}")
                        send_sms(message)
                        last_alerted = earliest_str
                    else:
                        log.info(f"Date unchanged: {earliest_str}")
                
                # For paid mode with current_date, check if earlier and alert
                elif args.mode == "paid" and current_date and earliest < current_date and earliest_str != last_alerted:
                    days_earlier = (current_date - earliest).days
                    message = (
                        f"🚨 VISA SLOT ALERT — Ethiopia\n"
                        f"Earlier slot found: {earliest_str}\n"
                        f"({days_earlier} days earlier than your current appt: {current_date})\n"
                        f"Book now → {BASE_URL}/niv/schedule/{schedule_id}/appointment"
                    )
                    log.info(f"ALERT! Earlier slot: {earliest_str} ({days_earlier} days earlier)")
                    send_sms(message)
                    last_alerted = earliest_str

                elif earliest_str == last_alerted:
                    log.info(f"Already alerted for {earliest_str}. No SMS.")

                else:
                    if args.mode == "paid" and current_date:
                        log.info(f"No earlier slot. Earliest available: {earliest_str}")
                    elif args.mode == "paid":
                        log.info(f"Earliest available: {earliest_str}")
            else:
                log.info("No date found this cycle.")

        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}")

        log.info(f"Sleeping {args.interval}s...\n")
        time.sleep(args.interval)

    driver.quit()


if __name__ == "__main__":
    main()