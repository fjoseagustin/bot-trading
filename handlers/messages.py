"""
Orchestrator principal del bot.

Flujo:
  handle_message()  → parsea texto, detecta símbolo/timeframe
  handle_callback() → recibe el timeframe elegido con botones inline
  run_analysis()    → pipeline completo (resolve → candles → chart → Claude → enviar)
"""
from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from services.finnhub_client import FinnhubClient
from services.gemini_client import GeminiClient
from services.symbol_resolver import SymbolResolver
from analysis.chart_builder import ChartBuilder
from utils.timeframe import parse_timeframe
from utils.errors import SymbolNotFoundError, APIError
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Instancias globales (se crean una vez al importar el módulo)
_finnhub      = FinnhubClient()
_claude       = GeminiClient()
_resolver     = SymbolResolver(_finnhub)
_chart_builder = ChartBuilder()

# Palabras clave que disparan el análisis
_TRIGGERS = ("analiza", "analizar", "analyze", "análisis", "analisis", "analisa")


# ──────────────────────────────────────────────────────────────
# Parsing de mensajes
# ──────────────────────────────────────────────────────────────

def _is_analyze_request(text: str) -> bool:
    return text.lower().strip().split()[0] in _TRIGGERS if text.strip() else False


def _parse_message(text: str) -> tuple[str | None, str | None]:
    """
    Extrae (símbolo, timeframe) del texto libre.
    Retorna None en cualquiera si no lo encuentra.
    """
    words = text.strip().split()
    if words and words[0].lower() in _TRIGGERS:
        words = words[1:]

    symbol    = None
    timeframe = None

    for word in words:
        tf = parse_timeframe(word)
        if tf and timeframe is None:
            timeframe = tf
        elif not tf and symbol is None:
            symbol = word.upper()

    return symbol, timeframe


# ──────────────────────────────────────────────────────────────
# Pipeline de análisis
# ──────────────────────────────────────────────────────────────

async def run_analysis(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    symbol_input: str,
    timeframe: str,
) -> None:
    """
    Pipeline completo. Usa update.effective_chat y context.bot
    para enviar mensajes, por lo que funciona tanto desde
    MessageHandler como desde CallbackQueryHandler.
    """
    chat_id = update.effective_chat.id
    bot     = context.bot

    # ── 1. Indicador "escribiendo" ─────────────────────────────
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # ── 2. Resolver símbolo ────────────────────────────────────
    try:
        resolved = await _resolver.resolve(symbol_input)
    except SymbolNotFoundError as exc:
        await bot.send_message(chat_id=chat_id, text=f"❌ {exc}")
        return
    except APIError as exc:
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Error al validar símbolo: {exc}")
        return

    # ── 3. Mensaje de estado (editable a lo largo del proceso) ──
    status = await bot.send_message(
        chat_id=chat_id,
        text=f"⏳ Descargando datos de *{resolved['display_name']}* — {timeframe}…",
        parse_mode="Markdown",
    )

    # ── 4. Obtener velas ───────────────────────────────────────
    try:
        ohlc = await _finnhub.get_candles(
            symbol    = resolved["finnhub_symbol"],
            asset_type= resolved["asset_type"],
            timeframe = timeframe,
            count     = 500,
        )
    except (SymbolNotFoundError, APIError) as exc:
        await status.edit_text(f"❌ {exc}")
        return

    # ── 5-6. Gráfico desactivado (ahorra tiempo y recursos) ───────

    # ── 5b. Aviso de frescura de datos ────────────────────────
    staleness = ohlc.get("staleness", "fresh")
    age_h     = ohlc.get("age_hours", 0)

    if staleness == "market_closed":
        await bot.send_message(
            chat_id    = chat_id,
            text       = (
                f"🔒 *Mercado cerrado* — última vela de "
                f"*{resolved['display_name']}* hace *{age_h}h*.\n"
                f"Fin de semana o festivo. El análisis usa la última sesión disponible."
            ),
            parse_mode = "Markdown",
        )
    elif staleness == "provider_lag":
        await bot.send_message(
            chat_id    = chat_id,
            text       = (
                f"⚠️ *Datos con retraso* — última vela de "
                f"*{resolved['display_name']}* hace *{age_h}h*.\n"
                f"El proveedor (Yahoo Finance) no entregó las velas más recientes.\n"
                f"Para gold/plata en H1/M15, probá con *H4 o D* que tienen datos más frescos."
            ),
            parse_mode = "Markdown",
        )

    # ── 6. Estadísticas de precio ─────────────────────────────
    stats_msg = _build_stats_block(ohlc, resolved["display_name"], timeframe)
    await bot.send_message(chat_id=chat_id, text=stats_msg, parse_mode="Markdown")

    # ── 7. Análisis con Gemini (opcional — no bloquea si falla) ──
    await status.edit_text("🧠 Analizando con IA (SMC/ICT)…")
    analysis: str | None = None
    try:
        analysis = await _claude.analyze(
            ohlc       = ohlc,
            symbol     = resolved["display_name"],
            timeframe  = timeframe,
            asset_type = resolved["asset_type"],
        )
    except APIError as exc:
        logger.warning(f"Gemini no disponible: {exc}")
        # Continúa sin análisis IA — el gráfico ya fue enviado

    # ── 8. Enviar análisis o aviso de no disponibilidad ────────
    await status.delete()

    if analysis:
        header = (
            f"🔍 *Análisis SMC/ICT — {resolved['display_name']} {timeframe}*\n"
            f"{'─' * 32}\n\n"
        )
        full_text = header + analysis
        for chunk in _split_text(full_text, max_len=4000):
            await bot.send_message(
                chat_id    = chat_id,
                text       = chunk,
                parse_mode = "Markdown",
            )
    else:
        await bot.send_message(
            chat_id    = chat_id,
            text       = (
                f"📊 *{resolved['display_name']} — {timeframe}*\n\n"
                f"✅ Gráfico generado con {ohlc['count']} velas\n"
                f"❌ Análisis IA no disponible temporalmente\n\n"
                f"_Verifica tu API key de Gemini en aistudio.google.com_"
            ),
            parse_mode = "Markdown",
        )


