# Pokémon XD: Game in Darkness

A screen-reader companion that makes **Pokémon XD: Gale of Darkness** and
the **XG: NeXt Gen** ROM hack playable by blind and low-vision players. It
runs beside Dolphin, reads the game's live state out of emulated memory,
and speaks it through NVDA.

It only ever reads. It does not write to the game, modify your disc image,
alter Dolphin, or send anything over the network. Two features are the
deliberate exception — Autowalk and Teleport move your character — and
both are opt-in, on their own keys, documented as exceptions in the code
that implements them.

**No game data of any kind is in this repository.** The companion needs
the game's own text, item, move and collision tables; those are
copyrighted, so each player generates them locally from the disc image
they already own.

---

## For players

Download a release, extract it, run `Setup.cmd`, run
`Launch Accessible XD.cmd`. You need Windows, NVDA, Dolphin, and your own
copy of the game. **You do not need to install Python** — a release brings
its own, and setup needs no internet connection.

Full instructions, hotkeys and troubleshooting are in
[README.txt](README.txt), which is also what ships inside the release. It
is deliberately plain ASCII text with no Markdown syntax or tables, so it
reads cleanly in Notepad and through a screen reader.

## What it reads out

- **Battles** — move menus with type and PP, damage and HP as
  percentages, stat changes, status, faints, Shadow moves and Heart
  Gauge, how many Pokémon the opponent brought, and what each target
  actually is while you are aiming at it.
- **The overworld** — a navigable list of nearby NPCs, items, doors,
  warps, elevators, PCs and shops, with a steerable audio beacon,
  terrain footsteps, and a routed navigation guide that refuses to
  invent a route it cannot walk.
- **Menus and screens** — the bag, shops, the party list and summary,
  the PC and Purify Chamber, the P✩DA, and the title screen.
- **Dialogue** — NPC conversations, spoken per page with the speaker
  named.
- **Its own settings** — a spoken settings menu on `F1`, including a
  Sound library that plays every non-speech cue and says what it means.

---

## For developers

### Running from a checkout

```bash
Setup.cmd
```

In a checkout there is no bundled `Runtime/`, so this builds
`Companion/.venv` and needs Python 3.12 — **specifically 3.12**, because
`dolphin-memory-engine` publishes no wheel past it. Both entry points
prefer `Runtime/` when present and fall back to `.venv`, so a checkout and
an extracted release both work.

### Running the tests

`Companion/tests/` has no `__init__.py` and the tests import
`battle_narrator.*`, so the obvious invocations collect nothing. Discover
from the tests directory with `Companion` on `sys.path`:

```bash
Companion/.venv/Scripts/python.exe -c "import sys,unittest;sys.path.insert(0,'Companion');unittest.main(module=None,argv=['x','discover','-s','Companion/tests','-t','Companion/tests'])"
```

Roughly 1,900 tests, about three minutes. Two failures in
`test_passability.DestinationProjectionTests` are pre-existing and
unrelated to anything outside `pathfinding.py` / `collision_probe.py`;
treat "2 failures, both of those" as the green baseline.

**Always subclass `unittest.TestCase`.** A bare `def test_*()` is not
collected by unittest discovery, so it never runs and never fails. That is
exactly how a PC box-grid addressing bug once survived — every box cell
decoded the same address, with a test file that looked like coverage.

### Building a release

```bash
Build Accessibility Release.cmd
```

Writes to a sibling `Accessibility Releases` folder, outside the project.
The builder works from an allowlist (`Tools/release-manifest.txt`) and
refuses to produce an archive unless every check passes — no forbidden
content, beacon sounds complete, footsteps complete *and* resolvable, and
the staged tree importable **on the staged runtime**. See
[README-DISTRIBUTION.md](README-DISTRIBUTION.md).

---

## How it is put together

| Concern | Where |
|---|---|
| Live memory reading, per-build addresses | `Companion/battle_narrator/profile.py`, `memory.py` |
| Which build is running | `battle_narrator/game_build.py` |
| Entity navigation, routing, beacons | `entity_nav.py`, `pathfinding.py`, `npc_beacons.py` |
| Speech | `speech.py`, `messages.py` |
| First run and discovery | `Companion/setup_companion.py`, `setup_discovery.py` |
| Generating game data from a disc | `Companion/bootstrap_game_data.py` |
| Release pipeline | `Tools/` |

### Documentation

The design record lives in [`Documentation/`](Documentation/) and is
treated as part of the work, not a summary of it.

- **[MASTER.md](Documentation/MASTER.md)** — start here. One entry per
  feature: what it does for the player, which module owns it, how it is
  verified, and what is still open.
- **[INDEX.md](Documentation/INDEX.md)** — the full map.
- **[XG_COMPATIBILITY.md](Documentation/XG_COMPATIBILITY.md)** — whether
  any of this works on XG, and the **normative data-sourcing rules** that
  came out of finding that it mostly does. Read its "Data sourcing rules"
  section before touching any loader.
- **[FIRST_RUN_AND_RUNTIME.md](Documentation/FIRST_RUN_AND_RUNTIME.md)** —
  how a player gets from a zip to a running game, and the bundled Python.
- **[ACCESSIBILITY_COVERAGE_MATRIX.md](Documentation/ACCESSIBILITY_COVERAGE_MATRIX.md)**
  — authoritative per-screen status.
- **[ACCESSIBILITY_BACKLOG.md](Documentation/ACCESSIBILITY_BACKLOG.md)** —
  what is open, including diagnosed-but-unfixed findings.

---

## How things get believed here

This project reverse-engineers a commercial game with no source. The
standing rules exist because each was learned by shipping the mistake:

- **Derive from the image in hand; never from a constant that was true of
  one build.** XG keeps the engine layout but not the data shapes — it
  packs 106 abilities into the space vanilla used for 78. Four separate
  defects were the same mistake in different structures.
- **A disc label is neither necessary nor sufficient.** Two different
  vanilla XD builds ship under the same `GXXE01`, and XG relabels nothing.
  Identify builds by fingerprint, not by name.
- **Agreement from a second code path is not verification.** A check that
  passes because a *different* branch covered for it has not been tested.
  Confirm the branch you think you are exercising actually ran.
- **State what is unverified.** Documents here carry explicit
  "not verified" sections, and features that are implemented but not
  live-tested say so.

---

## Licence and credits

MIT — see [LICENSE](LICENSE).

Beacon and footstep sounds are the project's own, except the "Video game
beeps" pack by the Freesound user **Mossy4**, used under CC-BY 4.0. The
attribution in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) is a
licence obligation, not a courtesy.

Pokémon and Pokémon XD are trademarks of Nintendo, Creatures Inc. and
GAME FREAK Inc. This project is not affiliated with, endorsed by, or
connected to any of them, and distributes no game code or game data.
