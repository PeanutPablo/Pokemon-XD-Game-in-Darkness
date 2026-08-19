"""Tests for identifying which game build is running.

The companion's offline tables describe one disc. Loaded against another
they do not fail loudly -- they disagree, and the move reader goes quiet.
That happened twice in two days, in both directions, which is why the
choice is now made by fingerprinting the running game instead of by the
player remembering which data they generated last.

Real values from the two images on hand, so a change that broke the
scheme would be caught here rather than in play:

    vanilla US XD      8FF9D518
    Pokemon XG 1.2.1   7BB1937C
"""
import json
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator import game_build

RUNTIME_WRITTEN_PAGES = (448, 451, 454, 457)
"""Pages of the fingerprint region the engine rewrites after load,
measured against a running vanilla disc (2026-08-13). The sampling must
step over these: a page the game writes would fingerprint differently
from the disc it came from, so every session would fail to match."""


class SampleOffsetTests(unittest.TestCase):
    def test_the_samples_are_deterministic(self):
        self.assertEqual(game_build.sample_offsets(),
                         game_build.sample_offsets())

    def test_there_are_as_many_samples_as_declared(self):
        self.assertEqual(len(game_build.sample_offsets()),
                         game_build.SAMPLE_COUNT)

    def test_every_sample_lies_inside_the_region(self):
        for offset in game_build.sample_offsets():
            self.assertGreaterEqual(offset, 0)
            self.assertLessEqual(
                offset + game_build.PAGE_SIZE, game_build.REGION_SIZE)

    def test_no_sample_lands_on_a_page_the_game_rewrites(self):
        """Why the sample count is pinned rather than chosen to taste.

        Measured: sampling 64 pages lands on page 451 and the fingerprint
        then matches no disc at all, every session. 32 steps over the
        whole cluster."""
        pages = {
            offset // game_build.PAGE_SIZE
            for offset in game_build.sample_offsets()
        }
        self.assertEqual(pages & set(RUNTIME_WRITTEN_PAGES), set())


