# ENVIRONMENT.md

Status of the local machine and toolchain against xd-decomp's stated requirements.
Investigation date: 2026-07-23.

## Current checkpoint (authoritative summary)

- **Confirmed:** The current live-test boundary is vanilla US Pokémon XD, `GXXE01`, disc 0, revision 0. Pokémon XG has not yet been created or tested.
- **Confirmed:** Dolphin was updated from 2503a to 2606 during the prior live session. The current executable has no Windows version resource, so 2606 is supported by the previously observed Dolphin window title rather than `VersionInfo`.
- **Confirmed:** The verified replacement `Pokemon XD - Gale of Darkness (USA).rvz` exists both beside Dolphin and under `xd-decomp/orig/GXXE01`. Both copies are 960,244,616 bytes and independently hash to container SHA-1 `061DCF1C19928E7DFB0A7EDF31CF427F37EDE823`.
- **Confirmed:** The replacement's decompressed disc identity was previously verified with `dtk disc verify` as `GXXE01`, disc 1 in dtk's human-facing numbering (disc-number byte 0), revision 0, Redump match, disc-content SHA-1 `C1B5218F832403D15AA500AC4D6AACC8865C792D`.
- **Confirmed:** The superseded truncated image had SHA-1 `FED1C3D7087250AAA20546A5A017410D7F0AE023`, size 1,107,298,670 bytes, and failed around `DVDOffset=0x56336BA0`. It was removed from `orig/GXXE01` and must not be reused.
- **Confirmed:** `build/GXXE01/main.dol` independently hashes to `FF9E752EAD9914AF0B363AE6C831A34CCCE189D2`, exactly matching `config/GXXE01/build.sha1`.
- **Confirmed:** The current `report.json` records 11.215364% matched code, 8.127718% complete/linked code, and 104 of 737 complete units. Its category totals are 522 game units and 215 SDK units; matched-code percentages are 0.748518% game and 76.513580% SDK.
- **Confirmed:** The companion environment is Python 3.12.10 with `dolphin-memory-engine==1.3.1` and `cytolk==0.1.13`.
- **Confirmed (prior live session):** Read-only attachment succeeded while emulation was active, the standard disc header read `GXXE01`, disc 0, revision 0, and every test detached cleanly.
- **Confirmed (current audit):** With Dolphin closed, the connection diagnostic again returned `DolphinStatus.notRunning`, `is_hooked(): False`, and detached cleanly.
- **Confirmed:** No companion script calls a `dolphin_memory_engine.write_*` API. The snapshot files are local read-only investigation artifacts and must never be committed.

## Target identity (do not blur these lines)

| Field | Value |
|---|---|
| Target game | Pokémon XG: NeXt Gen (ROM hack) |
| Base game | Pokémon XD: Gale of Darkness (US) |
| Game ID the decomp expects | `GXXE01` |
| Game revision | Rev 0 (US) is what xd-decomp supports. **XG's exact revision/base is unconfirmed.** |
| Other versions in the repo | `NXXJ01` (JP demo disc) — not our target, do not mix symbols/addresses from it into XG work |
| Versions NOT supported here | PAL, full JP retail, any version besides GXXE01 Rev 0 and the NXXJ01 demo |

Confirmed from `xd-decomp/README.md`: the project's stated goal is a **byte-matching** rebuild of the retail binary, version GXXE01 (USA) or NXXJ01 (JP Demo Disc). Nothing in the repo currently declares support for an "XG" revision. Any assumption that XG shares addresses/symbols with vanilla XD is **unconfirmed** and must be treated as a hypothesis to test once a legally-owned XG image is available.

## Locally installed tooling (checked, not installed)

