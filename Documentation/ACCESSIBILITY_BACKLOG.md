# ACCESSIBILITY_BACKLOG.md

**Status:** Living document. Created 2026-07-29, seeded from verified repository state and the current session's task list. Cross-referenced against [ACCESSIBILITY_COVERAGE_MATRIX.md](ACCESSIBILITY_COVERAGE_MATRIX.md) — every item here should have a matching row there, and vice versa for anything past "Unknown."

Per [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md)'s work-in-progress limits: **one** active blocker, **one** active foundational feature, **one** active investigation, **one** regression queue, **one** story-locked queue, at any given time.

---

## Open finding — autowalk says it cannot reach exits (2026-08-19)

**Reported by the project owner: "the autowalk feature says it can't go to
any exit when I'm pretty sure that should be false." Confirmed real from
the log. NOT fixed — the cause is in the walk model, which is the area with
two red tests and three documented design reversals, and guessing there
sends a blind player's character into a wall.**

### It is real, and it is mostly exits

`Companion/logs/battle_narrator_phase1b.log` carries **98** occurrences of
"Cannot reach it; walking to the closest point I can reach". Pairing each
one with the "Autowalk on, X" that preceded it:

| Target | Count |
|---|---|
| `Elevator to lab, basement` / `basement level N` | 31 |
| warps (`to lab, basement level N A/B`, `to Pokemon HQ Lab`, ...) | 21 |
| `Item box` | 13 |
| `Door` | 7 |
| NPCs (Naps, John, Max, Lily) | 11 |

So the owner's reading is right: it is exits far more than anything else.

Note what this is NOT. Hard refusals — `unroutable
confidence=DIRECT_FALLBACK`, where autowalk will not move at all — number
**5** in the whole log. The common case is PARTIAL: it *does* walk, while
announcing that it cannot reach the thing.

### The shortfalls are real, not an over-cautious message

Spoken shortfalls: 8, 46, 56, 61, 71, 77, 88, 121 units, against an
arrival distance of 4.0. The route genuinely stops a long way short. This
is not a threshold that needs loosening.

### Target projection is NOT the cause

Worth stating plainly, because `target_projection` appears 1,104 times in
the log and looks like the answer. It is not. Every route build in the
owner's 2026-08-19 session reports:

    room=D1_labo_B3 passability=swept radius=3.50 nodes=207
    rejected_edges=129 rejected_nodes=0 target_projected=True
    target_projection_offset=0.0 reseeded=False relocated=170

`target_projected=True` with `offset=0.0` — the destination projects onto
the walk mesh cleanly. `radius=3.50` also confirms this is a current build,
not the stale-process trap.

What stands out instead is `relocated=170` of `nodes=207` — **82% to 98% of
nodes are relocated on every build**, across every room in that session
(D1_labo_B1, B2, B3), together with a large `rejected_edges`.

**A correction, recorded so it is not repeated:** a first pass at this
computed `rejected_edges / nodes` and reported it as "percentage of edges
rejected". That is wrong — a graph has many more edges than nodes, so the
ratio is edges-per-node and exceeds 100% routinely (M6_tower_top averages
77). The log does not carry a total edge count, so **what fraction of edges
are rejected is currently unknown**, and no conclusion should be drawn from
that ratio.

### What was changed

Only observability. `partial_shortfall` and `partial_vertical` were
computed, stored on the route and spoken, but never logged — so a report
like this one could be confirmed without the log saying whether the gap was
**horizontal or vertical**, and those are different bugs:

- **vertical** — the destination sits on a level this room's walk model
  does not connect, and refusing may be correct (you may genuinely need to
  ride the elevator rather than walk to it)
- **horizontal** — the walk graph is refusing ground the player can
  actually cross, and the passability model is too strict

The route build line now carries `partial=`, `partial_shortfall=` and
`partial_vertical=`.

### Next step, before any fix

One short play session in the lab basement, walking to the elevator and to
a couple of warps. Then read `partial_vertical` out of the route build
lines. That single number decides which of the two bugs above this is, and
it cannot be inferred from anything already recorded.

Also check first whether the `DestinationProjectionTests` work is still in
flight — those two failures are in the same walk model, and this project
has already reversed its position on cross-level destinations twice
(2026-08-12 refuse, 2026-08-13 partial-instead-of-refuse).

---

## Open finding — teleport lands wrong, and used to claim it had not (2026-08-19)

**Reported by the project owner: "teleporting doesn't work all the time."
Partly fixed. The reporting defect is closed; the two suspected landing
defects are NOT changed, because changing where a teleport puts the player
needs a live test and this project does not do that from a code read.**

### What was fixed

`teleport.py` wrote the position, said "Teleported to X", and moved on. It
never checked. So every failure mode its own module docstring already
describes — landing inside collision and being shoved straight back out —
was announced to the player as a teleport that had worked.

It now verifies, and the check is **deferred by 0.35s on purpose**. The
write goes into MEM1, so reading the position back immediately returns the
bytes just written and would confirm every teleport ever performed,
including the ones the player watched do nothing. Only after the engine has
run frames does the position mean anything. On failure it says "Teleport
did not take. You did not move." and logs target versus landed.

Also: an unreadable hero model or player pose used to be caught by
`phase1b_lifecycle.poll_teleport`, logged at debug, and produce **silence**
— indistinguishable from the key not registering. Both now speak.

The log had 629 successful "Teleported to" lines and exactly 1 read
failure, which is what made this worth attacking from the reporting side
first: the companion was not detecting the failures at all, so the log
could not say how often they happen. It can now.

### What is suspected and NOT fixed

**1. Only `npc` gets the collision pull-back.** `NPC_LIKE_CATEGORIES` is
`{"npc"}`. The module docstring explains why NPCs need it — landing on
their coordinates puts the player inside their collision and the game
shoves them out, which "looked like teleport does nothing". But `interact`
(televisions, beds, machines, consoles, the Snag Machine, the Relic Stone)
are solid objects too, and so are treasure boxes under `item`. Those get
no pull-back. Warps and doors legitimately must NOT get one — landing on
the trigger is the point.

**2. Every non-NPC category lands at the PLAYER's current Y.**
`Position(entity.position.x, pose.position.y, entity.position.z)`. That is
deliberate and documented: those entity Y values are CCD centroids at
arbitrary heights. But it is wrong whenever the target is on a different
floor of the same room — and the log shows exactly those targets, e.g.
"Teleported to to Pyrite Town hotel, 2nd floor". Right X/Z at the wrong
height is inside geometry or under the floor, and the engine rejects it.

The fix for (2) is to resolve the walkable ground height at the target X/Z
from the room's own collision data rather than assuming the player's.
`pathfinding.walk_height_candidates` and
`terrain_footsteps.find_ground_triangle` already do this, and
`phase1b_app` already has `warp_collision_dir` and `room_codes` in scope
where `TeleportReader` is built, so the plumbing is short. What is not
settled is which candidate height to choose when a room stacks several at
one X/Z — and note that the suite's two long-standing failures are in
`test_passability.DestinationProjectionTests`, which is precisely the
cross-level projection question. Do not change this without a live test,
and check whether that in-flight work lands first.

### How to test it live

The new "Teleport did not take" message makes this cheap: teleport around
a multi-floor room (the Pyrite hotel) and to interactables, and read
`TELEPORT DID NOT TAKE` lines out of the log with their target and landed
coordinates. That says which of (1) and (2) is real, and how often, before
anything changes.

---

## Open finding — footsteps go silent while beacons keep working (2026-08-18)

**Reported by the project owner as "a few times the beacons will activate
but not the footsteps." Diagnosed from their own log. NOT FIXED — the fix
changes live movement behaviour and this project does not make that change
without a live test.**

The cause is not packaging and not settings. Both were checked and ruled
out first: `companion_settings.json` has `sounds.footsteps: true` and
`sounds.footstep_volume: 1.0` (louder than the beacons, at 0.4), and all
seven recordings are present and cached as 16-bit.

`Companion/logs/battle_narrator_phase1b.log` spans 2026-07-24 to
2026-08-18 across many sessions, so it is quoted **scoped to 2026-08-18
alone** — the whole-file totals (2,892,456 occurrences) include the
vanilla-XD era and prove nothing about now.

