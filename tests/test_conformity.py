"""Langages ajoutés (ex. PHP) : la compilation ne suffit pas, le code doit aussi reprendre les noms du diagramme."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from umlfactory import umlmodel  # noqa: E402
from umlfactory.generators._declarative import CommandRuntime  # noqa: E402
from umlfactory.languages import LanguageSpec  # noqa: E402
from umlfactory.verify import Tracker, VerifyContext  # noqa: E402

PUML = """@startuml
class Client {
  -nom : String
  +getNom()
}
class Compte {
  -solde : double
  +deposer()
}
Client "1" --> "*" Compte
@enduml
"""

FULL = {
    "Client.php": "<?php class Client { private string $nom; public function getNom() { return $this->nom; }"
                  " private array $comptes = []; /** @var Compte[] */ }",
    "Compte.php": "<?php class Compte { private float $solde; public function deposer() {} }",
}


def check(files: dict[str, str], puml: str = PUML):
    spec = LanguageSpec(id="zzphp", display_name="PHP", file_extensions=[".php"], plan_rules="One file per type.",
                        style_rules="Rule.", tools=["python"], build=["python", "-c", "pass"],
                        sensitive_calls=[], status="validated", score=90)
    model = umlmodel.parse(puml)
    ctx = VerifyContext(files=files, model=model, class_files={n: f"{n}.php" for n in model.classes},
                        tracker=Tracker(10.0))
    return CommandRuntime(spec).check(ctx)


class DeclarativeConformityTest(unittest.TestCase):
    def test_conforming_code_scores_100(self):
        report = check(FULL)
        self.assertEqual(report.errors, {})
        self.assertEqual(report.score, 100)

    def test_missing_class_is_reported_and_not_100(self):
        report = check({"Client.php": FULL["Client.php"]})
        self.assertLess(report.score, 100)
        self.assertTrue(any("Compte" in msg for msg in report.errors.values()))

    def test_missing_operation_is_reported(self):
        files = dict(FULL, **{"Compte.php": "<?php class Compte { private float $solde; }"})
        report = check(files)
        self.assertIn("Compte.php", report.errors)
        self.assertIn("deposer", report.errors["Compte.php"])
        self.assertLess(report.score, 100)

    def test_missing_attribute_is_reported(self):
        files = dict(FULL, **{"Client.php": "<?php class Client { public function getNom() {} private $comptes; }"})
        report = check(files)
        self.assertIn("nom", report.errors.get("Client.php", ""))

    def test_snake_case_and_case_are_tolerated(self):
        files = dict(FULL, **{"Client.php": FULL["Client.php"].replace("getNom", "get_nom")})
        self.assertEqual(check(files).errors, {})

    def test_unparsed_diagram_is_never_100(self):
        report = check(FULL, puml="@startuml\n@enduml\n")
        self.assertLessEqual(report.score, 60)
        self.assertTrue(any("non vérifiée" in n for n in report.notes))


if __name__ == "__main__":
    unittest.main()
