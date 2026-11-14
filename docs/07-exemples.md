# Exemples d'utilisation

Ces exemples reprennent les commandes du `README.md` et les diagrammes du dossier `examples/`. Ils sont réalistes, mais le code produit par le modèle n'est pas identique d'une exécution à l'autre : les fichiers décrits ici sont ceux que les règles de chaque langage demandent. Le plan exact (nombre de fichiers, noms) est décidé par le modèle, puis contrôlé.

## Diagrammes fournis

| Fichier | Contenu | Éléments remarquables |
|---|---|---|
| `examples/model.puml` | 5 types : `BankAccount`, `CreditCard`, `Customer`, `Wallet` (abstraite), `IPaymentProcessor` (interface) | un héritage (`Wallet` vers `CreditCard`), une réalisation d'interface (`CreditCard` vers `IPaymentProcessor`), des notes, des relations avec cardinalités |
| `examples/banque_grand.puml` | 11 types, dont une énumération `TypeTransaction` | héritage, interface `IPaiement`, associations dans les deux sens, notes en français |

Les deux fichiers sont proposés automatiquement par le menu de la CLI, car ils se trouvent dans `examples/`.

## 1. Premier lancement, tout en interactif

```
python -m umlfactory.cli
```

Ce que le programme fait, dans l'ordre :

1. si la pile n'est pas allumée, il lance le serveur MCP, le coordinateur et les agents (`✔ Pile prête`) ;
2. il teste les clés présentes dans `.env` ; si les deux fournisseurs sont valides, il demande lequel utiliser, une seule fois ;
3. il affiche la liste des `.puml` de `examples/` (`cli.step_file` → `ui.choose_puml`) ; on choisit `banque_grand.puml` avec les flèches et Entrée ;
4. il affiche le menu des langages (Espace pour cocher, par exemple Java et Python) ;
5. il propose `sortie` comme dossier (Entrée pour accepter) ;
6. il génère, affiche la progression, puis le résultat ; à la fin, il arrête la pile.

Pendant l'étape 3, `←` ou `Échap` deux fois revient à l'étape précédente. Un seul appui affiche le rappel « Appuyez encore une fois... ».

## 2. Génération Java en une ligne

```
python -m umlfactory.cli examples/model.puml --lang java -o sortie
```

- Le langage est donné : aucune question sur le langage ; `-o` donne le dossier, donc aucune question sur la destination.
- Un seul langage et `--layout auto` : les fichiers sont écrits directement dans `sortie\`.
- D'après les règles du langage (`JavaGenerator.plan_rules`), il y a un fichier par type de premier niveau, nommé comme le type : `BankAccount.java`, `CreditCard.java`, `Customer.java`, `Wallet.java`, `IPaymentProcessor.java`. Le code est sans `package` (aucun package demandé).
- Le verdict s'affiche par langage, par exemple « ✔ Conforme au diagramme », ou « ⚠ Partiellement conforme au diagramme » suivi des éléments manquants.
- Si un JDK est installé, `javac` compile le code et un test de fumée instancie les classes. Sans JDK, la ligne « Compilation non vérifiée : outil introuvable sur cet appareil : javac, java » apparaît (`JavaRuntime.blocked`).

Les blocs de sortie ci-dessus sont des formes. Un résultat réel ressemble à ceci (le format vient de `cli.run` et `cli.conformity_lines`) :

```diff
+ ✔ Java : 5 fichier(s) → C:\...\sortie
+    ✔ Conforme au diagramme
+ Durée totale : 1m12s
```

## 3. Java avec un package

```
python -m umlfactory.cli examples/model.puml --lang java --package com.exemple.banque -o sortie
```

Avec `--package`, chaque fichier est placé dans le dossier du package (`normalize_path` dans `planning.py`) :

```
sortie\
  com\
    exemple\
      banque\
        BankAccount.java
        CreditCard.java
        ...
