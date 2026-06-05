#!/usr/bin/env python3.11
"""
US Visa Appointment Slot Checker — Ethiopia (AIS)
Monitors ais.usvisa-info.com and posts to a Telegram channel when slots change.

See README.md for full setup and usage instructions.
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime
from typing import Optional

from alerts import Slots, alert_if_changed
from telegram_bot import get_interval, is_paused, set_cutoffs, set_interval, set_start_time, start_command_listener, update_bot_state
from browser_session import login, make_driver, restart_driver
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
        "--earliest",
        required=False,
        default=None,
        metavar="YYYY-MM-DD",
        help="Ignore slots before this date (lower bound, inclusive)",
    )
    parser.add_argument(
        "--latest",
        required=False,
        default=None,
        metavar="YYYY-MM-DD",
        help="Ignore slots on or after this date (upper bound, exclusive — e.g. your current appointment)",
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

    # mode="w" — each run's log is self-contained; no rotation needed
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            # logging.StreamHandler(sys.stdout),
            logging.FileHandler(f"visa_slot_monitor_{datetime.now().strftime('%Y%m%d%H%M%S')}.log", mode="w"),
        ],
    )

    def _parse_date(val: str, flag: str) -> date:
        try:
            return datetime.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            log.error("Invalid %s. Use YYYY-MM-DD format.", flag)
            sys.exit(1)

    earliest_cutoff: Optional[date] = _parse_date(args.earliest, "--earliest") if args.earliest else None
    latest_cutoff: Optional[date] = _parse_date(args.latest, "--latest") if args.latest else None

    log.info("=" * 60)
    log.info("  US Visa Slot Checker — Ethiopia (AIS)")
    if earliest_cutoff:
        log.info("  Earliest      : %s (ignore before)", earliest_cutoff)
    if latest_cutoff:
        log.info("  Latest        : %s (ignore on/after)", latest_cutoff)
    log.info("  Check every   : %ss", args.interval)
    log.info("  Telegram channel: %s", CONFIG.telegram_channel_id)
    if CONFIG.night_ping_targets:
        log.info("  Night pings   : %s", ", ".join(CONFIG.night_ping_targets))
    log.info("=" * 60)

    set_start_time()
    set_interval(args.interval)
    set_cutoffs(earliest_cutoff, latest_cutoff)
    cmd_thread = start_command_listener()
    log.info("Telegram command listener started (thread: %s)", cmd_thread.name)

    driver = make_driver(headless=not args.no_headless)
    facility_id = CONFIG.facility_id or None
    last_alerted: Optional[Slots] = None
    first_run = True

    while True:
        if is_paused():
            time.sleep(30)
            continue

        try:
            current_url = driver.current_url

            # AIS silently redirects to the login page on session expiry — no error page
            if first_run or "sign_in" in current_url:
                if first_run:
                    log.info("Logging in...")
                else:
                    log.warning("Session expired. Re-logging in...")
                first_run = False
                if not login(driver, CONFIG.ais_email, CONFIG.ais_password):
                    log.error("Login failed. Retrying in 60s.")
                    time.sleep(60)
                    continue

            slots, fee_paid = check_slots(driver, CONFIG.schedule_id, facility_id)

            if fee_paid and not facility_id:
                _die("FACILITY_ID is required in .env when MRV fee is already paid", driver)

            last_alerted = alert_if_changed(slots, last_alerted, fee_paid, CONFIG.schedule_id, earliest_cutoff, latest_cutoff)
            update_bot_state(datetime.now(), fee_paid, slots)

        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as exc:
            log.error("Unexpected error: %s", exc)
            if "no such window" in str(exc).lower() or "invalid session" in str(exc).lower():
                log.warning("Browser window lost — restarting Chrome...")
                driver = restart_driver(driver, headless=not args.no_headless)
                first_run = True
            time.sleep(15)
            continue

        log.info("Sleeping %ss...\n", get_interval())
        time.sleep(get_interval())

    driver.quit()


if __name__ == "__main__":
    main()
