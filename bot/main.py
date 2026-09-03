"""Entry — Render free Web Service."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.config import BOT_NAME, BOT_TOKEN, setup_logging, validate_config
from bot.database import init_db
from bot.handlers import (
    WAIT_ADD,
    addadmin_cmd,
    addkeyword_cmd,
    cancel_cmd,
    clear_cmd,
    deletekeyword_cmd,
    disable_cmd,
    enable_cmd,
    help_cmd,
    listadmins_cmd,
    listkeywords_cmd,
    myid_cmd,
    on_add_text,
    on_cb,
    process_message,
    removeadmin_cmd,
    start_cmd,
    status_cmd,
)

logger = logging.getLogger(__name__)


async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


async def root(_: Request) -> JSONResponse:
    return JSONResponse({"status": "running", "bot": BOT_NAME})


def build_app() -> Application:
    application = (
        Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    )

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_cmd),
            CommandHandler("menu", start_cmd),
            CallbackQueryHandler(on_cb, pattern=r"^m:"),
        ],
        states={
            WAIT_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_add_text),
                CallbackQueryHandler(on_cb, pattern=r"^m:"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_cmd),
            CommandHandler("start", start_cmd),
            CallbackQueryHandler(on_cb, pattern=r"^m:"),
        ],
        allow_reentry=True,
        name="sk_simple",
    )
    application.add_handler(conv)

    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("myid", myid_cmd))
    application.add_handler(CommandHandler("addkeyword", addkeyword_cmd))
    application.add_handler(CommandHandler("listkeywords", listkeywords_cmd))
    application.add_handler(CommandHandler("deletekeyword", deletekeyword_cmd))
    application.add_handler(CommandHandler("clear", clear_cmd))
    application.add_handler(CommandHandler("clearkeywords", clear_cmd))
    application.add_handler(CommandHandler("enable", enable_cmd))
    application.add_handler(CommandHandler("disable", disable_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("addadmin", addadmin_cmd))
    application.add_handler(CommandHandler("removeadmin", removeadmin_cmd))
    application.add_handler(CommandHandler("listadmins", listadmins_cmd))

    application.add_handler(MessageHandler(filters.Document.ALL, process_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))
    application.add_handler(MessageHandler(filters.CAPTION, process_message))
    application.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST
            & (filters.TEXT | filters.CAPTION | filters.Document.ALL),
            process_message,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.UpdateType.EDITED_CHANNEL_POST & (filters.TEXT | filters.CAPTION),
            process_message,
        )
    )

    async def err(update, context):
        logger.error("Error", exc_info=context.error)

    application.add_error_handler(err)
    return application


async def run() -> None:
    await init_db()
    application = build_app()
    await application.initialize()
    await application.start()
    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES, drop_pending_updates=True
    )
    logger.info("%s running.", BOT_NAME)
    port = int(os.environ.get("PORT", "10000"))
    server = uvicorn.Server(
        uvicorn.Config(
            Starlette(routes=[Route("/", root), Route("/health", health), Route("/healthz", health)]),
            host="0.0.0.0",
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    try:
        await server.serve()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def main() -> None:
    setup_logging()
    try:
        validate_config()
    except ValueError as e:
        logger.critical("%s", e)
        sys.exit(1)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.critical("Fatal: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