```

Chaque fichier déclare `package com.exemple.banque;`. Le contrôle de cohérence de `JavaGenerator.validate()` refuse un fichier dont le `package` ne correspond pas à son dossier, et renvoie cette erreur au modèle pour correction.

## 4. Plusieurs langages à la fois

```
python -m umlfactory.cli examples/model.puml --lang java python -o sortie
```

Avec deux langages, `--layout auto` choisit `by-language` (`coordinator.pick_destination`) : le code Java va dans `sortie\java\`, et le code Python dans `sortie\python\`.

Pour Python, les modules sont nommés en `snake_case` : `bank_account.py`, `credit_card.py`, `customer.py`, `wallet.py`, `i_payment_processor.py` (règle `PythonGenerator.plan_rules`). Avec `--package`, les modules sont rangés dans ce dossier et un `__init__.py` réexporte les types.

Les agents tournent en parallèle : la durée totale est proche de celle du langage le plus long, et non la somme des deux.

## 5. Grand diagramme avec énumération

```
python -m umlfactory.cli examples/banque_grand.puml --lang java -o sortie --package com.exemple.banque
```

Ce diagramme contient une énumération `TypeTransaction` (`DEPOT`, `RETRAIT`, `VIREMENT`) : elle devient un fichier `TypeTransaction.java` contenant un `enum`. La vérification Java compare ses constantes aux attributs du diagramme (`A` dans le fichier d'attentes), et ne cherche pas d'opérations dans une énumération.

Une classe abstraite (`CompteBancaire`) et deux sous-classes (`CompteCourant`, `CompteEpargne`) donnent une vérification d'héritage : `Class.isAssignableFrom` doit être vrai. Si le modèle oublie `extends`, le constat `FAIL` est transformé en erreur, et la correction le renvoie.

## 6. PHP

```
python -m umlfactory.cli examples/model.puml --lang php -o sortie
```

PHP est un langage déclaratif (`generators/php.py`) : il n'a pas de harnais d'exécution. Le contrôle se fait par `php -l` sur chaque fichier, puis par la recherche des noms du diagramme dans le texte. Les fichiers sont nommés en PascalCase (`BankAccount.php`), avec des dossiers selon les espaces de noms.

Si `php` n'est pas installé, le code est généré, mais la ligne « Compilation non vérifiée : outil introuvable sur cet appareil : php » s'affiche. Un langage dont l'outil manque est signalé à l'avance par la CLI, avant la génération (`cli.run` : « outil manquant (php). Le code sera créé mais pas testé. »).

## 7. Demande libre : le modèle choisit le langage

```
python -m umlfactory.cli examples/model.puml --ask "en Python" -o sortie
```

Avec `--ask`, le coordinateur demande au modèle quels langages l'utilisateur veut parmi ceux qui sont disponibles (`Coordinator._choose_languages`). Le modèle répond par un objet JSON. Si aucun langage n'est reconnu, la demande échoue avec la liste des langages disponibles. Le README indique que `--lang` est plus fiable.

## 8. Consignes libres

```
python -m umlfactory.cli examples/model.puml --lang java --instructions "utilise des records quand c'est possible" -o sortie
```

La consigne est ajoutée au message de l'utilisateur, dans la section « Additional instructions from the user (trusted) » (`PromptsMixin._extras`). Elle ne peut pas modifier le diagramme : le message système rappelle que la structure ne doit pas changer.

## 9. Dossier déjà rempli

Relancer la même commande alors que `sortie\` contient déjà des fichiers :

```
python -m umlfactory.cli examples/model.puml --lang java -o sortie
```

En mode interactif, la CLI affiche « ... contient déjà N fichier(s). Remplacer les fichiers qui ont le même nom ? » (`ui.confirm`). En mode non interactif (par exemple dans un script), la même commande échoue avec « utiliser --overwrite pour les remplacer ». Avec `--overwrite` ou `-y`, les fichiers sont remplacés.

Le serveur MCP refuse en plus d'écraser un fichier dont le contenu est différent sans `overwrite` : le message est « fichiers existants différents (rien n'a été écrit) ».

## 10. Utilisation dans un script ou en CI

```
python -m umlfactory.cli examples/model.puml --lang java -o build\code --overwrite
```

En dehors d'un terminal interactif, il faut donner le fichier, le langage et le dossier : `cli.run` ne pose aucune question dans ce cas, et une option manquante fait échouer la commande avec un message (par exemple « préciser --lang parmi : ... »). Le code de sortie permet de réagir : `0` tout va bien, `1` échec d'un langage, `2` option incorrecte, `130` interruption.

## 11. Garder la pile allumée pour enchaîner les conversions

```
python -m umlfactory.cli examples/model.puml --lang java -o sortie --keep-running
python -m umlfactory.cli examples/banque_grand.puml --lang python -o sortie --package banque
python -m umlfactory.cli --stop
```

- Le premier appel démarre la pile, puis la laisse allumée (`deploy.running_stack(..., keep=True)`) et écrit `.umlfactory-stack.json`.
- Le deuxième appel trouve le coordinateur allumé : il ne démarre rien (`stack_needed` renvoie faux).
- `--stop` lit `.umlfactory-stack.json`, vérifie que chaque port répond, arrête chaque processus, puis supprime le fichier d'état.

Sortie attendue de `--stop` (format de `cli.stop_command`) :

```
Pile trouvée : serveur MCP (port 9000), coordinateur (port 9200), agent java (port 9101), ...
  ✔ arrêté      serveur MCP (port 9000)
