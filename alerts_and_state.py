import logging
from datetime import date
from typing import Optional

import requests

from config import CONFIG

log = logging.getLogger(__name__)


def send_telegram(body: str) -> None:
    url = f"https://api.telegram.org/bot{CONFIG.telegram_bot_token}/sendMessage"
    try:
        response = requests.post(
            url, json={"chat_id": CONFIG.telegram_channel_id, "text": body}, timeout=10
        )
        response.raise_for_status()
        log.info("Telegram message sent — message_id: %s", response.json()["result"]["message_id"])
    except Exception as exc:
        log.error("Telegram send failed: %s", exc)


def format_date(d: date, current_date: Optional[date] = None) -> str:
    """
    Return a human-readable date string with contextual info.
    """
    parts = [d.strftime("%A, %B %d, %Y"), f"in {(d - date.today()).days} days"]
    if current_date:
        parts.append(f"{(current_date - d).days} days earlier than your appointment")
    return f"{parts[0]}  ({' · '.join(parts[1:])})"


def alert_if_changed(
    new_val: Optional[date],
    last_val: Optional[date],
    mode: str,
    schedule_id: int,
    current_date: Optional[date] = None,
) -> Optional[date]:
    """
    Compare new_val to last_val, alert on changes, and return the latest value.
    """
    if new_val == last_val:
        if new_val:
            log.debug("Earliest slot unchanged: %s", new_val)
        return last_val

    if new_val and last_val:
        log.info(
            "ALERT! Earliest slot moved %s: %s → %s",
            "earlier 🟢" if new_val < last_val else "later 🔴",
            last_val,
            new_val,
        )
    elif new_val:
        log.info("ALERT! Earliest slot first seen: %s", new_val)
    else:
        log.info("Earliest slot disappeared — no slots available")

    if new_val:
        movement = (
            f"🟢 Moved earlier from {last_val.strftime('%b %d')}!\n"
            if last_val and new_val < last_val
            else f"🔴 Moved later from {last_val.strftime('%b %d')}.\n"
            if last_val
            else ""
        )
        appointment_url = f"{CONFIG.base_url}/niv/schedule/{schedule_id}/appointment"
        action_links = (
            f"💳 Pay fee → {CONFIG.base_url}/niv/schedule/{schedule_id}/payment\n"
            f"📅 Book appt → {appointment_url}"
            if mode == "unpaid"
            else f"📅 Book now → {appointment_url}"
        )
        send_telegram(
            f"🚨 VISA APPOINTMENT — Ethiopia\n"
            f"{movement}"
            f"{format_date(new_val, current_date)}\n\n"
            + action_links
        )

    return new_val
