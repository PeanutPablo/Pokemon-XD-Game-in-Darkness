"""Tests for the first-run prompts: confirming, picking, and typing.

The behaviour pinned here is what a player using a screen reader actually
experiences. Two rules matter more than the rest, and both are easy to
break by accident:

  Enter means "yes, that one". Discovery exists so the common case is a
  single keystroke, so a blank line can no longer mean "cancel" -- it means
  accept. Cancelling is a typed word.

  A listed candidate is still validated. Discovery scans, then the player
  reads, then the player answers; a file can disappear in between. Trusting
  the list would turn that into a confusing failure several steps later,
  inside bootstrap, instead of a plain "there is no file at ..." right here.

`input` is patched rather than driven through a pty: the prompts are the
unit under test, not the console."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

import setup_companion as setup  # noqa: E402
from setup_discovery import Candidate  # noqa: E402


def answers(*replies):
    """Patch `input` to give `replies` in order, then fail loudly.

    Running out is an error rather than an EOF because every test here
    knows exactly how many prompts it expects; an extra prompt is the
    defect, and a silent EOF would hide it."""
    supply = iter(replies)

    def answer(*_args):
        try:
            return next(supply)
        except StopIteration:
            raise AssertionError("asked for more input than the test supplied")
    return mock.patch("builtins.input", answer)


def accept_anything(_answer):
    return None


def reject_everything(_answer):
    return "no."


class ChooseWithOneCandidateTests(unittest.TestCase):
    """The streamlined path: one thing found, one keystroke to accept."""

    def setUp(self):
        self.found = Candidate(Path(r"C:\Dolphin\Dolphin.exe"),
                               "beside this folder", "version 5.0")

    def test_enter_accepts_the_single_candidate(self):
        with answers(""):
            chosen = setup.choose(
                "Dolphin", [self.found], accept_anything, "hint")
        self.assertEqual(chosen, self.found.path)

    def test_a_typed_path_overrides_the_candidate(self):
        with answers(r"D:\Other\Dolphin.exe"):
            chosen = setup.choose(
                "Dolphin", [self.found], accept_anything, "hint")
        self.assertEqual(chosen, Path(r"D:\Other\Dolphin.exe"))

    def test_a_candidate_that_no_longer_validates_falls_back_to_typing(self):
        """Scanned, then read aloud, then deleted -- caught here, not later."""
        with answers("", r"D:\Real\Dolphin.exe"):
            with mock.patch.object(
                    setup, "existing_file", lambda *_a: accept_anything):
                chosen = setup.choose(
                    "Dolphin", [self.found],
                    lambda answer: None if "Real" in answer else "gone.",
                    "hint")
        self.assertEqual(chosen, Path(r"D:\Real\Dolphin.exe"))

    def test_typing_a_cancel_word_stops_setup(self):
        with answers("q"):
            with self.assertRaises(SystemExit):
                setup.choose("Dolphin", [self.found], accept_anything, "hint")


class ChooseWithSeveralCandidatesTests(unittest.TestCase):
    """The pick list."""

    def setUp(self):
        self.found = [
            Candidate(Path(r"C:\A\game.iso"), "beside Dolphin", "GXXE01 rev 0"),
            Candidate(Path(r"C:\B\game.iso"), "in Downloads", "GXXE01 rev 0"),
            Candidate(Path(r"C:\C\game.iso"), "in Desktop", "GXXE01 rev 0"),
        ]

    def test_enter_takes_the_first_which_is_the_best_ranked(self):
        with answers(""):
            chosen = setup.choose("a game", self.found, accept_anything, "hint")
        self.assertEqual(chosen, self.found[0].path)

    def test_a_number_takes_that_entry(self):
        with answers("3"):
            chosen = setup.choose("a game", self.found, accept_anything, "hint")
        self.assertEqual(chosen, self.found[2].path)

    def test_a_number_outside_the_list_asks_again_rather_than_guessing(self):
        with answers("9", "2"):
            chosen = setup.choose("a game", self.found, accept_anything, "hint")
        self.assertEqual(chosen, self.found[1].path)

    def test_zero_is_out_of_range_not_an_index(self):
        with answers("0", "1"):
            chosen = setup.choose("a game", self.found, accept_anything, "hint")
        self.assertEqual(chosen, self.found[0].path)

    def test_a_typed_path_is_accepted_alongside_the_numbers(self):
        with answers(r"E:\Elsewhere\other.iso"):
            chosen = setup.choose("a game", self.found, accept_anything, "hint")
        self.assertEqual(chosen, Path(r"E:\Elsewhere\other.iso"))

    def test_a_rejected_typed_path_asks_again(self):
        with answers("nonsense", "2"):
            chosen = setup.choose(
                "a game", self.found,
                lambda answer: None if answer.endswith(".iso") else "no.",
                "hint")
        self.assertEqual(chosen, self.found[1].path)

    def test_every_candidate_is_read_out_with_its_number(self):
        with answers("1"):
            with mock.patch("builtins.print") as printed:
                setup.choose("a game", self.found, accept_anything, "hint")
        said = "\n".join(str(call.args[0]) for call in printed.call_args_list
                         if call.args)
        for index in (1, 2, 3):
            self.assertIn(f"{index}. ", said)
        self.assertIn("beside Dolphin", said)


class ChooseWithNoCandidatesTests(unittest.TestCase):
    """The fallback, which is the old behaviour and must keep working."""

    def test_a_typed_path_is_taken(self):
        with answers(r"C:\Typed\game.iso"):
            chosen = setup.choose("a game", [], accept_anything, "hint")
        self.assertEqual(chosen, Path(r"C:\Typed\game.iso"))

    def test_a_blank_line_cancels_when_there_is_nothing_to_accept(self):
        with answers(""):
            with self.assertRaises(SystemExit):
                setup.choose("a game", [], accept_anything, "hint")

    def test_a_rejected_path_asks_again(self):
        with answers("bad", "good"):
            chosen = setup.choose(
                "a game", [],
                lambda answer: None if answer == "good" else "no.", "hint")
        self.assertEqual(chosen, Path("good"))

    def test_a_cancel_word_stops_setup(self):
        with answers("cancel"):
            with self.assertRaises(SystemExit):
                setup.choose("a game", [], accept_anything, "hint")


class ExistingFileTests(unittest.TestCase):
    """The validator both paths share."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_real_file_with_an_allowed_suffix_passes(self):
        image = self.root / "game.iso"
        image.write_bytes(b"")
        self.assertIsNone(setup.existing_file(".iso")(str(image)))

    def test_a_missing_file_is_reported_by_path(self):
        problem = setup.existing_file(".iso")(str(self.root / "absent.iso"))
        self.assertIn("absent.iso", problem)

    def test_a_real_file_with_the_wrong_suffix_is_reported_by_suffix(self):
        note = self.root / "notes.txt"
        note.write_bytes(b"")
        problem = setup.existing_file(".iso", ".gcm")(str(note))
        self.assertIn(".iso", problem)
        self.assertIn(".gcm", problem)

    def test_a_directory_is_not_a_file(self):
        self.assertIsNotNone(setup.existing_file()(str(self.root)))