On 2026-08-18: of **191,186** log lines, **98,639 — 52% of everything
logged that day — are `hero model resource 100 not found`**, and **49,579**
of those are `Isolated terrain-footstep read failure`.
`hero_model_address` (`npc_beacons.py`) walks the resource list for a node
matching `group_id == 0 and candidate_id == 100 and state == 0` and raises
`MemoryError` when there is none.

Note the shape of it: 49,579 failures produced only **104** logged
`CLEAR`s, because `clear` logs only when `_last_position is not None`.
The reader is therefore re-seeding on an occasional good poll and being
cleared again before it can accumulate — oscillating, never reaching the
threshold.

Why that silences footsteps specifically, while beacons survive it:

- `phase1b_lifecycle.poll_terrain_footsteps` catches the `MemoryError`,
  logs it at **debug**, and calls `clear("terrain-footstep read failure")`.
- `TerrainFootstepReader.clear` sets `_accumulated_distance = 0.0`.
- A footstep needs `STEP_DISTANCE = 12.0` world units **accumulated across
  consecutive successful polls**.

So any failure rate frequent enough to interrupt 12 units of travel means
the accumulator never reaches its threshold and **no footstep ever plays**.
A beacon re-aims from whatever position it last got and is indifferent to
gaps, which is exactly why one keeps working while the other does not —
and the log's last lines that day show `NPC BEACON` firing normally. The
whole thing is invisible because the only record is a debug line.

One corroborating signal, offered as suggestive rather than proof:
`new terrain type observed` fired **0** times on 2026-08-18. `_known_types`
is per-instance and resets every launch, so a day of play that plays
footsteps normally would log it several times. It is not conclusive because
that line is skipped when `collision_type is None`, which happens whenever
`find_ground_triangle` finds nothing — a step still plays in that case.

### What to check before fixing

1. **Is resource id 100 right for XG?** The hero model id is a repository
   constant, and [XG_COMPATIBILITY.md](XG_COMPATIBILITY.md) §9 lists the
   profile addresses that were never checkable statically. This has the
   exact shape of the four defects that document already records: a
   constant that was true of one build. If 100 is wrong for XG, the read
   failure is the bug and the accumulator is a symptom.
2. **Or is the failure legitimate and transient** — the hero model
   genuinely absent during transitions, loading, cutscenes — in which case
   the bug is that a *transient* read failure discards accumulated walking
   distance at all.

Those want different fixes and the log alone does not separate them. Get
the success/failure ratio per second of ordinary walking first.

### Proposed fix, once (1) is settled

Separate the two meanings of `clear`. A room change or a dialogue should
discard accumulated distance; a one-poll read failure should discard only
`_last_position`, so the next good pair resumes accumulating instead of
starting over. Raise the failure out of `debug` — a million of anything
should not sit at debug level.

### Already done (2026-08-18)

Not the fix, but the reason this took a log dive to find is now closed:
`resolve_step_paths` warns, naming the reason, instead of falling back to
the synthesized click in silence; `TerrainTonePlayer.using_real_footsteps`
exposes which of the two is in use and `phase1b_app` states it at startup;
and the release builder enumerates `sounds/footsteps/` rather than copying
a hardcoded list of seven, checks the staged count, and runs
`resolve_step_paths` against the staged tree so a release whose footsteps
would fall back cannot be built. See
[FIRST_RUN_AND_RUNTIME.md](FIRST_RUN_AND_RUNTIME.md) and
[README-DISTRIBUTION.md](../README-DISTRIBUTION.md).

---

## Handoff — next session starts here (2026-08-09, latest)

**Entity-navigation re-audit (Pass 2) complete. No production code
changed. Suite 1115 passing** (was 1106 at Phase 2; Codex's menu/PDA work
added the rest).

Read [ENTITY_NAVIGATION_AUDIT.md](ENTITY_NAVIGATION_AUDIT.md) **§0** — it
supersedes the status claims in the rest of that document and in the
2026-08-06 handoff below.

**The three reported symptoms are all the revert, still in place.** The
Agate three-clerk label, "NPC A", and NPCs announced where nobody is
standing are all produced by the pre-Phase-2 code that
`build_overworld_sources` was put back on. Nothing new is broken.

**Quantified, from three days of production log:** 2396 "Out of
interaction range" against **4** "Interaction available", all four of them
Items. **No NPC in three days was ever reported interactable**, including
at 10-11 units from a Mart clerk. `(opened)` has now fired **zero times in
the project's entire log history**.

**The validation mechanism has never run.** `--interaction-diagnostics` is
not in the launcher; the log contains zero `INTERACTION DIAG`,
`NPC SOURCE rejected` or `neck=` lines. Every "the diagnostic will settle
this" claim from Phase 2 is still open.

### New this pass (offline, no live memory)

- **The Phase 4 question is answered.** There are no unparsed `common.rel`
  interaction types (disproven). The missing object system is the 241
  marker-`0x0100` records whose `+0x0A` indexes the **owning room
  script's** function table — 241/241 verified, 0 out of range. They are
  `watch_tv`, `esa_set` (PokéSpot plates), `check_snatchmachine` (Snag
  Machine), `bed_recovery`, `check_shrine` (Relic Stone), `tako_machine`,
  `crane_move_*`, `hero_fall`. See
  [INTERACTABLE_OBJECTS.md](INTERACTABLE_OBJECTS.md).
- **The treasure record is fully resolved**, including `+0x06` (collected
  flag) and `+0x08` (spawn flag) as *separate* general flags, `+0x0C`
  (item id), and `+0x02` (facing — previously UNVERIFIED, now traced).
  Placeable kinds are 1/2/3 read as `(byte >> 5) & 7`.
- **Three hardcodes now have real owners**, including the discovery that
  `HEALING = {0x8A: …}` is `M5_apart_1F`'s `check_mana_bed` — a **bed**,
  mislabelled as a healing station.

### Gateon Port bridge connections — SHIPPED as their own category

Pulled forward from Phase 5 at the project owner's request. A **`bridge`**
category (spoken "Bridges") publishes the connections the pier's *current*
alignment offers, re-read from flag 968 on every query. Rotate the bridges
and the list changes; the old connections disappear.

Empty — and therefore skipped by the cycle — everywhere except on the
pier.

Nothing is hardcoded: the state table is **parsed** from the extracted
`M6_out` script, and the two decks, their northern/southern naming, each
segment's compass direction and every position are **derived** from
`M6_out.ccd`.

**One thing to know while using it:** use the **plain beacon
(ctrl+shift+g)** on a selected bridge connection, not the routed guide
(ctrl+shift+n). Routing is still not alignment-aware — see
[GATEON_BRIDGE_ACCESSIBILITY.md](GATEON_BRIDGE_ACCESSIBILITY.md) §5.

**To validate live:** stand on a pier, cycle to Bridges, walk to one
announced connection and confirm you can cross there. Then change the
alignment and confirm the list changes. Two observations settle the
polarity in the game rather than against a document.

### Phase 4 — room-script objects and hazards — SHIPPED, needs live validation

Suite **1274**. Two new things in the cycle:

- **Interactables** now includes televisions, beds, healing machines,
  PokeSpot plates, the Relic Stone and a vending machine, plus a generic
  "Interactable" for every other press-A object a room script owns.
- **Hazards** is a new category: eight fall regions in Citadark's
  `D6_fort_6F`. It never beacons and never says "Interaction available".

**Needs a narrator restart.**

Easiest live checks, in rooms you pass through anyway:

1. Any house with a **television** — cycle to Interactables, expect
   "Television".
2. **Agate's Pokémon Centre** or any lab with a `tako_machine` — expect
   "Healing machine". This one is a real prediction: it was classified from
   its calls, not its name.
3. **M3_shrine_1F** — expect "Relic Stone" instead of the old hardcoded
   relabel.
4. A **PokeSpot** — expect "PokeSpot plate".

Deliberately generic for now: the **Snag Machine** (story-gated, guard not
traced) and the **crane consoles** (no direct calls to classify by). Both
appear as "Interactable" rather than being named on a guess.

### Phase 3 — containers and loose items — SHIPPED, needs live validation

Suite **1226**. Item boxes and loose/story pickups are now driven by the
engine's own state machine. **Needs a narrator restart.**

**Live validation, one action at a time — tell me when you are ready:**

1. Find an **unopened item box**. Cycle to Items. It should say
   **"Item box"** and beacon.
