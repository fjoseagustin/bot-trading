"""
Cliente async para Yahoo Finance (yfinance).

Cubre gratis y sin API key:
  - Forex:       EURUSD=X, GBPUSD=X, USDJPY=X …
  - Commodities: GC=F / XAUUSD=X (Oro), SI=F (Plata), CL=F (WTI), BZ=F (Brent)
  - Acciones:    AAPL, TSLA, MSFT … (fallback si Finnhub falla)

ESTRATEGIA DE DATOS FRESCOS:
  - Usa start/end explícito (más fiable que period)
  - Para activos con ticker alternativo (ej. GC=F → XAUUSD=X), intenta el
    alternativo si los datos del primario están desactualizados
  - Clasifica staleness en tres estados: fresh / market_closed / provider_lag
"""
from __future__ import annotations

import asyncio
import datetime
from functools import partial

import pandas as pd
import yfinance as yf

from utils.errors import APIError, SymbolNotFoundError
from utils.logger import setup_logger

logger = setup_logger(__name__)

# ── Mapa OANDA symbol → (ticker primario, ticker alternativo) ─
# El alternativo se prueba si el primario da datos obsoletos.
OANDA_TO_YF: dict[str, tuple[str, str | None]] = {
    # Forex
    "OANDA:EUR_USD":   ("EURUSD=X",   None),
    "OANDA:GBP_USD":   ("GBPUSD=X",   None),
    "OANDA:USD_JPY":   ("USDJPY=X",   None),
    "OANDA:USD_CHF":   ("USDCHF=X",   None),
    "OANDA:AUD_USD":   ("AUDUSD=X",   None),
    "OANDA:NZD_USD":   ("NZDUSD=X",   None),
    "OANDA:USD_CAD":   ("USDCAD=X",   None),
    "OANDA:GBP_JPY":   ("GBPJPY=X",   None),
    # Commodities — primario: futuros | alternativo: spot/ETF
    "OANDA:XAU_USD":   ("GC=F",       "XAUUSD=X"),   # Oro
    "OANDA:XAG_USD":   ("SI=F",       "XAGUSD=X"),   # Plata
    "OANDA:BCO_USD":   ("BZ=F",       None),          # Brent
    "OANDA:WTICO_USD": ("CL=F",       None),          # WTI
}

# ── Timeframe → (intervalo yfinance, días hacia atrás) ────────
TF_TO_YF: dict[str, tuple[str, int]] = {
    "M15": ("15m",  60),    # límite yf para intraday: 60 días
    "H1":  ("1h",   60),
    "H4":  ("1h",   90),    # descarga H1, agrega × 4
    "D":   ("1d",   730),
    "W":   ("1wk", 3650),
}

# ── Antigüedad máxima aceptable (horas) ───────────────────────
# Antes de aplicar el ajuste de fin de semana
MAX_AGE_HOURS: dict[str, float] = {
    "M15": 4,
    "H1":  6,
    "H4":  20,
    "D":   50,
    "W":   200,
}


