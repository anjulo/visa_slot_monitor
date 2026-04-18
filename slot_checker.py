import json
import logging
import re
from datetime import date, datetime
from typing import Optional

import undetected_chromedriver as uc

from browser_session import navigate
from config import CONFIG

log = logging.getLogger(__name__)


def check_slots(driver: uc.Chrome, schedule_id: int, facility_id: Optional[int]) -> tuple[Optional[date], str]:
    """
    Navigate to the appointment page and return (earliest_date, detected_mode).
    detected_mode is 'unpaid' if redirected to /payment, 'paid' otherwise.
    """
    navigate(driver, f"{CONFIG.base_url}/niv/schedule/{schedule_id}/appointment", wait_seconds=2)

    if "payment" in driver.current_url:
        log.info("[AUTO] Redirected to payment page — fee not paid yet")
        return _scrape_earliest_from_page(driver), "unpaid"

    log.info("[AUTO] On appointment page — fee paid")
    return _fetch_paid_slots(driver, schedule_id, facility_id), "paid"


def _scrape_earliest_from_page(driver: uc.Chrome) -> Optional[date]:
    """
    Scrape the earliest available appointment date from the current page source.
    Used when the account has not paid the fee yet.
    """
    page = driver.page_source

    patterns = [
        r"(\d{1,2}\s+\w+,?\s*\d{4})",
        r"(?:earliest|first available|available appointment)[^\d]*(\w+ \d{1,2},?\s*\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ]

    for pattern in patterns:
        match = re.search(pattern, page, re.IGNORECASE)
        if match:
            raw = match.group(1).strip()
            parsed = parse_date_flexible(raw)
            if parsed:
                log.debug("[UNPAID] Found date on page: %s -> %s", raw, parsed)
                return parsed

    log.warning("[UNPAID] Could not find date on page. Saving to unpaid_debug.html")
    with open("unpaid_debug.html", "w", encoding="utf-8") as handle:
        handle.write(page)
    log.warning("Open unpaid_debug.html to inspect the page and update the regex pattern.")
    return None


def parse_date_flexible(raw: str) -> Optional[date]:
    """Try multiple date formats and return a date object or None."""
    formats = [
        "%d %B, %Y",
        "%d %B %Y",
        "%B %d, %Y",
        "%B %d %Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _fetch_paid_slots(driver: uc.Chrome, schedule_id: int, facility_id: Optional[int]) -> Optional[date]:
    """
    Call the AIS appointment days API using the browser's authenticated session
    and return the earliest available business-day slot.
    """
    if not facility_id:
        return None

    api_url = (
        f"{CONFIG.base_url}/niv/schedule/{schedule_id}/appointment/"
        f"days/{facility_id}.json?appointments[expedite]=false"
    )

    log.debug("[PAID] Calling API: %s", api_url)

    try:
        result = driver.execute_async_script(
            """
            const [url, callback] = arguments;
            fetch(url, {
                headers: {
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest"
                },
                credentials: "include"
            })
            .then(r => r.text())
            .then(callback)
            .catch(() => callback(null));
            """,
            api_url,
        )
    except Exception as exc:
        log.error("[PAID] JS fetch error: %s", exc)
        return None

    if not result or not isinstance(result, str):
        log.warning("[PAID] Empty or unexpected API response.")
        return None

    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        log.warning("[PAID] Non-JSON response: %s", result[:200])
        return None

    if not isinstance(data, list) or not data:
        log.info("[PAID] No available dates in API response.")
        return None

    available = []
    for entry in data:
        if not entry.get("business_day"):
            continue
        try:
            available.append(datetime.strptime(entry["date"], "%Y-%m-%d").date())
        except (ValueError, TypeError):
            continue

    if not available:
        log.info("[PAID] No business-day slots available.")
        return None

    available.sort()
    log.info("[PAID] Available dates: %s", available)
    return available[0]
