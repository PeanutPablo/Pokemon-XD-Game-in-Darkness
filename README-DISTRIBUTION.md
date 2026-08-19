# Accessibility-only releases

Build a shareable archive by running `Build Accessibility Release.cmd`
(optionally `-Version 0.1.0`; the default is a timestamp). The archive is
written to the sibling `Accessibility Releases` folder, outside this
project. The command wrapper handles Windows PowerShell's script policy.

The builder uses an allowlist — see `Tools/release-manifest.txt`. It
never includes personal music replacements, game images, extracted game
data, logs, research repositories, virtual environments, development
probes, or save files.

## The bundled Python runtime

A release carries its own interpreter in `Runtime/`, so the recipient
installs nothing and needs no internet connection to set up. `Tools/
build_runtime.py` stages it: CPython's official **embeddable** package
for Windows, plus the four packages in `requirements.txt` installed into
`Runtime/Lib/site-packages`. About 37 MB zipped, 104 MB unpacked.

Three things about it are load-bearing.

- **The download is pinned.** `build_runtime.py` carries the SHA-256 of
  `python-3.12.10-embed-amd64.zip` and refuses to build if the bytes
  differ. A version with no pinned hash refuses outright rather than
  downloading unverified. The zip is cached in the sibling `RuntimeCache`
  folder, outside this project.
- **Wheels are chosen by the interpreter running pip**, because the
  embeddable package has no pip of its own and the packages go in via
  `pip install --target`. The builder therefore requires a matching 3.12
  win-amd64 interpreter — `Companion/.venv` is one — and checks the
  version and platform rather than assuming.
- **It is not a full standard library.** `venv`, `ensurepip` and
  `tkinter` are all absent. This is not a detail: `setup_companion.py`
  imported `venv` at module level for the source-checkout path, and the
  first release built with a bundled runtime died with
  `ModuleNotFoundError` before printing a line. There is now a test
  pinning it (`test_setup_companion.BundledRuntimeImportTests`), and the
  staged import check below runs on the staged runtime for the same
  reason.

`-NoRuntime` skips the whole step for a fast check of the code side. The
archive it produces is **not** fit to give anyone — Setup would fall back
to hunting for a Python on the recipient's machine.

Both entry points prefer `Runtime/` and fall back to `Companion/.venv`,
so a source checkout keeps working exactly as before.

Personal music belongs in the sibling `Personal Music Overrides` folder.
It is for the owner's local Dolphin/game setup only and is not part of
this project.

## What the builder checks before it will produce an archive

- **No forbidden content** — disc-image and save extensions, and the
  `_dialogue_extraction`, `logs`, `.venv` and research directories.
- **Beacon sounds are complete** — `PASSIVE_BEACON_SOUND_FILES` is
  re-read out of the *staged* `npc_beacons.py` and every file it names
  must be staged under `sounds/`. Adding a seventh category without its
  sound fails the build. This check exists because every release before
  2026-08-10 shipped with no `sounds/` at all: the runtime looked for it
  one level above the project, outside anything the builder staged, and
  the missing files raised `LocalDataError` on the first beacon that came
  into range — a clean build that died minutes into play.
- **The staged tree imports** — every staged module is compiled, and
  `setup_companion`, `launch_accessible` and `bootstrap_game_data` are
  imported from the staged copy, **using the staged runtime** when there
  is one. The allowlist is hand-maintained, so the mistake it invites is
  omitting an import target; without this check that surfaces as a
  traceback on the recipient's first launch. Running it on the project's
  `.venv` instead of the staged runtime is what let the missing-`venv`
  defect above through — the check passed on an interpreter the recipient
  does not have.

## What the recipient still has to supply

Their own disc image. The companion reads the game's own text, item, move
and collision tables, which are copyrighted and are never packaged.
`Companion/bootstrap_game_data.py` generates them locally from the disc
image the player already owns; `Setup.cmd` drives it as part of first-run
setup. Verified against a real disc: all 189 generated files come out
byte-identical to the copy this project built by hand.
