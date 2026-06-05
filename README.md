# US Visa Appointment Slot Checker — Ethiopia

Monitors [ais.usvisa-info.com/en-et](https://ais.usvisa-info.com/en-et) and posts to a Telegram channel when appointment slots are available (see `TELEGRAM_CHANNEL_ID` in [`.env.example`](.env.example)).

---

## Flows

The script auto-detects which flow your account is in:

**Unpaid** — Fee not paid yet. Watches the earliest available date shown on your payment page and posts to your channel whenever it changes.

**Paid** — Fee paid. Calls the AIS calendar API and posts to your channel when the earliest open slot changes.

Use `--earliest` and/or `--latest` to restrict which slots trigger alerts (e.g. only alert for slots between a minimum date and your current appointment).

---

## Setup

### Requirements

- **Python 3.10 or 3.11** (required by `undetected-chromedriver` — does not support Python 3.12+)
- `pip` and `git`
- **macOS:** `caffeinate` (built-in) — prevents the machine from sleeping during monitoring

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

### Telegram channel ID

Add your bot as an **administrator** of the channel with permission to **post messages**.

**Option A — public channel:** use the channel username with `@`, for example `@my_visa_alerts`.

**Option B — `getUpdates` (same idea as finding a private chat ID):**

1. After the bot can post to the channel, send any message **in that channel** (or post as the bot if you prefer).
2. Open this URL in a browser (replace the token with your bot token from @BotFather):

   `https://api.telegram.org/bot{YOUR_BOT_TOKEN}/getUpdates`

3. In the JSON response, search for `"channel_post"` or `"chat"` and read `"id"` — channel IDs are usually negative (for example `-1001234567890`). Use that value (including the minus sign) as `TELEGRAM_CHANNEL_ID`.

4. Confirm delivery with:

   `https://api.telegram.org/bot{YOUR_BOT_TOKEN}/sendMessage?chat_id={YOUR_CHANNEL_ID}&text=Hello`

---

## Usage

```bash
# Monitor your schedule and auto-detect unpaid vs paid flow
python3 visa_slot_monitor.py

# Only alert for slots earlier than your current appointment
python3 visa_slot_monitor.py --latest 2026-12-31

# Only alert for slots within a specific window
python3 visa_slot_monitor.py --earliest 2026-08-01 --latest 2026-12-31

# Recommended: wrap with caffeinate (macOS) to prevent the machine from sleeping
caffeinate -i python3.11 visa_slot_monitor.py --earliest 2026-07-26 --latest 2026-09-20
```

Set both `SCHEDULE_ID` and `FACILITY_ID` in `.env`. `FACILITY_ID` is required when paid mode is detected.

## All flags

| Flag | Description |
|---|---|
| `--earliest YYYY-MM-DD` | Ignore slots before this date (lower bound, inclusive). |
| `--latest YYYY-MM-DD` | Ignore slots on or after this date (upper bound, exclusive). Typically your current appointment. |
| `--interval` | Seconds between checks. |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`). |
| `--no-headless` | Show the browser window. Useful if login keeps failing. |

---

## Troubleshooting

**Login fails** — Run with `--no-headless` to watch the browser.

**Date not found (unpaid mode)** — The script saves the page to `unpaid_debug.html`. Open it to see what the page actually shows and update the regex in `check_unpaid()`.
