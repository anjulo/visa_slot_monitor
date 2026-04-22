# CLAUDE.md — Visa Slot Monitor

## What this project does

Polls `ais.usvisa-info.com/en-et` for US visa appointment availability in Ethiopia and sends Telegram alerts when slots change.

## Module layout

| File | Responsibility |
|------|---------------|
| `visa_slot_monitor.py` | Entry point. Login loop, session-expiry detection, orchestration. |
| `browser_session.py` | `make_driver()`, `login()`, `navigate()`. All Selenium/Chrome logic lives here. |
| `slot_checker.py` | `check_slots()` — detects fee-paid state, calls the right scrape/API path. |
| `alerts_and_state.py` | `alert_if_changed()` — change detection, Telegram formatting, night pings. |
| `config.py` | Loads `.env`, validates required fields, exposes a frozen `CONFIG` singleton. |

## Two modes — fee paid vs. not paid

Whether the MRV fee has been paid is **auto-detected from the URL redirect**, not a CLI argument. The distinction matters for how slots are fetched:

- **Fee not paid** — AIS redirects to `/payment`. We scrape the earliest date from the HTML with a regex (`_scrape_earliest_from_page`). The times API is inaccessible in this state, so the slot count is always 0.
- **Fee paid** — We call the AIS days JSON API, then the times JSON API per date to get slot counts.

`check_slots()` returns `(slots, fee_paid: bool)`. Do not reintroduce a mode string or CLI flag.

## AIS API endpoints

Both use browser JS fetch (`execute_async_script`) so the `_yatri_session` cookie is included automatically. A plain `requests.get` can't access that cookie.

```
Days:  GET /niv/schedule/{schedule_id}/appointment/days/{facility_id}.json?appointments[expedite]=false
Times: GET /niv/schedule/{schedule_id}/appointment/times/{facility_id}.json?date=YYYY-MM-DD&appointments[expedite]=false
```

- Days response: `[{"date": "YYYY-MM-DD", ...}, ...]`
- Times response: `{"available_times": ["08:15", ...], "business_times": [...]}` — it's a **dict**, not a list.
- `appointments[expedite]=false` is required on both; omitting it causes an API error.

`_api_get()` in `slot_checker.py` handles the JS fetch + JSON parse for both. It returns `Optional[dict | list]` — callers guard with `isinstance`.

## Slots type

```python
Slots = list[tuple[date, int]]  # (date, available_time_count)
```

Up to 5 earliest dates returned. Slot count is 0 in fee-not-paid mode.

## Alert logic

`alert_if_changed()` only fires when the **set of available dates changes**. Same dates, even with different slot counts, do not re-alert (avoids channel spam).

Night ping: between 23:00–06:00 local time, the same message is also sent directly to each chat ID in `NIGHT_PING_TARGETS`. The user configures Telegram to ring loudly on those chats.

## `FACILITY_ID` requirement

`FACILITY_ID` is only required when the fee is already paid (needed for the API calls). If fee is paid and `FACILITY_ID` is missing, `visa_slot_monitor.py` calls `_die()` with the driver to quit cleanly. Do not add a fallback guard inside `slot_checker.py` — validation happens upstream.

## Chrome / undetected_chromedriver

`undetected_chromedriver` patches Chrome to bypass AIS bot-detection fingerprinting. Standard Selenium Chrome gets blocked. `use_subprocess=False` is required on macOS with Chrome 133+ — subprocess mode breaks the WebDriver session before the first navigation completes (ref: ultrafunkamsterdam/undetected-chromedriver#2295).

## Login verbosity

`login()` in `browser_session.py` has verbose logging intentionally. Login runs once per session and the logs are essential for debugging CAPTCHA or layout changes on the AIS login page. Do not remove them.

## What not to do

- Do not mock the `_yatri_session` cookie — it only exists in the live browser jar.
- Do not remove the `appointments[expedite]=false` query param — the API returns an error without it.
- Do not reintroduce `[PAID]`/`[UNPAID]`/`[AUTO]` log prefixes — mode is always auto-detected.
- Do not add `if not facility_id` guards inside `slot_checker.py` — validated upstream.
