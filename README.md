# US Visa Appointment Slot Checker — Ethiopia

Monitors [ais.usvisa-info.com/en-et](https://ais.usvisa-info.com/en-et) and sends an SMS when appointment slots are available.

---

## Modes

**`unpaid`** — Fee not paid yet. Watches the earliest available date shown on your payment page and texts you whenever it changes.

**`paid`** — Fee paid. Calls the AIS calendar API and texts you when the earliest open slot changes (SMS includes that single earliest date).

If you have a current appointment and only want to be alerted for earlier slots, pass `--current-date`.

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # edit .env — every variable is documented in .env.example
```

Environment variables are described inline in [`.env.example`](.env.example). Copy that file to `.env` and fill in your credentials.

---

## Usage

```bash
# Unpaid mode
python3 visa_checker.py --mode unpaid

# Paid mode — alerts when the earliest open slot changes
python3 visa_checker.py --mode paid

# Paid mode — only alert if a slot is earlier than your current appointment
python3 visa_checker.py --mode paid --current-date 2026-12-31
```

## All flags

| Flag | Description |
|---|---|
| `--mode` | `unpaid` or `paid` — required |
| `--current-date` | `YYYY-MM-DD`. Paid mode only. If set, alerts only for slots earlier than this date. |
| `--schedule-id` | Override Schedule ID. Useful when account has multiple groups. |
| `--facility-id` | Override Facility ID (paid mode). |
| `--interval` | Seconds between checks. |
| `--no-headless` | Show the browser window. Useful if login keeps failing. |

---

## Troubleshooting

**Login fails** — Run with `--no-headless` to watch the browser.

**Date not found (unpaid mode)** — The script saves the page to `unpaid_debug.html`. Open it to see what the page actually shows and update the regex in `check_unpaid()`.

**Wrong group picked** — Pass `--schedule-id` explicitly.