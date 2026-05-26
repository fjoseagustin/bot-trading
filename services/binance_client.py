"""
Cliente async para Binance API pública (sin autenticación).

Endpoint: GET https://api.binance.com/api/v3/klines
- Gratis, sin API key
- Hasta 1000 velas por llamada
- Soporta H4 nativo (no hay que agregar)
"""
from __future__ import annotations

import httpx
import pandas as pd

from utils.errors import APIError, SymbolNotFoundError
from utils.logger import setup_logger

logger = setup_logger(__name__)

_BASE_URL = "https://api.binance.com/api/v3/klines"

# Timeframe canónico → intervalo Binance
_INTERVAL_MAP: dict[str, str] = {
    "M1":  "1m",
    "M5":  "5m",
    "M15": "15m",
    "H1":  "1h",
    "H4":  "4h",   # ← nativo en Binance, no hay que agregar
    "D":   "1d",
    "W":   "1w",
}

_KLINE_COLS = [
    "timestamp", "open", "high", "low", "close", "volume",
    "close_time", "quote_vol", "num_trades",
    "buy_base_vol", "buy_quote_vol", "ignore",
]


class BinanceClient:

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int = 500,
    ) -> dict:
        """
        symbol   : formato "BINANCE:BTCUSDT" o directamente "BTCUSDT"
        timeframe: clave canónica (M15, H1, H4, D, W)
        count    : velas deseadas (máx 1000 por llamada)
        """
        clean = symbol.replace("BINANCE:", "").upper()

        interval = _INTERVAL_MAP.get(timeframe)
        if not interval:
            raise APIError(f"Timeframe '{timeframe}' no soportado en Binance")

        limit = min(count, 1000)

        params = {"symbol": clean, "interval": interval, "limit": limit}
        logger.debug(f"Binance candles → {clean} {interval} limit={limit}")

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(_BASE_URL, params=params)
        except httpx.TimeoutException:
            raise APIError("Binance API no respondió (timeout)")
        except Exception as exc:
            raise APIError(f"Error de conexión con Binance: {exc}") from exc

        if resp.status_code == 400:
            raise SymbolNotFoundError(
                f"Símbolo '{clean}' no encontrado en Binance. "
                "Verifica el ticker (ej: BTCUSDT, ETHUSDT)"
            )
        if resp.status_code != 200:
            raise APIError(f"Binance API respondió {resp.status_code}")

        raw = resp.json()
        if not raw:
            raise SymbolNotFoundError(
                f"No hay datos de Binance para {clean} {timeframe}"
            )

        df = pd.DataFrame(raw, columns=_KLINE_COLS)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()

        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)

        df["timestamp"] = (df["timestamp"] / 1000).astype(int)   # ms → s
        df["datetime"]  = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.sort_values("datetime").reset_index(drop=True)

        logger.debug(f"Binance devolvió {len(df)} velas")

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
            "stale":      False,   # Binance siempre entrega datos en tiempo real
            "age_hours":  0.0,
        }
