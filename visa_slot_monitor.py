#!/usr/bin/env python3.11
"""
US Visa Appointment Slot Checker — Ethiopia (AIS)
Monitors ais.usvisa-info.com and sends a Telegram message when an earlier slot appears.

See README.md for full setup and usage instructions.
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime
from typing import Optional

from alerts_and_state import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, alert_if_changed, load_earliest
from browser_session import (
    AIS_EMAIL,
    AIS_PASSWORD,
    CHECK_INTERVAL,
    FACILITY_ID,
    SCHEDULE_ID,
    login,
    make_driver,
    resolve_id,
)
from slot_checker import check_slots

log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="US Visa Slot Checker — Ethiopia")
    parser.add_argument(
        "--current-date",
        required=False,
        default=None,
        help="Your current appointment date YYYY-MM-DD (only for paid mode — alerts when an earlier slot is found)",
    )
    parser.add_argument(
        "--schedule-id",
        type=int,
        default=None,
        help="Schedule ID (priority: flag -> SCHEDULE_ID env).",
    )
    parser.add_argument(
        "--facility-id",
        type=int,
        default=None,
        help="Consulate facility ID for paid mode (priority: flag -> FACILITY_ID env). "
        "Find it by inspecting the location dropdown on the AIS reschedule page.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=CHECK_INTERVAL,
        help=f"Seconds between checks (default: {CHECK_INTERVAL})",
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
            log.error("Invalid --current-date. Use YYYY-MM-DD format.")
            sys.exit(1)

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")
        sys.exit(1)

    log.info("=" * 60)
    log.info("  US Visa Slot Checker — Ethiopia (AIS)")
    if current_date:
        log.info("  Current appt  : %s", current_date)
        log.info("  Alert if      : earlier than %s", current_date)
    log.info("  Check every   : %ss", args.interval)
    log.info("  Telegram chat : %s", TELEGRAM_CHAT_ID)
    log.info("=" * 60)

    driver = make_driver(headless=not args.no_headless)

    log.info("Logging in...")
    if not login(driver, AIS_EMAIL, AIS_PASSWORD):
        driver.quit()
        sys.exit(1)

    schedule_id = resolve_id(args.schedule_id, SCHEDULE_ID, "Schedule ID", driver=driver)
    facility_id = args.facility_id or FACILITY_ID or None

    last_alerted = load_earliest("slot")
    if last_alerted:
        log.info("Restored persisted earliest: %s", last_alerted)

    while True:
        try:
            if "sign_in" in driver.current_url:
                log.warning("Session expired. Re-logging in...")
                if not login(driver, AIS_EMAIL, AIS_PASSWORD):
                    log.error("Re-login failed. Retrying in 60s.")
                    time.sleep(60)
                    continue

            earliest_date, detected_mode = check_slots(driver, schedule_id, facility_id)

            if detected_mode == "paid" and earliest_date and current_date and earliest_date >= current_date:
                log.info("No slots earlier than %s. Earliest overall: %s", current_date, earliest_date)
                earliest_date = None

            last_alerted = alert_if_changed(
                earliest_date,
                last_alerted,
                detected_mode,
                schedule_id,
                current_date,
            )

            if detected_mode == "paid" and not earliest_date:
                log.debug("No available slots this cycle.")
        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as exc:
            log.error("Unexpected error: %s", exc)

        log.debug("Sleeping %ss...\n", args.interval)
        time.sleep(args.interval)

    driver.quit()


if __name__ == "__main__":
    main()
