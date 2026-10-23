"""Briques A2A partagées : mise en service d'un agent, découverte, appel d'un agent avec événements en direct."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
import socket
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx
import uvicorn
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers.proto_helpers import (get_artifact_text, get_data_parts, get_message_text, new_data_message,
                                       new_data_part)
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCard, Message, Role, SendMessageRequest, TaskState
from starlette.applications import Starlette

from .config import describe, load_env_file, load_settings

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 3600.0     # un LLM lent peut mettre de nombreuses minutes
CODEGEN_PREFIX = "codegen:"
_FAILED = (TaskState.TASK_STATE_FAILED, TaskState.TASK_STATE_REJECTED, TaskState.TASK_STATE_CANCELED)
EventHandler = Callable[[dict], Awaitable[None] | None]


# ---------------------------------------------------------------------------------- serveur

def build_app(agent: AgentExecutor, base_url: str) -> Starlette:
    card = agent.build_card(base_url)  # type: ignore[attr-defined]
    handler = DefaultRequestHandlerV2(agent_executor=agent, task_store=InMemoryTaskStore(), agent_card=card)
    routes = [*create_agent_card_routes(card), *create_jsonrpc_routes(handler, rpc_url="/")]
    return Starlette(routes=routes)


def serve_agent(agent: AgentExecutor, label: str, host: str, port: int, base_url: str | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    url = (base_url or f"http://{host}:{port}").rstrip("/") + "/"
    try:
        print(f"LLM : {describe(load_settings(require_api=False))}")
    except ValueError as exc:
        print(f"Configuration : {exc}")
    print(f"Agent {label} : {url}", flush=True)
    uvicorn.run(build_app(agent, url), host=host, port=port, log_level="warning")


def run_cli(agent: AgentExecutor, label: str, env_url_var: str, default_url: str) -> None:
    """Point d'entrée d'un agent à URL fixe (le coordinateur) : `python -m umlfactory.coordinator`."""
    import os

    load_env_file()
    configured = os.environ.get(env_url_var, "").strip() or default_url
    parser = argparse.ArgumentParser(description=f"Agent {label} (A2A)")
    parser.add_argument("--host", default="127.0.0.1", help="127.0.0.1 par défaut : accès local uniquement")
    parser.add_argument("--port", type=int, default=urlparse(configured).port or 9100)
    parser.add_argument("--url", help="URL publique annoncée dans l'Agent Card (défaut : variable .env)")
    args = parser.parse_args()
    serve_agent(agent, label, args.host, args.port, args.url or configured)


def event_message(event: dict, context_id: str, task_id: str):
    """Message de statut A2A portant un événement de progression (objet JSON)."""
    return new_data_message(event, media_type="application/json", context_id=context_id, task_id=task_id)


async def send_event(updater: TaskUpdater, context_id: str, task_id: str, event: dict) -> None:
    """Publie un événement de progression ; un échec de suivi ne doit jamais faire échouer la tâche."""
    try:
        await updater.update_status(TaskState.TASK_STATE_WORKING, event_message(event, context_id, task_id))
    except Exception:  # noqa: BLE001
        log.debug("événement non transmis", exc_info=True)


# ---------------------------------------------------------------------------------- client

def _http(timeout: float) -> httpx.AsyncClient:
    # Les agents sont locaux : on ignore les proxys de l'environnement (sinon 127.0.0.1 peut être détourné).
    return httpx.AsyncClient(timeout=timeout, trust_env=False)


@dataclass
class DiscoveredAgent:
    url: str
    card: AgentCard

    def tags(self) -> set[str]:
        return {tag for skill in self.card.skills for tag in skill.tags}

    def languages(self) -> list[str]:
        return sorted(t.removeprefix(CODEGEN_PREFIX) for t in self.tags() if t.startswith(CODEGEN_PREFIX))

    def runtime_tools(self, language: str) -> list[str] | None:
        """Outils requis par la vérification d'exécution de ce langage (tags `tool:`), ou None si elle n'existe pas."""
        for skill in self.card.skills:
            if f"verify:{language}" in skill.tags:
                return [t.removeprefix("tool:") for t in skill.tags if t.startswith("tool:")]
        return None

    def display_name(self, language: str) -> str:
        for skill in self.card.skills:
            if f"{CODEGEN_PREFIX}{language}" in skill.tags:
                return skill.name.removeprefix("Génération de code ").strip() or language
        return language


async def _fetch_card(http: httpx.AsyncClient, url: str) -> DiscoveredAgent | None:
    try:
        return DiscoveredAgent(url, await A2ACardResolver(http, url).get_agent_card())
    except Exception as exc:  # noqa: BLE001 - un agent absent ne bloque pas les autres
        log.warning("agent injoignable %s : %s", url, exc)
        return None


async def discover(urls: list[str] | tuple[str, ...], timeout: float = 5.0) -> list[DiscoveredAgent]:
    """Récupère l'Agent Card de chaque URL (en parallèle) ; les agents injoignables sont ignorés."""
    async with _http(timeout) as http:
        found = await asyncio.gather(*(_fetch_card(http, u) for u in urls))
    return [a for a in found if a is not None]


