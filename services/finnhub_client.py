"""
Cliente async para Finnhub API.

Enrutamiento por tipo de activo:
  crypto → BinanceClient    (gratis, sin key, H4 nativo)
  forex  → TwelveDataClient (800 req/día gratis, datos en tiempo real)
  stock  → Finnhub          (plan gratuito OK para acciones US)
              └─ fallback TwelveData si Finnhub devuelve 403/401

Finnhub es síncrono → cada llamada corre en thread pool para no bloquear asyncio.
"""
from __future__ import annotations

import asyncio
import time
from functools import partial

import finnhub
import pandas as pd

import config
from utils.errors import APIError, SymbolNotFoundError
from utils.logger import setup_logger
from utils.timeframe import TIMEFRAME_CONFIG

logger = setup_logger(__name__)


class FinnhubClient:
    def __init__(self) -> None:
        self._client      = finnhub.Client(api_key=config.FINNHUB_API_KEY)
        self._binance     = None   # lazy
        self._twelvedata  = None   # lazy

    def _get_binance(self):
        if self._binance is None:
            from services.binance_client import BinanceClient
            self._binance = BinanceClient()
        return self._binance

    def _get_twelvedata(self):
        if self._twelvedata is None:
            from services.twelvedata_client import TwelveDataClient
            self._twelvedata = TwelveDataClient()
        return self._twelvedata

    # ── Helpers ───────────────────────────────────────────────

    async def _call(self, func, *args, **kwargs):
        """Ejecuta una llamada síncrona de Finnhub en un thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    # ── Validación ────────────────────────────────────────────

    async def validate_stock(self, symbol: str) -> bool:
        """True si Finnhub reconoce el ticker como acción."""
        try:
            profile = await self._call(self._client.company_profile2, symbol=symbol)
            return bool(profile and profile.get("ticker"))
        except Exception:
            return False

    async def validate_crypto(self, symbol: str) -> bool:
        """
        Para crypto usamos Binance directamente.
        True si el símbolo existe en Binance.
        """
        try:
            clean = symbol.replace("BINANCE:", "").upper()
            import httpx
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    "https://api.binance.com/api/v3/klines",
                    params={"symbol": clean, "interval": "1h", "limit": 1},
                )
            return resp.status_code == 200
        except Exception:
            return False

    # ── Datos OHLCV ───────────────────────────────────────────

    async def get_candles(
        self,
        symbol: str,
        asset_type: str,
        timeframe: str,
        count: int = 500,
    ) -> dict:
        """
        Enruta la descarga al cliente correcto según asset_type:
          crypto → BinanceClient
          stock  → Finnhub
          forex  → Finnhub (premium) con error claro si 403
        """
        # ── Crypto → Binance ──────────────────────────────────
        if asset_type == "crypto":
            logger.debug(f"Routing crypto {symbol} → Binance")
            return await self._get_binance().get_candles(symbol, timeframe, count)

        # ── Forex / Commodities → Twelve Data ─────────────────
        if asset_type == "forex":
            logger.debug(f"Routing forex {symbol} → TwelveData")
            return await self._get_twelvedata().get_candles(symbol, timeframe, count)

        # ── Stocks → Finnhub (con fallback a Yahoo Finance) ───
        tf      = TIMEFRAME_CONFIG[timeframe]
        res     = tf["finnhub_resolution"]
        minutes = tf["minutes"]

        to_ts         = int(time.time())
        fetch_minutes = 60 if tf.get("aggregate") else minutes
        buffer        = 3.0
        from_ts       = to_ts - int(fetch_minutes * 60 * count * buffer)

        logger.debug(f"Fetching {asset_type} {symbol} res={res}")

        try:
            raw = await self._fetch_raw(asset_type, symbol, res, from_ts, to_ts)
        except Exception as exc:
            exc_str = str(exc)
            if "403" in exc_str or "401" in exc_str or "access" in exc_str.lower():
                logger.warning(f"Finnhub 403 para {symbol}, usando Twelve Data como fallback")
                return await self._get_twelvedata().get_candles(symbol, timeframe, count)
            raise APIError(f"Finnhub error: {exc}") from exc

        self._check_response(raw, symbol, timeframe)

        df = self._build_df(raw)

        if tf.get("aggregate"):
            df = self._aggregate_h4(df)

        df = df.tail(count).reset_index(drop=True)

        if len(df) < 10:
            raise APIError(
                f"Datos insuficientes: solo {len(df)} velas para {symbol} {timeframe}"
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
            "stale":      False,   # Finnhub entrega datos en tiempo real
            "age_hours":  0.0,
        }

    # ── Privados ──────────────────────────────────────────────

    async def _fetch_raw(
        self, asset_type: str, symbol: str, resolution: str, from_ts: int, to_ts: int
    ) -> dict:
        if asset_type == "stock":
            return await self._call(
                self._client.stock_candles, symbol, resolution, from_ts, to_ts
            )
        elif asset_type == "forex":
            return await self._call(
                self._client.forex_candles, symbol, resolution, from_ts, to_ts
            )
        else:
            raise APIError(f"asset_type desconocido: {asset_type}")

    def _check_response(self, raw: dict, symbol: str, timeframe: str) -> None:
        if not raw:
            raise APIError("Respuesta vacía de Finnhub")
        status = raw.get("s", "")
        if status == "no_data":
            raise SymbolNotFoundError(
                f"No hay datos para {symbol} en {timeframe}. "
                "Verifica el símbolo o prueba otro timeframe."
            )
        if status != "ok":
            raise APIError(f"Finnhub respondió status='{status}'")

    def _build_df(self, raw: dict) -> pd.DataFrame:
        df = pd.DataFrame({
            "timestamp": raw["t"],
            "open":      raw["o"],
            "high":      raw["h"],
            "low":       raw["l"],
            "close":     raw["c"],
            "volume":    raw["v"],
        })
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.sort_values("datetime").drop_duplicates("timestamp").reset_index(drop=True)
        return df

    def _aggregate_h4(self, df: pd.DataFrame) -> pd.DataFrame:
        """Agrega velas H1 → H4 para Finnhub (que no tiene resolución 240)."""
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
