import logging
import threading
import time
from datetime import date, datetime
from typing import Optional

import requests

from config import CONFIG

log = logging.getLogger(__name__)

_SEP = "─" * 18

_state_lock = threading.Lock()
_bot_state: dict = {
    "start_time":       None,
    "last_check_time":  None,
    "fee_paid":         None,
    "slots":            None,
    "paused":           False,
    "interval":         900,
    "earliest_cutoff":  None,
    "latest_cutoff":    None,
}


def send_telegram(body: str, chat_id: str = None) -> None:
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


def set_start_time() -> None:
    with _state_lock:
        _bot_state["start_time"] = datetime.now()


def set_cutoffs(earliest: Optional[date], latest: Optional[date]) -> None:
    with _state_lock:
        _bot_state["earliest_cutoff"] = earliest
        _bot_state["latest_cutoff"] = latest


def set_interval(seconds: int) -> None:
    with _state_lock:
        _bot_state["interval"] = seconds


def get_interval() -> int:
    with _state_lock:
        return _bot_state["interval"]


def is_paused() -> bool:
    with _state_lock:
        return bool(_bot_state["paused"])


def update_bot_state(
    last_check_time: datetime,
    fee_paid: bool,
    slots: Optional[list[tuple[date, int]]],
) -> None:
    with _state_lock:
        _bot_state["last_check_time"] = last_check_time
        _bot_state["fee_paid"] = fee_paid
        _bot_state["slots"] = slots


def start_command_listener() -> threading.Thread:
    t = threading.Thread(target=_poll_loop, name="tg-command-listener", daemon=True)
    t.start()
    return t


def _poll_loop() -> None:
    base = f"https://api.telegram.org/bot{CONFIG.telegram_bot_token}"
    offset = 0
    log.info("[tg-listener] Started, polling for commands...")
    while True:
        try:
            resp = requests.get(
                f"{base}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("[tg-listener] getUpdates error: %s — retrying in 5s", exc)
            time.sleep(5)
            continue
        for update in data.get("result", []):
            offset = update["update_id"] + 1
            _handle_update(update)


def _handle_update(update: dict) -> None:
    message = update.get("message") or update.get("channel_post")
    if not message:
        return
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = (message.get("text") or "").strip()
    if chat_id != str(CONFIG.telegram_channel_id):
        log.debug("[tg-listener] Ignoring message from unknown chat %s", chat_id)
        return

    cmd = text.split()[0].split("@")[0] if text else ""
    log.info("[tg-listener] %s from %s", cmd, chat_id)

    if cmd == "/status":
        with _state_lock:
            reply = _build_status_reply()
        send_telegram(reply, chat_id=chat_id)

    elif cmd == "/slots":
        with _state_lock:
            reply = _build_slots_reply()
        send_telegram(reply, chat_id=chat_id)

    elif cmd == "/pause":
        with _state_lock:
            _bot_state["paused"] = True
        send_telegram("⏸ Monitoring paused — send /resume to restart.", chat_id=chat_id)

    elif cmd == "/resume":
        with _state_lock:
            _bot_state["paused"] = False
        send_telegram("▶️ Monitoring resumed.", chat_id=chat_id)

    elif cmd == "/interval":
        parts = text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            send_telegram("Usage: /interval <minutes> (minimum 5)", chat_id=chat_id)
            return
        minutes = int(parts[1])
        if minutes < 5:
            send_telegram("⚠️ Minimum interval is 5 minutes.", chat_id=chat_id)
            return
        with _state_lock:
            _bot_state["interval"] = minutes * 60
        send_telegram(f"✅ Check interval set to {minutes} minutes.", chat_id=chat_id)

    elif cmd == "/help":
        send_telegram(
            "Commands:\n"
            "/status — uptime, last check, current slots\n"
            "/slots — all available dates (ignores cutoffs)\n"
            "/pause — pause monitoring\n"
            "/resume — resume monitoring\n"
            "/interval <min> — set check interval (min 5)\n"
            "/help — this message",
            chat_id=chat_id,
        )


def _build_slots_reply() -> str:
    slots = _bot_state["slots"]
    last  = _bot_state["last_check_time"]
    last_str = last.strftime("%-I:%M %p") if last else "not yet run"
    if slots:
        slot_lines = "\n".join(
            f"  • {d.strftime('%b %d, %Y')} — {n} slot{'s' if n != 1 else ''}"
            for d, n in slots
        )
    else:
        slot_lines = "  none found"
    return f"📅 Slots as of {last_str}:\n{slot_lines}"




def _build_status_reply() -> str:
    from datetime import timedelta
    start           = _bot_state["start_time"]
    last            = _bot_state["last_check_time"]
    paid            = _bot_state["fee_paid"]
    slots           = _bot_state["slots"]
    paused          = _bot_state["paused"]
    interval        = _bot_state["interval"]
    earliest_cutoff = _bot_state["earliest_cutoff"]
    latest_cutoff   = _bot_state["latest_cutoff"]

    now          = datetime.now()
    status_str   = "⏸ paused" if paused else "▶️ running"
    start_str    = start.strftime("%-I:%M %p, %b %d") if start else "unknown"
    fee_str      = ("✅ paid" if paid else "❌ not paid") if paid is not None else "unknown"
    interval_str = f"{interval // 60} min" if interval else "unknown"
    earliest_str = earliest_cutoff.strftime("%b %d, %Y") if earliest_cutoff else "not set"
    latest_str   = latest_cutoff.strftime("%b %d, %Y") if latest_cutoff else "not set"

    if start:
        delta   = now - start
        h, rem  = divmod(int(delta.total_seconds()), 3600)
        uptime_str = f"{h}h {rem // 60}m"
    else:
        uptime_str = "unknown"

    if last and not paused:
        next_check = last + timedelta(seconds=interval)
        next_str = next_check.strftime("%-I:%M %p") if next_check > now else "soon"
    elif paused:
        next_str = "paused"
    else:
        next_str = "soon"

    last_str = last.strftime("%-I:%M %p, %b %d") if last else "not yet run"

    filtered = [
        (d, n) for d, n in (slots or [])
        if (not earliest_cutoff or d >= earliest_cutoff)
        and (not latest_cutoff or d < latest_cutoff)
    ]
    if filtered:
        slot_lines = "\n".join(
            f"  • {d.strftime('%b %d, %Y')} — {n} slot{'s' if n != 1 else ''}"
            for d, n in filtered
        )
    else:
        slot_lines = "  none within cutoffs"

    return (
        f"✅ Visa Slot Monitor is alive\n"
        f"{_SEP}\n"
        f"Status:      {status_str}\n"
        f"Uptime:      {uptime_str}\n"
        f"Started:     {start_str}\n"
        f"Last check:  {last_str}\n"
        f"Next check:  {next_str}\n"
        f"Interval:    {interval_str}\n"
        f"MRV fee:     {fee_str}\n"
        f"Earliest:    {earliest_str}\n"
        f"Latest:      {latest_str}\n"
        f"{_SEP}\n"
        f"Current slots:\n{slot_lines}"
    )