2. **Open it.** Without leaving the room, cycle to Items again. It should
   say **"Opened item box"**, the beacon should be gone, and it should
   still be listed.
3. Find a **loose item** (a ground sparkle). It should say "Item" and
   beacon.
4. **Collect it.** It should disappear from the list entirely and go
   silent.

The prediction that distinguishes right from lucky: the box **stays** and
the loose item **goes**. That asymmetry is the engine's
(`floorEventCtrlTresure` mode 0), not a policy choice, so if a collected
box vanishes or a collected ground item lingers, the kind decode is wrong.

### Canonical NPC source — status frozen 2026-08-09, swap DEFERRED

Deferred to conserve investigation time, **not abandoned**. Shadow mode
stays on; production keeps the old source.

| Claim | Status |
|---|---|
| Canonical architecture | **strongly validated** |
| `NPC SHADOW STARVED` | **zero across 8 rooms**, 37 minutes |
| Agate Mart clerk | **correct live** — one clerk, two ordinary NPCs |
| Phantom static-NPC rejection | **proven** — 5 of 19 in Phenac had no live actor at all |
| Live talk distance | **proven** — `talk_live=9.00` vs `talk_static=3.00` on the clerk |
| Moving actors | **tracked**, d=1.53 poll skew between sources |
| Corrected neck resolver | **awaiting live validation** — the 3,601 clamp saves at 298-372 units were logged by the build *before* the fix |
| Production swap | **deferred, not abandoned** |

Outstanding before a swap: criterion 4 (a role outside Agate) and
criterion 6 (neck offsets confirmed sane on the corrected resolver). Both
are one play session away. **Do not spend further time on the neck
resolver unless item work depends on it.**

### Phase 2 step 1 — shadow mode — SHIPPED, needs a narrator restart

Suite **1140 passing**. `npc_shadow.NPCSourceShadowReader` runs the
canonical NPC source alongside the one production actually speaks, changes
nothing about what is spoken, and logs the difference. **On by default**
(`--no-npc-shadow` disables) — deliberately, because the off-by-default
diagnostic has never once run.

**A narrator restart is required before it produces a single line.**

**Shadow mode found three defects in one day, all invisible to a green
suite.** Full detail in
[IMPLEMENTATION_ATTRIBUTION.md](IMPLEMENTATION_ATTRIBUTION.md); suite
**1179**.

- **R6 — rule 6 compared two namespaces.** `floor_character +0x06` is an
  INDEX (81, 116, 145); `people_work +0x1C` is the record's ID
  (`0x15FA0400`…). Never matched, so it rejected every NPC in every room:
  1,497 `STARVED` lines. **Fixed, and confirmed live** — the next session
  logged `room=0x86 primary=3 shadow=3 both=3`, zero starvations.
- **R7 — the role table was keyed on the wrong number.** Live talk ids are
  `0x01000006/7/8`; the low bits are the **function index** in the room's
  script table, not the `talk_<N>_` number in its name. Agate's Mart now
  resolves to `{7: "Pokemon Mart clerk"}` = `talk_122_shop_m`, exactly one
  clerk. Table coverage 15 rooms → **26**.
- **The neck resolver is intermittently wrong.** Offsets of **40.92** and
  **11.32** against a 4.0 collision ball, one NPC jumping 0.50 → 11.32 in
  five seconds. Now bounded by the character's own collision ball with a
  fallback to the actor position; **the JObj walk itself still needs
  fixing**.

Also settled: **the live talk distance is NOT initialised from the static
one** — one Agate NPC reads `talk_live=9.0` against `talk_static=3.0`, a
six-unit under-report in the rule production still uses.

**What you do:** play normally. Visit the Agate Poké Mart at some point,
and any room where an NPC walks or a cutscene moves someone. Then say so,
and the log gets read.

**What decides the swap** — one line, by name:

```
NPC SHADOW STARVED ... -- the canonical source published nothing where
the production source published N. Do NOT swap sources while this appears.
```

If that never appears across a real session, the canonical source is safe
to swap in. If it appears, it names the room, and that room becomes the
next investigation instead of a live failure you have to notice by ear.

The same log answers the three questions Phase 2 left open — `talk_live`
vs `talk_static`, `neck_offset`, `talk_sct` — plus a per-NPC `drift`
measurement of how far production's published position is from the live
one, which is the "announced where nobody is standing" defect quantified.

### Then, before the swap

1. **Re-examine validity rule 6** (actor vs static `people_info_id`). It
   is a project-invented check the engine does not perform and the rule
   most able to empty the category. Demote to a logged warning unless the
   shadow log shows it never fires.
2. Swap the source, keeping a fallback that preserves the old output if
   the live source publishes nothing in a room whose static table says
   characters exist.
3. Live-validate one case at a time per the 2026-08-06 list below.

**Do not start Phase 3 until at least two manual A-press cases agree with
the prediction.**

---

## Handoff — 2026-08-06 (superseded by the entry above)

> **REVERTED IN PRODUCTION, 2026-08-06.** The project owner was mid-dungeon
> and lost the NPC category, so `phase1b_app.build_overworld_sources` was
> put back on the pre-Phase-2 `NPCEntitySource`, and the Mart beacon back on
> `profile.pokemart_room_ids`. **Every Phase 2 module and test stays in the
> tree and the suite is still 1106 passing** — only the production wiring
> was reverted. Re-enabling is two edits, both marked with a `REVERTED TO
> THE PRE-PHASE-2 NPC SOURCE` comment in `phase1b_app.py`.
>
> Consequences of the revert, so nobody is surprised: the three-clerk Agate
> label is back, unnamed NPCs speak as "NPC A" again, and interaction range
> uses the old horizontal `talk_distance + 1.5` rule. **Do not re-enable
> without live validation first** — `LiveNPCEntitySource` is strictly more
> selective, so any single wrong offset in its chain empties the category,
> which is what happened.

**Entity-navigation Phase 2 (canonical NPC source) is code-complete and
regression-tested at 1106 passing, but NOT live-validated.** A narrator
restart is required. See
[ENTITY_NAVIGATION_AUDIT.md](ENTITY_NAVIGATION_AUDIT.md) for the full
root-cause list and the Phase 3-7 plan.

**Immediate next step — live validation of Phase 2**, with
`--interaction-diagnostics` enabled, one case at a time:

1. one stationary named NPC
2. one unnamed NPC (must speak as "A", never "NPC A")
3. one moving NPC
4. the Agate Poké Mart clerk — must be **one** clerk, not three
5. a non-clerk NPC in the same Mart — must keep its own name or letter
6. an NPC behind or near a wall
7. an NPC just outside, then inside, interaction range

For each: select it, press the mark hotkey (`ctrl+shift+k`) immediately
before pressing A, then stop and read the `INTERACTION MARK RESULT` line.
`AGREES=True` means the prediction matched reality.

**Three questions the diagnostic exists to settle** (all currently
unverified, none guessed into production):

- `neck_offset=` — how far the neck reference really sits from the model
  position. Expected under a game unit; if so, the neck reference is a
  correctness improvement rather than the dominant fix.
- `talk_live=` vs `talk_static=` — whether `people_work +0x178` is
  initialised from `people_info +0x24`.
- `talk_sct=` — whether live talk script ids match the `talk_<N>_` numbers
  the role table is derived from. Agate's clerk should read `talk_sct=122`.

**Do not start Phase 3 (containers and loose items) until at least two
manual A-press cases agree with the prediction.**

---

## Handoff — 2026-08-04 (superseded by the entry above)

**This supersedes both handoffs below. The grid-resolution blocker is
resolved; awaiting live confirmation.**

State: **786 tests pass** (was 774). Narrator runs from
`Companion/.venv/Scripts/pythonw.exe run_accessible_pokemon_xd.py
--terrain-footsteps`. Hotkeys: **ctrl+shift+g** = plain beacon on the
selected entity, **ctrl+shift+n** = routed navigation.
**A narrator restart is required for these changes to take effect.**

### What the previous handoff got wrong, and what actually broke

The blocker was stated as grid resolution. Resolution was real, but it was
not what failed in the last live session, and it was not the largest defect.
Reading the production log first found that the **only** `cause=` ever
emitted in the whole 60 MB tail is `target_projection` (22 times) —
`grid_alignment`, the diagnostic built to detect the resolution symptom, has
never fired in real play. Four separate defects were found and fixed:

