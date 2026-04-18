#!/usr/bin/env python3.11
"""
US Visa Appointment Slot Checker — Ethiopia (AIS)
Monitors ais.usvisa-info.com and sends a Telegram message when an earlier slot appears.

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

import requests
import undetected_chromedriver as uc
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

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

# Schedule ID — priority: --schedule-id flag → this env var → error
# Useful to set when your account has multiple groups.
SCHEDULE_ID = int(os.getenv("SCHEDULE_ID", "0"))

# Facility ID for Addis Ababa — required for paid mode.
# Priority: --facility-id flag → FACILITY_ID in .env → error
# Find it by inspecting the location dropdown on the AIS reschedule page:
#   right-click the consulate dropdown → Inspect → <option value="???">Addis Ababa</option>
FACILITY_ID = int(os.getenv("FACILITY_ID", "0"))

# Telegram — https://t.me/BotFather
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# Seconds between checks (don't go below 120 — site will block you)
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))

# ─────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────────

def send_telegram(body: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": body}, timeout=10)
        resp.raise_for_status()
        log.info(f"Telegram message sent — message_id: {resp.json()['result']['message_id']}")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def navigate(driver: uc.Chrome, url: str, wait_seconds: int = 3) -> None:
    """Navigate to a URL and wait for the page to settle."""
    driver.get(url)
    time.sleep(wait_seconds)


def resolve_id(flag_val: Optional[int], env_val: int, name: str,
               required: bool = True, driver: Optional[uc.Chrome] = None) -> Optional[int]:
    """
    Resolves an integer ID using: flag → env → error.
    Quits the driver and exits if required and not found.
    """
    value = flag_val or env_val or None
    if not value and required:
        log.error(f"{name} is required. Pass --{name.lower().replace(' ', '-')} or set it in .env")
        if driver:
            driver.quit()
        sys.exit(1)
    log.debug(f"Using {name}: {value}")
    return value


def format_date(d: date, current_date: Optional[date] = None) -> str:
    """
    Returns a human-readable date string with contextual info:
      Wednesday, August 11, 2026  (in 116 days · 47 days earlier than your appointment)
    """
    days_from_now = (d - date.today()).days
    parts = [d.strftime("%A, %B %d, %Y"), f"in {days_from_now} days"]
    if current_date:
        diff = (current_date - d).days
        parts.append(f"{diff} days earlier than your appointment")
    return f"{parts[0]}  ({' · '.join(parts[1:])})"


EARLIEST_DATE_FILE = "earliest_date.json"


def load_earliest(mode: str) -> Optional[date]:
    """Load the previously recorded earliest date from disk for this mode."""
    try:
        with open(EARLIEST_DATE_FILE) as f:
            data = json.load(f)
        raw = data.get(mode)
        return datetime.strptime(raw, "%Y-%m-%d").date() if raw else None
    except (FileNotFoundError, KeyError, ValueError):
        return None


def save_earliest(mode: str, d: Optional[date]) -> None:
    """Persist the current earliest date to disk for this mode."""
    try:
        try:
            with open(EARLIEST_DATE_FILE) as f:
                data = json.load(f)
        except (FileNotFoundError, ValueError):
            data = {}
        data[mode] = d.isoformat() if d else None
        with open(EARLIEST_DATE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        log.warning(f"Could not save earliest date: {e}")


def alert_if_changed(new_val: Optional[date], last_val: Optional[date], mode: str,
                     schedule_id: int,
                     current_date: Optional[date] = None) -> Optional[date]:
    """
    Compares new_val to last_val (persisted across restarts via disk).
    Alerts with a direction-aware message — 'earlier' (good) or 'later' (worse).
    Returns new_val and saves it to disk if changed.
    """
    if new_val == last_val:
        if new_val:
            log.debug(f"Earliest slot unchanged: {new_val}")
        return last_val

    if new_val and last_val:
        direction = "earlier 🟢" if new_val < last_val else "later 🔴"
        log.info(f"ALERT! Earliest slot moved {direction}: {last_val} → {new_val}")
    elif new_val:
        log.info(f"ALERT! Earliest slot first seen: {new_val}")
    else:
        log.info(f"Earliest slot disappeared — no slots available")

    if new_val:
        direction = (
            f"🟢 Moved earlier from {last_val.strftime('%b %d')}!\n" if last_val and new_val < last_val
            else f"🔴 Moved later from {last_val.strftime('%b %d')}.\n" if last_val
            else ""
        )
        send_telegram(
            f"🚨 VISA APPOINTMENT — Ethiopia\n"
            f"{direction}"
            f"{format_date(new_val, current_date)}\n\n"
            f"Book now → {BASE_URL}/niv/schedule/{schedule_id}/{'payment' if mode == 'unpaid' else 'appointment'}"
        )

    save_earliest(mode, new_val)
    return new_val

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
    navigate(driver, f"{BASE_URL}/niv/schedule/{schedule_id}/payment")

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
# AIS calendar uses. Returns all available dates.
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
    navigate(driver, f"{BASE_URL}/niv/schedule/{schedule_id}/appointment", wait_seconds=2)
    log.debug(f"[PAID] Calling API: {api_url}")

    # Execute fetch() in the browser context — it carries all session cookies
    try:
        result = driver.execute_async_script(
            """
            const [url, callback] = arguments;
            fetch(url, {
                headers: {
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest"
                },
                credentials: "include"
            })
            .then(r => r.text())
            .then(callback)
            .catch(e => callback(null));
            """,
            api_url
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
            logging.FileHandler("visa_slot_monitor.log", mode="w"),
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

    # Validate Telegram credentials early
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")
        sys.exit(1)

    log.info("=" * 60)
    log.info("  US Visa Slot Checker — Ethiopia (AIS)")
    log.info(f"  Mode          : {args.mode.upper()}")
    if current_date:
        log.info(f"  Current appt  : {current_date}")
        log.info(f"  Alert if      : earlier than {current_date}")
    log.info(f"  Check every   : {args.interval}s")
    log.info(f"  Telegram chat : {TELEGRAM_CHAT_ID}")
    log.info("=" * 60)

    headless = not args.no_headless
    driver = make_driver(headless=headless)

    # --- LOGIN ---
    log.info("Logging in...")
    if not login(driver, AIS_EMAIL, AIS_PASSWORD):
        driver.quit()
        sys.exit(1)

    # --- RESOLVE SCHEDULE ID: flag → env → error ---
    schedule_id = resolve_id(args.schedule_id, SCHEDULE_ID, "Schedule ID", driver=driver)

    # --- RESOLVE FACILITY ID: flag → env → error (paid mode only) ---
    facility_id = resolve_id(args.facility_id, FACILITY_ID, "Facility ID",
                             required=(args.mode == "paid"), driver=driver)

    # In-memory dedupe, seeded from disk so restarts don't re-alert the same date
    last_unpaid_alerted: Optional[date] = load_earliest("unpaid")
    last_paid_alerted: Optional[date] = load_earliest("paid")
    if last_unpaid_alerted:
        log.info(f"Restored persisted unpaid earliest: {last_unpaid_alerted}")
    if last_paid_alerted:
        log.info(f"Restored persisted paid earliest: {last_paid_alerted}")

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

            if args.mode == "unpaid":
                earliest_date = check_unpaid(driver, schedule_id)
                last_unpaid_alerted = alert_if_changed(
                    earliest_date,
                    last_unpaid_alerted,
                    "unpaid",
                    schedule_id,
                )

            else:
                available = check_paid(driver, schedule_id, facility_id)

                earliest_date = None
                if available:
                    slots = [d for d in available if d < current_date] if current_date else available
                    if current_date and not slots:
                        log.info(f"No slots earlier than {current_date}. Earliest overall: {available[0]}")
                    else:
                        earliest_date = slots[0]

                last_paid_alerted = alert_if_changed(
                    earliest_date,
                    last_paid_alerted,
                    "paid",
                    schedule_id,
                    current_date,
                )

                if not available:
                    log.debug("No available slots this cycle.")

        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}")

        log.debug(f"Sleeping {args.interval}s...\n")
        time.sleep(args.interval)

    driver.quit()


if __name__ == "__main__":
    main()
