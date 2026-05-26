"""
Cliente async para Anthropic Claude Sonnet.

Usa prompt caching en el system prompt SMC/ICT (cache_control: ephemeral)
→ TTL 5 min, ahorra tokens y reduce latencia en llamadas repetidas.
"""
from __future__ import annotations

import anthropic

import config
from analysis.smc_prompt import build_system_prompt, build_user_prompt
from utils.errors import APIError
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ClaudeClient:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self._model  = config.CLAUDE_MODEL

    async def analyze(
        self,
        ohlc: dict,
        symbol: str,
        timeframe: str,
        asset_type: str,
    ) -> str:
        """
        Envía los datos OHLCV a Claude y retorna el análisis SMC/ICT como texto.
        El system prompt se marca con cache_control para reutilizarlo entre llamadas.
        """
        system_prompt = build_system_prompt()
        user_prompt   = build_user_prompt(ohlc, symbol, timeframe, asset_type)

        logger.debug(f"Calling Claude {self._model} for {symbol} {timeframe}")

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1000,  # formato denso: ~880-950 tokens output; margen para CIERRE completo
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},  # Prompt caching
                    }
                ],
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
            )
        except anthropic.APIStatusError as exc:
            logger.error(f"Anthropic API error {exc.status_code}: {exc.message}")
            raise APIError(f"Error en Claude API ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise APIError(f"Error de conexión con Claude: {exc}") from exc
        except Exception as exc:
            logger.exception(f"Error inesperado llamando a Claude: {exc}")
            raise APIError(f"Error inesperado en análisis IA: {exc}") from exc

        # Log cache stats si disponibles
        usage = getattr(response, "usage", None)
        if usage:
            cache_read    = getattr(usage, "cache_read_input_tokens", 0)
            cache_created = getattr(usage, "cache_creation_input_tokens", 0)
            logger.info(
                f"Claude tokens — input: {usage.input_tokens}, output: {usage.output_tokens}, "
                f"cache_read: {cache_read}, cache_created: {cache_created}"
            )

        return response.content[0].text