...
✔ Pile arrêtée (5 composant(s)).
```

## 12. Pile au premier plan, dans un autre terminal

Terminal 1 :

```
python -m umlfactory.deploy
```

Le programme affiche une ligne par composant, avec ✔ quand il est prêt, puis attend. Les journaux sont dans `logs\`. `Ctrl+C` arrête tout.

Terminal 2 :

```
python -m umlfactory.cli examples/model.puml --lang java -o sortie
```

Le coordinateur répond déjà sur `127.0.0.1:9200` : la CLI n'essaie pas de démarrer une seconde pile, et ne l'arrête pas à la fin.

## 13. Lister les langages

```
python -m umlfactory.cli --list-languages
```

Affiche une ligne par langage, au format `{identifiant:<12} {nom}` (`cli.run`), par exemple `java` suivi de `Java`, `php` suivi de `PHP`, `python` suivi de `Python`. Les langages ajoutés y apparaissent aussi.

## 14. Ajouter un langage

Deux voies sont prévues.

### Par la CLI

```
python -m umlfactory.cli --add-language Go
```

ou, dans le menu des langages, « Autre langage… ». La CLI enchaîne les étapes décrites dans [05-llm-et-agents.md](05-llm-et-agents.md#ajouter-un-langage-flux-complet) : rédaction de la spécification par le modèle, vérification des outils (avec un guide d'installation en texte si un outil manque), approbation de la commande de contrôle, test sur les diagrammes de référence.

Avant de l'essayer, lire la note « Point à corriger » de [05-llm-et-agents.md](05-llm-et-agents.md#skills-skillspy-et-languagespy) : dans l'état actuel du code, l'étape de validation d'un brouillon échoue, car `DeclarativeGenerator` n'est pas importé dans `skills.py`.

### À la main

Un langage est un fichier dans `umlfactory/generators/`. Le README donne cet exemple, pour Kotlin :

```python
from ._declarative import CommandGenerator

class KotlinGenerator(CommandGenerator):
    language = "kotlin"
    display_name = "Kotlin"
    file_extensions = (".kt",)
    plan_rules = "one file per class, named <TypeName>.kt."
    style_rules = "Kotlin rules:\n- Use data classes where it fits...\n"
    tools = ("kotlinc",)
    build = ("kotlinc", "{file}")
    conformity_rules = "- An attribute is a `val` or `var` property.\n- An operation is a `fun name(` declaration.\n"
```

Au prochain démarrage de la pile, `deploy.plan_components` voit le module `kotlin` (`language_modules()`) et lance son agent. Le langage apparaît alors dans le menu. Pour le retirer, supprimer le fichier.

## 15. Lire un verdict de non-conformité

Quand le modèle trouve des éléments manquants, la CLI affiche par exemple :

```diff
  ⚠ Partiellement conforme au diagramme
      - méthode deposer() de Compte
      - attribut solde de Compte
```

Les éléments sont tirés du champ `missing` du verdict, avec 8 éléments au maximum, et seulement cinq sont affichés (`cli.conformity_lines`). Pour savoir où ils se trouvent, ouvrir le fichier concerné dans le dossier de sortie. Un verdict « non conforme » affiche le résumé du modèle sur une ligne.

## 16. Erreurs d'options

Quelques erreurs courantes et leur message :

```
python -m umlfactory.cli --bidule
```

donne `Option incorrecte : option inconnue : --bidule` suivi de « Pour voir les options : python -m umlfactory.cli --help ».

```
python -m umlfactory.cli --provider foo
```

donne `Option incorrecte : --provider : la valeur « foo » n'existe pas (choix possibles : 'openai', 'anthropic')`, suivi de la ligne d'aide.

```
python -m umlfactory.cli model.puml --lang cobol -o sortie
```

donne `Erreur : langage inconnu : cobol. Disponibles : java, php, python`.

Pour une erreur de configuration, par exemple une clé refusée par tous les fournisseurs, le message est « aucune clé d'API n'a été acceptée » suivi de la raison pour chaque clé (`providers.choose`), sans affichage de la clé en entier (`mask_key`).
