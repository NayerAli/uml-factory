"""`python -m umlfactory.generators <langage> [--port N]` : lance l'agent du module generators/<langage>.py.

Ajouter un langage = déposer un fichier dans ce dossier avec une sous-classe de BaseGeneratorAgent
(ou de CommandGenerator : quelques attributs suffisent, voir _declarative.py).
Aucun point d'entrée à écrire : ce lanceur trouve la classe tout seul.
"""

import argparse
import importlib.util

from ..a2a_common import serve_agent
from ..config import DEFAULT_PORT_RANGE, load_env_file
from . import agent_class
from .base import BaseGeneratorAgent


def build_agent(name: str) -> BaseGeneratorAgent:
    """Agent du langage `name` : le fichier generators/<name>.py (écrit à la main ou créé par la CLI)."""
    if importlib.util.find_spec(f"{__package__}.{name}") is None:
        raise SystemExit(f"langage « {name} » inconnu : il n'y a pas de fichier umlfactory/generators/{name}.py")
    return agent_class(name)()


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
