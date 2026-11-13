# Tests

Le dossier `tests/` contient six fichiers, soit 76 méthodes de test au total. Ils utilisent le module standard `unittest` : aucune dépendance supplémentaire n'est nécessaire. Chaque fichier ajoute le dossier du projet au chemin Python (`sys.path.insert(...)`) pour importer le paquet `umlfactory`.

## Lancer les tests

Depuis le dossier du dépôt (celui qui contient `umlfactory/`) :

```
python -m unittest discover -s tests
```

Pour plus de détails (un nom par test) :

```
python -m unittest discover -s tests -v
```

Pour un seul fichier :

```
python -m unittest discover -s tests -p "test_verify.py"
```

Les tests Java sont ignorés (`@unittest.skipUnless`) si `javac` ou `java` n'est pas trouvé sur la machine (`verify.find_tool`). Ils apparaissent alors comme « skipped » dans la sortie. Le dossier `tests/__pycache__/` est généré automatiquement et n'a pas d'autre rôle.

## Vue d'ensemble

| Fichier | Méthodes | Thème principal |
|---|---|---|
| `test_conformity.py` | 6 | contrôle des noms pour un langage déclaratif, verdict du modèle |
| `test_languages.py` | 5 | fichier d'agent généré pour un langage ajouté |
| `test_navigation.py` | 14 | menus au clavier, retour en arrière, étapes |
| `test_stack.py` | 16 | démarrage et arrêt de la pile, options de la CLI |
| `test_verdict.py` | 16 | verdict de conformité, affichage, génération sans exécution |
| `test_verify.py` | 19 | lecture du PlantUML, vérifications Python, Java et langages déclaratifs, sécurité des spécifications |

## Détail par fichier

### `tests/test_verify.py` (19 méthodes)

Ce fichier teste les modules de vérification et d'analyse.

