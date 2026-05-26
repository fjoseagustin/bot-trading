"""
Carga y valida variables de entorno.
Importar este módulo antes que cualquier servicio.
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)  # override=True: el .env siempre tiene prioridad sobre env vars del sistema

TELEGRAM_BOT_TOKEN: str  = os.getenv("TELEGRAM_BOT_TOKEN", "")
FINNHUB_API_KEY: str     = os.getenv("FINNHUB_API_KEY", "")
GEMINI_API_KEY: str      = os.getenv("Gemini_API_KEY", "")
TWELVEDATA_API_KEY: str  = os.getenv("TWELVEDATA_API_KEY", "")
GEMINI_MODEL: str        = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
LOG_LEVEL: str           = os.getenv("LOG_LEVEL", "INFO")
CANDLES_COUNT: int       = int(os.getenv("CANDLES_COUNT", "500"))


def validate() -> None:
    """Verifica que todas las variables críticas estén presentes."""
    required = {
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "FINNHUB_API_KEY":    FINNHUB_API_KEY,
        "Gemini_API_KEY":     GEMINI_API_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(
            f"Variables de entorno faltantes: {', '.join(missing)}\n"
            "Copia .env.example → .env y completa los valores."
        )
