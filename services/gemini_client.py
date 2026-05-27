"""
Cliente async para Google Gemini (SDK google-genai v2+).

Usa la librería google-genai para generar el análisis SMC/ICT.
El system prompt se pasa como instrucción de sistema al crear el chat.
"""
from __future__ import annotations

import asyncio

from google import genai
from google.genai import types

import config
from analysis.smc_prompt import build_system_prompt, build_user_prompt
from utils.errors import APIError
from utils.logger import setup_logger

logger = setup_logger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 8   # segundos entre reintentos para 503


class GeminiClient:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        self._model_name = config.GEMINI_MODEL
        self._system_prompt = build_system_prompt()

    async def analyze(
        self,
        ohlc: dict,
        symbol: str,
        timeframe: str,
        asset_type: str,
        htf_ohlc: dict | None = None,
        htf_timeframe: str | None = None,
    ) -> str:
        """
        Envía los datos OHLCV a Gemini y retorna el análisis SMC/ICT como texto.
        Si se proveen htf_ohlc y htf_timeframe, incluye contexto multi-timeframe.
        La SDK de Gemini es síncrona; se ejecuta en un executor para no bloquear el event loop.
        """
        user_prompt = build_user_prompt(
            ohlc, symbol, timeframe, asset_type,
            htf_ohlc=htf_ohlc, htf_timeframe=htf_timeframe,
        )

        logger.debug(f"Calling Gemini {self._model_name} for {symbol} {timeframe}")

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._client.models.generate_content(
                        model=self._model_name,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=self._system_prompt,
                            max_output_tokens=4096,   # Gemini 2.5 usa tokens de razonamiento internos
                            temperature=0.4,
                            thinking_config=types.ThinkingConfig(
                                thinking_budget=1024,  # Cap razonamiento: deja ~3072 para el texto
                            ),
                        ),
                    ),
                )
                break   # éxito → salir del loop

            except Exception as exc:
                last_exc = exc
                exc_str = str(exc)
                is_retryable = "503" in exc_str or "UNAVAILABLE" in exc_str or "429" in exc_str
                if is_retryable and attempt < _MAX_RETRIES:
                    logger.warning(
                        f"Gemini intento {attempt}/{_MAX_RETRIES} falló ({exc_str[:80]}), "
                        f"reintentando en {_RETRY_DELAY}s…"
                    )
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                # Error no recuperable o último intento
                logger.exception(f"Error llamando a Gemini (intento {attempt}): {exc}")
                if "503" in exc_str or "UNAVAILABLE" in exc_str:
                    raise APIError(
                        "Gemini está temporalmente sobrecargado (503). "
                        "Intentá de nuevo en unos segundos."
                    ) from exc
                if "401" in exc_str or "API_KEY" in exc_str or "invalid" in exc_str.lower():
                    raise APIError(
                        "API key de Gemini inválida. "
                        "Verificá la variable Gemini_API_KEY en Railway."
                    ) from exc
                raise APIError(f"Error en Gemini API: {exc}") from exc

        # Log de uso si está disponible
        usage = getattr(response, "usage_metadata", None)
        if usage:
            logger.info(
                f"Gemini tokens — input: {getattr(usage, 'prompt_token_count', '?')}, "
                f"output: {getattr(usage, 'candidates_token_count', '?')}"
            )

        # Extraer texto de los parts directamente (más robusto que response.text)
        try:
            parts = response.candidates[0].content.parts if response.candidates else None
            if parts:
                text = "".join(p.text for p in parts if hasattr(p, "text") and p.text)
                if text:
                    return text
            finish = response.candidates[0].finish_reason if response.candidates else "desconocido"
            logger.error(f"Gemini devolvió respuesta vacía. finish_reason={finish}")
            raise APIError(f"Gemini no generó texto (finish_reason={finish}). Puede ser MAX_TOKENS o SAFETY.")
        except APIError:
            raise
        except Exception as exc:
            logger.error(f"No se pudo extraer texto de la respuesta Gemini: {exc}")
            raise APIError(f"Respuesta inesperada de Gemini: {exc}") from exc
