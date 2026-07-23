# REPOSITORY_AUDIT.md

Audit of the two cloned repositories as of the commit hashes below. Investigation date: 2026-07-23.

## Clone record

| Repo | Path | Remote | Default branch | HEAD commit | HEAD commit date |
|---|---|---|---|---|---|
| Primary | `PokemonXGAccessibility/xd-decomp/` | `https://github.com/TeamOrre/xd-decomp.git` | `main` | `017351246c9a48fd8e7f68bbf600652d413752f3` | 2026-05-24 15:19:09 -0400 |
| Secondary (research reference only) | `PokemonXGAccessibility/Pokemon-XD-Code/` | `https://github.com/PekanMmd/Pokemon-XD-Code.git` | `master` | `f2d6c4af0b6bdd78717fb41f7be7cc14aa5476a0` | 2024-09-02 00:29:49 +0100 |

Both cloned as full clones (not shallow) with `git clone` (no `--recurse-submodules` flag was passed for xd-decomp — see submodule note below).

**Note on `Pokemon-XD-Code`:** its last commit is from September 2024, nearly two years old at the time of this audit, while `xd-decomp` was updated in May 2026. Treat it strictly as historical/community research reference material, consistent with your instruction — not as an active or primary codebase.

**Submodule note:** `xd-decomp/.gitmodules` declares one submodule, `extern/musyx` → `https://github.com/AxioDL/musyx.git` (the MusyX sound engine, used by `MusyX()` library objects in `configure.py`). Since I cloned without `--recurse-submodules`, **this submodule is currently uninitialized/empty** in the local clone. The README's documented clone command is `git clone --recurse-submodules ...` — I did not do this, so `extern/musyx` needs `git submodule update --init` before a real build would get past the MusyX library objects. Flagging rather than doing it, since it's an additional network fetch.

## xd-decomp: build system identity

This is an instance of the **dtk-template** (decomp-toolkit) build system — the same generic framework used by many GameCube/Wii matching-decompilation projects (confirmed by the header comment in `tools/project.py:1-11`: "shared between multiple projects... submit a PR to encounter/dtk-template"). If you have any familiarity with other GC/Wii decomps (Metroid Prime, Super Mario Sunshine, Pikmin, etc.), the workflow here is structurally identical.

- **Config path:** `config/GXXE01/config.yml` — points at `object_base: orig/GXXE01`, `object: sys/main.dol`, expects hash `ff9e752ead9914af0b363ae6c831a34ccce189d2`.
- **Symbol map:** `config/GXXE01/symbols.txt` — 21,539 lines. Format: `symbol_name = section:0xADDRESS; // type:TYPE size:0xSIZE scope:SCOPE`, e.g. `menuTitle = .text:0x800A35FC; // type:function size:... scope:global` (exact line format confirmed by direct read).
- **Splits map:** `config/GXXE01/splits.txt` — 131,375 bytes. Defines exact `.text`/`.data`/`.rodata`/`.bss`/etc. address ranges per source object, e.g. `game/dbgMenuCamera.cpp: .text start:0x800056A4 end:0x80005798` — confirmed present **even for files that don't exist in `src/` yet**. This means the toolchain already knows precisely where in the retail binary's address space every named function/object lives, independent of whether it has been reverse-engineered into C.

## How the build handles undecompiled code (confirmed by reading `tools/project.py`)

This is the most important mechanical fact for planning any accessibility hook, so I traced it directly in code rather than assuming:

- `tools/project.py:1113-1155` (`add_unit`): for every object, if a real source file exists under `src/` it's compiled; if not, and `config.non_matching` wasn't passed, it falls through to `elif obj_path is not None: link_step.add(Path(obj_path))` — **the original, pre-extracted machine code object is linked in as-is.**
- That `obj_path` is produced by `dtk` splitting the user-supplied `orig/GXXE01` disc image according to `splits.txt`'s address ranges (this is the standard dtk-template extraction step; I did not re-derive dtk's internals beyond confirming this call site and its inputs/outputs).
- **Conclusion (Confirmed by code reading, not yet verified by an actual build):** the project is designed so that, once configured and built against a correct disc image, it can produce a **fully working, byte-identical `main.dol`** at essentially any stage of decompilation progress — including today's, where almost none of the game-logic (`game/`) layer has real C source. Undecompiled functions ship as the original bytes, not as broken stubs. This is exactly why the README frames this project's primary goal as "produce a matching retail binary," not "reimplement the game."
- The `--non-matching` flag (and its `asm_dir` override) exists specifically for **modded/equivalent builds** (`configure.py:117-121`: `"builds equivalent (but non-matching) or modded objects"`) — i.e., the project has an explicit, intended path for producing a *modified* (not necessarily byte-matching) `main.dol`, which is directly relevant to Part 3/4 below.

## Current decompilation completion status (Confirmed by direct file count, not by the badges)

