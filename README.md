# Telegram Keyword Replacer Bot

A production-ready Telegram bot that **automatically finds and replaces configured keywords** in messages posted in groups and channels where the bot is an administrator.

It edits messages **in place** (using `editMessageText` / `editMessageCaption`). It never deletes, re-uploads, or creates duplicate messages.

> **Important Telegram limitation**  
> PDF/document **filenames** of already-uploaded files are intentionally **not** modified because the Telegram Bot API does not provide normal direct editing for this field. Only the **caption** of documents is edited when it contains a matching keyword.

---

## Features

- ✅ Automatic in-place keyword replacement in **text** and **media captions**
- ✅ Unlimited replacement rules per chat
- ✅ Independent settings per group / channel
- ✅ Case-insensitive (default) or case-sensitive matching
- ✅ `contains` or whole-`word` match modes
- ✅ Owner + authorized-admin only configuration
- ✅ Clean command interface + optional inline admin panel
- ✅ Handles new messages **and** edited messages
- ✅ Robust error handling (flood control, permissions, network…)
- ✅ SQLite by default (Render free-tier friendly) + PostgreSQL compatible
- ✅ Ready for GitHub + Render free worker deployment (long polling)

---

## Supported content types

The bot processes any field that the Telegram Bot API allows bots to edit:

| Type              | Field processed |
|-------------------|-----------------|
| Normal text       | `message.text`  |
| Photo / Video / Document / Audio / Animation / Voice | `message.caption` |

**Not supported (by Telegram design):**
- Changing the actual filename of an already-uploaded document/PDF
- Editing messages the bot does not have permission to edit

---

## Required bot permissions

Add the bot as an **administrator** in the target group or channel and grant at least:

- **Edit messages** ← required for keyword replacement
- Presence / ability to see messages

Optional (not required for core functionality):
- Delete messages

Without **Edit messages** the bot cannot replace keywords.

---

## How to create a Telegram bot

