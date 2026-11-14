# Génération par langage

Ce document explique comment un agent de langage transforme un diagramme en code : la planification, l'écriture, les contrôles, la correction, la vérification d'exécution et le verdict. Il décrit ensuite ce qui est propre à Java, à Python, à PHP et aux langages déclaratifs.

Tous les agents partagent le même pipeline, défini dans `generators/base.py`. Seuls les règles de style, la vérification d'exécution et les contrôles statiques changent d'un langage à l'autre.

## Le socle commun : `BaseGeneratorAgent`

Fichier : `umlfactory/generators/base.py`.

`BaseGeneratorAgent` hérite de quatre classes : `PromptsMixin` (messages, [voir 05](05-llm-et-agents.md#prompts-generatorspromptspy)), `PlanningMixin` (plan de fichiers), `RepairMixin` (contrôles communs), et `AgentExecutor` (protocole A2A).

Une sous-classe définit :

| Attribut | Rôle | Exemple (Java) |
|---|---|---|
| `language` | identifiant (et nom du module) | `"java"` |
| `display_name` | nom affiché | `"Java"` |
| `file_extensions` | extensions acceptées dans le plan | `(".java",)` |
| `source_media_type` | type MIME des artefacts | `"text/x-java-source"` |
| `plan_rules` | règle de découpage en fichiers, donnée au modèle | « one file per top-level type, named exactly `<TypeName>.java` » |
| `style_rules` | règles de génération, donnée au modèle | Java 17, packages, getters et setters |
| `conformity_rules` | conseils pour le verdict | (vide pour Java : le verdict repose sur les constats automatiques) |

La méthode `validate(files)` est abstraite : elle fait les contrôles statiques du langage. La méthode `runtime()` renvoie la vérification d'exécution (un objet `Runtime`), ou `None`.

### Le déroulement de `generate()`

`generate(req, llm, concurrency, max_repairs, emit, verify_budget)` enchaîne les étapes suivantes :

1. **Planification** : `self._plan(req, llm, warnings, say)` demande au modèle la liste des fichiers. Événements `phase` « planification » puis `plan`.
2. **Écriture** : un appel du modèle par fichier, en parallèle, limité par un sémaphore de taille `concurrency` (`OPENAI_CONCURRENCY`, défaut 5). Chaque réponse passe par `textutil.extract_code()`, qui garde le plus long bloc de code.
3. **Boucle de contrôle et de correction**, au plus `max_repairs + 1` passages (`MAX_REPAIRS = 2`, donc trois passages au maximum) :
   - `self._check(files, plan)` : contrôles communs puis contrôles du langage ;
   - si aucune erreur statique, `self._verify(...)` lance la vérification d'exécution (voir plus bas) et ajoute ses erreurs ;
   - s'il reste des erreurs et qu'il reste un tour, `fix_one` renvoie chaque fichier fautif au modèle avec le problème à corriger ; sinon les erreurs deviennent des avertissements.
4. **Comparaison avec le diagramme** : `umlmodel.parse(req.puml)` ; si aucune classe n'est trouvée, le verdict est « non vérifié ». Sinon `repair.judge_conformity(...)` demande le verdict au modèle.
5. **Résultat** : un `GenerationResult` (`files`, `warnings`, `verification`).

Le pipeline complet est résumé dans [FONCTIONNEMENT.md](FONCTIONNEMENT.md#vue-par-étapes-de-la-génération-dun-langage).

### Vérification d'exécution : `_verify()`

`_verify` lance `runtime.check(ctx)` dans un thread (`asyncio.to_thread`) et surveille la tâche toutes les 0,25 s. Si l'étape dure plus d'une seconde (`SLOW_AFTER = 1.0`), un événement `verify` « slow » indique l'étape en cours. À la fin, un événement `verify` « done » donne le score et la durée. Si la vérification lève une exception, elle devient un `VerifyReport` avec `skipped` : la génération n'échoue pas pour cela.

## Planification : `generators/planning.py`

Le modèle reçoit le diagramme (dans un bloc `<uml>`), les consignes du package et des instructions, et doit répondre par un objet JSON :

```json
{"files": [{"path": "<chemin relatif>", "elements": ["<élément UML>"], "summary": "<une ligne>"}]}
```

`PlanningMixin._plan()` fait jusqu'à **trois tentatives** (`PLAN_ATTEMPTS = 3`). Chaque réponse est contrôlée par `_parse_plan()` :

- `files` doit être une liste non vide ;
- chaque entrée doit avoir un `path` texte ;
- le chemin est rendu conforme au package : `normalize_path()` place le fichier dans le dossier du package (`com/exemple/banque/` pour `com.exemple.banque`) ;
- le chemin doit passer `paths.safe_relative_path` (pas de `..`, pas de chemin absolu) ;
- l'extension doit être celle du langage ;
- les doublons sont refusés ;
- au plus 300 fichiers sont retenus (`MAX_PLANNED_FILES`).

Ensuite, `textutil.declared_names(req.puml)` repère les types déclarés dans le diagramme (une regex sur les lignes `class`, `interface`, `enum`, `abstract class`, sans les notes). Les noms absents des `elements` du plan sont renvoyés au modèle avec la consigne de refaire le plan. Si, à la dernière tentative, le plan est exploitable mais incomplet, la génération continue et un avertissement est ajouté : « éléments du diagramme absents du plan : ... ». Si aucun plan exploitable n'existe après trois tentatives, `LLMError` est levée.

Le plan est ensuite communiqué à tous les appels d'écriture (`_plan_listing`), pour que chaque fichier connaisse les noms des autres.

## Contrôles communs : `generators/repair.py` (`RepairMixin._check`)

Pour chaque fichier du plan :

1. un fichier vide donne l'erreur « the file is empty » ;
2. chaque élément du plan doit apparaître comme mot entier dans le fichier (regex `\b<nom>\b`), sinon l'erreur liste les éléments absents : « the file must define: ... ».

Puis `self.validate(...)` (contrôles du langage) ajoute ses erreurs. Les erreurs d'un même fichier sont fusionnées.

## Vérification d'exécution : `umlfactory/verify.py`

`verify.py` ne dépend d'aucun module réseau : il peut être testé seul (son en-tête le dit).

### Principes de sécurité

- le code est écrit dans un dossier temporaire (`tempfile.TemporaryDirectory`), jamais dans le projet ;
- chaque commande est lancée **sans shell** (`run()` utilise `subprocess.run` avec une liste d'arguments, `stdin=DEVNULL`, délai strict, sortie limitée à 20 000 caractères) ;
- l'environnement est filtré par une liste blanche (`_ENV_KEEP`) : les variables comme `OPENAI_API_KEY` ou celles du `.env` ne sont pas transmises (`clean_env`). `TMP`, `TEMP` et `TMPDIR` pointent vers le dossier temporaire ;
- un scan préalable (`scan_sensitive`) cherche les appels sensibles déclarés par le langage. S'il en trouve, rien n'est exécuté : `Runtime.blocked()` renvoie un score de 0 et une erreur par fichier, que la correction doit supprimer ;
- il n'y a pas d'isolation système (pas de conteneur) : le code vérifié tourne avec les droits de l'utilisateur.

### Budget de temps

`Tracker(budget)` fixe une échéance globale (`VERIFY_BUDGET = 10.0` secondes dans `config.py`, valeur fixe). `Tracker.measure(nom)` enregistre la durée de chaque étape. Les commandes reçoivent un délai de `min(tracker.left(), limite de l'étape)`. Un dépassement donne « non vérifié » (`skipped`), jamais « réussi ».

### Outils présents sur la machine

`Runtime.missing()` vérifie avec `shutil.which` (`find_tool`) que les exécutables requis existent. Pour `python`, l'interpréteur courant (`sys.executable`) suffit. Si un outil manque, `blocked()` renvoie un rapport `skipped` : le code est généré mais non exécuté, et la CLI l'affiche (« Compilation non vérifiée : outil introuvable... »).

### Score interne

`compute_score(parts)` fait une moyenne pondérée de paliers, chacun valant entre 0 et 1 :

```python
round(100 * sum(w * (f or 0.0) for w, f in parts) / total)
```

Un palier non exécuté compte 0. `findings_to_report()` construit les paliers :

| Palier | Poids (langage avec test de fumée) | Source |
|---|---|---|
| outils et exécution de base | 10 | constant à 1,0 |
| compilation (ou chargement des modules) | 40 | fraction des constats `import` (Python) ou 1,0 si `javac` a réussi |
| test de fumée | 25 | fraction des constats `init` (instanciation des classes) |
| conformité | 25 | fraction des constats `class`, `extends`, `attr`, `op`, `rel` |

Sans test de fumée (`smoke_checked=False`, cas PHP et langages déclaratifs), les poids deviennent 10, 40 et 50 : la conformité remplace le test de fumée.

Le score n'est jamais affiché à l'utilisateur (`cli.conformity_lines` et `ui.LiveView` ne montrent que le verdict du modèle et la durée de contrôle).

### Constats

Le harnais (Java ou Python) imprime des lignes `@@UMLFACTORY@@NIVEAU|genre|classe|message` (voir [02-flux-de-donnees.md](02-flux-de-donnees.md#lignes-de-résultat-du-harnais)). `parse_findings()` les lit. `findings_to_report()` transforme :

- un constat `FAIL` en erreur, attribuée au fichier qui définit la classe (`ctx.file_of(nom)`), avec le libellé « loading », « smoke test » ou « diagram conformity » ;
- un constat `SOFT` (cardinalité, instanciation avec des valeurs nulles) en remarque. Les remarques de relation vont dans `notes`, les autres dans `details`.

Un constat `SKIP` (classe jamais chargée parce qu'un module n'a pas pu être importé) compte comme un échec, pas comme une réussite.

### Comparaison par noms : `name_findings()`

Pour les langages sans harnais d'exécution (PHP, langages déclaratifs), `name_findings()` vérifie seulement que les noms du diagramme apparaissent comme identifiants dans le fichier de chaque classe (casse et `_` ignorés, grâce à `_norm`). Les types, les paramètres et le comportement ne sont pas comparés.

## Java : `generators/java.py`

### Règles de génération (`style_rules`)

Le modèle reçoit les règles suivantes (résumé) : Java 17 ; un type de premier niveau par fichier, public, nommé comme le fichier ; le package est celui demandé (sinon aucun `package`) ; seules les bibliothèques du JDK ; attributs privés avec accesseurs `getX` / `setX` (`isX` pour les booléens) ; relations typées par la classe cible, collections en `List<T>` initialisées ; `abstract class` et `interface` traduits en conséquence ; pas de `toString`, `equals` ou `hashCode` récursifs dans les associations bidirectionnelles.

### Contrôles statiques : `JavaGenerator.validate()`

1. `balanced(code)` vérifie que les parenthèses, crochets et accolades sont équilibrés, en ignorant les chaînes, les caractères et les commentaires (`_LITERALS`). C'est un contrôle de secours, indépendant de `javac`.
2. La déclaration `package` doit correspondre au dossier du fichier : un fichier dans `com/exemple/banque/` doit déclarer `package com.exemple.banque;`, et un fichier à la racine ne doit avoir aucun `package`. Sans cette règle, les fichiers ne se verraient pas entre eux.

### Vérification d'exécution : `JavaRuntime`

- **Outils** : `javac` et `java`.
- **Scan** : le scan refuse les appels liés aux processus (`ProcessBuilder`, `Runtime.getRuntime`), au réseau (`java.net`, `Socket`, `HttpClient`), aux fichiers (`java.io.File`, `java.nio.file`), à la réflexion et au code natif, à l'environnement et aux sorties (`System.exit`, `System.getenv`).
- **Compilation** : `javac` avec `-proc:none`, `-encoding UTF-8`, sortie dans un dossier `out`, avec les fichiers du projet et le harnais `UmlSmoke.java`. La première tentative utilise `-J-XX:TieredStopAtLevel=1` ; si la machine virtuelle refuse ces options, la compilation est relancée sans elles.
- **Erreurs de compilation** : la sortie de `javac` est découpée par la regex `_ERROR_START` (`fichier.java:ligne: error: `). Chaque bloc est attribué au fichier concerné. Si aucun bloc n'est reconnu, une remarque est ajoutée. Un échec de compilation donne un score de 10.
- **Exécution** : `java -cp out UmlSmoke expect.txt` avec un budget de 5 secondes. Le harnais lit le fichier d'attentes (voir [02](02-flux-de-donnees.md#fichier-dattentes-pour-java-expecttxt)).

### Le harnais Java (`_HARNESS`)

Le harnais est une classe Java écrite dans la chaîne `_HARNESS`. Il fait, dans cet ordre :

1. charger chaque type attendu (`Class.forName`) et vérifier sa nature : interface, énumération, classe abstraite ou classe concrète ;
2. vérifier l'héritage et la réalisation (`isAssignableFrom`) ;
3. vérifier les attributs (champs déclarés, constantes d'énumération) et les opérations (méthodes déclarées) par leur nom normalisé ;
4. vérifier les relations : un champ dont le type générique cite la cible (regex sur `getTypeName()`), ou une collection si la cardinalité est supérieure à 1 (remarque `SOFT` sinon) ;
5. instancier chaque classe concrète avec des valeurs par défaut (`value()` : `0`, `false`, `""`, listes vides...), en essayant les constructeurs du plus petit au plus grand. Aucune méthode métier n'est appelée. Une exception `NullPointerException`, `IllegalArgumentException`, `IllegalStateException`, `UnsupportedOperationException` ou `ArithmeticException` donne seulement une remarque.

Le harnais ne lance jamais `main`. Il est compatible Java 8 et suivants (commentaire dans le code).

## Python : `generators/python.py`

### Règles de génération

Un module par classe, interface ou énumération, nommé en `snake_case` (`BankAccount` vers `bank_account.py`). Si un package est donné, les modules sont rangés dans ce dossier avec un `__init__.py` qui réexporte les types (`__all__`). Python 3.10 ou plus ; `from __future__ import annotations` ; imports circulaires interdits, avec la règle `if TYPE_CHECKING:` pour les imports seulement utilisés dans les annotations ; attributs d'instance dans `__init__`, les attributs privés exposés par `@property` ; classes abstraites en `abc.ABC` avec `@abstractmethod`.

### Contrôles statiques : `PythonGenerator.validate()`

1. Chaque fichier est analysé avec `ast.parse`. Une erreur de syntaxe donne « SyntaxError line N : ... ».
2. `runtime_imports(tree, known)` relève les modules du projet importés au chargement. Les imports dans un bloc `if TYPE_CHECKING:` et dans les fonctions sont ignorés.
3. `find_cycle(graph)` cherche un cycle dans ce graphe (parcours en profondeur). Les fichiers du cycle reçoivent l'erreur « circular import at load time : a -> b -> a... ». Le modèle reçoit aussi la consigne de `prompts.repair_hint` : déplacer les imports d'annotation sous `TYPE_CHECKING`.

### Vérification d'exécution : `PythonRuntime`

- **Outils** : aucun (l'interpréteur qui fait tourner l'agent suffit).
- **Scan** : refuse les processus (`os.system`, `subprocess`, `multiprocessing`), le réseau (imports de `socket`, `urllib`, `http`, `requests`...), les fichiers (`shutil`, `os.remove`, `open(`...), le code dynamique (`exec`, `eval`, `compile`, `__import__`, `ctypes`), et l'environnement (`os.environ`, `sys.exit`).
- **Exécution** : `python -I -B -X utf8 harness.py spec.json src`, avec un budget de 6 secondes. L'option `-I` ignore l'environnement utilisateur et le répertoire courant. Le harnais est exécuté dans un sous-processus séparé.
- **Harnais Python** (`_HARNESS`) : importe chaque module (`importlib.import_module`), vérifie qu'une classe du diagramme existe avec la bonne nature (`enum.Enum` pour une énumération, non abstraite pour une classe), vérifie l'héritage (`issubclass`), les attributs (noms de `dir()`, annotations, attributs d'instance ou texte de la source), les opérations (`dir()`), les relations (regex sur le texte de la source), et instancie les classes concrètes avec des valeurs par défaut déduites de l'annotation (`default_for` : `int`, `float`, `bool`, `str`, `list`, `set`, `dict`, `tuple`).
- La fraction de réussite des imports sert de palier « compilation » (poids 40).

Un import qui échoue donne un `FAIL` pour le module. Ensuite, toute classe du diagramme qui n'est introuvable alors qu'un import a échoué reçoit un `SKIP` (et non un `FAIL`), car son absence peut venir de ce module.

## PHP et langages déclaratifs : `_declarative.py` et `php.py`

Un langage déclaré par données n'a pas de code de vérification propre. Ses attributs décrivent tout : règles, outils, commande de contrôle. `_declarative.py` contient le moteur commun.

### `CommandRuntime`

Vérifie le code avec la commande déclarée (`build`), après avoir écrit les fichiers et les `scaffold` dans `src/` d'un dossier temporaire :

1. les fichiers interdits (`build.rs`, `package.json`, `*.csproj`, scripts, etc., listés dans `languages.FORBIDDEN_FILES` et `FORBIDDEN_SUFFIXES`) donnent une erreur et arrêtent la vérification ;
2. le scan des appels sensibles (`sensitive_calls`) est appliqué ;
3. si `build` contient `{file}`, la commande est lancée une fois par fichier ; sinon une seule fois avec `{files}` ou `{dir}` ;
4. les erreurs sont attribuées au fichier (si `{file}`) ou à l'ensemble des fichiers ;
5. sans erreur, `name_findings()` compare les noms, avec `findings_to_report(..., smoke_checked=False)`.

`expand_command()` remplace `{files}`, `{file}` et `{dir}` dans la liste d'arguments. Aucun shell n'est utilisé.

Sans commande (`build` vide), la vérification est « non compilée » : le code est généré, et la remarque « code non compilé (aucune commande de vérification) » est ajoutée.

### `CommandGenerator`

Sous-classe de `BaseGeneratorAgent` qui ne déclare que des attributs de classe : `tools`, `build`, `scaffold`, `sensitive_calls`, `conformity_rules`, `status`, `score`. Sa méthode `runtime()` contrôle la spécification avec `safety_problems()` (exécutable hors liste, argument contenant un caractère de shell, etc.). Si un problème est trouvé, elle lève un `RuntimeError` « agent « ... » refusé » dès que la vérification est demandée (construction de la carte A2A ou début de `_verify`).

`validate()` ne fait rien de plus que renvoyer un `Validation` vide : la vérification réelle est faite par la commande.

### `DeclarativeGenerator`

Agent construit à partir d'une `LanguageSpec` (brouillon) pendant la validation d'un langage ajouté, avant l'écriture de son fichier définitif. Voir [05](05-llm-et-agents.md#skills-skillspy-et-languagespy) pour le cycle complet.

### `PhpGenerator` (`php.py`)

C'est l'exemple d'agent déclaratif. Il est écrit comme un fichier créé par la CLI (la mention « Fichier créé par « Autre langage… » » est reconnue par `languages.is_generated`), mais il est modifiable à la main.

| Élément | Valeur |
|---|---|
| `file_extensions` | `.php` |
| `tools` | `php` |
| `build` | `php -l {file}` (contrôle de syntaxe, un fichier à la fois) |
| `sensitive_calls` | `exec(`, `shell_exec(`, `system(`, `curl_init(`, `unlink(`, `getenv(`, `$_ENV`... |
| `status`, `score` | `validated`, 100 |

Les règles de conformité (`conformity_rules`) disent au modèle comment retrouver chaque élément : une classe est une déclaration `class`, `abstract class`, `interface` ou `enum` ; un attribut est une propriété `$nom` ; une opération est `function nom(` ; l'héritage est `extends`, la réalisation `implements` ; une relation est une propriété typée par l'autre classe, ou un tableau documenté `list<Autre>` pour une cardinalité supérieure à 1.

Comme PHP n'a pas de harnais d'exécution, son score de conformité repose sur `name_findings()` (présence des noms), et son test de fumée est absent.

## Correction : tours de réparation

Les erreurs des contrôles et de la vérification sont renvoyées par `fix_one` :

- le message envoyé contient la tâche (`[task: repair path=...]`), le diagramme, les consignes de package, le plan, les autres fichiers (si leur total est inférieur à `SIBLING_CONTEXT_CHARS` = 24 000 caractères), le contenu actuel du fichier, les problèmes trouvés, et une consigne ciblée si la cause est un import circulaire ;
- le modèle doit répondre par un seul bloc de code contenant le fichier complet ; si la réponse est vide, l'ancien contenu est conservé ;
- seuls les fichiers en erreur sont renvoyés, en parallèle ;
- au plus **deux** tours de correction (`MAX_REPAIRS = 2`, constante fixe). Les erreurs qui restent sont ajoutées aux avertissements, avec le fichier et le premier message d'erreur.

Une erreur résiduelle empêche le verdict « conforme » : `judge_conformity` le remplace par « partiel » et ajoute l'erreur dans la liste des éléments manquants (8 au maximum).

## Verdict de conformité : `repair.judge_conformity()`

Le modèle relit le diagramme et le code. Son message système, `JUDGE_SYSTEM`, lui demande de lister chaque classe, attribut, opération, héritage et relation, de chercher leur nom dans le code (casse et `_` ignorés), puis de répondre par un objet JSON :

```json
{"verdict": "conforme | partiel | non_conforme", "missing": ["..."], "summary": "une phrase"}
```

Le message utilisateur contient les conseils du langage (`conformity_rules`), les constats automatiques (jusqu'à 12), le diagramme, et le code. Les fichiers dont le total dépasse 60 000 caractères ne sont pas transmis (remplacés par « fichier trop long, non transmis »).

Le résultat est nettoyé : `missing` est limité à 8 éléments de 120 caractères, `summary` à 200 caractères.

Le verdict est « non vérifié » (`unverified(raison)`) dans trois cas : le diagramme n'a pas pu être analysé (aucune classe trouvée), le modèle a échoué (exception), ou sa réponse n'est pas un JSON exploitable avec un verdict connu.

## Tableau comparatif

| Aspect | Java | Python | PHP (déclaratif) |
|---|---|---|---|
| Fichier | `generators/java.py` | `generators/python.py` | `generators/php.py` |
| Classe | `JavaGenerator` + `JavaRuntime` | `PythonGenerator` + `PythonRuntime` | `PhpGenerator` (`CommandGenerator`) |
| Contrôles statiques | parenthèses équilibrées, package et dossier | `ast.parse`, cycles d'imports | `php -l` par fichier |
| Compilation | `javac` avec `-proc:none` | import des modules dans un sous-processus | `php -l` |
| Test de fumée | instanciation des classes (`UmlSmoke`) | instanciation des classes (`harnais Python`) | aucun |
| Comparaison | réflexion Java | `dir()`, annotations, texte de source | noms dans le texte |
| Outils requis | `javac`, `java` | aucun | `php` |
| Budget | `javac` 8 s, `java` 5 s | 6 s | 8 s |

## Ce que la CLI affiche de ces vérifications

Le détail visible est limité à trois lignes par langage (voir [03-cli-et-affichage.md](03-cli-et-affichage.md)) : le verdict du modèle, une ligne « Compilation non vérifiée : ... » si l'exécution n'a pas eu lieu, et la mention « code contrôlé » ou « code non exécuté » dans l'affichage en direct.
