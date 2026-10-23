"""Chemins relatifs sûrs : tout nom de fichier venant d'un LLM ou d'un agent est une donnée non fiable."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

MAX_PATH_LEN = 200
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class UnsafePathError(ValueError):
    pass


def safe_relative_path(raw: str) -> PurePosixPath:
    """Accepte « a/b/C.java » ; refuse absolu, '..', '\\', lecteur Windows, formes non canoniques."""
    if not raw or len(raw) > MAX_PATH_LEN:
        raise UnsafePathError(f"nom de fichier vide ou trop long : {raw[:40]!r}")
    if "\x00" in raw or "\\" in raw or raw.startswith("/") or _WINDOWS_DRIVE.match(raw):
        raise UnsafePathError(f"nom de fichier refusé : {raw!r}")
    path = PurePosixPath(raw)
    if path.as_posix() != raw or any(p in ("", ".", "..") for p in path.parts):
        raise UnsafePathError(f"nom de fichier refusé : {raw!r}")
    for part in path.parts:
        if part.split(".")[0].lower() in _RESERVED or part.endswith((" ", ".")) or re.search(r'[<>:"|?*]', part):
            raise UnsafePathError(f"nom de fichier non portable : {raw!r}")
    return path
