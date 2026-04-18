# US Visa Appointment Slot Checker — Ethiopia

Monitors [ais.usvisa-info.com/en-et](https://ais.usvisa-info.com/en-et) and sends a Telegram message when appointment slots are available.

---

## Flows

The script auto-detects which flow your account is in:

**Unpaid** — Fee not paid yet. Watches the earliest available date shown on your payment page and sends a Telegram message whenever it changes.

**Paid** — Fee paid. Calls the AIS calendar API and sends a Telegram message when the earliest open slot changes.

If you have a current appointment and only want to be alerted for earlier slots, pass `--current-date`.

---

## Setup

### Requirements

- **Python 3.10 or 3.11** (required by `undetected-chromedriver` — does not support Python 3.12+)
- `pip` and `git`

### Using a Virtual Environment (venv) — Unix/Linux/macOS

```bash
# Clone the repository (if not already done)
git clone <repository-url>
cd visa_slot_monitor

# Create a virtual environment
python3 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate

# Verify activation (your prompt should show "(.venv)")
which python3

```

### Install Dependencies

```bash
pip install -r requirements.txt
cp .env.example .env   # edit .env — every variable is documented in .env.example
```

Environment variables are described inline in [`.env.example`](.env.example). Copy that file to `.env` and fill in your credentials.

---

## Usage

```bash
# Monitor your schedule and auto-detect unpaid vs paid flow
python3 visa_slot_monitor.py --schedule-id 12345678

# Only alert if a slot is earlier than your current appointment
python3 visa_slot_monitor.py --schedule-id 12345678 --current-date 2026-12-31
```

Set `FACILITY_ID` in `.env` for paid-flow checks. (`SCHEDULE_ID` can be set in `.env` too if you want to omit `--schedule-id`.)

## All flags

| Flag | Description |
|---|---|
| `--schedule-id` | Schedule ID (priority: flag → `SCHEDULE_ID` env). Required. |
| `--current-date` | `YYYY-MM-DD`. If set, alerts only for slots earlier than this date. |
| `--interval` | Seconds between checks. |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`). |
| `--no-headless` | Show the browser window. Useful if login keeps failing. |

---

## Troubleshooting

**Login fails** — Run with `--no-headless` to watch the browser.

**Date not found (unpaid mode)** — The script saves the page to `unpaid_debug.html`. Open it to see what the page actually shows and update the regex in `check_unpaid()`.
