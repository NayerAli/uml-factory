"""Tests du module de vérification : python -m unittest discover -s tests   (depuis le dossier umlfactory-llm).

Les tests Java sont ignorés si `javac` est introuvable sur la machine.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from umlfactory import umlmodel                                            # noqa: E402
from umlfactory.generators._declarative import CommandRuntime              # noqa: E402
from umlfactory.generators.java import JavaRuntime                         # noqa: E402
from umlfactory.generators.python import PythonRuntime                     # noqa: E402
from umlfactory.languages import LanguageSpec, safety_problems, sanitize_id  # noqa: E402
from umlfactory.verify import Tracker, VerifyContext, find_tool            # noqa: E402

PUML = """@startuml
abstract class Wallet {
  -amount : double
  +addMoney()
}
interface IPay {
  +pay()
}
class Card {
  -number : String
}
Wallet <|-- Card
Card ..|> IPay
Card "1" --> "0..*" Wallet : holds
@enduml
"""

PY_OK = {
    "wallet.py": "from __future__ import annotations\nfrom abc import ABC\n\n\nclass Wallet(ABC):\n"
                 "    def __init__(self) -> None:\n        self.amount = 0.0\n\n    def add_money(self) -> None:\n        pass\n",
    "i_pay.py": "from __future__ import annotations\nfrom abc import ABC, abstractmethod\n\n\nclass IPay(ABC):\n"
                "    @abstractmethod\n    def pay(self) -> None: ...\n",
    "card.py": "from __future__ import annotations\nfrom wallet import Wallet\nfrom i_pay import IPay\n\n\n"
               "class Card(Wallet, IPay):\n    def __init__(self) -> None:\n        super().__init__()\n"
               "        self.number = ''\n        self.wallets: list[Wallet] = []\n\n    def pay(self) -> None:\n        pass\n",
}
JAVA_OK = {
    "Wallet.java": "public abstract class Wallet {\n    private double amount;\n    public void addMoney() { }\n}\n",
    "IPay.java": "public interface IPay {\n    void pay();\n}\n",
    "Card.java": "import java.util.ArrayList;\nimport java.util.List;\n\npublic class Card extends Wallet implements IPay {\n"
                 "    private String number;\n    private List<Wallet> wallets = new ArrayList<>();\n    public void pay() { }\n}\n",
}


def ctx(files: dict[str, str], budget: float = 10.0) -> VerifyContext:
    return VerifyContext(files=dict(files), model=umlmodel.parse(PUML), class_files={}, tracker=Tracker(budget))


class UmlModelTest(unittest.TestCase):
    def test_example_model(self):
        model = umlmodel.parse((ROOT / "examples" / "model.puml").read_text(encoding="utf-8"))
        self.assertEqual(set(model.classes), {"BankAccount", "CreditCard", "Customer", "Wallet", "IPaymentProcessor"})
        self.assertEqual(model.classes["Wallet"].kind, "abstract")
        self.assertEqual(model.extends, [("CreditCard", "Wallet")])
        self.assertEqual(model.implements, [("CreditCard", "IPaymentProcessor")])
        self.assertIn("addMoney", model.classes["Wallet"].operations)

    def test_static_member_and_inline_body(self):
        model = umlmodel.parse("class A {\n  -{static} total : int\n  +{static} count() : int\n}\nclass B { +x : int }\n")
        self.assertEqual(model.classes["A"].attributes, ["total"])
        self.assertEqual(model.classes["A"].operations, ["count"])
        self.assertIn("B", model.classes)


class PythonRuntimeTest(unittest.TestCase):
    def test_conforming_code_scores_100(self):
        report = PythonRuntime().check(ctx(PY_OK))
        self.assertEqual(report.errors, {})
        self.assertEqual(report.score, 100)

    def test_missing_inheritance_is_reported_on_the_file(self):
        files = {**PY_OK, "card.py": PY_OK["card.py"].replace("Card(Wallet, IPay)", "Card(IPay)")}
        report = PythonRuntime().check(ctx(files))
        self.assertIn("card.py", report.errors)
        self.assertIn("must extend", report.errors["card.py"])
        self.assertLess(report.score, 100)

    def test_runtime_error_in_module_is_caught(self):
        files = {**PY_OK, "wallet.py": PY_OK["wallet.py"] + "\nclass Broken:\n    value = Undefined()\n"}
        report = PythonRuntime().check(ctx(files))
        self.assertIn("NameError", report.errors["wallet.py"])

    def test_infinite_loop_is_cut_and_reported_unverified(self):
        files = {**PY_OK, "wallet.py": PY_OK["wallet.py"] + "\nwhile True:\n    pass\n"}
        report = PythonRuntime().check(ctx(files, budget=2.0))
        self.assertIsNone(report.score)
        self.assertIn("délai", report.skipped)
        self.assertTrue(report.notes)

    def test_sensitive_calls_are_never_executed(self):
        marker = "never_created.txt"
        files = {**PY_OK, "wallet.py": "import socket\nopen('" + marker + "', 'w')\n" + PY_OK["wallet.py"]}
        report = PythonRuntime().check(ctx(files))
        self.assertEqual(report.score, 0)
        self.assertIn("wallet.py", report.errors)
        self.assertFalse(Path(marker).exists())

    def test_environment_is_clean(self):
        import os
        os.environ["OPENAI_API_KEY"] = "secret-key"
        files = {"wallet.py": "import os\nx = os.environ\n"}
        self.assertEqual(PythonRuntime().check(ctx(files)).score, 0)      # os.environ est un appel sensible
        from umlfactory.verify import clean_env
        self.assertNotIn("OPENAI_API_KEY", clean_env())


@unittest.skipUnless(find_tool("javac") and find_tool("java"), "JDK introuvable")
class JavaRuntimeTest(unittest.TestCase):
    def test_conforming_code_scores_100(self):
        report = JavaRuntime().check(ctx(JAVA_OK))
        self.assertEqual(report.errors, {})
        self.assertEqual(report.score, 100)

    def test_compile_error_is_attributed_to_the_file(self):
        files = {**JAVA_OK, "Wallet.java": JAVA_OK["Wallet.java"].replace("double", "doubl")}
        report = JavaRuntime().check(ctx(files))
        self.assertIn("Wallet.java", report.errors)
        self.assertEqual(report.score, 10)

    def test_missing_attribute_is_reported(self):
        files = {**JAVA_OK, "Card.java": JAVA_OK["Card.java"].replace("private String number;", "")}
        report = JavaRuntime().check(ctx(files))
        self.assertIn("number", report.errors["Card.java"])


class LanguageSpecTest(unittest.TestCase):
    def spec(self, **kw):
        base = dict(id="demo", display_name="Demo", file_extensions=[".py"], plan_rules="x", style_rules="y",
                    tools=["python"], build=["python", "-m", "py_compile", "{file}"])
        return LanguageSpec(**{**base, **kw})

    def test_safe_spec_is_accepted(self):
        self.assertEqual(safety_problems(self.spec()), [])

    def test_unknown_executable_is_refused(self):
        self.assertTrue(safety_problems(self.spec(tools=["rm"], build=["rm", "-rf", "{dir}"])))

    def test_shell_syntax_is_refused(self):
        self.assertTrue(safety_problems(self.spec(build=["python", "-c", "print(1); import os"])))

    def test_build_scripts_in_scaffold_are_refused(self):
        self.assertTrue(safety_problems(self.spec(scaffold={"build.rs": "fn main(){}"})))

    def test_single_letter_language_id_is_valid(self):
        self.assertEqual(self.spec(id="c", display_name="C").id, "c")
        self.assertEqual(sanitize_id("C"), "c")

    def test_ids(self):
        self.assertEqual((sanitize_id("C++"), sanitize_id("C#"), sanitize_id("Type Script")), ("cpp", "csharp", "typescript"))

    def test_command_runtime_checks_each_file(self):
        runtime = CommandRuntime(self.spec())
        good = runtime.check(ctx(PY_OK))
        self.assertEqual(good.score, 100)
        compiles_only = runtime.check(ctx({"a.py": "x = 1\n", "b.py": "y = 2\n"}))
        self.assertLess(compiles_only.score, 100)         # compile, mais ne reprend pas le diagramme
        bad = runtime.check(ctx({"a.py": "x = 1\n", "b.py": "def (:\n"}))
        self.assertEqual(list(bad.errors), ["b.py"])

    def test_generated_build_files_are_refused(self):
        report = CommandRuntime(self.spec()).check(ctx({"build.rs": "fn main(){}"}))
        self.assertIn("build.rs", report.errors)


if __name__ == "__main__":
    unittest.main()
