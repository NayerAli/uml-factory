"""Planification : requête de génération, plan de fichiers et suivi de progression du LLM."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Awaitable, Callable

from pydantic import BaseModel, Field

from ..llm import LLMClient, LLMError
from ..paths import UnsafePathError, safe_relative_path
from ..textutil import declared_names, extract_json

MAX_PUML_CHARS = 200_000
MAX_PLANNED_FILES = 300
PLAN_ATTEMPTS = 3
EVENT_INTERVAL = 0.25                     # secondes entre deux événements de progression d'un même fichier
Emit = Callable[[dict], Awaitable[None]]


class _Tracker:
    """Transforme les morceaux reçus du LLM en événements de progression (au plus ~4 par seconde).

    État annoncé : « thinking » (réflexion du modèle) ou « writing » (code en cours d'écriture),
    avec le nombre de caractères reçus et la dernière ligne écrite.
    """

    def __init__(self, emit: Emit, template: dict) -> None:
        self.emit, self.template = emit, template
        self.content, self.reasoning, self.state, self.last = "", 0, "", 0.0

    def _visible(self) -> tuple[str, bool]:
        low = self.content.lower()
        opened = low.rfind("<think>")
        if opened != -1 and low.find("</think>", opened) == -1:
            return self.content[:opened], True                 # réflexion balisée encore ouverte
        return self.content, False

    async def __call__(self, kind: str, text: str) -> None:
        if kind == "reset":
            self.content, self.reasoning, self.state = "", 0, ""
        elif kind == "reasoning":
            self.reasoning += len(text)
        else:
            self.content += text
        visible, thinking = self._visible()
        state = "thinking" if (thinking or (kind == "reasoning" and not visible.strip())) else "writing"
        now = time.monotonic()
        if state == self.state and now - self.last < EVENT_INTERVAL:
            return
        self.state, self.last = state, now
        lines = [ln.strip() for ln in re.sub(r"<think>.*?(</think>|$)", "", visible, flags=re.S | re.I).splitlines()
                 if ln.strip() and not ln.strip().startswith("```")]
        await self.emit({**self.template, "state": state, "chars": len(visible), "thought": self.reasoning,
                         "preview": lines[-1][:90] if lines else ""})



class GenerationRequest(BaseModel):
    puml: str = Field(min_length=10, max_length=MAX_PUML_CHARS)
    package: str | None = Field(default=None, max_length=120,
                                pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
    instructions: str | None = Field(default=None, max_length=2000)
    provider: str | None = Field(default=None, pattern=r"^(openai|anthropic)$")


@dataclass(frozen=True)
class PlannedFile:
    path: str
    elements: tuple[str, ...]
    summary: str




class PlanningMixin:
    """Découpage du diagramme en fichiers (utilise `_plan_messages` de PromptsMixin)."""

    def normalize_path(self, path: str, package: str | None) -> str:
        """Impose le dossier du package (Java : com/x/Foo.java ; Python : pkg/foo.py)."""
        if not package:
            return path
        folder = package.replace(".", "/")
        return path if path.startswith(folder + "/") else f"{folder}/{PurePosixPath(path).name}"

    def _parse_plan(self, data: dict, req: GenerationRequest) -> tuple[list[PlannedFile] | None, list[str], list[str]]:
        raw = data.get("files")
        if not isinstance(raw, list) or not raw:
            return None, ["'files' must be a non-empty list"], []
        problems: list[str] = []
        plan: list[PlannedFile] = []
        seen: set[str] = set()
        for item in raw[:MAX_PLANNED_FILES]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                problems.append("every file needs a string 'path'")
                continue
            path = self.normalize_path(item["path"].strip().replace("\\", "/"), req.package)
            try:
                safe_relative_path(path)
            except UnsafePathError as exc:
                problems.append(str(exc))
                continue
            if not path.endswith(self.file_extensions):
                problems.append(f"{path}: expected extension {' or '.join(self.file_extensions)}")
            elif path in seen:
                problems.append(f"duplicate path {path}")
            else:
                seen.add(path)
                elements = item.get("elements") if isinstance(item.get("elements"), list) else []
                plan.append(PlannedFile(path, tuple(str(e) for e in elements if isinstance(e, str)),
                                        str(item.get("summary", ""))[:200]))
        if problems:
            return None, problems, []
        covered = {e for pf in plan for e in pf.elements}
        return plan, [], [n for n in declared_names(req.puml) if n not in covered]

    async def _plan(self, req: GenerationRequest, llm: LLMClient, warnings: list[str],
                    emit: Emit) -> list[PlannedFile]:
        messages = self._plan_messages(req)
        feedback = ""
        for attempt in range(1, PLAN_ATTEMPTS + 1):
            reply = await llm.chat(messages, on_delta=_Tracker(emit, {"event": "phase", "text": "planification"}))
            plan: list[PlannedFile] | None = None
            missing: list[str] = []
            try:
                plan, problems, missing = self._parse_plan(extract_json(reply), req)
            except ValueError as exc:
                problems = [str(exc)]
            if plan is not None and not missing:
                return plan
            if plan is not None and attempt == PLAN_ATTEMPTS:      # plan exploitable mais incomplet
                warnings.append("éléments du diagramme absents du plan : " + ", ".join(missing))
                return plan
            if plan is None and attempt == PLAN_ATTEMPTS:
                raise LLMError("le LLM n'a pas produit de plan de fichiers exploitable : " + "; ".join(problems))
            feedback = ("Your plan is invalid: " + "; ".join(problems)) if plan is None else \
                       ("These diagram elements are not in your plan: " + ", ".join(missing))
            messages = [*messages, {"role": "assistant", "content": reply},
                        {"role": "user", "content": feedback + ". Reply again with the corrected JSON only."}]
        raise AssertionError("unreachable")
