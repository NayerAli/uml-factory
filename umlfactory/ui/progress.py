"""Progression à l'écran : génération (LiveView), étapes d'une tâche longue (StepView), ligne d'attente."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field

from .term import Term, char_width, clean, fit, fmt_seconds, fmt_size, fmt_time, text_width

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


# ------------------------------------------------------------------ ligne d'état (démarrage)

class StatusLine:
    """Une ligne animée (spinner + durée) pour les attentes sans détail, ex. le démarrage de la pile."""

    def __init__(self, term: Term, text: str) -> None:
        self.term, self.text, self._stop = term, text, threading.Event()
        self._start = time.monotonic()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def set(self, text: str) -> None:
        self.text = text

    def __enter__(self) -> "StatusLine":
        if self.term.tty:
            self._thread.start()
        else:
            self.term.write(self.text + "\n")
        return self

    def _loop(self) -> None:
        i = 0
        while not self._stop.wait(0.1):
            line = fit(f"{SPIN[i % len(SPIN)]} {self.text} · {fmt_time(time.monotonic() - self._start)}", self.term.width)
            self.term.write("\r\x1b[2K" + self.term.cyan(line[0]) + line[1:])
            i += 1

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()
        if self.term.tty:
            self.term.write("\r\x1b[2K")


# ------------------------------------------------------------------ progression de la génération

@dataclass
class FileView:
    state: str = "wait"          # wait | start | thinking | writing | fix | done | error
    chars: int = 0
    thought: int = 0
    preview: str = ""
    detail: str = ""
    began: float | None = None
    ended: float | None = None
    fixing: bool = False


@dataclass
class LangView:
    id: str
    name: str
    phase: str = "en attente"
    began: float = field(default_factory=time.monotonic)
    ended: float | None = None
    files: dict[str, FileView] = field(default_factory=dict)
    dest: str = ""
    count: int = 0
    error: str = ""
    score: int | None = None            # fiabilité du code (vérification d'exécution), sur 100
    verified_in: float | None = None
    verify_note: str = ""               # pourquoi le code n'a pas pu être exécuté


class LiveView:
    """Reçoit les événements des agents et dessine la progression (rafraîchie 10 fois par seconde)."""

    def __init__(self, term: Term, names: dict[str, str], selected: list[str] | None = None) -> None:
        self.term, self.names = term, names
        self.langs = {lid: LangView(lid, names.get(lid, lid)) for lid in (selected or [])}
        self.phase = "démarrage"
        self.began = time.monotonic()
        self._task: asyncio.Task | None = None
        self._frame = 0
        self._drawn = 0
        self._printed: set[tuple] = set()      # mode sans terminal : évite les répétitions

    # -------------------------------------------------------------- événements

    def handle(self, event: dict) -> None:
        kind, lang = event.get("event"), self._lang(event.get("lang"))
        if kind == "phase":
            if lang:
                lang.phase = str(event.get("text", ""))
                self._log(("phase", lang.id, lang.phase), f"{lang.name} : {lang.phase}")
            else:
                self.phase = str(event.get("text", ""))
        elif kind == "plan" and lang:
            for path in event.get("files", []):
                lang.files.setdefault(str(path), FileView())
        elif kind == "file" and lang:
            self._file(lang, event)
        elif kind == "verify" and lang:
            if event.get("state") == "slow":              # l'agent ne signale que les étapes de plus d'une seconde
                lang.phase = f"vérification · {event.get('step', '')}"
                self._log(("verify", lang.id, lang.phase), f"{lang.name} : {lang.phase} (plus d'une seconde)")
            else:
                lang.score, lang.verified_in = event.get("score"), event.get("seconds")
                lang.verify_note = str(event.get("skipped") or "")
                if lang.phase.startswith("vérification ·"):
                    lang.phase = "vérification terminée"
                self._log(("verified", lang.id, lang.score, lang.verify_note), f"{lang.name} : " + self._badge_plain(lang))
        elif kind == "written" and lang:
            lang.dest, lang.count, lang.ended = str(event.get("dest", "")), int(event.get("count", 0)), time.monotonic()
            lang.phase = "terminé"
            self._log(("written", lang.id), f"{lang.name} : {lang.count} fichier(s) écrits dans {lang.dest}")

    @staticmethod
    def _badge_plain(lang: LangView) -> str:
        if lang.score is None:
            return f"code non exécuté ({lang.verify_note})" if lang.verify_note else ""
        return f"fiabilité {int(lang.score)}/100" + (f" · vérifiée en {fmt_seconds(float(lang.verified_in))}" if lang.verified_in is not None else "")

    def _badge(self, lang: LangView) -> str:
        t = self.term
        text = self._badge_plain(lang)
        if not text:
            return ""
        if lang.score is None:
            return " · " + t.yellow(text)
        color = t.green if lang.score >= 80 else (t.yellow if lang.score >= 50 else t.red)
        return " · " + color(text)

    def _lang(self, lid: str | None) -> LangView | None:
        if not lid:
            return None
        if lid not in self.langs:               # langage choisi par le coordinateur (demande libre)
            self.langs[lid] = LangView(lid, self.names.get(lid, lid))
        return self.langs[lid]

    def _file(self, lang: LangView, e: dict) -> None:
        path = str(e.get("path", ""))
        f = lang.files.setdefault(path, FileView())
        state = str(e.get("state", ""))
        now = time.monotonic()
        if f.began is None and state in ("start", "thinking", "writing", "fix"):
            f.began = now
        if state == "fix":
            f.fixing, f.ended = True, None
        f.state = "fix" if state == "fix" else state
        if state in ("thinking", "writing"):
            f.fixing = bool(e.get("fix", f.fixing))
        f.chars = int(e.get("chars", f.chars) or 0)
        f.thought = int(e.get("thought", f.thought) or 0)
        f.preview = str(e.get("preview", f.preview) or "")
        if state == "done":
            f.ended = now
            self._log(("done", lang.id, path, f.fixing), f"  ✔  {path} ({fmt_size(f.chars)})")
        elif state == "error":
            f.detail = clean(str(e.get("detail", "")))
            self._log(("error", lang.id, path, f.detail), f"  ✘  {path} : {f.detail}")

    def _log(self, key: tuple, text: str) -> None:
        if not self.term.tty and key not in self._printed:
            self._printed.add(key)
            self.term.write(text + "\n")

    # -------------------------------------------------------------- dessin

    def _file_line(self, name: str, f: FileView, spin: str) -> str:
        t = self.term
        elapsed = fmt_time((f.ended or time.monotonic()) - f.began) if f.began else ""
        if f.state == "done":
            return f"  {t.green('✔ ')} {name} {t.dim(f'{fmt_size(f.chars)} · {elapsed}')}"
        if f.state == "error":
            return f"  {t.red('✘ ')} {name} {t.red(f.detail)}"
        if f.state == "wait":
            return f"  {t.dim('· ')} {t.dim(name)}"
        verb = {"start": "en attente du modèle", "thinking": "réflexion", "writing": "écriture",
                "fix": "correction"}.get(f.state, f.state)
        if f.fixing and f.state in ("thinking", "writing"):
            verb = "correction · " + verb
        if f.state == "thinking":
            extra = f"réflexion · {fmt_size(f.thought)}" if f.thought else ""
        else:
            extra = fmt_size(f.chars) if f.chars else ""
        head = f"  {t.cyan(spin + ' ')} {name} {t.dim(' · '.join(x for x in (verb, extra, elapsed) if x))}"
        preview = clean(f.preview)
        if preview and f.state == "writing":
            room = t.width - text_width(f"  x {name} {verb} {extra} {elapsed}") - 6
            if room > 12:
                head += "  " + t.dim("↳ " + fit(preview, room))
        return head

    def lines(self) -> list[str]:
        t, now = self.term, time.monotonic()
        spin = SPIN[self._frame % len(SPIN)]
        out: list[str] = []
        total = fmt_time(now - self.began)
        out.append(f"{t.cyan(spin + ' ')} {t.bold(self.phase)} {t.dim('· ' + total)}")
        budget = t.height - 4
        for lang in self.langs.values():
            if lang.error:
                icon, tail = t.red("✘ "), t.red(lang.error)
            elif lang.ended:
                icon, tail = t.green("✔ "), t.dim(f"{lang.phase} · {fmt_time(lang.ended - lang.began)}") + self._badge(lang)
            else:
                icon, tail = t.cyan(spin + " "), t.dim(f"{lang.phase} · {fmt_time(now - lang.began)}") + self._badge(lang)
            out.append(f"{icon} {t.bold(lang.name)} {tail}")
            shown = list(lang.files.items())
            room = max(3, budget // max(1, len(self.langs)))
            if len(shown) > room:           # trop de fichiers pour l'écran : on replie ceux qui sont terminés
                finished = [(n, f) for n, f in shown if f.state == "done"]
                active = [(n, f) for n, f in shown if f.state != "done"]
                shown = active[:room - 1]
                if finished:
                    out.append(f"  {t.green('✔ ')} {t.dim(f'{len(finished)} fichier(s) terminé(s)')}")
            for name, f in shown:
                out.append(self._file_line(name, f, spin))
        return [fit_ansi(line, t.width) for line in out]

    def _draw(self, final: bool = False) -> None:
        if not self.term.tty:
            return
        lines = self.lines()
        if final:
            lines[0] = f"{self.term.green('✔ ')} {self.term.bold('Terminé')} {self.term.dim('· ' + fmt_time(time.monotonic() - self.began))}"
        buf = (f"\x1b[{self._drawn}A" if self._drawn else "") + "".join(f"\r\x1b[2K{ln}\n" for ln in lines) + "\x1b[J"
        self._drawn = len(lines)
        self.term.write(buf)

    async def _loop(self) -> None:
        while True:
            self._frame += 1
            self._draw()
            await asyncio.sleep(0.1)

    def start(self) -> None:
        if self.term.tty:
            self.term.write("\x1b[?25l")            # curseur masqué pendant l'animation
            self._task = asyncio.create_task(self._loop())

    async def stop(self, failed: bool = False) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._draw(final=not failed)
            self.term.write("\x1b[?25h")


def fit_ansi(line: str, width: int) -> str:
    """Tronque une ligne contenant des séquences ANSI sans couper une séquence, en largeur d'affichage."""
    plain, out, i = 0, [], 0
    while i < len(line):
        if line[i] == "\x1b":
            j = line.find("m", i)
            j = len(line) - 1 if j == -1 else j
            out.append(line[i:j + 1])
            i = j + 1
            continue
        cw = char_width(line[i])
        if plain + cw > width - 1:
            out.append("…\x1b[0m")
            break
        out.append(line[i])
        plain += cw
        i += 1
    return "".join(out)


