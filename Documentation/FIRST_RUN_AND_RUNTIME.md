# First run and the bundled runtime

**Status: implemented and verified end to end 2026-08-18.** A release was
built, extracted to a clean folder, and set up from start to finish using
only what was inside it — no Python on the path, no typed paths, no
internet. §7 records exactly what that run proved and §8 what it did not.

How a player gets from a downloaded zip to a running game, and why each
part of it is shaped the way it is.

---

## 1. What it was, and why that was the wrong shape

Before this, a release asked the recipient to do three things before they
could play:

1. Install **Python 3.12** — not 3.12-or-newer, *3.12*, because
   `dolphin-memory-engine` publishes no wheel past it. Anyone already on
   3.13 had to be talked into installing an older one alongside, and told
   to tick "Add python.exe to PATH" in an installer they could not see.
2. Type the **absolute path to their disc image** into a console prompt.
3. Type the **absolute path to `Dolphin.exe`** into a second one.

Steps 2 and 3 have no completion, no browse dialog, and no way to check a
typo before pressing Enter. For a project whose entire purpose is that a
blind player can play this game, the least accessible thing in it was the
first thing anyone met.

Step 1 also meant setup needed an internet connection to pip-install four
packages, so a failure there was a wall of pip output about compilers.

## 2. What it is now

    Extract the zip.  Run Setup.cmd.  Run Launch Accessible XD.cmd.

Setup asks no questions the player must answer from memory. It reports
what it found and asks for confirmation:

    Found Dolphin:
      Dolphin.exe -- Dolphin-x64 -- in Desktop\apps\Dolphin-x64,
      in C:\Users\...\OneDrive\Desktop\apps\Dolphin-x64

    Press Enter to use it, or type the full path to a different one.

With more than one match it becomes a numbered list, Enter taking number
one. Typing a full path still works everywhere, and is the only option
when discovery comes up empty — discovery cannot be exhaustive and does
not pretend to be.

## 3. Discovery — `Companion/setup_discovery.py`

Two ordering rules, both deliberate.

**Nearest first.** A release extracted *inside* the Dolphin folder, or
beside it, is the arrangement this is optimised for: `Dolphin.exe` is then
the first and only candidate and the player presses Enter. This is what
"just drop it in your Dolphin folder" means in practice.

**Dolphin's own opinion beats ours.** For disc images, the paths Dolphin
is configured to scan for games come before anything found by guessing at
Downloads or the desktop. A game the player can already see in Dolphin's
list is a game whose file Dolphin can name.

Three config layouts are read, in order: the portable one (`portable.txt`
beside the executable, config under `User\Config`), then
`%APPDATA%\Dolphin Emulator\Config`, then `<Documents>\Dolphin Emulator\
Config` in both its plain and OneDrive-redirected forms. Portable comes
first because such a build ignores the shared locations entirely, so
preferring a shared one would read a config Dolphin is not using.

> **`%APPDATA%` was missing until 2026-08-18, and it is the common case.**
> This was written checking only portable and Documents, and called
> verified on a machine that is neither: no `portable.txt`, no
> `Documents\Dolphin Emulator`. `dolphin_config_dir` returned None, so
> this entire ranking never ran. Nothing looked wrong, because the disc
> images happened to sit beside `Dolphin.exe` and the *next* branch down
> found them — the pick list was correct for the wrong reason. The real
> config was in `%APPDATA%\Dolphin Emulator\Config`, and its `ISOPath0`
> named that same folder. Pinned by `DolphinConfigDirTests`.
>
> The general lesson is the one this project keeps relearning: a check
> that passes because a *different* code path covered for it has not been
> verified. Confirm the branch you think you are testing actually ran.

Search order for Dolphin: inside the release, beside the release, registry
install locations, the usual folders, the system PATH. For disc images: in
and beside the release, Dolphin's configured game paths, the folder
Dolphin lives in, the usual folders.