| Measure | Count |
|---|---|
| Total `Object(...)` build entries declared in `configure.py` | 737 |
| ...of which explicitly `NonMatching` | 632 |
| ...of which version-conditional `MatchingFor(...)` (matches for specific versions, e.g. GXXE01/NXXJ01) | 105 |
| Distinct `"game/..."` paths referenced by the object list | 522 |
| Actual files existing under `src/game/` on disk | **8** |
| Actual files existing under `src/dolphin/` on disk (GameCube SDK — separate from game logic) | ~198 |
| Actual files existing under `include/game/` on disk | ~18 |

The 8 real `src/game/` files are all under `src/game/pxdvs/app/{hero,kaisuu,pokemon}/`:
`heroMemberFunctions.cpp`, `kaisuu.cpp`, `kaisuuBios.cpp`, `kaisuuData.c`, `pokemon.cpp`, `pokemonBios.cpp`, `pokemonDB.cpp`, `pokemonStatusPokemon.cpp`.

**Reading:** the SDK (Dolphin/OS/Pad/GX/etc.) layer is substantially decompiled — this is shared, well-understood GameCube SDK code common across many decomp projects and ports over relatively quickly. The **game-logic layer (menus, battle, field/overworld, debug menus) is almost entirely undecompiled** — only a narrow slice of Pokémon-data-model code (species/move/party data structures) exists as real source today. The project's own progress badges in `README.md` (`decomp.dev` shields for "Code (US)" / "Data (US)") track this precisely and should be treated as the authoritative live number — I did not fetch those badge values since they require a network image render; the file-count method above is what I could verify directly and is consistent with "early stage" for game code.

## Answers to Part 1, item 3 (the specific checklist)

| Question | Answer | Confidence |
|---|---|---|
| Required Python version | No version pin found anywhere in the repo; only stdlib is used (`argparse`, `pathlib`, `typing`, `urllib.request`, `zipfile`, `json`, `re`, `platform`, `shutil`, `os`, `sys`, `io`, `stat`, `fnmatch`). Python 3.14.6 (installed here) satisfies it. | Confirmed |
| Ninja requirements | Required; not pinned to a specific ninja version in the repo; obtained via `pip install ninja` or GitHub releases per README. Not installed on this machine. | Confirmed |
| Compiler requirements | Metrowerks/CodeWarrior GC compilers, multiple pinned `mw_version`s (`GC/1.2.5n`, `GC/1.3.2`, `GC/2.6`), fetched as a bundle (`compilers_20250812.zip`) from `files.decomp.dev`, not from Nintendo/Metrowerks directly, and not yet downloaded. | Confirmed |
| Platform-specific dependencies | Windows: none beyond Python+Ninja ("native tooling," WSL/msys2 explicitly discouraged). macOS/Linux: `wibo` (32-bit Windows binary wrapper) auto-downloaded, not needed on Windows. | Confirmed (README) |
| Expected original-game files | User-supplied disc image in `orig/GXXE01/`, one of ISO/RVZ/WIA/WBFS/CISO/NFS/GCZ/TGC. Currently empty (only `.gitkeep`). | Confirmed |
| Expected filenames/hashes/revisions | Target hash is for the **built** `main.dol` (`ff9e752ead9914af0b363ae6c831a34ccce189d2`), not the input disc image. Supported revisions: `GXXE01` Rev 0 (US retail) and `NXXJ01` (JP demo disc) only. No XG-specific config exists. | Confirmed |
| Build and verification commands | `python configure.py` (optionally `--version NXXJ01`), then `ninja`. Verification/diffing via `objdiff` (separate download) against `objdiff.json`, generated after first successful build. CI (`​.github/workflows/build.yml`) additionally runs `ninja all_source progress build/${version}/report.json` inside a private prebuilt container (`ghcr.io/teamorre/xd-decomp-build:main`) with `/orig` and `/binutils`/`/compilers` already present — i.e., CI has always-available disc images and toolchains that a local contributor must source themselves. | Confirmed |
| Current decompilation completion status | Game-logic layer: ~8 of 522+ referenced game-code files have real source (very early). SDK layer: substantially further along (~198 real files). See table above. | Confirmed by file count; exact percentage is tracked by the project's own `decomp.dev` progress badges, which I did not query. |
| Can it produce a modified/shifted `main.dol`? | Yes, by design — the `--non-matching`/`asm_dir` mechanism exists explicitly for "modded objects," and the default build already links non-decompiled functions as extracted-original bytes, so incremental modification of individually-decompiled functions is the intended workflow once you have a working baseline build. | Confirmed by code reading in `tools/project.py`/`configure.py`; **not yet verified by an actual successful build** (no disc image available). |
| Does it support adding new code, or only matching the original binary? | The project's stated goal is matching. It has an explicit modding escape hatch (`--non-matching`), but I found no framework in this repo for injecting **wholly new functions/hooks** (e.g., no REL-injection helper, no code-cave/trampoline tooling, no Gecko-code generation). Adding genuinely new logic (as opposed to modifying/replacing an already-matched function) is not something this repo currently provides tooling for. | Confirmed absence within this repo; does not rule out such tooling existing elsewhere (e.g., in the broader decomp/modding community) — Unknown beyond that. |

