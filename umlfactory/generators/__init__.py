"""Agents générateurs de code : un module par langage (java.py, python.py, php.py...).

Ce paquet est la seule source de vérité pour la liste des langages intégrés et la recherche de leur agent.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from .base import BaseGeneratorAgent

SUPPORT_MODULES = {"base", "planning", "prompts", "repair"}      # code commun, pas des langages


def built_in_ids() -> set[str]:
    """Langages intégrés : chaque module du paquet, sauf les modules de support et ceux commençant par « _ »."""
    return {m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_") and m.name not in SUPPORT_MODULES}


def agent_class(module_name: str) -> type[BaseGeneratorAgent]:
    """La seule sous-classe concrète de BaseGeneratorAgent définie dans generators/<module_name>.py."""
    module = importlib.import_module(f"{__name__}.{module_name}")
    found = [c for _, c in inspect.getmembers(module, inspect.isclass)
             if issubclass(c, BaseGeneratorAgent) and c is not BaseGeneratorAgent
             and c.__module__ == module.__name__ and not inspect.isabstract(c)]
    if len(found) != 1:
        raise ValueError(f"{module_name}.py doit définir exactement une sous-classe de BaseGeneratorAgent "
                         f"(trouvé : {len(found)})")
    return found[0]
