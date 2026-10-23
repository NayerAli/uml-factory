"""Serveur MCP : accès fichiers du projet (il ne comprend pas l'UML, c'est le rôle du LLM).

Outils exposés :
  read_puml(path)                          -> texte du fichier PlantUML
  write_sources(dest_dir, files, ...)      -> écrit les sources générées dans le dossier choisi

Garde-fous : seuls les fichiers .puml/.plantuml/.pu sont lisibles ; l'écriture refuse les chemins
qui sortiraient du dossier de destination et ne remplace jamais un fichier existant au contenu différent
(sauf `overwrite=True`).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from .config import load_env_file, load_settings
from .paths import safe_relative_path

PUML_SUFFIXES = {".puml", ".plantuml", ".pu", ".uml"}
MAX_PUML_BYTES = 1_000_000
MAX_FILE_BYTES = 2_000_000
MAX_FILES = 2_000


class PumlDocument(BaseModel):
    path: str
    text: str


class SourceFile(BaseModel):
    path: str
    content: str


class WriteReport(BaseModel):
    dest_dir: str
    written: list[str]


def read_puml_file(path: str) -> PumlDocument:
    p = Path(path).expanduser()
    if p.suffix.lower() not in PUML_SUFFIXES:
        raise ValueError(f"seuls les fichiers {', '.join(sorted(PUML_SUFFIXES))} sont lisibles : {path}")
    if not p.is_file():
        raise ValueError(f"fichier introuvable : {path}")
    if p.stat().st_size > MAX_PUML_BYTES:
        raise ValueError(f"fichier PlantUML trop volumineux (> {MAX_PUML_BYTES} octets)")
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    if "@startuml" not in text.lower():
        raise ValueError("ce fichier ne contient pas de diagramme PlantUML (@startuml absent)")
    return PumlDocument(path=str(p.resolve()), text=text)


def write_source_files(dest_dir: str, files: list[SourceFile], overwrite: bool = False) -> WriteReport:
    if not dest_dir.strip():
        raise ValueError("dossier de destination vide")
    if not files:
        raise ValueError("aucun fichier à écrire")
    if len(files) > MAX_FILES:
        raise ValueError(f"trop de fichiers ({len(files)})")
    root = Path(dest_dir).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise ValueError(f"la destination existe et n'est pas un dossier : {root}")

    plan: list[tuple[str, Path, bytes]] = []
    seen: set[str] = set()
    for f in files:
        rel = safe_relative_path(f.path).as_posix()
        if rel in seen:
            raise ValueError(f"chemin en double : {rel}")
        seen.add(rel)
        data = f.content.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"fichier trop volumineux : {rel}")
        target = (root / Path(*rel.split("/"))).resolve()
        if root not in target.parents:
            raise ValueError(f"sortie du dossier de destination : {rel}")
        plan.append((rel, target, data))

    conflicts = [rel for rel, target, data in plan if target.is_file() and target.read_bytes() != data]
    if conflicts and not overwrite:
        raise ValueError(
            "fichiers existants différents (rien n'a été écrit) : " + ", ".join(conflicts[:10])
            + (" …" if len(conflicts) > 10 else "")
            + ". Choisir un autre dossier ou autoriser l'écrasement (--overwrite)."
        )
    for _, target, data in plan:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return WriteReport(dest_dir=str(root), written=[str(t) for _, t, _ in plan])


_READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def build_server() -> MCPServer:
    mcp = MCPServer(
        "umlfactory-files",
        instructions=(
            "Accès fichiers pour umlfactory : read_puml lit un diagramme PlantUML, write_sources écrit "
            "les fichiers sources générés dans le dossier de destination choisi par l'utilisateur."
        ),
    )

    @mcp.tool(description="Lit un fichier PlantUML (.puml) et renvoie son texte.", annotations=_READ)
    def read_puml(path: str) -> PumlDocument:
        try:
            return read_puml_file(path)
        except ValueError as exc:               # ToolError : le message arrive tel quel chez le client
            raise ToolError(str(exc)) from exc

    @mcp.tool(
        description=("Écrit des fichiers sources (chemins relatifs) dans dest_dir. Refuse de remplacer un "
                     "fichier existant au contenu différent sauf overwrite=true."),
        annotations=_WRITE,
    )
    def write_sources(dest_dir: str, files: list[SourceFile], overwrite: bool = False) -> WriteReport:
        try:
            return write_source_files(dest_dir, files, overwrite=overwrite)
        except (ValueError, OSError) as exc:
            raise ToolError(str(exc)) from exc

    return mcp


def main() -> None:
    """`python -m umlfactory.mcp_server [--host H] [--port N]` : serveur MCP en HTTP (Streamable HTTP)."""
    load_env_file()
    parsed = urlparse(load_settings(require_api=False).mcp_url)
    parser = argparse.ArgumentParser(description="Serveur MCP umlfactory (lecture .puml, écriture des sources)")
    parser.add_argument("--host", default="127.0.0.1", help="127.0.0.1 par défaut : accès local uniquement")
    parser.add_argument("--port", type=int, default=parsed.port or 9000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = parsed.path or "/mcp"
    print(f"Serveur MCP : http://{args.host}:{args.port}{path}", flush=True)
    asyncio.run(build_server().run_streamable_http_async(host=args.host, port=args.port, streamable_http_path=path))


if __name__ == "__main__":
    main()
