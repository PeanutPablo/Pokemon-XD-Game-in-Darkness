"""Tests for first-run discovery of Dolphin and the player's disc image.

Everything here runs against a temporary tree. Discovery's whole job is to
look at the real machine, so a test that let it do that would pass or fail
according to what happens to be installed on whoever's computer is running
the suite -- which is why `find_dolphin` and `find_disc_images` both take a
`roots` override, and why every test below supplies one.

Disc bytes are synthetic, the same arrangement `test_bootstrap_game_data.py`
and `test_fsys_lzss.py` use: the real images are copyrighted and cannot live
in a repository, so what is pinned here is the header layout as the code
reads it.

Every case is a `unittest.TestCase`. A bare `def test_*` here would be
collected by pytest and silently skipped by unittest discovery, which is
how this project actually shipped a PC box-addressing bug once."""
import struct
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parents[1]))

import setup_discovery as discovery


def disc_header(game_id=b"GXXE01", revision=0, name=b"POKeMON XD",
                magic=discovery.DISC_MAGIC):
    """A 0x440-byte GameCube disc header, as `describe_disc` reads it."""
    header = bytearray(0x440)
    header[0x00:0x06] = game_id
    header[0x07] = revision
    header[0x20:0x20 + len(name)] = name
    struct.pack_into(">I", header, 0x1C, magic)
    return bytes(header)


