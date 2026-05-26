from utils.errors import InvalidTimeframeError

# Configuración canónica de cada timeframe
TIMEFRAME_CONFIG = {
    "M15": {
        "finnhub_resolution": "15",
        "minutes": 15,
        "label": "15 Minutos",
        "aggregate": False,
    },
    "H1": {
        "finnhub_resolution": "60",
        "minutes": 60,
        "label": "1 Hora",
        "aggregate": False,
    },
    "H4": {
        "finnhub_resolution": "60",   # Descarga H1 y agrega a H4
        "minutes": 240,
        "label": "4 Horas",
        "aggregate": True,
    },
    "D": {
        "finnhub_resolution": "D",
        "minutes": 1440,
        "label": "Daily",
        "aggregate": False,
    },
    "W": {
        "finnhub_resolution": "W",
        "minutes": 10080,
        "label": "Weekly",
        "aggregate": False,
    },
}

TIMEFRAME_LABELS = {k: v["label"] for k, v in TIMEFRAME_CONFIG.items()}

# Aliases para parsear texto libre del usuario
TIMEFRAME_ALIASES: dict[str, str] = {
    # M15
    "M15": "M15", "15M": "M15", "15MIN": "M15", "15MINUTOS": "M15", "15": "M15",
    # H1
    "H1": "H1", "1H": "H1", "1HORA": "H1", "60M": "H1", "60MIN": "H1",
    # H4
    "H4": "H4", "4H": "H4", "4HORAS": "H4",
    # Daily
    "D": "D", "D1": "D", "1D": "D", "DAILY": "D", "DIARIO": "D", "DIA": "D", "DAY": "D",
    # Weekly
    "W": "W", "W1": "W", "1W": "W", "WEEKLY": "W", "SEMANAL": "W", "SEMANA": "W", "WEEK": "W",
}


def parse_timeframe(text: str) -> str | None:
    """Parsea texto libre → clave canónica del timeframe, o None si no reconoce."""
    return TIMEFRAME_ALIASES.get(text.upper().strip())


def validate_timeframe(timeframe: str) -> str:
    """Valida y retorna clave canónica, o lanza InvalidTimeframeError."""
    canonical = TIMEFRAME_ALIASES.get(timeframe.upper().strip())
    if not canonical:
        valid = ", ".join(TIMEFRAME_CONFIG.keys())
        raise InvalidTimeframeError(
            f"Timeframe '{timeframe}' no válido. Opciones: {valid}"
        )
    return canonical
