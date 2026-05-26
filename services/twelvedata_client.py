"""
Cliente async para Twelve Data API.

Plan gratuito (sin tarjeta):
  - 800 req/día | 8 req/min
  - Forex:       EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, NZD/USD, USD/CAD, GBP/JPY
  - Commodities: XAU/USD (Oro), XAG/USD (Plata), WTI/USD, BRENT/USD
  - Datos en tiempo real (sin lag)

Registro: https://twelvedata.com → Dashboard → API Keys
"""
from __future__ import annotations

import pandas as pd
import httpx

import config
from utils.errors import APIError, SymbolNotFoundError
from utils.logger import setup_logger

logger = setup_logger(__name__)

_BASE_URL = "https://api.twelvedata.com/time_series"

# ── OANDA symbol → Twelve Data symbol ────────────────────────
OANDA_TO_TD: dict[str, str] = {
    # Forex
    "OANDA:EUR_USD":   "EUR/USD",
    "OANDA:GBP_USD":   "GBP/USD",
    "OANDA:USD_JPY":   "USD/JPY",
    "OANDA:USD_CHF":   "USD/CHF",
    "OANDA:AUD_USD":   "AUD/USD",
    "OANDA:NZD_USD":   "NZD/USD",
    "OANDA:USD_CAD":   "USD/CAD",
    "OANDA:GBP_JPY":   "GBP/JPY",
    # Commodities
    "OANDA:XAU_USD":   "XAU/USD",    # Oro
    "OANDA:XAG_USD":   "XAG/USD",    # Plata
    "OANDA:BCO_USD":   "BRENT/USD",  # Brent
    "OANDA:WTICO_USD": "WTI/USD",    # WTI
}

# ── Timeframe canónico → intervalo Twelve Data ────────────────
TF_TO_TD: dict[str, str] = {
    "M15": "15min",
    "H1":  "1h",
    "H4":  "4h",    # nativo en TD — no hay que agregar
    "D":   "1day",
    "W":   "1week",
}

# ── Antigüedad máxima aceptable (horas) ──────────────────────
MAX_AGE_HOURS: dict[str, float] = {
    "M15": 4,
    "H1":  6,
    "H4":  20,
    "D":   50,
    "W":   200,
}


