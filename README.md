# Telegram Keyword Replacer Bot

Premium bot for **per-admin keyword replacement** in Telegram channels.

## Features

- Per-admin private keyword rules (your rules ≠ others’ rules)
- Text & caption in-place edit
- PDF/document **filename** rename (download → re-upload → delete, ordered)
- Hindi/Unicode-safe filenames
- Owner **broadcast** to everyone who `/start`ed the bot
- Admin management (`/addadmin`)
- Render **free Web Service** ready (health check + long polling)

## Render free – Environment

| Key | Value |
|-----|--------|
| `BOT_TOKEN` | From @BotFather |
| `OWNER_ID` | Your numeric Telegram ID |
| `DATABASE_URL` | `sqlite+aiosqlite:///./bot.db` |
| `PYTHON_VERSION` | `3.12.7` |
| `LOG_LEVEL` | `INFO` |

**Build:** `pip install -r requirements.txt`  
**Start:** `python -m bot.main`  
**Type:** Web Service (Free)

## Commands

### Everyone
`/start` `/myid` `/help`

### Owner & Admins
`/addkeyword OLD \| NEW` · `/deletekeyword OLD` · `/listkeywords` · `/clearkeywords`  
`/enable` · `/disable` · `/status` · `/panel`  
`/casesensitive on\|off` · `/matchmode contains\|word`

### Owner only
`/addadmin ID` · `/removeadmin ID` · `/listadmins`  
`/users` · `/broadcast message…`

## How keywords work

1. Open bot in **private chat** → add your rules  
2. Add bot as **channel admin** (post + delete)  
3. **You** post in the channel → only **your** rules apply  

## Notes

- Groups: Telegram often blocks editing others’ messages; **channels** work best  
- PDF rename needs delete + re-upload rights  
- Free Render may sleep after idle; ping the service URL if needed  

MIT License
