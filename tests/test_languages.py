"""Ajout d'un langage : le fichier d'agent généré (generators/<id>.py) est du vrai code, au même format que java.py."""

import importlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from umlfactory import languages  # noqa: E402
from umlfactory.generators._declarative import CommandGenerator  # noqa: E402
from umlfactory.languages import LanguageSpec, export_generator, is_generated, render_generator  # noqa: E402


def make_spec(**kw) -> LanguageSpec:
    base = dict(id="zzdemo", display_name="ZzDemo", file_extensions=[".zz"], plan_rules="One file per type.",
                style_rules="Rule one.\nRule 'two' with \"quotes\".", tools=["python"],
                build=["python", "-c", "pass"], sensitive_calls=["os.system("], status="validated", score=90)
    base.update(kw)
    return LanguageSpec(**base)


class GeneratedAgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self._old = (languages.GENERATORS_DIR, languages.DRAFT_DIR)
        languages.GENERATORS_DIR, languages.DRAFT_DIR = root / "generators", root / "drafts"
        languages.GENERATORS_DIR.mkdir()
        self.addCleanup(lambda: setattr(languages, "GENERATORS_DIR", self._old[0]))
        self.addCleanup(lambda: setattr(languages, "DRAFT_DIR", self._old[1]))

    def load(self, path: Path):
        spec = importlib.util.spec_from_file_location("umlfactory.generators.zzdemo", path)
        module = importlib.util.module_from_spec(spec)
        module.__package__ = "umlfactory.generators"
        spec.loader.exec_module(module)
        return module

    def test_rendered_source_round_trips(self):
        spec = make_spec()
        path = export_generator(spec)
        self.assertTrue(is_generated("zzdemo"))
        agent = self.load(path).ZzdemoGenerator()
        self.assertIsInstance(agent, CommandGenerator)
        self.assertEqual((agent.language, agent.display_name, agent.file_extensions), ("zzdemo", "ZzDemo", (".zz",)))
        self.assertEqual(agent.style_rules, spec.style_rules.strip() + "\n")
        self.assertEqual(agent.build, ("python", "-c", "pass"))
        self.assertEqual(agent.runtime().tools, ("python",))

    def test_export_removes_draft(self):
        spec = make_spec()
        languages.save_spec(spec)
        export_generator(spec)
        self.assertIsNone(languages.load_spec("zzdemo"))

    def test_unsafe_spec_is_never_written(self):
        with self.assertRaises(ValueError):
            export_generator(make_spec(tools=["rm"], build=["rm", "-rf", "{dir}"]))
        self.assertFalse(languages.generator_path("zzdemo").exists())

    def test_hand_edited_unsafe_command_is_refused_at_runtime(self):
        source = render_generator(make_spec()).replace("('python', '-c', 'pass')", "('rm', '-rf', '/')")
        path = Path(self.tmp.name) / "zzdemo.py"
        path.write_text(source, encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.load(path).ZzdemoGenerator().runtime()

    def test_only_generated_files_can_be_deleted(self):
        handmade = languages.generator_path("zzdemo")
        handmade.write_text("class A: pass\n", encoding="utf-8")
        languages.delete_generated("zzdemo")
        self.assertTrue(handmade.exists())
        export_generator(make_spec())
        languages.delete_generated("zzdemo")
        self.assertFalse(handmade.exists())


if __name__ == "__main__":
    unittest.main()
