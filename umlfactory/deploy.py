"""Démarrage de toute la pile en local : serveur MCP + coordinateur + un agent par langage.

    python -m umlfactory.deploy          # au premier plan, Ctrl+C pour tout arrêter

La CLI (`python -m umlfactory.cli`) démarre elle-même cette pile quand elle n'est pas allumée, et l'arrête à la fin.
Avec `--keep-running` elle la laisse allumée en arrière-plan ; `--stop` l'arrête (voir `stop_stack`).

Les langages sont détectés automatiquement : chaque fichier de umlfactory/generators/ (hors base.py et
fichiers commençant par « _ ») est un langage et reçoit son agent (java.py, python.py, ou un fichier créé par la CLI), sur un port libre de la plage
GENERATOR_PORT_RANGE. Les journaux de chaque composant sont écrits dans ./logs/.
Un composant déjà démarré est laissé tel quel.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
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
STATE_FILE = ".umlfactory-stack.json"      # composants laissés allumés par `--keep-running` (nom, PID, adresse)
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
    from .generators import built_in_ids
    return sorted(built_in_ids())


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
                  progress: Progress | None = None, keep: bool = False):
    """Lance les composants locaux qui ne tournent pas déjà ; les arrête à la sortie.

    Renvoie la liste des composants démarrés par cet appel. Avec `keep`, ils sont détachés, restent allumés après la
    sortie et leurs PID sont enregistrés pour `stop_stack`."""
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
    kept = False
    detach: dict = {}
    if keep:
        detach = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
                  if os.name == "nt" else {"start_new_session": True})
    try:
        for c in comps:
            if urlparse(c.url).hostname not in LOCAL_HOSTS or is_ready(c):
                say(c.name, "running", c.url)             # distant ou déjà lancé à la main
                continue
            say(c.name, "starting", c.url)
            handle = open(logs / f"{c.name}.log", "w", encoding="utf-8")
            handles.append(handle)
            procs[c.name] = subprocess.Popen([sys.executable, "-m", *c.command], stdout=handle,
                                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **detach)
            started.append(c)
        deadline = time.time() + timeout
        for c in started:
            while not is_ready(c):
                if procs[c.name].poll() is not None:
                    say(c.name, "failed", f"voir {logs / (c.name + '.log')}")
                    if c.name in ("mcp", "coordinator"):
                        raise RuntimeError(f"{c.name} s'est arrêté au démarrage : un autre programme utilise peut-être "
                                           f"le port {urlparse(c.url).port}. Détails dans {logs / (c.name + '.log')}")
                    break
                if time.time() > deadline:
                    raise RuntimeError(f"{c.name} n'a pas démarré en {timeout:.0f} s (voir {logs / (c.name + '.log')})")
                time.sleep(0.2)
            else:
                say(c.name, "ready", c.url)
        if keep and started:
            write_state(state_path(logs), [(c.name, procs[c.name].pid, c.url) for c in started])
            kept = True
        yield [c.name for c in started]
    finally:
        if not kept:
            for p in procs.values():
                p.terminate()
            for p in procs.values():
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
        for h in handles:
            h.close()


# ---------------------------------------------------------------------------------- pile laissée allumée

def state_path(log_dir: str | Path = "logs") -> Path:
    return Path(log_dir).resolve().parent / STATE_FILE


def write_state(path: Path, components: list[tuple[str, int, str]]) -> None:
    data = {"components": [{"name": n, "pid": pid, "url": url} for n, pid, url in components]}
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"impossible d'enregistrer l'état de la pile ({path}) : {exc.strerror or exc}") from exc


def read_state(path: Path) -> list[dict] | None:
    """Composants enregistrés, ou None s'il n'y a rien d'exploitable (fichier absent, illisible ou mal formé)."""
    try:
        items = json.loads(path.read_text(encoding="utf-8"))["components"]
        if isinstance(items, list) and all(isinstance(i, dict) and isinstance(i.get("name"), str)
                                           and isinstance(i.get("pid"), int) and isinstance(i.get("url"), str)
                                           for i in items):
            return items
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


@dataclass(frozen=True)
class Stopped:
    name: str
    url: str
    state: str          # stopped | already | failed

    @property
    def port(self) -> int | None:
        return urlparse(self.url).port


def _is_up(name: str, url: str) -> bool:
    return is_ready(Component(name, (), url, "mcp" if name == "mcp" else "agent"))


def stop_stack(log_dir: str | Path = "logs", timeout: float = 10.0) -> list[Stopped] | None:
    """Arrête la pile laissée allumée. None : aucune pile enregistrée.

    Un PID n'est arrêté que si l'adresse du composant répond encore (Windows réutilise les PID)."""
    path = state_path(log_dir)
    items = read_state(path)
    if items is None:
        path.unlink(missing_ok=True)            # fichier mal formé : rien d'exploitable
        return None
    results: list[Stopped] = []
    for item in items:
        name, pid, url = item["name"], item["pid"], item["url"]
        if not _is_up(name, url):
            results.append(Stopped(name, url, "already"))
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            results.append(Stopped(name, url, "failed"))
            continue
        deadline = time.time() + timeout
        while _is_up(name, url) and time.time() < deadline:
            time.sleep(0.2)
        results.append(Stopped(name, url, "failed" if _is_up(name, url) else "stopped"))
    left = [i for i, r in zip(items, results) if r.state == "failed"]
    if left:
        path.write_text(json.dumps({"components": left}, indent=2), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    return results


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
    except (RuntimeError, OSError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