class FingerprintTests(unittest.TestCase):
    def region(self, filler):
        return bytes(
            (filler + (index // game_build.PAGE_SIZE)) & 0xFF
            for index in range(game_build.REGION_SIZE))

    def dol_for(self, body):
        """A DOL whose single section carries `body` at the region address."""
        header = bytearray(0x100)
        struct.pack_into(">I", header, 0x00, 0x100)                  # offset
        struct.pack_into(">I", header, 0x48, game_build.REGION_ADDRESS)
        struct.pack_into(">I", header, 0x90, len(body))
        sections = [(0, 0x100, game_build.REGION_ADDRESS, len(body))]
        return bytes(header) + body, sections

    def test_disc_and_memory_agree_on_the_same_bytes(self):
        """The whole scheme rests on this: a stamp written from a disc has
        to equal the fingerprint taken from that disc once it is running."""
        body = self.region(7)
        dol, sections = self.dol_for(body)

        def read_bytes(address, size):
            start = address - game_build.REGION_ADDRESS
            return body[start:start + size]

        self.assertEqual(
            game_build.fingerprint_from_dol(dol, sections),
            game_build.fingerprint_from_memory(read_bytes))

    def test_different_builds_fingerprint_differently(self):
        first, first_sections = self.dol_for(self.region(7))
        second, second_sections = self.dol_for(self.region(9))
        self.assertNotEqual(
            game_build.fingerprint_from_dol(first, first_sections),
            game_build.fingerprint_from_dol(second, second_sections))

    def test_a_dol_without_the_region_is_rejected(self):
        """Refusing beats returning a fingerprint of nothing, which would
        collide with every other such build."""
        header = bytearray(0x100)
        struct.pack_into(">I", header, 0x00, 0x100)
        struct.pack_into(">I", header, 0x48, 0x80000000)
        struct.pack_into(">I", header, 0x90, 0x40)
        with self.assertRaises(ValueError):
            game_build.fingerprint_from_dol(
                bytes(header) + b"\0" * 0x40,
                [(0, 0x100, 0x80000000, 0x40)])

    def test_a_short_read_is_an_error_not_a_hash_of_nothing(self):
        with self.assertRaises(ValueError):
            game_build.fingerprint_from_memory(lambda address, size: b"")


class StampTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="build-stamp-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_a_stamp_round_trips(self):
        game_build.write_stamp(
            self.root / "a", "8FF9D518", source="x.iso", game_id="GXXE01",
            revision=0, internal_name="POKeMON XD")
        stamp = game_build.read_stamp(self.root / "a")
        self.assertEqual(stamp["fingerprint"], "8FF9D518")
        self.assertEqual(stamp["internal_name"], "POKeMON XD")

    def test_an_unstamped_directory_reads_as_none(self):
        (self.root / "bare").mkdir()
        self.assertIsNone(game_build.read_stamp(self.root / "bare"))

    def test_a_stamp_from_another_sampling_scheme_is_refused(self):
        """Comparing fingerprints taken different ways would be
        meaningless, so an old stamp is treated as absent and regenerated
        rather than trusted."""
        directory = self.root / "old"
        directory.mkdir()
        (directory / game_build.STAMP_NAME).write_text(json.dumps({
            "fingerprint": "8FF9D518",
            "region_address": game_build.REGION_ADDRESS,
            "region_size": game_build.REGION_SIZE,
            "sample_count": game_build.SAMPLE_COUNT + 1,
            "page_size": game_build.PAGE_SIZE,
        }), encoding="utf-8")
        self.assertIsNone(game_build.read_stamp(directory))

    def test_a_corrupt_stamp_reads_as_none(self):
        directory = self.root / "broken"
        directory.mkdir()
        (directory / game_build.STAMP_NAME).write_text("{", encoding="utf-8")
        self.assertIsNone(game_build.read_stamp(directory))


class SelectTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="build-select-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for name, fingerprint in (("GXXE01-8FF9D518", "8FF9D518"),
                                  ("GXXE01-7BB1937C", "7BB1937C")):
            game_build.write_stamp(
                self.root / name, fingerprint, game_id="GXXE01",
                internal_name="POKeMON XD")

    def test_it_picks_the_tree_matching_the_running_game(self):
        directory, stamp, _reason = game_build.select(self.root, "7BB1937C")
        self.assertEqual(directory.name, "GXXE01-7BB1937C")
        self.assertEqual(stamp["fingerprint"], "7BB1937C")

    def test_the_two_real_builds_do_not_collide(self):
        """Both discs report GXXE01 revision 0 and pass every engine
        signature, so this is the only thing telling them apart."""
        first, _s, _r = game_build.select(self.root, "8FF9D518")
        second, _s, _r = game_build.select(self.root, "7BB1937C")
        self.assertNotEqual(first, second)

    def test_an_unknown_build_selects_nothing_and_says_so(self):
        """Guessing here would restore exactly the silent-wrong-data
        failure the module exists to prevent."""
        directory, stamp, reason = game_build.select(self.root, "DEADBEEF")
        self.assertIsNone(directory)
        self.assertIsNone(stamp)
        self.assertIn("DEADBEEF", reason)
        self.assertIn("GXXE01-8FF9D518".split("-")[1], reason)

    def test_no_stamped_data_is_reported_distinctly(self):
        empty = Path(tempfile.mkdtemp(prefix="build-empty-"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        _directory, _stamp, reason = game_build.select(empty, "8FF9D518")
        self.assertIn("no data tree carries a build stamp", reason)


class SharedFileTests(unittest.TestCase):
    """`shared/` holds the few files a fresh tree cannot contain.

    They are not regenerable from a disc -- they came from a third-party
    disassembler -- so without this a feature would silently vanish on any
    build but the one they were made from. Sharing is allowed only after
    checking the file is the same in every build in hand: Gateon Port's
    decoded script and collision data qualify because every decoded entry
    of XG's `M6_out.fsys` is byte-identical to vanilla's, despite the archive
    being recompressed."""

    def setUp(self):
        from battle_narrator.phase1b_app import shared_or_local
        self.resolve = shared_or_local
        self.base = Path(tempfile.mkdtemp(prefix="shared-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.extraction = self.base / "_dialogue_extraction"
        (self.extraction / "shared" / "rooms").mkdir(parents=True)
        (self.extraction / "shared" / "rooms" / "M6_out.txt").write_text(
            "shared", encoding="utf-8")
        (self.extraction / "shared" / "collision").mkdir()
        (self.extraction / "shared" / "collision" / "M6_out.ccd").write_bytes(
            b"shared collision")

    def test_a_build_without_its_own_copy_gets_the_shared_one(self):
        tree = self.extraction / "GXXE01-7BB1937C"
        tree.mkdir()
        path = self.resolve(tree, self.base, "rooms", "M6_out.txt")
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(encoding="utf-8"), "shared")

    def test_a_builds_own_copy_always_wins(self):
        """So dropping in real per-build data later overrides the shared
        file without touching any code."""
        tree = self.extraction / "GXXE01-8FF9D518"
        (tree / "rooms").mkdir(parents=True)
        (tree / "rooms" / "M6_out.txt").write_text("mine", encoding="utf-8")
        path = self.resolve(tree, self.base, "rooms", "M6_out.txt")
        self.assertEqual(path.read_text(encoding="utf-8"), "mine")

    def test_a_build_can_use_the_verified_shared_gateon_collision(self):
        tree = self.extraction / "GXXE01-7BB1937C"
        tree.mkdir()
        path = self.resolve(tree, self.base, "collision", "M6_out.ccd")
        self.assertEqual(path.read_bytes(), b"shared collision")

    def test_a_file_in_neither_place_is_reported_missing(self):
        """The caller checks `.exists()` and disables the feature; this
        must not raise or invent a path that appears to exist."""
        tree = self.extraction / "GXXE01-7BB1937C"
        tree.mkdir()
        path = self.resolve(tree, self.base, "rooms", "nothing.txt")
        self.assertFalse(path.exists())


class FakeBackend:
    """Dolphin as seen by the startup wait: not there, then there but not
    booted, then booted."""

    def __init__(self, script):
        self.script = list(script)
        self.hooks = 0

    def hook(self):
        self.hooks += 1

    def is_hooked(self):
        return bool(self.script) and self.script[0] is not None

    def read_bytes(self, address, size):
        state = self.script[0]
        if state is None:
            raise RuntimeError("not hooked")
        return state[:size].ljust(size, b"\0")

    def advance(self):
        if len(self.script) > 1:
            self.script.pop(0)


class WaitForBootedGameTests(unittest.TestCase):
    """Startup used to depend on the player's launch order.

    The fingerprint can only be taken from a running game, and the
    narrator is normally started from a desktop shortcut. Started before
    the disc was loaded, it fell through to whichever tree was left over
    -- which is how a vanilla tree came to be loaded against XG, giving a
    silent move menu. Waiting removes the ordering requirement."""

    def setUp(self):
        from battle_narrator.phase1b_app import wait_for_booted_game
        self.wait = wait_for_booted_game
        self.logger = Logger()
        self.speech = SpeechRecorder()

    def test_it_returns_at_once_when_a_game_is_already_booted(self):
        backend = FakeBackend([b"GXXE01\x00\x00"])
        slept = []
        self.assertTrue(self.wait(
            backend, self.logger, self.speech, sleep=slept.append))
        self.assertEqual(slept, [], "must not stall the common case")
        self.assertEqual(self.speech.events, [],
                         "nothing to announce when nothing is waited for")

    def test_it_waits_for_a_game_that_appears_later(self):
        backend = FakeBackend([b"\0" * 8, b"GXXE01\x00\x00"])

        def sleep(_seconds):
            backend.advance()

        self.assertTrue(
            self.wait(backend, self.logger, self.speech, sleep=sleep))

    def test_a_hooked_dolphin_with_no_disc_is_not_a_booted_game(self):
        """The exact state that misfired: Dolphin open at its game list,
        readable, with an all-zero disc header."""
        backend = FakeBackend([b"\0" * 8])
        self.assertFalse(self.wait(
            backend, self.logger, self.speech, timeout=2,
            sleep=lambda _s: None))

    def test_an_unreachable_dolphin_is_waited_through_not_crashed_on(self):
        backend = FakeBackend([None, b"GXXE01\x00\x00"])

        def sleep(_seconds):
            backend.advance()

        self.assertTrue(
            self.wait(backend, self.logger, self.speech, sleep=sleep))

    def test_the_wait_is_announced_once(self):
        """A blind player facing a frozen launcher cannot tell waiting
        from hung -- but repeating it every second would be worse."""
        backend = FakeBackend([b"\0" * 8])
        self.wait(backend, self.logger, self.speech, timeout=5,
                  sleep=lambda _s: None)
        self.assertEqual(len(self.speech.events), 1)
        self.assertIn("Waiting", self.speech.events[0][1])

    def test_it_gives_up_rather_than_blocking_forever(self):
        backend = FakeBackend([b"\0" * 8])
        self.assertFalse(self.wait(
            backend, self.logger, self.speech, timeout=3,
            sleep=lambda _s: None))
        self.assertTrue(self.logger.warnings)


class Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, fmt, *args):
        self.warnings.append(fmt % args if args else fmt)

    def info(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


class SpeechRecorder:
    def __init__(self):
        self.events = []

    def emit(self, event_class, text, interrupt=True):
        self.events.append((event_class, text))
        return True


if __name__ == "__main__":
    unittest.main()
