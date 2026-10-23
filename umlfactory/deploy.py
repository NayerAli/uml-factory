"""Démarrage de toute la pile en local : serveur MCP + coordinateur + un agent par langage.

    python -m umlfactory.deploy          # au premier plan, Ctrl+C pour tout arrêter

Les langages sont détectés automatiquement : chaque fichier de umlfactory/generators/ (hors base.py et
fichiers commençant par « _ ») est un langage et reçoit son agent, sur un port libre de la plage
GENERATOR_PORT_RANGE. Les journaux de chaque composant sont écrits dans ./logs/.
Un composant déjà démarré est laissé tel quel.
"""

from __future__ import annotations

import asyncio
import contextlib
import pkgutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from .a2a_common import discover_local
from .config import Settings, describe, load_env_file, load_settings

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
# (nom, état, détail) avec état = starting | ready | running | failed
Progress = Callable[[str, str, str], None]


@dataclass(frozen=True)
class Component:
    name: str
    command: tuple[str, ...]      # arguments après « python -m »
    url: str
    kind: str                     # "mcp" ou "agent"


def language_modules() -> list[str]:
    """Langages disponibles = modules de umlfactory/generators (convention : nom du fichier = id du langage)."""
    from . import generators
    from .languages import active_ids
    built_in = {m.name for m in pkgutil.iter_modules(generators.__path__)
                if not m.name.startswith("_") and m.name != "base"}
    return sorted(built_in | set(active_ids()))


def tcp_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def agent_ready(url: str) -> bool:
    try:
        return httpx.get(url.rstrip("/") + "/.well-known/agent-card.json", timeout=1.0, trust_env=False).status_code == 200
    except httpx.HTTPError:
        return False


def is_ready(c: Component) -> bool:
    port = urlparse(c.url).port or 80
    return tcp_open(port, urlparse(c.url).hostname or "127.0.0.1") if c.kind == "mcp" else agent_ready(c.url)


def plan_components(settings: Settings, existing_languages: set[str], used_ports: set[int]) -> list[Component]:
    """Composants à démarrer : MCP, coordinateur, et un agent pour chaque langage pas déjà en service."""
    comps = [
        Component("mcp", ("umlfactory.mcp_server",), settings.mcp_url, "mcp"),
        Component("coordinator", ("umlfactory.coordinator",), settings.coordinator_url, "agent"),
    ]
    low, high = settings.generator_ports
    free = (p for p in range(low, high + 1) if p not in used_ports and not tcp_open(p))
    for language in language_modules():
        if language in existing_languages:
            continue
        try:
            port = next(free)
        except StopIteration:
            raise RuntimeError(f"plus de port libre dans {low}-{high} pour l'agent « {language} » "
                               "(élargir GENERATOR_PORT_RANGE)") from None
        comps.append(Component(language, ("umlfactory.generators", language, "--port", str(port)),
                               f"http://127.0.0.1:{port}", "agent"))
    return comps


@contextlib.contextmanager
def running_stack(settings: Settings | None = None, timeout: float = 90.0, log_dir: str | Path = "logs",
                  progress: Progress | None = None):
    """Lance les composants locaux qui ne tournent pas déjà ; les arrête à la sortie."""
    settings = settings or load_settings(require_api=False)
    say = progress or (lambda *_: None)
    logs = Path(log_dir)
    logs.mkdir(parents=True, exist_ok=True)

    existing = asyncio.run(discover_local(settings.generator_ports, settings.generator_urls))
    languages = {lang for a in existing for lang in a.languages()}
    used = {urlparse(a.url).port for a in existing if urlparse(a.url).port}
    comps = plan_components(settings, languages, used)

    procs: dict[str, subprocess.Popen] = {}
    handles = []
    started: list[Component] = []
    try:
        for c in comps:
            if urlparse(c.url).hostname not in LOCAL_HOSTS or is_ready(c):
                say(c.name, "running", c.url)             # distant ou déjà lancé à la main
                continue
            say(c.name, "starting", c.url)
            handle = open(logs / f"{c.name}.log", "w", encoding="utf-8")
            handles.append(handle)
            procs[c.name] = subprocess.Popen([sys.executable, "-m", *c.command], stdout=handle,
                                             stderr=subprocess.STDOUT)
            started.append(c)
        deadline = time.time() + timeout
        for c in started:
            while not is_ready(c):
                if procs[c.name].poll() is not None:
                    say(c.name, "failed", f"voir {logs / (c.name + '.log')}")
                    if c.name in ("mcp", "coordinator"):
                        raise RuntimeError(f"{c.name} s'est arrêté au démarrage (voir {logs / (c.name + '.log')})")
                    break
                if time.time() > deadline:
                    raise RuntimeError(f"{c.name} n'a pas démarré en {timeout:.0f} s (voir {logs / (c.name + '.log')})")
                time.sleep(0.2)
            else:
                say(c.name, "ready", c.url)
        yield
    finally:
        for p in procs.values():
            p.terminate()
        for p in procs.values():
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        for h in handles:
            h.close()


def main() -> int:
    env = load_env_file()
    settings = load_settings(require_api=False)
    print(f".env : {env or 'introuvable (variables d’environnement seulement)'}")
    print(describe(settings))
    if not (settings.api_url and settings.model):
        print("Attention : OPENAI_API_URL / OPENAI_MODEL non renseignés, la génération échouera.")
    print(f"Langages détectés : {', '.join(language_modules()) or 'aucun'}")
    icons = {"starting": "…", "ready": "✔", "running": "✔ (déjà actif)", "failed": "✘"}

    def show(name: str, state: str, detail: str) -> None:
        if state != "starting":
            print(f"  {icons[state]:<14} {name:<12} {detail}", flush=True)

    try:
        with running_stack(settings, progress=show):
            print("Pile prête. Exemple :  python -m umlfactory.cli examples/model.puml\n(Ctrl+C pour arrêter)")
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        print("\nArrêt.")
        return 0
    except RuntimeError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
