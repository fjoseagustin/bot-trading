"""
Construye los prompts SMC/ICT para Claude Sonnet.

- build_system_prompt()  → string estático (se cachea con Anthropic prompt caching)
- build_user_prompt()    → string dinámico con los datos OHLCV del activo
"""
from __future__ import annotations

import pandas as pd


# ──────────────────────────────────────────────────────────────
# System prompt (CACHEABLE — no cambia entre llamadas)
# ──────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """Eres analyst de risk desk institucional: SMC, ICT, Wyckoff, Order Flow, Liquidez.
Objetivo: análisis operable, honesto, conciso. Estilo risk desk — no gurú.

LENGUAJE: Usar "es consistente con" / "favorece" / "hipótesis de mayor probabilidad" / "estructura compatible con".
PROHIBIDO: "Los institucionales están haciendo" / "El mercado va a" / "Van a buscar".

DATOS: OHLCV = tiempo real, confiable. DXY/Noticias = no disponible, declarar y continuar.

════════ REGLAS DE FORMATO ════════
— El sistema ya agrega el encabezado. Comenzar DIRECTAMENTE con 🎯 SESGO.
— Sin separadores ---, sin headers ##, sin tablas.
— Secciones 1–5: EXACTAMENTE 4 bullets, máx 8 palabras por bullet, CERO párrafos.
— Si no cambia la decisión → no ponerlo. Sin timestamps ni decimales innecesarios.
— Justificación: 60–80 palabras. Score: una sola línea compacta.

════════ FORMATO OBLIGATORIO ════════

🕒 [datetime última vela] UTC | DXY/Noticias: N/D

📐 CONTEXTO HTF ([HTF_TF]) [INCLUIR SOLO SI HAY DATOS HTF EN EL PROMPT — omitir sección completa si no]
• Tendencia: [ALCISTA/BAJISTA/NEUTRO HTF] — [motivo 3-4 palabras]
• Estructura: [BOS/CHoCH HTF + nivel]
• Zona clave: [OB/FVG/Liquidez HTF más relevante]
• Alineación: [ALINEADO/DIVERGENTE] con [LTF_TF]

🎯 SESGO
• Macro: [ALCISTA/BAJISTA/NEUTRO] — [basado en HTF si disponible, sino en inicio LTF]
• Micro: [ALCISTA/BAJISTA/NEUTRO] — [motivo 3-4 palabras]
• TF manda: [timeframe]
• Alineación: [ALINEADOS/DIVERGENTES] — [implicación 3-4 palabras]

📊 ESTRUCTURA
• Tendencia: [descripción]
• BOS/CHoCH: [nivel + dirección]
• Liquidez dominante: [zona]
• Contexto: [frase institucional breve]

🟩 ORDER BLOCKS
• OB demanda: [zona] — [intacto/mitigado]
• OB oferta: [zona] — [intacto/mitigado]
• OB clave ahora: [zona + por qué, 4 palabras]
• Confluencia: [con qué coincide]

⚡ FVG
• Principal: [zona] — [imán/resistencia/soporte]
• Secundario: [zona] — [efecto]
• Estado: [visitado/parcial/no visitado]

💧 LIQUIDEZ
• BSL: [nivel/zona]
• SSL: [nivel/zona]
• Stop hunt: [sí — breve / no]
• Hipótesis: [dirección probable 3-4 palabras]

📊 SCORE: X/10 (+2+X+X+X+X+X+X+X) — [0-3 ❌ No trade | 4-5 ⚠️ Especulativo | 6-7 ✅ Operable | 8-10 🔥 Alta convicción]
[Detalle: Macro+2 | Micro+X | BOS+X | Liquidez+X | OB/FVG+X | Confirm+X | HTF+X | SinCat+X]

📈 ESCENARIOS [% suman 100%]
• Principal XX%: [1 línea]
• Alternativo XX%: [1 línea]

