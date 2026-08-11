# INTERACTION_DIAGNOSTIC.md

The development-only tool that scores entity navigation's predictions
against what the game actually does. **Phase 2, 2026-08-06.**

---

## Why it exists

Phase 1 found four independent reasons an NPC could be announced as
reachable when it was not, but could not establish their relative weight:
nothing in 367 MB of logs recorded whether an A press actually landed. Any
fix chosen without that evidence would be a guess about which cause
mattered.

This closes the gap. It logs the complete talk-predicate state for the
selected NPC, and lets the project owner mark the exact moment they press
A so the prediction can be scored against the real outcome.

## Safety

- **Read-only.** Never writes memory, never sends input, never presses A.
  `test_interaction_diagnostics.SafetyTests` asserts the module contains no
  input-sending call.
- **Off by default.** Without `--interaction-diagnostics` the reader is
  never constructed and nothing is logged.
- **Isolated.** `poll_interaction_diagnostics` catches `MemoryError` like
  every other reader; a diagnostic must never take the narrator down.
- **Observer only.** It reads the navigator's published selection through
  an injected callable and the same runtime/pose objects the navigator is
  using — not a second set with its own caches, which could disagree with
  what the player actually heard.

## Enabling it

```bash
python Companion/run_battle_narrator.py --interaction-diagnostics
```

Marker hotkey defaults to `ctrl+shift+k` (`--interaction-mark-hotkey`).
Deliberately not an entity-nav chord: it has to be pressable immediately
before or after A without disturbing the selection being measured.
`ctrl+shift+m` was the obvious choice and is already the money summary.

## What a sample records

One `INTERACTION DIAG` line per 0.5 s while an NPC is selected:

| Field | Meaning |
|---|---|
| `room=` | room code |
| `identity=` `gen=` | canonical `(groupID, resID)` and runtime generation |
| `work=` `slot=` | live `tagPeopleWork` address and slot |
| `group=` `res=` `info=` | the three identity/type fields |
| `name_id=` `talk_sct=` | name id and **talk script id** (settles the `talk_<N>` question) |
| `model=` | live model position |
| `static=` `drift=` | scripted spawn point and how far the actor has moved from it |
| `neck=` `neck_offset=` | resolved neck reference and its horizontal offset from the model position |
| `hero=` `facing=` `yaw=` | player position, hero rot.y, camera yaw |
| `dist3d=` `dist_h=` | 3-D distance (what the game uses) and horizontal (what the old code used) |
| `hero_ball=` `npc_ball=` | both collision-ball sizes |
| `talk_live=` `talk_static=` | `people_work +0x178` vs `people_info +0x24` |
| `threshold=` | the computed three-term threshold |
| `flags=` `bit0=` | `people_work +0x10` and its talk-suppression bit |
| `disp=` `static_visible=` `load_init=` | live and static visibility |
| `start_type=` `wall_through=` `wall_blocked=` | talk-start type and the wall gate |
| `facing_error=` | degrees off the 40° cone |
| `ELIGIBLE=` `reason=` `unknown=` | the verdict, the rejecting gate, and any gate that could not be checked |

An `INTERACTION DIAG NAV` line is emitted alongside when the navigator's
own in-range claim is supplied, with `AGREE=` comparing the two.

## What a marker records

Pressing the marker logs:

```
INTERACTION MARK identity=(7, 0) predicted_eligible=True reason=None
  dist3d=6.41 threshold=10.00 facing_error=12.3 -- watching 3.0s for dialogue
```

then, within three seconds, exactly one of:

```
INTERACTION MARK RESULT ... outcome=DIALOGUE_OPENED elapsed=0.183s AGREES=True
INTERACTION MARK RESULT ... outcome=NO_DIALOGUE    elapsed=3.001s AGREES=True
```

`AGREES` is the whole point: `True` means the prediction matched reality
(predicted eligible and dialogue opened, or predicted ineligible and
nothing happened). A run of `AGREES=False` is the signal that a gate is
still wrong.

## The three questions it is meant to settle

1. **`neck_offset`** — how far the neck reference actually sits from the
   model position. If it is consistently well under a game unit, the neck
   reference is a correctness improvement rather than the dominant fix.
   Expected small; not assumed either way.
2. **`talk_live` vs `talk_static`** — whether `people_work +0x178` is
   initialised from `people_info +0x24`. Currently unverified; the live
   value is what the predicate uses regardless.
3. **`talk_sct`** — whether live talk script ids match the `talk_<N>_`
   numbers in the extracted script dumps, which the role table depends on.
   In Agate's Mart the clerk should read `talk_sct=122`.

## Scope

NPC selections only. Other categories carry no talk predicate; extending
the diagnostic to treasure (which does go through `peopleTalkCheck`, with
an extra facing gate for kind-1 boxes) is Phase 3 work.