class TwelveDataClient:

    def to_td_symbol(self, oanda_symbol: str) -> str:
        """Convierte símbolo OANDA → Twelve Data."""
        return OANDA_TO_TD.get(oanda_symbol, oanda_symbol)

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int = 500,
    ) -> dict:
        """
        symbol   : formato OANDA (OANDA:XAU_USD) o directo (XAU/USD)
        timeframe: clave canónica (M15, H1, H4, D, W)
        count    : velas deseadas (máx 5000)
        """
        if not config.TWELVEDATA_API_KEY:
            raise APIError(
                "TWELVEDATA_API_KEY no configurada. "
                "Registrate en twelvedata.com y agrega la key en .env"
            )

        td_symbol = self.to_td_symbol(symbol)
        interval  = TF_TO_TD.get(timeframe)

        if not interval:
            raise APIError(f"Timeframe '{timeframe}' no soportado en Twelve Data")

        params = {
            "symbol":     td_symbol,
            "interval":   interval,
            "outputsize": min(count, 5000),
            "order":      "ASC",          # oldest → newest
            "timezone":   "UTC",          # forzar UTC — sin esto usa timezone del exchange
            "apikey":     config.TWELVEDATA_API_KEY,
            "format":     "JSON",
        }

        logger.debug(
            f"TwelveData → {td_symbol} {interval} outputsize={params['outputsize']}"
        )

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(_BASE_URL, params=params)
        except httpx.TimeoutException:
            raise APIError("Twelve Data API no respondió (timeout 15s)")
        except Exception as exc:
            raise APIError(f"Error de conexión con Twelve Data: {exc}") from exc

        if resp.status_code != 200:
            raise APIError(f"Twelve Data respondió HTTP {resp.status_code}")

        data = resp.json()

        # ── Manejo de errores de la API ───────────────────────
        status  = data.get("status", "")
        if status != "ok":
            code    = data.get("code", 0)
            message = data.get("message", "Sin mensaje")
            msg_lo  = message.lower()

            if code == 400 or "not found" in msg_lo or "invalid symbol" in msg_lo:
                raise SymbolNotFoundError(
                    f"Símbolo '{td_symbol}' no encontrado en Twelve Data. "
                    "Verifica el par (ej: XAU/USD, EUR/USD)."
                )
            if code == 429:
                raise APIError(
                    "Twelve Data: límite de requests alcanzado (800/día o 8/min). "
                    "Intentá en unos minutos."
                )
            if code == 401 or "api" in msg_lo and "key" in msg_lo:
                raise APIError(
                    f"Twelve Data: API key inválida o expirada — {message}"
                )
            raise APIError(f"Twelve Data error (código {code}): {message}")

        values = data.get("values", [])
        if not values:
            raise SymbolNotFoundError(
                f"No hay datos en Twelve Data para {td_symbol} {timeframe}. "
                "El mercado puede estar cerrado o el símbolo no está disponible en tu plan."
            )

        # ── Construcción del DataFrame ────────────────────────
        df = pd.DataFrame(values)

        # Datetime: Twelve Data devuelve strings UTC ("2026-05-25 14:00:00")
        df["datetime"] = pd.to_datetime(df["datetime"]).dt.tz_localize("UTC")

        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                df[col] = 0.0

        df["timestamp"] = (df["datetime"].astype("int64") // 10**9).astype(int)

        df = (
            df[["timestamp", "datetime", "open", "high", "low", "close", "volume"]]
            .sort_values("datetime")
            .dropna(subset=["open", "close"])
            .reset_index(drop=True)
        )

        # ── Eliminar velas de fin de semana (oro/forex no opera Sáb/Dom) ──
        # Primero filtramos por día de semana (determinístico):
        #   - Sábado completo
        #   - Domingo antes de las 21:00 UTC (mercado reabre ~21:00)
        # Twelve Data a veces genera velas con rango $0.27 en weekends,
        # demasiado grandes para el filtro de rango pero igualmente sintéticas.
        df = self._drop_weekend_candles(df, timeframe)

        # ── Eliminar cualquier vela sintética residual ────────
        # Rango < 1% de la mediana → captura stubs que quedaron
        df = self._drop_synthetic_candles(df)

        if len(df) < 10:
            raise APIError(
                f"Datos insuficientes: solo {len(df)} velas para {symbol} {timeframe}"
            )

        # ── Clasificación de frescura ─────────────────────────
        age_hours = self._age_hours(df)
        staleness = self._classify_staleness(df, timeframe)
        stale     = staleness == "provider_lag"

        logger.info(
            f"{symbol} {timeframe} — última vela hace {age_hours:.1f}h [{staleness}]"
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

    # ── Helpers ───────────────────────────────────────────────

    def _drop_weekend_candles(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """
        Elimina velas de sábado y domingo para timeframes intraday.
        Oro y forex NO operan en fin de semana:
          - Sábado: completamente cerrado
          - Domingo: cerrado hasta ~21:00 UTC (apertura Sydney/Asia)
        Para D y W Twelve Data genera correctamente una sola vela semanal
        (no incluye días individuales de fin de semana).
        """
        if timeframe in ("D", "W"):
            return df   # barras diarias/semanales no tienen este problema

        dow  = df["datetime"].dt.dayofweek   # 0=Lun … 5=Sáb, 6=Dom
        hour = df["datetime"].dt.hour

        is_saturday    = dow == 5
        is_sunday_pre  = (dow == 6) & (hour < 21)   # Dom antes de las 21:00 UTC

        mask   = ~(is_saturday | is_sunday_pre)
        before = len(df)
        df     = df[mask].reset_index(drop=True)
        removed = before - len(df)
        if removed:
            logger.debug(f"Velas de fin de semana eliminadas: {removed}")
        return df

    def _drop_synthetic_candles(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Elimina velas sintéticas que Twelve Data inserta en fin de semana.
        Criterio: rango (high-low) < 1% de la mediana del resto de velas.
        Para XAU/USD H1: mediana ~$3-5 → umbral ~$0.03-0.05.
        Una vela legítima (incluso un doji en oro) tiene al menos $0.50 de rango.
        """
        candle_range = df["high"] - df["low"]
        p50 = candle_range.median()
        if p50 <= 0:
            return df
        threshold = p50 * 0.01
        before = len(df)
        df = df[candle_range >= threshold].reset_index(drop=True)
        removed = before - len(df)
        if removed:
            logger.debug(f"Velas sintéticas eliminadas: {removed} (umbral={threshold:.5f})")
        return df

    def _age_hours(self, df: pd.DataFrame) -> float:
        last_dt = df["datetime"].iloc[-1]
        now_utc = pd.Timestamp.now(tz="UTC")
        return (now_utc - last_dt).total_seconds() / 3600

    def _is_weekend_gap(self, df: pd.DataFrame, timeframe: str) -> bool:
        """
        True si el gap entre última vela y ahora es explicable por el fin de semana.
        Última vela = viernes + ahora = sábado/domingo/lunes → cierre normal.
        """
        last_dt  = df["datetime"].iloc[-1]
        now_utc  = pd.Timestamp.now(tz="UTC")
        last_dow = last_dt.weekday()   # 0=Lun…4=Vie, 5=Sáb, 6=Dom
        now_dow  = now_utc.weekday()
        age_h    = (now_utc - last_dt).total_seconds() / 3600

        # Última vela es viernes + ahora es Sáb/Dom/Lun + gap < 90h
        if last_dow == 4 and now_dow in (5, 6, 0) and age_h < 90:
            return True
        # Última vela es domingo (apertura Asia) + ahora es domingo/lunes
        if last_dow == 6 and now_dow in (6, 0) and age_h < 24:
            return True
        return False

    def _classify_staleness(self, df: pd.DataFrame, timeframe: str) -> str:
        """
        "fresh"         — datos actualizados (dentro del umbral)
        "market_closed" — gap explicado por cierre de fin de semana/festivo
        "provider_lag"  — datos desactualizados (no esperado con Twelve Data)
        """
        age_h = self._age_hours(df)
        max_h = MAX_AGE_HOURS.get(timeframe, 48)

        if age_h <= max_h:
            return "fresh"
        if self._is_weekend_gap(df, timeframe):
            return "market_closed"
        return "provider_lag"