1. Open Telegram and talk to [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the instructions
3. Copy the **bot token** (looks like `1234567890:ABCdef...`)
4. (Recommended) Disable privacy mode if you want the bot to see all messages in groups:
   - `/setprivacy` → select your bot → **Disable**

---

## How to obtain your OWNER_ID

1. Talk to [@userinfobot](https://t.me/userinfobot) or [@getidsbot](https://t.me/getidsbot)
2. Or add this bot to a chat and send `/myid`
3. Copy the numeric ID (e.g. `123456789`)

---

## Environment variables

| Variable       | Required | Description                                      | Example                                      |
|----------------|----------|--------------------------------------------------|----------------------------------------------|
| `BOT_TOKEN`    | Yes      | Token from @BotFather                            | `123456:ABC...`                              |
| `OWNER_ID`     | Yes      | Your numeric Telegram user ID                    | `123456789`                                  |
| `DATABASE_URL` | No       | SQLAlchemy async URL (default = SQLite)          | `sqlite+aiosqlite:///./bot.db`               |
| `LOG_LEVEL`    | No       | `DEBUG`, `INFO`, `WARNING`, `ERROR`              | `INFO`                                       |

For PostgreSQL later:

```
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname
```

---

## Local installation & run

```bash
# 1. Clone / download
git clone <your-repo-url>
cd telegram-keyword-replacer

# 2. Create virtualenv (recommended)
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# Edit .env and put your BOT_TOKEN and OWNER_ID

# 5. Run
python -m bot.main
```

The bot will create the SQLite database automatically on first start.

---

## Commands

| Command                        | Description                              | Who can use          |
|--------------------------------|------------------------------------------|----------------------|
| `/start`                       | Welcome message                          | Everyone             |
| `/help`                        | Full help                                | Everyone             |
| `/myid`                        | Show your Telegram user ID               | Everyone             |
| `/chatid`                      | Show current chat ID                     | Everyone             |
| `/permissions`                 | Required bot admin permissions           | Everyone             |
| `/status`                      | Current bot status for this chat         | Authorized           |
| `/addkeyword OLD \| NEW`       | Add / update a replacement rule          | Owner / authorized   |
| `/deletekeyword OLD`           | Remove a rule                            | Owner / authorized   |
| `/listkeywords`                | List all rules                           | Owner / authorized   |
| `/clearkeywords`               | Delete all rules in this chat            | Owner / authorized   |
| `/enable`                      | Enable automatic replacement             | Owner / authorized   |
| `/disable`                     | Disable automatic replacement            | Owner / authorized   |
| `/casesensitive on\|off`       | Toggle case sensitivity                  | Owner / authorized   |
| `/matchmode contains\|word`    | Matching mode                            | Owner / authorized   |
| `/panel`                       | Open simple admin panel                  | Owner / authorized   |

**Example**

```
/addkeyword OLDNAME | @NewChannel
```

After this, any new message containing `OLDNAME` (any case) will be automatically edited to contain `@NewChannel` instead.

---

## Render FREE Web Service deployment

Render free tier only offers **Web Service** (Background Worker is paid).

This bot is already configured for it:
- A tiny HTTP health-check server listens on `$PORT`
- The Telegram bot runs with **long polling** in the same process

### Steps

1. Push the repository to GitHub.
2. Go to [Render Dashboard](https://dashboard.render.com) → **New** → **Web Service**.
3. Connect your GitHub repository.
4. Settings:
   - **Name**: `telegram-keyword-replacer` (or any name)
   - **Runtime**: Python 3
   - **Instance Type**: Free
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python -m bot.main`
5. Add Environment Variables:
   - `BOT_TOKEN` = your bot token
   - `OWNER_ID` = your numeric user ID
   - `DATABASE_URL` = `sqlite+aiosqlite:///./bot.db` (optional)
   - `LOG_LEVEL` = `INFO`
6. Create the Web Service.

### Important notes about free Web Service

- Render free web services **spin down after ~15 minutes of no HTTP traffic**.
- When someone visits the service URL (or health-check hits), it wakes up again.
- The bot will also wake up and resume polling.
- For personal / low-traffic groups this is usually fine.
- For always-on behaviour you need a paid plan or an external cron that pings your Render URL every 10–14 minutes.

You can also use the included `render.yaml` Blueprint.

---

## Database

- Default: **SQLite** (file `bot.db`) – perfect for free tier
- Tables are created automatically on first start
- Designed with SQLAlchemy so you can later switch to PostgreSQL by changing `DATABASE_URL`

---

## How it works (high level)

1. You add the bot as admin to a group/channel and give it **Edit messages** permission.
2. Owner runs `/addkeyword OLD | NEW` inside that chat.
3. Whenever a new message (or an edited message) arrives that contains a matching keyword, the bot calls:
   - `editMessageText` for pure text messages
   - `editMessageCaption` for media captions
4. The original message stays in place – only the text/caption is changed.

---

## Troubleshooting

| Problem                              | Solution                                                                 |
|--------------------------------------|--------------------------------------------------------------------------|
| Bot does not react to messages       | Disable privacy mode in BotFather (`/setprivacy` → Disable)              |
| “Message can’t be edited”            | Give the bot **Edit messages** admin right                               |
| Commands ignored                     | Only `OWNER_ID` (and authorized admins) can configure                    |
| Bot sleeps on Render free            | Normal behaviour; it wakes on activity. Upgrade for always-on            |
| Database errors                      | Check `DATABASE_URL`. For SQLite ensure the process has write permission |

---

## Security notes

- Never commit your real `.env` file or bot token to GitHub.
- Keep `OWNER_ID` secret – only that user (and explicitly authorized admins) can change rules.
- The bot never logs message content at INFO level.

---

## Development & tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## Project structure

```
telegram-keyword-replacer/
├── bot/
│   ├── __init__.py
│   ├── main.py          # Entry point
│   ├── config.py
│   ├── database.py
│   ├── handlers.py
│   ├── replacer.py
│   ├── permissions.py
│   ├── keyboards.py
│   └── utils.py
├── tests/
│   └── test_replacer.py
├── requirements.txt
├── render.yaml
├── Procfile
├── .env.example
├── .gitignore
├── README.md
└── LICENSE
```

---

## License

MIT License – see [LICENSE](LICENSE).

---

**Happy keyword replacing!**  
If you find a bug or want a feature, open an issue on GitHub.
