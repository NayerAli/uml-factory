# umlfactory-llm

Transforme un diagramme PlantUML (`.puml`) en code source, **écrit par un LLM** (ni regex, ni gabarits).
Vous choisissez le langage cible dans une liste et le dossier de destination, puis vous suivez la génération en direct.

```
 python -m umlfactory.cli                     questions + progression en direct
          │  A2A (streaming)
          ▼
   Coordinateur (9200) ──MCP──► Serveur MCP (9000) : lit le .puml, écrit les sources
          │  A2A (streaming)
          └──► un agent par langage (ports 9101+)   plan → fichiers → vérification → corrections
                      │
                      └──► API compatible OpenAI (URL, modèle, clé dans .env)
```

Le LLM lit le diagramme, planifie les fichiers et écrit chacun. Le code est ensuite **vérifié sur votre machine** :
analyse statique, puis compilation, test de fumée (les classes sont instanciées) et conformité au diagramme
(héritage, attributs, opérations, relations). Enfin, le modèle relit le diagramme et le code, et rend un **verdict** :
conforme, partiellement conforme (avec la liste de ce qui manque) ou non conforme. Si quelque chose n'a pas pu être
vérifié (outil absent, délai dépassé), c'est écrit « Non vérifié » avec la raison. En cas d'erreur, le message repart au LLM pour correction (2 tours par défaut). Ce qui reste invalide
est signalé en avertissement, jamais caché. Un langage absent du menu peut être ajouté depuis le menu
(« Autre langage… »), voir plus bas.

## Structure

```
umlfactory-llm/
├── .env.example            à copier en .env (URL, modèle et clé de l'API)
├── requirements.txt
├── examples/model.puml
└── umlfactory/
    ├── cli.py              point d'entrée : questions + progression en direct
    ├── deploy.py           démarre la pile (MCP, coordinateur, un agent par langage)
    ├── coordinator.py      agent coordinateur (A2A) + skills de gestion des langages
    ├── skills.py           skills du coordinateur : créer un langage, vérifier ses outils, le valider
    ├── verify.py           vérification locale du code généré (exécution contrôlée)
    ├── umlmodel.py         lecture minimale du PlantUML, pour CONTRÔLER le code (ne génère rien)
    ├── languages.py        règles de sécurité des langages ajoutés + génération de leur fichier d'agent
    ├── eval_corpus.py      diagrammes de référence pour valider un agent de langage
    ├── mcp_server.py       serveur MCP (lecture du .puml, écriture des sources)
    ├── generators/         UN FICHIER PAR LANGAGE : java.py, python.py, php.py... (+ base.py commun)
    └── config.py, llm.py, ui.py, a2a_common.py, mcp_client.py, paths.py, textutil.py
└── tests/test_verify.py    python -m unittest discover -s tests
```

## Installation (une seule fois)

Pas d'installation du projet : seulement ses dépendances. Toutes les commandes se lancent **depuis le dossier
`umlfactory-llm`**.

```
python -m pip install -r requirements.txt
copy .env.example .env                 (Linux/macOS : cp .env.example .env)
```
Puis ouvrir `.env` et renseigner `OPENAI_API_URL`, `OPENAI_API_KEY` et `OPENAI_MODEL`.

> Écrire `python -m pip` plutôt que `pip` : cela évite le lanceur `pip.exe`, parfois bloqué par Windows Defender.

Pour Java, un JDK (commande `javac` disponible) permet de **compiler** le code généré et de renvoyer les erreurs au
LLM. Sans JDK, seules les parenthèses et accolades sont vérifiées.

## Démarrage rapide

