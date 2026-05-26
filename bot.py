"""
Entry point del bot.

Arranca python-telegram-bot en modo long-polling.
Registra handlers de comandos, mensajes y callbacks.
"""
import asyncio
import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import config
from handlers.commands import start_command, help_command, timeframes_command
from handlers.messages import handle_message, handle_callback
from utils.logger import setup_logger

logger = setup_logger(__name__)


def main() -> None:
    # Valida variables de entorno antes de arrancar
    config.validate()

    logger.info(f"Iniciando bot | modelo={config.GEMINI_MODEL}")

    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .build()
    )

    # ── Comandos ──────────────────────────────────────────────
    app.add_handler(CommandHandler("start",      start_command))
    app.add_handler(CommandHandler("help",       help_command))
    app.add_handler(CommandHandler("timeframes", timeframes_command))

    # ── Botones inline ────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^tf:"))

    # ── Mensajes de texto ─────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot activo — esperando mensajes (long-polling)")
    app.run_polling(
        drop_pending_updates=True,   # Ignora mensajes acumulados mientras estaba offline
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()
