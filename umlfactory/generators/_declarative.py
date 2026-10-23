"""Agent générateur piloté par une SPÉCIFICATION (umlfactory/langspecs/<id>.json) : aucun code propre au langage.

Le préfixe « _ » exclut ce fichier de la liste des langages (il n'est pas un langage lui-même).
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path, PurePosixPath

from ..languages import LanguageSpec, forbidden_generated
from ..verify import Runtime, VerifyContext, VerifyReport, clean_env, compute_score, find_tool, run, write_tree
from .base import BaseGeneratorAgent, Validation


def expand_command(argv: list[str], files: list[str], src_dir: str, one: str | None = None) -> list[str]:
    """Remplace {files} (une entrée par fichier), {file} (le fichier `one`) et {dir}. Aucun shell n'est utilisé."""
    out: list[str] = []
    for arg in argv:
        if arg == "{files}":
            out.extend(files)
        elif arg == "{file}":
            out.append(one or "")
        else:
            out.append(arg.replace("{dir}", src_dir))
    return out


class CommandRuntime(Runtime):
    """Vérifie un langage ajouté en lançant la commande de la spécification (compilation ou contrôle de syntaxe)."""

    def __init__(self, spec: LanguageSpec) -> None:
        self.spec = spec
        self.tools = tuple(spec.tools)
        self.sensitive = {f"appel sensible « {s} »": re.escape(s) for s in spec.sensitive_calls}

    def check(self, ctx: VerifyContext) -> VerifyReport:
        banned = forbidden_generated(list(ctx.files))
        if banned:
            return self.finish(ctx, VerifyReport(
                score=0, skipped="fichiers de projet interdits",
                errors={p: "this file type can run code at build time and is not allowed: generate source files only"
                        for p in banned}))
        blocked = self.blocked(ctx)
        if blocked is not None:
            return self.finish(ctx, blocked)
        report = VerifyReport()
        if not self.spec.build:
            report.skipped = "aucune commande de vérification pour ce langage"
            report.notes.append(f"{self.spec.display_name} : code non compilé (aucune commande de vérification)")
            return self.finish(ctx, report)
        tracker = ctx.tracker
        failures: dict[str, str] = {}
        res = None
        with tempfile.TemporaryDirectory(prefix="umlfactory-lang-") as tmp:
            root = Path(tmp)
            src = root / "src"
            write_tree(src, ctx.files)
            write_tree(src, self.spec.scaffold)
            targets: list[str | None] = list(ctx.files) if "{file}" in self.spec.build else [None]
            env = clean_env(root)
            with tracker.measure(f"compilation ({PurePosixPath(self.spec.build[0]).name})") as step:
                for target in targets:
                    argv = expand_command(self.spec.build, list(ctx.files), str(src), target)
                    argv[0] = find_tool(argv[0]) or argv[0]
                    res = run(argv, src, min(tracker.left(), 8.0), env)
                    if res.timed_out or res.missing:
                        break
                    if not res.ok:
                        text = (res.err.strip() or res.out.strip() or f"exit code {res.code}")
                        failures[target or ""] = text.replace(str(src) + "/", "").replace(str(src) + "\\", "")[:3000]
                step.ok = not failures and res is not None and res.ok
        if res is None or res.timed_out:
            report.skipped = "délai dépassé pendant la compilation"
            report.notes.append("vérification interrompue : la compilation a dépassé le budget de temps (non vérifié)")
            return self.finish(ctx, report)
        if res.missing:
            report.skipped = "outil introuvable"
            report.notes.append(f"{self.spec.build[0]} introuvable sur cet appareil")
            return self.finish(ctx, report)
        if not failures:
            report.score = compute_score([(10, 1.0), (90, 1.0)])
            report.details.append("seule la compilation est vérifiée pour ce langage (pas de test de fumée)")
            return self.finish(ctx, report)
        for target, text in failures.items():
            if target:
                report.errors[target] = "build command failed:\n" + text
            else:                                           # une seule commande pour tous les fichiers
                hit = [p for p in ctx.files if p in text or PurePosixPath(p).name in text]
                for path in (hit or list(ctx.files)[:8]):
                    report.errors[path] = "build command failed:\n" + text
        ok_fraction = 1 - len(report.errors) / max(1, len(ctx.files))
        report.score = compute_score([(10, 1.0), (90, max(0.0, ok_fraction) * 0.5)])
        return self.finish(ctx, report)


class DeclarativeGenerator(BaseGeneratorAgent):
    def __init__(self, spec: LanguageSpec) -> None:
        self.spec = spec
        self.language = spec.id
        self.display_name = spec.display_name
        self.file_extensions = tuple(spec.file_extensions)
        self.source_media_type = spec.source_media_type
        self.plan_rules = spec.plan_rules
        self.style_rules = spec.style_rules.strip() + "\n"
        self.version = f"spec-{spec.status}"

    def runtime(self) -> Runtime:
        return CommandRuntime(self.spec)

    def validate(self, files: dict[str, str]) -> Validation:
        return Validation()          # contrôle statique minimal : la vérification se fait par la commande