class BundledRuntimeImportTests(unittest.TestCase):
    """Pins a defect that shipped a release which could not start at all.

    CPython's embeddable package -- the interpreter a release carries --
    is not a full standard library. `venv`, `ensurepip` and `tkinter` are
    all absent. `setup_companion.py` imported `venv` at module level for
    the checkout path, which meant that on the release path it raised
    ModuleNotFoundError before printing a single line, on precisely the
    machines the bundled runtime exists to serve.

    The source is read rather than the module inspected, because by the
    time the module object exists the import in question has already
    succeeded in whatever interpreter is running the suite."""

    ABSENT_FROM_EMBEDDABLE = ("venv", "ensurepip", "tkinter")

    def module_level_imports(self, path):
        import ast
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        names = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_setup_imports_nothing_the_bundled_runtime_lacks(self):
        imported = self.module_level_imports(setup.__file__)
        for name in self.ABSENT_FROM_EMBEDDABLE:
            self.assertNotIn(
                name, imported,
                f"setup_companion imports {name} at module level; the "
                f"bundled runtime has no {name}, so setup would die before "
                f"its first line of output.")

    def test_the_release_entry_points_are_equally_clean(self):
        companion = Path(setup.__file__).parent
        for name in ("launch_accessible.py", "setup_discovery.py",
                     "bootstrap_game_data.py"):
            imported = self.module_level_imports(companion / name)
            for absent in self.ABSENT_FROM_EMBEDDABLE:
                self.assertNotIn(
                    absent, imported,
                    f"{name} imports {absent} at module level, which the "
                    f"bundled runtime does not have.")