async def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def discover_local(ports: tuple[int, int], extra_urls: tuple[str, ...] = (), host: str = "127.0.0.1",
                         timeout: float = 5.0) -> list[DiscoveredAgent]:
    """Cherche les agents sur une plage de ports locale (+ URLs explicites) : un nouvel agent est trouvé
    sans aucune configuration dès qu'il écoute dans la plage."""
    candidates = list(range(ports[0], ports[1] + 1))
    opened = await asyncio.gather(*(port_open(p, host) for p in candidates))
    urls = [f"http://{host}:{p}" for p, ok in zip(candidates, opened) if ok]
    urls += [u.rstrip("/") for u in extra_urls if u.rstrip("/") not in urls]
    return await discover(urls, timeout)


def free_port(ports: tuple[int, int], host: str = "127.0.0.1") -> int:
    """Premier port de la plage où rien n'écoute."""
    for port in range(ports[0], ports[1] + 1):
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex((host, port)) != 0:
                return port
    raise RuntimeError(f"plus de port libre dans {ports[0]}-{ports[1]} (élargir GENERATOR_PORT_RANGE)")


@dataclass
class AgentReply:
    state: int
    text: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)   # nom -> contenu


class AgentFailed(RuntimeError):
    pass


async def _emit(handler: EventHandler | None, event: dict) -> None:
    if handler is None:
        return
    result = handler(event)
    if inspect.isawaitable(result):
        await result


async def call_agent(card: AgentCard, payload: dict[str, Any], on_event: EventHandler | None = None,
                     timeout: float = DEFAULT_TIMEOUT) -> AgentReply:
    """Envoie `payload` (DataPart JSON) à un agent A2A en streaming.

    `on_event` reçoit chaque événement de progression (dict) émis par l'agent pendant son travail.
    Renvoie le message final et les artefacts.
    """
    request = SendMessageRequest(message=Message(
        message_id=str(uuid.uuid4()), role=Role.ROLE_USER,
        parts=[new_data_part(payload, media_type="application/json")]))
    chunks: dict[str, tuple[str, list[str]]] = {}
    state, text = TaskState.TASK_STATE_UNSPECIFIED, ""
    async with _http(timeout) as http:
        client = await create_client(card, client_config=ClientConfig(streaming=True, httpx_client=http))
        try:
            async for resp in client.send_message(request):
                if resp.HasField("task"):
                    state = resp.task.status.state
                    if resp.task.status.HasField("message"):
                        text = get_message_text(resp.task.status.message)
                    for art in resp.task.artifacts:
                        chunks[art.artifact_id] = (art.name, [get_artifact_text(art)])
                elif resp.HasField("artifact_update"):
                    art = resp.artifact_update.artifact
                    entry = chunks.setdefault(art.artifact_id, (art.name, []))
                    if not resp.artifact_update.append:
                        entry[1].clear()
                    entry[1].append(get_artifact_text(art))
                elif resp.HasField("status_update"):
                    state = resp.status_update.status.state
                    if resp.status_update.status.HasField("message"):
                        message = resp.status_update.status.message
                        text = get_message_text(message)
                        if state == TaskState.TASK_STATE_WORKING:
                            data = [d for d in get_data_parts(message.parts) if isinstance(d, dict)]
                            for event in data or ([{"event": "log", "text": text}] if text else []):
                                await _emit(on_event, event)
        finally:
            await client.close()
    if state in _FAILED:
        raise AgentFailed(f"{card.name} : {text or TaskState.Name(state)}")
    if state != TaskState.TASK_STATE_COMPLETED:
        raise AgentFailed(f"{card.name} : tâche non terminée ({TaskState.Name(state)})")
    return AgentReply(state=state, text=text, artifacts={n: "".join(c) for n, c in chunks.values()})