1. **The collision radius was wrong.** `DEFAULT_COLLISION_RADIUS` was 4.0,
   the `peopleInfo` table's dominant value, flagged as unconfirmed since
   §6g and shipped anyway. Pinned behaviourally from live play instead: the
   engine only ever puts the player at least `colBallSize` from a swept
   wall, and across the 311 logged `D1_garage_1F` positions the minimum
   clearance is **3.495**, with zero below 3.0 and a hard floor hit at two
   independent walls. **The hero's radius is 3.5.** With 4.0, **67.8% of
   the positions the player was actually standing in were classified as
   inside an obstacle** — the real origin of much of the "resolution"
   fragmentation, and why halving the tile size never helped.
2. **`resolve_destination_node` ignored height**, projecting the basement
   stairwell warp (48.2 units below the floor) laterally onto the ground
   floor and seeding an unreachable component. That, not the lattice, is
   what produced the "six-tile pocket."
3. **`exempt_tiles` let the flood enter the player's tile through a wall**,
   which made the player look linked to that pocket and stopped the
   reachability fallback from ever firing.
4. **Then resolution itself**, fixed by relocating each tile's node to the
   roomiest point inside it rather than shrinking `TILE_SIZE`.

Largest connected component, before → after:

| Room | before | after |
|---|---|---|
| `D1_garage_1F` | 184 (40.5%) | **230 (50.7%)** |
| `M3_pc_1F` | 85 (50.6%) | **113 (67.3%)** |
| `M2_shop_1F` | 100 (55.6%) | **147 (81.7%)** |
| `M2_hotel_1F` | 73 (16.9%) | **185 (42.8%)** |

Replaying **all 311** real logged garage positions, every one now routes —
both to the stairwell that produced the pocket and to an ordinary in-room
destination. `M3_out` is untouched by construction and verified identical
(2968 nodes, `relocated_nodes=0`).

Full account: `WORLD_NAVIGATION_ARCHITECTURE.md` §6j.

### Next concrete action

**Live-test it.** Nothing here has been confirmed in a real play session —
this is offline measurement against real captured data plus regression
tests, which is not the same thing. Worth checking specifically:
- the garage basement warp now guides toward the stairwell instead of into
  the south wall;
- indoor rooms generally (Pokémon Centre, shops, the hotel) route where they
  previously gave up;
- the log's new `reseeded=` and `relocated=` fields on each route build.

### Still open in navigation

- The 3.5 radius is a **bound from one room's live positions**, not a read
  of the hero's `peopleInfo` record. A direct read should supersede it and
  should agree.
- **Cross-level routing is diagnosed, not solved.** `height_layer` now names
  it and the guide degrades to "nearest reachable point," which is honest
  and useful, but a real stairwell route is still unimplemented.
