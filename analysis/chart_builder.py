"""
Generador de gráficos de velas con Matplotlib (puro, sin mplfinance).

Diseño oscuro estilo TradingView con:
- Cuerpos OHLC (rectángulos verdes/rojos)
- Mechas (wickes)
- Barras de volumen
- Líneas de niveles clave: HH, LL, swing recientes, precio actual
- Título con símbolo, timeframe y fecha
"""
from __future__ import annotations

import asyncio
import os
import uuid
from functools import partial

import matplotlib
matplotlib.use("Agg")  # Backend sin pantalla (headless)

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from utils.logger import setup_logger

logger = setup_logger(__name__)

_TMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tmp")


class ChartBuilder:
    def __init__(self) -> None:
        os.makedirs(_TMP_DIR, exist_ok=True)

    # ── API pública ───────────────────────────────────────────

    async def build(self, ohlc: dict, symbol: str, timeframe: str) -> str:
        """Genera el gráfico en un thread pool y retorna la ruta del PNG."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            partial(self._build_sync, ohlc, symbol, timeframe),
        )

    def cleanup(self, path: str) -> None:
        """Elimina el PNG temporal tras enviarlo."""
        try:
            os.remove(path)
        except Exception as exc:
            logger.warning(f"No se pudo borrar {path}: {exc}")

    # ── Generación síncrona ───────────────────────────────────

    def _build_sync(self, ohlc: dict, symbol: str, timeframe: str) -> str:
        df = ohlc["df"].copy()

        # Mostramos las últimas 100 velas para legibilidad
        display_n = min(100, len(df))
        df = df.tail(display_n).reset_index(drop=True)

        # ── Layout ────────────────────────────────────────────
        plt.style.use("dark_background")
        fig, (ax_c, ax_v) = plt.subplots(
            2, 1,
            figsize=(16, 9),
            gridspec_kw={"height_ratios": [4, 1], "hspace": 0.04},
            facecolor="#0d1117",
        )

        self._draw_candles(ax_c, df)
        self._draw_levels(ax_c, df)
        self._draw_volume(ax_v, df)
        self._style_axes(ax_c, ax_v, df, symbol, timeframe, display_n, ohlc["count"])

        plt.tight_layout(pad=0.8)

        filename = f"chart_{uuid.uuid4().hex[:10]}.png"
        filepath = os.path.join(_TMP_DIR, filename)
        fig.savefig(filepath, dpi=130, bbox_inches="tight", facecolor="#0d1117")
        plt.close(fig)

        logger.debug(f"Chart saved → {filepath}")
        return filepath

    # ── Dibujo de velas ───────────────────────────────────────

    def _draw_candles(self, ax, df: pd.DataFrame) -> None:
        for i, row in df.iterrows():
            bull     = row["close"] >= row["open"]
            color    = "#26a69a" if bull else "#ef5350"    # verde/rojo TradingView
            body_b   = min(row["open"], row["close"])
            body_h   = max(abs(row["close"] - row["open"]), 1e-10)  # evita altura 0

            # Cuerpo
            ax.add_patch(Rectangle(
                (i - 0.38, body_b), 0.76, body_h,
                linewidth=0.4, edgecolor=color, facecolor=color, alpha=0.9,
            ))
            # Mecha
            ax.plot([i, i], [row["low"], row["high"]],
                    color=color, linewidth=0.9, alpha=0.9, solid_capstyle="round")

        ax.set_xlim(-0.8, len(df) + 9)   # Espacio derecho para etiquetas

    # ── Niveles clave ─────────────────────────────────────────

    def _draw_levels(self, ax, df: pd.DataFrame) -> None:
        n          = len(df)
        high_all   = df["high"].max()
        low_all    = df["low"].min()
        current    = df["close"].iloc[-1]

        recent_n   = max(20, n // 5)
        recent     = df.tail(recent_n)
        swing_h    = recent["high"].max()
        swing_l    = recent["low"].min()

        def hline(y, color, label, ls="--", alpha=0.85, lw=1.0):
            ax.axhline(y, color=color, linewidth=lw, linestyle=ls, alpha=alpha)
            ax.text(n + 0.6, y, f" {label}\n {y:,.5f}",
                    color=color, fontsize=6.5, va="center", linespacing=1.4)

        hline(high_all, "#ffd700", "HH",    ls="--")
        hline(low_all,  "#ff6b6b", "LL",    ls="--")

        # Swing recientes (solo si difieren lo suficiente del HH/LL)
        thresh = (high_all - low_all) * 0.003
        if abs(swing_h - high_all) > thresh:
            hline(swing_h, "#80cbc4", "SH", ls="-.", lw=0.8, alpha=0.7)
        if abs(swing_l - low_all) > thresh:
            hline(swing_l, "#ef9a9a", "SL", ls="-.", lw=0.8, alpha=0.7)

        # Precio actual
        ax.axhline(current, color="#ffffff", linewidth=0.7, linestyle=":", alpha=0.5)
        ax.text(n + 0.6, current, f" Last\n {current:,.5f}",
                color="#ffffff", fontsize=6.5, va="center", linespacing=1.4)

        # Punto medio del rango
        mid = (high_all + low_all) / 2
        ax.axhline(mid, color="#888888", linewidth=0.5, linestyle=":", alpha=0.35)

    # ── Volumen ───────────────────────────────────────────────

    def _draw_volume(self, ax, df: pd.DataFrame) -> None:
        for i, row in df.iterrows():
            color = "#26a69a" if row["close"] >= row["open"] else "#ef5350"
            ax.bar(i, row["volume"], color=color, alpha=0.55, width=0.78)
        ax.set_facecolor("#0d1117")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f"{x/1e6:.1f}M" if x >= 1e6 else f"{x/1e3:.0f}K" if x >= 1e3 else str(int(x))
        ))
        ax.tick_params(colors="#666", labelsize=6)
        ax.set_ylabel("Vol", color="#666", fontsize=7)
        for spine in ax.spines.values():
            spine.set_color("#2a2a2a")

    # ── Estilos y ejes ────────────────────────────────────────

    def _style_axes(
        self, ax_c, ax_v, df: pd.DataFrame,
        symbol: str, timeframe: str, display_n: int, total_n: int,
    ) -> None:
        n = len(df)

        # ── Eje candles ───────────────────────────────────────
        ax_c.set_facecolor("#0d1117")
        ax_c.tick_params(colors="#666", labelsize=7)
        ax_c.set_ylabel("Precio", color="#888", fontsize=8)
        ax_c.set_xticks([])

        # Grid horizontal suave
        ax_c.yaxis.set_minor_locator(mticker.AutoMinorLocator(4))
        ax_c.grid(axis="y", which="major", color="#1e1e2e", linewidth=0.6, alpha=0.7)
        ax_c.grid(axis="y", which="minor", color="#141424", linewidth=0.3, alpha=0.4)

        for spine in ax_c.spines.values():
            spine.set_color("#2a2a2a")

        # ── Título ────────────────────────────────────────────
        last_dt = df["datetime"].iloc[-1]
        if hasattr(last_dt, "strftime"):
            last_str = last_dt.strftime("%Y-%m-%d %H:%M UTC")
        else:
            last_str = str(last_dt)[:16]

        ax_c.set_title(
            f"📊  {symbol}  ·  {timeframe}  ·  {display_n} velas mostradas / {total_n} analizadas"
            f"  ·  {last_str}",
            color="#cccccc", fontsize=10, pad=10, fontweight="bold",
        )

        # ── Eje volumen — X labels ────────────────────────────
        step = max(1, n // 10)
        ticks  = list(range(0, n, step))
        labels = [df["datetime"].iloc[i].strftime("%d/%m %H:%M") for i in ticks]
        ax_v.set_xticks(ticks)
        ax_v.set_xticklabels(labels, rotation=40, ha="right", fontsize=5.5, color="#666")
        ax_v.set_xlim(-0.8, n + 9)
        ax_v.grid(axis="y", color="#1e1e2e", linewidth=0.4, alpha=0.5)

        # ── Marca de agua ─────────────────────────────────────
        ax_c.text(
            0.5, 0.015, "SMC/ICT Bot · Análisis automático",
            transform=ax_c.transAxes, color="#2a2a3a",
            fontsize=8, ha="center", va="bottom",
        )