```
python -m umlfactory.cli --spawn
```
Le programme démarre tout seul les composants, puis pose trois questions : le fichier `.puml`, le **langage cible**
(menu construit à partir des langages disponibles, avec l'entrée **« Autre langage… »**) et le dossier de
destination. Les composants s'arrêtent à la fin.

## Commande principale : `python -m umlfactory.cli`

```
python -m umlfactory.cli [fichier.puml] [options]
```

Tout ce qui n'est pas donné en option est demandé interactivement.

| Option | Ce que ça fait |
|---|---|
| `fichier.puml` | Le diagramme à convertir. Demandé si absent. |
| `-o`, `--out DOSSIER` | Où écrire le code généré. Demandé si absent. Le dossier est créé s'il n'existe pas. |
| `--lang java` | Langage cible, sans passer par le menu. Plusieurs possibles : `--lang java python` (génère les deux, chacun dans son sous-dossier). |
| `--list-languages` | Affiche les langages disponibles puis s'arrête. |
| `--add-language NOM` | Ajoute un langage cible (ex. `Go`) avant de générer : voir « Ajouter un langage depuis le menu ». |
| `--approve` | Autorise sans demander la commande de vérification d'un langage ajouté (usage sans terminal interactif). |
| `--ask "en Python"` | Au lieu de `--lang`, une phrase libre : le LLM en déduit le langage. `--lang` est plus fiable. |
| `--package com.exemple.banque` | Nom du package Java (ou du dossier-package Python). Sans lui, aucun package n'est utilisé. |
| `--instructions "ajoute des javadoc"` | Consigne libre ajoutée à la demande envoyée au LLM. |
| `--layout auto\|by-language\|flat` | Organisation des fichiers. `auto` (défaut) : un sous-dossier par langage **seulement s'il y en a plusieurs**. `by-language` : toujours un sous-dossier (`sortie/java/`). `flat` : tout directement dans le dossier de destination (un seul langage). |
| `--overwrite`, `-y` | Remplace sans demander les fichiers existants du même nom. Sans cette option, la CLI demande confirmation si le dossier n'est pas vide, et ne remplace jamais rien en silence. |
| `--spawn` | Démarre la pile pour la durée de la commande, puis l'arrête. À utiliser si `deploy` n'est pas déjà lancé. |
| `--coordinator URL` | Adresse du coordinateur si elle diffère de `COORDINATOR_URL` du `.env`. |

### Exemples

```
python -m umlfactory.cli --spawn                                              tout en interactif
python -m umlfactory.cli model.puml --lang java -o C:\projets\banque --spawn
python -m umlfactory.cli model.puml --lang python -o sortie --spawn
python -m umlfactory.cli model.puml --lang java python -o sortie --spawn      deux langages : sortie\java et sortie\python
python -m umlfactory.cli model.puml --lang java --package com.exemple.banque -o sortie --spawn
python -m umlfactory.cli model.puml --lang java --instructions "utilise des records quand c'est possible" -o sortie --spawn
python -m umlfactory.cli --list-languages --spawn
```

### Pendant la génération

La progression s'affiche en direct : une ligne par langage, une ligne par fichier avec son état (*en attente du
modèle*, *réflexion*, *écriture* avec un aperçu de la ligne en cours, *correction*, ✔ terminé) et le temps écoulé.
Si rien ne bouge pendant longtemps, c'est le modèle qui réfléchit : le spinner et le chronomètre continuent de tourner.
`Ctrl+C` interrompt. Sans terminal interactif (redirection), l'affichage se réduit à quelques lignes de texte.

Code de sortie : `0` tout s'est bien passé, `1` erreur ou échec d'un langage, `130` interrompu.

## Garder la pile allumée : `python -m umlfactory.deploy`

```
python -m umlfactory.deploy
```
À lancer dans un premier terminal et à laisser ouvert. Il démarre le serveur MCP, le coordinateur et **un agent par
langage** (un par fichier de `umlfactory/generators/`). Dans un second terminal, la CLI s'utilise **sans `--spawn`** et
démarre instantanément :

```
python -m umlfactory.cli model.puml --lang java -o sortie
```
`Ctrl+C` dans le premier terminal arrête tout. Les journaux de chaque composant sont dans le dossier `logs/`
(utile si quelque chose ne démarre pas).

## Lancer un composant à la main (usage avancé)

| Commande | Rôle | Défaut |
|---|---|---|
| `python -m umlfactory.mcp_server [--port N]` | Serveur MCP : lit le `.puml`, écrit les fichiers | port 9000 |
| `python -m umlfactory.coordinator [--port N]` | Agent coordinateur | port 9200 |
| `python -m umlfactory.generators java --port 9101` | Agent d'un langage (nom du fichier dans `generators/`) | à préciser |

Les agents n'écoutent que sur `127.0.0.1` (votre PC) : rien n'est exposé sur le réseau.

## Réglages du fichier `.env`

