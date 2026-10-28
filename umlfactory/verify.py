"""Vérification locale du code généré : outils présents sur l'appareil, exécution contrôlée, score de fiabilité.

Il n'y a PAS d'isolation système (pas de Docker) : le code tourne avec les droits de l'utilisateur, sur sa machine.
Les garde-fous sont volontairement simples :
  - le code est écrit dans un dossier temporaire jetable, jamais dans le projet ;
  - un délai strict (budget global, 10 s par défaut) ; au-delà, le résultat est « non vérifié », jamais « réussi » ;
  - un environnement nettoyé : ni clé d'API ni variable du `.env` ne sont transmises au code généré ;
  - un scan préalable des appels sensibles (processus, réseau, fichiers) : s'il y en a, rien n'est exécuté ;
  - seules des instanciations sont faites (jamais d'opération métier, jamais de `main`).
Ce module n'importe rien de la partie A2A/MCP : il peut être testé seul.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .umlmodel import Model

DEFAULT_BUDGET = 10.0          # secondes entre « code entièrement généré » et « verdict »
SLOW_AFTER = 1.0               # au-delà, l'interface affiche l'étape en cours
MAX_OUTPUT = 20_000

# Variables d'environnement transmises au code vérifié (liste blanche) : tout le reste est retiré.
_ENV_KEEP = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "JAVA_HOME", "LANG", "LANGUAGE", "TZ", "HOME",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    "GOROOT", "GOPATH", "GOCACHE", "CARGO_HOME", "RUSTUP_HOME", "DOTNET_ROOT", "DOTNET_CLI_HOME", "NVM_HOME",
}
_ENV_PREFIXES = ("LC_", "PROGRAMFILES", "COMMONPROGRAMFILES")


# ---------------------------------------------------------------------------------- outils sur l'appareil

def find_tool(name: str) -> str | None:
    """Chemin complet de l'exécutable sur cet appareil, ou None. `python` désigne l'interpréteur courant."""
    if name in ("python", "python3", "py") and shutil.which(name) is None:
        return sys.executable
    return shutil.which(name)


def missing_tools(tools: tuple[str, ...] | list[str]) -> list[str]:
    return [t for t in tools if find_tool(t) is None]


def clean_env(tmp: Path | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k.upper() in _ENV_KEEP or k.upper().startswith(_ENV_PREFIXES)}
    if tmp is not None:
        env["TMP"] = env["TEMP"] = env["TMPDIR"] = str(tmp)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


# ---------------------------------------------------------------------------------- exécution contrôlée

@dataclass
class RunResult:
    code: int | None
    out: str = ""
    err: str = ""
    timed_out: bool = False
    seconds: float = 0.0
    missing: bool = False

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out


def _text(data: str | bytes | None) -> str:
    if data is None:
        return ""
    return (data.decode("utf-8", "replace") if isinstance(data, bytes) else data)[:MAX_OUTPUT]


def run(cmd: list[str], cwd: Path, timeout: float, env: dict[str, str]) -> RunResult:
    """Lance une commande SANS shell, avec délai strict, entrée vide et sortie bornée."""
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=max(0.5, timeout))
    except subprocess.TimeoutExpired as exc:
        return RunResult(None, _text(exc.stdout), _text(exc.stderr), True, time.monotonic() - started)
    except FileNotFoundError:
        return RunResult(None, missing=True)
    except OSError as exc:
        return RunResult(None, "", str(exc), False, time.monotonic() - started)
    return RunResult(proc.returncode, _text(proc.stdout), _text(proc.stderr), False, time.monotonic() - started)


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------------- scan préalable

def scan_sensitive(files: dict[str, str], patterns: dict[str, str]) -> dict[str, list[str]]:
    """{chemin: [libellés]} des appels sensibles trouvés (processus, réseau, fichiers…)."""
    compiled = {label: re.compile(rx) for label, rx in patterns.items()}
    found: dict[str, list[str]] = {}
    for path, code in files.items():
        hits = [label for label, rx in compiled.items() if rx.search(code)]
        if hits:
            found[path] = hits
    return found


def sensitive_errors(found: dict[str, list[str]]) -> dict[str, str]:
    return {path: ("forbidden API usage detected: " + ", ".join(hits) + ". A class generated from a UML diagram "
                   "must be plain domain code: remove every use of processes, network, files or the environment.")
            for path, hits in found.items()}


# ---------------------------------------------------------------------------------- suivi et score

@dataclass
class Step:
    name: str
    seconds: float = 0.0
    ok: bool = True
    detail: str = ""


class Tracker:
    """Chronomètre des étapes + budget global ; lu par l'agent pour afficher l'étape en cours."""

    def __init__(self, budget: float = DEFAULT_BUDGET) -> None:
        self.began = time.monotonic()
        self.deadline = self.began + budget
        self.step = ""
        self.steps: list[Step] = []

    def left(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def elapsed(self) -> float:
        return time.monotonic() - self.began

    @contextmanager
    def measure(self, name: str):
        step = Step(name)
        self.step = name
        t0 = time.monotonic()
        try:
            yield step
        finally:
            step.seconds = time.monotonic() - t0
            self.steps.append(step)


def compute_score(parts: list[tuple[int, float | None]]) -> int:
    """Moyenne pondérée de paliers (poids, réussite entre 0 et 1) ; un palier non exécuté compte 0."""
    total = sum(w for w, _ in parts) or 1
    return round(100 * sum(w * (f or 0.0) for w, f in parts) / total)


@dataclass
class VerifyReport:
    score: int | None = None                      # None : exécution non faite (voir `skipped`)
    errors: dict[str, str] = field(default_factory=dict)       # chemin -> problème (renvoyé au LLM)
    notes: list[str] = field(default_factory=list)             # remarques non bloquantes
    steps: list[Step] = field(default_factory=list)
    seconds: float = 0.0
    skipped: str = ""
    details: list[str] = field(default_factory=list)           # constats mineurs, non affichés comme avertissements

    def as_dict(self) -> dict:
        return {"score": self.score, "seconds": round(self.seconds, 2), "skipped": self.skipped,
                "details": self.details[:10],
                "steps": [{"name": s.name, "seconds": round(s.seconds, 2), "ok": s.ok, "detail": s.detail}
                          for s in self.steps]}


@dataclass
class VerifyContext:
    files: dict[str, str]
    model: Model
    class_files: dict[str, str]          # nom de type UML -> chemin du fichier qui le définit
    tracker: Tracker
    package: str | None = None

    def file_of(self, name: str) -> str | None:
        if name in self.class_files:
            return self.class_files[name]
        norm = re.sub(r"[^a-z0-9]", "", name.lower())
        for path in self.files:
            stem = re.sub(r"[^a-z0-9]", "", Path(path).stem.lower())
            if stem == norm:
                return path
        return None


class Runtime(ABC):
    """Vérification d'exécution d'un langage. `tools` : exécutables requis sur l'appareil."""

    tools: tuple[str, ...] = ()
    sensitive: dict[str, str] = {}

    def missing(self) -> list[str]:
        return missing_tools(self.tools)

    def blocked(self, ctx: VerifyContext) -> VerifyReport | None:
        """Rapport « non exécuté » si un outil manque ou si des appels sensibles sont présents."""
        gone = self.missing()
        if gone:
            return VerifyReport(skipped="outil introuvable sur cet appareil : " + ", ".join(gone),
                                notes=["code non exécuté : " + ", ".join(gone) + " introuvable sur cet appareil"])
        found = scan_sensitive(ctx.files, self.sensitive)
        if found:
            return VerifyReport(score=0, errors=sensitive_errors(found), skipped="appels sensibles détectés",
                                notes=["code non exécuté : appels sensibles détectés (processus, réseau ou fichiers)"])
        return None

    @abstractmethod
    def check(self, ctx: VerifyContext) -> VerifyReport:
        """Vérifie le code. Appelé dans un thread ; doit respecter `ctx.tracker.left()`."""

    def finish(self, ctx: VerifyContext, report: VerifyReport) -> VerifyReport:
        report.steps = list(ctx.tracker.steps)
        report.seconds = ctx.tracker.elapsed()
        return report