════════ VALIDACIÓN ════════
Coherencia: Sesgo→Estructura→Liquidez→OB/FVG→Escenario→Operación.
PROB: divergentes→máx 55% | alineados→puede superar 60% | incertidumbre→45-52%.
LONG: ✅ barrido SSL + ✅ reclaim + ✅ BOS alcista — falta uno → NO entrada.
SHORT: ✅ rechazo OB/FVG + ✅ desplazamiento bajista + ✅ BOS menor — falta uno → NO entrada.
Score <4 o falta confirmación → NO entrada.

HTF (si datos HTF disponibles):
  • HTF ALINEADO con LTF → score HTF +2, prob puede superar 65%.
  • HTF DIVERGENTE con LTF → score HTF +0, restar 1 punto total, prob máx 45%, mínimo 🟡 WATCHLIST.
  • Sweep SSL/BSL en LTF dentro de OB/demanda HTF → ALTA probabilidad de reversión (no continuación).
════════

🚀 OPERACIÓN
[Sin setup:] ❌ NO HAY SETUP | Activar: [condición long] | [condición short] (máx 2 líneas)
[Con setup:] Tipo: LONG/SHORT | Entrada: [zona] | Stop: [nivel] | TP1: [nivel] | TP2: [nivel] | R:R: [X:X] | Prob: XX% | Tamaño: [conservador/normal/agresivo]

🧠 JUSTIFICACIÓN (60–80 palabras, lenguaje probabilístico, no repetir datos, interpretar)

📌 CIERRE
• [🟢 EXECUTE / 🟡 WATCHLIST / 🔴 STAY OUT] — [motivo 1 línea]
• Tesis cae si: [condición conceptual]
• Sesgo cambia si: [nivel alcista] / [nivel bajista]
• Invalidación: [precio] | Riesgo: [BAJO/MEDIO/ALTO]

════════ FILTRO FINAL ════════
"¿El desk pondría dinero real hoy?" — Si no es SÍ claro → 🟡 WATCHLIST o 🔴 STAY OUT.
"Hoy no se opera" es respuesta válida y profesional."""


def build_system_prompt() -> str:
    return _SYSTEM_PROMPT


# ──────────────────────────────────────────────────────────────
# User prompt (DINÁMICO — datos frescos en cada análisis)
# ──────────────────────────────────────────────────────────────

def build_user_prompt(
    ohlc: dict,
    symbol: str,
    timeframe: str,
    asset_type: str,
    htf_ohlc: dict | None = None,
    htf_timeframe: str | None = None,
) -> str:
    df     = ohlc["df"]
    levels = _key_levels(df)

    # Velas en CSV según timeframe:
    # M1/M5 → 120 | M15/H1 → 100 | H4 → 80 | D/W → 50
    _csv_candles = {"M1": 120, "M5": 120, "M15": 100, "H1": 100, "H4": 80, "D": 50, "W": 50}
    n_csv = min(_csv_candles.get(timeframe, 100), len(df))
    csv   = _recent_ohlc_csv(df, n=n_csv)

    asset_label = {"crypto": "Cripto", "stock": "Acción", "forex": "Forex/Commodity"}.get(
        asset_type, asset_type
    )

    # Sección HTF (opcional)
    htf_section = ""
    if htf_ohlc is not None and htf_timeframe is not None:
        htf_section = _build_htf_section(htf_ohlc, htf_timeframe)

    return f"""{htf_section}══════════════════════════════════════════
ANÁLISIS PRINCIPAL — {symbol} ({asset_label}) | TF: {timeframe}
══════════════════════════════════════════
Precio: {levels['current']:,.5f} | Máx: {levels['high']:,.5f} | Mín: {levels['low']:,.5f}
Máx rec: {levels['recent_high']:,.5f} | Mín rec: {levels['recent_low']:,.5f} | Rango prom: {levels['avg_range']:,.5f}
Tendencia LTF: {levels['macro_trend']} | Precio vs mid: {'ENCIMA' if levels['above_mid'] else 'DEBAJO'} | Vol: {'ALTA' if levels['high_vol'] else 'NORMAL'}
DXY/Noticias/Sentimiento: No disponible
Total velas disponibles: {ohlc['count']}