# ──────────────────────────────────────────────────────────────
# Handlers de Telegram
# ──────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procesa mensajes de texto entrantes."""
    text = (update.message.text or "").strip()

    if not _is_analyze_request(text):
        await update.message.reply_text(
            "💡 Para analizar escribe:\n`Analiza {SÍMBOLO} {TIMEFRAME}`\n\n"
            "Ejemplo: `Analiza BTC H1`\n\n"
            "Escribe /help para más información.",
            parse_mode="Markdown",
        )
        return

    symbol, timeframe = _parse_message(text)

    if not symbol:
        await update.message.reply_text(
            "❌ No reconocí el símbolo.\n"
            "Ejemplo: `Analiza BTC H1` o `Analiza ORO Daily`",
            parse_mode="Markdown",
        )
        return

    if not timeframe:
        # Pedir timeframe con botones inline
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("M1",     callback_data=f"tf:{symbol}:M1"),
                InlineKeyboardButton("M5",     callback_data=f"tf:{symbol}:M5"),
                InlineKeyboardButton("M15",    callback_data=f"tf:{symbol}:M15"),
            ],
            [
                InlineKeyboardButton("H1",     callback_data=f"tf:{symbol}:H1"),
                InlineKeyboardButton("H4",     callback_data=f"tf:{symbol}:H4"),
            ],
            [
                InlineKeyboardButton("Daily",  callback_data=f"tf:{symbol}:D"),
                InlineKeyboardButton("Weekly", callback_data=f"tf:{symbol}:W"),
            ],
        ])
        await update.message.reply_text(
            f"⏱ ¿Qué timeframe para *{symbol}*?",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    await run_analysis(update, context, symbol, timeframe)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procesa el botón inline de selección de timeframe."""
    query = update.callback_query
    await query.answer()  # Cierra el spinner del botón

    data = query.data or ""
    if not data.startswith("tf:"):
        return

    parts = data.split(":", 2)
    if len(parts) != 3:
        return

    _, symbol, timeframe = parts

    # Elimina el mensaje de selección de timeframe
    try:
        await query.delete_message()
    except Exception:
        pass  # Si no se puede borrar no es crítico

    await run_analysis(update, context, symbol, timeframe)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _fmt_price(value: float) -> str:
    """Formatea el precio con precisión apropiada según su magnitud."""
    if value >= 100:
        return f"{value:,.2f}"
    elif value >= 1:
        return f"{value:,.4f}"
    else:
        return f"{value:,.6f}"


def _build_stats_block(ohlc: dict, display_name: str, timeframe: str) -> str:
    """
    Genera el bloque de estadísticas de precio para el período analizado.
    Se envía ANTES del análisis SMC para dar contexto inmediato.
    """
    df    = ohlc["df"]
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    current = close.iloc[-1]
    máximo  = high.max()
    mínimo  = low.min()
    promedio = close.mean()

    # Distancias desde el actual
    dist_max = ((máximo - current) / current) * 100
    dist_min = ((current - mínimo) / current) * 100

    # Período cubierto
    dt_from = df["datetime"].iloc[0].strftime("%d/%m/%Y")
    dt_to   = df["datetime"].iloc[-1].strftime("%d/%m/%Y %H:%M")
    n_velas = ohlc["count"]

    # Indicador visual de posición en el rango
    rango = máximo - mínimo
    pos_pct = int(((current - mínimo) / rango) * 10) if rango > 0 else 5
    pos_pct = max(0, min(10, pos_pct))
    barra = "▓" * pos_pct + "░" * (10 - pos_pct)

    return (
        f"📊 *{display_name} — {timeframe}*\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"💵 Actual:    `{_fmt_price(current)}`\n"
        f"📈 Máximo:    `{_fmt_price(máximo)}`  _(+{dist_max:.1f}% arriba)_\n"
        f"📉 Mínimo:    `{_fmt_price(mínimo)}`  _(-{dist_min:.1f}% abajo)_\n"
        f"∅  Promedio:  `{_fmt_price(promedio)}`\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"Rango: `[{barra}]`\n"
        f"↳ mín {_fmt_price(mínimo)} — actual — máx {_fmt_price(máximo)}\n"
        f"📅 {dt_from} → {dt_to} UTC | {n_velas} velas"
    )


def _split_text(text: str, max_len: int = 4000) -> list[str]:
    """Divide texto largo en chunks respetando saltos de línea."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