| Variable | Explication |
|---|---|
| `OPENAI_API_URL` | Adresse de l'API (`/v1` ajouté automatiquement s'il manque). Fonctionne avec tout serveur compatible OpenAI. |
| `OPENAI_API_KEY` | Votre clé d'API. Peut rester vide pour un serveur local sans authentification. |
| `OPENAI_MODEL` | Nom exact du modèle chez ce fournisseur. |
| `OPENAI_TIMEOUT` | Attente maximale (secondes) d'une réponse du modèle. Augmenter pour un modèle très lent. Défaut 600. |
| `OPENAI_CONCURRENCY` | Nombre de fichiers écrits en parallèle. Défaut 5 ; mettre 1 pour un petit modèle local. |
| `OPENAI_TEMPERATURE` | Créativité du modèle. Non envoyée par défaut (certains modèles la refusent). |
| `OPENAI_MAX_TOKENS` | Longueur maximale d'une réponse. Non envoyée par défaut. |
| `OPENAI_EXTRA` | Paramètres JSON ajoutés à chaque requête, ex. `{"reasoning_effort": "low"}`. |
| `MCP_URL`, `COORDINATOR_URL` | Adresses du serveur MCP et du coordinateur (défauts : ports 9000 et 9200). |
| `GENERATOR_PORT_RANGE` | Plage de ports où les agents de langage sont cherchés et lancés. Défaut `9101-9150`. |
| `GENERATOR_AGENT_URLS` | Agents de langage supplémentaires hors de cette plage (autre machine), séparés par des virgules. |

## Vérification du code généré

Après la génération, chaque agent vérifie son code **sur votre machine**, en quatre paliers (budget total : 10 s) :

| Palier | Contrôle | Poids |
|---|---|---|
| Statique | syntaxe, équilibrage, packages cohérents | 10 |
| Compilation | `javac` (Java) ; import de chaque module (Python) | 40 |
| Test de fumée | chaque classe concrète est instanciée avec des valeurs par défaut (aucune opération métier n'est appelée) | 25 |
| Conformité | héritage, interfaces, attributs, opérations, relations et collections du diagramme (par réflexion) | 25 |

Les erreurs de compilation, d'initialisation ou de conformité repartent au LLM (boucle de correction). Les avertissements
de cardinalité sont affichés mais ne bloquent pas. Pendant la génération, l'interface affiche l'étape de vérification en
cours **dès qu'elle dépasse 1 seconde**, puis le verdict de conformité (`✔ Conforme au diagramme`).

Si un outil manque sur l'appareil (par exemple `javac`), la CLI le signale avant la génération : le code est généré mais
affiché « non exécuté ». Si le budget est dépassé, le résultat est « non vérifié », jamais « réussi ».

## Ajouter un langage depuis le menu

Menu **« Autre langage… »** (ou `--add-language Go`). Chaque étape est affichée :

1. **Brouillon** : le LLM rédige des *données* (règles de génération, outils requis, commande de vérification),
   gardées dans `umlfactory/.drafts/` le temps de l'opération. Il n'écrit aucun code Python et n'exécute rien.
2. **Outils sur l'appareil** : les exécutables nécessaires sont cherchés sur votre machine. S'ils manquent, le LLM écrit
   un **guide d'installation en texte** (`umlfactory/.drafts/<langage>.install.txt`) ; rien n'est installé par lui.
   Suivez le guide, puis revenez : la CLI revérifie.
3. **Validation de la commande** : la commande de vérification est affichée et vous devez l'autoriser. Elle est limitée à
   une liste de compilateurs connus, sans shell.
4. **Validation de l'agent** : il convertit des diagrammes de référence (héritage, interfaces, énumérations, relations,
   visibilités…), le code est compilé et comparé au diagramme (un score interne, seuil **75/100**, décide). En dessous, le langage est
   « expérimental » et vous décidez de le garder ou non. Les règles de génération (jamais la commande) peuvent être
   reformulées une fois par le LLM à partir des échecs.
5. **Fichier d'agent créé** : `umlfactory/generators/<langage>.py`, généré depuis un gabarit fixe (une sous-classe de
   `CommandGenerator` avec quelques attributs). C'est le même format que `java.py` et `python.py`, modifiable à la main.
   Le langage est **disponible** immédiatement dans le menu, et lancé automatiquement par `deploy` ensuite.