class YFinanceClient:

    def to_yf_symbols(self, symbol: str) -> tuple[str, str | None]:
        """Devuelve (ticker_primario, ticker_alternativo)."""
        return OANDA_TO_YF.get(symbol, (symbol, None))

    # Mantener compatibilidad con código que usa to_yf_symbol (singular)
    def to_yf_symbol(self, symbol: str) -> str:
        primary, _ = self.to_yf_symbols(symbol)
        return primary

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int = 500,
    ) -> dict:
        primary, alternative = self.to_yf_symbols(symbol)
        interval, days       = TF_TO_YF.get(timeframe, ("1d", 730))

        end_dt   = datetime.date.today() + datetime.timedelta(days=1)
        start_dt = end_dt - datetime.timedelta(days=days)

        # ── Intento 1: ticker primario ────────────────────────
        logger.debug(f"YFinance → {primary}  interval={interval}  {start_dt}→{end_dt}")
        df = await self._fetch(primary, interval, start_dt, end_dt)

        # ── Intento 2: alternativo si primario está desactualizado
        if df is not None and not df.empty and alternative:
            age_h = self._age_hours(df)
            max_h = MAX_AGE_HOURS.get(timeframe, 48)
            if age_h > max_h and not self._is_weekend_gap(df, timeframe):
                logger.info(
                    f"Primario {primary} desactualizado ({age_h:.1f}h). "
                    f"Probando alternativo {alternative}…"
                )
                df_alt = await self._fetch(alternative, interval, start_dt, end_dt)
                if df_alt is not None and not df_alt.empty:
                    alt_age = self._age_hours(df_alt)
                    if alt_age < age_h:
                        logger.info(
                            f"Alternativo {alternative} más fresco "
                            f"({alt_age:.1f}h < {age_h:.1f}h). Usando alternativo."
                        )
                        df = df_alt

        if df is None or df.empty:
            raise SymbolNotFoundError(
                f"No hay datos en Yahoo Finance para '{symbol}'. "
                "Verifica el símbolo o prueba otro timeframe."
            )

        # H4: agrega H1 × 4
        if timeframe == "H4":
            df = self._resample_h4(df)

        df = df.tail(count).reset_index(drop=True)

        if len(df) < 10:
            raise APIError(
                f"Datos insuficientes: solo {len(df)} velas para {symbol} {timeframe}"
            )

        # ── Clasificación de frescura ─────────────────────────
        age_hours    = self._age_hours(df)
        staleness    = self._classify_staleness(df, timeframe)
        stale        = staleness == "provider_lag"

        logger.info(
            f"{symbol} {timeframe} — última vela hace {age_hours:.1f}h "
            f"[{staleness}]"
        )

        return {
            "df":         df,
            "open":       df["open"].tolist(),
            "high":       df["high"].tolist(),
            "low":        df["low"].tolist(),
            "close":      df["close"].tolist(),
            "volume":     df["volume"].tolist(),
            "timestamps": df["timestamp"].tolist(),
            "datetimes":  df["datetime"].tolist(),
            "count":      len(df),
            "stale":      stale,
            "staleness":  staleness,   # "fresh" | "market_closed" | "provider_lag"
            "age_hours":  round(age_hours, 1),
        }

    # ── Privados ──────────────────────────────────────────────

    async def _fetch(
        self,
        yf_sym: str,
        interval: str,
        start: datetime.date,
        end: datetime.date,
    ) -> pd.DataFrame | None:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            partial(self._download_sync, yf_sym, interval, start, end),
        )

    def _download_sync(
        self,
        yf_sym: str,
        interval: str,
        start: datetime.date,
        end: datetime.date,
    ) -> pd.DataFrame | None:
        try:
            hist = yf.Ticker(yf_sym).history(
                start=start,
                end=end,
                interval=interval,
                auto_adjust=True,
                prepost=False,
                repair=True,    # corrige datos corruptos/faltantes
            )
        except Exception as exc:
            logger.error(f"yfinance error para {yf_sym}: {exc}")
            return None

        if hist is None or hist.empty:
            return None

        df = hist.reset_index()
        df.columns = [str(c).lower() for c in df.columns]

        date_col = next((c for c in df.columns if c in ("datetime", "date")), None)
        if date_col is None:
            logger.error(f"Sin columna de fecha en {yf_sym}")
            return None

        df = df.rename(columns={date_col: "datetime"})

        if hasattr(df["datetime"].dt, "tz") and df["datetime"].dt.tz is None:
            df["datetime"] = df["datetime"].dt.tz_localize("UTC")
        else:
            try:
                df["datetime"] = df["datetime"].dt.tz_convert("UTC")
            except Exception:
                pass

        df["timestamp"] = (df["datetime"].astype("int64") // 10**9).astype(int)

        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                df[col] = 0.0

        df = (
            df[["timestamp", "datetime", "open", "high", "low", "close", "volume"]]
            .copy()
            .sort_values("datetime")
            .dropna(subset=["open", "close"])
            .reset_index(drop=True)
        )
        return df

    def _age_hours(self, df: pd.DataFrame) -> float:
        last_dt = df["datetime"].iloc[-1]
        now_utc = pd.Timestamp.now(tz="UTC")
        return (now_utc - last_dt).total_seconds() / 3600

    def _is_weekend_gap(self, df: pd.DataFrame, timeframe: str) -> bool:
        """
        True si el gap entre última vela y ahora es explicable por el fin de semana.
        Lógica: la última vela es viernes Y ahora es sábado, domingo o lunes temprano.
        """
        last_dt = df["datetime"].iloc[-1]
        now_utc = pd.Timestamp.now(tz="UTC")
        last_dow = last_dt.weekday()   # 0=Lun … 4=Vie, 5=Sáb, 6=Dom
        now_dow  = now_utc.weekday()
        age_h    = (now_utc - last_dt).total_seconds() / 3600

        # Última vela es viernes + ahora es Sáb/Dom/Lun + gap < 90h
        if last_dow == 4 and now_dow in (5, 6, 0) and age_h < 90:
            return True
        # Última vela es domingo (apertura) + ahora es domingo/lunes
        if last_dow == 6 and now_dow in (6, 0) and age_h < 24:
            return True
        return False

    def _classify_staleness(self, df: pd.DataFrame, timeframe: str) -> str:
        """
        Clasifica la frescura de los datos:
          "fresh"        — datos actualizados
          "market_closed" — gap explicado por cierre de fin de semana/festivo
          "provider_lag"  — datos desactualizados por lag del proveedor
        """
        age_h = self._age_hours(df)
        max_h = MAX_AGE_HOURS.get(timeframe, 48)

        if age_h <= max_h:
            return "fresh"

        if self._is_weekend_gap(df, timeframe):
            return "market_closed"

        return "provider_lag"

    def _resample_h4(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy().set_index("datetime")
        agg = df.resample("4h", origin="epoch").agg({
            "open":      "first",
            "high":      "max",
            "low":       "min",
            "close":     "last",
            "volume":    "sum",
            "timestamp": "first",
        }).dropna(subset=["open"])
        return agg.reset_index()
