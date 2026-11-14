=========================================
Analyse de l'architecture UML Factory
=========================================

Avant d'ajouter le support Rust, une étude du mécanisme de découverte
des générateurs a été réalisée.

Le premier problème rencontré était le message :

    Erreur : langage inconnu : rust.
    Disponibles : java, php, python

Cela signifiait que le fichier rust.py n'était pas pris en compte
par UML Factory.

Après analyse du code source, les points suivants ont été identifiés :

1. Héritage autorisé
--------------------

L'architecture du projet permet d'ajouter un nouveau langage en créant
un simple générateur héritant de la classe :

    CommandGenerator

Le fichier générateur n'a donc pas besoin d'implémenter toute la
logique complexe utilisée par Java.

Cela permet d'ajouter rapidement un nouveau langage sans modifier
le noyau de l'application.

2. Découverte automatique des générateurs
------------------------------------------

L'analyse du mécanisme de chargement montre que les générateurs sont
détectés automatiquement lorsqu'ils héritent indirectement de :

    BaseGeneratorAgent

Or :

    CommandGenerator
        ↓
    BaseGeneratorAgent

Ainsi, un générateur Rust basé sur CommandGenerator est automatiquement
compatible avec le système de découverte du projet.

Aucune modification du cœur de UML Factory n'est nécessaire.

3. Cause probable des erreurs de détection
-------------------------------------------

Si le langage Rust n'apparaît pas dans la liste des langages disponibles,
les causes les plus probables sont :

    - erreur de syntaxe dans rust.py
    - erreur d'import dans rust.py
    - fichier placé dans un mauvais dossier
    - nom de classe incorrect

Le fichier doit être placé exactement dans :

    umlfactory/generators/rust.py

4. Choix de conception
----------------------

Deux approches étaient possibles :

    - reproduire le générateur Java complet
    - créer un générateur déclaratif

Le générateur Java contient plusieurs centaines de lignes de code
comprenant :

    - compilation
    - vérification UML
    - tests automatiques
    - analyse de conformité

Pour une extension simple et maintenable, le choix retenu a été un
générateur déclaratif basé sur :

    CommandGenerator

Cette solution est pleinement compatible avec l'architecture
prévue par UML Factory pour l'ajout de nouveaux langages.

5. Implémentation du support Rust
---------------------------------

Un nouveau fichier a été ajouté :

    umlfactory/generators/rust.py

Le générateur définit notamment :

    language = "rust"
    display_name = "Rust"

ainsi que :

    - les règles de génération UML → Rust
    - les règles de conformité
    - les extensions de fichiers (.rs)
    - la commande de compilation rustc

Le langage Rust est alors reconnu automatiquement par UML Factory.

6. Vérification
---------------

Après ajout du générateur :

    python -c "from umlfactory.generators import built_in_ids; print(sorted(built_in_ids()))"

Résultat attendu :

    ['java', 'php', 'python', 'rust']

L'apparition de "rust" dans cette liste confirme que l'extension est
correctement chargée par le mécanisme de découverte automatique.

=========================================
Contribution personnelle
=========================================

Travail réalisé :

    - analyse de l'architecture UML Factory ;
    - étude du mécanisme de découverte des générateurs ;
    - conception du générateur Rust ;
    - définition des règles UML → Rust ;
    - intégration du langage sans modification du noyau ;
    - validation de la détection automatique du nouveau langage.

Fichier dont j'ai eu l'entière responsabilité :

    umlfactory/generators/rust.py