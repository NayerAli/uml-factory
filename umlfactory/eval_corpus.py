"""Diagrammes de référence pour valider un agent de langage : chacun cible une famille de cas courants.

Un agent « fiable » doit produire, pour chacun, du code qui compile (et, quand le langage le permet, qui s'instancie
et respecte le diagramme). Le score moyen décide si un langage ajouté est « validé » ou « expérimental ».
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reference:
    id: str
    title: str
    puml: str
    quick: bool = False          # inclus dans la validation rapide


CORPUS: tuple[Reference, ...] = (
    Reference("classes", "classes, attributs et association 1 → *", """@startuml
class Client {
  -nom : String
  -age : int
  +getNom() : String
}
class Commande {
  -numero : int
  -total : double
  +calculerTotal() : double
}
Client "1" --> "0..*" Commande : passe
@enduml
"""),
    Reference("heritage", "classe abstraite et héritage", """@startuml
abstract class Forme {
  -nom : String
  +aire() : double
}
class Cercle {
  -rayon : double
}
class Rectangle {
  -largeur : double
  -hauteur : double
}
Forme <|-- Cercle
Forme <|-- Rectangle
@enduml
""", quick=True),
    Reference("interfaces", "interfaces et réalisation multiple", """@startuml
interface Payable {
  +payer(montant : double)
}
interface Notifiable {
  +notifier()
}
class Facture {
  -montant : double
  +payer(montant : double)
  +notifier()
}
Payable <|.. Facture
Notifiable <|.. Facture
@enduml
""", quick=True),
    Reference("enumerations", "énumération et attribut typé", """@startuml
enum Statut {
  ACTIF
  INACTIF
  SUSPENDU
}
class Utilisateur {
  -email : String
  -statut : Statut
  +activer()
}
Utilisateur --> Statut
@enduml
"""),
    Reference("composition", "composition, agrégation et association bidirectionnelle", """@startuml
class Bibliotheque {
  -nom : String
}
class Livre {
  -titre : String
}
class Membre {
  -nom : String
}
class Emprunt {
  -date : String
}
Bibliotheque *-- "0..*" Livre : possede
Bibliotheque o-- "1..*" Membre : inscrit
Membre "1" -- "0..*" Emprunt : effectue
Emprunt --> Livre
@enduml
""", quick=True),
    Reference("visibilites", "visibilités, membres statiques et notes", """@startuml
class Compteur {
  -{static} total : int
  #valeur : int
  +incrementer()
  +{static} getTotal() : int
}
note right of Compteur
  Compte les appels et garde un total partagé
end note
@enduml
"""),
)


def select(quick: bool) -> list[Reference]:
    return [r for r in CORPUS if r.quick or not quick]
