"""
Telegram Keyword Replacer Bot – entry point.

Designed for Render FREE Web Service:
- Lightweight HTTP health-check server on $PORT
- Telegram bot runs with long polling in the same process
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
import uvicorn

from bot.config import BOT_TOKEN, setup_logging, validate_config
from bot.database import init_db
from bot.handlers import (
    addkeyword_cmd,
    casesensitive_cmd,
    chatid_cmd,
    clearkeywords_cmd,
    deletekeyword_cmd,
    disable_cmd,
    enable_cmd,
    help_cmd,
    listkeywords_cmd,
    matchmode_cmd,
    myid_cmd,
    on_my_chat_member,
    panel_callback,
    panel_cmd,
    permissions_cmd,
    process_message,
    start_cmd,
    status_cmd,
)

logger = logging.getLogger(__name__)


# -------------------- Health-check HTTP server (required by Render Web Service) --------------------

async def health(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK", status_code=200)


async def root(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "running",
            "service": "telegram-keyword-replacer",
            "mode": "long-polling + health-check",
        }
    )


def create_web_app() -> Starlette:
    return Starlette(
        routes=[
            Route("/", root),
            Route("/health", health),
            Route("/healthz", health),
        ]
    )


# -------------------- Telegram Application --------------------

def build_application() -> Application:
    """Build and configure the Telegram Application."""
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    # Commands
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("myid", myid_cmd))
    application.add_handler(CommandHandler("chatid", chatid_cmd))
    application.add_handler(CommandHandler("permissions", permissions_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("enable", enable_cmd))
    application.add_handler(CommandHandler("disable", disable_cmd))
    application.add_handler(CommandHandler("casesensitive", casesensitive_cmd))
    application.add_handler(CommandHandler("matchmode", matchmode_cmd))
    application.add_handler(CommandHandler("addkeyword", addkeyword_cmd))
    application.add_handler(CommandHandler("deletekeyword", deletekeyword_cmd))
    application.add_handler(CommandHandler("listkeywords", listkeywords_cmd))
    application.add_handler(CommandHandler("clearkeywords", clearkeywords_cmd))
    application.add_handler(CommandHandler("panel", panel_cmd))

    # Callback queries (admin panel)
    application.add_handler(CallbackQueryHandler(panel_callback, pattern=r"^panel:"))

    # Automatic keyword processing (new messages + captions)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            process_message,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.CAPTION,
            process_message,
        )
    )
    # Edited messages
    application.add_handler(
        MessageHandler(
            filters.UpdateType.EDITED_MESSAGE & (filters.TEXT | filters.CAPTION),
            process_message,
        )
    )

    # Bot membership changes
    application.add_handler(
        ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    # Global error handler
    application.add_error_handler(error_handler)

    return application


async def error_handler(update: object, context) -> None:
    """Log errors caused by updates."""
    logger.error("Exception while handling an update:", exc_info=context.error)


# -------------------- Combined runner --------------------

async def run_bot_and_web() -> None:
    """
    Start both:
    1. Telegram bot (long polling)
    2. Lightweight HTTP server for Render health checks
    """
    # Initialize database
    await init_db()

    application = build_application()

    # Initialize the telegram application
    await application.initialize()
    await application.start()

    # Start polling in background (non-blocking)
    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )
    logger.info("Telegram bot started with long polling.")

    # Start HTTP server (Render requires a process listening on $PORT)
    port = int(os.environ.get("PORT", "10000"))
    web_app = create_web_app()

    config = uvicorn.Config(
        web_app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    logger.info("Health-check HTTP server listening on port %s", port)

    try:
        await server.serve()
    finally:
        # Graceful shutdown
        logger.info("Shutting down…")
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def main() -> None:
    setup_logging()
    logger.info("Starting Telegram Keyword Replacer Bot (Render free Web Service mode)…")

    try:
        validate_config()
    except ValueError as e:
        logger.critical("Configuration error: %s", e)
        sys.exit(1)

    try:
        asyncio.run(run_bot_and_web())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
