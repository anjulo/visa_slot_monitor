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
    "start_time":      None,
    "last_check_time": None,
    "fee_paid":        None,
    "slots":           None,
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
    log.info("[tg-listener] Started, polling for /status commands...")
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
    if text == "/status" or text.startswith("/status@"):
        log.info("[tg-listener] /status requested from chat %s", chat_id)
        with _state_lock:
            reply = _build_status_reply()
        send_telegram(reply, chat_id=chat_id)


def _build_status_reply() -> str:
    start = _bot_state["start_time"]
    last  = _bot_state["last_check_time"]
    paid  = _bot_state["fee_paid"]
    slots = _bot_state["slots"]

    start_str = start.strftime("%-I:%M %p, %b %d") if start else "unknown"
    last_str  = last.strftime("%-I:%M %p, %b %d")  if last  else "not yet run"
    fee_str   = ("✅ paid" if paid else "❌ not paid") if paid is not None else "unknown"

    if slots:
        slot_lines = "\n".join(
            f"  • {d.strftime('%b %d, %Y')} — {n} slot{'s' if n != 1 else ''}"
            for d, n in slots
        )
    else:
        slot_lines = "  none found"

    return (
        f"✅ Visa Slot Monitor is alive\n"
        f"{_SEP}\n"
        f"Started:     {start_str}\n"
        f"Last check:  {last_str}\n"
        f"MRV fee:     {fee_str}\n"
        f"{_SEP}\n"
        f"Current slots:\n{slot_lines}"
    )
