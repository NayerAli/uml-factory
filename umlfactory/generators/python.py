"""Agent générateur Python (lancé par `python -m umlfactory.generators python`).

Le code est d'abord analysé (ast) ; PythonRuntime l'importe ensuite dans un sous-processus contrôlé
(dossier jetable, délai strict, environnement nettoyé) pour vérifier chargement, instanciation et conformité.
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
from pathlib import Path, PurePosixPath

from ..verify import (Runtime, VerifyContext, VerifyReport, clean_env, findings_to_report, parse_findings, run,
                      write_tree)
from .base import BaseGeneratorAgent, Validation


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or \
           (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")


def runtime_imports(tree: ast.Module, known: set[str]) -> set[str]:
    """Modules du projet importés au chargement (hors `if TYPE_CHECKING:` et hors fonctions)."""
    found: set[str] = set()

    def visit(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.If):
                if not _is_type_checking(node.test):
                    visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Try):
                visit(node.body)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    last = node.module.split(".")[-1]
                    if last in known:
                        found.add(last)
                for alias in node.names:        # `from . import wallet` / `from pkg import wallet`
                    if alias.name in known:
                        found.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    last = alias.name.split(".")[-1]
                    if last in known:
                        found.add(last)

    visit(tree.body)
    return found


def find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def dfs(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            if state.get(nxt, 0) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if state.get(nxt, 0) == 0:
                cycle = dfs(nxt)
                if cycle:
                    return cycle
        stack.pop()
        state[node] = 2
        return None

    for n in sorted(graph):
        if state.get(n, 0) == 0:
            cycle = dfs(n)
            if cycle:
                return cycle
    return None


class PythonGenerator(BaseGeneratorAgent):
    language = "python"
    display_name = "Python"
    file_extensions = (".py",)
    source_media_type = "text/x-python"
    plan_rules = (
        "one module per class, abstract class, interface and enum, with a snake_case file name "
        "(BankAccount -> bank_account.py). If a package is given, put the modules in that package folder "
        "and add an `__init__.py` re-exporting every type with `__all__`; otherwise no `__init__.py`."
    )
    style_rules = (
        "Python rules:\n"
        "- Target Python 3.10+. Start every module with `from __future__ import annotations` and use "
        "type hints everywhere.\n"
        "- Modules import each other, so avoid circular imports: an import used ONLY in type hints goes "
        "under `if TYPE_CHECKING:`; a base class must be a real runtime import.\n"
        "- Attributes become instance attributes set in `__init__`; private (-) ones are `_name` exposed "
        "through `@property` and a setter. Collections are `list[T]` initialised to an empty list.\n"
        "- `abstract class` and `interface` -> subclasses of `abc.ABC`, abstract operations decorated with "
        "`@abstractmethod`. Inheritance and interface realisation -> base classes in the class statement; "
        "concrete classes implement every abstract method.\n"
        "- Relations become attributes typed with the target class, named after the role if there is one, "
        "otherwise after the class (snake_case).\n"
        "- Add a short docstring to each class and public method (from the diagram notes)."
    )

    def runtime(self) -> Runtime:
        return PythonRuntime()

    def validate(self, files: dict[str, str]) -> Validation:
        result = Validation()
        trees: dict[str, ast.Module] = {}
        for path, code in files.items():
            try:
                trees[path] = ast.parse(code, filename=path)
            except SyntaxError as exc:
                result.errors[path] = f"SyntaxError line {exc.lineno}: {exc.msg}"
        stems = {PurePosixPath(p).stem: p for p in trees if PurePosixPath(p).name != "__init__.py"}
        graph = {stem: runtime_imports(trees[p], set(stems)) - {stem} for stem, p in stems.items()}
        cycle = find_cycle(graph)
        if cycle:
            for stem in set(cycle):
                result.errors.setdefault(
                    stems[stem],
                    "circular import at load time: " + " -> ".join(cycle)
                    + ". Move imports used only in annotations under `if TYPE_CHECKING:`.")
        return result


# ---------------------------------------------------------------------------------- vérification d'exécution

_SENSITIVE = {
    "process execution": r"\b(?:os\s*\.\s*(?:system|popen|exec\w*|spawn\w*|startfile)|subprocess|multiprocessing)\b",
    "network": r"(?m)^\s*(?:import|from)\s+(?:socket|urllib|http|requests|httpx|ftplib|smtplib|telnetlib|aiohttp)\b",
    "files": r"\bshutil\s*\.\s*(?:rmtree|move|copy\w*)|\bos\s*\.\s*(?:remove|unlink|rmdir|rename|makedirs|mkdir)\b|(?<![\w.])open\s*\(",
    "dynamic code": r"(?<![\w.])(?:exec|eval|compile|__import__)\s*\(|\bctypes\b",
    "environment / exit": r"\bos\s*\.\s*(?:environ|_exit|getenv)\b|\bsys\s*\.\s*exit\b",
}

# Harnais exécuté dans le sous-processus : importe chaque module, vérifie la forme des types, instancie les classes
# concrètes avec des valeurs par défaut. Aucune opération métier n'est appelée.
_HARNESS = r"""
import enum, importlib, inspect, json, re, sys, traceback
MARK = "@@UMLFACTORY@@"
def emit(level, kind, cls, msg=""):
    print(MARK + "|".join([level, kind, cls, str(msg).replace("\n", " ").replace("\r", " ")]), flush=True)
