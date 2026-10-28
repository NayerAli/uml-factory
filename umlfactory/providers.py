"""Choix du fournisseur de modèles au lancement de la CLI.

Les clés présentes dans l'environnement (ou le `.env`) sont testées une à une par une requête légère
(liste des modèles). Une seule clé valide : elle est utilisée sans rien demander. Deux clés valides :
l'utilisateur choisit dans un menu, où chaque clé est affichée masquée (première et dernière lettres).
"""

from __future__ import annotations

import asyncio
import os
import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import (ANTHROPIC, ANTHROPIC_VERSION, KEY_VARS, PROVIDERS, Candidate, ConfigError,
                     candidates, local_candidate, mask_key)
from .ui import Term

PROBE_TIMEOUT = 10.0
PREFS_FILE = Path(__file__).resolve().parent.parent / ".umlfactory.json"     # choix mémorisé au premier lancement


def saved_provider() -> str | None:
    try:
        value = json.loads(PREFS_FILE.read_text(encoding="utf-8")).get("provider")
    except (OSError, ValueError, AttributeError):
        return None
    return value if value in PROVIDERS else None


def save_provider(provider: str | None) -> None:
    try:
        if provider is None:
            PREFS_FILE.unlink(missing_ok=True)
        else:
            PREFS_FILE.write_text(json.dumps({"provider": provider}) + "\n", encoding="utf-8")
    except OSError:
        pass


@dataclass(frozen=True)
class Probe:
    candidate: Candidate
    ok: bool
    reason: str


async def _probe_one(candidate: Candidate) -> Probe:
    """Une requête simple (liste des modèles) : suffit à savoir si la clé est acceptée."""
    if candidate.provider == ANTHROPIC:
        url = f"{candidate.url}/v1/models"
        headers = {"x-api-key": candidate.key, "anthropic-version": ANTHROPIC_VERSION}
    else:
        url = f"{candidate.url}/models"
        headers = {"Authorization": f"Bearer {candidate.key}"}
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as http:
            resp = await http.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return Probe(candidate, False, f"réseau indisponible ({type(exc).__name__})")
    if resp.status_code == 200:
        return Probe(candidate, True, "clé valide")
    if resp.status_code in (401, 403):
        return Probe(candidate, False, "clé refusée")
    if resp.status_code == 404:      # certains fournisseurs compatibles n'exposent pas la liste des modèles
        return Probe(candidate, True, "clé non vérifiée (liste des modèles absente chez ce fournisseur)")
    return Probe(candidate, False, f"HTTP {resp.status_code}")


async def probe_all(found: list[Candidate]) -> list[Probe]:
    return list(await asyncio.gather(*(_probe_one(c) for c in found)))


def choose(term: Term, probes: list[Probe], interactive: bool) -> Candidate:
    """Renvoie le fournisseur à utiliser ; lève ConfigError s'il n'y en a aucun valide."""
    valid = [p.candidate for p in probes if p.ok]
    if not valid:
        details = "\n".join(f"  - {p.candidate.label} ({KEY_VARS[p.candidate.provider]} "
                            f"{mask_key(p.candidate.key)}) : {p.reason}" for p in probes)
        raise ConfigError("aucune clé d'API n'a été acceptée :\n" + details)
    if len(valid) == 1:
        return valid[0]
    if not interactive:
        return valid[0]        # PROVIDERS est classé par préférence (Anthropic d'abord)
    from .ui import select
    labels = [f"{c.label} (modèle {c.model})" for c in valid]
    return valid[select(term, "Plusieurs services d'IA sont disponibles. Lequel utiliser ?", labels)[0]]


def apply(candidate: Candidate) -> None:
    """Rend le choix visible aux agents lancés depuis ce processus (et à la CLI elle-même)."""
    os.environ["UMLFACTORY_PROVIDER"] = candidate.provider


async def resolve(term: Term, interactive: bool, forced: str | None = None, reset: bool = False) -> Candidate:
    """Point d'entrée : teste les clés, choisit, et renvoie le candidat retenu."""
    found = candidates(forced)
    if not found:
        chosen = local_candidate(forced)
        if chosen:
            apply(chosen)
            return chosen
        wanted = f"{KEY_VARS[forced]}" if forced else "OPENAI_API_KEY ou ANTHROPIC_API_KEY"
        raise ConfigError(f"aucune clé d'API trouvée : renseigner {wanted} dans le fichier .env")
    if reset:
        save_provider(None)
    remembered = None if forced else saved_provider()
    if remembered:
        mine = [c for c in found if c.provider == remembered]
        if mine and (await probe_all(mine))[0].ok:         # choix mémorisé et clé toujours valide : rien à demander
            apply(mine[0])
            return mine[0]
    probes = await probe_all(found)
    chosen = choose(term, probes, interactive)
    if not forced and interactive and sum(p.ok for p in probes) > 1:
        save_provider(chosen.provider)        # demandé une seule fois ; `--reset-model` pour changer
    apply(chosen)
    return chosen
