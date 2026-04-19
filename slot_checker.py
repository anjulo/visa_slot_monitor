import json
import logging
import re
from datetime import date, datetime
from typing import Optional

import undetected_chromedriver as uc

from browser_session import navigate
from config import CONFIG

log = logging.getLogger(__name__)

# credentials:"include" tells the browser to send the _yatri_session cookie —
# a plain requests.get can't access that cookie since it lives in the browser jar
_JS_FETCH = """
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
"""


def _api_get(driver: uc.Chrome, url: str) -> Optional[dict | list]:
    """Fetch JSON from an AIS API endpoint using the browser's authenticated session."""
    try:
        result = driver.execute_async_script(_JS_FETCH, url)
    except Exception as exc:
        log.error("JS fetch error (%s): %s", url, exc)
        return None
    if not result or not isinstance(result, str):
        log.warning("Empty response from %s", url)
        return None
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        log.warning("Non-JSON response from %s: %s", url, result[:200])
        return None


def check_slots(driver: uc.Chrome, schedule_id: int, facility_id: Optional[int]) -> tuple[list[tuple[date, int]], bool]:
    """
    Navigate to the appointment page and return (slots, fee_paid).
    Each slot is (date, available_time_count).
    fee_paid=False means the MRV fee hasn't been paid; the AIS site redirects to /payment in that case.
    """
    navigate(driver, f"{CONFIG.base_url}/niv/schedule/{schedule_id}/appointment", wait_seconds=2)

    if "payment" in driver.current_url:
        log.debug("MRV Fee not paid — reading earliest date from page")
        d = _scrape_earliest_from_page(driver)
        return ([(d, 0)] if d else []), False

    log.debug("MRV Fee already paid — fetching available dates via API")
    return _fetch_available_dates(driver, schedule_id, facility_id), True


def _scrape_earliest_from_page(driver: uc.Chrome) -> Optional[date]:
    """
    Scrape the earliest available date from the current page HTML.
    Used when the MRV fee hasn't been paid; the API endpoint is inaccessible in that state.
    """
    page = driver.page_source

    match = re.search(r"([A-Za-z]+ \d{1,2}, \d{4})", page) # look for something like "March 15, 2026"
    if match:
        raw = match.group(1)
        try:
            parsed = datetime.strptime(raw, "%B %d, %Y").date()
            log.debug("Found date on page: %s", parsed)
            return parsed
        except ValueError:
            pass

    log.warning("Could not find date on page. Saving to unpaid_debug.html for inspection.")
    with open("unpaid_debug.html", "w", encoding="utf-8") as handle:
        handle.write(page)
    return None



def _fetch_available_dates(driver: uc.Chrome, schedule_id: int, facility_id: int) -> list[tuple[date, int]]:
    """
    Call the AIS days API and return the 5 earliest dates with their available time slot counts.
    Uses browser JS fetch to carry the authenticated session cookie.
    """
    # appointments[expedite]=false is required; omitting it causes an API error
    days_url = (
        f"{CONFIG.base_url}/niv/schedule/{schedule_id}/appointment/"
        f"days/{facility_id}.json?appointments[expedite]=false"
    )

    data = _api_get(driver, days_url)
    if not isinstance(data, list) or not data:
        log.debug("No available dates returned by API.")
        return []

    available = []
    for entry in data:
        try:
            available.append(datetime.strptime(entry["date"], "%Y-%m-%d").date())
        except (ValueError, TypeError, KeyError):
            continue

    if not available:
        log.debug("No slots available.")
        return []

    available.sort()
    top = available[:5]
    log.debug("Found %d available date(s), showing earliest 5: %s", len(available), top)

    return [(d, _count_times(driver, schedule_id, facility_id, d)) for d in top]


def _count_times(driver: uc.Chrome, schedule_id: int, facility_id: int, d: date) -> int:
    """Return the number of available appointment times for a given date."""
    times_url = (
        f"{CONFIG.base_url}/niv/schedule/{schedule_id}/appointment/"
        f"times/{facility_id}.json?date={d.isoformat()}&appointments[expedite]=false"
    )
    data = _api_get(driver, times_url)
    if not isinstance(data, dict):
        return 0
    count = len(data.get("available_times", []))
    log.debug("Times for %s: %d available", d, count)
    return count