## Build attempt status — UPDATE 2026-07-23: actually built and independently verified

The original audit above (and [ENVIRONMENT.md](ENVIRONMENT.md)) described why no build had been attempted: no disc image, `ninja` not installed, submodule not initialized. All of that has since changed. The user supplied their own legally-owned vanilla US Pokémon XD GameCube disc image (already in their possession, installed alongside their own Dolphin copy — not downloaded by me), and asked me to proceed through the full setup. Steps actually performed, in order:

1. `pip install ninja` (system Python 3.14) — ninja 1.13.0 installed. Its console-script wrapper isn't on `PATH` in this shell session, so it was invoked by full path (`...\Scripts\ninja.exe`) rather than adding anything to `PATH`.
2. `git submodule update --init` — initialized `extern/musyx` at commit `37e8ecd4e6503e90b97ea81cd7d669357861d501`.
3. The user's ISO was placed at `orig/GXXE01/Pokémon XD - Gale of Darkness (2005)(Nintendo)(US).iso` as a **plain copy** (not a hardlink — a hardlink to the OneDrive-synced original was tried first and consistently failed; see the troubleshooting note below).
4. `python configure.py` (default GXXE01 target) — succeeded, generated `build.ninja`.
5. `ninja` — after two rounds of troubleshooting (see below), **succeeded**: `[2/4] CHECK config\GXXE01\build.sha1` → `build/GXXE01/main.dol: OK`.

**Independently re-verified, not just trusted from the tool's own report:** I ran `Get-FileHash -Algorithm SHA1` on the produced `build/GXXE01/main.dol` myself. Result: `FF9E752EAD9914AF0B363AE6C831A34CCCE189D2` — an exact match (case-insensitive) to the pinned hash in `config/GXXE01/build.sha1`. **This project genuinely builds a byte-identical copy of the retail US Pokémon XD GXXE01 `main.dol` on this machine, from source, given the user's own disc image.** This is no longer a claim inferred from the README or CI — it's something I built and checked myself.

**Real, freshly-measured decompilation progress** (from the build's own `PROGRESS` step, not the file-count heuristic used earlier in this document):

| Category | Matched | Linked | Files |
|---|---|---|---|
| All | 11.22% | 8.13% | 104 / 737 |
| Game Code | 0.75% | 0.01% | 3 / 522 |
| SDK Code | 76.51% | 58.79% | 101 / 215 |

Note "Game Code: 3/522 matched" is slightly lower than the "8 real source files" figure cited earlier in this document — "matched" specifically means the compiled object is byte-identical to the original at the object/file level (per `objdiff`), which is a stricter bar than "a `.cpp` file exists and compiles." Some of the 8 existing game-code source files apparently don't yet fully byte-match, even though they compile and link.

### Troubleshooting notes (worth keeping for future reference)

- **First attempt** failed at disc extraction: `dtk.exe dol split` errored `Failed to create directory 'orig\GXXE01\sys'` / `The system cannot find the file specified (os error 2)`, reproducible 3 times in a row (once via hardlink, once via plain copy — ruling out a OneDrive/reparse-point cause). Manual `mkdir` in the same folder worked fine via PowerShell.
- **Root cause (per the user): Windows security (Controlled Folder Access or similar) blocking freshly-downloaded, unrecognized executables from creating files/folders under the `Documents` tree.** This project's path is under `Documents\My Games\...`, a commonly-protected folder. Once the user allowed `dtk.exe` through, disc extraction and compilation succeeded (124/133 objects built) but the **next** freshly-downloaded tool, `objdiff-cli.exe`, hit the identical error class at its own file-write step (`build\GXXE01\report.json`). Once the user allowed that one through too, the build completed end to end. **Pattern: each newly-downloaded build tool needs its own one-time security approval on this machine, not just the first one.**
- If this build is ever redone from scratch (e.g. a clean clone), expect to need to approve `dtk.exe`, `objdiff-cli.exe`, and possibly `sjiswrap.exe`/binutils individually if they trigger the same protection.

## The critical version-mismatch caveat (ties into UNKNOWNS_AND_BLOCKERS.md)

Everything in `xd-decomp` — symbols, splits, the target hash — is scoped to **unmodified retail US Pokémon XD (GXXE01 Rev 0)** and the JP demo (`NXXJ01`). Pokémon XG: NeXt Gen is a ROM hack of unknown revision/build process. Two possibilities, both currently **Unknown**, not to be assumed:

- If XG was built as a patch/mod layered on a specific GXXE01 Rev 0 image without relocating existing code (common for hacks that only replace data tables, text, or small routines in-place), then many `xd-decomp` addresses/symbols may still line up with what's actually running in XG.
- If XG shifts, expands, or recompiles any part of the code segment (common when a hack adds substantial new logic, needs more space than the original section, or targets a different base revision), addresses will diverge, potentially significantly and unpredictably, from `xd-decomp`'s map.

**This project cannot determine which is true without your XG disc image.** Nothing here should be treated as verified to apply to XG until checked against it directly (see FIRST_VERTICAL_SLICE.md for the proposed verification experiment).
