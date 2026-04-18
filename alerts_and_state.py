import json
import logging
import os
from datetime import date, datetime
from typing import Optional

import requests
from dotenv import load_dotenv

from browser_session import BASE_URL

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
EARLIEST_DATE_FILE = "earliest_date.json"

log = logging.getLogger(__name__)


def send_telegram(body: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": body}, timeout=10)
        response.raise_for_status()
        log.info("Telegram message sent — message_id: %s", response.json()["result"]["message_id"])
    except Exception as exc:
        log.error("Telegram send failed: %s", exc)


def format_date(d: date, current_date: Optional[date] = None) -> str:
    """
    Return a human-readable date string with contextual info.
    """
    days_from_now = (d - date.today()).days
    parts = [d.strftime("%A, %B %d, %Y"), f"in {days_from_now} days"]
    if current_date:
        diff = (current_date - d).days
        parts.append(f"{diff} days earlier than your appointment")
    return f"{parts[0]}  ({' · '.join(parts[1:])})"


def load_earliest(mode: str) -> Optional[date]:
    """Load the previously recorded earliest date from disk for this mode."""
    try:
        with open(EARLIEST_DATE_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        raw = data.get(mode)
        return datetime.strptime(raw, "%Y-%m-%d").date() if raw else None
    except (FileNotFoundError, KeyError, ValueError):
        return None


def save_earliest(mode: str, d: Optional[date]) -> None:
    """Persist the current earliest date to disk for this mode."""
    try:
        try:
            with open(EARLIEST_DATE_FILE, encoding="utf-8") as handle:
                data = json.load(handle)
        except (FileNotFoundError, ValueError):
            data = {}

        data[mode] = d.isoformat() if d else None
        with open(EARLIEST_DATE_FILE, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    except Exception as exc:
        log.warning("Could not save earliest date: %s", exc)


def alert_if_changed(
    new_val: Optional[date],
    last_val: Optional[date],
    mode: str,
    schedule_id: int,
    current_date: Optional[date] = None,
) -> Optional[date]:
    """
    Compare new_val to last_val, alert on changes, and persist the new value.
    """
    if new_val == last_val:
        if new_val:
            log.debug("Earliest slot unchanged: %s", new_val)
        return last_val

    if new_val and last_val:
        direction = "earlier 🟢" if new_val < last_val else "later 🔴"
        log.info("ALERT! Earliest slot moved %s: %s → %s", direction, last_val, new_val)
    elif new_val:
        log.info("ALERT! Earliest slot first seen: %s", new_val)
    else:
        log.info("Earliest slot disappeared — no slots available")

    if new_val:
        direction = (
            f"🟢 Moved earlier from {last_val.strftime('%b %d')}!\n"
            if last_val and new_val < last_val
            else f"🔴 Moved later from {last_val.strftime('%b %d')}.\n"
            if last_val
            else ""
        )
        send_telegram(
            f"🚨 VISA APPOINTMENT — Ethiopia\n"
            f"{direction}"
            f"{format_date(new_val, current_date)}\n\n"
            + (
                f"💳 Pay fee → {BASE_URL}/niv/schedule/{schedule_id}/payment\n"
                f"📅 Book appt → {BASE_URL}/niv/schedule/{schedule_id}/appointment"
                if mode == "unpaid"
                else f"📅 Book now → {BASE_URL}/niv/schedule/{schedule_id}/appointment"
            )
        )

    save_earliest("slot", new_val)
    return new_val
