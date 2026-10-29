"""Pile locale : démarrage automatique, --keep-running / --stop, erreurs d'options sans trace Python."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from umlfactory import cli, deploy  # noqa: E402
from umlfactory.deploy import Stopped, read_state, state_path, stop_stack, write_state  # noqa: E402


class PlainTerm:
    width = 100

    def __getattr__(self, name):          # green, red, dim... : sans couleur
        return lambda text: text


def capture(func, *args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = func(*args)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class StackNeededTest(unittest.TestCase):
    def test_local_coordinator_down_starts_the_stack(self):
        self.assertTrue(cli.stack_needed("http://127.0.0.1:9200", is_up=lambda url: False))

    def test_local_coordinator_up_starts_nothing(self):
        self.assertFalse(cli.stack_needed("http://127.0.0.1:9200", is_up=lambda url: True))

    def test_remote_coordinator_never_starts_anything(self):
        self.assertFalse(cli.stack_needed("http://serveur.exemple.org:9200", is_up=lambda url: False))


class StopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logs = Path(self.tmp.name) / "logs"
        self.logs.mkdir()
        write_state(state_path(self.logs), [("mcp", 111, "http://127.0.0.1:9000/mcp"),
                                            ("java", 222, "http://127.0.0.1:9101")])

    def test_no_state_file_means_no_stack(self):
        self.assertIsNone(stop_stack(Path(self.tmp.name) / "autre" / "logs"))

    def test_corrupt_state_file_is_ignored_cleanly(self):
        state_path(self.logs).write_text("{ pas du json", encoding="utf-8")
        self.assertIsNone(stop_stack(self.logs))
        self.assertFalse(state_path(self.logs).exists())

    def test_running_components_are_stopped_and_state_removed(self):
        alive = {"mcp": True, "java": True}
        killed = []

        def kill(pid, sig):
            killed.append(pid)
            alive["mcp" if pid == 111 else "java"] = False

        with mock.patch.object(deploy, "_is_up", lambda name, url: alive[name]), \
                mock.patch.object(deploy.os, "kill", kill):
            results = stop_stack(self.logs, timeout=1)
        self.assertEqual([r.state for r in results], ["stopped", "stopped"])
        self.assertEqual(killed, [111, 222])
        self.assertFalse(state_path(self.logs).exists())

    def test_dead_component_is_not_killed(self):
        """Le PID peut avoir été réutilisé : sans réponse sur le port, on ne touche à rien."""
        with mock.patch.object(deploy, "_is_up", lambda name, url: False), \
                mock.patch.object(deploy.os, "kill") as kill:
            results = stop_stack(self.logs, timeout=1)
        kill.assert_not_called()
        self.assertEqual([r.state for r in results], ["already", "already"])

    def test_component_that_refuses_to_stop_is_reported_and_kept(self):
        with mock.patch.object(deploy, "_is_up", lambda name, url: True), \
                mock.patch.object(deploy.os, "kill", lambda pid, sig: None):
            results = stop_stack(self.logs, timeout=0.3)
        self.assertEqual([r.state for r in results], ["failed", "failed"])
        self.assertEqual(len(read_state(state_path(self.logs))), 2)


class StopCommandTest(unittest.TestCase):
    settings = mock.Mock(coordinator_url="http://127.0.0.1:9200")

    def test_stop_without_stack_is_a_clean_message(self):
        with mock.patch.object(deploy, "stop_stack", lambda: None), \
                mock.patch.object(cli, "stack_needed", lambda url: True):
            code, out, err = capture(cli.stop_command, PlainTerm(), self.settings)
        self.assertNotEqual(code, 0)
        self.assertIn("Aucune pile UML Factory n'était active", out)
        self.assertNotIn("Traceback", out + err)

    def test_stop_lists_what_was_found_and_stopped(self):
        found = [Stopped("mcp", "http://127.0.0.1:9000/mcp", "stopped"),
                 Stopped("coordinator", "http://127.0.0.1:9200", "stopped"),
                 Stopped("java", "http://127.0.0.1:9101", "stopped")]
        with mock.patch.object(deploy, "stop_stack", lambda: found):
            code, out, _ = capture(cli.stop_command, PlainTerm(), self.settings)
        self.assertEqual(code, 0)
        self.assertIn("Pile trouvée : serveur MCP (port 9000), coordinateur (port 9200), agent java (port 9101)", out)
        self.assertIn("Pile arrêtée (3 composant(s))", out)

    def test_stop_failure_exits_with_error(self):
        found = [Stopped("mcp", "http://127.0.0.1:9000/mcp", "failed")]
        with mock.patch.object(deploy, "stop_stack", lambda: found):
            code, _, err = capture(cli.stop_command, PlainTerm(), self.settings)
        self.assertEqual(code, 1)
        self.assertIn("tourne encore", err)


class OptionsTest(unittest.TestCase):
    def parse(self, *argv):
        return capture(lambda: cli.build_parser().parse_args(list(argv)))

    def test_new_options(self):
        args = cli.build_parser().parse_args(["--keep-running"])
        self.assertTrue(args.keep_running)
        self.assertTrue(cli.build_parser().parse_args(["--stop"]).stop)

    def test_spawn_no_longer_exists(self):
        code, _, err = self.parse("--spawn")
        self.assertEqual(code, 2)
        self.assertIn("option inconnue : --spawn", err)

    def test_option_errors_are_short_french_messages(self):
        for argv, expected in ((["--bidule"], "option inconnue"), (["--provider", "foo"], "n'existe pas"),
                               (["-o"], "une valeur est attendue")):
            code, _, err = self.parse(*argv)
            self.assertEqual(code, 2)
            self.assertIn(expected, err)
            self.assertIn("--help", err)
            self.assertNotIn("usage:", err)
            self.assertNotIn("Traceback", err)

    def test_stop_with_keep_running_is_refused_cleanly(self):
        with mock.patch.object(sys, "argv", ["umlfactory", "--stop", "--keep-running"]):
            code, _, err = capture(cli.main)
        self.assertEqual(code, 1)
        self.assertIn("ne vont pas ensemble", err)

    def test_unexpected_exception_hides_the_traceback(self):
        def boom(*_):
            raise ValueError("cassé")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sys, "argv", ["umlfactory", "--list-languages"]), \
                mock.patch.object(cli, "stack_needed", lambda url: False), mock.patch.object(cli, "run", boom), \
                mock.patch.object(cli, "log_crash", lambda exc: "logs/erreur.log"):
            code, _, err = capture(cli.main)
        self.assertEqual(code, 1)
        self.assertIn("Erreur inattendue", err)
        self.assertIn("logs/erreur.log", err)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
