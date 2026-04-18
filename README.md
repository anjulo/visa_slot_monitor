# US Visa Appointment Slot Checker — Ethiopia

Monitors [ais.usvisa-info.com/en-et](https://ais.usvisa-info.com/en-et) and sends an SMS when appointment slots are available.

---

## Modes

**`unpaid`** — Fee not paid yet. Watches the earliest available date shown on your payment page and texts you whenever it changes.

**`paid`** — Fee paid. Calls the AIS calendar API and texts you when the earliest open slot changes (SMS includes that single earliest date).

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
# Unpaid mode
python3 visa_checker.py --mode unpaid --schedule-id 12345678

# Paid mode — alerts when the earliest open slot changes
python3 visa_checker.py --mode paid --schedule-id 12345678 --facility-id 100

# Paid mode — only alert if a slot is earlier than your current appointment
python3 visa_checker.py --mode paid --schedule-id 12345678 --facility-id 100 --current-date 2026-12-31
```

Alternatively, set `SCHEDULE_ID` and `FACILITY_ID` in `.env` and omit the flags.

## All flags

| Flag | Description |
|---|---|
| `--mode` | `unpaid` or `paid` — required |
| `--schedule-id` | Schedule ID (priority: flag → `SCHEDULE_ID` env). Required. |
| `--current-date` | `YYYY-MM-DD`. Paid mode only. If set, alerts only for slots earlier than this date. |
| `--facility-id` | Facility ID (paid mode). Required for paid mode. |
| `--interval` | Seconds between checks. |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`). |
| `--no-headless` | Show the browser window. Useful if login keeps failing. |

---

## Troubleshooting

**Login fails** — Run with `--no-headless` to watch the browser.

**Date not found (unpaid mode)** — The script saves the page to `unpaid_debug.html`. Open it to see what the page actually shows and update the regex in `check_unpaid()`.