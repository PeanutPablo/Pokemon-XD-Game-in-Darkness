# PHASE_0_RESULTS.md

Detailed record of the live, read-only Phase 0 investigation against a verified vanilla US Pokémon XD (GXXE01, Revision 0) image, run in Dolphin. This document is the primary evidence trail; [ENVIRONMENT.md](ENVIRONMENT.md) carries the environment-facts summary and [ACCESSIBILITY_HOOKS.md](ACCESSIBILITY_HOOKS.md)/[ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md) fold the findings back into the broader code map. Investigation date: 2026-07-23.

**Scope discipline, stated up front and binding for the rest of this document:** everything here is a runtime observation against a specific, verified vanilla US GXXE01 build, under Dolphin 2503a/2606, on this specific machine, on this specific play session. **Nothing in this document should be read as applying to Pokémon XG.** XG's revision, code layout, and memory addresses are unconfirmed and may differ arbitrarily from what's recorded here (see [UNKNOWNS_AND_BLOCKERS.md](UNKNOWNS_AND_BLOCKERS.md)). Every address below is labeled with its confidence level for vanilla XD specifically; none are labeled or should be treated as XG-compatible.

**Safety discipline, also binding:** no ISO/RVZ modification, no rebuild-in-place, no memory writes, no Gecko/Action Replay codes, no save editing, no binary patches were performed at any point in this investigation. Every script used is read-only — verified by direct code review (see "No-writes audit" at the end of this document).

## Phase 0A — Runtime attachment (fully confirmed)

