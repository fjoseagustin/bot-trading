class BotError(Exception):
    """Base error para el bot"""
    pass

class SymbolNotFoundError(BotError):
    """Símbolo no encontrado en ningún exchange"""
    pass

class APIError(BotError):
    """Error en API externa (Finnhub, Claude, etc.)"""
    pass

class InvalidSymbolError(BotError):
    """Formato de símbolo inválido"""
    pass

class InvalidTimeframeError(BotError):
    """Timeframe inválido o no soportado"""
    pass

class ChartError(BotError):
    """Error al generar gráfico"""
    pass