def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())
spec = json.load(open(sys.argv[1], encoding="utf-8"))
sys.path.insert(0, sys.argv[2])
modules = {}
failed_imports = False
for name in spec["modules"]:
    try:
        modules[name] = importlib.import_module(name)
        emit("OK", "import", name.rsplit(".", 1)[-1])
    except BaseException as exc:
        failed_imports = True
        emit("FAIL", "import", name.rsplit(".", 1)[-1],
             "importing module " + name + " failed: " + traceback.format_exception_only(type(exc), exc)[-1].strip())
def find(name):
    for mod in modules.values():
        obj = getattr(mod, name, None)
        if inspect.isclass(obj) and obj.__module__ == mod.__name__:
            return obj
    for mod in modules.values():
        obj = getattr(mod, name, None)
        if inspect.isclass(obj):
            return obj
    return None
def source(cls):
    try:
        return inspect.getsource(cls)
    except (OSError, TypeError):
        return ""
classes = {}
for c in spec["classes"]:
    obj = find(c["name"])
    if obj is None:
        emit("SKIP" if failed_imports else "FAIL", "class", c["name"],
             "no class named " + c["name"] + " was found in the generated modules")
        continue
    classes[c["name"]] = obj
    kind, ok, why = c["kind"], True, ""
    if kind == "enum":
        ok = issubclass(obj, enum.Enum)
        why = "declared as an enum in the diagram but is not an enum.Enum"
    elif kind == "class":
        ok = not inspect.isabstract(obj) and not issubclass(obj, enum.Enum)
        why = ("it still has unimplemented abstract methods: " + ", ".join(sorted(obj.__abstractmethods__))
               if inspect.isabstract(obj) else "declared as a plain class in the diagram")
    emit("OK" if ok else "FAIL", "class", c["name"], c["name"] + ": " + why)
def default_for(param):
    ann = param.annotation
    text = (ann if isinstance(ann, str) else getattr(ann, "__name__", str(ann))).lower()
    m = re.match(r"^(int|float|bool|str|list|set|dict|tuple)\b", text)
    return {"int": 0, "float": 0.0, "bool": False, "str": "", "list": [], "set": set(), "dict": {}, "tuple": ()}.get(
        m.group(1) if m else "", None)