**Redirected folders.** Roots come from the environment, not from
`Path.home()`. With OneDrive Backup on, Desktop and Documents live under
`%OneDrive%` and `~/Desktop` is absent or an empty stub. Both are
searched, OneDrive first. The development machine is one of these, which
is how the case was noticed.

**Bounded.** Depth 3 below each root, and one shared budget of 6,000
directories for the whole run, so a crowded home folder cannot turn setup
into a disk crawl with no output. Observed cost on the development
machine: 4.7 seconds.

### The one thing discovery is allowed to rule out

A disc label is neither necessary nor sufficient here — XG relabels
nothing, and two different vanilla XD builds ship under the same `GXXE01`.
So discovery **never filters on a filename**. It reads the 0x440-byte
header and reports what it says, as description only.

It does reject on one ground: an `.iso` or `.gcm` whose disc magic is
absent is not a GameCube disc, and that is a conclusion drawn from the
file's own bytes. This is not hypothetical — the development machine had
two PlayStation 3 `.iso` files in `Program Files (x86)` that were being
offered as game candidates until the check went in. Compressed containers
(`.rvz` and friends) have no header where this looks, cannot be ruled out,
and are offered undescribed.

## 4. The bundled runtime — `Tools/build_runtime.py`

A release carries its own interpreter in `Runtime/`: CPython's official
**embeddable** package for Windows, plus the four packages from
`requirements.txt` in `Runtime/Lib/site-packages`. 37 MB zipped, 104 MB
unpacked. It is a plain zip of the same binaries as the installer build —
no installer, no registry entries, no effect on any Python already on the
machine.

Setup therefore installs nothing. The environment-building step does not
run at all in a release; it exists only for a source checkout, which has
no `Runtime/` and still builds `Companion/.venv` exactly as before. Both
entry points prefer `Runtime/` and fall back to `.venv`.

Three properties are load-bearing.

**The download is pinned.** `build_runtime.py` carries the SHA-256 of
`python-3.12.10-embed-amd64.zip` and refuses to build if the bytes differ.
A version with no pinned hash refuses outright rather than downloading
unverified. This is trust-on-first-use: it does not prove the first
download (2026-08-18, HTTPS, certificate-validated) was honest, but it
does mean every release is built from those same bytes and a later
substitution fails the build loudly.

**Wheels are chosen by whichever interpreter runs pip.** The embeddable
package has no pip, so packages go in via `pip install --target` run by
the build machine. A cp312 wheel dropped beside a 3.13 runtime fails at
import time on the *player's* machine, so the builder checks its own
version and platform instead of assuming.

**`sys.path` is controlled by a `._pth` file.** When the embeddable
package's `python312._pth` exists, CPython treats it as the whole of
`sys.path`: the script's own directory is *not* prepended and
`site-packages` is not consulted. The file is therefore rewritten to add
`Lib\site-packages` and `..\Companion`, which is what makes
`import battle_narrator` work from every entry point without any of them
touching `sys.path`.

## 5. The embeddable package is not a full standard library

`venv`, `ensurepip` and `tkinter` are absent from it.

This is recorded as its own section because it cost a release.
`setup_companion.py` imported `venv` at module level for the
source-checkout path. Under the bundled runtime that raised
`ModuleNotFoundError` **before setup printed a single line** — on exactly
the machines the bundled runtime exists to serve.

Two things now prevent a recurrence:

- `test_setup_companion.BundledRuntimeImportTests` parses the source of
  each release entry point and fails if any of the three absent modules
  is imported at module level. The source is parsed rather than the module
  inspected, because by the time a module object exists the import has
  already succeeded in whatever interpreter is running the suite.
- The builder's staged import check now runs **on the staged runtime**
  when there is one, not on the project's `.venv`. Running it on `.venv`
  is precisely what let this through: the check passed on an interpreter
  the recipient does not have.

`venv` is now imported inside `build_environment()`, which is unreachable
when `Runtime/` exists.

## 6. Windows' 260-character limit, and the half of it long paths do not fix

