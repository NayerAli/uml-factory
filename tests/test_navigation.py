"""Navigation des menus : retour en arrière confirmé par un double appui, rien de coché, enchaînement des étapes."""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from umlfactory.ui import prompts  # noqa: E402
from umlfactory.ui.prompts import BACK_LABEL, QUIT_LABEL, BackGuard, GoBack, run_steps, select  # noqa: E402


class FakeTerm:
    tty = True
    width = 100

    def __init__(self):
        self.out: list[str] = []

    def write(self, text: str) -> None:
        self.out.append(text)

    def cyan(self, t): return t
    def bold(self, t): return t
    def dim(self, t): return t
    def red(self, t): return t
    def yellow(self, t): return t

    @property
    def screen(self) -> str:
        return "".join(self.out)


def run_menu(keys: list[str], **kwargs):
    term = FakeTerm()
    feed = iter(keys)
    with mock.patch.object(prompts, "read_key", lambda: next(feed)), \
            mock.patch.object(prompts.sys.stdin, "isatty", return_value=True, create=True), \
            mock.patch.object(prompts, "raw_mode", mock.MagicMock()):
        return select(term, "Question", ["A", "B", "C"], **kwargs), term


class BackGuardTest(unittest.TestCase):
    def test_one_press_does_not_go_back(self):
        self.assertFalse(BackGuard().press("left"))

    def test_two_presses_go_back(self):
        guard = BackGuard()
        self.assertFalse(guard.press("esc"))
        self.assertTrue(guard.press("left"))

    def test_other_key_resets(self):
        guard = BackGuard()
        guard.press("left")
        guard.press("down")
        self.assertFalse(guard.press("left"))
        self.assertTrue(guard.press("left"))


class MenuTest(unittest.TestCase):
    def test_single_back_key_shows_warning_and_stays(self):
        (picked, term) = run_menu(["left", "down", "enter"], back=BACK_LABEL)
        self.assertEqual(picked, [1])
        self.assertIn("encore une fois", term.screen)

    def test_double_back_key_goes_back(self):
        with self.assertRaises(GoBack):
            run_menu(["esc", "esc"], back=BACK_LABEL)

    def test_back_row_needs_two_enter(self):
        with self.assertRaises(GoBack):
            run_menu(["down", "down", "down", "enter", "enter"], back=BACK_LABEL)

    def test_back_row_single_enter_stays(self):
        (picked, term) = run_menu(["down", "down", "down", "enter", "up", "enter"], back=BACK_LABEL)
        self.assertEqual(picked, [2])
        self.assertIn("encore une fois sur Entrée", term.screen)

    def test_back_key_ignored_without_back_option(self):
        (picked, _) = run_menu(["esc", "esc", "enter"])
        self.assertEqual(picked, [0])

    def test_nothing_checked_is_refused_then_accepts(self):
        (picked, term) = run_menu(["enter", "down", "space", "enter"], multi=True)
        self.assertEqual(picked, [1])
        self.assertIn("Rien n'est coché", term.screen)

    def test_several_checked(self):
        (picked, _) = run_menu(["space", "down", "down", "space", "enter"], multi=True)
        self.assertEqual(picked, [0, 2])

    def test_numbered_fallback_zero_goes_back(self):
        term = FakeTerm()
        term.tty = False
        with mock.patch("builtins.input", return_value="0"), mock.patch("builtins.print"):
            with self.assertRaises(GoBack):
                select(term, "Question", ["A", "B"], back=BACK_LABEL)


class StepsTest(unittest.TestCase):
    def run_flow(self, script: dict) -> tuple[bool, list[str]]:
        log: list[str] = []

        def make(name):
            async def step(back):
                log.append(f"{name}:{'quit' if back == QUIT_LABEL else 'back'}")
                action = script[name].pop(0) if script[name] else None
                if action == "back":
                    raise GoBack
            return step

        ok = asyncio.run(run_steps([make("file"), make("langs"), make("out")]))
        return ok, log

    def test_forward(self):
        ok, log = self.run_flow({"file": [], "langs": [], "out": []})
        self.assertTrue(ok)
        self.assertEqual(log, ["file:quit", "langs:back", "out:back"])

    def test_back_returns_to_previous_step_then_continues(self):
        ok, log = self.run_flow({"file": [], "langs": [], "out": ["back"]})
        self.assertTrue(ok)
        self.assertEqual(log, ["file:quit", "langs:back", "out:back", "langs:back", "out:back"])

    def test_back_on_first_step_quits(self):
        ok, log = self.run_flow({"file": ["back"], "langs": [], "out": []})
        self.assertFalse(ok)
        self.assertEqual(log, ["file:quit"])


if __name__ == "__main__":
    unittest.main()