instances = {}
for c in spec["classes"]:
    obj = classes.get(c["name"])
    if obj is None or c["kind"] != "class" or inspect.isabstract(obj) or issubclass(obj, enum.Enum):
        continue
    try:
        params = [p for p in inspect.signature(obj).parameters.values()
                  if p.default is p.empty and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
        instances[c["name"]] = obj(**{p.name: default_for(p) for p in params})
        emit("OK", "init", c["name"])
    except BaseException as exc:
        text = type(exc).__name__ + ": " + str(exc)
        soft = isinstance(exc, (ValueError, ZeroDivisionError)) or (
            isinstance(exc, (TypeError, AttributeError)) and ("NoneType" in str(exc) or "argument" in str(exc)))
        emit("SOFT" if soft else "FAIL", "init", c["name"],
             ("note: " if soft else "") + "instantiating " + c["name"] + " with default arguments raised " + text)
for child, parent in spec["extends"]:
    if child in classes and parent in classes:
        ok = issubclass(classes[child], classes[parent])
        emit("OK" if ok else "FAIL", "extends", child, child + " must extend or implement " + parent + " as in the diagram")
def names_of(name):
    cls = classes[name]
    names = {norm(n) for n in dir(cls)} | {norm(n) for n in getattr(cls, "__annotations__", {})}
    if issubclass(cls, enum.Enum):
        names |= {norm(n) for n in cls.__members__}
    if name in instances:
        try:
            names |= {norm(n) for n in vars(instances[name])}
        except TypeError:
            pass
    return names
for cls_name, member in spec["attrs"]:
    if cls_name in classes:
        ok = norm(member) in names_of(cls_name) or (cls_name not in instances and norm(member) in norm(source(classes[cls_name])))
        emit("OK" if ok else "FAIL", "attr", cls_name, "attribute '" + member + "' of " + cls_name + " is in the diagram but missing from the code")
for cls_name, member in spec["ops"]:
    if cls_name in classes:
        ok = norm(member) in {norm(n) for n in dir(classes[cls_name])}
        emit("OK" if ok else "FAIL", "op", cls_name, "operation '" + member + "' of " + cls_name + " is in the diagram but missing from the code")
def refers(cls, target):
    return re.search(r"\b" + re.escape(target) + r"\b", source(cls)) is not None
def collection_of(cls, target):
    return re.search(r"(?:list|List|set|Set|Sequence|Collection|Iterable|tuple|Tuple|deque)\s*\[[^\]]*\b" + re.escape(target) + r"\b", source(cls)) is not None
for src, tgt, many, both in spec["rels"]:
    if src not in classes or tgt not in classes:
        continue
    direct, reverse = refers(classes[src], tgt), both and refers(classes[tgt], src)
    if not direct and not reverse:
        emit("FAIL", "rel", src, src + " should have an attribute referring to " + tgt + " (relation of the diagram)")
        continue
    emit("OK", "rel", src, "")
    if many and direct and not collection_of(classes[src], tgt):
        emit("SOFT", "rel", src, "note: " + src + " -> " + tgt + " has a cardinality above 1 but no collection attribute was found")
"""


def _module_name(path: str) -> str | None:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


class PythonRuntime(Runtime):
    tools = ()                      # l'interpréteur qui fait tourner l'agent suffit
    sensitive = _SENSITIVE

    def check(self, ctx: VerifyContext) -> VerifyReport:
        blocked = self.blocked(ctx)
        if blocked is not None:
            return self.finish(ctx, blocked)
        tracker, report = ctx.tracker, VerifyReport()
        model = ctx.model
        spec = {
            "modules": [m for m in (_module_name(p) for p in sorted(ctx.files, key=lambda x: x.count("/"))) if m],
            "classes": [{"name": c.name, "kind": c.kind} for c in model.classes.values()],
            "extends": [*model.extends, *model.implements],
            "attrs": [[c.name, a] for c in model.classes.values() for a in c.attributes],
            "ops": [[c.name, o] for c in model.classes.values() if c.kind != "enum" for o in c.operations],
            "rels": [[r.source, r.target, r.many, r.both] for r in model.relations],
        }
        with tempfile.TemporaryDirectory(prefix="umlfactory-py-") as tmp:
            root, src = Path(tmp), Path(tmp) / "src"
            write_tree(src, ctx.files)
            write_tree(root, {"harness.py": _HARNESS, "spec.json": json.dumps(spec)})
            with tracker.measure("chargement, test de fumée et conformité (python)") as step:
                res = run([sys.executable, "-I", "-B", "-X", "utf8", str(root / "harness.py"), str(root / "spec.json"), str(src)],
                          root, min(tracker.left(), 6.0), clean_env(root))
                step.ok = res.ok
        if res.timed_out:
            report.skipped = "délai dépassé pendant l'exécution"
            report.notes.append("vérification interrompue : le code Python a dépassé le budget de temps (non vérifié)")
            return self.finish(ctx, report)
        findings = parse_findings(res.out)
        if not findings:
            report.notes.append("test de fumée sans résultat : " + (res.err.strip() or "aucune sortie")[-300:])
            report.skipped = "test de fumée sans résultat"
            return self.finish(ctx, report)
        imports = [f for f in findings if f.kind == "import"]
        import_frac = (sum(1 for f in imports if f.level == "OK") / len(imports)) if imports else 1.0
        return self.finish(ctx, findings_to_report(ctx, findings, import_frac, report, executed=True))
