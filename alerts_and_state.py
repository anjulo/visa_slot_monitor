import logging
from datetime import date, datetime
from typing import Optional

import requests

from config import CONFIG

log = logging.getLogger(__name__)

Slots = list[tuple[date, int]]  # (date, available_time_count)


def send_telegram(body: str, chat_id: str = None) -> None:
    """Send a Telegram message to chat_id (defaults to the configured channel)."""
    url = f"https://api.telegram.org/bot{CONFIG.telegram_bot_token}/sendMessage"
    target = chat_id or CONFIG.telegram_channel_id
    try:
        response = requests.post(
            url, json={"chat_id": target, "text": body}, timeout=10
        )
        response.raise_for_status()
        log.info("Telegram sent to %s — message_id: %s", target, response.json()["result"]["message_id"])
    except Exception as exc:
        log.error("Telegram send failed to %s: %s", target, exc)


def _is_nighttime() -> bool:
    """Return True if the current local time is between 23:00 and 06:00."""
    return datetime.now().hour >= 23 or datetime.now().hour < 8


def _format_slots(slots: Slots, current_date: Optional[date] = None) -> str:
    """Format available dates as a numbered list with time slot counts and days-until context."""
    lines = []
    for i, (d, count) in enumerate(slots, 1):
        days_until = (d - date.today()).days
        extra = f" · {(current_date - d).days} days earlier" if current_date else ""
        slot_str = f"{count} slot{'s' if count != 1 else ''}" if count else "slots unknown"
        lines.append(f"{i}. {d.strftime('%A, %B %d')} (in {days_until} days{extra}) — {slot_str}")
    return "\n".join(lines)


def alert_if_changed(
    new_slots: Slots,
    last_slots: Optional[Slots],
    fee_paid: bool,
    schedule_id: int,
    current_date: Optional[date] = None,
) -> Optional[Slots]:
    """Compare new_slots to last_slots, send a Telegram alert on changes, and return the latest value."""
    new_dates = frozenset(d for d, _ in new_slots)
    last_dates = frozenset(d for d, _ in last_slots) if last_slots is not None else None

    # Only fire on state changes; polling every few minutes would spam the channel otherwise
    if last_dates is not None and new_dates == last_dates:
        if new_slots:
            log.debug("Slots unchanged: %s", sorted(new_dates))
        return last_slots

    new_earliest = new_slots[0][0] if new_slots else None
    last_earliest = last_slots[0][0] if last_slots else None

    # Log the change in slot availability
    if new_earliest and last_earliest:
        direction = "earlier 🟢" if new_earliest < last_earliest else "later 🔴"
        log.info("Slot moved %s: %s → %s", direction, last_earliest, new_earliest)
    elif new_earliest:
        log.info("New slot available: %s", new_earliest)
    else:
        log.info("Slots disappeared — no appointments showing")

    # Build and send the Telegram message on availability changes
    if new_slots:
        movement = ""
        if last_earliest:
            movement = (
                f"🟢 Moved earlier from {last_earliest.strftime('%b %d')}!\n"
                if new_earliest < last_earliest
                else f"🔴 Moved later from {last_earliest.strftime('%b %d')}.\n"
            )

        appointment_url = f"{CONFIG.base_url}/niv/schedule/{schedule_id}/appointment"
        action_links = (
            f"💳 Pay fee → {CONFIG.base_url}/niv/schedule/{schedule_id}/payment\n"
            f"📅 Book appt → {appointment_url}"
            if not fee_paid
            else f"📅 Book now → {appointment_url}"
        )
        body = (
            f"🚨 VISA APPOINTMENT — Ethiopia\n"
            f"{movement}"
            f"\n{_format_slots(new_slots, current_date)}\n\n"
            + action_links
        )
        send_telegram(body)
        if _is_nighttime() and CONFIG.night_ping_targets:
            for target in CONFIG.night_ping_targets:
                send_telegram(body, chat_id=target)

    return new_slots if new_slots else None
