# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the bot

```bash
# Activate virtual environment (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and populate environment variables
cp .env.example .env   # then edit .env

# Start the bot
python bot.py
```

## Environment variables

| Variable | Required | Default |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — |
| `FINNHUB_API_KEY` | ✅ | — |
| `ANTHROPIC_API_KEY` | ✅ | — |
| `TWELVEDATA_API_KEY` | ✅ for forex/commodities | — |
| `CLAUDE_MODEL` | | `claude-sonnet-4-6` |
| `LOG_LEVEL` | | `INFO` |
| `CANDLES_COUNT` | | `500` |

`config.py` loads `.env` at import time and `config.validate()` is called at startup to fail fast on missing keys.

## Architecture

### Request pipeline (happy path)

```
User: "Analiza BTC H1"
  └─ handlers/messages.py handle_message()
       ├─ _parse_message()         → (symbol="BTC", timeframe="H1")
       ├─ SymbolResolver.resolve() → {finnhub_symbol, asset_type, display_name}
       ├─ FinnhubClient.get_candles() → ohlc dict
       ├─ _build_stats_block()    → price stats message (sent immediately)
       ├─ ClaudeClient.analyze()  → SMC/ICT analysis text
       └─ sends chunked Markdown messages
```

If the user omits the timeframe, `handle_message()` sends an inline keyboard; `handle_callback()` receives the selection and calls `run_analysis()` with the same pipeline.

### Data routing by asset type

`FinnhubClient.get_candles()` routes requests to different providers:

| Asset type | Provider | Notes |
|---|---|---|
| `crypto` | `BinanceClient` | Public API, no key required, H4 native |
| `forex` | `TwelveDataClient` | 800 req/day free; stocks fall back here on Finnhub 403 |
| `stock` | Finnhub | Free plan; fallback to TwelveData on 403/401 |

**H4 aggregation**: Finnhub has no 240-minute resolution. `TIMEFRAME_CONFIG["H4"]` fetches H1 (`finnhub_resolution: "60"`, `aggregate: True`) and `_aggregate_h4()` resamples with `pandas resample("4h")`. BinanceClient and TwelveDataClient support H4 natively.

### The `ohlc` dict

All three data clients return the same dict shape consumed by `ClaudeClient` and `handlers/messages.py`:

```python
{
  "df":         pd.DataFrame,  # columns: timestamp, datetime, open, high, low, close, volume
  "open/high/low/close/volume": list[float],
  "timestamps": list[int],
  "datetimes":  list,
  "count":      int,
  "stale":      bool,
  "staleness":  "fresh" | "market_closed" | "provider_lag",
  "age_hours":  float,
}
```

### Symbol resolution

`SymbolResolver.resolve()` applies a three-step hierarchy:
1. `ALIAS_MAP` in `symbol_resolver.py` — covers common crypto, forex, commodities, indices
2. Finnhub `company_profile2` validation — for stocks not in the alias map
3. Binance klines validation — for unknown crypto tickers (`<TICKER>USDT`)

### Claude integration

`ClaudeClient` uses **Anthropic prompt caching**: `build_system_prompt()` returns a static string tagged with `cache_control: ephemeral` (5-min TTL). The user prompt is dynamically built by `build_user_prompt()` from the `ohlc` dict. Output is capped at 1000 tokens to fit the dense SMC/ICT format.

### Concurrency model

- Bot runs `python-telegram-bot` in **long-polling** mode (no webhook/port needed).
- Finnhub's synchronous SDK is wrapped in `asyncio.get_event_loop().run_in_executor(None, ...)`.
- `ChartBuilder.build()` also offloads matplotlib to the thread pool.
- `BinanceClient` and `TwelveDataClient` use `httpx.AsyncClient` directly (native async).

### Global service instances

`handlers/messages.py` creates one instance of each service at module import time:
```python
_finnhub       = FinnhubClient()
_claude        = ClaudeClient()
_resolver      = SymbolResolver(_finnhub)
_chart_builder = ChartBuilder()
```

The chart is currently disabled in the pipeline (see comment in `run_analysis()`) but `ChartBuilder` remains available.

## Deployment

Deployed as a **Background Worker** on Render.com (not a Web Service — no HTTP port). The `Procfile` (`worker: python bot.py`) and `runtime.txt` (`python-3.12.3`) configure the build.
