# 📊 Bot de Análisis SMC/ICT para Telegram

Bot de Telegram que analiza mercados financieros con metodología **Smart Money Concepts (SMC)** e **ICT** usando Claude Sonnet + Finnhub API.

---

## ✨ Qué hace

1. El usuario escribe `Analiza BTC H1`
2. El bot obtiene 500 velas OHLCV de Finnhub en tiempo real
3. Genera un gráfico de velas (Matplotlib) con niveles clave
4. Envía el gráfico inmediatamente
5. Llama a Claude Sonnet con los datos + prompt SMC/ICT experto
6. Responde con análisis estructurado:
   - Sesgo dominante
   - BOS / CHOCH
   - Order Blocks
   - Fair Value Gaps
   - Zonas de liquidez
   - Escenarios probabilísticos
   - Operación recomendada (entrada · SL · TP · R:R)

---

## 🚀 Setup local

### 1. Clonar y crear entorno virtual

```bash
git clone <repo>
cd "Bot Trading"
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
# Edita .env con tus API keys
```

### 4. Obtener API Keys

| Servicio | URL | Plan |
|---|---|---|
| **Telegram Bot Token** | Habla con [@BotFather](https://t.me/BotFather) en Telegram | Gratis |
| **Finnhub API Key** | [finnhub.io/register](https://finnhub.io/register) | Plan gratuito OK |
| **Anthropic API Key** | [console.anthropic.com](https://console.anthropic.com) | De pago |

### 5. Ejecutar

```bash
python bot.py
```

---

## 📦 Deploy en Render.com

### Paso a paso

1. Sube el código a un repositorio GitHub (privado recomendado)
2. En [render.com](https://render.com) → **New → Background Worker**
3. Conecta el repositorio
4. Configura:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
5. En **Environment Variables**, añade:
   - `TELEGRAM_BOT_TOKEN`
   - `FINNHUB_API_KEY`
   - `ANTHROPIC_API_KEY`
   - `CLAUDE_MODEL` = `claude-sonnet-4-6`
   - `LOG_LEVEL` = `INFO`
6. Deploy → el bot arranca automáticamente

> **Nota:** Usa tipo **Background Worker** (no Web Service). El bot usa long-polling, no necesita puerto HTTP.

---

## 💬 Comandos disponibles

| Comando | Descripción |
|---|---|
| `/start` | Bienvenida e instrucciones |
| `/help` | Ayuda completa |
| `/timeframes` | Lista de timeframes |
| `Analiza BTC H1` | Análisis completo |
| `Analiza ORO Daily` | Con cualquier activo |
| `Analiza AAPL H4` | Acciones |
| `Analiza EURUSD M15` | Forex |
| `Analiza ETH` | Sin timeframe → bot pregunta |

---

## 🗂️ Estructura del proyecto

```
Bot Trading/
├── bot.py                    # Entry point
├── config.py                 # Variables de entorno
├── requirements.txt
├── Procfile                  # Render deploy
├── runtime.txt               # Python version
├── .env.example
│
├── handlers/
│   ├── commands.py           # /start /help /timeframes
│   └── messages.py           # Orchestrador del pipeline
│
├── services/
│   ├── finnhub_client.py     # API Finnhub (OHLCV)
│   ├── claude_client.py      # API Claude Sonnet
│   └── symbol_resolver.py    # BTC → BINANCE:BTCUSDT
│
├── analysis/
│   ├── chart_builder.py      # Gráfico Matplotlib
│   └── smc_prompt.py         # Prompts SMC/ICT para Claude
│
└── utils/
    ├── timeframe.py          # Normalización M15/H1/H4/D/W
    ├── errors.py             # Excepciones custom
    └── logger.py             # Logging estructurado
```

---

## ⚙️ Decisiones de arquitectura

- **Long-polling** (no webhook) → más simple, funciona sin URL pública
- **Prompt caching** en el system prompt → ahorra ~80% de tokens de entrada en llamadas repetidas
- **H4 por agregación** → Finnhub no soporta 240min; descargamos H1 y reagrupamos con pandas resample
- **Imagen primero** → el gráfico se envía antes del análisis para mejor UX percibida
- **Stateless** → cada análisis es independiente, sin base de datos
- **Thread pool** → las llamadas síncronas de Finnhub se ejecutan en executor para no bloquear asyncio

---

## 🔧 Variables de entorno

| Variable | Descripción | Default |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot | *requerido* |
| `FINNHUB_API_KEY` | API key de Finnhub | *requerido* |
| `ANTHROPIC_API_KEY` | API key de Anthropic | *requerido* |
| `CLAUDE_MODEL` | Modelo de Claude | `claude-sonnet-4-6` |
| `LOG_LEVEL` | Nivel de logs | `INFO` |
| `CANDLES_COUNT` | Velas a analizar | `500` |