- `_wall_spans_height` has **no minimum obstacle height** — a 0.5-unit lip
  blocks exactly like a wall. Not indicted by any measurement so far (the
  garage's blockers are all 34 units tall), but unverified.
- `M2_hotel_1F`'s largest component is 42.8%. Much better than 16.9%, still
  not obviously correct.

### Also open, smaller

- **One reader's exception kills the entire narrator.** Barrier log #10 was
  severity 0 for this reason — the `AttributeError` was the trigger, not the
  reason every feature went silent at once. Nothing has been done about it.
- **Purification results 50503/50510/50511 all speak the same sentence**
  (`menus.py`), so the player hears the identical line three times and
  learns nothing. Real messages presumably differ.
- **Cross-level destinations** remain unsolved; `diagnose_unreachable`
  reports `height_layer` rather than routing them.
- ~~**The hero's own `colBallSize` is unconfirmed.**~~ **Resolved
  2026-08-04 (late): it is 3.5, not 4.0.** Pinned behaviourally from 311
  live player positions rather than by indexing the record (see the handoff
  above and `WORLD_NAVIGATION_ARCHITECTURE.md` §6j). A direct read of the
  hero's `peopleInfo` record would still be worth having as independent
  confirmation.
- **Test doubles have twice diverged from real interfaces** and hidden real
  bugs (`PartySlot.nickname`, `FixedResultNavigation.begin`). Worth a sweep
  for others.

### Healing service — where it actually stands

Phases 2/3/5/6 are done and the false-positive control passes. 15 healing
rooms game-wide, split into **5 nurse rooms and 10 machine rooms** — which
corrects Phase 9's "point at the live People actor" for two thirds of them.
`$characters[N]` is confirmed **not** the live actor index. Remaining:
Phase 4 (reachability), Phase 7 (availability), Phase 8 (generate the data
file), Phase 9 (Interactables entry). See `HEALING_SERVICE_SCRIPT_TRACE.md`
§6b–6e.

---

## Handoff — healing service (2026-08-04, earlier)

**Read [HEALING_SERVICE_SCRIPT_TRACE.md](HEALING_SERVICE_SCRIPT_TRACE.md) §1 first.**

⚠ **Correction carried forward:** an earlier session concluded the Pokémon
Center healing method was **"People method 85"**. **That was wrong.** The
healing method is **script class 35 (`Character`), method 101 (`0x65`),
`Character.useHealingMachine`**. The number 85 is *only* the internal
`cmpPeople` jump-table index — the dispatch does `subi r0, r27, 0x10`, so
`101 − 16 = 85`. GoD Tool independently names method 85
`getYRotationDegrees`, which is what the uncorrected number would have
wrongly selected. Never search bytecode for `0x55`, and never search raw
bytes for `0x65` either (see that document's §4 for why byte scanning is
invalid).

Confirmed chain: live People actor → talk script ID (Agate nurse
`0x01000008`) → room `.fsys` script → `Character` class 35 method 101
`useHealingMachine` → `cmpPeople` dispatch index 85 → `recoveryEventPC`
(`0x801CF474`) → party healing.

**Phase 1 (tooling inventory) is COMPLETE — do not redo it.** GoD Tool
(`Pokemon-XD-Code/Objects/scripts/XD/`) and the Python `XDscriptTools`
(`Research/ThirdParty/XDscriptTools/`) are both installed; adapt them rather
than writing a new parser. Note the measured split: XDscriptTools decodes
instructions but names only 5 `Character` methods, while GoD Tool's
`XGScriptClassFunctionsData.swift` names 97 — use the Python decoder with
GoD Tool's name table.

**Immediate blocker for Phase 2:** room `.fsys` archives are not extracted.
Only `common`, `fight_common`, `pocket_menu`, `battle_disk` and the
`collision/` `.ccd` set exist under `Companion/_dialogue_extraction/`.

Remaining phases 2–10, deliverables, validation set (two+ Pokémon Centers, a
Poké Mart clerk, another receptionist — the latter two as false-positive
controls) and boundaries are all specified in that document. No production
accessibility code was changed by the trace session.

---

## Active blocker

**None currently set.** Per the project owner's explicit instruction, this is left unset until the current live play state is reviewed with them — nothing in the verified repository state indicates a live, currently-blocking Level 0 barrier stopping progress right now (the party-summary-screen bug was Level 1/2 and is already fixed pending live confirmation, not a hard stop). The next play session should confirm this slot stays empty or surface what belongs here.

---

## Active foundational feature

**Comprehensive entity and treasure detection.** Set 2026-07-29, per the project owner's explicit priority: "grabbing every single entity and treasure that a sighted person can easily see." Footstep/collision work below is now paused (footsteps shipped and live-confirmed; collision explicitly on hold), freeing this slot.

- Exact blind-player failure: entity-nav currently only surfaces NPCs, warps, doors, elevators, and healing spots — anything else a sighted player would simply see and walk up to (signs/plaques, PC terminals as field objects, and critically, on-the-ground item/treasure pickups) is invisible to a blind player using this companion, even though entity-nav's whole design goal is exactly this kind of parity.
- Expected accessible behavior: every entity-nav-surfaceable object type a sighted player could visually notice and approach gets its own accurate category, not just the five already covered.
- Severity: 1-2 depending on the object (a treasure/item pickup a sighted player can just see and grab, with no blind-accessible equivalent at all, is a real independence gap).
- Known gaps to close, in rough priority order:
  1. **Treasure/item pickups on the ground.** The `ITEMS` category exists in code but is currently an empty dict — nothing is wired in. Earlier investigation this project (see `IMPLEMENTATION_ATTRIBUTION.md`'s 2026-07-27 "item/elevator categories" entry) explored a candidate in-memory table (`0x804E88F0`/`0x804E88F4`) but repeatedly found it resolved to elevators, not items, across four live tests — that table was correctly rejected as the wrong source, not yet replaced with a real one. Separately, static tracing this session found that treasure pickup is a **genuinely separate hardcoded C mechanism** (`floorEventCtrlTresure`/`floorEventGetTresure`), not part of the `common.rel` interaction table at all — meaning the real per-room treasure/item placement data lives somewhere else entirely and hasn't been found yet.
  2. **Text/sign interaction-table type (`0xC`, ~89 records game-wide).** Already confirmed to exist in the same interaction table warps/doors/elevators come from (same parser already handles it structurally), explicitly deferred earlier for lack of an obvious entity-nav category to wire it into — now in scope given this priority shift.
  3. **PC interaction-table type (`0xE`, ~26 records game-wide).** Same table, same parser; `Pokemon-XD-Code` documents its parameters as "unused in XD" specifically, so reliability needs live spot-checking before trusting it as a category, but it's a real, findable object type a sighted player would see.
- Story availability: available now, no story gate — applies to the whole game.
- Current evidence: parser and CCD-centroid resolution infrastructure already exist and are proven (`authoritative_warps.py`) for types 4/5/6/0xD; extending to 0xC/0xE is mechanically the same pattern.
- **Treasure/item pickup: implemented and live-tested, 2026-07-29.** Static disassembly of `_floorInitTresure` (room-load-time treasure initializer) found it reads the exact same live table already used for warps/doors/elevators (`0x804E88F0`/`0x804E88F4`, `0x1C`-byte stride) but through the game's own runtime field layout, not the on-disk `common.rel` layout — explaining why the earlier (2026-07-27) attempt at this same table kept resolving to elevators: it was reading the right table with the wrong field offsets, not the wrong table. Runtime layout: `+0x00` byte's low 3 bits = "kind" (1/2/4 = placeable pickup), `+0x04` = room ID, `+0x10`/`+0x14`/`+0x18` = position. Implemented as `treasure_entities.LiveTreasureEntitySource`, a pure live read needing no offline extraction at all, wired into entity-nav's `item` category in place of the empty stub. 7 new tests, 399 total passing. **Live-confirmed via the narrator's log**: items found correctly across multiple rooms, distance tracked accurately and monotonically while approaching one (84→...→8 units), correctly flipping to "In interaction range" on arrival.
- **Item kind confirmed:** the project owner directly confirmed the live-tested item is an "Item Box" (kind=4) — now labeled accordingly in code. Kinds 1/2 remain unconfirmed.
- **PC: implemented and live-tested, 2026-07-29.** Same proven interaction-table pattern as Door/Elevator/Warp (type `0xE`), wired into `entity_nav_factory`'s `pc` category. `Pokemon-XD-Code` flags this type's own parameters as "unused in XD" specifically, so reliability beyond position remains a caveat. **Live-confirmed** — the project owner walked to a reported PC location and confirmed a real PC was there.
- **Sign/Text: implemented 2026-07-29, not yet live-tested.** Same pattern again (type `0xC`, ~89 records game-wide), wired into a new `sign` category. Announces generically as "Sign" — the record's secondary field is a candidate message ID, not yet confirmed to resolve through any string table. This closes out all six known `common.rel` interaction types as entity-nav categories.
- **Healing-spot coverage: investigated, not resolved.** Cross-checked the one existing hand-scanned `HEALING` entry (floor `0x8A`) against the live item/kind table directly — no matching record found (nearest was 33+ units away), ruling out "kind 1/2 = healing" for that sample. Healing spots use some other mechanism, not yet identified. Comprehensive healing coverage remains an open gap.
- Next concrete action: live-confirm the `sign` category against a real sign; continue investigating the healing-spot mechanism (candidates: Door/Text interaction subtypes, a scripted-NPC-like object, or a separate table); investigate whether Text's `message_field` resolves through the general string table to eventually speak sign contents.
- Completion criteria: per [VERTICAL_SLICE_TEMPLATE.md](VERTICAL_SLICE_TEMPLATE.md), per new category.

---

## Active investigation

**NPC direct-interaction assistance (bypass distance/facing cone).** Remains on hold pending the project owner's decision (unchanged this pass — see below); not being actively worked while entity/treasure coverage is the priority.

- Decision this investigation supports: whether, and how, to let the player initiate a conversation with an entity-nav-selected NPC without physically satisfying the game's proximity/facing check.
- Current evidence: full call chain traced (`updateChat`→`peopleTalkCheck`→`peopleGetTalkSctID`→`floorExecScriptRes`/`floorExecScriptResThread`); the talk-triggering functions confirmed pure and `(groupID, resID)`-driven; `(groupID, resID)` confirmed as the pool's canonical identity via the independently-discovered `peopleSearchID` function; no safe external invocation mechanism found (execution breakpoints unreliable in this Dolphin/GDB-stub setup; the retail debug-menu system is a technically-real but disproportionately risky/visual candidate; code-patching excluded without separate authorization).
- Next concrete action: a decision from the project owner on how to proceed — re-test one-shot (not persistent) breakpoint reliability, consider a scoped/explicitly-authorized code patch, or accept a narrower "impersonate whichever real NPC happens to be in range" fallback. Not proceeding further without that decision.
- See [PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md) #5 for the full incident record.

---

## Next reachable features

Ordered candidates for what to pick up next once the active blocker/foundational/investigation slots free up, per the master plan's priority order. Not a commitment — a newly discovered Level 0 blocker overrides this.

1. ~~Live-confirm the party-summary multi-Pokémon fix.~~ **Done 2026-07-29** — project owner confirmed live ("much better"). Surfaced a separate, on-hold defect (Shadow Pokémon move display) in the process — see Known backlog below.
2. **Live-confirm the 5 recently-implemented battle notifications** (send-out, level-up, shadow/catch flavor text, catch-target messages, victory sentence) — same situation, implemented and regression-tested, awaiting a real battle/catch/level-up/victory event during natural play.
3. **Live-confirm the NPC-category teleport approach-position fix.**
4. **Shops.** Investigation already started 2026-07-29 (see coverage matrix's Shops section) — item-table offline decode/verification is now done (shared with Bag/descriptions, see "Item name resolution infrastructure" and "Item description text" in the coverage matrix); quantity-adjuster/shop-goods-table live reads are the remaining concrete, bounded next actions with no unresolved blocker like the NPC-interaction investigation has.
5. **Add the single-instance mutex guard to `run_battle_narrator.py`.** Small, well-understood, prevents a real recurring bug (double-narration).

## Known backlog

Items with a clear need and no current blocker, not yet started, in no particular forced order beyond the master plan's general priorities.

### PC Storage box grid navigation
- Exact blind-player failure: the Pokémon box grid cannot be narrated at all — no live cursor/slot-index field has been found despite four separate attempts.
- Expected accessible behavior: announce the occupied/empty state and, if occupied, the Pokémon's name/level as the player moves the box-grid cursor — mirroring `party_list_screen.py`'s existing pattern.
- Severity: 0-1.
- Dependencies: none technical beyond finding the field; not story-gated.
- Story availability: available now (PC already reached and partially investigated).
- Proposed smallest useful slice: a fresh investigation angle (a live GDB write-watchpoint trace, matching the methodology that successfully resolved the earlier speaker-ID and party-address problems) — explicitly not another heuristic memory scan, which has already failed four times.
- Current evidence: box-Pokémon struct format confirmed identical to party Pokémon (0xC4 stride) via `SaveFileTables.swift`; PC main menu (`menu_id=122`) and storage-action submenu (`menu_id=123`) already found.
- Next concrete action: scope a live GDB trace session for the box-grid cursor field.
- Completion criteria: standard three-part (Implemented/Live-tested/Regression-tested).

### PC Item Storage
- Exact blind-player failure: PC Item Storage cannot be narrated.
- Expected accessible behavior: same as the overworld Bag, since it's confirmed to reuse the identical `menu_id=44` window.
- Severity: 1.
- Dependencies: none — this can ship independently of the box-grid blocker.
- Story availability: available now.
- Proposed smallest useful slice: wire the existing Bag category-tab reader to also cover this window, following the exact pattern already used to add the Give/Take popup as a second configuration of `PartyActionMenuReader`.
- Current evidence: confirmed via passive window-state logging that PC Item Storage opens the same window ID as the overworld Bag.
- Next concrete action: implement, no further research needed.
- Completion criteria: standard three-part.

### EXP point count / money-earned value
- Exact blind-player failure: level-up is announced, but the exact EXP gained (and money earned after a trainer battle) is not.
- Expected accessible behavior: announce the numeric value.
- Severity: 2.
- Dependencies: needs the "Quantity" opcode's real source address, which one prior attempt found leads only to a generic, non-specific engine utility.
- Story availability: available now.
- Proposed smallest useful slice: a live GDB write-watchpoint trace on the EXP/money display fields during a real battle-end event.
- Current evidence: opcode structurally identified; one dead-end address already ruled out and documented.
- Next concrete action: schedule the trace for the next convenient battle-end event.
- Completion criteria: standard three-part.

### Victory message's opponent trainer name
- Exact blind-player failure: victory is announced with a fixed sentence, without which trainer was defeated.
- Expected accessible behavior: include the trainer's name/class.
- Severity: 3 (a correct, if generic, announcement already exists).
- Dependencies: no known "current opponent trainer" global exists anywhere in the profile today.
- Story availability: available now.
- Proposed smallest useful slice: live GDB trace during a real trainer victory.
- Current evidence: opcode identified (`0x22`/`0x23`/`0x25` substitution), no live source found yet.
- Next concrete action: not scheduled ahead of higher-severity items.
- Completion criteria: standard three-part.

### Held-item name resolution
- Exact blind-player failure: a held item is announced only by raw numeric ID, not by name.
- Expected accessible behavior: resolve the name via the shared item database.
- Severity: 2.
- Dependencies: none — the item-name resolver this was waiting on is now built and live-confirmed (`item_database.ItemDatabase`/`ItemNameResolver`, built for the Bag item list, 2026-07-29).
- Story availability: available now.
- Proposed smallest useful slice: pass the existing held-item-ID read through `ItemNameResolver.resolve_name`; no new research needed, just wiring.
- Current evidence: see the coverage matrix's "Item name resolution infrastructure" entry.
- Next concrete action: wire it in whenever this specific screen is picked up.
- Completion criteria: standard three-part.

### Eevee evolution-stone selection menu — implemented via direct OCR confirmation, pending live test
- Exact blind-player failure (was): a dedicated "choose a stone for Eevee to evolve" screen (5 selectable options) spoke nothing at all.
- Resolution: the project owner directly read the real on-screen order via their own OCR — Water Stone, Thunder Stone, Fire Stone, Moon Shard, Sun Shard (indices 0-4) — after live investigation confirmed the selection cursor lives at the window's (`menu_id=175`) `+0x9F` offset but found no way to derive the labels themselves generically (two candidate data sources near the window were both ruled out as UI decoration, not item content — see the coverage matrix entry for the full trail, including a caught-before-reported false lead). Implemented by reusing `PartyActionMenuReader` unchanged with these 5 fixed labels — the same pattern already used for the party action popup, bag category tabs, and pause menu.
- Severity: was 2 (blocking for any user without OCR); resolved pending live confirmation.
- Dependencies: none remaining for this specific menu. General item-name resolution ([Held-item name resolution](#held-item-name-resolution), Bag/shop item lists) is still a separate, unsolved, broader problem — this fix does not generalize to those.
- Story availability: available now.
- Next concrete action: live-test after the next narrator relaunch — confirm all 5 labels are actually spoken correctly on a return trip to this screen. Also unconfirmed: whether this exact order is fixed regardless of inventory/save state, or specific to this one instance.
- Completion criteria: live-test confirmation only; implementation and regression tests are done.

### Ribbons page decoding
- Exact blind-player failure: the summary screen's Ribbons page announces only its name, not actual ribbon contents.
- Expected accessible behavior: announce which ribbons the Pokémon has.
- Severity: 3.
- Dependencies: needs a Pokémon with at least one real, known ribbon to test the bitfield decode against — none confirmed available in the current save.
- Story availability: partially story-gated (most ribbons require specific achievements).
- Proposed smallest useful slice: revisit once a ribbon-holding Pokémon exists.
- Next concrete action: none until a test subject exists.
- Completion criteria: standard three-part.

### Collision (blocked-movement cue) — on hold, not ready for live testing
- Exact blind-player failure: walking into a wall, obstacle, or NPC produces no feedback at all.
- Expected accessible behavior: a distinct "blocked" cue specifically when the player is actively trying to walk into an obstacle — not merely standing near one.
- Severity: 1.
- **Rejected first cut:** stillness + facing a wall, with no input check — correctly identified by the project owner as an unacceptable false positive.
- **Current design:** `BlockedMovementReader` (own class, own flag `--collision-feedback`, independent of `--terrain-footsteps`) requires ALL five: movement input actively held, displacement below stillness threshold, forward collision geometry in the facing direction, sustained for a debounce window, not already fired this episode. Resets on movement resuming, input release, a material facing change, or the obstacle clearing.
- **Blocking dependency:** needs a verified "is a movement direction actively held" signal. Two candidates exist, **neither confirmed**: `movement_input.GSinputMovementSource` (game's own Control Stick cache, controller-port-0 assumption unconfirmed) and a `tagPeopleWork+0x54` animation-state enum (confirmed for AI-controlled walk/rotate via named setter functions, not yet confirmed for player-driven movement).
- Current evidence: gating logic and both candidate-source modules implemented and unit-tested; zero live verification of either signal.
- Next concrete action: on hold — deprioritized 2026-07-29 in favor of entity/treasure coverage, not abandoned. When resumed: a read-only live poll comparing the candidate value(s) across idle/blocked/walking states.
- Completion criteria: **do not mark "Partially accessible" or begin live testing until a movement-intent signal is verified.**

### Native footstep SFX / GDB trace — deferred, optional future enhancement only
- The original plan to reproduce the game's actual native footstep sound required a live GDB trace, deferred indefinitely per the project owner's explicit sign-off requirement, given the prior slowdown/boot-hang incident. No longer a dependency — the shipped synthetic footstep layer already answers "am I moving, what am I walking on" without it. Only worth reconsidering if the project owner specifically wants native-accurate terrain audio later.

### Sound-beacon-engine improvements — explicitly deferred by the project owner
- The project owner asked to investigate whether the existing NPC/entity proximity beacon engine (`npc_beacons.py`, `SpatialWavePlayer`) could be improved, then explicitly said to skip this investigation (2026-07-29) in favor of the entity/treasure coverage priority. Not started. Revisit if/when raised again — no assumptions made about what "improved" would mean without that conversation.

### Shadow Pokémon move display (summary/move-list shows post-purification moveset)
- Exact blind-player failure: a Shadow Pokémon's move list is announced as its eventual post-purification moveset (e.g. "Return, Lick, Refresh...") instead of what's actually usable right now (e.g. "Shadow Mist"), misleading the player about what moves are actually selectable in battle.
- Expected accessible behavior: announce the Pokémon's actual current moves, substituting the live Shadow move's name for whichever slot is currently shadow-locked.
- Severity: 2.
- Dependencies: none technical beyond finding the right field/logic — this is an investigation, not a story gate.
- Story availability: available now (reproducible against the current live save).
- Proposed smallest useful slice: disassemble the game's own move-list draw/resolution code to find what it checks to decide "show the Shadow move instead of the real one" — explicitly not a hardcoded per-species override table, per the project owner's standing no-hardcoding instruction.
- Current evidence: live-confirmed the struct's normal move slots already hold the real post-purification move; no separate shadow-override field found yet from a two-Pokémon byte diff alone. Full detail in [PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md) #6.
- Next concrete action: on hold at the project owner's explicit request, in favor of the footstep/collision investigation. Not abandoned.
- Completion criteria: standard three-part.

### Room or area summaries
- Exact blind-player failure: not yet characterized — no investigation performed.
- Expected accessible behavior: not yet defined.
- Severity: unknown.
- Dependencies: needs scoping first (what would "an area summary" actually say, and is that meaningfully different from what entity-nav + beacons already provide?).
- Story availability: available now.
- Proposed smallest useful slice: not yet defined — first requires a scoping pass, ideally prompted by a real moment during play where the project owner felt the lack of it.
- Next concrete action: none scheduled; explicitly not pursued speculatively per the master plan's overengineering rule.

---

## Story-locked / unresolved-reachability queue

**Correction (2026-07-29):** "story-locked" was previously used as a catch-all for anything not yet confirmed reachable, conflating "confirmed to require more story progress" with "reachability simply hasn't been verified." These are now split, per explicit instruction. Nothing below is asserted as story-blocked unless that's actually been established — most of this queue is genuinely **unresolved**, not locked, and should not be treated as fixed until the project owner reports their current position.

**Genuinely reached, awaiting audit (not locked at all):**
- **Shadow gauge / Hyper mode state.** A Shadow Pokémon (Teddiursa) is confirmed present in the current live save as of 2026-07-29 — this is reachable *now*, not locked. See coverage matrix's Shadow Pokémon systems section; likely a strong near-term candidate once the current on-hold items clear.

**Currently reachable, not story-gated at all (previously miscategorized as story-locked):**
- **Shops and the Bag/shop item lists.** Durable, repeatable locations — investigation already underway (see Shops section of the coverage matrix).
- **PC Storage (box grid, PC summary, Item Storage).** Durable, repeatable location — already directly investigated live in a prior session (task #50).

**Unresolved reachability — awaiting the project owner's report, not guessed:**
- **Purify Chamber and later purification systems.** No record establishes whether this has been reached.
- **Gateon Port bridge.** No record establishes whether this has been reached.
- **Later puzzles** (switches, object-placement/pattern puzzles, timing mechanics beyond ordinary doors/elevators/warps). No record establishes whether any such puzzle has been encountered.
- **Late-game battle states** (beyond ordinary switching/targeting, which are already generally covered). No record establishes what, if anything, late-game-specific has been encountered.

**Genuinely undiscoverable by definition:**
- **Unknown future menus/minigames/special interfaces.** Not yet discoverable until encountered.

---

## Regression queue

Existing, working features that must not silently break as new work lands. Verified via `python -m unittest discover -s tests -p "test_*.py"` after every change (361 passing as of 2026-07-29), plus periodic live spot-checks.

- Battle HP narration (`health.py` / `test_phase1f_health.py`)
- Manual HP summary hotkey (`hotkeys.py` / `test_battle_hp_summary.py`)
- VS/command menu narration (`test_battle_narrator.py`, `test_phase1e_menus.py`)
- Entity navigation, all categories (`test_entity_nav.py`, `test_authoritative_warps.py`)
- Party list/action/summary menu narration (`test_party_list_screen.py`, `test_party_action_menu.py`, `test_party_summary_screen.py`)
- Overworld dialogue and speaker names (`test_dialogue.py`, `test_entity_names.py`)
- Speech backend / lifecycle (`test_phase1b_lifecycle.py`, `test_phase1b_shutdown_and_reset.py`)
- Teleport (`test_teleport.py`, `test_memory.py`)
- Audio guide (`test_audio_guide.py`)
- PDA (`test_pda.py`)
- NPC proximity beacons (`test_npc_beacons.py`, `test_npc_sounds.py`, `test_npc_interactions.py`)
- Collision probe diagnostic (`test_collision_probe.py`)

This list should grow whenever a new feature graduates from "Implemented" to "Regression-tested" in the coverage matrix — it is not meant to be exhaustive of every test file forever, just the set of player-facing behaviors that would be a real regression if silently broken.

---

## Technical debt

- **`run_battle_narrator.py` lacks the single-instance mutex guard** that `run_accessible_pokemon_xd.py` has, allowing double-narration if both are ever running at once. See coverage matrix's Infrastructure section.
- **`INDEX.md` and `UNKNOWNS_AND_BLOCKERS.md` are stale** (dated 2026-07-25), describing a pre-production research state superseded by extensive verified work since. Not urgent to fix (this master plan and coverage matrix are now the current source of truth), but should eventually be refreshed or explicitly marked historical to avoid misleading a future session that reads them first.
- **XG-vs-vanilla-XD divergence remains formally unverified**, even though live work has succeeded repeatedly against the actual running game this session. Standing caveat, not an active task.

---

## Deferred ideas

- **Automatic multi-room route guidance** (a room-connectivity graph walking through doors automatically). Reasoned through and deliberately not built — doors/warps are already selectable entity-nav categories, so guiding to a door, walking through it, and reselecting in the new room already composes without new code. Revisit only if this composition proves too effortful in practice.
- ~~**General autowalk.** Explicitly rejected as a direction distinct from the read-only audio-guide approach the project owner chose instead, per the tension flagged and resolved earlier this session (autowalk means sending input, which the audio guide deliberately avoids).~~ **Reversed and implemented 2026-08-16** at the project owner's explicit direction. The rejection rested on a premise that turned out to be false: autowalk does *not* have to send input. `heroMove.s` carries the engine's own scripted-stick override (`HeroMove+0x3AE`, read by `_getStickData` before the controller is ever consulted, and used by the game itself in `_heroMoveSlowStopFactor`), so the companion writes five bytes and the engine walks the character through ordinary locomotion — no synthetic keyboard, no virtual gamepad, no Dolphin focus requirement, and no position write. See `autowalk.py`, `hero_stick.py`, and the coverage matrix's Autowalk entry. Implemented but **not yet live-tested**.
- ~~Text (0xC) and PC (0xE) entity-nav interaction-table types.~~ **Resolved 2026-07-29** — both implemented as `sign`/`pc` categories; PC live-confirmed, sign not yet live-tested. See the active-foundational-feature section above.

---

## Completed slices

Slices that have reached the full three-part completion bar (Implemented + Live-tested + Regression-tested) as of 2026-07-29. See [ACCESSIBILITY_COVERAGE_MATRIX.md](ACCESSIBILITY_COVERAGE_MATRIX.md) for full detail on each.

- Title screen / main menu / options
- Command menu, move menu (name/type/PP), ability text
- Battle HP/status settled narration, manual HP summary hotkey
- Overworld NPC dialogue (scripted + free-roam) and speaker names
- Party list screen, party action popup, Give/Take popup, Bag category tabs
- Bag item list (per-category item/quantity narration, shared item-name resolution infrastructure)
- Entity navigation (NPC/door/elevator/warp/healing) and its refresh hotkey
- Authoritative warp/door/elevator data (full 177-room extraction)
- Audio guide (hot/cold tone)
- NPC proximity sound beacons (currently muted by request, code otherwise complete)
- PDA / Trainer Card
- Yes/No confirmation dialogs
- Dynamic party-address resolution (savedata randomization fix)
- Dialogue crash fixes (transient-read crash, eager player-name read)
- Party summary screen's multi-Pokémon slot-selection fix (live-confirmed 2026-07-29)
- Synthetic terrain footsteps (live-confirmed 2026-07-29, after finding and fixing a real threshold bug via live data; remaining checklist items — menu/turn-in-place silence, real terrain-change correlation, speech clarity, input lag — explicitly skipped by the project owner's own choice, not exhaustively confirmed)
- Item/treasure entity-nav category (live-confirmed 2026-07-29 via the narrator's own log — accurate multi-room detection and monotonic distance tracking into interaction range)

Not yet complete (Implemented + Regression-tested, but live-test outstanding): the five newly-added battle notifications, teleport's NPC-category approach-position fix. These stay in "Next reachable features" above until confirmed live.

## Navigation — deferred after the walk-model rewrite (2026-08-02)

The obstacle-aware audio guide is now **live-confirmed on the original
terraced route** (`AUDIO GUIDE Arrived.`, 2026-08-02 14:17:22; routes on the
game's own CCD +0x24 walk model with real layer identity — see
`WORLD_NAVIGATION_ARCHITECTURE.md` §6). These items were consciously left
undone rather than forgotten:

1. ~~**Line-of-sight route simplification**~~ **DONE 2026-08-03** (found
   2026-08-04 by reading the code — the session that did it left no
   documentation anywhere; see `WORLD_NAVIGATION_ARCHITECTURE.md` §6a for
   the full recovered list, which also includes the waypoint-span rescale,
   the `MAX_TILES` fix that had been failing **every route in Gateon Port**,
   the stall-timer retirement, and the committed waypoint sequence).
   Shipped as `simplify_route` in its conservative **collinear-collapse**
   form rather than line-of-sight shortcutting, which keeps the
   walkable-straight-line guarantee by construction. Measured against the
   real 2026-08-04 route: 0 of 18 legs is worse than the hops it replaced.
   True shortcutting between non-collinear nodes is still unimplemented and
   would need a swept test against both models — not currently justified.

2. **First waypoint changes between guide re-toggles from the same spot.**
   Reported live; **not reproduced** under investigation — the flow field is
   deterministic (6/6 identical builds, identical first hop) and the first
   waypoint is stable across ±3 units *and* across a tile boundary at the
   tested position. Leading hypothesis: equal-cost **branch points**, where two
   adjacent tiles each have a different but equally optimal next hop, so
   crossing between them flips the aim point. Needs the player's position at
   the moment it happens to confirm — adding position logging to the guide is
   the cheap next step.

3. **Dynamic object-enable state — IMPLEMENTED 2026-08-13, live validation
   still owed.** `GScolsys2SetObjEnable` is called from `script.s` and
   `WalkGetHeight` skips disabled objects, so scripted geometry changes are
   real — and treating every object as enabled was actively inventing walls,
   not merely missing a feature. It sealed Agate's Relic Stone cave mouth into
   a 26-tile pocket (`M3_out` object 33) and split the cave interior
   (`M3_cave_1F_1` objects 4, 5), the latter producing a confident route
   ending 180.4 units from the exit.

   The earlier probe at `≈0x80445C20` "returned mapped memory but a byte
   pattern that did not clearly match" — **that is explained**. The record
   base is `GScolsys2 + 0x04`, not `+0x00`; probing at `+0x00` with stride
   `0x28` reads each record's transform floats shifted by four bytes, which
   is exactly a plausible-but-wrong pattern. The full structure, its
   derivation from `GScolsys2.s`, and a binary-image byte match verifying the
   address are in COLLISION_DETECTION_INVESTIGATION.md §"Runtime
   object-enable state".

   `LiveObjectEnableState` now reads it; `NavigationService` invalidates
   geometry and discards stale routes on change. **LIVE-VALIDATED 2026-08-13
   in `M3_out`**: the engine reported object 33 disabled, wall triangles fell
   1097 → 1095, the cave pocket became the 1861-node component predicted
   statically before the game was run, and the `cause=disconnected` /
   partial-route failures stopped. See COLLISION_DETECTION_INVESTIGATION.md
   §"Live confirmation".

   **Remaining:** the Gateon oracle (entries 23–31 against `pier_def`/flag
   968) — a second, independent confirmation on a room that toggles objects
   *mid-session*, which Agate does not exercise. 27 of 212 room scripts use
   the mechanism.

4. **Rooms whose walk model is absent or unparseable.** 10 of 177 `.ccd` files
   have no +0x24 model at all; a further 3 (`M6_pc_1F`, `M6_tower_3F`,
   `M6_tower_4F`) fail parsing outright on non-finite vertex values — a real,
   newly-discovered data issue, uninvestigated. All load as an honest empty
   result and fall back to direct guidance; none crash.

5. **Undecoded walk-triangle metadata.** Byte +0x30's two nibbles are the
   engine's `0xF` sentinel throughout `M3_out`, but other rooms show
   non-sentinel values whose meaning is unknown. Preserved raw as
   `WalkTriangle.raw_metadata_byte` so this can be decoded later without
   re-parsing every file. Also unresolved: the purpose of the **second** hit
   model at +0x34 versus +0x28.

6. **Cross-room routing** remains explicitly out of scope — `NavigationService`
   is intra-room only; a floor change invalidates the route. Doors and warps
   are already their own entity-nav categories, so guiding to a door, walking
   through, and re-selecting composes naturally.

7. **Guide hotkeys split (2026-08-04).** `ctrl+shift+n` now carries the
   obstacle-aware routed navigation that `ctrl+shift+g` used to; `g` is now
   a plain beacon sitting on the selected entity, with no routing at all.
   Only one runs at a time. Not yet live-tested — the announcements changed
   ("Beacon on." / "Navigation on." instead of "Guide on."), so this needs
   confirming by ear on the next play session.

8. **Waypoint capture ignored height — fixed 2026-08-04, not yet
   live-tested.** A fallen player was credited with reaching a waypoint 44.7
   units above their head. Full incident, evidence and fix in
   `WORLD_NAVIGATION_ARCHITECTURE.md` §6b; what the follow-up measurements
   did and did not establish is in §6c. **The measurements specifically did
   NOT justify clearance-aware routing** — the drop-off metric behind that
   idea failed its own sanity check three times and is documented as
   unreliable. Do not implement it without a drop-off test that correctly
   reports an indoor room as having no drops.

9. **Still unexplained: what made the player leave the route on 2026-08-04.**
   The capture fix explains the guide's behaviour after the fall, not the
   fall. Two logged positions 5.8 s apart cannot locate it (100–200 units of
   unobserved travel at measured walking/running speed). Cheap next step:
   log the player's position every poll while the guide is active, not only
   when a waypoint changes.

**Shelved, not backlog:** `traversal_log.py` (conservative walked-edge
recorder). Built on the assumption that floor data was missing; that premise
is false, so learning walkability from player trails would be strictly worse
than reading the surface the engine itself walks on. Kept and tested but with
zero importers — do not wire it in without fresh justification.


## 2026-08-06 — battle-system additions (Phases 1-3)

Added by the battle audit. See `BATTLE_SYSTEM_ARCHITECTURE.md`,
`BATTLE_ACCESSIBILITY_AUDIT.md`, `BATTLE_IDENTITY_MODEL.md` and
`BATTLE_MESSAGE_PIPELINE.md`.

**Ready to act on**

1. **Battle Yes/No labels are an authoritative resource.** Message 20390 is
   the battle Yes/No panel's own label string, and 20389 / 20391 are the
   move-forget prompts. `menus.yes_no_focus` currently hardcodes
   `("Yes", "No")`. Blocked only on the `<SCOL=…>` markup question below.
2. **`<SCOL=0x0d0e0f>` markup grammar.** Six menu-panel strings carry it as
   literal text, not as the binary colour opcode. Needs its grammar
   established before any panel string is spoken; do not regex-strip.
3. **`profile.command_labels`** (`Fight`/`Item`/`Pokemon`/`Call`) is still an
   unverified index→word tuple — the same pattern already corrected once for
   `shop_menu_labels`. Verify by selecting each position and checking the
   resulting screen, not by trusting the spoken label.
4. **Dead code cleanup:** `resolver.trainer_party_names`,
   `opponent_trainer_full_name`, `opponent_trainer_name` are no longer called
   in production. Inert, not a second speech path.

**Awaiting evidence**

5. **Does any stat change have no message?** The one thing that would
   justify re-enabling `HealthTracker(narrate_stat_stages=True)`.
6. **`_TRAINER_LOSE` (0x24) / `_TRAINER_CLIENTNO` (0x27) writers**, used by
   three templates, all link-battle forms.
7. **Unsent party slot HP** — carried over from 2026-07-30; still blocks a
   "Pokémon remaining" count.

**Live-trigger queue** (implemented, automated-test validated, never seen
running): the full status/effect family, Call messages, Shadow discovery,
Reverse Mode, money reward, wild appeared, capture, nickname prompt, all four
send-outs plus the two-trainer 20309 form, trainer class+name, speaker opcode
0x59, side-name qualifiers, Baton Pass identity, doubles level-up recipient,
and the no-self-interrupt speech change.

## Navigation: region-aware routing (2026-08-12)

Routed guidance now accepts a route only when an ordinary walkable path
reaches the destination's interaction region. Distance-based acceptance is
retired. See `NAVIGATION_AUDIT_2026-08-04.md` 6h and
`WORLD_NAVIGATION_ARCHITECTURE.md` 6k.

**Routed coverage is intentionally lower** -- roughly 43% of interaction
pairs, down from 69.3% -- because the removed 26 points were false routes:
measured, 1759 of 2024 previously-accepted reseeds put the player on the far
side of a wall from the destination. The invariant is zero known false
`VERIFIED` routes, not maximum coverage.

Remaining limitations, all measured and none fixed here:

- Cross-level destinations within one room are diagnosed (`height_layer` /
  `disconnected`), never routed.
- `M3_cave_1F_1`'s passage reads as disconnected pockets in the collision
  data even though the player can walk it; wall semantics are not yet
  investigated.
- Region target hysteresis and reachable-component selection are specified
  but not implemented.
- Worst-case route build in `M6_out` remains multi-second.