| Item | Result |
|---|---|
| Dolphin versions tested | `2503a` (session start) and `2606` (after the user's own in-app update mid-session) |
| Game image | `Pokemon XD - Gale of Darkness (USA).rvz` — see [ENVIRONMENT.md](ENVIRONMENT.md) for the full ISO saga (an earlier, differently-named `.iso` file turned out to be an incomplete/non-Redump-matching dump and was superseded; this `.rvz` is Redump-verified) |
| Verified disc-content identity | Game ID `GXXE01`, Disc 1, Revision 0 (via `dtk disc verify`); disc header independently re-confirmed by reading RAM directly at the standard `0x80000000` GC header location: `GXXE01`, disc 0, revision 0 |
| Verified disc-content SHA-1 | `c1b5218f832403d15aa500ac4d6aacc8865c792d` (matches Redump exactly) |
| `xd-decomp` build against this image | `build/GXXE01/main.dol` hash-verified: `FF9E752EAD9914AF0B363AE6C831A34CCCE189D2`, matching the project's own pinned hash, re-checked independently via `Get-FileHash` |
| `dolphin_memory_engine.hook()` | Succeeded — `get_status()` returned `DolphinStatus.hooked` while the game was running |
| `is_hooked()` | `True` |
| `un_hook()` | Called and succeeded cleanly every single time a script ran, across the entire session |
| Memory writes performed | **None.** Confirmed by code review of every script used (see "No-writes audit" below) |

**Conclusion: Confirmed.** Runtime attachment to a live, correctly-identified, hash-verified vanilla GXXE01 Rev 0 session works cleanly and repeatably via `dolphin_memory_engine`, with no writes.

## Phase 0B — Validating a known game-state structure (HP): partial, Inferred

### The hypothesis that was tested and refuted

**Starting hypothesis** (from `xd-decomp`'s own resolved symbols, see [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md) category 7): a static `Hero` class instance — either `_orreHero` (`.bss:0x8043C930`, size `0x978`) or `_menuCtrlHero` (`.bss:0x804B00A4`, same size) — holding `partyPokemon[6]` at offset `+0x30`, with `Pokemon.hp` at `+0x4` and `Pokemon.condition` at `+0x16` within each 0xC4-byte Pokémon struct. A candidate global pointer, `g_pHero` (`.sbss:0x804EBBE0`, scope:global), was hypothesized to point at whichever `Hero` instance was currently "live."

**What was actually observed, live:**
- Before any game session was active (still on boot screens), `g_pHero` read `0x00000000` and both `_orreHero`/`_menuCtrlHero` read all zeros — consistent with an uninitialized pre-session state, not yet informative either way.
- **Once a real game session was active** (after the intro battle had been played), `g_pHero` became a genuine, non-null, live pointer: `0x80CD6160`. This confirms `g_pHero` is a real, actively-used global.
- However, `g_pHero`'s target does **not** match either static candidate address (`_orreHero`/`_menuCtrlHero` continued reading all zeros even during active gameplay), and a raw hex dump of the memory at `0x80CD6160` does **not** match the hypothesized `Hero`/`Pokemon` struct layout at all: it shows a repeating ~0xB0-byte pattern beginning with a 4-byte zero field followed by a self-referential pointer (each block points to its own start address), interspersed with floating-point values that shift slightly between reads (consistent with position/rotation data for some kind of battle-actor array), not the integer-heavy `Hero`/`Pokemon` field layout `xd-decomp`'s header describes.

**Verdict: hypothesis refuted, not confirmed.** `g_pHero` is real and live, but does not lead to the party-storage `Hero` struct via the assumed offset, at least not during battle. This is recorded as a negative result deliberately — per the investigation's own methodology, a plausible symbol name is not evidence of a matching runtime layout until checked, and this is a concrete case of that check failing.

### The candidate that was actually found (via brute-force scanning, unrelated to the above)

**Method:** full-MEM1 (24 MiB, `0x80000000`–`0x817FFFFF`) snapshot-and-diff, taken with Dolphin's own emulation genuinely paused between reads (unpaused diffs were far too noisy — continuous animation/audio/particle state changes produced 150,000+ candidate addresses from a single hit, even restricted to a plausible HP-sized delta range). Even paused, a single hit's diff was still ~150,000–260,000 candidates (attack animations touch a surprising amount of transient state). Narrowing required a "decreased by a plausible amount on two separate, consecutive controlled hits" filter (5,864 candidates), followed by manual inspection of the surrounding memory window for the most narratively-consistent candidate (no separate stable "max HP" companion field was found nearby, so this could not be narrowed further by that route).

**Candidate addresses:** `0x804454B4` and `0x804454BC` — two addresses 8 bytes apart, holding **identical values in every single observation** (strongly suggesting a mirrored/duplicated field, a common pattern for a stat used both in live calculation and in on-screen display).

**Observed value sequence, across four controlled reads during a real battle (Salamence vs. a wild/trainer Metagross):**

| Reading | Value | Context |
|---|---|---|
| 1 (baseline) | 590 | Before any hit in this test sequence |
| 2 | 170 | After one hit (delta −420) |
| 3 | 125 | After a second hit (delta −45) |
| 4 | 53 | After the user reported taking poison damage (Sludge Bomb inflicted the poison status) and then using Earthquake to knock out the opposing Metagross (delta −72) |

**Why reading 4 is the strongest evidence:** standard poison damage in this game family is 1/8 of the Pokémon's maximum HP per turn. With a hypothesized max HP near 590, 1/8 ≈ 73.75 — within 2 points of the observed −72 delta. This is a specific, falsifiable, quantitative prediction that held, not just a "the number went down" observation.

**Why this remains labeled Inferred, not Confirmed:**
1. No struct-level confirmation — this address was found by brute-force scanning, not by tracing from a known struct/symbol, so its relationship to the `Pokemon.hp` field `xd-decomp` describes (or to any named symbol at all) is unestablished.
2. Whose HP this is has not been directly confirmed, only inferred from context — reasoning: the value dropped from poison, and poison damages the poisoned Pokémon (per the user's account, Salamence was the one poisoned), so this is very likely Salamence's (the player's own Pokémon's) live HP, not Metagross's. This inference is strong but not independently checked (e.g. by also confirming the *other* Pokémon's HP at 0 after the KO, which was attempted and not resolved — see below).
3. No stable "max HP" companion field was located nearby to corroborate the 590-ish starting value structurally, only numerically (via the poison-damage arithmetic).
4. The mirrored pair at `+8` bytes is unexplained — could be a legitimate display/calculation duplicate, or could be coincidental.
5. **Not tested across a Dolphin/game restart.** The address may or may not be a stable, session-independent location — this needs verification before being relied on for anything beyond this single play session.

**What was searched for and not found:**
- Metagross's (the opponent's) HP address — an attempt to find "a value that drops to exactly 0" after the KO produced 66,544 candidates (battle-end transitions reset enormous amounts of unrelated state: victory fanfare, EXP counters, animation flags), too noisy to narrow further within this session.
- A stable "max HP" field near `0x804454B4`/`0x804454BC` — the surrounding ±0x60-byte window was inspected value-by-value; nothing held constant at 590 (or any other plausible max-HP-like value) across all snapshots.

### Explicit non-transferability statement (per explicit instruction)

**`0x804454B4` and `0x804454BC` are not to be treated as universal, stable, or Pokémon-XG-compatible addresses.** They are runtime observations made against one specific vanilla US GXXE01 Revision 0 session, under Dolphin 2503a/2606, on 2026-07-23, and have not been verified to survive even a same-game restart yet, let alone a different game/hack. Any future use of these addresses — including against XG — requires independent re-verification via the same controlled methodology, not by assumption.

## Phase 0C — Menu-selection discovery: ready, live experiment blocked on game state

The documentation checkpoint is now complete. No menu-selection address has been searched for in an active menu yet. The earlier pre-session check of symbol-only candidates (`_menuTitleStatus`, `_menuTopSelectCursor`, and related fields) read zero before a game session existed and is not positive or negative evidence about their live behavior.

The preferred target is the opening battle command menu, followed by move selection, pause/start, then title screen. The complete controlled scan definition—menu identification by self-captured screenshot, one-input snapshot boundaries, 8/16/32-bit interpretations, stability and restart criteria, address-space distinctions, logging, and rollback—is recorded in [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md).

**Current blocker:** Dolphin is not running, so there is no active game screen to capture or emulated memory to inspect. The current connection diagnostic returned `DolphinStatus.notRunning` and detached cleanly. Starting Dolphin or manipulating the user's game session is not being inferred from the documentation-only checkpoint; the next live step requires Dolphin running at a repeatable menu.

## Phase 0D — Read-only speech proof: not started

Depends on Phase 0C succeeding first, per the original design in [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md).

## No-writes audit

Every script used during this live investigation, and what it calls from `dolphin_memory_engine`:

| Script | Calls used | Writes? |
|---|---|---|
| `Companion/test_dolphin_connection.py` | `hook`, `is_hooked`, `get_status`, `un_hook` | No |
| `Companion/_phase0_scratch_read_header.py` | `hook`, `is_hooked`, `read_bytes`, `un_hook` | No |
| `Companion/_phase0_scratch_read_titlemenu.py` | `hook`, `is_hooked`, `read_bytes`, `un_hook` | No |
| `Companion/_phase0_scratch_read_hero.py` | `hook`, `is_hooked`, `read_bytes`, `un_hook` | No |
| `Companion/_phase0_scratch_read_hero2.py` | `hook`, `is_hooked`, `read_word`, `read_bytes`, `un_hook` | No |
| `Companion/_phase0_scratch_hexdump.py` | `hook`, `is_hooked`, `read_bytes`, `un_hook` | No |
| `Companion/_phase0_scratch_snapshot.py` | `hook`, `is_hooked`, `read_bytes`, `un_hook` | No |
| `Companion/_phase0_scratch_diff.py` | (local file comparison only — no Dolphin connection) | No |
| `Companion/_phase0_scratch_diff_region.py` | (local file comparison only) | No |
| `Companion/_phase0_scratch_double_decrease.py` | (local file comparison only) | No |
| `Companion/_phase0_scratch_window.py` | (local file comparison only) | No |

No script in this list imports or calls `write_byte`, `write_word`, `write_bytes`, `write_float`, or `write_double`. All scripts prefixed `_phase0_scratch_` are exploratory/diagnostic, kept separate from the two production-track diagnostics (`test_speech.py`, `test_dolphin_connection.py`) described in [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md).
