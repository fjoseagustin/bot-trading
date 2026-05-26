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
    ) -> str:
        """
        Envía los datos OHLCV a Gemini y retorna el análisis SMC/ICT como texto.
        La SDK de Gemini es síncrona; se ejecuta en un executor para no bloquear el event loop.
        """
        user_prompt = build_user_prompt(ohlc, symbol, timeframe, asset_type)

        logger.debug(f"Calling Gemini {self._model_name} for {symbol} {timeframe}")

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

        except Exception as exc:
            logger.exception(f"Error llamando a Gemini: {exc}")
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
