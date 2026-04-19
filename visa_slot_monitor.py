#!/usr/bin/env python3.11
"""
US Visa Appointment Slot Checker — Ethiopia (AIS)
Monitors ais.usvisa-info.com and posts to a Telegram channel when an earlier slot appears.

See README.md for full setup and usage instructions.
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime
from typing import Optional

from alerts_and_state import alert_if_changed
from browser_session import login, make_driver
from config import CONFIG
from slot_checker import check_slots
log = logging.getLogger(__name__)


def _die(message: str, driver=None) -> None:
    log.error(message)
    if driver:
        driver.quit()
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="US Visa Slot Checker — Ethiopia")
    parser.add_argument(
        "--current-date",
        required=False,
        default=None,
        help="Your current appointment date YYYY-MM-DD (only for paid mode — alerts when an earlier slot is found)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=CONFIG.check_interval,
        help=f"Seconds between checks (default: {CONFIG.check_interval})",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log level (default: INFO)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Show the browser window (useful for debugging login)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("visa_slot_monitor.log", mode="w"),
        ],
    )

    current_date: Optional[date] = None
    if args.current_date:
        try:
            current_date = datetime.strptime(args.current_date, "%Y-%m-%d").date()
        except ValueError:
            _die("Invalid --current-date. Use YYYY-MM-DD format.")

    log.info("=" * 60)
    log.info("  US Visa Slot Checker — Ethiopia (AIS)")
    if current_date:
        log.info("  Current appt  : %s", current_date)
        log.info("  Alert if      : earlier than %s", current_date)
    log.info("  Check every   : %ss", args.interval)
    log.info("  Telegram channel: %s", CONFIG.telegram_channel_id)
    log.info("=" * 60)

    driver = make_driver(headless=not args.no_headless)

    facility_id = CONFIG.facility_id or None

    last_alerted: Optional[date] = None

    first_run = True
    while True:
        try:
            if first_run or "sign_in" in driver.current_url:
                log.info("logging in...") if first_run else log.warning("Session expired. Re-logging in...")
                first_run = False
                if not login(driver, CONFIG.ais_email, CONFIG.ais_password):
                    log.error("login failed. Retrying in 60s.")
                    time.sleep(60)
                    continue

            earliest_date, detected_mode = check_slots(driver, CONFIG.schedule_id, facility_id)
            if detected_mode == "paid" and not facility_id:
                _die("FACILITY_ID is required in .env", driver)

            if detected_mode == "paid" and earliest_date and current_date and earliest_date >= current_date:
                log.info("No slots earlier than %s. Earliest overall: %s", current_date, earliest_date)
                earliest_date = None

            last_alerted = alert_if_changed(
                earliest_date,
                last_alerted,
                detected_mode,
                CONFIG.schedule_id,
                current_date,
            )

            if detected_mode == "paid" and not earliest_date:
                log.debug("No available slots this cycle.")
        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as exc:
            log.error("Unexpected error: %s", exc)

        log.info("Sleeping %ss...\n", args.interval)
        time.sleep(args.interval)

    driver.quit()


if __name__ == "__main__":
    main()