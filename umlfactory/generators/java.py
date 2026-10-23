"""Agent générateur Java (lancé par `python -m umlfactory.generators Java`)."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path, PurePosixPath

from ..verify import (Runtime, VerifyContext, VerifyReport, clean_env, compute_score, find_tool, findings_to_report,
                      parse_findings, run, write_tree)
from .base import BaseGeneratorAgent, Validation

_ERROR_START = re.compile(r"^(?P<file>[^\n]+?\.java):(?P<line>\d+): error: ", re.MULTILINE)
_LITERALS = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|//[^\n]*|/\*.*?\*/', re.DOTALL)
_PAIRS = {")": "(", "]": "[", "}": "{"}
_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)


def balanced(code: str) -> str | None:
    """Contrôle de secours sans javac : parenthèses/accolades/crochets équilibrés. Renvoie le problème."""
    stack: list[str] = []
    for ch in _LITERALS.sub("", code):
        if ch in "([{":
            stack.append(ch)
        elif ch in _PAIRS:
            if not stack or stack.pop() != _PAIRS[ch]:
                return f"unbalanced '{ch}'"
    return f"unclosed '{stack[-1]}'" if stack else None


class JavaGenerator(BaseGeneratorAgent):
    language = "java"
    display_name = "Java"
    file_extensions = (".java",)
    source_media_type = "text/x-java-source"
    plan_rules = (
        "one file per top-level type, named exactly `<TypeName>.java` (Java rules: the public type and "
        "the file share the same name); no other files."
    )
    style_rules = (
        "Java rules:\n"
        "- Target Java 17. One top-level type per file, public, named like the file.\n"
        "- Packages: if a package is given, EVERY file declares exactly that package. If none is given, "
        "NO file may contain a `package` statement (default package) - never invent one such as "
        "com.example.*. All files share the same package, which must match their folder.\n"
        "- Add every import that is needed (java.util.List, java.util.ArrayList, ...). Use only the JDK.\n"
        "- Attributes follow the diagram visibility (usually private) with getters and setters named "
        "getX/setX (isX for boolean). Relations become fields typed with the target class, named after the "
        "role if there is one, otherwise after the class; collections are `List<T>` initialised with "
        "`new ArrayList<>()`.\n"
        "- `abstract class` -> abstract class; abstract operations have no body. `interface` -> interface "
        "with method signatures only. Use `extends` / `implements` from the diagram, and implement every "
        "inherited abstract or interface method in concrete classes (with @Override).\n"
        "- Operations without a return type are `void`. Map UML types to Java types (String, double, int, "
        "boolean, LocalDate, ...).\n"
        "- With bidirectional associations, never write toString/equals/hashCode that recurse into the "
        "other side."
    )

    def runtime(self) -> Runtime:
        return JavaRuntime()

    def validate(self, files: dict[str, str]) -> Validation:
        """Contrôles statiques. La compilation se fait dans JavaRuntime (une seule fois, avec le test de fumée)."""
        result = Validation()
        for path, code in files.items():
            problem = balanced(code)
            if problem:
                result.errors[path] = f"syntax: {problem}"
            declared = (_PACKAGE.search(code) or [None, ""])[1]
            expected = PurePosixPath(path).parent.as_posix().replace("/", ".")
            expected = "" if expected == "." else expected
            if declared != expected:
                wanted = f"declare exactly `package {expected};`" if expected else "have NO package statement"
                result.errors[path] = (result.errors.get(path, "") + "\n" if path in result.errors else "") + (
                    f"package mismatch: this file is in folder '{PurePosixPath(path).parent.as_posix()}', so it must "
                    f"{wanted} (found: {('`package ' + declared + ';`') if declared else 'none'}). "
                    "All files of the project must use the same package, otherwise they cannot see each other.")
        return result

# ---------------------------------------------------------------------------------- vérification d'exécution

_SENSITIVE = {
    "process execution": r"\b(?:ProcessBuilder|Runtime\s*\.\s*getRuntime)\b",
    "network": r"\bimport\s+java\.net\.|\bjava\.net\.\w|\bnew\s+(?:Server)?Socket\b|\bHttpClient\b",
    "files": r"\bjava\.io\.(?:File|RandomAccessFile)\w*|\bjava\.nio\.file\b",
    "reflection / native code": r"\bjava\.lang\.reflect\b|\bClass\s*\.\s*forName\b|\bSystem\s*\.\s*(?:load|loadLibrary|setSecurityManager)\b",
    "environment / exit": r"\bSystem\s*\.\s*(?:exit|getenv)\b|\bRuntime\s*\.\s*halt\b",
}

# Harnais exécuté APRÈS compilation : il charge chaque type, vérifie sa forme par réflexion et instancie les classes
# concrètes avec des valeurs par défaut. Aucune opération métier n'est appelée. Compatible Java 8+.
_HARNESS = r"""
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

