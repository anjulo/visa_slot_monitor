import json
import logging
import re
from datetime import date, datetime
import time
from typing import Optional

import undetected_chromedriver as uc

from config import CONFIG

log = logging.getLogger(__name__)

# credentials:"include" tells the browser to send the _yatri_session cookie —
# a plain requests.get can't access that cookie since it lives in the browser jar
_JS_FETCH = """
const [url, callback] = arguments;
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 20000);
fetch(url, {
    signal: controller.signal,
    headers: {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest"
    },
    credentials: "include"
})
.then(r => r.text())
.then(t => { clearTimeout(timer); callback(t); })
.catch(() => { clearTimeout(timer); callback(null); });
"""


def _api_get(driver: uc.Chrome, url: str) -> Optional[dict | list]:
    """Fetch JSON from an AIS API endpoint using the browser's authenticated session."""
    try:
        result = driver.execute_async_script(_JS_FETCH, url)
    except Exception as exc:
        log.debug("JS fetch error (%s): %s", url, exc)
        return None
    if not result or not isinstance(result, str):
        log.debug("Empty response from %s", url)
        return None
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        log.debug("Non-JSON response from %s: %s", url, result[:200])
        return None


def check_slots(driver: uc.Chrome, schedule_id: int, facility_id: Optional[int]) -> tuple[list[tuple[date, int]], bool]:
    """
    Navigate to the appointment page and return (slots, fee_paid).
    Each slot is (date, available_time_count).
    fee_paid=False means the MRV fee hasn't been paid; the AIS site redirects to /payment in that case.
    """
    log.info("Checking for available dates and slots...")
    driver.get(f"{CONFIG.base_url}/niv/schedule/{schedule_id}/appointment")
    time.sleep(3)

    if "payment" in driver.current_url:
        log.info("Redirected to payment page — MRV fee not paid. Scraping for earliest date ...")
        d = _scrape_earliest_from_page(driver)
        return ([(d, 0)] if d else []), False

    log.info("Perfect, MRV Fee has already been paid — getting available dates")
    if facility_id is None: 
        return [], True
    return _fetch_available_dates(driver, schedule_id, facility_id), True


def _scrape_earliest_from_page(driver: uc.Chrome) -> Optional[date]:
    """
    Scrape the earliest available date from the current page HTML.
    Used when the MRV fee hasn't been paid; the API endpoint is inaccessible in that state.
    """
    page = driver.page_source

    if match := re.search(r"([A-Za-z]+ \d{1,2}, \d{4})", page): # look for something like "March 15, 2026"
        raw = match.group(1)
        try:
            parsed = datetime.strptime(raw, "%B %d, %Y").date()
            log.info("Found date on page: %s", parsed)
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
        log.debug("No available dates found!")
        return []

    available = []
    for entry in data:
        try:
            available.append(datetime.strptime(entry["date"], "%Y-%m-%d").date())
        except (ValueError, TypeError, KeyError):
            continue

    top = sorted(available)[:5]
    log.info("Found %d available date(s), showing earliest 5: %s", len(available), top)

    return [(d, _count_times(driver, schedule_id, facility_id, d)) for d in top]


def _count_times(driver: uc.Chrome, schedule_id: int, facility_id: int, d: date) -> int:
    """Return the number of available appointment times for a given date."""
    times_url = (
        f"{CONFIG.base_url}/niv/schedule/{schedule_id}/appointment/"
        f"times/{facility_id}.json?date={d.isoformat()}&appointments[expedite]=false"
    )
    for attempt in range(2):
        data = _api_get(driver, times_url)
        if isinstance(data, dict):
            count = len(data.get("available_times", [])) # jfyi - some dates have "business_times" instead of "available_times".
            log.info("Times for %s: %d available", d, count)
            return count
        log.warning("Unexpected times response for %s (%s), attempt %d/2", d, type(data).__name__, attempt + 1)
        time.sleep(1)
    return 0
