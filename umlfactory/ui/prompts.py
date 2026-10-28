"""Questions et menus au clavier : saisie, oui/non, menu à flèches (cases à cocher), choix de fichiers."""

from __future__ import annotations

import contextlib
import os
import sys

from .progress import fit_ansi
from .term import Term, clean

BACK_LABEL = "← Retour (revenir à l'étape précédente)"
QUIT_LABEL = "✕ Quitter"
BACK_WORDS = ("<", "retour")        # à taper dans une question libre pour revenir en arrière


class GoBack(Exception):
    """L'utilisateur veut revenir à l'étape précédente (Échap, « ← Retour » ou « < »)."""


BACK_KEYS = ("esc", "left")
BACK_WARNING = "Appuyez encore une fois sur ← (ou Échap) pour revenir à l'étape précédente."


class BackGuard:
    """Évite les retours par accident : il faut deux appuis de suite ; toute autre touche remet à zéro."""

    def __init__(self) -> None:
        self.armed = False

    def press(self, key: str) -> bool:
        """True quand le retour est confirmé (deuxième appui consécutif)."""
        if key not in BACK_KEYS:
            self.armed = False
            return False
        if self.armed:
            self.armed = False
            return True
        self.armed = True
        return False


NEW_LANGUAGE = "+new"      # préfixe renvoyé quand l'utilisateur choisit « Autre langage… » (suivi de « :nom »)


# ------------------------------------------------------------------ questions

def ask(term: Term, question: str, default: str | None = None, back: bool = False) -> str:
    """Question libre. Avec `back`, taper « < » (ou « retour ») revient à l'étape précédente."""
    suffix = f" [{default}]" if default else ""
    if back:
        print(term.dim("  (Tapez < puis Entrée pour revenir en arrière)"))
    while True:
        answer = input(f"{term.cyan('?')} {question}{suffix} : ").strip().strip('"').strip("'")
        if back and answer.lower() in BACK_WORDS:
            raise GoBack
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
           hint: str | None = None, back: str | None = None) -> list[int]:
    """Menu à flèches. Renvoie les indices choisis.

    `back` : libellé de la dernière ligne (« ← Retour » ou « ✕ Quitter »). La choisir, ou appuyer sur Échap,
    lève `GoBack`. Avec `multi`, on coche avec Espace ; valider sans rien cocher est refusé avec un message.
    Sans terminal interactif : liste numérotée (0 = retour).
    """
    if not (term.tty and sys.stdin.isatty()):
        return _select_numbered(term, question, items, multi, default, back)
    rows = items + ([back] if back else [])
    cursor, checked, drawn, notice = max(0, min(default, len(items) - 1)), set(), 0, ""
    guard = BackGuard()
    keys = ["↑ ↓ pour vous déplacer"]
    if multi:
        keys.append("Espace pour cocher ou décocher")
    keys.append("Entrée pour valider")
    if back:
        keys.append("Échap ou ← deux fois pour revenir")
    footer = hint or " · ".join(keys)

    def draw(final: str | None = None) -> None:
        nonlocal drawn
        if final is not None:
            lines = [f"{term.cyan('?')} {term.bold(question)} {term.cyan(final)}"]
        else:
            lines = [f"{term.cyan('?')} {term.bold(question)}"]
            for i, label in enumerate(rows):
                is_back = back is not None and i == len(items)
                mark = ("[x] " if i in checked else "[ ] ") if multi and not is_back else ""
                if i == cursor:
                    lines.append(term.cyan(f"  ❯ {mark}{label}"))
                else:
                    lines.append(f"    {mark}{label}")
            lines.append(term.dim("  " + footer))
            if notice:
                lines.append(term.yellow("  " + notice))
        buf = (f"\x1b[{drawn}A" if drawn else "") + "".join(f"\r\x1b[2K{fit_ansi(ln, term.width)}\n" for ln in lines) + "\x1b[J"
        drawn = len(lines)
        term.write(buf)

    term.write("\x1b[?25l")
    try:
        with raw_mode():
            while True:
                draw()
                key = read_key()
                notice = ""
                if back and key in BACK_KEYS and guard.press(key):
                    draw("(retour)")
                    raise GoBack
                if key not in BACK_KEYS and not (key == "enter" and back and cursor == len(items)):
                    guard.armed = False
                if key in BACK_KEYS and back:
                    notice = BACK_WARNING
                    continue
                if key == "up":
                    cursor = (cursor - 1) % len(rows)
                elif key == "down":
                    cursor = (cursor + 1) % len(rows)
                elif key == "space" and multi and cursor < len(items):
                    checked.symmetric_difference_update({cursor})
                elif key == "enter":
                    if back and cursor == len(items):
                        if guard.press("esc"):
                            draw("(retour)")
                            raise GoBack
                        notice = "Appuyez encore une fois sur Entrée pour revenir à l'étape précédente."
                        continue
                    if multi:
                        if not checked:
                            notice = "Rien n'est coché : appuyez sur Espace devant au moins un choix, puis sur Entrée."
                            continue
                        picked = sorted(checked)
                    else:
                        picked = [cursor]
                    draw(", ".join(clean(items[i]) for i in picked))
                    return picked
    finally:
        term.write("\r\x1b[?25h")