public class UmlSmoke {
    static final String MARK = "@@UMLFACTORY@@";
    static void out(String level, String kind, String cls, String msg) {
        System.out.println(MARK + level + "|" + kind + "|" + cls + "|" + String.valueOf(msg).replace('\n', ' ').replace('\r', ' '));
    }
    static String norm(String s) { return s.toLowerCase().replaceAll("[^a-z0-9]", ""); }
    static Object value(Class<?> t) {
        if (t == int.class || t == Integer.class) return 0;
        if (t == long.class || t == Long.class) return 0L;
        if (t == double.class || t == Double.class) return 0.0d;
        if (t == float.class || t == Float.class) return 0.0f;
        if (t == boolean.class || t == Boolean.class) return false;
        if (t == char.class || t == Character.class) return 'a';
        if (t == byte.class || t == Byte.class) return (byte) 0;
        if (t == short.class || t == Short.class) return (short) 0;
        if (t == String.class) return "";
        if (t.isArray()) return Array.newInstance(t.getComponentType(), 0);
        if (t == List.class || t == Collection.class || t == Iterable.class) return new ArrayList<Object>();
        if (t == Set.class) return new HashSet<Object>();
        if (t == Map.class) return new HashMap<Object, Object>();
        return null;
    }
    static boolean refers(Class<?> c, String target) {
        java.util.regex.Pattern p = java.util.regex.Pattern.compile("(^|[^A-Za-z0-9_])" + target + "([^A-Za-z0-9_]|$)");
        for (Field f : c.getDeclaredFields()) if (p.matcher(f.getGenericType().getTypeName()).find()) return true;
        return false;
    }
    static boolean collectionOf(Class<?> c, String target) {
        java.util.regex.Pattern p = java.util.regex.Pattern.compile("(List|Set|Collection|Iterable|Queue|Deque)<.*\\b" + target + "\\b|\\b" + target + "\\[\\]");
        for (Field f : c.getDeclaredFields()) if (p.matcher(f.getGenericType().getTypeName()).find()) return true;
        return false;
    }
    static Throwable root(Throwable t) { while (t.getCause() != null && t.getCause() != t) t = t.getCause(); return t; }