# ---------------------------------------------------------------------------------- lecture des résultats des harnais

HARNESS_MARK = "@@UMLFACTORY@@"


@dataclass
class Finding:
    level: str        # OK | FAIL | SOFT
    kind: str         # import | class | extends | attr | op | rel | init
    cls: str
    msg: str


def parse_findings(stdout: str) -> list[Finding]:
    found: list[Finding] = []
    for line in stdout.splitlines():
        if line.startswith(HARNESS_MARK):
            parts = line[len(HARNESS_MARK):].split("|", 3)
            if len(parts) == 4:
                found.append(Finding(*[p.strip() for p in parts]))
    return found


def findings_to_report(ctx: VerifyContext, findings: list[Finding], compile_frac: float,
                       report: VerifyReport, executed: bool = True) -> VerifyReport:
    """Transforme les constats du harnais en erreurs (par fichier), remarques et score.

    `executed=False` : le code n'a pas pu être chargé (compilation en échec) ; les paliers suivants comptent 0."""
    def frac(kinds: set[str]) -> float | None:
        # un contrôle SKIP (classe jamais chargée, module en échec) n'est pas une réussite : il compte comme un échec
        rows = [f for f in findings if f.kind in kinds and f.level in ("OK", "FAIL", "SKIP")]
        return None if not rows else sum(1 for f in rows if f.level == "OK") / len(rows)

    for f in findings:
        if f.level == "FAIL":
            path = ctx.file_of(f.cls) or next(iter(ctx.files), "")
            label = {"import": "loading", "init": "smoke test"}.get(f.kind, "diagram conformity")
            message = f"{label}: {f.msg}"
            report.errors[path] = (report.errors.get(path, "") + "\n" + message).strip()
        elif f.level == "SOFT":
            target = report.notes if f.kind == "rel" else report.details      # cardinalité : à montrer à l'utilisateur
            if f.msg not in target:
                target.append(f.msg)
    smoke = frac({"init"})
    conformity = frac({"class", "extends", "attr", "op", "rel"})
    if not executed:
        smoke = conformity = 0.0
    # aucune classe dans le diagramme : rien à contrôler (100 %) ; des classes sans aucun contrôle exécuté : 0 %
    nothing_to_check = not any(f.kind == "class" for f in findings)
    no_evidence = 1.0 if nothing_to_check else 0.0
    report.score = compute_score([(10, 1.0), (40, compile_frac), (25, no_evidence if smoke is None else smoke),
                                  (25, no_evidence if conformity is None else conformity)])
    return report
