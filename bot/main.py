"""SK Keywords Replacer — Render free Web Service entry."""

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
    ChatMemberHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.branding import BOT_NAME
from bot.config import BOT_TOKEN, setup_logging, validate_config
from bot.database import init_db
from bot.handlers import (
    WAIT_ADD_ADMIN,
    WAIT_BATCH,
    WAIT_BROADCAST,
    WAIT_CREDIT,
    WAIT_DEL_ADMIN,
    WAIT_DEL_KEYWORD,
    WAIT_KEYWORDS,
    WAIT_TEMPLATE,
    bulk_collect,
    cancel_conv,
    menu_cmd,
    on_add_admin_text,
    on_batch_text,
    on_broadcast_text,
    on_credit_text,
    on_del_admin_text,
    on_del_kw_text,
    on_keywords_text,
    on_my_chat_member,
    on_template_text,
    process_message,
    sk_callback,
    start_cmd,
)

logger = logging.getLogger(__name__)


async def health(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


async def root(request: Request) -> JSONResponse:
    return JSONResponse({"status": "running", "bot": BOT_NAME})


def create_web_app() -> Starlette:
    return Starlette(
        routes=[
            Route("/", root),
            Route("/health", health),
            Route("/healthz", health),
        ]
    )


def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_cmd),
            CommandHandler("menu", menu_cmd),
            CallbackQueryHandler(sk_callback, pattern=r"^sk:"),
        ],
        states={
            WAIT_KEYWORDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_keywords_text)
            ],
            WAIT_BATCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_batch_text)],
            WAIT_CREDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_credit_text)
            ],
            WAIT_TEMPLATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_template_text)
            ],
            WAIT_BROADCAST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_broadcast_text)
            ],
            WAIT_ADD_ADMIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_add_admin_text)
            ],
            WAIT_DEL_ADMIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_del_admin_text)
            ],
            WAIT_DEL_KEYWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_del_kw_text)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conv),
            CommandHandler("start", start_cmd),
            CallbackQueryHandler(sk_callback, pattern=r"^sk:"),
        ],
        allow_reentry=True,
        name="sk_main_conv",
        persistent=False,
    )
    app.add_handler(conv)

    # Live + bulk media (outside conv for channel posts and bulk files)
    app.add_handler(MessageHandler(filters.Document.ALL, process_message))
    app.add_handler(MessageHandler(filters.VIDEO, process_message))
    app.add_handler(MessageHandler(filters.ANIMATION, process_message))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, process_message)
    )
    app.add_handler(MessageHandler(filters.CAPTION, process_message))
    app.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST
            & (filters.TEXT | filters.CAPTION | filters.Document.ALL),
            process_message,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.UpdateType.EDITED_CHANNEL_POST & (filters.TEXT | filters.CAPTION),
            process_message,
        )
    )
    app.add_handler(
        ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    async def on_error(update: object, context) -> None:
        logger.error("Handler error", exc_info=context.error)

    app.add_error_handler(on_error)
    return app


async def run_bot_and_web() -> None:
    await init_db()
    application = build_application()
    await application.initialize()
    await application.start()
    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )
    logger.info("%s running (polling + health).", BOT_NAME)

    port = int(os.environ.get("PORT", "10000"))
    config = uvicorn.Config(
        create_web_app(), host="0.0.0.0", port=port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def main() -> None:
    setup_logging()
    logger.info("Starting %s…", BOT_NAME)
    try:
        validate_config()
    except ValueError as e:
        logger.critical("Config: %s", e)
        sys.exit(1)
    try:
        asyncio.run(run_bot_and_web())
    except KeyboardInterrupt:
        logger.info("Stopped.")
    except Exception as e:
        logger.critical("Fatal: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