A bundled runtime adds about 1,800 files, the deepest of them 105
characters below the release folder. That makes `MAX_PATH` a real
first-run failure for the first time in this project's life, and the way
it fails is the problem: extracting a release into a deep folder produces

    ImportError: DLL load failed while importing _dolphin_memory_engine:
    The filename or extension is too long

when the narrator starts — naming a package, saying nothing about
folders, and arriving long after the choice that caused it.

**Long-path support does not save you.** This was measured, not assumed.
On the development machine `LongPathsEnabled` is `1`, ordinary file access
past 260 characters works, and the import above still failed from a
281-character path. `LoadLibrary` is capped at `MAX_PATH` whatever the
registry says. So:

| File kind | Past 260 characters |
|---|---|
| `.pyd` / `.dll` | fatal on every machine |
| everything else | fatal only where long-path support is off |

`setup_companion.check_path_length` therefore measures the two separately
and refuses before doing any work, naming the folder and what to do about
it. The rule itself is `too_deep()`, split out so it can be tested without
a 1,800-file tree; `test_setup_companion.PathLengthTests` pins both halves,
including that a long `.pyd` is fatal *with* long paths on.

Practical margin: the longest binary is 94 characters below the release
folder, so the release folder itself needs to be under about 165
characters. `C:\Games\...` is fine; a folder nested under a temp
directory with a GUID in it is not.

## 7. What the 2026-08-18 verification actually did

Built a release, extracted it to a clean folder, and ran
`Runtime\python.exe Companion\setup_companion.py` with no other Python
involved:

- Discovery found the one Dolphin on the machine (under a OneDrive-
  redirected Desktop, three levels down) and four GameCube images, each
  described by disc header. The two PS3 images on the same machine were
  correctly absent.
- Accepting Dolphin with Enter and picking the XG image by number ran
  `bootstrap_game_data.py` under the bundled interpreter to completion:
  4,552 strings from 3 tables, 169 collision rooms, all required and
  optional archives, written to a per-build tree `GXXE01-7BB1937C`.
- Settings were written; setup reported finished.

Also fixed from that run: the step heading printed *after* the bootstrap
output it introduces, because the parent's buffered `stdout` had not been
flushed before the child wrote to the same handle. Invisible on a console,
plainly wrong when piped — and a screen reader announcing a minute of
bootstrap output before the sentence explaining it is worth the flush.

## 8. What is not verified

- **The narrator has not been run from a bundled release.** Its whole
  import graph does load under the bundled interpreter — from a clean
  extraction at `C:\xgtest\`, `run_accessible_pokemon_xd` plus
  `settings_menu`, `sound_library`, `autowalk` and `hero_stick` all
  imported, and `launch_accessible` resolved the bundled `pythonw.exe`,
  the recorded settings and the generated data. That is the failure mode a
  bundled interpreter actually invites, and it is closed. What remains
  untested is the live path: attaching to Dolphin, and speaking through
  NVDA, from a release rather than from the checkout.
- **Only one machine.** Discovery's registry branch, the non-OneDrive
  folder layout, a portable Dolphin with `portable.txt`, and a Dolphin
  found on PATH are all covered by unit tests against temporary trees, not
  by observation on a machine arranged that way.
- **No non-English or unusual-locale path has been tried.**
- The pinned interpreter is **3.12.10**. When
  `dolphin-memory-engine` publishes for a newer Python, the pin and
  `MAX_SUPPORTED_PYTHON` move together or not at all.

## 9. Files

| Concern | Owner |
|---|---|
| Finding Dolphin and disc images | `Companion/setup_discovery.py` |
| The prompts, and what they accept | `Companion/setup_companion.py` |
| Staging the bundled interpreter | `Tools/build_runtime.py` |
| Building the archive | `Tools/Build Accessibility Release.ps1` |
| What a release contains | `Tools/release-manifest.txt` |
| Choosing the interpreter at launch | `Companion/launch_accessible.py` |
| Tests | `Companion/tests/test_setup_discovery.py`, `Companion/tests/test_setup_companion.py` |

Player-facing: [README.md](../README.md). Builder-facing:
[README-DISTRIBUTION.md](../README-DISTRIBUTION.md).
