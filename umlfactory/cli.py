"""Client interactif : envoie un .puml au coordinateur (A2A) et affiche la progression en direct.

    python -m umlfactory.cli                         # pose les questions (fichier, langage, dossier)
    python -m umlfactory.cli model.puml --lang java --out ./sortie
    python -m umlfactory.cli model.puml --ask "en Python" --out ./sortie
    python -m umlfactory.cli --list-languages
    python -m umlfactory.cli model.puml --spawn      # démarre la pile le temps de l'appel
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import textwrap
import time
from pathlib import Path

import httpx
from a2a.client import A2ACardResolver

from . import providers, ui
from .a2a_common import AgentFailed, call_agent
from .config import ConfigError, describe, load_env_file, load_settings


class CliError(RuntimeError):
    pass


async def connect(url: str):
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as http:
            return await A2ACardResolver(http, url).get_agent_card()
    except Exception as exc:  # noqa: BLE001
        raise CliError(f"coordinateur injoignable ({url}) : {exc}\n"
                       "Lancer la pile avec `python -m umlfactory.deploy` ou ajouter --spawn.") from exc


async def list_languages(card) -> tuple[list[tuple[str, str]], dict[str, list[str]]]:
    """(menu des langages, outils manquants sur cet appareil par langage)."""
    try:
        reply = await call_agent(card, {"action": "list_languages"}, timeout=60)
    except AgentFailed as exc:
        raise CliError(str(exc)) from exc
    available = json.loads(reply.artifacts["report.json"])["available"]
    return [(l["id"], l["name"]) for l in available], {l["id"]: l.get("missing_tools", []) for l in available}


async def call_steps(card, payload: dict, term: ui.Term) -> dict:
    """Appelle une action du coordinateur et affiche ses étapes en direct ; renvoie son rapport."""
    provider = os.environ.get("UMLFACTORY_PROVIDER")      # fixé par providers.resolve() au lancement
    if provider and "provider" not in payload:
        payload = {**payload, "provider": provider}
    view = ui.StepView(term)
    view.start()
    try:
        reply = await call_agent(card, payload, on_event=view.handle)
    except AgentFailed as exc:
        await view.stop(failed=True)
        raise CliError(str(exc)) from exc
    await view.stop()
    return json.loads(reply.artifacts.get("report.json", "{}"))


async def add_language(card, term: ui.Term, name: str | None, interactive: bool, approve: bool) -> str | None:
    """Ajoute un langage cible, étape par étape. Renvoie son identifiant s'il est utilisable, sinon None.

    1. le LLM rédige une spécification (données) ; 2. les outils sont cherchés sur cet appareil (sinon un guide
    d'installation en texte est écrit : rien n'est installé ni exécuté par le LLM) ; 3. l'utilisateur valide la commande
    de vérification ; 4. l'agent est validé sur des diagrammes de référence ; 5. il apparaît dans le menu.
    """
    if not name:
        if not interactive:
            raise CliError("nom du langage manquant (--add-language NOM)")
        name = ui.ask(term, "Quel langage voulez-vous ajouter ? (ex. Go, Kotlin, TypeScript)")
    print(term.dim("Ajout du langage en 3 étapes : préparation, outils, test."))
    report = await call_steps(card, {"action": "create_language", "language_name": name}, term)
    lang = report["language"]
    lid = lang["id"]

    while report.get("missing_tools"):
        print(term.yellow(f"! Outils manquants sur votre PC : {', '.join(report['missing_tools'])}"))
        if report.get("guide_path"):
            print(f"  Guide d'installation : {report['guide_path']}")
        print(term.dim("  Rien n'est installé tout seul : suivez le guide, puis revenez."))
        if not interactive or not ui.confirm(term, "Outils installés ? Vérifier à nouveau", default=True):
            print(f"Langage « {lang['name']} » gardé en brouillon. Installez les outils, puis relancez avec "
                  f"--add-language \"{name}\".")
            return None
        report = await call_steps(card, {"action": "check_language", "language_id": lid}, term)

    print()
    print(term.bold(f"Contrôle du code {lang['name']} généré"))
    print(term.dim("  Pour contrôler le code, cette commande sera lancée sur votre PC :"))
    print("  " + term.cyan(lang["build"] or "(aucune : contrôle simple seulement)"))
    if lang.get("scaffold"):
        print(term.dim("  Fichiers de projet ajoutés : " + ", ".join(lang["scaffold"])))
    if lang.get("sensitive_calls"):
        print(term.dim("  Le code est refusé s'il contient : " + ", ".join(lang["sensitive_calls"][:5])))
    if not approve:
        if not interactive:
            raise CliError("commande de vérification non approuvée : ajouter --approve pour l'autoriser")
        if not ui.confirm(term, "Autoriser cette commande ?", default=True):
            print("Annulé. La spécification reste en brouillon (rien n'a été exécuté).")
            return None

    quick = True
    if interactive:
        print()
        print(term.bold(f"Test du nouveau langage {lang['name']}"))
        print(term.dim("  Le langage est essayé sur des diagrammes d'exemple avant d'être ajouté."))
        quick = ui.confirm(term, "Faire un test rapide (quelques minutes) ? Non = test complet, plus long",
                           default=True)
    print(term.dim("Test en cours, patientez…"))
    result = await call_steps(card, {"action": "validate_language", "language_id": lid, "approve": True,
                                     "quick": quick}, term)
    print()
    diagrams = result.get("diagrams", [])
    for d in diagrams:
        good = d["score"] >= result["threshold"]
        print(f"  {term.green('✔') if good else term.yellow('⚠')}  {d['title']}")
        for w in d.get("warnings", [])[:2]:
            print(term.dim("       ! " + w.splitlines()[0][:100]))
    passed = sum(1 for d in diagrams if d["score"] >= result["threshold"])
    if result["status"] == "validated":
        print(term.green(f"✔  {lang['name']} validé : {passed} diagramme(s) sur {len(diagrams)} conformes — disponible dans le menu."))
        if result.get("file"):
            print(term.dim(f"   Fichier créé : {Path(result['file']).relative_to(Path.cwd()) if Path(result['file']).is_relative_to(Path.cwd()) else result['file']}"))
        return lid
    print(term.yellow(f"! {lang['name']} : seulement {passed} diagramme(s) sur {len(diagrams)} conformes. Résultats moins sûrs."))
    if interactive and ui.confirm(term, "Garder ce langage malgré tout ?", default=False):
        return lid
    await call_steps(card, {"action": "discard_language", "language_id": lid}, term)
    print("Langage supprimé.")
    return None


def conformity_lines(term: ui.Term, check: dict) -> list[str]:
    """Verdict du modèle sur la conformité au diagramme : 1 à 4 lignes courtes, jamais de note chiffrée."""
    width = min(term.width - 5, 78)
    conformity = check.get("conformity") or {}
    verdict = conformity.get("verdict")
    if verdict == "conforme":
        lines = [term.green("   ✔ Conforme au diagramme")]
    elif verdict == "partiel":
        lines = [term.yellow("   ⚠ Partiellement conforme au diagramme")]
        lines += [term.yellow("     - " + textwrap.shorten(m, width, placeholder="…")) for m in conformity.get("missing", [])[:5]]
    elif verdict == "non_conforme":
        lines = [term.red("   ✘ Non conforme au diagramme")]
        if conformity.get("summary"):
            lines.append(term.dim("     " + textwrap.shorten(conformity["summary"], width, placeholder="…")))
    else:
        reason = conformity.get("reason") or "vérification indisponible"
        lines = [term.yellow(f"   ? Non vérifié : {reason}")]
    if conformity.get("not_run"):
        lines.append(term.dim("     Compilation non vérifiée : " + textwrap.shorten(conformity["not_run"], width, placeholder="…")))
    return lines


def count_files(folder: Path) -> int:
    return sum(1 for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else 0


async def run(args: argparse.Namespace, term: ui.Term) -> int:
    settings = load_settings(require_api=False)
    card = await connect(args.coordinator or settings.coordinator_url)
    options, missing = await list_languages(card)
    ids = {lid for lid, _ in options}
    names = dict(options)

    if args.list_languages:
        for lid, name in options:
            print(f"{lid:<12} {name}")
        return 0

    interactive = sys.stdin.isatty() and term.tty

    # 0. fournisseur de modèles : les clés présentes sont testées, une seule valide suffit
    try:
        chosen = await providers.resolve(term, interactive, args.provider, args.reset_model)
    except ConfigError as exc:
        raise CliError(str(exc)) from exc
    print(term.dim(f"Modèle utilisé : {chosen.label} ({chosen.model})"))

    async def refresh() -> None:
        nonlocal options, missing, ids, names
        options, missing = await list_languages(card)
        ids, names = {lid for lid, _ in options}, dict(options)

    added: list[str] = []
    if args.add_language:
        lid = await add_language(card, term, args.add_language, interactive, args.approve)
        if lid is None:
            return 1
        await refresh()
        added.append(lid)
    # 1-3. diagramme, langage(s), destination : étapes avec retour possible (Échap) tant que rien n'est lancé
    model = args.model
    languages: list[str] | None = added or None
    if args.lang:
        languages = [*added, *(l.lower() for l in args.lang)]
        unknown = [l for l in languages if l not in ids]
        if unknown:
            raise CliError(f"langage inconnu : {', '.join(unknown)}. Disponibles : {', '.join(sorted(ids))}")
    out = args.out
    ask_languages = not args.lang and not args.ask and not languages      # jamais « tous » par défaut
    if not interactive:
        if not model:
            raise CliError("fichier PlantUML manquant (premier argument)")
        if ask_languages:
            raise CliError(f"préciser --lang parmi : {', '.join(sorted(ids))}")
        if not out:
            raise CliError("dossier de destination manquant (--out)")

    async def step_file(back: str) -> None:
        nonlocal model
        while True:
            model = ui.choose_puml(term, next((c for c in ("model.puml",) if Path(c).is_file()), None), back=back)
            if Path(model).expanduser().is_file():
                return
            print(term.red(f"  Fichier introuvable : {model}. Vérifiez le chemin et réessayez."))

    async def step_languages(back: str) -> None:
        nonlocal languages
        chosen_langs = ui.choose_languages(term, options, allow_new=True, back=back)
        languages = []
        for entry in chosen_langs:
            if entry.startswith(ui.NEW_LANGUAGE):
                new_name = entry.partition(":")[2] or None
                lid = await add_language(card, term, new_name, interactive, args.approve)
                if lid is None:
                    raise CliError("ajout du langage abandonné")
                await refresh()
                entry = lid
            languages.append(entry)

    async def step_destination(back: str) -> None:
        nonlocal out
        default_out = str(Path("sortie").resolve())
        print(term.dim("  Dossier où seront créés les fichiers générés. Entrée = garder celui proposé."))
        out = ui.ask(term, "Dossier de destination", default_out, back=True)

    steps = [fn for fn, needed in ((step_file, not model), (step_languages, ask_languages), (step_destination, not out))
             if needed]
    if not await ui.run_steps(steps):
        print("Annulé.")
        return 1
    model_path = Path(model).expanduser().resolve()
    if not model_path.is_file():
        raise CliError(f"fichier introuvable : {model_path}")
    out_dir = Path(out).expanduser().resolve()

    for lid in languages or []:         # la vérification d'exécution a besoin d'outils présents sur CET appareil
        if missing.get(lid):
            print(term.yellow(f"! {names.get(lid, lid)} : outil manquant ({', '.join(missing[lid])}). "
                              "Le code sera créé mais pas testé."))

    payload: dict = {"puml_path": str(model_path), "output_dir": str(out_dir), "layout": args.layout,
                     "provider": chosen.provider}
    if languages:
        payload["languages"] = languages
    if args.ask:
        payload["request"] = args.ask
    if args.package:
        payload["package"] = args.package
    if args.instructions:
        payload["instructions"] = args.instructions

    # 4. dossiers déjà remplis : demander avant de remplacer quoi que ce soit
    from .coordinator import CoordinatorRequest, pick_destination
    probe = CoordinatorRequest(output_dir=str(out_dir), layout=args.layout)
    targets = {Path(pick_destination(probe, l, languages)) for l in languages} if languages else {out_dir}
    existing = sum(count_files(t) for t in targets)
    overwrite = args.overwrite or args.yes
    if existing and not overwrite:
        where = ", ".join(str(t) for t in sorted(targets))
        if not interactive:
            raise CliError(f"{where} contient déjà {existing} fichier(s) : utiliser --overwrite pour les remplacer")
        print(term.yellow(f"! {where} contient déjà {existing} fichier(s)."))
        if not ui.confirm(term, "Remplacer les fichiers qui ont le même nom ?"):
            print("Annulé.")
            return 1
        overwrite = True
    payload["overwrite"] = overwrite

    # 5. génération avec progression en direct
    view = ui.LiveView(term, names, languages)
    started = time.monotonic()
    view.start()
    failed = True
    try:
        reply = await call_agent(card, payload, on_event=view.handle)
        failed = False
    except AgentFailed as exc:
        await view.stop(failed=True)
        raise CliError(str(exc)) from exc
    finally:
        if failed:
            await view.stop(failed=True)
    await view.stop()

    report = json.loads(reply.artifacts.get("report.json", "{}"))
    print()
    for lid, info in report.get("languages", {}).items():
        print(f"{term.green('✔ ')} {term.bold(names.get(lid, lid))} : {len(info['files'])} fichier(s) → {info['dest']}")
        for line in conformity_lines(term, info.get("verification") or {}):
            print(line)
        warnings = info.get("warnings", [])
        for w in warnings[:3]:
            print(term.yellow("   ! " + textwrap.shorten(w, min(term.width - 5, 78), placeholder="…")))
        if len(warnings) > 3:
            print(term.dim(f"   … et {len(warnings) - 3} autre(s) remarque(s)"))
    for lid, reason in report.get("failed", {}).items():
        print(f"{term.red('✘ ')} {term.bold(names.get(lid, lid))} : {reason}", file=sys.stderr)
    print(term.dim(f"Durée totale : {ui.fmt_time(time.monotonic() - started)}"))
    return 1 if report.get("failed") else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="umlfactory", description="PlantUML -> code source via agents LLM")
    parser.add_argument("model", nargs="?", help="fichier PlantUML (.puml) ; demandé si absent")
    parser.add_argument("-o", "--out", help="dossier de destination ; demandé si absent")
    parser.add_argument("--lang", nargs="+", help="langage(s) cible(s) ; sans cette option, un menu les propose")
    parser.add_argument("--list-languages", action="store_true", help="affiche les langages disponibles")
    parser.add_argument("--ask", help="demande en langage naturel : le LLM choisit le langage")
    parser.add_argument("--package", help="package / namespace du code généré (ex. com.exemple.banque)")
    parser.add_argument("--instructions", help="consignes supplémentaires pour le LLM")
    parser.add_argument("--layout", choices=["auto", "by-language", "flat"], default="auto",
                        help="auto : un sous-dossier par langage s'il y en a plusieurs")
    parser.add_argument("--overwrite", "-y", "--yes", dest="overwrite", action="store_true",
                        help="remplace sans demander les fichiers existants du même nom")
    parser.add_argument("--add-language", metavar="NOM", help="ajoute un langage cible (ex. Go) avant de générer")
    parser.add_argument("--approve", action="store_true",
                        help="autorise sans demander la commande de vérification d'un langage ajouté")
    parser.add_argument("--coordinator", help="URL du coordinateur (défaut : COORDINATOR_URL)")
    parser.add_argument("--spawn", action="store_true", help="démarre la pile locale pour la durée de l'appel")
    parser.add_argument("--reset-model", action="store_true",
                        help="oublie le fournisseur mémorisé et le redemande")
    parser.add_argument("--provider", choices=["openai", "anthropic"],
                        help="fournisseur de modèles à utiliser (sinon : testé et choisi au lancement)")
    return parser


def main() -> int:
    load_env_file()
    args = build_parser().parse_args()
    args.yes = False
    term = ui.Term()
    try:
        settings = load_settings(require_api=False)
        stack = contextlib.nullcontext()
        status = None
        if args.spawn:
            from .deploy import running_stack
            status = ui.StatusLine(term, "Démarrage de la pile (MCP, coordinateur, agents)")
            ready: list[str] = []

            def progress(name: str, state: str, detail: str) -> None:
                if state in ("ready", "running"):
                    ready.append(name)
                if status:
                    status.set(f"Démarrage de la pile · prêts : {', '.join(ready) or 'aucun'}")

            status.__enter__()
            stack = running_stack(settings, progress=progress)
        try:
            with stack:
                if status:
                    status.__exit__(None, None, None)
                    print(term.green("✔ ") + " Pile prête")
                    status = None
                return asyncio.run(run(args, term))
        finally:
            if status:
                status.__exit__(None, None, None)
    except KeyboardInterrupt:
        print("\nInterrompu.")
        return 130
    except (CliError, ConfigError, RuntimeError) as exc:
        print(term.red(f"Erreur : {exc}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
