"""Langages ajoutés à la volée : une SPÉCIFICATION (données JSON validées), jamais du code écrit par un LLM.

La spécification décrit les règles de génération, les outils requis sur l'appareil et la commande de vérification.
Cette commande est exécutée sur la machine de l'utilisateur : elle est donc restreinte à une liste de compilateurs
connus, sans shell, et l'utilisateur la valide avant la première exécution (champ `approved`).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from .paths import UnsafePathError, safe_relative_path

log = logging.getLogger(__name__)

SPEC_DIR = Path(__file__).parent / "langspecs"
VALIDATED_MIN = 75           # score moyen (sur 100) à partir duquel un langage est « validé »

# Seuls ces exécutables peuvent être lancés pour vérifier un langage ajouté.
ALLOWED_TOOLS = frozenset({
    "javac", "java", "python", "python3", "py", "go", "gofmt", "rustc", "cargo", "node", "tsc", "deno", "bun",
    "dotnet", "csc", "kotlinc", "kotlin", "swiftc", "swift", "gcc", "g++", "cc", "clang", "clang++", "php", "ruby",
    "perl", "dart", "scalac", "scala", "ghc", "lua", "luac", "nim", "zig", "ocamlc", "ocamlfind", "fpc", "crystal",
    "julia", "Rscript", "groovy", "gfortran", "gnatmake", "dmd", "ldc2", "v", "odin",
})
_BAD_ARG = re.compile(r"[;&|`$<>\n\r\x00]")
_BAD_SCAFFOLD_CONTENT = re.compile(r"<\s*Exec\b|<\s*Target\b|\bCommand\s*=|\bpostinstall\b|\bprebuild\b", re.IGNORECASE)
FORBIDDEN_FILES = frozenset({"build.rs", "makefile", "cmakelists.txt", "package.json", "setup.py", "conftest.py",
                             "pom.xml", "build.gradle", "build.gradle.kts", "gradlew", "directory.build.props",
                             "directory.build.targets", "justfile"})
FORBIDDEN_SUFFIXES = (".csproj", ".fsproj", ".vbproj", ".sln", ".targets", ".props", ".gemspec", ".bat", ".cmd", ".sh",
                      ".ps1")
PLACEHOLDERS = ("{files}", "{file}", "{dir}")      # {file} : une exécution par fichier généré


class LanguageSpec(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9]{0,19}$")
    display_name: str = Field(min_length=1, max_length=40)
    file_extensions: list[str] = Field(min_length=1, max_length=4)
    source_media_type: str = Field(default="text/plain", pattern=r"^[a-z]+/[a-z0-9.+-]{1,40}$")
    plan_rules: str = Field(max_length=1500)
    style_rules: str = Field(max_length=4000)
    tools: list[str] = Field(default_factory=list, max_length=4)
    build: list[str] = Field(default_factory=list, max_length=30)      # argv, avec {files} et {dir}
    scaffold: dict[str, str] = Field(default_factory=dict)             # fichiers de projet fixes (go.mod…)
    sensitive_calls: list[str] = Field(default_factory=list, max_length=30)   # sous-chaînes LITTÉRALES interdites
    status: Literal["draft", "experimental", "validated"] = "draft"
    approved: bool = False                    # l'utilisateur a validé la commande de vérification
    score: int | None = None
    install_guide: str | None = None

    @field_validator("file_extensions")
    @classmethod
    def _extensions(cls, value: list[str]) -> list[str]:
        for ext in value:
            if not re.fullmatch(r"\.[a-z0-9+#]{1,8}", ext):
                raise ValueError(f"extension invalide : {ext!r}")
        return value

    @field_validator("sensitive_calls")
    @classmethod
    def _sensitive(cls, value: list[str]) -> list[str]:
        return [v for v in value if isinstance(v, str) and 1 <= len(v) <= 60]


def sanitize_id(name: str) -> str:
    """'C++' -> 'cpp', 'C#' -> 'csharp', 'Type Script' -> 'typescript'."""
    text = name.strip().lower().replace("++", "pp").replace("#", "sharp")
    text = re.sub(r"[^a-z0-9]", "", text)
    return text[:20] if text[:1].isalpha() else ""


def safety_problems(spec: LanguageSpec) -> list[str]:
    """Raisons pour lesquelles la spécification ne peut pas être exécutée sur la machine de l'utilisateur."""
    problems: list[str] = []
    for tool in spec.tools:
        if tool not in ALLOWED_TOOLS:
            problems.append(f"outil « {tool} » hors de la liste autorisée")
    if spec.build:
        head = PurePosixPath(spec.build[0].replace("\\", "/")).name
        if head not in ALLOWED_TOOLS:
            problems.append(f"la commande de vérification doit commencer par un compilateur connu (reçu : {spec.build[0]!r})")
        elif head not in spec.tools:
            problems.append(f"« {head} » doit aussi figurer dans `tools`")
        for arg in spec.build:
            if _BAD_ARG.search(arg):
                problems.append(f"argument refusé dans la commande : {arg!r}")
            if "{" in arg and arg not in PLACEHOLDERS and not all(p in PLACEHOLDERS for p in re.findall(r"\{[^}]*\}", arg)):
                problems.append(f"marqueur inconnu dans la commande : {arg!r}")
    for rel, content in spec.scaffold.items():
        try:
            safe_relative_path(rel)
        except UnsafePathError as exc:
            problems.append(str(exc))
            continue
        name = PurePosixPath(rel).name.lower()
        if name in FORBIDDEN_FILES or name.endswith(FORBIDDEN_SUFFIXES):
            problems.append(f"fichier de projet refusé : {rel}")
        if _BAD_SCAFFOLD_CONTENT.search(content) or len(content) > 4000:
            problems.append(f"contenu refusé dans {rel} (tâche exécutable ou trop long)")
    return problems


def forbidden_generated(paths: list[str]) -> list[str]:
    """Fichiers générés qui déclencheraient du code à la compilation (ex. build.rs) : jamais acceptés."""
    return [p for p in paths if PurePosixPath(p).name.lower() in FORBIDDEN_FILES
            or PurePosixPath(p).name.lower().endswith(FORBIDDEN_SUFFIXES)]


# ---------------------------------------------------------------------------------- stockage

def spec_path(language_id: str) -> Path:
    return SPEC_DIR / f"{language_id}.json"


def guide_path(language_id: str) -> Path:
    return SPEC_DIR / f"{language_id}.install.txt"


def load_spec(language_id: str) -> LanguageSpec | None:
    path = spec_path(language_id)
    if not re.fullmatch(r"[a-z][a-z0-9]{0,19}", language_id) or not path.is_file():
        return None
    try:
        spec = LanguageSpec.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError, OSError) as exc:
        log.warning("spécification de langage illisible (%s) : %s", path.name, exc)
        return None
    return spec if spec.id == language_id and not safety_problems(spec) else None


def save_spec(spec: LanguageSpec) -> Path:
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    path = spec_path(spec.id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(spec.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return path


def delete_spec(language_id: str) -> None:
    for path in (spec_path(language_id), guide_path(language_id)):
        path.unlink(missing_ok=True)


def list_specs() -> list[LanguageSpec]:
    if not SPEC_DIR.is_dir():
        return []
    found = (load_spec(p.stem) for p in sorted(SPEC_DIR.glob("*.json")))
    return [s for s in found if s is not None]


def active_ids() -> list[str]:
    """Langages ajoutés qui doivent recevoir un agent au démarrage (validés ou expérimentaux, commande approuvée)."""
    return [s.id for s in list_specs() if s.approved and s.status in ("experimental", "validated")]
