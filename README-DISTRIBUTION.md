# Accessibility-only releases

Build a shareable archive by running `Build Accessibility Release.cmd`
(optionally `-Version 0.1.0`; the default is a timestamp). The archive is
written to the sibling `Accessibility Releases` folder, outside this
project. The command wrapper handles Windows PowerShell's script policy.

The builder uses an allowlist — see `Tools/release-manifest.txt`. It
never includes personal music replacements, game images, extracted game
data, logs, research repositories, virtual environments, development
probes, or save files.

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
  imported from the staged copy. The allowlist is hand-maintained, so the
  mistake it invites is omitting an import target; without this check that
  surfaces as a traceback on the recipient's first launch.

## What the recipient still has to supply

Their own disc image. The companion reads the game's own text, item, move
and collision tables, which are copyrighted and are never packaged.
`Companion/bootstrap_game_data.py` generates them locally from the disc
image the player already owns; `Setup.cmd` drives it as part of first-run
setup. Verified against a real disc: all 189 generated files come out
byte-identical to the copy this project built by hand.