| Requirement | Repo's stated need | What's on this machine | Status |
|---|---|---|---|
| Python | Any Python 3.x (README says "Install Python and add it to PATH"; no version pin found anywhere in the repo — `configure.py` and `tools/*.py` use only stdlib: `argparse`, `pathlib`, `typing`, `urllib.request`, `zipfile`, `json`, `re`, `platform`, `shutil`) | Python 3.14.6 (`python --version`) | **Satisfies stated requirement.** No repo-side minimum version to fall short of. |
| Ninja | Required, install via `pip install ninja` or download from ninja-build releases | Not installed (`ninja --version` → command not found; `pip show ninja` → not found) | **Missing.** Small install (~2–3 MB via pip). Not installed automatically — flagging per instructions before any install. |
| Git | Needed to clone (incl. submodules) | git 2.54.0.windows.1 | **Satisfies.** |
| Compiler | Not a locally-installed compiler — the build downloads pinned Metrowerks CodeWarrior compiler packages (see below) | N/A | **Not yet downloaded**, and downloading is gated behind your go-ahead (see below). |

## What `python configure.py` would download if run (not yet run)

`configure.py` pins these tool versions and, on first run, fetches them via `tools/download_tool.py` (confirmed by reading that script):

| Tool | Pinned tag | Source | Purpose | Size (not measured; not downloaded) |
|---|---|---|---|---|
| `gc-wii-binutils` | `2.42-1` | `github.com/encounter/gc-wii-binutils` releases (zip) | GNU binutils prebuilt for PowerPC/GC-Wii | Small, typically single-digit MB |
| Metrowerks compilers bundle | `20250812` | `https://files.decomp.dev/compilers_20250812.zip` | The actual CodeWarrior/Metrowerks compiler binaries the project's `mw_version`s require (`GC/1.2.5n`, `GC/1.3.2`, `GC/2.6`) | **Likely the largest download** — a multi-compiler-version bundle. Not measured since it was not fetched. |
| `decomp-toolkit` (`dtk`) | `v1.7.4` | `github.com/encounter/decomp-toolkit` releases | Extracts objects from the disc image, generates the linker script, checks hashes | Small, single prebuilt binary |
| `objdiff-cli` | `v3.4.0` | `github.com/encounter/objdiff` releases | Diffing/verification tool (optional for a basic build; required for the diffing workflow) | Small |
| `sjiswrap` | `v1.2.2` | `github.com/encounter/sjiswrap` releases | Wraps the compiler to feed it Shift-JIS source (the game's text pipeline uses SJIS) | Tiny (single .exe) |
| `wibo` | `1.0.0-beta.4` | `github.com/decompals/wibo` releases | 32-bit Windows binary wrapper — **only needed on Linux/macOS**, not Windows | N/A on this platform |

**None of these have been downloaded.** Running `python configure.py` is what triggers these downloads (or `ninja` on first invocation, depending on which step needs the missing tool). Per your instructions, I stopped here to report this before installing or downloading anything. The compiler package is the one worth a deliberate yes/no since it's the largest and is proprietary-derived (redistributed by the decomp community for GC/Wii targets, not sourced from Nintendo/Metrowerks directly).

## Expected original-game files

From `README.md` and `orig/GXXE01/`:

- A user-supplied disc image goes in `orig/GXXE01/`. **Currently empty** except a `.gitkeep` placeholder — confirmed by directory listing.
- Supported container formats: ISO (GCM), RVZ, WIA, WBFS, CISO, NFS, GCZ, TGC.
- Expected hash: `config/GXXE01/config.yml` and `config/GXXE01/build.sha1` both pin **`ff9e752ead9914af0b363ae6c831a34ccce189d2`** (SHA-1) for the *built* `build/GXXE01/main.dol` — i.e. this is the hash the finished build must reproduce to be "matching," not a hash of the input disc image itself. No separate input-disc-hash/CRC was found documented in the repo for GXXE01.
- The repo's legal notice is explicit: no ROMs/ISOs/copyrighted assets are included or should be added. This aligns with your instruction not to supply or download a game image.

## UPDATE 2026-07-23: build attempted and verified successful

Everything below this line supersedes the original "why I have not attempted a build" reasoning above (kept for history) — the user supplied their own legally-owned vanilla US Pokémon XD ISO (already in their possession, alongside their own separately-installed Dolphin copy at `C:\Users\psych\OneDrive\Desktop\apps\Dolphin-x64\`) and asked me to proceed through the full build.

**Result: success, independently re-verified by me.** `ninja` completed with `build/GXXE01/main.dol: OK` against the pinned SHA-1, and I separately ran `Get-FileHash -Algorithm SHA1` on the output myself: `FF9E752EAD9914AF0B363AE6C831A34CCCE189D2`, an exact match. Full details, real progress percentages, and the two rounds of troubleshooting it took to get there are in [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md)'s "UPDATE 2026-07-23" section — the short version is that Windows security (likely Controlled Folder Access, since this project lives under `Documents\`) blocked each freshly-downloaded build tool (`dtk.exe`, then separately `objdiff-cli.exe`) from writing files on its first run, and needed one-time user approval each time.

### What's now installed/present as a result

| Item | Status |
|---|---|
| `ninja` | 1.13.0, installed via system Python 3.14's pip. Not on `PATH` in this shell — invoked by full path (`C:\Users\psych\AppData\Local\Python\pythoncore-3.14-64\Scripts\ninja.exe`). Not added to `PATH` since that's a persistent environment change I didn't make without being asked specifically for it. |
| `extern/musyx` submodule | Initialized, commit `37e8ecd4e6503e90b97ea81cd7d669357861d501`. |
| `build\tools\dtk.exe` | Downloaded, `v1.7.4`. |
| `build\tools\objdiff-cli.exe` | Downloaded, `v3.4.0`. |
| `build\tools\sjiswrap.exe` | Downloaded, `v1.2.2`. |
| `build\compilers\` | Downloaded, the `compilers_20250812.zip` bundle (Metrowerks/CodeWarrior). |
| `orig/GXXE01/Pokémon XD - Gale of Darkness (2005)(Nintendo)(US).iso` | A **plain copy** (~1.1 GB) of the user's own ISO — not a hardlink (one was tried first, consistently failed for reasons that turned out to be the Windows-security issue above, not the hardlink itself in the end, but the copy was already in place by the time that was diagnosed and there was no reason to switch back). |
| `build/GXXE01/main.dol` | Built, hash-verified. |

Note: this is a build of **vanilla US Pokémon XD**, not Pokémon XG. It confirms `xd-decomp` genuinely works end-to-end on this machine and gives a verified, known-good baseline to diff future XG findings against — it does not by itself tell us anything new about XG (see [UNKNOWNS_AND_BLOCKERS.md](UNKNOWNS_AND_BLOCKERS.md), which is unchanged by this).

### Original "recommended next steps" (all now done, kept for history)

1. ~~`pip install ninja`~~ — done.
2. ~~Decide whether to run `python configure.py`~~ — done, with the user's explicit go-ahead.
3. ~~Place a legally-obtained GXXE01 disc image in `orig/GXXE01/`~~ — done, with the user's own vanilla XD image.

## Companion environment (Windows companion app, separate from the xd-decomp build above)

This section tracks the Python environment for the NVDA-facing companion under `Companion/` — unrelated to `xd-decomp`'s own build requirements above. These two toolchains are intentionally kept separate (different Python versions, different purposes).

### Why a second, older Python is involved

The system-wide Python is 3.14.6 (see above) and was **not changed or downgraded**. `dolphin-memory-engine` currently only publishes prebuilt binary wheels for Python 3.8–3.12; forcing an install under 3.14 would require a source build (not attempted, per instruction) and installing under the system interpreter would also mean managing dependencies globally rather than per-project. A second Python was installed side by side instead.

| Item | Value |
|---|---|
| System Python (unchanged) | 3.14.6, at `C:\Users\psych\AppData\Local\Python\pythoncore-3.14-64\python.exe` |
| Additional Python installed for this project | **3.12.10**, 64-bit, official installer `python-3.12.10-amd64.exe` from `python.org` |
| Additional Python location | `C:\Users\psych\AppData\Local\Programs\Python\Python312\python.exe` |
| Verification | `py -0p` lists both: `-V:3.14 *` (default) and `-V:3.12` |
| Project virtual environment | `PokemonXGAccessibility\Companion\.venv`, created with `py -3.12 -m venv Companion\.venv` |
| Venv's own Python version | 3.12.10 (confirmed via `Companion\.venv\Scripts\python.exe --version` and `pyvenv.cfg`) |

Note on tooling: creating the venv failed silently the first time it was attempted through the Bash tool (a `[WinError 2]` from Python's `venv` module, likely related to how that tool passes a path containing spaces — `pokemon xg accessibility` — to a Windows subprocess). It succeeded on retry through the PowerShell tool. If this project's setup is ever repeated, prefer PowerShell over Bash for venv/Windows-path-sensitive operations in this environment.

### Installed packages (inside `Companion/.venv` only — the system Python 3.14 and 3.12 installs themselves have no extra packages)

| Package | Exact version installed | Source |
|---|---|---|
| `dolphin-memory-engine` | **1.3.1** | PyPI (`henriquegemignani/py-dolphin-memory-engine`) — prebuilt `win_amd64` wheel for `cp39-abi3` (forward-compatible with 3.12) |
| `cytolk` | **0.1.13** | PyPI (`pauliyobo/cytolk`) — prebuilt `win_amd64` wheel for `cp312` |
| `pip` (in the venv) | 26.1.2 (upgraded from the venv's bundled 25.0.1) | Standard PyPI |

Recorded verbatim (also mirrored in [Companion/requirements.txt](../Companion/requirements.txt)):
```
cytolk==0.1.13
dolphin-memory-engine==1.3.1
```

### Confirmed APIs (by introspection, not assumed) — relevant for anything built on top of these later

- `dolphin_memory_engine`: `hook()`, `un_hook()`, `is_hooked() -> bool`, `get_status() -> DolphinStatus` (enum: `hooked=0`, `notRunning=1`, `noEmu=2`, `unHooked=3`), plus read/write functions (`read_byte/word/float/double/bytes`, `write_*`, `follow_pointers`, `MemWatch`) — **none of the read/write functions have been called against a real address in this project yet**, per your instruction.
- `cytolk.tolk`: `load()`, `is_loaded()`, `unload()`, `detect_screen_reader() -> Optional[str]`, `has_speech()`, `has_braille()`, `speak(text, interrupt=False)`, `braille(text)`, plus a `tolk.tolk()` context manager. Per the library's own documentation, calling most functions before `load()` raises an exception — the diagnostic script accounts for this.

### Diagnostic test results (2026-07-23, no Dolphin installed, NVDA running)

| Script | Result |
|---|---|
| `Companion/test_speech.py` | **Succeeded.** Detected screen reader: `NVDA`. Speech supported: `True`. Braille supported: `True`. `tolk.speak()` and `tolk.braille()` both returned `True`. Tolk unloaded cleanly on exit. **User confirmed audibly hearing NVDA speak the test message.** |
| `Companion/test_dolphin_connection.py` | **Succeeded as expected for "Dolphin not installed."** `get_status()` returned `DolphinStatus.notRunning`; `is_hooked()` returned `False`; script reported "Dolphin not found. This is expected — Dolphin is not installed/running yet." and released the (never-established) hook cleanly. No address was read or written. |

Neither script performs menu polling, hard-codes any game memory address, modifies Dolphin, or modifies the game — consistent with the current research/setup-only phase of this project.

## UPDATE 2026-07-23 (continued): live Dolphin testing session (Phase 0)

This section records the environment facts from the live Phase 0 investigation. Full narrative, evidence, and findings are in [PHASE_0_RESULTS.md](PHASE_0_RESULTS.md) — this is the environment-facts summary only.

### Dolphin versions tested

| Version | Context |
|---|---|
| `2503a` | Embedded version string extracted from `Dolphin.exe` (UTF-16/ASCII scan of the binary, since no version resource was stamped and `--version`/`--help` produced no usable console output). This is the version installed at the start of this session's live testing. |
| `2606` | After the user ran Dolphin's own built-in updater mid-session (their action, not mine). Confirmed via the window title (`Dolphin 2606 | ...`) after relaunch. |

Both versions exhibited the same disc-read failure against the bad ISO (see below) and both worked correctly once the ISO was replaced — the bad dump, not the Dolphin version, was the cause.

### The ISO saga: bad dump superseded by a verified-good replacement

**Original file (now superseded — do not use):** `Pokémon XD - Gale of Darkness (2005)(Nintendo)(US).iso`
- SHA-1: `FED1C3D7087250AAA20546A5A017410D7F0AE023` (verified identical between the user's original copy and this project's build-tree copy, both before and after troubleshooting — confirmed unmodified throughout)
- Size: 1,107,298,670 bytes
- `dtk disc verify` result: correctly identified as `GXXE01, Disc 1, Revision 0`, but **`Redump: Not found ❌`** — does not match the known-good preservation-verified dump for this game
- Diagnosis: Dolphin's own verbose log (`Logger.ini` with `DVD`/`BOOT`/`CORE` enabled, `WriteToFile = True`) showed the boot sequence reading progressively further into the disc, then stalling ~25 seconds on a 32-byte read at `DVDOffset=0x56336ba0` (≈1.347 GiB — beyond this file's actual 1.031 GiB size) before Dolphin gave up: `Requesting error... (0x00031100)`. This offset falls within where the disc's intro logo/movie files (`movie_tpc_logo.fsys`, `movie_gs_logo.fsys`, etc.) are expected to be. Conclusion: **this specific dump is missing real content**, most likely in the intro movie sequence — not something introduced by this project (hash was verified unchanged throughout troubleshooting), not a Dolphin-version bug (persisted across the 2503a→2606 update), and not a Windows-security issue (different error signature and behavior than the earlier build-tool-blocking issue).
- **This file has been deleted from `orig/GXXE01/`** and should not be used for further testing.

**Replacement file (current, verified-good):** `Pokemon XD - Gale of Darkness (USA).rvz`
- Format: RVZ (Dolphin's own compressed disc-image format), compression Zstandard, 128 KiB blocks, `Verification data: true` (created with embedded hash-verification data)
- Container file SHA-1 (of the compressed `.rvz` bytes themselves): `061DCF1C19928E7DFB0A7EDF31CF427F37EDE823`, size 960,244,616 bytes
- **Decompressed disc-content hashes** (via `dtk disc verify`, the figures that actually matter for identifying the disc content): CRC32 `c0f69d18` ✅, **SHA-1 `c1b5218f832403d15aa500ac4d6aacc8865c792d`** ✅, XXH64 `b24385e81a8d0cb5` ✅, and critically: **`Redump: Pokemon XD - Gale of Darkness (USA) ✅`** — this is a known-good, preservation-verified dump.
- Identity confirmed the same as before: `GXXE01, Disc 1, Revision 0`.
- Copied into `orig/GXXE01/`, byte-identity confirmed against the source file (`Get-FileHash` match).
- `xd-decomp` rebuilt against this file: `build/GXXE01/main.dol` still hash-matches `FF9E752EAD9914AF0B363AE6C831A34CCCE189D2` (re-verified independently by me). Same real decompilation-progress numbers as before (11.22% matched overall, 0.75% game code, 76.51% SDK code) — expected, since it's the same underlying game code, just from a complete source image this time.
- With this file, Dolphin boots correctly: intro plays, gameplay proceeds normally (confirmed by the user reaching the opening battle, a "press start" screen, and subsequent battle gameplay).

### Live `dolphin_memory_engine` attachment (confirmed against real, running emulation)

- `hook()` → `get_status()` returned `DolphinStatus.hooked` (not just `notRunning`/`noEmu` as in the earlier no-Dolphin-installed test) while the verified-good RVZ was running in Dolphin.
- `is_hooked()` → `True`.
- `un_hook()` called cleanly every time, in every script used this session (confirmed by code review — no script in this session omits the `finally: dme.un_hook()` pattern).
- Disc header read at `0x80000000` (the standard, non-game-specific GC disc-header location, not a guessed offset) returned Game ID `GXXE01`, disc 0, revision 0 — consistent with the file identity above.
- **No memory writes were performed at any point this session.** Every script used (`test_dolphin_connection.py` and the `Companion/_phase0_scratch_*.py` exploration scripts) calls only `hook`, `is_hooked`, `get_status`, `un_hook`, `read_bytes`, `read_word`, and `read_word`/`read_bytes` derivatives — none call `write_byte`, `write_word`, `write_bytes`, `write_float`, or `write_double`. This was true throughout, including during the memory-scanning work described in [PHASE_0_RESULTS.md](PHASE_0_RESULTS.md).
