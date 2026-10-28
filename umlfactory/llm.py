"""Client minimal pour les API de modèles : OpenAI (et compatibles) et Anthropic, avec streaming.

- OpenAI : POST {url}/chat/completions, flux SSE « data: {choices…} ».
- Anthropic : POST {url}/v1/messages, flux SSE « content_block_delta ».
Le fournisseur vient de `Settings.provider` ; l'appelant ne voit que `chat()`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import httpx

from .config import (ANTHROPIC, ANTHROPIC_VERSION, DEFAULT_ANTHROPIC_MAX_TOKENS, THINKING_BUDGETS, Settings,
                     load_settings)
from .textutil import strip_think

log = logging.getLogger(__name__)

_HINTS = {
    400: "requête refusée par le modèle",
    401: "clé d'API refusée",
    403: "accès refusé (droits de la clé ou du modèle)",
    404: "URL ou modèle inconnu",
    413: "requête trop volumineuse",
    429: "quota ou débit dépassé",
    529: "service surchargé",
}
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}

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
        self.anthropic = self.settings.provider == ANTHROPIC

    # ------------------------------------------------------------------ requête

    @property
    def endpoint(self) -> str:
        if self.anthropic:
            return f"{self.settings.api_url}/v1/messages"
        return f"{self.settings.api_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.anthropic:
            headers["x-api-key"] = self.settings.api_key
            headers["anthropic-version"] = ANTHROPIC_VERSION
        elif self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        return headers

    def _payload(self, messages: list[dict[str, str]], overrides: dict[str, Any]) -> dict[str, Any]:
        s = self.settings
        if self.anthropic:
            system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
            turns = [m for m in messages if m.get("role") != "system"]
            payload: dict[str, Any] = {"model": s.model, "messages": turns,
                                       "max_tokens": s.max_tokens or DEFAULT_ANTHROPIC_MAX_TOKENS}
            if system:
                payload["system"] = system
            if s.thinking in THINKING_BUDGETS:
                budget = THINKING_BUDGETS[s.thinking]
                payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
                payload["max_tokens"] = max(payload["max_tokens"], budget + 4096)   # la réflexion compte dans la limite
        else:
            payload = {"model": s.model, "messages": messages}
            if s.max_tokens:
                payload["max_tokens"] = s.max_tokens
            if s.reasoning_effort:
                payload["reasoning_effort"] = s.reasoning_effort
        # l'API Anthropic refuse une température différente de 1 quand la réflexion est active
        thinking_on = self.anthropic and s.thinking in THINKING_BUDGETS
        if s.temperature is not None and not thinking_on:
            payload["temperature"] = s.temperature
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
        payload = self._payload(messages, overrides)
        last = ""
        for attempt in range(self.retries + 1):
            try:
                if on_delta is None:
                    return await self._once(self.endpoint, payload)
                return await self._stream(self.endpoint, payload, on_delta)
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

    def _check_status(self, code: int, body: str) -> None:
        if code == 200:
            return
        detail = f"HTTP {code} {_HINTS.get(code, '')} — {body[:300]}"
        if code in (401, 403):
            detail += f" (vérifier {self._var('KEY')})"
        elif code == 404:
            detail += f" (vérifier {self._var('MODEL')})"
        if code in _RETRY_STATUS:
            raise _Retryable(detail)
        raise LLMError(f"appel LLM échoué : {detail}")

    def _var(self, what: str) -> str:
        """Nom de la variable du .env à vérifier : KEY -> ANTHROPIC_API_KEY, MODEL -> OPENAI_MODEL, etc."""
        if self.anthropic:
            return "ANTHROPIC_API_KEY" if what == "KEY" else "ANTHROPIC_MODEL"
        return "OPENAI_API_KEY" if what == "KEY" else "OPENAI_MODEL"

    def _text(self, body: str) -> str:
        try:
            data = json.loads(body)
            if self.anthropic:
                blocks = data.get("content") or []
                content = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
                finish = {"max_tokens": "length"}.get(data.get("stop_reason"), data.get("stop_reason"))
                return self._final(content, finish)
            choice = data["choices"][0]
            content = choice["message"].get("content")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise LLMError(f"réponse inattendue du serveur LLM : {body[:300]}") from None
        if isinstance(content, list):   # certains serveurs renvoient une liste de parties
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return self._final(content or "", choice.get("finish_reason"))

    def _final(self, content: str, finish_reason: str | None) -> str:
        text = strip_think(content)
        if not text:
            why = " (réponse tronquée : augmenter les tokens de sortie)" if finish_reason == "length" else ""
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
                        event = json.loads(data)
                    except ValueError:
                        continue
                    if self.anthropic:
                        kind, piece, stop = self._anthropic_event(event)
                        finish = stop or finish
                        if kind == "stop":
                            break
                        if kind is None:
                            continue
                    else:
                        try:
                            choice = event["choices"][0]
                        except (KeyError, IndexError, TypeError):
                            continue
                        finish = choice.get("finish_reason") or finish
                        delta = choice.get("delta") or {}
                        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                        if reasoning:
                            await on_delta("reasoning", reasoning)
                        kind, piece = "content", delta.get("content")
                    if kind == "reasoning" and piece:
                        await on_delta("reasoning", piece)
                    elif kind == "content" and piece:
                        content.append(piece)
                        await on_delta("content", piece)
        return self._final("".join(content), "length" if finish == "max_tokens" else finish)

    def _anthropic_event(self, event: dict) -> tuple[str | None, str | None, str | None]:
        """(nature, texte, stop_reason) d'un événement de flux Anthropic ; nature None = à ignorer."""
        kind = event.get("type")
        if kind == "error":
            raise LLMError("erreur du flux Anthropic : " + str(event.get("error", {}).get("message", event))[:300])
        if kind == "message_stop":
            return "stop", None, None
        if kind == "message_delta":
            return None, None, (event.get("delta") or {}).get("stop_reason")
        if kind == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                return "content", delta.get("text"), None
            if delta.get("type") == "thinking_delta":
                return "reasoning", delta.get("thinking"), None
        return None, None, None