Pour les langages ajoutés, la vérification porte sur la compilation ou la syntaxe (le test de fumée et la conformité
sont propres à Java et Python). Les fichiers de projet qui exécutent du code à la compilation (`build.rs`, `*.csproj`,
`package.json`, scripts) sont refusés. Pour retirer un langage (ajouté ou intégré, Java et Python compris) : supprimer son fichier dans `umlfactory/generators/`. Le noyau n'a pas à changer.

## Tests

```
python -m unittest discover -s tests
```
Les tests Java sont ignorés si `javac` n'est pas disponible.

## Ajouter un langage à la main (code)

Créer **un seul fichier** `umlfactory/generators/<langage>.py` (le nom du fichier est l'identifiant du langage) :

```python
from .base import BaseGeneratorAgent, Validation

class KotlinGenerator(BaseGeneratorAgent):
    language = "kotlin"
    display_name = "Kotlin"
    file_extensions = (".kt",)
    plan_rules = "one file per class, named <TypeName>.kt."
    style_rules = "Kotlin rules:\n- Use data classes where it fits...\n"

    def validate(self, files: dict[str, str]) -> Validation:
        return Validation()          # contrôles statiques ; l'exécution se branche via runtime() (voir verify.py)
```
Au prochain `python -m umlfactory.deploy` (ou `--spawn`), l'agent est lancé automatiquement et **Kotlin apparaît
dans le menu**, sans modifier le coordinateur ni la CLI.

## Problèmes courants

| Symptôme | Solution |
|---|---|
| `pip` ne fait rien / bloqué par Windows | Utiliser `python -m pip install -r requirements.txt`. |
| `ModuleNotFoundError: No module named ...` | Dépendances absentes de ce Python : lancer `python -m pip install -r requirements.txt`. |
| `coordinateur injoignable` | La pile n'est pas lancée : ajouter `--spawn` ou lancer `python -m umlfactory.deploy`. |
| `aucun agent de langage joignable` | Aucun fichier de langage démarré : voir `logs/` et la sortie de `deploy`. |
| Erreur 401 / 404 de l'API | Vérifier `OPENAI_API_KEY`, `OPENAI_API_URL` et `OPENAI_MODEL` dans `.env`. |
| Dossier de destination « non vide » | Choisir un autre dossier, ou confirmer / utiliser `--overwrite`. |
| `javac introuvable sur cet appareil` | Installer un JDK pour compiler et tester le Java généré (facultatif : sinon le code est généré mais « non exécuté »). |
| `code non exécuté : appels sensibles détectés` | Le code généré utilise des processus, du réseau ou des fichiers : il n'est pas exécuté et le LLM doit le corriger. |
| `non vérifié` / délai dépassé | La vérification a dépassé 10 secondes (machine lente ou boucle infinie). |
| Langage ajouté en « brouillon » | Un outil manque : suivre le guide `.install.txt`, puis relancer `--add-language`. |
| Avertissement sur un fichier à la fin | Le LLM n'a pas réussi à corriger ce fichier : le relire, ou relancer la génération. |

## Sécurité

Tout est en local (127.0.0.1). Le contenu du diagramme est traité comme une donnée dans les prompts. Les noms de
fichiers venant du LLM sont validés (pas de `..`, pas de chemin absolu).
Le serveur MCP ne remplace jamais un fichier existant au contenu différent sans autorisation.
`.env` (clé d'API) est dans `.gitignore`.

**Exécution du code généré.** Pour le vérifier, le code généré est compilé et instancié sur votre machine. Il n'y a
**pas d'isolation système** (ni Docker ni bac à sable) : le code tourne avec vos droits, car tout est local et le
diagramme est supposé de confiance. Les garde-fous sont volontairement simples :

- dossier temporaire jetable, jamais votre projet ;
- délai strict (10 s au total), puis « non vérifié » ;
- environnement nettoyé : ni clé d'API ni variable du `.env` ne sont transmises au code ;
- scan préalable des appels sensibles (processus, réseau, fichiers, environnement) : s'il y en a, rien n'est exécuté ;
- seules des instanciations sont faites (jamais d'opération métier, jamais de `main`) ;

Pour un langage ajouté depuis le menu, le LLM ne produit que des données ; la commande de vérification qu'il propose
est restreinte à une liste de compilateurs, sans shell, et doit être autorisée par l'utilisateur.
