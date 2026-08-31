# SK Keywords Replacer

Premium Telegram bot: **Global + Per-admin keywords**, live replace, bulk ordered re-upload.

## Edit branding (one file)

Open **`bot/branding.py`** only:

- `FORCE_CHANNEL` = `@The_Sk08`
- `OWNER_USERNAME` = `@SunilChoudhary08`
- `DEVELOPER_USERNAME` = `@SunilChoudhary_08`
- `DEFAULT_CREDIT` = `@The_Sk08`
- `BOT_NAME` / `TAGLINE`

## Render Environment

| Key | Value |
|-----|--------|
| `BOT_TOKEN` | BotFather token |
| `OWNER_ID` | Your numeric Telegram ID |
| `DATABASE_URL` | `postgresql+asyncpg://USER:PASS@HOST:5432/postgres?ssl=require` |
| `PYTHON_VERSION` | `3.12.7` |
| `LOG_LEVEL` | `INFO` |

Password `#` → `%23`. Never use mongodb or psycopg2 in URL.

**Build:** `pip install -r requirements.txt`  
**Start:** `python -m bot.main`

## Features

- Button UI (minimal commands)
- Keywords: `Mk&Sk,xyz&SK,1&2`
- Global or Per-admin mode
- Live channel/group replace
- Bulk mode with **FIFO order**
- Force join channel
- Owner: admins + broadcast

Repo root must contain `bot/` folder (not nested extra folder).