    public static void main(String[] args) throws Exception {
        List<String> lines = Files.readAllLines(Paths.get(args[0]), StandardCharsets.UTF_8);
        Map<String, Class<?>> classes = new LinkedHashMap<String, Class<?>>();
        Map<String, String> kinds = new HashMap<String, String>();
        ClassLoader loader = UmlSmoke.class.getClassLoader();
        for (String line : lines) {
            String[] p = line.split("\t", -1);
            if (!p[0].equals("C")) continue;
            try {
                Class<?> c = Class.forName(p[2], false, loader);
                classes.put(p[1], c);
                kinds.put(p[1], p[3]);
                int mod = c.getModifiers();
                boolean ok;
                if (p[3].equals("interface")) ok = c.isInterface();
                else if (p[3].equals("enum")) ok = c.isEnum();
                else if (p[3].equals("abstract")) ok = Modifier.isAbstract(mod) && !c.isInterface();
                else ok = !c.isInterface() && !c.isEnum() && !Modifier.isAbstract(mod);
                if (ok) out("OK", "class", p[1], "");
                else out("FAIL", "class", p[1], "the diagram declares " + p[1] + " as " + p[3] + " but the code defines it differently");
            } catch (Throwable t) {
                out("FAIL", "class", p[1], "cannot load type " + p[1] + " (" + root(t) + ")");
            }
        }
        for (String line : lines) {
            String[] p = line.split("\t", -1);
            try {
                if (p[0].equals("X")) {
                    Class<?> c = classes.get(p[1]), s = classes.get(p[2]);
                    if (c == null || s == null) continue;
                    if (s.isAssignableFrom(c)) out("OK", "extends", p[1], "");
                    else out("FAIL", "extends", p[1], p[1] + " must extend or implement " + p[2] + " as in the diagram");
                } else if (p[0].equals("A") || p[0].equals("O")) {
                    Class<?> c = classes.get(p[1]);
                    if (c == null) continue;
                    Set<String> names = new HashSet<String>();
                    if (p[0].equals("A")) {
                        if (c.isEnum()) for (Object o : c.getEnumConstants()) names.add(norm(((Enum<?>) o).name()));
                        for (Field f : c.getDeclaredFields()) names.add(norm(f.getName()));
                    } else {
                        for (Method m : c.getDeclaredMethods()) names.add(norm(m.getName()));
                    }
                    String kind = p[0].equals("A") ? "attr" : "op";
                    if (names.contains(norm(p[2]))) out("OK", kind, p[1], "");
                    else out("FAIL", kind, p[1], (kind.equals("attr") ? "attribute '" : "operation '") + p[2] + "' of " + p[1] + " is in the diagram but missing from the code");
                } else if (p[0].equals("R")) {
                    Class<?> c = classes.get(p[1]), t = classes.get(p[2]);
                    if (c == null || t == null) continue;
                    boolean both = p[4].equals("1"), many = p[3].equals("1");
                    boolean direct = refers(c, p[2]), reverse = both && refers(t, p[1]);
                    if (!direct && !reverse) {
                        out("FAIL", "rel", p[1], p[1] + " should have a field referring to " + p[2] + " (relation of the diagram)");
                    } else {
                        out("OK", "rel", p[1], "");
                        boolean coll = direct ? collectionOf(c, p[2]) : collectionOf(t, p[1]);
                        if (many && direct && !coll) out("SOFT", "rel", p[1], "note: " + p[1] + " -> " + p[2] + " has a cardinality above 1 but no collection field was found");
                    }
                }
            } catch (Throwable t) {
                out("SOFT", "harness", "", "note: check skipped (" + root(t) + ")");
            }
        }
        for (Map.Entry<String, Class<?>> e : classes.entrySet()) {
            String name = e.getKey();
            Class<?> c = e.getValue();
            if (!"class".equals(kinds.get(name)) || c.isInterface() || c.isEnum() || Modifier.isAbstract(c.getModifiers())) continue;
            try {
                Class.forName(c.getName(), true, loader);
            } catch (Throwable t) {
                out("FAIL", "init", name, "static initialisation of " + name + " failed: " + root(t));
                continue;
            }
            Constructor<?>[] ks = c.getDeclaredConstructors();
            Arrays.sort(ks, new Comparator<Constructor<?>>() {
                public int compare(Constructor<?> a, Constructor<?> b) { return a.getParameterTypes().length - b.getParameterTypes().length; }
            });
            Throwable last = null;
            boolean done = false;
            for (Constructor<?> k : ks) {
                try {
                    k.setAccessible(true);
                    Class<?>[] ts = k.getParameterTypes();
                    Object[] vals = new Object[ts.length];
                    for (int i = 0; i < ts.length; i++) vals[i] = value(ts[i]);
                    k.newInstance(vals);
                    done = true;
                    break;
                } catch (InvocationTargetException ex) {
                    last = ex.getCause() != null ? ex.getCause() : ex;
                } catch (Throwable t) {
                    last = t;
                }
            }
            if (done || ks.length == 0) { out("OK", "init", name, ""); continue; }
            boolean soft = last instanceof NullPointerException || last instanceof IllegalArgumentException
                    || last instanceof IllegalStateException || last instanceof UnsupportedOperationException
                    || last instanceof ArithmeticException;
            out(soft ? "SOFT" : "FAIL", "init", name, (soft ? "note: " : "") + "instantiating " + name + " with default arguments raised " + root(last));
        }
    }
}
"""

_JAVAC_FAST = ["-J-XX:TieredStopAtLevel=1", "-J-Xshare:auto"]
_JVM_FAST = ["-XX:TieredStopAtLevel=1", "-Xshare:auto"]


def _fqn(path: str) -> str:
    return ".".join(PurePosixPath(path).with_suffix("").parts)


def _expectations(ctx: VerifyContext) -> str:
    """Fichier d'attentes lu par le harnais (tabulations) : types, héritage, attributs, opérations, relations."""
    rows: list[str] = []
    for name, cls in ctx.model.classes.items():
        path = ctx.file_of(name)
        rows.append(f"C\t{name}\t{_fqn(path) if path else name}\t{cls.kind}")
    rows += [f"X\t{c}\t{p}" for c, p in [*ctx.model.extends, *ctx.model.implements]]
    for name, cls in ctx.model.classes.items():
        rows += [f"A\t{name}\t{a}" for a in cls.attributes]
        rows += [f"O\t{name}\t{o}" for o in cls.operations if cls.kind != "enum"]
    rows += [f"R\t{r.source}\t{r.target}\t{int(r.many)}\t{int(r.both)}" for r in ctx.model.relations]
    return "\n".join(rows) + "\n"


