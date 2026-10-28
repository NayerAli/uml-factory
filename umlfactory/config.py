"""Configuration `.env` partagée par le serveur MCP, le coordinateur et les agents.

Deux fournisseurs de modèles sont gérés : OpenAI (ou toute API compatible) et Anthropic (Claude).
Le fournisseur utilisé est choisi au lancement de la CLI (voir `umlfactory/providers.py`) et transmis
aux agents dans chaque requête ; sans choix explicite, il est déduit des clés présentes.

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
DEFAULT_PORT_RANGE = (9101, 9150)
VERIFY_BUDGET = 10.0                   # secondes de la vérification d'exécution (valeur fixe)     # plage où les agents de langage sont cherchés (et lancés par deploy)

OPENAI = "openai"
ANTHROPIC = "anthropic"
PROVIDERS = (ANTHROPIC, OPENAI)       # ordre d'affichage et de préférence
DEFAULT_OPENAI_URL = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_URL = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-5-5"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_MAX_TOKENS = 8192   # l'API Anthropic exige une limite de sortie explicite
# Niveau de réflexion -> budget de tokens de réflexion (Anthropic « extended thinking »)
THINKING_BUDGETS = {"low": 2048, "medium": 8192, "high": 16000}

PROVIDER_LABELS = {OPENAI: "OpenAI (API compatible)", ANTHROPIC: "Anthropic (Claude)"}
KEY_VARS = {OPENAI: "OPENAI_API_KEY", ANTHROPIC: "ANTHROPIC_API_KEY"}


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


def anthropic_root(raw: str) -> str:
    """'https://api.anthropic.com' ou '.../v1' -> 'https://api.anthropic.com' (le chemin /v1/messages est ajouté ensuite)."""
    url = raw.strip().rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


@dataclass(frozen=True)
class Candidate:
    """Un fournisseur dont les paramètres de connexion sont lus dans l'environnement (source unique)."""
    provider: str
    key: str
    url: str
    model: str

    @property
    def label(self) -> str:
        return PROVIDER_LABELS[self.provider]


def candidates(preferred: str | None = None) -> list[Candidate]:
    """Un candidat par fournisseur dont la clé est renseignée (env ou .env déjà chargé)."""
    found: list[Candidate] = []
    for provider in PROVIDERS:
        if preferred and provider != preferred:
            continue
        key = os.environ.get(KEY_VARS[provider], "").strip()
        if not key:
            continue
        if provider == ANTHROPIC:
            url = os.environ.get("ANTHROPIC_API_URL", "").strip() or DEFAULT_ANTHROPIC_URL
            model = os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_ANTHROPIC_MODEL
            found.append(Candidate(provider, key, anthropic_root(url), model))
        else:
            url = os.environ.get("OPENAI_API_URL", "").strip() or DEFAULT_OPENAI_URL
            found.append(Candidate(provider, key, api_base(url), os.environ.get("OPENAI_MODEL", "").strip()))
    return found


def local_candidate(forced: str | None = None) -> Candidate | None:
    """Serveur local sans authentification (Ollama, LM Studio...) : URL et modèle renseignés, aucune clé à tester."""
    url = os.environ.get("OPENAI_API_URL", "").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip()
    if url and model and forced in (None, OPENAI):
        return Candidate(OPENAI, "", api_base(url), model)
    return None


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
    temperature: float | None
    max_tokens: int | None
    extra: dict = field(default_factory=dict)
    provider: str = OPENAI
    mcp_url: str = DEFAULT_MCP_URL
    coordinator_url: str = DEFAULT_COORDINATOR_URL
    generator_ports: tuple[int, int] = DEFAULT_PORT_RANGE
    generator_urls: tuple[str, ...] = ()       # agents supplémentaires (autre machine, autre plage)
    verify_budget: float = VERIFY_BUDGET       # secondes allouées à la vérification d'exécution
    thinking: str = "off"                      # Anthropic : off | low | medium | high
    reasoning_effort: str | None = None        # OpenAI (modèles raisonneurs) : low | medium | high


def infer_provider() -> str:
    """Fournisseur par défaut : celui demandé dans l'environnement, sinon Anthropic si seule sa clé existe."""
    chosen = os.environ.get("UMLFACTORY_PROVIDER", "").strip().lower()
    if chosen in PROVIDERS:
        return chosen
    if os.environ.get("ANTHROPIC_API_KEY", "").strip() and not os.environ.get("OPENAI_API_KEY", "").strip():
        return ANTHROPIC
    return OPENAI


def load_settings(require_api: bool = True, provider: str | None = None) -> Settings:
    provider = (provider or infer_provider()).lower()
    if provider not in PROVIDERS:
        raise ConfigError(f"fournisseur inconnu : {provider!r} (attendu : {', '.join(PROVIDERS)})")
    if provider == ANTHROPIC:
        url = os.environ.get("ANTHROPIC_API_URL", "").strip() or DEFAULT_ANTHROPIC_URL
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        model = os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_ANTHROPIC_MODEL
        missing = [] if key else ["ANTHROPIC_API_KEY"]
        api_url = anthropic_root(url)
    else:
        url = os.environ.get("OPENAI_API_URL", "").strip()
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        model = os.environ.get("OPENAI_MODEL", "").strip()
        missing = [n for n, v in (("OPENAI_API_URL", url), ("OPENAI_MODEL", model)) if not v]
        api_url = api_base(url) if url else ""
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

    thinking = os.environ.get("ANTHROPIC_THINKING", "").strip().lower() or "off"
    if thinking not in ("off", *THINKING_BUDGETS):
        raise ConfigError("ANTHROPIC_THINKING doit être off, low, medium ou high (reçu : " + repr(thinking) + ")")
    effort = os.environ.get("OPENAI_REASONING_EFFORT", "").strip().lower() or None
    if effort not in (None, "low", "medium", "high"):
        raise ConfigError("OPENAI_REASONING_EFFORT doit être low, medium ou high (reçu : " + repr(effort) + ")")
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

    return Settings(
        api_url=api_url,
        verify_budget=VERIFY_BUDGET,
        api_key=key,
        model=model,
        timeout=_float("OPENAI_TIMEOUT") or 600.0,
        concurrency=max(1, _int("OPENAI_CONCURRENCY", 5)),
        temperature=_float("OPENAI_TEMPERATURE"),
        max_tokens=int(max_tokens) if max_tokens else None,
        extra=extra,
        provider=provider,
        thinking=thinking,
        reasoning_effort=effort,
        mcp_url=os.environ.get("MCP_URL", "").strip() or DEFAULT_MCP_URL,
        coordinator_url=os.environ.get("COORDINATOR_URL", "").strip() or DEFAULT_COORDINATOR_URL,
        generator_ports=ports,
        generator_urls=generators,
    )


def mask_key(key: str) -> str:
    """Première et dernière lettres seulement : « sk-ant-api03-AbC…xYz » ; court : « *** »."""
    return f"{key[:6]}…{key[-4:]}" if len(key) > 14 else ("***" if key else "(aucune)")


def describe(settings: Settings) -> str:
    masked = mask_key(settings.api_key)
    return (f"{PROVIDER_LABELS.get(settings.provider, settings.provider)} | modèle {settings.model or '(non configuré)'} "
            f"| API {settings.api_url or '(non configurée)'} | clé {masked}")
