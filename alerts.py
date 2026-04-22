import logging
from datetime import date, datetime
from typing import Optional

from config import CONFIG
from telegram_bot import send_telegram

log = logging.getLogger(__name__)

Slots = list[tuple[date, int]]  # (date, available_time_count)

_SEP = "─" * 18


def _is_nighttime() -> bool:
    """Return True if the current local time is between 20:00 and 09:00."""
    return datetime.now().hour >= 20 or datetime.now().hour < 9


def _detect_change(
    new_slots: Slots,
    last_slots: Optional[Slots],
) -> tuple[bool, bool, str]:
    """Return (should_send, dates_changed, log_msg)."""
    new_dates = frozenset(d for d, _ in new_slots)
    last_dates = frozenset(d for d, _ in last_slots) if last_slots is not None else None

    if last_dates is not None and new_dates == last_dates:
        last_counts = {d: n for d, n in last_slots}
        any_decrease = any(n < last_counts.get(d, 0) for d, n in new_slots)
        if not any_decrease:
            msg = "Slots unchanged: " + ", ".join(str(d) for d, _ in new_slots) if new_slots else ""
            return False, False, msg

    dates_changed = last_dates is not None and new_dates != last_dates
    new_earliest = new_slots[0][0] if new_slots else None
    last_earliest = last_slots[0][0] if last_slots else None

    if new_earliest and dates_changed and last_earliest:
        direction = "earlier" if new_earliest < last_earliest else "later"
        msg = f"Slot moved {direction}: {last_earliest} → {new_earliest}"
    elif new_earliest and not dates_changed:
        msg = "Slot counts decreased: " + ", ".join(f"{d}({n})" for d, n in new_slots)
    elif new_earliest:
        msg = "New slots available: " + ", ".join(str(d) for d, _ in new_slots)
    else:
        msg = ""

    return True, dates_changed, msg


def _format_slots(
    slots: Slots,
    last_slots: Optional[Slots] = None,
    dates_changed: bool = False,
    current_date: Optional[date] = None,
) -> str:
    last_counts = {d: n for d, n in last_slots} if last_slots else {}
    lines = []
    for i, (d, count) in enumerate(slots, 1):
        slot_str = f"{count} slot{'s' if count != 1 else ''}" if count else "slots unknown"
        if count and not dates_changed and d in last_counts and count < last_counts[d]:
            slot_str += f" (was {last_counts[d]})"
        lines.append(f"{i}. {d.strftime('%A, %B %d')} · {slot_str}")
    if current_date:
        lines.append(f"{len(slots) + 1}. {current_date.strftime('%A, %B %d')} · ← your appt")
    return "\n".join(lines)


def _build_alert(
    new_slots: Slots,
    last_slots: Optional[Slots],
    current_date: Optional[date],
    fee_paid: bool,
    schedule_id: int,
    dates_changed: bool,
) -> str:
    new_earliest = new_slots[0][0]
    last_earliest = last_slots[0][0] if last_slots else None

    if last_earliest and new_earliest < last_earliest:
        header = f"🟢 Earlier:  {last_earliest.strftime('%b %d')}  →  {new_earliest.strftime('%b %d')}"
    elif last_earliest and new_earliest >= last_earliest:
        header = f"🔴 Later:  {last_earliest.strftime('%b %d')}  →  {new_earliest.strftime('%b %d')}"
    elif current_date:
        days_earlier = (current_date - new_earliest).days
        header = f"🟢 {days_earlier} days earlier than your appointment"
    elif not dates_changed:
        header = "🔴 Slots filling up"
    else:
        header = "🆕 New slots found"

    appointment_url = f"{CONFIG.base_url}/niv/schedule/{schedule_id}/appointment"
    footer_lines = []
    if not fee_paid:
        footer_lines.append(f"💳 Pay → {CONFIG.base_url}/niv/schedule/{schedule_id}/payment")
    footer_lines.append(f"📅 Book → {appointment_url}")

    slot_block = _format_slots(new_slots, last_slots, dates_changed, current_date)

    return "\n".join([
        "🚨 US Visa Slot — Ethiopia",
        "",
        header,
        _SEP,
        slot_block,
        _SEP,
        "\n".join(footer_lines),
    ])


def alert_if_changed(
    new_slots: Slots,
    last_slots: Optional[Slots],
    fee_paid: bool,
    schedule_id: int,
    current_date: Optional[date] = None,
) -> Optional[Slots]:
    """Compare new_slots to last_slots, send a Telegram alert on date changes, and return the latest value."""
    all_available_earliest = new_slots[0][0] if new_slots else None
    if current_date:
        new_slots = [(d, n) for d, n in new_slots if d < current_date]

    should_send, dates_changed, log_msg = _detect_change(new_slots, last_slots)

    if not should_send:
        if log_msg:
            log.info(log_msg)
        return last_slots

    new_earliest = new_slots[0][0] if new_slots else None

    if log_msg:
        log.info(log_msg)
    elif current_date and all_available_earliest:
        log.warning("No slots earlier than appointment (%s) — earliest available: %s", current_date, all_available_earliest)
    else:
        log.warning("No appointments available")

    if new_earliest:
        body = _build_alert(new_slots, last_slots, current_date, fee_paid, schedule_id, dates_changed)
        send_telegram(body)
        if _is_nighttime() and CONFIG.night_ping_targets:
            for target in CONFIG.night_ping_targets:
                send_telegram(body, chat_id=target)

    return new_slots or None