class PathLengthTests(unittest.TestCase):
    """Windows' 260-character limit, and the half of it that long-path
    support does not fix.

    Measured on the development machine, where `LongPathsEnabled` is 1:
    ordinary file access past the limit works, and importing
    `dolphin_memory_engine` from a 281-character path still failed with
    "The filename or extension is too long". `LoadLibrary` is capped at
    MAX_PATH whatever the registry says, so a `.pyd` or `.dll` past the
    limit is fatal on every machine, while a data file past it is fatal
    only where long paths are off. Getting that backwards means either
    refusing a copy that would have worked, or accepting one that dies
    minutes later pointing at a package instead of at the folder."""

    LIMIT = setup.WINDOWS_PATH_LIMIT

    def test_a_short_tree_is_fine_either_way(self):
        for long_paths in (True, False):
            self.assertIsNone(setup.too_deep(120, 100, long_paths))

    def test_a_long_dll_is_fatal_even_with_long_paths_on(self):
        """The case that was observed failing."""
        self.assertEqual(
            setup.too_deep(self.LIMIT + 21, self.LIMIT + 21, True),
            self.LIMIT + 21)

    def test_a_long_dll_is_fatal_with_long_paths_off(self):
        self.assertEqual(
            setup.too_deep(self.LIMIT + 5, self.LIMIT + 5, False),
            self.LIMIT + 5)

    def test_a_long_data_file_is_fatal_only_with_long_paths_off(self):
        self.assertEqual(
            setup.too_deep(self.LIMIT + 5, 100, False), self.LIMIT + 5)
        self.assertIsNone(setup.too_deep(self.LIMIT + 5, 100, True))

    def test_exactly_at_the_limit_is_already_too_long(self):
        """MAX_PATH counts the terminating null, so 260 does not fit."""
        self.assertEqual(
            setup.too_deep(self.LIMIT, self.LIMIT, True), self.LIMIT)

    def test_loadable_files_are_measured_separately_by_suffix(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            (root / "deep").mkdir()
            (root / "deep" / "notes.txt").write_bytes(b"")
            (root / "deep" / "engine.pyd").write_bytes(b"")
            longest, loadable = setup.longest_paths(root)
            self.assertEqual(longest, len(str(root / "deep" / "engine.pyd")))
            self.assertEqual(loadable, len(str(root / "deep" / "engine.pyd")))

    def test_a_tree_with_no_binaries_reports_no_loadable_length(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            (root / "notes.txt").write_bytes(b"")
            _longest, loadable = setup.longest_paths(root)
            self.assertEqual(loadable, 0)

    def test_the_suffix_match_is_case_insensitive(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            (root / "ENGINE.PYD").write_bytes(b"")
            _longest, loadable = setup.longest_paths(root)
            self.assertEqual(loadable, len(str(root / "ENGINE.PYD")))


class InterpreterSelectionTests(unittest.TestCase):
    """Which Python setup drives, in a release versus a checkout."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def stage(self, runtime=False, venv=False):
        if runtime:
            (self.root / "Runtime").mkdir(parents=True, exist_ok=True)
            (self.root / "Runtime" / "python.exe").write_bytes(b"")
        if venv:
            scripts = self.root / "Companion" / ".venv" / "Scripts"
            scripts.mkdir(parents=True, exist_ok=True)
            (scripts / "python.exe").write_bytes(b"")
        return mock.patch.multiple(
            setup,
            RUNTIME=self.root / "Runtime",
            VENV=self.root / "Companion" / ".venv")

    def test_a_release_uses_its_bundled_runtime(self):
        with self.stage(runtime=True):
            self.assertEqual(setup.interpreter(),
                             self.root / "Runtime" / "python.exe")

    def test_a_checkout_uses_the_venv(self):
        with self.stage(venv=True):
            self.assertIsNone(setup.runtime_python())
            self.assertEqual(
                setup.interpreter(),
                self.root / "Companion" / ".venv" / "Scripts" / "python.exe")

    def test_the_bundled_runtime_wins_when_both_are_present(self):
        """A release unpacked inside a working tree is the thing under
        test, and its own interpreter is the one that should run it."""
        with self.stage(runtime=True, venv=True):
            self.assertEqual(setup.interpreter(),
                             self.root / "Runtime" / "python.exe")


if __name__ == "__main__":
    unittest.main()
