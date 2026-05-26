"""
Resuelve símbolos escritos por el usuario → ticker canónico de Finnhub.

Jerarquía de resolución:
  1. ALIAS_MAP  → cobertura inmediata de los activos más comunes
  2. Stock validation  → tickers tipo AAPL, TSLA, etc.
  3. Crypto Binance   → agrega prefijo BINANCE: y sufijo USDT
"""
from __future__ import annotations

from utils.errors import SymbolNotFoundError
from utils.logger import setup_logger

logger = setup_logger(__name__)

# ──────────────────────────────────────────────────────────────
# (finnhub_symbol, asset_type, display_name)
# asset_type: "crypto" | "stock" | "forex"
# ──────────────────────────────────────────────────────────────
ALIAS_MAP: dict[str, tuple[str, str, str]] = {
    # ── Crypto ────────────────────────────────────────────────
    "BTC":      ("BINANCE:BTCUSDT",  "crypto", "Bitcoin"),
    "BITCOIN":  ("BINANCE:BTCUSDT",  "crypto", "Bitcoin"),
    "ETH":      ("BINANCE:ETHUSDT",  "crypto", "Ethereum"),
    "ETHEREUM": ("BINANCE:ETHUSDT",  "crypto", "Ethereum"),
    "SOL":      ("BINANCE:SOLUSDT",  "crypto", "Solana"),
    "SOLANA":   ("BINANCE:SOLUSDT",  "crypto", "Solana"),
    "BNB":      ("BINANCE:BNBUSDT",  "crypto", "BNB"),
    "XRP":      ("BINANCE:XRPUSDT",  "crypto", "XRP"),
    "ADA":      ("BINANCE:ADAUSDT",  "crypto", "Cardano"),
    "DOGE":     ("BINANCE:DOGEUSDT", "crypto", "Dogecoin"),
    "AVAX":     ("BINANCE:AVAXUSDT", "crypto", "Avalanche"),
    "DOT":      ("BINANCE:DOTUSDT",  "crypto", "Polkadot"),
    "MATIC":    ("BINANCE:MATICUSDT","crypto", "Polygon"),
    "LINK":     ("BINANCE:LINKUSDT", "crypto", "Chainlink"),
    "LTC":      ("BINANCE:LTCUSDT",  "crypto", "Litecoin"),
    "UNI":      ("BINANCE:UNIUSDT",  "crypto", "Uniswap"),
    "ATOM":     ("BINANCE:ATOMUSDT", "crypto", "Cosmos"),
    "FIL":      ("BINANCE:FILUSDT",  "crypto", "Filecoin"),

    # ── Forex ─────────────────────────────────────────────────
    "EURUSD":   ("OANDA:EUR_USD", "forex", "EUR/USD"),
    "EUR/USD":  ("OANDA:EUR_USD", "forex", "EUR/USD"),
    "EUR":      ("OANDA:EUR_USD", "forex", "EUR/USD"),
    "GBPUSD":   ("OANDA:GBP_USD", "forex", "GBP/USD"),
    "GBP/USD":  ("OANDA:GBP_USD", "forex", "GBP/USD"),
    "GBP":      ("OANDA:GBP_USD", "forex", "GBP/USD"),
    "USDJPY":   ("OANDA:USD_JPY", "forex", "USD/JPY"),
    "USD/JPY":  ("OANDA:USD_JPY", "forex", "USD/JPY"),
    "USDCHF":   ("OANDA:USD_CHF", "forex", "USD/CHF"),
    "USD/CHF":  ("OANDA:USD_CHF", "forex", "USD/CHF"),
    "AUDUSD":   ("OANDA:AUD_USD", "forex", "AUD/USD"),
    "AUD/USD":  ("OANDA:AUD_USD", "forex", "AUD/USD"),
    "NZDUSD":   ("OANDA:NZD_USD", "forex", "NZD/USD"),
    "NZD/USD":  ("OANDA:NZD_USD", "forex", "NZD/USD"),
    "USDCAD":   ("OANDA:USD_CAD", "forex", "USD/CAD"),
    "USD/CAD":  ("OANDA:USD_CAD", "forex", "USD/CAD"),
    "GBPJPY":   ("OANDA:GBP_JPY", "forex", "GBP/JPY"),
    "GBP/JPY":  ("OANDA:GBP_JPY", "forex", "GBP/JPY"),

    # ── Commodities (como forex en Finnhub) ───────────────────
    "ORO":      ("OANDA:XAU_USD", "forex", "Oro/USD"),
    "GOLD":     ("OANDA:XAU_USD", "forex", "Oro/USD"),
    "XAU":      ("OANDA:XAU_USD", "forex", "Oro/USD"),
    "XAUUSD":   ("OANDA:XAU_USD", "forex", "Oro/USD"),
    "XAU/USD":  ("OANDA:XAU_USD", "forex", "Oro/USD"),
    "PLATA":    ("OANDA:XAG_USD", "forex", "Plata/USD"),
    "SILVER":   ("OANDA:XAG_USD", "forex", "Plata/USD"),
    "XAG":      ("OANDA:XAG_USD", "forex", "Plata/USD"),
    "XAGUSD":   ("OANDA:XAG_USD", "forex", "Plata/USD"),
    "XAG/USD":  ("OANDA:XAG_USD", "forex", "Plata/USD"),
    "OIL":      ("OANDA:BCO_USD", "forex", "Petróleo Brent"),
    "PETROLEO": ("OANDA:BCO_USD", "forex", "Petróleo Brent"),
    "BRENT":    ("OANDA:BCO_USD", "forex", "Petróleo Brent"),
    "WTI":      ("OANDA:WTICO_USD","forex", "WTI/USD"),

    # ── Índices US (como ETF en Finnhub) ──────────────────────
    "SPX":      ("SPY",  "stock", "S&P 500 (SPY)"),
    "SP500":    ("SPY",  "stock", "S&P 500 (SPY)"),
    "S&P500":   ("SPY",  "stock", "S&P 500 (SPY)"),
    "NASDAQ":   ("QQQ",  "stock", "NASDAQ (QQQ)"),
    "NAS":      ("QQQ",  "stock", "NASDAQ (QQQ)"),
    "DOW":      ("DIA",  "stock", "Dow Jones (DIA)"),
    "DJI":      ("DIA",  "stock", "Dow Jones (DIA)"),
    "VIX":      ("UVXY", "stock", "VIX (UVXY)"),
}


