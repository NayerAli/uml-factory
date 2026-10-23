"""Nettoyage des réponses d'un LLM : réflexion, blocs de code, JSON."""

from __future__ import annotations

import json
import re

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)
_OPEN_FENCE = re.compile(r"^\s*```[^\n`]*\n", re.DOTALL)
_DECLARED = re.compile(r"^\s*(?:abstract\s+)?(?:class|interface|enum)\s+\"?([A-Za-z_]\w*)", re.MULTILINE)
# Notes sur plusieurs lignes (« note … / end note ») : leur texte libre n'est pas une déclaration.
# Une note d'une ligne (« note right of A : texte ») contient « : » et n'est donc pas confondue avec un bloc.
_NOTE_BLOCK = re.compile(r"^\s*note\b[^:\n]*\n.*?^\s*end\s*note\b", re.IGNORECASE | re.DOTALL | re.MULTILINE)


def strip_think(text: str) -> str:
    """Supprime les blocs <think>…</think> (et un <think> jamais refermé)."""
    text = _THINK.sub("", text)
    if "<think>" in text.lower():
        text = text[: text.lower().index("<think>")]
    return text.strip()


def extract_code(text: str) -> str:
    """Contenu du bloc de code le plus long ; à défaut, le texte brut sans fence d'ouverture orpheline."""
    text = strip_think(text)
    blocks = _FENCE.findall(text)
    if blocks:
        code = max(blocks, key=len)
    else:
        code = _OPEN_FENCE.sub("", text, count=1)
        code = re.sub(r"\n```\s*$", "", code)
    return code.strip("\n") + "\n" if code.strip() else ""


def extract_json(text: str) -> dict:
    """Premier objet JSON de la réponse (avec ou sans fence). Lève ValueError si introuvable."""
    text = strip_think(text)
    blocks = _FENCE.findall(text)
    candidates = [*blocks, text]
    for cand in candidates:
        start, end = cand.find("{"), cand.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(cand[start:end + 1])
            except ValueError:
                continue
            if isinstance(data, dict):
                return data
    raise ValueError("aucun objet JSON valide dans la réponse")


def declared_names(puml: str) -> list[str]:
    """Noms de types déclarés (garde-fou de couverture, pas un analyseur UML)."""
    return list(dict.fromkeys(_DECLARED.findall(_NOTE_BLOCK.sub("", puml))))


def strip_notes(puml: str) -> str:
    """PlantUML sans les notes à plusieurs lignes (leur texte libre n'est pas du modèle)."""
    return _NOTE_BLOCK.sub("", puml)