def write(path, payload=b""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


class TempTreeTest(unittest.TestCase):
    """Gives each test its own tree and tears it down again."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def paths_of(self, candidates):
        return [candidate.path for candidate in candidates]

    def names_of(self, candidates):
        return [candidate.path.name for candidate in candidates]


class IsoPathsFromIniTests(unittest.TestCase):
    """`Dolphin.ini` parsing, hand-rolled because configparser rejects it."""

    def test_isopath_entries_are_returned_in_file_order(self):
        text = (
            "[General]\n"
            "ISOPaths = 2\n"
            "ISOPath0 = C:\\Games\\GameCube\n"
            "ISOPath1 = D:\\More Games\n"
        )
        self.assertEqual(
            discovery.iso_paths_from_ini(text),
            ["C:\\Games\\GameCube", "D:\\More Games"])

    def test_the_isopaths_count_is_not_mistaken_for_a_path(self):
        text = "[General]\nISOPaths = 1\nISOPath0 = C:\\Games\n"
        self.assertEqual(discovery.iso_paths_from_ini(text), ["C:\\Games"])

    def test_isopath_entries_outside_the_general_section_are_ignored(self):
        text = (
            "[General]\n"
            "ISOPath0 = C:\\Real\n"
            "[Interface]\n"
            "ISOPath0 = C:\\Decoy\n"
        )
        self.assertEqual(discovery.iso_paths_from_ini(text), ["C:\\Real"])

    def test_a_value_containing_a_percent_sign_survives(self):
        """configparser's interpolation raises on these; this must not."""
        text = "[General]\nISOPath0 = C:\\100%% Complete\\Games\n"
        self.assertEqual(
            discovery.iso_paths_from_ini(text), ["C:\\100%% Complete\\Games"])

    def test_an_empty_value_is_not_offered_as_a_path(self):
        text = "[General]\nISOPath0 = \nISOPath1 = C:\\Games\n"
        self.assertEqual(discovery.iso_paths_from_ini(text), ["C:\\Games"])

    def test_an_empty_or_pathless_config_yields_nothing(self):
        self.assertEqual(discovery.iso_paths_from_ini(""), [])
        self.assertEqual(
            discovery.iso_paths_from_ini("[General]\nShowLag = False\n"), [])


class DescribeDiscTests(TempTreeTest):
    """The cheap header read that gives the pick list something to say."""

    def test_a_gamecube_header_is_described_by_id_revision_and_name(self):
        image = write(self.root / "game.iso", disc_header())
        self.assertEqual(
            discovery.describe_disc(image), "GXXE01 rev 0, POKeMON XD")

    def test_the_revision_is_reported_as_read_not_assumed_zero(self):
        image = write(self.root / "game.iso", disc_header(revision=2))
        self.assertIn("rev 2", discovery.describe_disc(image))

    def test_a_file_without_the_disc_magic_is_not_a_disc(self):
        image = write(self.root / "movie.iso", disc_header(magic=0xDEADBEEF))
        self.assertIsNone(discovery.describe_disc(image))

    def test_a_file_shorter_than_the_header_is_not_a_disc(self):
        image = write(self.root / "stub.iso", b"\x00" * 0x100)
        self.assertIsNone(discovery.describe_disc(image))

    def test_a_missing_file_is_reported_rather_than_raised(self):
        self.assertIsNone(discovery.describe_disc(self.root / "absent.iso"))


class FindDolphinTests(TempTreeTest):
    """Ordering here is the feature: nearest first, so the streamlined
    arrangements cost the player no questions at all."""

    def test_dolphin_inside_the_release_folder_comes_first(self):
        release = self.root / "release"
        write(release / "Dolphin.exe")
        write(self.root / "elsewhere" / "Dolphin.exe")
        found = discovery.find_dolphin(
            release, environ={}, roots=[self.root / "elsewhere"])
        self.assertEqual(found[0].path, release / "Dolphin.exe")
        self.assertEqual(found[0].source, "in this folder")

    def test_a_release_dropped_into_the_dolphin_folder_finds_it_beside(self):
        """The arrangement the whole design is optimised for."""
        dolphin_folder = self.root / "Dolphin-x64"
        exe = write(dolphin_folder / "Dolphin.exe")
        release = dolphin_folder / "PokemonXGAccessibility"
        release.mkdir()
        found = discovery.find_dolphin(release, environ={}, roots=[])
        self.assertEqual(self.paths_of(found), [exe])
        self.assertEqual(found[0].source, "beside this folder")

    def test_dolphin_is_found_three_levels_below_a_search_root(self):
        """`Desktop/apps/Dolphin-x64/Dolphin.exe` is the observed layout."""
        desktop = self.root / "Desktop"
        exe = write(desktop / "apps" / "Dolphin-x64" / "Dolphin.exe")
        found = discovery.find_dolphin(
            self.root / "release", environ={}, roots=[desktop])
        self.assertEqual(self.paths_of(found), [exe])

    def test_the_same_dolphin_reached_two_ways_is_offered_once(self):
        dolphin_folder = self.root / "Dolphin-x64"
        exe = write(dolphin_folder / "Dolphin.exe")
        release = dolphin_folder / "release"
        release.mkdir()
        found = discovery.find_dolphin(
            release, environ={}, roots=[self.root, dolphin_folder])
        self.assertEqual(self.paths_of(found), [exe])

    def test_an_exe_installer_install_under_program_files_is_found(self):
        """Dolphin ships both a portable archive and a Windows installer.

        The installer puts it in Program Files and writes an uninstall
        registry entry. Two independent routes find it -- this one, and
        `_registry_dolphin_directories` -- which matters because whether
        that installer populates `InstallLocation` has not been confirmed
        here (the development machine's Dolphin is portable and has no
        uninstall entry at all). This route does not depend on it."""
        program_files = self.root / "Program Files"
        exe = write(program_files / "Dolphin Emulator" / "Dolphin.exe")
        found = discovery.find_dolphin(
            self.root / "release",
            environ={"ProgramFiles": str(program_files)})
        self.assertEqual(self.paths_of(found), [exe])

    def test_nothing_installed_yields_an_empty_list_not_a_guess(self):
        found = discovery.find_dolphin(
            self.root / "release", environ={}, roots=[self.root])
        self.assertEqual(found, [])

    def test_a_directory_named_dolphin_exe_is_not_offered(self):
        (self.root / "Dolphin.exe").mkdir()
        found = discovery.find_dolphin(
            self.root / "release", environ={}, roots=[self.root])
        self.assertEqual(found, [])

    def test_the_search_stops_at_the_depth_limit(self):
        deep = self.root
        for level in range(discovery.MAX_DEPTH + 2):
            deep = deep / f"level{level}"
        write(deep / "Dolphin.exe")
        found = discovery.find_dolphin(
            self.root / "release", environ={}, roots=[self.root])
        self.assertEqual(found, [])

    def test_an_exhausted_budget_returns_what_was_found_so_far(self):
        write(self.root / "Dolphin-x64" / "Dolphin.exe")
        spent = discovery._Budget(limit=0)
        found = discovery.find_dolphin(
            self.root / "release", environ={}, roots=[self.root],
            budget=spent)
        self.assertEqual(found, [])


class FindDiscImagesTests(TempTreeTest):
    """Ranking, and the one thing discovery is allowed to rule out."""

    def test_an_image_beside_the_release_outranks_one_in_a_search_root(self):
        release = self.root / "release"
        release.mkdir()
        near = write(self.root / "near.iso", disc_header())
        far = write(self.root / "Downloads" / "far.iso", disc_header())
        found = discovery.find_disc_images(
            release, environ={}, roots=[self.root / "Downloads"])
        self.assertEqual(self.paths_of(found)[:1], [near])
        self.assertIn(far, self.paths_of(found))

    def test_an_iso_without_the_disc_magic_is_excluded_entirely(self):
        """Read, not judged by name: two PlayStation 3 `.iso` files on the
        development machine were offered as game candidates before this."""
        release = self.root / "release"
        release.mkdir()
        write(self.root / "playstation.iso", disc_header(magic=0x12345678))
        gamecube = write(self.root / "gamecube.iso", disc_header())
        found = discovery.find_disc_images(release, environ={}, roots=[])
        self.assertEqual(self.paths_of(found), [gamecube])

    def test_a_compressed_container_is_offered_undescribed_not_dropped(self):
        """`.rvz` has no header where this looks, so it cannot be ruled out
        -- bootstrap converts it through DolphinTool later."""
        release = self.root / "release"
        release.mkdir()
        compressed = write(self.root / "game.rvz", b"RVZ\x01not a header")
        found = discovery.find_disc_images(release, environ={}, roots=[])
        self.assertEqual(self.paths_of(found), [compressed])
        self.assertEqual(found[0].detail, "")

    def test_dolphins_configured_game_paths_are_searched(self):
        release = self.root / "release"
        release.mkdir()
        library = self.root / "GameLibrary"
        image = write(library / "game.iso", disc_header())
        dolphin_folder = self.root / "Dolphin-x64"
        exe = write(dolphin_folder / "Dolphin.exe")
        write(dolphin_folder / "portable.txt")
        write(dolphin_folder / "User" / "Config" / "Dolphin.ini",
              f"[General]\nISOPaths = 1\nISOPath0 = {library}\n".encode())
        found = discovery.find_disc_images(
            release, dolphin_exe=exe, environ={}, roots=[])
        self.assertEqual(self.paths_of(found), [image])
        self.assertEqual(found[0].source, "in Dolphin's own game list")

    def test_an_image_beside_dolphin_is_found_without_any_config(self):
        release = self.root / "release"
        release.mkdir()
        dolphin_folder = self.root / "Dolphin-x64"
        exe = write(dolphin_folder / "Dolphin.exe")
        image = write(dolphin_folder / "game.iso", disc_header())
        found = discovery.find_disc_images(
            release, dolphin_exe=exe, environ={}, roots=[])
        self.assertEqual(self.paths_of(found), [image])
        self.assertEqual(found[0].source, "beside Dolphin")

    def test_the_same_image_reached_two_ways_is_offered_once(self):
        release = self.root / "release"
        release.mkdir()
        dolphin_folder = self.root / "Dolphin-x64"
        exe = write(dolphin_folder / "Dolphin.exe")
        write(dolphin_folder / "game.iso", disc_header())
        found = discovery.find_disc_images(
            release, dolphin_exe=exe, environ={}, roots=[dolphin_folder])
        self.assertEqual(len(found), 1)

    def test_files_that_are_not_disc_images_are_never_offered(self):
        release = self.root / "release"
        release.mkdir()
        write(self.root / "notes.txt", b"hello")
        write(self.root / "save.sav", b"\x00" * 0x500)
        found = discovery.find_disc_images(release, environ={}, roots=[self.root])
        self.assertEqual(found, [])


class DolphinConfigDirTests(TempTreeTest):
    """Where Dolphin's own config lives, which decides whether the
    "Dolphin's own game list" ranking runs at all.

    `%APPDATA%` was missing from this function until 2026-08-18. The
    development machine's Dolphin has no `portable.txt` and no
    `Documents/Dolphin Emulator`, so the lookup returned None and that
    entire branch of `find_disc_images` never executed -- masked by the
    images happening to sit beside `Dolphin.exe`, where a different branch
    found them. Its real config was in `%APPDATA%/Dolphin Emulator/Config`,
    naming that same folder as `ISOPath0`."""

    def config_at(self, *parts):
        config = self.root.joinpath(*parts)
        config.mkdir(parents=True, exist_ok=True)
        (config / "Dolphin.ini").write_text("[General]\n", encoding="utf-8")
        return config

    def test_appdata_is_found(self):
        config = self.config_at("AppData", "Roaming", "Dolphin Emulator",
                                "Config")
        found = discovery.dolphin_config_dir(
            None, {"APPDATA": str(self.root / "AppData" / "Roaming")})
        self.assertEqual(found, config)

    def test_documents_is_still_found_when_appdata_has_none(self):
        config = self.config_at("Documents", "Dolphin Emulator", "Config")
        found = discovery.dolphin_config_dir(
            None, {"APPDATA": str(self.root / "nowhere"),
                   "USERPROFILE": str(self.root)})
        self.assertEqual(found, config)

    def test_onedrive_redirected_documents_is_found(self):
        config = self.config_at("OneDrive", "Documents", "Dolphin Emulator",
                                "Config")
        found = discovery.dolphin_config_dir(
            None, {"OneDrive": str(self.root / "OneDrive")})
        self.assertEqual(found, config)

    def test_appdata_wins_over_documents(self):
        appdata = self.config_at("AppData", "Roaming", "Dolphin Emulator",
                                 "Config")
        self.config_at("Documents", "Dolphin Emulator", "Config")
        found = discovery.dolphin_config_dir(
            None, {"APPDATA": str(self.root / "AppData" / "Roaming"),
                   "USERPROFILE": str(self.root)})
        self.assertEqual(found, appdata)

    def test_a_portable_install_beats_every_shared_location(self):
        """A build with portable.txt ignores the shared ones entirely."""
        self.config_at("AppData", "Roaming", "Dolphin Emulator", "Config")
        dolphin = self.root / "Dolphin-x64"
        exe = write(dolphin / "Dolphin.exe")
        write(dolphin / "portable.txt")
        found = discovery.dolphin_config_dir(
            exe, {"APPDATA": str(self.root / "AppData" / "Roaming")})
        self.assertEqual(found, dolphin / "User" / "Config")

    def test_nothing_configured_yields_none(self):
        self.assertIsNone(discovery.dolphin_config_dir(None, {}))

    def test_forward_slash_iso_paths_are_read(self):
        """Dolphin writes ISOPath0 with forward slashes on Windows."""
        library = self.root / "Games"
        image = write(library / "game.iso", disc_header())
        config = self.root / "AppData" / "Roaming" / "Dolphin Emulator" / "Config"
        config.mkdir(parents=True)
        (config / "Dolphin.ini").write_text(
            "[General]\n"
            f"ISOPath0 = {str(library).replace(chr(92), '/')}\n"
            "ISOPaths = 1\n", encoding="utf-8")
        release = self.root / "release"
        release.mkdir()
        found = discovery.find_disc_images(
            release, dolphin_exe=None,
            environ={"APPDATA": str(self.root / "AppData" / "Roaming")},
            roots=[])
        self.assertEqual(self.paths_of(found), [image])
        self.assertEqual(found[0].source, "in Dolphin's own game list")


class UserRootsTests(unittest.TestCase):
    """Where discovery looks, and why it cannot just use `Path.home()`."""

    def test_onedrive_redirected_folders_are_searched(self):
        """With OneDrive Backup on, the real Desktop is under %OneDrive%
        and `~/Desktop` is absent or an empty stub."""
        roots = discovery.user_roots(
            {"USERPROFILE": r"C:\Users\p", "OneDrive": r"C:\Users\p\OneDrive"})
        self.assertIn(Path(r"C:\Users\p\OneDrive\Desktop"), roots)
        self.assertIn(Path(r"C:\Users\p\Desktop"), roots)

    def test_onedrive_is_searched_before_the_plain_profile(self):
        roots = discovery.user_roots(
            {"USERPROFILE": r"C:\Users\p", "OneDrive": r"C:\Users\p\OneDrive"})
        self.assertLess(roots.index(Path(r"C:\Users\p\OneDrive\Desktop")),
                        roots.index(Path(r"C:\Users\p\Desktop")))

    def test_an_empty_environment_yields_no_roots_rather_than_raising(self):
        self.assertEqual(discovery.user_roots({}), [])


class CandidateTests(unittest.TestCase):
    """What the player actually hears."""

    def test_the_description_names_the_file_its_detail_and_its_folder(self):
        candidate = discovery.Candidate(
            Path(r"C:\Games\XG.iso"), "beside Dolphin", "GXXE01 rev 0")
        described = candidate.describe()
        self.assertIn("XG.iso", described)
        self.assertIn("GXXE01 rev 0", described)
        self.assertIn("beside Dolphin", described)
        self.assertIn(r"C:\Games", described)

    def test_a_candidate_with_no_detail_reads_without_an_empty_gap(self):
        candidate = discovery.Candidate(
            Path(r"C:\Games\game.rvz"), "in this folder")
        self.assertNotIn(" --  -- ", candidate.describe())


if __name__ == "__main__":
    unittest.main()
