"""Questions et menus au clavier : saisie, oui/non, menu à flèches (cases à cocher), choix de fichiers."""

from __future__ import annotations

import contextlib
import os
import sys

from .progress import fit_ansi
from .term import Term, clean

NEW_LANGUAGE = "+new"      # préfixe renvoyé quand l'utilisateur choisit « Autre langage… » (suivi de « :nom »)


# ------------------------------------------------------------------ questions

def ask(term: Term, question: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"{term.cyan('?')} {question}{suffix} : ").strip().strip('"')
        if answer:
            return answer
        if default:
            return default


def confirm(term: Term, question: str, default: bool = False) -> bool:
    answer = input(f"{term.cyan('?')} {question} [{'O/n' if default else 'o/N'}] : ").strip().lower()
    return default if not answer else answer in ("o", "oui", "y", "yes")


# ------------------------------------------------------------------ menus à flèches

def read_key() -> str:
    """Une touche : up, down, enter, space, esc, ou le caractère tapé. Ctrl+C lève KeyboardInterrupt."""
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(msvcrt.getwch(), "")
    else:                           # le terminal est déjà en mode brut (voir `raw_mode`)
        import select
        fd = sys.stdin.fileno()                  # os.read : sys.stdin.read mettrait en mémoire tampon la suite de la séquence
        ch = os.read(fd, 1).decode("utf-8", "replace")
        if ch == "\x1b":
            if select.select([fd], [], [], 0.05)[0]:
                return {"[A": "up", "[B": "down", "[D": "left", "[C": "right"}.get(os.read(fd, 2).decode("ascii", "replace"), "")
            return "esc"
    if ch == "\x03":
        raise KeyboardInterrupt
    return {"\r": "enter", "\n": "enter", " ": "space", "\x1b": "esc"}.get(ch, ch)


@contextlib.contextmanager
def raw_mode():
    """Mode brut le temps d'un menu (POSIX) : les touches ne sont ni affichées ni perdues. Sans effet sous Windows."""
    if os.name == "nt":
        yield
        return
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def select(term: Term, question: str, items: list[str], multi: bool = False, default: int = 0,
           hint: str | None = None) -> list[int]:
    """Menu à flèches (↑/↓, Entrée ; Espace pour cocher si `multi`). Renvoie les indices choisis.

    Sans terminal interactif : liste numérotée.
    """
    if not (term.tty and sys.stdin.isatty()):
        return _select_numbered(term, question, items, multi, default)
    cursor, checked, drawn = max(0, min(default, len(items) - 1)), set(), 0
    footer = hint or ("↑/↓ naviguer · Espace cocher · Entrée valider" if multi else "↑/↓ naviguer · Entrée valider")

    def draw(final: str | None = None) -> None:
        nonlocal drawn
        if final is not None:
            lines = [f"{term.cyan('?')} {term.bold(question)} {term.cyan(final)}"]
        else:
            lines = [f"{term.cyan('?')} {term.bold(question)}"]
            for i, label in enumerate(items):
                mark = ("[x] " if i in checked else "[ ] ") if multi else ""
                if i == cursor:
                    lines.append(term.cyan(f"  ❯ {mark}{label}"))
                else:
                    lines.append(f"    {mark}{label}")
            lines.append(term.dim("  " + footer))
        buf = (f"\x1b[{drawn}A" if drawn else "") + "".join(f"\r\x1b[2K{fit_ansi(ln, term.width)}\n" for ln in lines) + "\x1b[J"
        drawn = len(lines)
        term.write(buf)

    term.write("\x1b[?25l")
    try:
        with raw_mode():
            while True:
                draw()
                key = read_key()
                if key == "up":
                    cursor = (cursor - 1) % len(items)
                elif key == "down":
                    cursor = (cursor + 1) % len(items)
                elif key.isdigit() and 1 <= int(key) <= len(items):
                    cursor = int(key) - 1
                elif key == "space" and multi:
                    checked.symmetric_difference_update({cursor})
                elif key == "enter":
                    picked = sorted(checked) if multi and checked else [cursor]
                    draw(", ".join(clean(items[i]) for i in picked))
                    return picked
    finally:
        term.write("\r\x1b[?25h")


def _select_numbered(term: Term, question: str, items: list[str], multi: bool, default: int) -> list[int]:
    print(f"{term.cyan('?')} {question}")
    for i, label in enumerate(items, 1):
        print(f"   {term.bold(str(i))}) {label}")
    while True:
        raw = input(f"  Votre choix (numéro{', plusieurs séparés par des virgules' if multi else ''}) [{default + 1}] : ").strip()
        tokens = [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()] or [str(default + 1)]
        if all(t.isdigit() and 1 <= int(t) <= len(items) for t in tokens) and (multi or len(tokens) == 1):
            return sorted({int(t) - 1 for t in tokens})
        print(term.red("  Entrez un numéro de la liste."))


def choose_languages(term: Term, options: list[tuple[str, str]], allow_new: bool = False) -> list[str]:
    """Langage(s) cible(s) : menu à cocher. « Autre langage… » demande ensuite son nom."""
    labels = [name for _, name in options]
    if allow_new:
        labels.append("Autre langage… (ajouter un nouveau langage)")
    picked = select(term, "Langage cible", labels, multi=True)
    out: list[str] = []
    for i in picked:
        if i < len(options):
            out.append(options[i][0])
        else:
            name = ask(term, "Quel langage voulez-vous ajouter ? (ex. PHP, Go, Kotlin)")
            out.append(f"{NEW_LANGUAGE}:{name}")
    return out

# ------------------------------------------------------------------ fichier source

SOURCE_DIRS = ("examples", "source")      # dossiers où chercher les .puml proposés


def choose_puml(term: Term, default: str | None = None) -> str:
    """Liste les .puml du dossier `examples/` (ou `source/`) ; ou saisie du chemin d'un autre fichier."""
    from pathlib import Path
    folder = next((Path(d) for d in SOURCE_DIRS if Path(d).is_dir() and any(Path(d).glob("*.puml"))), None)
    files = sorted(folder.glob("*.puml")) if folder else []
    if not files:
        print(term.dim("Astuce : placez vos fichiers .puml dans le dossier `examples/` : ils seront proposés ici."))
        return ask(term, "Chemin du fichier PlantUML (.puml)", default)
    labels = [f.name for f in files] + ["Autre fichier… (saisir son chemin)"]
    i = select(term, f"Fichier PlantUML (dossier {folder.as_posix()}/)", labels,
               hint="↑/↓ naviguer · Entrée valider · ou « Autre fichier » pour un chemin libre")[0]
    if i < len(files):
        return str(files[i])
    return ask(term, "Chemin du fichier PlantUML (.puml)")
