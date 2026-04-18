#!/usr/bin/env python3
"""
US Visa Appointment Slot Checker — Ethiopia (AIS)
Monitors ais.usvisa-info.com and sends an SMS when an earlier slot appears.

See README.md for full setup and usage instructions.
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
LOGIN_URL   = f"{BASE_URL}/niv/users/sign_in"
NIV_HOME    = f"{BASE_URL}/niv"

# Your AIS account
AIS_EMAIL    = os.getenv("AIS_EMAIL", "")
AIS_PASSWORD = os.getenv("AIS_PASSWORD", "")

# Schedule ID — priority: --schedule-id flag → this env var → auto-detect
# Useful to set when your account has multiple groups.
SCHEDULE_ID = int(os.getenv("SCHEDULE_ID", "0"))

# Facility ID for Addis Ababa — required for paid mode.
# Priority: --facility-id flag → FACILITY_ID in .env → error
# Find it by inspecting the location dropdown on the AIS reschedule page:
#   right-click the consulate dropdown → Inspect → <option value="???">Addis Ababa</option>
FACILITY_ID = int(os.getenv("FACILITY_ID", "0"))

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
        options.add_argument("--headless")
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
    time.sleep(3)
    
    try:
        log.info(f"Page loaded. Title: {driver.title}, URL: {driver.current_url}")
        
        wait = WebDriverWait(driver, 20)

        # Fill email
        log.info("Waiting for email field...")
        email_field = wait.until(EC.presence_of_element_located((By.ID, "user_email")))
        log.info("✓ Found email field")
        email_field.clear()
        email_field.send_keys(email)

        # Fill password
        log.info("Filling password...")
        pw_field = driver.find_element(By.ID, "user_password")
        pw_field.clear()
        pw_field.send_keys(password)

        # Accept policy checkbox
        log.info("Finding privacy policy checkbox...")
        try:
            checkbox = driver.find_element(By.ID, "policy_confirmed")
            log.info(f"Checkbox found. Currently selected: {checkbox.is_selected()}")
            
            # Ensure checkbox is always clicked
            # Use JavaScript click as a fallback if regular click doesn't work
            if not checkbox.is_selected():
                try:
                    checkbox.click()
                    log.info("✓ Clicked checkbox with Selenium")
                except:
                    log.info("Checkbox click via Selenium failed, trying JavaScript...")
                    driver.execute_script("arguments[0].click();", checkbox)
                    log.info("✓ Clicked checkbox with JavaScript")
            
            time.sleep(0.5)
            if not checkbox.is_selected():
                log.warning("Checkbox still not selected after click. Trying again...")
                driver.execute_script("arguments[0].checked = true;", checkbox)
                log.info("✓ Set checkbox to checked via JavaScript")
                
        except Exception as e:
            log.error(f"Checkbox error: {e}")
            pass

        # Submit
        log.info("Submitting login form...")
        submit_btn = driver.find_element(By.CSS_SELECTOR, "input[type='submit'], button[type='submit']")
        submit_btn.click()

        # Close any error dialogs
        time.sleep(2)
        try:
            ok_button = driver.find_element(By.CSS_SELECTOR, ".ui-dialog-buttonset button")
            ok_button.click()
            log.info("Closed error dialog")
            time.sleep(1)
        except:
            pass

        # Wait for redirect away from login page
        log.info("Waiting for redirect...")
        wait.until(EC.url_changes(LOGIN_URL))
        time.sleep(2)

        current = driver.current_url
        if "sign_in" in current:
            log.error("Login failed — still on login page. Check credentials or solve CAPTCHA manually.")
            return False

        log.info("✓ Login successful")
        return True

    except Exception as e:
        log.error(f"Login error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────
# EXTRACT CSRF TOKEN
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
# The /payment page shows the earliest available appointment date
# to users who haven't paid yet.
# ─────────────────────────────────────────────────────────────────

def check_unpaid(driver: uc.Chrome, schedule_id: int) -> Optional[date]:
    """
    Navigates to the payment page (e.g. /en-et/niv/schedule/73783417/payment)
    which shows the earliest available appointment date to unpaid users.
    Returns a date object if found, else None.
    """
    payment_url = f"{BASE_URL}/niv/schedule/{schedule_id}/payment"
    log.debug(f"[UNPAID] Loading payment page: {payment_url}")
    driver.get(payment_url)
    time.sleep(3)

    page = driver.page_source

    # AIS shows the date in the "First Available Appointments" table like:
    # "11 August, 2026" (day month, year format)
    # We try several patterns to be resilient to wording changes.
    patterns = [
        r"(\d{1,2}\s+\w+,?\s*\d{4})",   # "11 August, 2026" or "11 August 2026"
        r"(?:earliest|first available|available appointment)[^\d]*(\w+ \d{1,2},?\s*\d{4})",
        r"(\d{4}-\d{2}-\d{2})",          # ISO fallback: 2026-08-11
        r"(\d{1,2}/\d{1,2}/\d{4})",      # US format fallback: 08/11/2026
    ]

    for pat in patterns:
        m = re.search(pat, page, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            parsed = parse_date_flexible(raw)
            if parsed:
                log.debug(f"[UNPAID] Found date on page: {raw} → {parsed}")
                return parsed

    # Save page for debugging if nothing matched
    log.warning("[UNPAID] Could not find date on page. Saving to unpaid_debug.html")
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

def check_paid(driver: uc.Chrome, schedule_id: int, facility_id: int) -> Optional[list[date]]:
    """
    Calls the AIS appointment days API using the browser's authenticated session.
    We inject a fetch() call into the page via JavaScript so the browser sends
    all the right cookies and headers automatically — no manual cookie extraction needed.
    """
    api_url = (
        f"{BASE_URL}/niv/schedule/{schedule_id}/appointment/"
        f"days/{facility_id}.json?appointments[expedite]=false"
    )

    # Navigate to the appointment page first so Referer header is correct
    appt_page = f"{BASE_URL}/niv/schedule/{schedule_id}/appointment"
    log.debug(f"[PAID] Loading appointment page: {appt_page}")
    driver.get(appt_page)
    time.sleep(2)

    log.debug(f"[PAID] Calling API: {api_url}")

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

    # Convert strings to date objects
    available = []
    for entry in data:
        if entry.get("business_day"):
            try:
                d = datetime.strptime(entry["date"], "%Y-%m-%d").date()
                available.append(d)
            except (ValueError, TypeError):
                continue
    
    if not available:
        log.info("[PAID] No business-day slots available.")
        return None

    available.sort()
    log.info(f"[PAID] Available dates: {available}")
    return available


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="US Visa Slot Checker — Ethiopia")
    parser.add_argument("--mode", choices=["unpaid", "paid"], required=True)
    parser.add_argument("--current-date", required=False, default=None,
                        help="Your current appointment date YYYY-MM-DD (only for paid mode — "
                             "alerts when an earlier slot is found)")
    parser.add_argument("--schedule-id", type=int, default=None,
                        help="Schedule ID (priority: flag → SCHEDULE_ID env).")
    parser.add_argument("--facility-id", type=int, default=None,
                        help="Consulate facility ID for paid mode (priority: flag → FACILITY_ID env). "
                             "Find it by inspecting the location dropdown on the AIS reschedule page.")
    parser.add_argument("--interval", type=int, default=CHECK_INTERVAL,
                        help=f"Seconds between checks (default: {CHECK_INTERVAL})")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO",
                        help="Log level (default: INFO)")
    parser.add_argument("--no-headless", action="store_true",
                        help="Show the browser window (useful for debugging login)")
    args = parser.parse_args()

    # Configure logging with the specified level
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("visa_checker.log", mode="w"),
        ],
    )

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

    # --- LOGIN ---
    log.info("Logging in...")
    if not login(driver, AIS_EMAIL, AIS_PASSWORD):
        driver.quit()
        sys.exit(1)

    # --- RESOLVE SCHEDULE ID: flag → env ---
    schedule_id = args.schedule_id or (int(os.getenv("SCHEDULE_ID", "0")) or None)
    if not schedule_id:
        log.error(
            "Schedule ID is required.\n"
            "Options: --schedule-id XXXXXXXX  |  SCHEDULE_ID=XXXXXXXX in .env"
        )
        driver.quit()
        sys.exit(1)
    log.debug(f"Using schedule ID: {schedule_id}")

    # --- RESOLVE FACILITY ID: flag → env → error (paid mode only) ---
    facility_id = None
    if args.mode == "paid":
        facility_id = args.facility_id or FACILITY_ID or None
        if not facility_id:
            log.error(
                "Facility ID is required for paid mode.\n"
                "Options: --facility-id XXXXX  |  FACILITY_ID=XXXXX in .env\n"
                "Find it by inspecting the location dropdown on the AIS reschedule page."
            )
            driver.quit()
            sys.exit(1)
        log.debug(f"Using facility ID: {facility_id}")

    # In-memory dedupe only (avoid repeat SMS each cycle for the same earliest date)
    last_unpaid_alerted: Optional[date] = None
    last_paid_earliest_alerted: Optional[date] = None

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
                earliest_date = check_unpaid(driver, schedule_id)

                if earliest_date:
                    if earliest_date != last_unpaid_alerted:
                        readable_date = earliest_date.strftime("%B %d, %Y")
                        message = (
                            f"🚨 VISA APPOINTMENT AVAILABLE — Ethiopia\n"
                            f"Earliest available: {readable_date}\n"
                            f"Book now → {BASE_URL}/niv/schedule/{schedule_id}/payment"
                        )
                        log.info(f"NEW DATE! {readable_date}")
                        send_sms(message)
                        last_unpaid_alerted = earliest_date
                    else:
                        log.debug(f"Date unchanged: {earliest_date}")
                else:
                    log.debug("No date found this cycle.")

            else:
                available = check_paid(driver, schedule_id, facility_id)

                earliest_date: Optional[date] = None
                if available:
                    slots = list(available)
                    if current_date:
                        slots = [d for d in available if d < current_date]
                        if not slots:
                            log.info(
                                "No slots earlier than %s. Earliest overall: %s",
                                current_date,
                                available[0],
                            )
                        else:
                            earliest_date = slots[0]
                    else:
                        earliest_date = available[0]

                if earliest_date:
                    if earliest_date != last_paid_earliest_alerted:
                        readable_date = earliest_date.strftime("%B %d, %Y")
                        message = (
                            f"🚨 VISA SLOTS AVAILABLE — Ethiopia\n"
                            f"Earliest available: {readable_date}\n"
                            f"Book now → {BASE_URL}/niv/schedule/{schedule_id}/appointment"
                        )
                        log.info(f"ALERT! Earliest qualifying slot: {readable_date}")
                        send_sms(message)
                        last_paid_earliest_alerted = earliest_date
                    else:
                        log.debug(f"Earliest unchanged: {earliest_date}")
                elif not available:
                    log.debug("No available slots this cycle.")

        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}")

        log.debug(f"Sleeping {args.interval}s...\\n")
        time.sleep(args.interval)

    driver.quit()


if __name__ == "__main__":
    main()