class SymbolResolver:
    def __init__(self, finnhub_client) -> None:
        self.finnhub = finnhub_client

    async def resolve(self, symbol_input: str) -> dict:
        """
        Retorna:
          {
            "finnhub_symbol": str,
            "asset_type":     "crypto" | "stock" | "forex",
            "display_name":   str,
          }
        Lanza SymbolNotFoundError si no se puede resolver.
        """
        key = symbol_input.upper().strip().replace("-", "/")

        # 1. Alias directo
        if key in ALIAS_MAP:
            finnhub_sym, asset_type, display = ALIAS_MAP[key]
            logger.debug(f"Resolved '{symbol_input}' → {finnhub_sym} via alias")
            return {"finnhub_symbol": finnhub_sym, "asset_type": asset_type, "display_name": display}

        # 2. Intentar como acción (stock)
        upper = symbol_input.upper()
        is_stock = await self.finnhub.validate_stock(upper)
        if is_stock:
            logger.debug(f"Resolved '{symbol_input}' → stock {upper}")
            return {"finnhub_symbol": upper, "asset_type": "stock", "display_name": upper}

        # 3. Intentar como crypto en Binance (agrega USDT)
        crypto_sym = f"BINANCE:{upper}USDT"
        is_crypto = await self.finnhub.validate_crypto(crypto_sym)
        if is_crypto:
            logger.debug(f"Resolved '{symbol_input}' → crypto {crypto_sym}")
            return {
                "finnhub_symbol": crypto_sym,
                "asset_type": "crypto",
                "display_name": f"{upper}/USDT",
            }

        raise SymbolNotFoundError(
            f"No encontré '{symbol_input}'. "
            "Prueba con el ticker oficial (BTC, ETH, AAPL, ORO, EURUSD…)"
        )
