"""Terminal : couleurs, largeurs d'affichage et mise en forme de texte."""

from __future__ import annotations

import os
import shutil
import sys
import unicodedata


class Term:
    def __init__(self) -> None:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
            except (AttributeError, ValueError):
                pass
        self.tty = sys.stdout.isatty()
        self.color = self.tty and not os.environ.get("NO_COLOR")
        if os.name == "nt" and self.tty:
            self._enable_windows_ansi()

    @staticmethod
    def _enable_windows_ansi() -> None:
        try:
            import ctypes
            kernel = ctypes.windll.kernel32            # type: ignore[attr-defined]
            handle = kernel.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel.SetConsoleMode(handle, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:  # noqa: BLE001
            pass

    @property
    def width(self) -> int:
        return max(40, shutil.get_terminal_size((100, 30)).columns - 1)

    @property
    def height(self) -> int:
        return shutil.get_terminal_size((100, 30)).lines

    def paint(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.color else text

    def dim(self, t: str) -> str: return self.paint("2", t)
    def green(self, t: str) -> str: return self.paint("32", t)
    def red(self, t: str) -> str: return self.paint("31", t)
    def yellow(self, t: str) -> str: return self.paint("33", t)
    def cyan(self, t: str) -> str: return self.paint("36", t)
    def bold(self, t: str) -> str: return self.paint("1", t)

    def write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s}s" if s < 60 else f"{s // 60}m{s % 60:02d}s"


def fmt_size(n: int) -> str:
    """Taille d'un texte généré, en caractères (jamais en tokens : l'API ne les compte pas ici)."""
    if n >= 1000:
        return f"{n / 1000:.1f} k caractères".replace(".", ",")
    return f"{n} caractère{'s' if n > 1 else ''}"


def fmt_seconds(seconds: float) -> str:
    return f"{seconds:.1f} s".replace(".", ",")


def clean(text: str) -> str:
    """Texte sur une seule ligne, sans tabulations ni caractères de contrôle (ils décalent l'affichage)."""
    text = "".join(ch if ch.isprintable() else " " for ch in text.replace("\t", " "))
    return " ".join(text.split())


def char_width(ch: str) -> int:
    """Colonnes occupées à l'écran : 0 pour les accents combinés, 2 pour les caractères larges et les emoji."""
    if unicodedata.combining(ch) or ch in "\u200d\ufe0f":
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) >= 0x1F300:
        return 2
    return 1


def text_width(text: str) -> int:
    return sum(char_width(ch) for ch in text)


def fit(text: str, width: int) -> str:
    """Tronque en tenant compte de la largeur réelle à l'écran (un emoji compte pour deux colonnes)."""
    if text_width(text) <= width:
        return text
    out, used = [], 0
    for ch in text:
        cw = char_width(ch)
        if used + cw > width - 1:
            break
        out.append(ch)
        used += cw
    return "".join(out) + "…"