Últimas {n_csv} velas {timeframe} OHLCV (OBs/FVGs/BOS/estructura):
{csv}
Formato requerido: comenzar con 🕒, luego secciones en orden.
{"Incluir sección 📐 CONTEXTO HTF antes de 🎯 SESGO." if htf_section else "Omitir sección 📐 CONTEXTO HTF."}
Secciones 1-5: exactamente 4 bullets, máx 8 palabras c/u.
Score: sobre 10 si hay datos HTF, sobre 9 si no. Justificación: 60-80 palabras."""


# ── Helpers ───────────────────────────────────────────────────

def _key_levels(df: pd.DataFrame) -> dict:
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]

    recent_n   = max(20, len(df) // 5)
    recent     = df.tail(recent_n)

    avg_range  = (high - low).mean()
    recent_avg = (recent["high"] - recent["low"]).mean()
    mid        = (high.max() + low.min()) / 2

    return {
        "current":     round(close.iloc[-1], 5),
        "high":        round(high.max(), 5),
        "low":         round(low.min(), 5),
        "recent_high": round(recent["high"].max(), 5),
        "recent_low":  round(recent["low"].min(), 5),
        "avg_range":   round(avg_range, 5),
        "range_pct":   round((high.max() - low.min()) / low.min() * 100, 2),
        "macro_trend": "ALCISTA" if close.iloc[-1] > close.iloc[0] else "BAJISTA",
        "above_mid":   close.iloc[-1] > mid,
        "high_vol":    recent_avg > avg_range * 1.3,
    }


def _recent_ohlc_csv(df: pd.DataFrame, n: int = 50) -> str:
    cols   = ["datetime", "open", "high", "low", "close", "volume"]
    recent = df.tail(n)[cols].copy()

    recent["datetime"] = recent["datetime"].dt.strftime("%Y-%m-%d %H:%M")

    for col in ("open", "high", "low", "close"):
        recent[col] = recent[col].round(5)

    recent["volume"] = recent["volume"].round(0).astype(int)

    return recent.to_csv(index=False)


def _build_htf_section(htf_ohlc: dict, htf_timeframe: str) -> str:
    """
    Construye la sección de contexto HTF para el user prompt.
    Se envían las últimas N velas del HTF para que Gemini identifique
    estructura, OBs/FVGs y sesgo de marco superior.
    """
    df     = htf_ohlc["df"]
    levels = _key_levels(df)

    # Velas HTF en CSV: suficiente contexto sin saturar el prompt
    _htf_csv_candles = {"H1": 60, "H4": 40, "D": 25, "W": 15}
    n_csv = min(_htf_csv_candles.get(htf_timeframe, 40), len(df))
    csv   = _recent_ohlc_csv(df, n=n_csv)

    return f"""══════════════════════════════════════════
CONTEXTO HTF — {htf_timeframe} ({htf_ohlc['count']} velas totales)
══════════════════════════════════════════
Tendencia HTF: {levels['macro_trend']} | Precio vs mid HTF: {'ENCIMA' if levels['above_mid'] else 'DEBAJO'}
Máx HTF: {levels['high']:,.5f} | Mín HTF: {levels['low']:,.5f}
Máx rec HTF: {levels['recent_high']:,.5f} | Mín rec HTF: {levels['recent_low']:,.5f}
Rango prom HTF: {levels['avg_range']:,.5f} | Vol HTF: {'ALTA' if levels['high_vol'] else 'NORMAL'}

Últimas {n_csv} velas {htf_timeframe} OHLCV (estructura/OBs/FVGs de marco superior):
{csv}
"""
