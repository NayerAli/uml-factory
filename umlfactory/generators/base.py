"""Agent générateur A2A piloté par un LLM.

Aucune analyse UML n'est codée ici : le LLM lit le PlantUML, planifie les fichiers, écrit chaque
fichier, puis l'agent VALIDE le résultat (compilation / syntaxe) et renvoie les erreurs au LLM
pour correction. Une sous-classe de langage ne fournit que ses règles de style et son validateur.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from a2a.helpers.proto_helpers import get_data_parts, new_task_from_user_message, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Part
from pydantic import ValidationError

from ..a2a_common import send_event
from ..config import ConfigError, load_settings
from ..llm import LLMClient, LLMError
from ..textutil import extract_code
from ..umlmodel import Model, parse as parse_uml
from ..verify import DEFAULT_BUDGET, SLOW_AFTER, Runtime, Tracker, VerifyContext, VerifyReport
from .planning import (EVENT_INTERVAL, MAX_PLANNED_FILES, MAX_PUML_CHARS, PLAN_ATTEMPTS, Emit, GenerationRequest,  # noqa: F401
                       PlannedFile, PlanningMixin, _Tracker)
from .prompts import CONVERSION_RULES, SIBLING_CONTEXT_CHARS, PromptsMixin, repair_hint  # noqa: F401
from .repair import JUDGE_SYSTEM, MAX_REPAIRS, RepairMixin, Validation, judge_conformity, unverified  # noqa: F401

log = logging.getLogger(__name__)

REPORT_ARTIFACT = "_report.json"          # artefact réservé : avertissements, pas un fichier source


@dataclass
class GenerationResult:
    files: dict[str, str]
    warnings: list[str] = field(default_factory=list)
    verification: dict | None = None           # étapes de vérification (voir verify.VerifyReport) et clé « conformity »


class BaseGeneratorAgent(PromptsMixin, PlanningMixin, RepairMixin, AgentExecutor, ABC):
    language: ClassVar[str]                  # "java", "python", "cpp"...
    display_name: ClassVar[str]
    file_extensions: ClassVar[tuple[str, ...]]
    style_rules: ClassVar[str]               # règles de génération propres au langage
    plan_rules: ClassVar[str]                # règles de découpage en fichiers
    source_media_type: ClassVar[str] = "text/plain"
    version: ClassVar[str] = "0.1.0"
    conformity_rules: ClassVar[str] = ""     # conseils au modèle pour comparer le code au diagramme dans ce langage

    @abstractmethod
    def validate(self, files: dict[str, str]) -> Validation:
        """Contrôle déterministe et statique (syntaxe, cohérence). Appelé dans un thread : peut être bloquant."""

    def runtime(self) -> Runtime | None:
        """Vérification d'exécution du langage (compilation, test de fumée, conformité), ou None si non prévue."""
        return None

    # ------------------------------------------------------------------ pipeline

    async def _verify(self, files: dict[str, str], plan: list[PlannedFile], req: GenerationRequest, budget: float,
                      say: Emit) -> VerifyReport | None:
        """Palier d'exécution : tourne dans un thread, signale l'étape en cours si elle dépasse SLOW_AFTER secondes."""
        runtime = self.runtime()
        if runtime is None:
            return None
        try:
            model = parse_uml(req.puml)
        except Exception:  # noqa: BLE001 - l'analyse n'est qu'un contrôle : jamais bloquante
            log.exception("analyse du diagramme impossible pour la vérification")
            model = Model()
        ctx = VerifyContext(files=dict(files), model=model, package=req.package, tracker=Tracker(budget),
                            class_files={e: pf.path for pf in plan for e in pf.elements})
        job = asyncio.create_task(asyncio.to_thread(runtime.check, ctx))
        started, announced = time.monotonic(), ""
        while True:
            await asyncio.wait({job}, timeout=0.25)
            if job.done():
                break
            step = ctx.tracker.step
            if time.monotonic() - started >= SLOW_AFTER and step and step != announced:
                announced = step
                await say({"event": "verify", "state": "slow", "step": step})
        try:
            report = job.result()
        except Exception as exc:  # noqa: BLE001
            log.exception("échec de la vérification d'exécution")
            report = VerifyReport(skipped=f"erreur interne de vérification : {exc}",
                                  notes=[f"vérification d'exécution impossible : {exc}"])
        await say({"event": "verify", "state": "done", "score": report.score, "seconds": round(report.seconds, 1),
                   "skipped": report.skipped})
        return report

    async def generate(self, req: GenerationRequest, llm: LLMClient, concurrency: int, max_repairs: int,
                       emit: Emit | None = None, verify_budget: float = DEFAULT_BUDGET) -> GenerationResult:
        async def say(event: dict) -> None:
            log.info("%s", event)
            if emit is not None:
                await emit(event)

        warnings: list[str] = []
        await say({"event": "phase", "text": "planification"})
        plan = await self._plan(req, llm, warnings, say)
        await say({"event": "plan", "files": [p.path for p in plan]})
        await say({"event": "phase", "text": "génération"})

        sem = asyncio.Semaphore(max(1, concurrency))

        async def write_one(pf: PlannedFile) -> tuple[str, str]:
            async with sem:
                await say({"event": "file", "path": pf.path, "state": "start"})
                reply = await llm.chat(self._file_messages(req, plan, pf),
                                       on_delta=_Tracker(say, {"event": "file", "path": pf.path}))
                code = extract_code(reply)
                await say({"event": "file", "path": pf.path, "state": "done", "chars": len(code)})
                return pf.path, code

        files = dict(await asyncio.gather(*(write_one(pf) for pf in plan)))

        verification: VerifyReport | None = None
        unresolved: list[str] = []
        for round_no in range(max_repairs + 1):
            await say({"event": "phase", "text": "vérification du code"})
            check = await asyncio.to_thread(self._check, files, plan)
            verification = None
            if check.errors:
                verification = VerifyReport(score=0, skipped="code invalide (erreurs statiques)")
            elif verify_budget:
                verification = await self._verify(files, plan, req, verify_budget, say)
                if verification is not None:
                    check.errors.update(verification.errors)
                    check.notes.extend(n for n in verification.notes if n not in check.notes)
            if not check.errors:
                warnings.extend(n for n in check.notes if n not in warnings)
                break
            for path, problem in check.errors.items():
                await say({"event": "file", "path": path, "state": "error", "detail": problem.splitlines()[0][:100]})
            if round_no == max_repairs:
                unresolved = [f"{p} : {e.splitlines()[0][:100]}" for p, e in check.errors.items()]
                warnings.extend(f"{p} : {e}" for p, e in check.errors.items())
                warnings.extend(n for n in check.notes if n not in warnings)
                break
            await say({"event": "phase", "text": f"correction {round_no + 1}/{max_repairs}"})

            async def fix_one(path: str, problem: str) -> tuple[str, str]:
                async with sem:
                    await say({"event": "file", "path": path, "state": "fix"})
                    reply = await llm.chat(self._repair_messages(req, plan, files, path, problem),
                                           on_delta=_Tracker(say, {"event": "file", "path": path, "fix": True}))
                    code = extract_code(reply) or files.get(path, "")
                    await say({"event": "file", "path": path, "state": "done", "chars": len(code)})
                    return path, code

            files.update(await asyncio.gather(*(fix_one(p, e) for p, e in check.errors.items())))
        summary = verification.as_dict() if verification is not None else {}
        await say({"event": "phase", "text": "comparaison avec le diagramme"})
        try:
            parsed = parse_uml(req.puml)
        except Exception:  # noqa: BLE001
            parsed = Model()
        if not parsed.classes:
            conformity = unverified("le diagramme n'a pas pu être analysé")
        else:
            evidence = [*warnings, *(verification.notes if verification else []),
                        *(verification.details if verification else [])]
            conformity = await judge_conformity(llm, req.puml, files, self.conformity_rules, evidence, unresolved)
        if verification is not None and verification.skipped:
            conformity["not_run"] = verification.skipped            # compilation / exécution non faites : à dire
        summary["conformity"] = conformity
        return GenerationResult(files=files, warnings=warnings, verification=summary)

    # ------------------------------------------------------------------ Agent Card

    @property
    def skill_tag(self) -> str:
        return f"codegen:{self.language}"

    def build_card(self, base_url: str) -> AgentCard:
        runtime = self.runtime()
        skill = AgentSkill(
            id=f"codegen-{self.language}",
            name=f"Génération de code {self.display_name}",
            description=(f"Reçoit un diagramme PlantUML et renvoie le code {self.display_name} correspondant "
                         "(écrit par un LLM, validé par compilation/syntaxe), un artefact par fichier."),
            tags=[self.skill_tag, "uml", "codegen"],
            examples=[f"Génère le code {self.display_name} de ce diagramme PlantUML"],
            input_modes=["application/json"],
            output_modes=[self.source_media_type],
        )
        return AgentCard(
            name=f"generateur-{self.language}",
            description=f"Agent générateur {self.display_name} : PlantUML -> code, via LLM.",
            version=self.version,
            supported_interfaces=[AgentInterface(url=base_url, protocol_binding="JSONRPC", protocol_version="1.0")],
            capabilities=AgentCapabilities(streaming=True),
            default_input_modes=["application/json"],
            default_output_modes=[self.source_media_type],
            skills=[skill, *self._verify_skills(runtime)],
        )

    def _verify_skills(self, runtime: Runtime | None) -> list[AgentSkill]:
        """Skill de vérification d'exécution de cet agent (les outils requis sont des tags `tool:<exécutable>`)."""
        if runtime is None:
            return []
        return [AgentSkill(
            id=f"verify-{self.language}",
            name=f"Vérification d'exécution {self.display_name}",
            description=("Compile et exécute le code généré sur cet appareil (dossier jetable, délai strict, "
                         "environnement nettoyé), contrôle sa conformité au diagramme et calcule un score de fiabilité."),
            tags=["verify:runtime", f"verify:{self.language}", *(f"tool:{t}" for t in runtime.tools)],
            examples=[f"Vérifie que le code {self.display_name} généré compile et s'exécute"],
            input_modes=["application/json"],
            output_modes=["application/json"],
        )]

    # ------------------------------------------------------------------ protocole A2A

    @staticmethod
    def read_request(parts) -> GenerationRequest:
        data = get_data_parts(parts)
        if not data:
            raise ValueError('le message doit contenir un objet JSON {"puml": "...", "package": "...?"}')
        return GenerationRequest.model_validate(data[0])

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        def note(text: str):
            return new_text_message(text, context_id=task.context_id, task_id=task.id)

        try:
            req = self.read_request(message.parts)
        except (ValueError, ValidationError) as exc:
            await updater.failed(note(f"requête invalide : {exc}"))
            return
        try:
            settings = load_settings(provider=req.provider)
        except ConfigError as exc:
            await updater.failed(note(f"configuration LLM : {exc}"))
            return

        await updater.start_work()

        async def emit(event: dict) -> None:
            await send_event(updater, task.context_id, task.id, event)

        try:
            result = await self.generate(req, LLMClient(settings), settings.concurrency,
                                         MAX_REPAIRS, emit, settings.verify_budget)
        except LLMError as exc:
            await updater.failed(note(f"échec LLM : {exc}"))
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("échec de génération")
            await updater.failed(note(f"échec de génération {self.display_name} : {exc}"))
            return

        for path, content in result.files.items():
            await updater.add_artifact(
                parts=[Part(text=content, filename=path, media_type=self.source_media_type)],
                name=path, metadata={"language": self.language, "path": path})
        await updater.add_artifact(
            parts=[Part(text=json.dumps({"warnings": result.warnings, "model": settings.model,
                                         "verification": result.verification}, ensure_ascii=False),
                        filename=REPORT_ARTIFACT, media_type="application/json")],
            name=REPORT_ARTIFACT)
        suffix = f", {len(result.warnings)} avertissement(s)" if result.warnings else ""
        await updater.complete(note(f"{len(result.files)} fichier(s) {self.display_name} généré(s){suffix}"))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is not None:
            await TaskUpdater(event_queue, task.id, task.context_id).cancel()
