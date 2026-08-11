# MILESTONE_SAVE_INDEX.md

**Status:** Living document. Created 2026-07-29. Tracks permanent saves and Dolphin save states used for development and live-test validation, so a barrier or a feature can be re-tested later without needing the project owner to replay back to that point.

## Current actual save/state inventory (verified 2026-07-29)

This project does **not** yet have a named-milestone save system. What exists today:

- **Live memory card save:** `save.sav` at the project root (top-level directory, ~27 MB), the project owner's actual, ongoing, unarchived playthrough save. This is overwritten continuously as they play — it is *not* a stable checkpoint and should not be assumed to represent any specific story point for future reference.
- **One Dolphin save state:** `GXXE01.s01` in `Dolphin Emulator/StateSaves/` — an anonymous slot-1 save, not labeled to a story point, not confirmed what moment it captures.
- **One auto-save-on-close state:** `lastState.sav` in the same directory — overwritten every time Dolphin closes, not a stable reference point.

Neither existing state has been deliberately captured *as* a milestone under this system. Until they are explicitly re-saved under one of the stable names below (with the fields in this document filled in from a real, verified capture), they should be treated as ordinary "current progress," not durable test fixtures.

## Stable name convention

When a save or state is deliberately captured as a milestone going forward, copy it to a clearly named file (not the anonymous `.s01` slot, which gets overwritten) and record it here with every field below filled in from direct verification — not assumption.

## Planned milestones (none captured yet)

All of the following are **planned** — placeholders for saves this project expects to want eventually, based on the game's known overall structure, not saves that exist today. Do not treat any of these as available until this document is updated with real file locations and a "last verified" date.

| Stable name | Status |
|---|---|
| `First_Free_Roam` | Planned — not yet captured |
| `First_Shop` | Planned — not yet captured |
| `First_Trainer_Battle` | Planned — not yet captured |
| `First_Shadow_Pokemon` | Planned — not yet captured. **Worth capturing soon:** the current live save already has a Shadow Pokémon (Teddiursa, lv. 11, not yet purified) — a good candidate moment to actually capture this milestone rather than continuing to defer it, especially since it's also the exact state needed to resume the on-hold Shadow-move-display investigation and to eventually audit the Shadow gauge/Hyper mode gap. |
| `First_Map_Menu` | Planned — not yet captured |
| `Gateon_Bridge` | Planned — not yet captured (story point not yet reached as of this writing) |
| `First_Purification` | Planned — not yet captured (story point not yet reached) |
| `Purify_Chamber` | Planned — not yet captured (story point not yet reached) |
| `First_PC_Storage` | Planned — not yet captured (PC has been reached and partially investigated this session — see [ACCESSIBILITY_COVERAGE_MATRIX.md](ACCESSIBILITY_COVERAGE_MATRIX.md)'s "PC and storage" section — but no dedicated save state was captured for it) |
| `First_Complex_Puzzle` | Planned — not yet captured (no puzzle beyond ordinary doors/elevators/warps has been encountered yet) |
| `Late_Game_Battle` | Planned — not yet captured |

## Record format for when a milestone is actually captured

```
### <Stable_Name>

- Game location:
- Story point:
- Immediately reachable screen or mechanic:
- Why this save matters:
- Preconditions:
- Memory-card save or Dolphin save state: (file name, slot, or GCI)
- File location: (absolute path)
- Game build: (vanilla GXXE01 rev 0 / XG — state which, and how confirmed)
- Known risks: (e.g. "overwriting slot 1 will lose this — copy out before reusing the slot")
- Last verified date:
```

## Notes on maintaining this index

- Never overwrite a captured milestone's file to test something else — copy the anonymous slot forward, or use a fresh named slot, so a milestone remains re-testable indefinitely.
- When a milestone is captured specifically because a barrier was found near it, cross-reference the relevant entry in [PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md).
- A milestone should be captured at the moment a barrier is recorded (per the discovery-driven development cycle in [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md)) whenever practical, not retroactively — retroactive capture after progressing past the moment is often not possible in a single-save-slot game.
