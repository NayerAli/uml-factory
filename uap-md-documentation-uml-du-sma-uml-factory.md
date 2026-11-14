# Les diagrammes du projet UmlFactory

---

## Sommaire

1. [Vue d'ensemble du SMA](#1-vue-densemble-du-sma)
2. [Diagramme de composants](#2-diagramme-de-composants)
3. [Diagramme de déploiement](#3-diagramme-de-déploiement)
4. [Diagramme de paquetages](#4-diagramme-de-paquetages)
5. [Diagramme de classes](#5-diagramme-de-classes)
6. [Diagramme d'objets](#6-diagramme-dobjets)
7. [Diagramme de cas d'utilisation](#7-diagramme-de-cas-dutilisation)
8. [Diagramme de séquence — génération nominale](#8-diagramme-de-séquence--génération-nominale)
9. [Diagramme de séquence — vérification et verdict](#9-diagramme-de-séquence--vérification-et-verdict)
10. [Diagramme de séquence — ajout d'un langage](#10-diagramme-de-séquence--ajout-dun-langage)
11. [Diagramme de communication](#11-diagramme-de-communication)
12. [Diagramme d'activité — ajout d'un langage](#12-diagramme-dactivité--ajout-dun-langage)
13. [Diagramme d'états — fichier généré](#13-diagramme-détats--fichier-généré)
14. [Diagramme d'états — la pile](#14-diagramme-détats--la-pile)
15. [Diagramme d'états — verdict de conformité](#15-diagramme-détats--verdict-de-conformité)
16. [Chronologie d'une exécution](#16-chronologie-dune-exécution)
17. [Carte mentale de l'architecture](#17-carte-mentale-de-larchitecture)

---

## 1. Vue d'ensemble du SMA

La CLI (`python -m umlfactory.cli`) allume la pile, délègue au coordinateur (A2A), qui lit le `.puml` via le serveur MCP et fait écrire le code par les agents de langage, eux-mêmes clients de l'API du modèle d'IA.

```mermaid
flowchart LR
    U(["python -m umlfactory.cli"]) -->|"A2A"| C["Coordinateur<br/>port 9200"]
    C -->|"MCP"| M["Serveur MCP<br/>port 9000<br/>lit le .puml, écrit les sources"]
    C -->|"A2A"| A["Un agent par langage<br/>ports 9101 et suivants"]
    A -->|"plan, fichiers, contrôles,<br/>corrections, verdict"| L[("API du modèle<br/>OpenAI ou Anthropic")]
```

**Explication** : aucun gabarit ni regex pour générer : le modèle d'IA écrit un plan de fichiers puis chaque fichier. La fiabilité vient d'une boucle de contrôle (compilation, comparaison des noms avec le diagramme, correction, verdict).

---

## 2. Diagramme de composants

**Explication** : vue logique. La CLI orchestre ; le coordinateur répartit le travail et gère les langages ; le serveur MCP est la seule porte d'entrée/sortie des fichiers ; chaque agent de langage encapsule les prompts et la vérification de son langage. Les agents sont interchangeables : ajouter un langage = ajouter un fichier dans `umlfactory/generators/`, sans toucher au noyau.

```mermaid
flowchart TD
    subgraph CORE["Noyau (umlfactory)"]
        CLI["cli.py<br/>questions, progression, options"]
        DEP["deploy.py<br/>démarre / arrête la pile"]
        COORD["coordinator.py<br/>agent coordinateur A2A"]
        SKILLS["skills.py<br/>créer, vérifier, valider un langage"]
        PROV["providers.py<br/>test des clés, choix du fournisseur"]
        CONF["config.py<br/>lecture du .env, adresses"]
        VERIFY["verify.py<br/>contrôle local du code généré"]
        UMLM["umlmodel.py<br/>lecture PlantUML pour le contrôle"]
        LANG["languages.py<br/>sécurité des langages ajoutés"]
        EVAL["eval_corpus.py<br/>diagrammes de référence"]
        MCPS["mcp_server.py<br/>serveur MCP"]
        GEN["generators/<br/>base, planning, prompts, repair, _declarative"]
        AGJ["generators/java.py"]
        AGP["generators/python.py"]
        AGPHP["generators/php.py"]
        LLM["llm.py"]
        A2AC["a2a_common.py"]
        MCPC["mcp_client.py"]
        UI["ui/ term, progress, menus"]
    end
    subgraph EXT["Externe"]
        ENV[(".env")]
        API[("API du modèle<br/>OpenAI / Anthropic")]
        FS[("examples/, sortie/, logs/")]
    end
    CLI --> DEP
    CLI --> PROV
    CLI --> COORD
    CLI --> UI
    DEP --> MCPS
    DEP --> COORD
    DEP --> GEN
    COORD --> MCPC
    COORD --> A2AC
    COORD --> SKILLS
    SKILLS --> LANG
    SKILLS --> EVAL
    GEN --> LLM
    GEN --> A2AC
    MCPS --- FS
    LLM --> API
    CONF --- ENV
    VERIFY --> UMLM
    COORD --> VERIFY
```

---

## 3. Diagramme de déploiement

**Explication** : vue physique. Tout tourne sur le poste de l'utilisateur, sur `127.0.0.1` uniquement. La CLI démarre les trois familles de processus (ou réutilise une pile déjà allumée via `.umlfactory-stack.json`), et les agents de langage appellent l'API du modèle d'IA sur Internet. Les journaux vont dans `logs/`.

```mermaid
flowchart TD
    subgraph PC["Poste de l'utilisateur"]
        subgraph T1["Terminal : python -m umlfactory.cli"]
            CLI["CLI<br/>cli.py"]
        end
        subgraph P9000["Processus HTTP : 127.0.0.1:9000"]
            MCP["Serveur MCP<br/>mcp_server.py<br/>lit le .puml, écrit les sources"]
        end
        subgraph P9200["Processus HTTP : 127.0.0.1:9200"]
            CO["Coordinateur A2A<br/>coordinator.py"]
        end
        subgraph P9101["Processus HTTP : 127.0.0.1:9101"]
            AGJ["Agent Java"]
        end
        subgraph P9102["Processus HTTP : 127.0.0.1:9102"]
            AGP["Agent Python"]
        end
        subgraph P9103["Processus HTTP : 127.0.0.1:9103"]
            AGPHP["Agent PHP"]
        end
        JDK["JDK local<br/>javac, java"]
        FILES[("Fichiers<br/>examples/ · sortie/ · logs/<br/>.env · .umlfactory-stack.json")]
    end
    NET[("Internet : API du modèle<br/>OpenAI ou Anthropic")]
    CLI -->|"démarre / réutilise / arrête"| MCP
    CLI -->|"démarre / réutilise / arrête"| CO
    CLI -->|"démarre / réutilise / arrête"| AGJ
    CLI -->|"démarre / réutilise / arrête"| AGP
    CLI -->|"démarre / réutilise / arrête"| AGPHP
    CO -->|"MCP"| MCP
    CO -->|"A2A : plan, fichiers, verdict"| AGJ
    CO -->|"A2A : plan, fichiers, verdict"| AGP
    CO -->|"A2A : plan, fichiers, verdict"| AGPHP
    AGJ -->|"HTTPS"| NET
    AGP -->|"HTTPS"| NET
    AGPHP -->|"HTTPS"| NET
    AGJ -->|"javac / java"| JDK
    MCP --- FILES
    CLI --- FILES
```

---

## 4. Diagramme de paquetages

**Explication** : organisation du code. `umlfactory` est le paquet unique ; `generators` porte un fichier par langage plus le code commun (`base`, `planning`, `prompts`, `repair`, `_declarative`) ; `ui` isole l'affichage. Les dépendances vont des agents vers le commun, jamais entre agents.

```mermaid
flowchart TD
    subgraph PKG["umlfactory"]
        subgraph ENTRY["points d'entrée"]
            CLIM["cli.py"]
            DEPM["deploy.py"]
        end
        subgraph ORCH["orchestration"]
            COORDM["coordinator.py"]
            SKILLSM["skills.py"]
            LANGM["languages.py"]
            EVALM["eval_corpus.py"]
        end
        subgraph INFRA["infrastructure"]
            CONF["config.py"]
            PROV["providers.py"]
            LLM["llm.py"]
            A2AC["a2a_common.py"]
            MCPC["mcp_client.py"]
            PATHS["paths.py"]
            TXT["textutil.py"]
        end
        subgraph DATAM["données et contrôle"]
            UMLM["umlmodel.py"]
            VERIFYM["verify.py"]
            MCPSM["mcp_server.py"]
        end
        subgraph GENM["generators"]
            BASE["base.py"]
            PLAN["planning.py"]
            PROMPTS["prompts.py"]
            REPAIR["repair.py"]
            DECL["_declarative.py"]
            JAVA["java.py"]
            PY["python.py"]
            PHP["php.py"]
        end
        subgraph UIM["ui"]
            TERM["term.py"]
            PROG["progress.py"]
            MENUS["prompts.py"]
        end
    end
    CLIM --> DEPM
    CLIM --> COORDM
    CLIM --> UIM
    DEPM --> COORDM
    DEPM --> GENM
    COORDM --> DATAM
    COORDM --> SKILLSM
    SKILLSM --> LANGM
    SKILLSM --> EVALM
    JAVA --> DECL
    PY --> DECL
    PHP --> DECL
    DECL --> BASE
    BASE --> PLAN
    BASE --> PROMPTS
    BASE --> REPAIR
    BASE --> LLM
    BASE --> A2AC
    MCPSM --> UMLM
    VERIFYM --> UMLM
```

---

## 5. Diagramme de classes

**Explication** : conception objet. `BaseGeneratorAgent` porte la mécanique commune d'un agent de langage (plan, écriture, réparation, verdict) ; `_declarative.CommandGenerator` permet de définir un langage en quelques attributs (comme `KotlinGenerator` ci-dessous, exemple du readme) ; `JavaGenerator` et `PythonGenerator` ajoutent leur vérification d'exécution propre via `runtime()`.

```mermaid
classDiagram
    class Coordinator {
        +int port
        +dispatch(task)
        +listLanguages() List~String~
        +addLanguage(String name)
    }
    class McpServer {
        +readPuml(String path) UmlModel
        +writeFiles(List~File~ files)
    }
    class BaseGeneratorAgent {
        <<abstract>>
        +String language*
        +plan(UmlModel model) FilePlan
        +writeFile(FilePlan f) String
        +repair(String code, List~String~ errors) String
        +verdict(UmlModel model, String code) Verdict
        +runtime() Optional~RuntimeCheck~
    }
    class CommandGenerator {
        <<abstract>>
        +String language
        +String display_name
        +Tuple file_extensions
        +String plan_rules
        +String style_rules
        +Tuple tools
        +Tuple build
        +String conformity_rules
    }
    class JavaGenerator {
        +runtime() javac puis java
    }
    class PythonGenerator {
        +runtime() import en sous-processus
    }
    class PhpGenerator {
        +build = php -l
    }
    class KotlinGenerator {
        language = "kotlin"
        tools = kotlinc
    }
    class UmlModel {
        +List~UmlElement~ classes
        +List~Relation~ relations
        +Map inheritance
    }
    class Verifier {
        +check(String code) List~String~
        +compile(String code) CompileResult
        +compareNames(UmlModel m, String code) List~Gap~
    }
    class LlmClient {
        +String complete(List~Message~ msgs)
    }
    class Provider {
        <<abstract>>
        +testKey() bool
    }
    class OpenAiProvider
    class AnthropicProvider
    class SkillManager {
        +draft(String language) Draft
        +checkTools(Draft d) List~Tool~
        +validate(Draft d) Score
        +writeAgentFile(Draft d)
    }

    Coordinator --> McpServer : MCP
    Coordinator --> BaseGeneratorAgent : A2A
    Coordinator --> Verifier
    Coordinator --> SkillManager
    BaseGeneratorAgent --> LlmClient
    BaseGeneratorAgent --> UmlModel
    Verifier --> UmlModel
    CommandGenerator --|> BaseGeneratorAgent
    JavaGenerator --|> CommandGenerator
    PythonGenerator --|> CommandGenerator
    PhpGenerator --|> CommandGenerator
    KotlinGenerator --|> CommandGenerator
    LlmClient --> Provider
    OpenAiProvider --|> Provider
    AnthropicProvider --|> Provider
```

---

## 6. Diagramme d'objets

**Explication** : instantané pendant une génération Java de `examples/model.puml` : le coordinateur a délégué à l'agent Java (port 9101), deux fichiers sont en cours, l'un en correction après un échec de compilation `javac`.

```mermaid
classDiagram
    direction LR
    class task["tâche 7 : Task"] {
        model = "examples/model.puml"
        language = "java"
        outDir = "sortie/java"
    }
    class plan["planJava : FilePlan"] {
        files = 4
        package = "com.exemple.banque"
    }
    class f1["Client.java : GeneratedFile"] {
        status = "terminé"
        repairs = 0
    }
    class f2["Compte.java : GeneratedFile"] {
        status = "correction"
        repairs = 1
        error = "accolade manquante"
    }
    class agentJ["agentJava : JavaGenerator"] {
        port = 9101
        tools = "javac, java"
    }
    class verdict["verdict : Verdict"] {
        state = "en attente"
    }
    class llmC["llm : LlmClient"] {
        provider = "anthropic"
        model = "claude-haiku-5-5"
    }
    task --> plan
    task --> agentJ
    plan --> f1
    plan --> f2
    agentJ --> llmC
    agentJ --> verdict
```

---

## 7. Diagramme de cas d'utilisation

**Explication** : ce que l'utilisateur fait avec le SMA. Le cas principal « Convertir un diagramme » inclut le choix du fournisseur de modèle, le démarrage de la pile et la vérification du code. « Ajouter un langage » (menu « Autre langage… » ou `--add-language`) et la gestion de la pile (`--keep-running`, `--stop`, `deploy`) sont des cas séparés.

```mermaid
flowchart LR
    U(["Utilisateur"])
    subgraph SYS["Système UML Factory"]
        UC1["Convertir un diagramme .puml<br/>en code source"]
        UC2["Choisir le ou les langages cibles"]
        UC3["Choisir le fournisseur du modèle<br/>(OpenAI / Anthropic / local)"]
        UC4["Démarrer / arrêter la pile<br/>(--keep-running, --stop, deploy)"]
        UC5["Vérifier le code généré<br/>(compilation, comparaison, verdict)"]
        UC6["Corriger le code via le modèle"]
        UC7["Ajouter un nouveau langage"]
        UC8["Consulter les langages disponibles<br/>(--list-languages)"]
        UC9["Passer des instructions libres<br/>(--ask, --instructions)"]
    end
    U --> UC1
    U --> UC4
    U --> UC7
    U --> UC8
    UC1 -.->|include| UC2
    UC1 -.->|include| UC3
    UC1 -.->|include| UC4
    UC1 -.->|include| UC5
    UC1 -.->|extend| UC9
    UC5 -.->|extend| UC6
    UC7 -.->|extend| UC1
```

---

## 8. Diagramme de séquence — génération nominale

**Explication** : déroulé complet d'une conversion. La CLI teste les clés du `.env`, allume la pile, envoie la demande au coordinateur (A2A). Le coordinateur lit le `.puml` via MCP, l'agent de langage demande un plan au modèle, fait écrire chaque fichier, puis le coordinateur fait vérifier le code et rend le verdict. La CLI écrit les fichiers et éteint la pile.

```mermaid
sequenceDiagram
    participant U as Utilisateur
    participant CLI as cli.py
    participant C as Coordinateur (9200)
    participant M as Serveur MCP (9000)
    participant A as Agent Java (9101)
    participant L as API du modèle

    U->>CLI: python -m umlfactory.cli model.puml --lang java -o sortie
    CLI->>CLI: lecture du .env, test des clés
    CLI->>C: démarrage (ou réutilisation) de la pile
    CLI->>C: A2A : générer java dans sortie/
    C->>M: MCP : lire le .puml
    M-->>C: modèle UML
    C->>A: A2A : plan + modèle
    A->>L: demande du plan de fichiers
    L-->>A: plan (4 fichiers)
    loop pour chaque fichier
        A->>L: demande du code du fichier
        L-->>A: code source
        A->>A: contrôles + écriture (via MCP)
    end
    C->>A: vérification et verdict
    A-->>C: fichiers + verdict
    C-->>CLI: résultat
    CLI-->>U: progression en direct, verdict affiché
    CLI->>C: arrêt de la pile (sauf --keep-running)
```

---

## 9. Diagramme de séquence — vérification et verdict

**Explication** : zoom sur la boucle de fiabilité. Chaque fichier subit les contrôles du langage, la compilation (budget 10 s), la comparaison des noms avec le diagramme, puis jusqu'à 2 tours de correction par le modèle. Enfin le modèle rend son verdict de conformité.

```mermaid
sequenceDiagram
    participant C as Coordinateur
    participant V as verify.py
    participant A as Agent de langage
    participant L as API du modèle

    C->>V: contrôler le code généré
    V->>V: contrôles du langage (accolades, syntaxe, imports)
    V->>V: compilation (javac / import / php -l, budget 10 s)
    V->>V: comparaison des noms avec le diagramme
    alt erreurs détectées
        loop 2 tours au maximum
            V-->>A: erreurs du fichier
            A->>L: corriger le fichier
            L-->>A: code corrigé
            A->>V: re-vérifier
        end
    end
    V-->>C: constats (erreurs restantes en avertissement)
    C->>L: diagramme + code + constats
    L-->>C: verdict (conforme / partiel / non conforme / non vérifié)
    C-->>C: affichage du verdict et des manques
```

---

## 10. Diagramme de séquence — ajout d'un langage

**Explication** : le SMA se réécrit lui-même partiellement : le modèle rédige des **données** (jamais du code Python), la CLI vérifie les outils, demande l'autorisation pour la commande de vérification, teste l'agent sur les diagrammes de référence (score 75/100 requis), puis génère le fichier d'agent depuis un gabarit fixe.

```mermaid
sequenceDiagram
    participant U as Utilisateur
    participant CLI as cli.py / skills.py
    participant L as API du modèle
    participant FS as umlfactory/generators/

    U->>CLI: --add-language Go
    CLI->>L: rédiger les données du langage
    L-->>CLI: brouillon (règles, outils, commande, consignes)
    CLI->>FS: brouillon dans .drafts/
    CLI->>CLI: chercher les outils sur l'appareil
    alt outil manquant
        CLI->>FS: guide d'installation .install.txt
        CLI-->>U: suivre le guide puis revenir
    end
    CLI-->>U: commande de vérification à autoriser
    U->>CLI: autorisation
    CLI->>CLI: test sur les diagrammes de référence
    alt score moyen au moins 75/100
        CLI->>FS: génération de go.py (gabarit fixe)
        CLI-->>U: langage validé, disponible dans le menu
    else score insuffisant
        CLI->>L: reformulation des règles (une fois)
        CLI-->>U: langage expérimental, à garder ou non
    end
```

---

## 11. Diagramme de communication

**Explication** : le scénario nominal vu comme collaboration numérotée : qui parle à qui, dans quel ordre.

```mermaid
flowchart LR
    CLI[CLI] --> C[Coordinateur]
    C --> M[Serveur MCP]
    C --> A[Agent Java]
    A --> L[API du modèle]
    CLI -- "1 : générer java" --> C
    C -- "2 : lire le .puml" --> M
    M -- "3 : modèle UML" --> C
    C -- "4 : plan + modèle" --> A
    A -- "5 : plan de fichiers" --> L
    L -- "6 : plan" --> A
    A -- "7 : code de chaque fichier" --> L
    C -- "8 : vérifier + verdict" --> A
    A -- "9 : fichiers + verdict" --> C
    C -- "10 : résultat" --> CLI
```

---

## 12. Diagramme d'activité — ajout d'un langage

**Explication** : version activité de la section 10, avec les deux points de décision (outils présents, score de validation) et la boucle de reformulation unique des règles.

```mermaid
flowchart TD
    S([Début]) --> A["Brouillon par le modèle<br/>(règles, outils, commande, consignes)"]
    A --> B{"Outils présents<br/>sur l'appareil ?"}
    B -->|non| C["Guide d'installation en texte<br/>.install.txt, rien n'est installé"]
    C --> B
    B -->|oui| D["Afficher la commande de vérification"]
    D --> E{"Utilisateur autorise ?"}
    E -->|non| F(["Abandon : langage non ajouté"])
    E -->|oui| G["Test sur les diagrammes de référence<br/>(rapide ou complet)"]
    G --> H{"Score moyen<br/>au moins 75/100 ?"}
    H -->|non| I{"Reformulation des règles<br/>déjà utilisée ?"}
    I -->|non| A
    I -->|oui| J["Langage expérimental"]
    J --> K{"L'utilisateur garde ?"}
    K -->|non| F
    K -->|oui| L2["Fichier d'agent créé"]
    H -->|oui| L2
    L2 --> M(["Fin : langage dans le menu"])
```

---

## 13. Diagramme d'états — fichier généré

**Explication** : les états affichés en direct par la CLI pour chaque fichier, avec la boucle de correction limitée à 2 tours.

```mermaid
stateDiagram-v2
    [*] --> EnAttente : fichier planifié
    EnAttente --> Reflexion : requête envoyée au modèle
    Reflexion --> Ecriture : code reçu
    Ecriture --> Controle : contrôles du langage + compilation
    Controle --> Termine : aucun problème
    Controle --> Correction : erreurs détectées
    Correction --> Controle : code corrigé renvoyé
    Correction --> Avertissement : 2 tours épuisés, erreurs restantes
    Termine --> [*]
    Avertissement --> [*]
```

---

## 14. Diagramme d'états — la pile

**Explication** : les trois situations documentées du cycle de vie de la pile, pilotées par `COORDINATOR_URL` (démarrage automatique seulement si l'adresse est locale), `--keep-running`, `--stop` et `deploy.py`.

```mermaid
stateDiagram-v2
    [*] --> Eteinte
    Eteinte --> Demarrage : commande CLI, adresse locale
    Demarrage --> Erreur : port occupé ou démarrage impossible
    Erreur --> [*] : message clair + journal dans logs/
    Demarrage --> Allumee : tous les composants répondent
    Allumee --> Tache : conversion en cours
    Tache --> Allumee : fin de la conversion
    Allumee --> Eteinte : arrêt automatique (cas normal)
    Allumee --> Gardee : --keep-running ou deploy
    Gardee --> Tache : conversion suivante, démarrage immédiat
    Gardee --> Eteinte : --stop ou Ctrl+C
    Eteinte --> Reutilisee : pile déjà allumée détectée
    Reutilisee --> Tache : la CLI n'éteint pas une pile qu'elle n'a pas allumée
```

---

## 15. Diagramme d'états — verdict de conformité

**Explication** : les quatre verdicts possibles et leurs conditions, tels que définis dans le readme.

```mermaid
stateDiagram-v2
    [*] --> Evaluation : diagramme + code + constats envoyés au modèle
    Evaluation --> Conforme : rien ne manque
    Evaluation --> Partiel : éléments manquants listés (8 au maximum)
    Evaluation --> NonConforme : le code ne représente pas le diagramme
    Evaluation --> NonVerifie : diagramme illisible ou modèle sans réponse
    Conforme --> [*]
    Partiel --> [*]
    NonConforme --> [*]
    NonVerifie --> [*]
```

---

## 16. Chronologie d'une exécution

**Explication** : vue temporelle condensée d'une conversion Java, utile en soutenance.

```mermaid
timeline
    title python -m umlfactory.cli model.puml --lang java -o sortie
    Lancement : lecture du .env : test des clés : choix du fournisseur
    Pile : démarrage MCP 9000, coordinateur 9200, agents 9101+ : sonde de disponibilité
    Génération : lecture du .puml via MCP : plan demandé au modèle : écriture de chaque fichier
    Vérification : compilation : comparaison des noms : boucle de correction
    Verdict : conforme, partiel, non conforme ou non vérifié
    Fin : fichiers écrits dans sortie/ : arrêt de la pile
```

---

## 17. Carte mentale de l'architecture

**Explication** : synthèse visuelle de tout le projet.

```mermaid
mindmap
  root((UML Factory))
    CLI
      menus interactifs
      options --lang, --ask, --package
      --keep-running et --stop
    Pile locale
      Serveur MCP 9000
      Coordinateur 9200
      Agents de langage 9101+
    Génération par IA
      plan de fichiers
      écriture par fichier
      boucle de correction
    Vérification
      compilation javac, php -l
      comparaison des noms
      verdict de conformité
    Langages
      java, python, php intégrés
      ajout par --add-language
      score de validation 75/100
    Fournisseurs
      OpenAI ou compatible
      Anthropic
      serveur local sans clé
```

---

## Récapitulatif des vues UML couvertes

| Vue UML | Diagramme | Section |
| --- | --- | --- |
| Statique — structure logique | Composants | 2 |
| Statique — structure physique | Déploiement | 3 |
| Statique — organisation du code | Paquetages | 4 |
| Statique — conception objet | Classes | 5 |
| Statique — instantané | Objets | 6 |
| Dynamique — besoins | Cas d'utilisation | 7 |
| Dynamique — interactions | Séquences (nominal, vérification, ajout de langage) | 8, 9, 10 |
| Dynamique — interactions | Communication / collaboration | 11 |
| Dynamique — flux | Activité (ajout d'un langage) | 12 |
| Dynamique — machines à états | Fichier généré, pile, verdict | 13, 14, 15 |
| Transverses | Chronologie, carte mentale | 16, 17 |