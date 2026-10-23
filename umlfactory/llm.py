"""Client minimal pour une API compatible OpenAI (POST {url}/chat/completions), avec streaming SSE."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import httpx

from .config import Settings, load_settings
from .textutil import strip_think

log = logging.getLogger(__name__)

_HINTS = {
    400: "requête refusée par le modèle (vérifier OPENAI_MODEL et OPENAI_EXTRA)",
    401: "clé d'API refusée (vérifier OPENAI_API_KEY)",
    403: "accès refusé (droits de la clé ou du modèle)",
    404: "URL ou modèle inconnu (vérifier OPENAI_API_URL et OPENAI_MODEL)",
    429: "quota ou débit dépassé",
}
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}

# Rappel appelé à chaque morceau reçu : (nature, texte) avec nature = "reasoning" | "content" | "reset"
DeltaCallback = Callable[[str, str], Awaitable[None]]


class LLMError(RuntimeError):
    pass


class _Retryable(Exception):
    pass


class LLMClient:
    def __init__(self, settings: Settings | None = None, retries: int = 3) -> None:
        self.settings = settings or load_settings()
        self.retries = retries

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        return headers

    def _payload(self, messages: list[dict[str, str]], overrides: dict[str, Any]) -> dict[str, Any]:
        s = self.settings
        payload: dict[str, Any] = {"model": s.model, "messages": messages}
        if s.temperature is not None:
            payload["temperature"] = s.temperature
        if s.max_tokens:
            payload["max_tokens"] = s.max_tokens
        payload.update(s.extra)
        payload.update(overrides)
        return payload

    async def chat(self, messages: list[dict[str, str]], on_delta: DeltaCallback | None = None,
                   **overrides: Any) -> str:
        """Une complétion ; renvoie le texte final (réflexion retirée).

        Avec `on_delta`, la réponse est lue en streaming et chaque morceau est transmis au fur et à mesure
        (réflexion et contenu), ce qui permet d'afficher une progression en direct.
        Réessaie sur les erreurs transitoires.
        """
        url = f"{self.settings.api_url}/chat/completions"
        payload = self._payload(messages, overrides)
        last = ""
        for attempt in range(self.retries + 1):
            try:
                if on_delta is None:
                    return await self._once(url, payload)
                return await self._stream(url, payload, on_delta)
            except _Retryable as exc:
                last = str(exc)
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}" or type(exc).__name__
            if attempt < self.retries:
                delay = 2 ** attempt
                log.warning("LLM : %s ; nouvelle tentative dans %ss", last, delay)
                if on_delta is not None:
                    await on_delta("reset", "")
                await asyncio.sleep(delay)
        raise LLMError(f"appel LLM échoué après {self.retries + 1} tentatives : {last}")

    # ------------------------------------------------------------------ sans streaming

    async def _once(self, url: str, payload: dict[str, Any]) -> str:
        async with httpx.AsyncClient(timeout=self.settings.timeout) as http:
            resp = await http.post(url, json=payload, headers=self._headers())
        self._check_status(resp.status_code, resp.text)
        return self._text(resp.text)

    @staticmethod
    def _check_status(code: int, body: str) -> None:
        if code == 200:
            return
        detail = f"HTTP {code} {_HINTS.get(code, '')} — {body[:300]}"
        if code in _RETRY_STATUS:
            raise _Retryable(detail)
        raise LLMError(f"appel LLM échoué : {detail}")

    @staticmethod
    def _text(body: str) -> str:
        try:
            choice = json.loads(body)["choices"][0]
            content = choice["message"].get("content")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise LLMError(f"réponse inattendue du serveur LLM : {body[:300]}") from None
        if isinstance(content, list):   # certains serveurs renvoient une liste de parties
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return LLMClient._final(content or "", choice.get("finish_reason"))

    @staticmethod
    def _final(content: str, finish_reason: str | None) -> str:
        text = strip_think(content)
        if not text:
            why = " (réponse tronquée : augmenter OPENAI_MAX_TOKENS)" if finish_reason == "length" else ""
            raise LLMError(f"réponse vide du LLM{why}")
        return text

    # ------------------------------------------------------------------ streaming SSE

    async def _stream(self, url: str, payload: dict[str, Any], on_delta: DeltaCallback) -> str:
        payload = {**payload, "stream": True}
        content: list[str] = []
        finish: str | None = None
        async with httpx.AsyncClient(timeout=self.settings.timeout) as http:
            async with http.stream("POST", url, json=payload, headers=self._headers()) as resp:
                if resp.status_code != 200:
                    self._check_status(resp.status_code, (await resp.aread()).decode("utf-8", "replace"))
                if "text/event-stream" not in resp.headers.get("content-type", ""):
                    # le serveur a ignoré « stream » : réponse complète d'un coup
                    text = self._text((await resp.aread()).decode("utf-8", "replace"))
                    await on_delta("content", text)
                    return text
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        choice = json.loads(data)["choices"][0]
                    except (ValueError, KeyError, IndexError, TypeError):
                        continue
                    finish = choice.get("finish_reason") or finish
                    delta = choice.get("delta") or {}
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning:
                        await on_delta("reasoning", reasoning)
                    piece = delta.get("content")
                    if piece:
                        content.append(piece)
                        await on_delta("content", piece)
        return self._final("".join(content), finish)