- **`UmlModelTest`** (2) : lecture de `examples/model.puml` (classes, héritage, réalisation, opérations d'une classe abstraite) ; membres statiques `{static}` et corps de classe sur une ligne.
- **`PythonRuntimeTest`** (6) : code conforme donne 100 ; héritage manquant signalé sur le fichier concerné ; erreur à l'exécution (`NameError` dans un module) capturée ; boucle infinie coupée par le budget de temps et déclarée « délai dépassé » ; appels sensibles (`socket`, `open(`) refusés, et le fichier qui serait créé n'existe pas à la fin ; environnement nettoyé (`clean_env` retire `OPENAI_API_KEY`).
- **`JavaRuntimeTest`** (3, si un JDK est présent) : code conforme donne 100 ; faute de frappe dans `double` attribuée à `Wallet.java` avec un score de 10 ; attribut supprimé signalé dans `Card.java`.
- **`LanguageSpecTest`** (8) : spécification saine acceptée ; outil `rm` refusé ; syntaxe de shell refusée (`;`, `import`) ; script `build.rs` dans le `scaffold` refusé ; identifiant d'une lettre valide ; `sanitize_id` (`C++` vers `cpp`, `C#` vers `csharp`, `Type Script` vers `typescript`) ; `CommandRuntime` contrôle chaque fichier (un fichier mal formé est seul signalé) ; fichier de build généré refusé.

### `tests/test_verdict.py` (16 méthodes)

Ce fichier teste le verdict du modèle, son affichage, et la génération sans exécution (`verify_budget = 0`).

- **`JudgeTest`** (7) : verdicts `conforme`, `partiel` (avec liste des éléments manquants, même dans un bloc de code), `non_conforme` ; une erreur non résolue interdit le verdict `conforme` ; une exception du modèle donne « non vérifié » avec une raison ; une réponse illisible ou un verdict inconnu donne « non vérifié » ; les conseils du langage et le diagramme parviennent bien au modèle.
- **`DisplayTest`** (4) : chaque verdict a son texte (`conformity_lines`) ; « non vérifié » donne la raison et n'affiche jamais de note chiffrée ; une compilation non exécutée est signalée ; un verdict absent donne « Non vérifié ».
- **`GenerateTest`** (2) : la génération (`PhpGenerator.generate`, avec un modèle simulé) renvoie le verdict sans clé `explanation` ; un diagramme illisible donne « non vérifié ».
- **`NewLanguageTest`** (3) : le prompt de création demande des `conformity_rules` ; le fichier d'agent rendu contient ces règles et reste du Python valide ; l'agent PHP a ses règles de conformité.

### `tests/test_conformity.py` (6 méthodes)

Ce fichier teste `CommandRuntime` (les contrôles de noms des langages déclaratifs) avec une spécification dont la commande de build est `python -c pass` : la compilation est donc toujours réussie, et seule la comparaison des noms compte.

- le code qui reprend tous les noms obtient 100 et aucune erreur ;
- une classe absente (`Compte`) donne une erreur et un score inférieur à 100 ;
- une opération absente (`deposer`) est signalée dans le bon fichier ;
- un attribut absent (`nom`) est signalé dans `Client.php` ;
- `get_nom` est accepté pour `getNom` (casse et `_` ignorés) ;
- un diagramme non analysé (`@startuml @enduml` vide) ne peut pas dépasser 60, avec la remarque « non vérifiée ».

### `tests/test_languages.py` (5 méthodes)

Ce fichier teste la création du fichier d'agent d'un langage ajouté. Chaque test redirige `GENERATORS_DIR` et `DRAFT_DIR` vers un dossier temporaire.

- le fichier rendu puis chargé donne une sous-classe de `CommandGenerator` avec les bons attributs (`language`, `display_name`, `file_extensions`, `style_rules`, `build`, `tools`) ;
- l'export supprime le brouillon ;
- une spécification dangereuse (`rm -rf`) n'est jamais écrite (`ValueError`) ;
- un fichier édité à la main pour remplacer la commande par `rm` est refusé au moment de `runtime()` (`RuntimeError`) ;
- `delete_generated` ne supprime que les fichiers créés par la CLI, jamais un agent écrit à la main.

### `tests/test_navigation.py` (14 méthodes)

Ce fichier teste les menus. `run_menu` simule les touches avec `mock` : `read_key` renvoie les touches d'une liste, `raw_mode` est remplacé, et `sys.stdin.isatty` renvoie vrai.

- **`BackGuardTest`** (3) : un appui seul ne revient pas en arrière ; deux appuis (Échap puis flèche gauche) reviennent ; une autre touche remet le compteur à zéro.
- **`MenuTest`** (8) : un seul appui sur retour affiche le rappel et reste sur le menu ; deux appuis reviennent (`GoBack`) ; la ligne « ← Retour » demande deux Entrée ; pour les choix multiples, rien de coché est refusé avec un message, puis plusieurs cases cochées donnent la liste triée des indices ; le mode numéroté renvoie `GoBack` pour `0`.
- **`StepsTest`** (3) : l'enchaînement avant (première étape « Quitter », suivantes « Retour ») ; un retour revient à l'étape précédente puis reprend ; un retour à la première étape fait quitter (`run_steps` renvoie faux).

### `tests/test_stack.py` (16 méthodes)

Ce fichier teste la pile et les options de la CLI. Les processus et les ports sont simulés (`mock`), les tests ne lancent aucun composant.

- **`StackNeededTest`** (3) : coordinateur local arrêté, donc pile à démarrer ; coordinateur local allumé, rien à faire ; coordinateur distant, jamais de démarrage.
- **`StopTest`** (5) : sans fichier d'état, `stop_stack` renvoie `None` ; un fichier d'état corrompu est ignoré et supprimé ; les composants vivants sont arrêtés (SIGTERM simulé) et le fichier d'état est supprimé ; un identifiant dont le port ne répond plus n'est jamais tué (`os.kill` non appelé) ; un composant qui ne s'arrête pas est signalé et son état est conservé.
- **`StopCommandTest`** (3) : sans pile, message clair et code non nul, sans trace Python ; la liste des composants trouvés et arrêtés est affichée ; un arrêt en échec donne le code 1 et « tourne encore ».
- **`OptionsTest`** (5) : `--keep-running` et `--stop` sont reconnus ; `--spawn` n'existe plus (code 2) ; les erreurs d'options sont des phrases courtes en français, sans `usage:` ni `Traceback` ; `--stop` avec `--keep-running` est refusé ; une exception inattendue affiche « Erreur inattendue » et renvoie le chemin du journal, sans trace.

### `tests/test_navigation.py` et `tests/test_stack.py` : ce qu'ils ont en commun

Les deux fichiers remplacent les entrées et les processus par des objets simulés. Aucun test n'ouvre de terminal réel ni ne démarre de serveur.

## Ce qui est couvert indirectement

Certaines parties du code ne sont pas testées directement par ces six fichiers, mais leurs fonctions sont appelées par les tests :

- `skills.py` est importé par `test_verdict.py` (`_spec_prompt`) ; `skills.validate_language` et `skills.create_language` ne sont pas appelés ;
- `cli.py` est importé pour `conformity_lines`, `stop_command`, `stack_needed` et `build_parser` ; la fonction `run()` (le parcours complet) n'est pas testée ;
- `llm.py` n'est pas testé directement : `test_verdict.py` remplace le client par un objet simulé (`FakeLLM`, `ScriptedLLM`) ;
- `mcp_server.py`, `mcp_client.py`, `a2a_common.py`, `coordinator.py`, `providers.py` et `config.load_settings` n'ont pas de test dans `tests/`.