# ------------------------------------------------------------------ étapes d'une tâche longue

@dataclass
class StepRow:
    text: str
    state: str = "start"         # start | done | warn | fail
    detail: str = ""
    began: float = field(default_factory=time.monotonic)
    ended: float | None = None


class StepView:
    """Étapes d'une tâche longue (création ou validation d'un langage) : une ligne par étape, durée dès 1 s.

    Reçoit les événements {"event": "step", "id", "text", "state", "detail"} publiés par les skills du coordinateur.
    """

    def __init__(self, term: Term) -> None:
        self.term = term
        self.rows: dict[str, StepRow] = {}
        self._task: asyncio.Task | None = None
        self._frame = 0
        self._drawn = 0

    def handle(self, event: dict) -> None:
        if event.get("event") != "step":
            return
        sid, state = str(event.get("id", "")), str(event.get("state", "start"))
        row = self.rows.setdefault(sid, StepRow(str(event.get("text", sid))))
        row.text, row.state, row.detail = str(event.get("text", row.text)), state, str(event.get("detail", "") or "")
        row.ended = None if state == "start" else time.monotonic()
        if state != "start" and not self.term.tty:
            self.term.write(f"{self._icon(row, '·')} {row.text}" + (f" — {row.detail}" if row.detail else "") + "\n")

    def _icon(self, row: StepRow, spin: str) -> str:
        t = self.term
        return {"done": t.green("✔ "), "warn": t.yellow("! "), "fail": t.red("✘ ")}.get(row.state, t.cyan(spin + " "))

    def lines(self) -> list[str]:
        spin = SPIN[self._frame % len(SPIN)]
        now, out = time.monotonic(), []
        for row in self.rows.values():
            elapsed = (row.ended or now) - row.began
            timing = f" · {fmt_time(elapsed)}" if elapsed >= 1 else ""
            detail = f" — {row.detail}" if row.detail else ""
            out.append(fit_ansi(f"{self._icon(row, spin)} {row.text}" + self.term.dim(detail + timing), self.term.width))
        return out

    def _draw(self) -> None:
        if not self.term.tty:
            return
        lines = self.lines()
        buf = (f"\x1b[{self._drawn}A" if self._drawn else "") + "".join(f"\r\x1b[2K{ln}\n" for ln in lines) + "\x1b[J"
        self._drawn = len(lines)
        self.term.write(buf)

    async def _loop(self) -> None:
        while True:
            self._frame += 1
            self._draw()
            await asyncio.sleep(0.1)

    def start(self) -> None:
        if self.term.tty:
            self.term.write("\x1b[?25l")
            self._task = asyncio.create_task(self._loop())

    async def stop(self, failed: bool = False) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._draw()
            self.term.write("\x1b[?25h")