def _select_numbered(term: Term, question: str, items: list[str], multi: bool, default: int,
                     back: str | None = None) -> list[int]:
    print(f"{term.cyan('?')} {question}")
    for i, label in enumerate(items, 1):
        print(f"   {term.bold(str(i))}) {label}")
    if back:
        print(f"   {term.bold('0')}) {back}")
    while True:
        raw = input(f"  Votre choix (numéro{', plusieurs séparés par des virgules' if multi else ''}"
                    f"{', 0 pour revenir' if back else ''}) [{default + 1}] : ").strip()
        tokens = [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()] or [str(default + 1)]
        if back and tokens == ["0"]:
            raise GoBack
        if all(t.isdigit() and 1 <= int(t) <= len(items) for t in tokens) and (multi or len(tokens) == 1):
            return sorted({int(t) - 1 for t in tokens})
        print(term.red("  Entrez un numéro de la liste."))


def choose_languages(term: Term, options: list[tuple[str, str]], allow_new: bool = False,
                     back: str | None = None) -> list[str]:
    """Langage(s) cible(s) : menu à cocher. « Autre langage… » demande ensuite son nom."""
    labels = [name for _, name in options]
    if allow_new:
        labels.append("Autre langage… (ajouter un nouveau langage)")
    print(term.dim("  Vous pouvez en choisir plusieurs : le code sera généré dans chacun."))
    picked = select(term, "Dans quel(s) langage(s) voulez-vous le code ?", labels, multi=True, back=back)
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


def choose_puml(term: Term, default: str | None = None, back: str | None = None) -> str:
    """Liste les .puml du dossier `examples/` (ou `source/`) ; ou saisie du chemin d'un autre fichier."""
    from pathlib import Path
    folder = next((Path(d) for d in SOURCE_DIRS if Path(d).is_dir() and any(Path(d).glob("*.puml"))), None)
    files = sorted(folder.glob("*.puml")) if folder else []
    if not files:
        print(term.dim("Astuce : placez vos fichiers .puml dans le dossier `examples/` : ils seront proposés ici."))
        return ask(term, "Chemin du fichier PlantUML (.puml)", default, back=back is not None)
    labels = [f.name for f in files] + ["Autre fichier… (saisir son chemin)"]
    while True:
        i = select(term, f"Quel diagramme PlantUML voulez-vous convertir ? (dossier {folder.as_posix()}/)",
                   labels, back=back)[0]
        if i < len(files):
            return str(files[i])
        try:
            return ask(term, "Chemin du fichier PlantUML (.puml)", back=True)
        except GoBack:
            continue          # retour à la liste des fichiers


# ------------------------------------------------------------------ enchaînement des étapes

async def run_steps(steps: list) -> bool:
    """Exécute les étapes dans l'ordre ; `GoBack` revient à la précédente (la première propose « Quitter »).

    Chaque étape est une fonction asynchrone qui reçoit le libellé de la ligne de retour à afficher dans son menu.
    Renvoie False si l'utilisateur quitte depuis la première étape.
    """
    i = 0
    while i < len(steps):
        try:
            await steps[i](QUIT_LABEL if i == 0 else BACK_LABEL)
        except GoBack:
            if i == 0:
                return False
            i -= 1
            continue
        i += 1
    return True
