"""Configuration `.env` partagée par le serveur MCP et les trois agents.

Les variables déjà présentes dans l'environnement gagnent sur le fichier (CI, docker).
La clé d'API n'est jamais affichée (`describe` la masque).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_MCP_URL = "http://127.0.0.1:9000/mcp"
DEFAULT_COORDINATOR_URL = "http://127.0.0.1:9200"
DEFAULT_PORT_RANGE = (9101, 9150)     # plage où les agents de langage sont cherchés (et lancés par deploy)


class ConfigError(ValueError):
    """Configuration absente ou invalide (message destiné à l'utilisateur)."""


def find_env_file(start: str | Path | None = None) -> Path | None:
    here = Path(start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        candidate = folder / ".env"
        if candidate.is_file():
            return candidate
    return None


def parse_env_file(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        if key:
            values[key] = value
    return values


def load_env_file(path: str | Path | None = None) -> Path | None:
    """Charge `.env` dans os.environ sans écraser l'existant. Renvoie le fichier lu."""
    env_path = Path(path) if path else find_env_file()
    if env_path is None or not env_path.is_file():
        return None
    for key, value in parse_env_file(env_path).items():
        os.environ.setdefault(key, value)
    return env_path


def api_base(raw: str) -> str:
    """'https://api.exemple.com' -> 'https://api.exemple.com/v1' ; une URL déjà versionnée est conservée."""
    url = raw.strip().rstrip("/")
    tail = url.rsplit("/", 1)[-1].lower()
    if tail.startswith("v") and tail[1:2].isdigit():
        return url
    return f"{url}/v1"


def port_of(url: str, default: int) -> int:
    return urlparse(url).port or default


def _float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} doit être un nombre (reçu : {raw!r})") from None


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        raise ConfigError(f"{name} doit être un entier (reçu : {raw!r})") from None


@dataclass(frozen=True)
class Settings:
    api_url: str
    api_key: str
    model: str
    timeout: float
    concurrency: int
    max_repairs: int
    temperature: float | None
    max_tokens: int | None
    extra: dict = field(default_factory=dict)
    mcp_url: str = DEFAULT_MCP_URL
    coordinator_url: str = DEFAULT_COORDINATOR_URL
    generator_ports: tuple[int, int] = DEFAULT_PORT_RANGE
    generator_urls: tuple[str, ...] = ()       # agents supplémentaires (autre machine, autre plage)
    verify_budget: float = 10.0                # secondes allouées à la vérification d'exécution (0 : désactivée)


def load_settings(require_api: bool = True) -> Settings:
    url = os.environ.get("OPENAI_API_URL", "").strip()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip()
    missing = [n for n, v in (("OPENAI_API_URL", url), ("OPENAI_MODEL", model)) if not v]
    if missing and require_api:
        raise ConfigError(
            "configuration incomplète : " + ", ".join(missing) + " à renseigner dans le fichier .env "
            "(modèle : .env.example)."
        )
    extra: dict = {}
    raw_extra = os.environ.get("OPENAI_EXTRA", "").strip()
    if raw_extra:
        try:
            extra = json.loads(raw_extra)
            if not isinstance(extra, dict):
                raise ValueError
        except ValueError:
            raise ConfigError("OPENAI_EXTRA doit être un objet JSON, ex. {\"reasoning_effort\": \"low\"}") from None
    max_tokens = _float("OPENAI_MAX_TOKENS")

    listed = os.environ.get("GENERATOR_AGENT_URLS", "").strip()
    generators = tuple(u.strip() for u in listed.split(",") if u.strip())
    ports = DEFAULT_PORT_RANGE
    raw_ports = os.environ.get("GENERATOR_PORT_RANGE", "").strip()
    if raw_ports:
        try:
            low, _, high = raw_ports.partition("-")
            ports = (int(low), int(high or low))
            if not 0 < ports[0] <= ports[1] < 65536:
                raise ValueError
        except ValueError:
            raise ConfigError("GENERATOR_PORT_RANGE doit être de la forme 9101-9150") from None

    budget = _float("UMLFACTORY_VERIFY_TIMEOUT")
    return Settings(
        api_url=api_base(url) if url else "",
        verify_budget=10.0 if budget is None else max(0.0, budget),
        api_key=key,
        model=model,
        timeout=_float("OPENAI_TIMEOUT") or 600.0,
        concurrency=max(1, _int("OPENAI_CONCURRENCY", 2)),
        max_repairs=_int("UMLFACTORY_MAX_REPAIRS", 2),
        temperature=_float("OPENAI_TEMPERATURE"),
        max_tokens=int(max_tokens) if max_tokens else None,
        extra=extra,
        mcp_url=os.environ.get("MCP_URL", "").strip() or DEFAULT_MCP_URL,
        coordinator_url=os.environ.get("COORDINATOR_URL", "").strip() or DEFAULT_COORDINATOR_URL,
        generator_ports=ports,
        generator_urls=generators,
    )


def describe(settings: Settings) -> str:
    key = settings.api_key
    masked = f"{key[:3]}…{key[-3:]}" if len(key) > 12 else ("***" if key else "(aucune)")
    return (f"API {settings.api_url or '(non configurée)'} | modèle {settings.model or '(non configuré)'} "
            f"| clé {masked}")
