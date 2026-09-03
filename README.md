# SK Keywords (Simple)

Global keyword replacer for Telegram channels + private.

## Render env

| Key | Value |
|-----|--------|
| BOT_TOKEN | from BotFather |
| OWNER_ID | your numeric ID |
| DATABASE_URL | `sqlite+aiosqlite:///./bot.db` or `postgresql+asyncpg://user:pass@host:5432/db?ssl=require` |
| PYTHON_VERSION | 3.12.7 |
| LOG_LEVEL | INFO |

Optional: FORCE_CHANNEL, OWNER_USERNAME, DEVELOPER_USERNAME

**Build:** `pip install -r requirements.txt`  
**Start:** `python -m bot.main`

Repo root must contain `bot/` folder.

## Use

- `/start` — buttons
- Add: `Mk&Sk,xyz&SK` then Done
- Or `/addkeyword OLD | NEW`
- Bot admin in channel → auto caption/PDF replace
