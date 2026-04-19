import logging
import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppConfig:
    base_url: str
    ais_email: str
    ais_password: str
    schedule_id: int
    facility_id: int
    check_interval: int
    telegram_bot_token: str
    telegram_channel_id: str


def _die(message: str) -> None:
    log.error(message)
    sys.exit(1)


def _read_int(name: str, default: str) -> int:
    raw = os.getenv(name, default)
    try:
        return int(raw)
    except ValueError:
        _die(f"{name} must be an integer in .env")


def _build_config() -> AppConfig:
    load_dotenv()
    base_url = "https://ais.usvisa-info.com/en-et"

    cfg = AppConfig(
        base_url=base_url,
        ais_email=os.getenv("AIS_EMAIL", ""),
        ais_password=os.getenv("AIS_PASSWORD", ""),
        schedule_id=_read_int("SCHEDULE_ID", "0"),
        facility_id=_read_int("FACILITY_ID", "0"),
        check_interval=_read_int("CHECK_INTERVAL", "300"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_channel_id=(
            os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
            or os.getenv("TELEGRAM_CHAT_ID", "").strip()
        ),
    )

    if not cfg.telegram_bot_token or not cfg.telegram_channel_id:
        _die(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID must be set in .env "
            "(TELEGRAM_CHAT_ID is still accepted for compatibility)"
        )
    if not cfg.schedule_id:
        _die("SCHEDULE_ID must be set in .env")
    return cfg


CONFIG = _build_config()
