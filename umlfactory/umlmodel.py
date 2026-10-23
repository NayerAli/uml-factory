"""Lecture minimale d'un diagramme de classes PlantUML, pour CONTRÔLER le code généré.

Ce n'est pas un générateur : rien de ce module ne produit de code. Il extrait seulement ce qu'un test peut
vérifier de façon fiable (types, héritage, attributs, opérations, relations). Tout ce qui n'est pas reconnu
est ignoré plutôt que deviné.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textutil import strip_notes

_BLOCK_COMMENT = re.compile(r"/'.*?'/", re.DOTALL)
_LINE_COMMENT = re.compile(r"(?m)(^|\s)'.*$")
_DECL = re.compile(r'^\s*(abstract\s+class|abstract|class|interface|enum)\s+"?([A-Za-z_]\w*)"?', re.IGNORECASE)
_ARROW = (r"(?:<\|?|\*|o|#|\+|\^)?(?:--+|\.\.+|-+|\.+)(?:\|?>|\*|o|#|\+|\^)?")
_REL = re.compile(rf'^\s*([A-Za-z_]\w*)\s*(?:"([^"]*)"\s*)?({_ARROW})\s*(?:"([^"]*)"\s*)?([A-Za-z_]\w*)\s*(?::.*)?$')
_MODIFIERS = re.compile(r"\{(?:static|abstract|classifier)\}", re.IGNORECASE)


def norm(name: str) -> str:
    """Forme comparable d'un identifiant : addMoney == add_money == AddMoney."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


@dataclass
class UmlClass:
    name: str
    kind: str                                   # class | abstract | interface | enum
    attributes: list[str] = field(default_factory=list)      # constantes pour une énumération
    operations: list[str] = field(default_factory=list)


@dataclass
class UmlRelation:
    source: str               # le type qui doit référencer `target`
    target: str
    many: bool
    both: bool = False        # association sans navigabilité : l'un OU l'autre côté peut porter le champ


@dataclass
class Model:
    classes: dict[str, UmlClass] = field(default_factory=dict)
    extends: list[tuple[str, str]] = field(default_factory=list)      # (enfant, parent)
    implements: list[tuple[str, str]] = field(default_factory=list)   # (enfant, interface)
    relations: list[UmlRelation] = field(default_factory=list)


def _is_many(multiplicity: str | None) -> bool:
    if not multiplicity:
        return False
    m = multiplicity.strip()
    if "*" in m:
        return True
    upper = re.findall(r"\d+", m)
    return bool(upper) and int(upper[-1]) > 1


def _member_name(line: str, is_operation: bool, enum: bool) -> str:
    text = _MODIFIERS.sub("", line).strip().lstrip("+-#~ ").strip()
    if is_operation:
        head = text.split("(", 1)[0].strip()
        return head.split()[-1] if head else ""
    if ":" in text:
        return text.split(":", 1)[0].strip().split()[-1] if text.split(":", 1)[0].strip() else ""
    words = text.split()
    return words[-1] if words else ""


def parse(puml: str) -> Model:
    text = _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", strip_notes(puml)))
    model = Model()
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        decl = _DECL.match(line)
        if decl:
            word, name = decl.group(1).lower(), decl.group(2)
            kind = "abstract" if word.startswith("abstract") else word
            cls = model.classes.setdefault(name, UmlClass(name, kind))
            if "{" in line and "}" not in line.split("{", 1)[1]:          # corps sur plusieurs lignes
                is_enum = kind == "enum"
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("}"):
                    member = lines[i].strip()
                    if member and not re.match(r"^[-=_.]{2,}", member):
                        if "(" in member:
                            op = _member_name(member, True, is_enum)
                            if op and op != name:
                                cls.operations.append(op)
                        else:
                            attr = _member_name(member, False, is_enum)
                            if attr:
                                cls.attributes.append(attr)
                    i += 1
            i += 1
            continue
        rel = _REL.match(line)
        if rel:
            left, m_left, arrow, m_right, right = rel.groups()
            if "<|" in arrow or "|>" in arrow:
                child, parent = (right, left) if arrow.startswith("<|") else (left, right)
                (model.implements if ".." in arrow else model.extends).append((child, parent))
            else:
                navigable_right, navigable_left = arrow.endswith(">"), arrow.startswith("<")
                whole_left = arrow.startswith(("*", "o")) and "." not in arrow[:1]
                whole_right = arrow.endswith(("*", "o")) and len(arrow) > 2
                if navigable_right and not navigable_left or whole_left:
                    model.relations.append(UmlRelation(left, right, _is_many(m_right)))
                elif navigable_left and not navigable_right or whole_right:
                    model.relations.append(UmlRelation(right, left, _is_many(m_left)))
                else:
                    model.relations.append(UmlRelation(left, right, _is_many(m_right), both=True))
        i += 1
    for cls in model.classes.values():                 # supprime les doublons en gardant l'ordre
        cls.attributes = list(dict.fromkeys(cls.attributes))
        cls.operations = list(dict.fromkeys(cls.operations))
    model.relations = [r for r in model.relations if r.source in model.classes and r.target in model.classes]
    model.extends = [e for e in model.extends if all(n in model.classes for n in e)]
    model.implements = [e for e in model.implements if all(n in model.classes for n in e)]
    return model
