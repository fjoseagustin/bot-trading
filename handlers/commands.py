"""
Handlers de comandos Telegram: /start, /help, /timeframes
"""
from telegram import Update
from telegram.ext import ContextTypes

from utils.logger import setup_logger

logger = setup_logger(__name__)

_HELP = """
🤖 *Bot de Análisis SMC/ICT*

*Uso básico:*
`Analiza {SÍMBOLO} {TIMEFRAME}`

*Ejemplos:*
• `Analiza Bitcoin H1`
• `Analiza BTC H4`
• `Analiza ORO Daily`
• `Analiza EURUSD M15`
• `Analiza AAPL H1`
• `Analiza SOL Weekly`

*Si omites el timeframe, te lo pregunto* 👇

*Timeframes disponibles:*
• `M1`  — 1 minuto
• `M5`  — 5 minutos
• `M15` — 15 minutos
• `H1`  — 1 hora
• `H4`  — 4 horas
• `Daily` — Diario
• `Weekly` — Semanal

*El análisis incluye:*
✅ Sesgo dominante
✅ BOS / CHOCH
✅ Order Blocks
✅ Fair Value Gaps
✅ Zonas de liquidez
✅ Escenarios con probabilidades
✅ Operación recomendada (entrada · SL · TP · R:R)
"""


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 ¡Hola! Soy tu asistente de análisis SMC/ICT.\n" + _HELP,
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_HELP, parse_mode="Markdown")


async def timeframes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📊 *Timeframes soportados:*\n\n"
        "• `M1`  — 1 minuto\n"
        "• `M5`  — 5 minutos\n"
        "• `M15` — 15 minutos\n"
        "• `H1`  — 1 hora\n"
        "• `H4`  — 4 horas\n"
        "• `Daily` — Diario\n"
        "• `Weekly` — Semanal",
        parse_mode="Markdown",
    )
