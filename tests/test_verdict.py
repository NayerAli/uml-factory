"""Verdict de conformité rendu par le modèle, son affichage, et la consigne donnée au nouveau langage."""

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from umlfactory import skills  # noqa: E402
from umlfactory.cli import conformity_lines  # noqa: E402
from umlfactory.generators.base import GenerationRequest  # noqa: E402
from umlfactory.generators.php import PhpGenerator  # noqa: E402
from umlfactory.generators.repair import JUDGE_SYSTEM, judge_conformity  # noqa: E402
from umlfactory.languages import LanguageSpec, render_generator  # noqa: E402


class FakeLLM:
    def __init__(self, reply: str | Exception):
        self.reply, self.messages = reply, []

    async def chat(self, messages, **kwargs):
        self.messages = messages
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class PlainTerm:
    width = 100

    def __getattr__(self, name):          # green, red, yellow, dim... : sans couleur
        return lambda text: text


def judge(reply, **kw):
    llm = FakeLLM(reply)
    result = asyncio.run(judge_conformity(llm, "@startuml\nclass A\n@enduml", {"A.php": "<?php class A {}"}, **kw))
    return result, llm


class JudgeTest(unittest.TestCase):
    def test_conforme(self):
        result, _ = judge('{"verdict": "conforme", "missing": [], "summary": "ok"}')
        self.assertEqual(result["verdict"], "conforme")

    def test_partiel_lists_missing(self):
        result, _ = judge('```json\n{"verdict": "partiel", "missing": ["méthode deposer()"], "summary": "x"}\n```')
        self.assertEqual((result["verdict"], result["missing"]), ("partiel", ["méthode deposer()"]))

    def test_non_conforme(self):
        result, _ = judge('{"verdict": "non_conforme", "missing": [], "summary": "aucune classe"}')
        self.assertEqual(result["verdict"], "non_conforme")

    def test_unresolved_errors_forbid_conforme(self):
        result, _ = judge('{"verdict": "conforme", "missing": []}', unresolved=["Compte.php : classe absente"])
        self.assertEqual(result["verdict"], "partiel")
        self.assertIn("Compte.php : classe absente", result["missing"])

    def test_model_failure_is_not_verified(self):
        result, _ = judge(RuntimeError("réseau"))
        self.assertEqual(result["verdict"], "non_verifie")
        self.assertTrue(result["reason"])

    def test_unreadable_answer_is_not_verified(self):
        self.assertEqual(judge("je ne sais pas")[0]["verdict"], "non_verifie")
        self.assertEqual(judge('{"verdict": "parfait"}')[0]["verdict"], "non_verifie")

    def test_language_rules_and_diagram_reach_the_model(self):
        _, llm = judge('{"verdict": "conforme"}', rules="- attribut = $nom")
        text = llm.messages[1]["content"]
        self.assertIn("attribut = $nom", text)
        self.assertIn("class A", text)
        self.assertIn("A.php", text)


class DisplayTest(unittest.TestCase):
    def show(self, conformity, **extra):
        return "\n".join(conformity_lines(PlainTerm(), {"conformity": conformity, **extra}))

    def test_each_verdict(self):
        self.assertIn("Conforme au diagramme", self.show({"verdict": "conforme"}))
        partial = self.show({"verdict": "partiel", "missing": ["classe Compte"]})
        self.assertIn("Partiellement conforme", partial)
        self.assertIn("classe Compte", partial)
        self.assertIn("Non conforme", self.show({"verdict": "non_conforme", "summary": "vide"}))

    def test_not_verified_says_why_and_never_shows_a_score(self):
        text = self.show({"verdict": "non_verifie", "reason": "le diagramme n'a pas pu être analysé"})
        self.assertIn("Non vérifié : le diagramme n'a pas pu être analysé", text)
        self.assertNotIn("/100", self.show({"verdict": "conforme"}, score=100))

    def test_missing_compiler_is_mentioned(self):
        text = self.show({"verdict": "conforme", "not_run": "outil introuvable : php"})
        self.assertIn("Compilation non vérifiée", text)

    def test_missing_verdict_is_not_verified(self):
        self.assertIn("Non vérifié", "\n".join(conformity_lines(PlainTerm(), {})))


class ScriptedLLM:
    """Plan, fichiers, puis verdict : réponses selon la demande reçue."""

    def __init__(self, verdict: str):
        self.verdict, self.calls = verdict, 0

    async def chat(self, messages, on_delta=None, **kwargs):
        self.calls += 1
        if messages[0]["content"] == JUDGE_SYSTEM:
            return self.verdict
        if self.calls == 1:
            return '{"files": [{"path": "A.php", "elements": ["A"], "summary": "a"}]}'
        return "<?php class A {}"


class GenerateTest(unittest.TestCase):
    def run_generate(self, verdict: str, puml: str = "@startuml\nclass A\n@enduml\n"):
        # verify_budget=0 : pas d'exécution (php n'est pas requis pour ce test)
        return asyncio.run(PhpGenerator().generate(GenerationRequest(puml=puml), ScriptedLLM(verdict), 1, 0, None, 0))

    def test_generation_returns_the_models_verdict_without_score(self):
        result = self.run_generate('{"verdict": "partiel", "missing": ["attribut x"], "summary": "s"}')
        conformity = result.verification["conformity"]
        self.assertEqual((conformity["verdict"], conformity["missing"]), ("partiel", ["attribut x"]))
        self.assertNotIn("explanation", result.verification)

    def test_unreadable_diagram_is_not_verified(self):
        result = self.run_generate('{"verdict": "conforme"}', puml="@startuml\n@enduml\n")
        self.assertEqual(result.verification["conformity"]["verdict"], "non_verifie")


class NewLanguageTest(unittest.TestCase):
    def test_spec_prompt_asks_for_conformity_rules(self):
        prompt = skills._spec_prompt("Go")[0]["content"]
        self.assertIn('"conformity_rules"', prompt)
        self.assertIn("ignoring case and underscores", prompt)

    def test_generated_agent_file_keeps_the_rules(self):
        spec = LanguageSpec(id="zzgo", display_name="Go", file_extensions=[".go"], plan_rules="x", style_rules="y",
                            conformity_rules="- attribut = champ de struct")
        source = render_generator(spec, today="2026-01-01")
        compile(source, "zzgo.py", "exec")
        self.assertIn("conformity_rules", source)
        self.assertIn("champ de struct", source)

    def test_php_agent_has_conformity_rules(self):
        self.assertIn("extends", PhpGenerator.conformity_rules)
        self.assertEqual(PhpGenerator().to_spec().conformity_rules, PhpGenerator.conformity_rules)


if __name__ == "__main__":
    unittest.main()
