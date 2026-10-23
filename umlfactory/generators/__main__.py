"""`python -m umlfactory.generators <langage> [--port N]` : lance l'agent du module generators/<langage>.py.

Ajouter un langage = déposer un fichier dans ce dossier avec une sous-classe de BaseGeneratorAgent.
Aucun point d'entrée à écrire : ce lanceur trouve la classe tout seul.
"""

import argparse
import importlib
import importlib.util
import inspect

from ..a2a_common import serve_agent
from ..config import DEFAULT_PORT_RANGE, load_env_file
from ..languages import load_spec
from .base import BaseGeneratorAgent


def agent_class(module_name: str) -> type[BaseGeneratorAgent]:
    module = importlib.import_module(f"{__package__}.{module_name}")
    found = [c for _, c in inspect.getmembers(module, inspect.isclass)
             if issubclass(c, BaseGeneratorAgent) and c is not BaseGeneratorAgent
             and c.__module__ == module.__name__ and not inspect.isabstract(c)]
    if len(found) != 1:
        raise SystemExit(f"{module_name}.py doit définir exactement une sous-classe de BaseGeneratorAgent "
                         f"(trouvé : {len(found)})")
    return found[0]


def build_agent(name: str) -> BaseGeneratorAgent:
    """Langage intégré (fichier generators/<nom>.py) ou langage ajouté depuis le menu (langspecs/<nom>.json)."""
    if importlib.util.find_spec(f"{__package__}.{name}") is not None:
        return agent_class(name)()
    spec = load_spec(name)
    if spec is None or not spec.approved:
        raise SystemExit(f"langage « {name} » inconnu : ni generators/{name}.py, ni spécification approuvée "
                         f"(umlfactory/langspecs/{name}.json)")
    from ._declarative import DeclarativeGenerator
    return DeclarativeGenerator(spec)


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="Lance l'agent générateur d'un langage")
    parser.add_argument("language", help="nom du module dans umlfactory/generators (ex. java)")
    parser.add_argument("--host", default="127.0.0.1", help="127.0.0.1 par défaut : accès local uniquement")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT_RANGE[0])
    args = parser.parse_args()
    agent = build_agent(args.language)
    serve_agent(agent, f"générateur {agent.display_name}", args.host, args.port)


main()
