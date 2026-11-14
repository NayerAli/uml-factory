# CLI et affichage

Ce document couvre la ligne de commande (`umlfactory/cli.py`), les commandes de la pile (`deploy.py`), et le package d'affichage `umlfactory/ui/`.

## Commande principale

```
python -m umlfactory.cli [fichier.puml] [options]
```

Le point d'entrée est `cli.main()`, appelé par `sys.exit(main())`. Tout ce qui n'est pas donné en option est demandé à l'utilisateur, sauf en mode non interactif (voir plus bas).

### Options (telles que définies dans `cli.build_parser()`)

| Option | Effet dans le code |
|---|---|
| `fichier.puml` (positionnel, facultatif) | diagramme à convertir ; demandé si absent |
| `-o`, `--out DOSSIER` | dossier de destination ; demandé si absent (proposé : `sortie/` dans le dossier courant) |
| `--lang LANG [LANG ...]` | langages cibles, en minuscules ; contrôlés contre les langages disponibles |
| `--list-languages` | affiche `identifiant nom` pour chaque langage, puis quitte (code 0) |
| `--ask "..."` | demande libre : le modèle choisit le langage (`Coordinator._choose_languages`) |
| `--package NOM` | package ou namespace transmis aux agents |
| `--instructions "..."` | consigne libre ajoutée à la demande du modèle |
| `--layout {auto,by-language,flat}` | répartition des fichiers dans le dossier (voir [02-flux-de-donnees.md](02-flux-de-donnees.md#destination-selon-le-layout)) |
| `--overwrite`, `-y`, `--yes` | remplace les fichiers existants sans demander (même `dest`) |
| `--add-language NOM` | ajoute un langage (ex. `Go`) avant la génération |
| `--approve` | autorise la commande de vérification d'un langage ajouté sans question |
| `--coordinator URL` | adresse du coordinateur (défaut : `COORDINATOR_URL`) |
| `--keep-running` | laisse la pile allumée après la tâche |
| `--stop` | arrête la pile laissée allumée, puis quitte |
| `--reset-model` | oublie le fournisseur mémorisé dans `.umlfactory.json` |
| `--provider {openai,anthropic}` | impose le fournisseur, sans test ni question |
| `-h`, `--help` | aide |

`--stop` et `--keep-running` ensemble sont refusés : « ne vont pas ensemble » (`cli.main`).

### Exemples de lignes de commande (issus du README)

```
python -m umlfactory.cli
python -m umlfactory.cli model.puml --lang java -o C:\projets\banque
python -m umlfactory.cli model.puml --lang java python -o sortie
python -m umlfactory.cli model.puml --lang java --package com.exemple.banque -o sortie
python -m umlfactory.cli model.puml --lang java --instructions "utilise des records quand c'est possible" -o sortie
python -m umlfactory.cli --list-languages
```

## Mode interactif et mode non interactif

Le mode est décidé dans `cli.run()` :

```python
interactive = sys.stdin.isatty() and term.tty
```

- **Interactif** (terminal) : les questions sont posées avec des menus à flèches (`ui.select`) et des saisies (`ui.ask`).
- **Non interactif** (redirection, CI) : aucune question. Il faut donner le fichier, `--lang` (ou `--ask`) et `--out`. Sinon la CLI s'arrête avec un message :
  - « fichier PlantUML manquant (premier argument) » ;
  - « préciser --lang parmi : ... » ;
  - « dossier de destination manquant (--out) » ;
  - « ... contient déjà N fichier(s) : utiliser --overwrite pour les remplacer ».
- `ui.select` sait afficher une liste numérotée quand le terminal n'est pas interactif (`prompts._select_numbered`), comme le décrit le README. Dans le code de `cli.run`, toutefois, les questions ne sont posées que si la session est interactive : sans terminal, une option manquante fait échouer la commande.

### Les trois questions

Les étapes sont enchaînées par `ui.run_steps` :

1. **Fichier** (`step_file` → `ui.choose_puml`) : liste les `.puml` du dossier `examples/` (ou `source/`), avec l'entrée « Autre fichier… » qui demande un chemin. Sans fichier dans ces dossiers, la CLI demande directement le chemin.
2. **Langages** (`step_languages` → `ui.choose_languages`) : menu à cocher (Espace), avec « Autre langage… » qui demande un nom et lance l'ajout d'un langage.
3. **Dossier** (`step_destination` → `ui.ask`) : proposé `sortie/` (chemin absolu), Entrée accepte la valeur proposée.

Les questions sont ignorées pour toute information déjà donnée sur la ligne de commande.

### Touches

| Touche | Effet |
|---|---|
| `↑` `↓` | déplacer le curseur |
| `Espace` | cocher ou décocher (menus à choix multiples) |
| `Entrée` | valider |
| `←` ou `Échap`, deux fois de suite | revenir à l'étape précédente (un seul appui affiche un rappel) |
| ligne « ← Retour » + `Entrée`, deux fois | même effet ; à la première étape, la ligne devient « ✕ Quitter » |
| `<` puis `Entrée` (question libre) | revenir en arrière (`BACK_WORDS` : `<` et `retour`) |
| `Ctrl+C` | interruption (`read_key` lève `KeyboardInterrupt`, code 130) |

Le double appui est géré par `prompts.BackGuard` : toute autre touche remet le compteur à zéro. Un menu à choix multiples refuse de valider sans rien cocher (« Rien n'est coché : appuyez sur Espace... »).

### Terminal Windows et POSIX

- Sous Windows, `read_key()` utilise `msvcrt.getwch()` ; les flèches sont reconnues à partir des codes `H`, `P`, `K`, `M`.
- Sous POSIX, `raw_mode()` passe le terminal en mode brut le temps du menu (`termios`, `tty.setraw`), puis le restaure.
- `Term._enable_windows_ansi()` active les séquences ANSI dans la console Windows (`ENABLE_VIRTUAL_TERMINAL_PROCESSING`).

## Démarrage de la pile

Avant la question sur le fichier, `main()` vérifie si la pile est nécessaire :

- `cli.stack_needed(url)` renvoie faux si le coordinateur n'est pas local (`127.0.0.1`, `localhost`, `::1`), ou s'il répond déjà ;
- sinon `deploy.running_stack(...)` démarre les composants manquants et affiche une ligne d'état animée (`ui.StatusLine`) :

```
⠋ Démarrage de la pile · prêts : mcp, coordinator
```

Quand tout est prêt, la CLI affiche `✔  Pile prête`. Si la pile est déjà allumée, rien n'est affiché sauf avec `--keep-running` (« La pile est déjà allumée : rien à démarrer. »).

## Choix du fournisseur

`providers.resolve()` teste les clés présentes (une requête de liste de modèles chacune) et affiche la ligne :

```
Modèle utilisé : Anthropic (Claude) (claude-haiku-5-5)
```

Si deux clés sont valides, la CLI demande laquelle utiliser (une seule fois : le choix est mémorisé). `--reset-model` le redemande ; `--provider` l'impose. Le détail est dans [05-llm-et-agents.md](05-llm-et-agents.md#fournisseurs-providerspy-et-configpy).

## Affichage pendant la génération

`ui.LiveView` reçoit les événements (voir [02-flux-de-donnees.md](02-flux-de-donnees.md#8-événements-de-progression)) et redessine le bloc toutes les 0,1 s (tâche `asyncio` lancée par `LiveView.start()`).

Le bloc a cette structure (`LiveView.lines()`) :

1. une ligne d'en-tête : spinner, phase générale (par exemple « lecture du diagramme (MCP) »), durée totale ;
2. une ligne par langage : icône (spinner, `✔` ou `✘`), nom du langage, phase, durée, et une mention « code contrôlé en Xs » ou « code non exécuté (raison) » ;
3. une ligne par fichier, avec un état :

| Affichage | Signification (état `FileView.state`) |
|---|---|
| `· nom` | en attente (`wait`) |
| spinner, « en attente du modèle » | démarré, le modèle n'a pas encore répondu (`start`) |
| spinner, « réflexion · N caractères » | le modèle raisonne (`thinking`) |
| spinner, « écriture · N caractères » + aperçu de la ligne en cours | le modèle écrit le code (`writing`) |
| spinner, « correction · ... » | correction après contrôle (`fix`, indicateur `fixing`) |
| `✔ nom taille · durée` | terminé (`done`) |
| `✘ nom message` | erreur signalée (`error`) |

Si le bloc dépasse la hauteur du terminal, les fichiers terminés sont repliés en une ligne « N fichier(s) terminé(s) » (`budget = t.height - 4`).

À la fin, `LiveView.stop()` redessine l'en-tête en « ✔ Terminé · durée » (sauf en cas d'échec).

### Sortie sans terminal

Quand la sortie n'est pas un terminal (`term.tty` est faux), rien n'est redessiné. `LiveView._log()` imprime une seule fois chaque événement important (phase, fichier terminé, erreur, vérification, écriture), grâce à un ensemble de clés `_printed`.

### Résultat final

Après `cli.run()`, pour chaque langage réussi, la CLI écrit :

```
✔  Java : N fichier(s) → <dossier>
   ✔ Conforme au diagramme
```

ou une des autres formes produites par `conformity_lines()` (« ⚠ Partiellement conforme », avec la liste des éléments manquants, « ✘ Non conforme », « ? Non vérifié : raison »). Le verdict ne contient jamais de note chiffrée. Puis les avertissements (trois au maximum), et la ligne « Durée totale : ».

Les échecs de langage sont écrits sur la sortie d'erreur : `✘ <langage> : <raison>`.

## Codes de sortie

| Code | Cas (fonction qui le renvoie) |
|---|---|
| `0` | tout s'est bien passé (`cli.run`, `cli.stop_command`, `cli.main`) |
| `1` | erreur (`CliError`, `ConfigError`, `RuntimeError`), échec d'un langage, ajout de langage abandonné, aucune pile à arrêter (`--stop`) |
| `2` | option incorrecte (`FriendlyParser.error` lève `SystemExit(2)`) |
| `130` | interruption par `Ctrl+C` (`KeyboardInterrupt`) |

Les messages d'erreur sont courts :

- `Erreur : ...` (sortie d'erreur) pour les erreurs attendues ;
- `Option incorrecte : option inconnue : --bidule` suivi de « Pour voir les options : python -m umlfactory.cli --help » pour les options ;
- `Erreur inattendue : Type: message` suivi de « Le détail technique est dans logs/erreur.log » (`cli.log_crash` écrit la trace complète dans `logs/erreur.log`).

## Ajouter un langage depuis la CLI

`cli.add_language()` suit les étapes annoncées à l'écran :

1. « Ajout du langage en 3 étapes : préparation, outils, test. »
2. Le modèle rédige la spécification (`call_steps` affiche les étapes `step` du coordinateur, avec `ui.StepView`).
3. Si des outils manquent, la CLI indique le guide d'installation et demande de vérifier à nouveau (`ui.confirm`).
4. La commande de vérification est affichée. Elle doit être approuvée (`ui.confirm`) ou passée avec `--approve`.
5. Pour la validation, la CLI demande un test rapide (défaut) ou complet.
6. Les résultats par diagramme de référence sont affichés (✔ ou ⚠), puis le verdict « validé » ou « seulement N diagramme(s) sur M conformes ».
7. Si le langage n'est pas validé, la CLI demande s'il faut le garder ; sinon il est supprimé.

Le détail des règles est dans [04-generation-par-langage.md](04-generation-par-langage.md) et [05-llm-et-agents.md](05-llm-et-agents.md#ajouter-un-langage-flux-complet).

## Commandes de la pile

### `python -m umlfactory.deploy` (premier plan)

`deploy.main()` charge la configuration, affiche le fichier `.env` utilisé (ou « introuvable »), le modèle, les langages détectés, puis lance `running_stack`. Chaque composant est signalé (`✔ prêt`, `✔ (déjà actif)`, `✘ échec`). La pile reste allumée jusqu'à `Ctrl+C` (`time.sleep(3600)` en boucle). Les processus sont alors arrêtés.

### `--keep-running` et `--stop` (arrière-plan)

- Avec `--keep-running`, `running_stack(..., keep=True)` détache les processus (`DETACHED_PROCESS` sous Windows, `start_new_session` sinon), écrit leur identifiant, leur nom et leur adresse dans `.umlfactory-stack.json` (`deploy.write_state`), et ne les arrête pas à la fin.
- `--stop` appelle `cli.stop_command()`, qui appelle `deploy.stop_stack()` :
  - si le fichier d'état n'existe pas ou est illisible, la réponse est « Aucune pile UML Factory n'était active (rien à arrêter). » (code 1) ;
  - pour chaque composant, un identifiant n'est tué que si son adresse répond encore (les identifiants Windows peuvent être réutilisés) ;
  - les états possibles sont `arrêté`, `déjà arrêté`, `n'a pas pu être arrêté` ; en cas d'échec, le fichier d'état est réécrit avec les composants restants.

## Le package `ui/`

Le package est découpé en trois modules, et `ui/__init__.py` réexporte les éléments utilisés par `cli.py` et `providers.py`.

### `ui/term.py` : terminal et formats

- `Term` : détecte le terminal (`tty`), la couleur (désactivée si `NO_COLOR` est défini ou si la sortie n'est pas un terminal), et fournit `dim`, `green`, `red`, `yellow`, `cyan`, `bold`. `width` donne la largeur utilisable (au moins 40 colonnes), `height` la hauteur.
- `Term.__init__` force l'encodage UTF-8 de `stdout` et `stderr` (avec `errors="replace"`).
- `fmt_time(secondes)` : `42s` ou `3m07s`.
- `fmt_size(n)` : taille en caractères (jamais en tokens), par exemple `1,2 k caractères`.
- `fmt_seconds(s)` : `2,3 s`.
- `char_width`, `text_width`, `fit`, `clean` : largeur réelle à l'écran (un emoji compte pour deux colonnes), troncature avec `…`, texte sur une seule ligne sans tabulations.

### `ui/progress.py` : progression

| Classe | Usage | Fonctionnement |
|---|---|---|
| `StatusLine` | attente sans détail (démarrage de la pile) | thread qui réécrit la ligne toutes les 0,1 s ; sans terminal, le texte est imprimé une fois |
| `LiveView` | génération (événements `phase`, `plan`, `file`, `verify`, `written`) | tâche `asyncio` qui redessine le bloc ; curseur masqué pendant l'animation |
| `StepView` | étapes de création ou de validation d'un langage (événements `step`) | une ligne par étape, durée affichée à partir d'une seconde |

Les trois classes utilisent la même technique : un code d'échappement ANSI remonte le curseur du nombre de lignes déjà dessinées (`\x1b[nA`), efface chaque ligne (`\x1b[2K`) et redessine. `fit_ansi()` tronque une ligne contenant des couleurs sans couper une séquence.

`FileView`, `LangView` et `StepRow` sont les structures d'état de ces vues.

### `ui/prompts.py` : questions et menus

| Fonction | Rôle |
|---|---|
| `select(term, question, items, multi, default, hint, back)` | menu à flèches (ou liste numérotée) ; renvoie la liste des indices choisis |
| `ask(term, question, default, back)` | saisie libre ; `back=True` accepte `<` pour revenir |
| `confirm(term, question, default)` | réponse oui ou non (`o`, `oui`, `y`, `yes`) |
| `choose_languages(term, options, allow_new, back)` | menu à cocher des langages ; ajoute `NEW_LANGUAGE` (`+new:nom`) pour « Autre langage… » |
| `choose_puml(term, default, back)` | liste des `.puml` de `examples/` ou `source/` |
| `run_steps(steps)` | enchaîne les étapes ; `GoBack` revient à l'étape précédente ; retourne faux si l'utilisateur quitte depuis la première |
| `read_key()`, `raw_mode()` | lecture d'une touche, par plateforme |
| `BackGuard` | exige deux appuis consécutifs sur retour |
| `GoBack` | exception levée pour revenir en arrière |

`run_steps` reçoit, pour chaque étape, le libellé de la dernière ligne du menu : « ✕ Quitter » à la première étape, « ← Retour (revenir à l'étape précédente) » sinon.

`select` affiche une ligne de rappel (« ↑ ↓ pour vous déplacer · Espace pour cocher ou décocher · Entrée pour valider · Échap ou ← deux fois pour revenir ») sous les choix.

## Où regarder en cas de problème

| Symptôme | Fichier à consulter |
|---|---|
| un composant de la pile ne démarre pas | `logs/<composant>.log` (`mcp.log`, `coordinator.log`, `java.log`, ...) |
| erreur inattendue dans la CLI | `logs/erreur.log` |
| journal de l'ajout d'un langage | `umlfactory/.drafts/<langage>.install.txt` pour les outils manquants |
