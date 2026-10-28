"""Affichage terminal : progression en direct façon Claude Code / Codex, menus et questions.

Découpé en trois modules : term (rendu et largeurs), progress (affichage d'une tâche), prompts (saisie).
Sans terminal interactif (redirection, CI), tout se dégrade en lignes de texte simples.
"""


from .term import (
    Term,
    char_width,
    clean,
    fit,
    fmt_seconds,
    fmt_size,
    fmt_time,
    text_width,
)

from .progress import (
    FileView,
    LangView,
    LiveView,
    SPIN,
    StatusLine,
    StepRow,
    StepView,
    fit_ansi,
)

from .prompts import (
    NEW_LANGUAGE,
    NEW_LANGUAGE,
    SOURCE_DIRS,
    ask,
    choose_languages,
    choose_puml,
    confirm,
    raw_mode,
    read_key,
    select,
)