class JavaRuntime(Runtime):
    tools = ("javac", "java")
    sensitive = _SENSITIVE

    @staticmethod
    def _tool_failed(res) -> bool:
        return not res.ok and ("Unrecognized" in res.err or "Could not create the Java Virtual Machine" in res.err)

    def check(self, ctx: VerifyContext) -> VerifyReport:
        blocked = self.blocked(ctx)
        if blocked is not None:
            return self.finish(ctx, blocked)
        tracker, report = ctx.tracker, VerifyReport()
        javac, java = find_tool("javac"), find_tool("java")
        with tempfile.TemporaryDirectory(prefix="umlfactory-java-") as tmp:
            root = Path(tmp)
            src, out, hdir = root / "src", root / "out", root / "harness"
            out.mkdir()
            write_tree(src, ctx.files)
            write_tree(hdir, {"UmlSmoke.java": _HARNESS})
            (root / "expect.txt").write_text(_expectations(ctx), encoding="utf-8", newline="\n")
            env = clean_env(root)

            with tracker.measure("compilation (javac)") as step:
                base = ["-J-Dfile.encoding=UTF-8", "-proc:none", "-encoding", "UTF-8", "-nowarn", "-Xmaxerrs", "200",
                        "-d", str(out),
                        *ctx.files, str(hdir / "UmlSmoke.java")]
                res = run([javac, *_JAVAC_FAST, *base], src, min(tracker.left(), 8.0), env)
                if self._tool_failed(res):
                    res = run([javac, *base], src, min(tracker.left(), 8.0), env)
                step.ok = res.ok
            if res.timed_out:
                report.skipped = "délai dépassé pendant la compilation"
                report.notes.append(f"vérification interrompue : javac n'a pas fini dans le budget de {tracker.elapsed():.0f} s (code non vérifié)")
                return self.finish(ctx, report)
            if not res.ok:
                stderr = res.err.replace(str(src) + "\\", "").replace(str(src) + "/", "")
                starts = list(_ERROR_START.finditer(stderr))
                for i, m in enumerate(starts):
                    block = stderr[m.start(): starts[i + 1].start() if i + 1 < len(starts) else len(stderr)]
                    name = m.group("file").replace("\\", "/")
                    key = name if name in ctx.files else next(
                        (p for p in ctx.files if p.endswith("/" + name) or p == name), None)
                    if key:
                        report.errors[key] = (report.errors.get(key, "") + "\n" + block.strip()).strip()
                if not report.errors:
                    report.notes.append("javac a échoué : " + (stderr.strip() or "aucun détail")[:500])
                    report.score = None
                    report.skipped = "compilation impossible à interpréter"
                    return self.finish(ctx, report)
                report.score = compute_score([(10, 1.0), (40, 0.0), (25, 0.0), (25, 0.0)])
                return self.finish(ctx, report)

            with tracker.measure("test de fumée et conformité (java)") as step:
                args = ["-Xmx256m", "-Dfile.encoding=UTF-8", "-cp", str(out), "UmlSmoke", str(root / "expect.txt")]
                res = run([java, *_JVM_FAST, *args], root, min(tracker.left(), 5.0), env)
                if self._tool_failed(res):
                    res = run([java, *args], root, min(tracker.left(), 5.0), env)
                step.ok = res.ok
            if res.timed_out:
                report.skipped = "délai dépassé pendant le test"
                report.notes.append("vérification interrompue : le test de fumée a dépassé le budget (code compilé mais non testé)")
                return self.finish(ctx, report)
            findings = parse_findings(res.out)
            if not findings:
                report.notes.append("test de fumée sans résultat : " + (res.err.strip() or "aucune sortie")[:300])
                report.skipped = "test de fumée sans résultat"
                return self.finish(ctx, report)
            return self.finish(ctx, findings_to_report(ctx, findings, 1.0, report))
