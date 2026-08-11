# ENTITY_STATE_AND_BEACON_POLICY.md

What an entity's state means, and which states are allowed to make noise.

**Written 2026-08-09** as a Phase 1 (audit) deliverable. This document
defines the policy the later phases implement; **none of it is implemented
today**, and §4 records exactly how far the current code is from it.

---

## 1. Six conditions, not one

The audit brief's central structural point, restated as the model this
project will use. These are independent:

| Condition | Means | Wrong answer costs |
|---|---|---|
| **exists** | a record for it is present in the room | listing something the room does not contain |
| **spawned** | the runtime object has been created | announcing an item before the story places it |
| **visible** | the game is currently drawing it | steering to a hidden NPC |
| **interactable** | pressing A (or entering) will do something | "Interaction available" that does nothing |
| **landmark** | still useful to navigate by, even if used up | losing the opened chest a player orients by |
| **beaconing** | should emit a repeating sound | an opened box that keeps sounding like treasure |

`Entity` today can express **none** of them. It has `category`,
`identity`, `label`, `position`, `interaction_distance`, `subtype`,
`metadata` — and appearing in a source's output is simultaneously "exists",
"interactable" and "beaconing", because `WarpAugmentedNPCSource`
synthesises `NPC(visible=True, talk_id=1)` for every entity any wrapped
source returns.

That single line is why an opened item box cannot be silenced without
also deleting it, and it is the structural half of audit cause **F**.

## 2. The state fields, and what each one reads

Only fields with a named engine owner. Nothing speculative — the brief's
rule, and the reason this list is shorter than the brief's candidate list.

| Field | Type | Source | Applies to |
|---|---|---|---|
| `exists` | implicit | publishing the entity at all | all |
| `spawned` | bool | treasure record **+0x08** general flag; live actor present | items, story objects |
| `collected` | bool | treasure record **+0x06** general flag | items |
| `visible` | bool | `people_work +0x0D` (`disp`) | NPCs, items |
| `enabled` | bool | `GScolsys2GetObjEnable(entry)` | CCD-region objects, bridges |
| `interactable` | bool | `talk_predicate` verdict (NPCs); method byte + region containment (regions) | all |
| `landmark` | bool | policy, see §3 | all |
| `beacon` | enum | policy, see §3 | all |
| `generation` | int | `(slot, model)` binding change | live-actor entities |
| `interaction_position` | vec3 | neck reference / nearest point on region | all |
| `confidence` | enum | which inputs were readable | all |

`collected` and `spawned` are **separate flags in the engine**, at
different offsets, tested by different branches of `_floorInitTresure`
(see [ENTITY_NAVIGATION_AUDIT.md](ENTITY_NAVIGATION_AUDIT.md) §0.6). This
is why the model does not collapse them into one tri-state: the game does
not, and the player needs different wording for "you already took this"
versus "this is not here yet".

## 3. The policy

### 3.1 Navigation eligibility

An entity appears in the cycle when it **exists**, is **on the current
room/floor**, and its position is **currently readable**.

It does **not** appear when:

- no live runtime object backs it and the category requires one (NPCs,
  spawned items) — a static record alone is never proof of presence;
- its spawn flag says it has not spawned;
- its `enabled` state is known to be false;
- its identity is unresolved (per the standing rule, unresolved sources
  publish nothing rather than an invented identity);
- the game can never interact with it and it is not a useful landmark
  (talk-flag-blocked NPCs, talk-start-type 3).

An entity that exists but is not currently interactable **stays in the
list** with wording that says so. A blind player still needs to know the
clerk is there while walking toward them.

### 3.2 Beacon eligibility — deliberately narrower

| Entity state | In the cycle | Beacon |
|---|---|---|
| unopened item box | yes | **yes** — item beacon |
| **opened** item box | yes — "Opened item box" | **no** |
| loose item, not yet spawned | no | no |
| loose item, spawned | yes | **yes** |
| loose item, collected | no | no |
| NPC, live and talkable | yes | yes |
| NPC, live but permanently blocked | no | no |
| NPC, static record with no actor | no | no |
| duplicate runtime record | no | no |
| machine / terminal / television / bed | yes | category beacon, only where it earns the noise |
| sign / bookshelf | yes | no — reading it is not urgent |
| hazard (`hero_fall`, `booth_battle_*`) | yes | **proximity warning, not a destination beacon** |
| bridge endpoint, current alignment | yes | yes |
| bridge endpoint, stale alignment | no | no |
| anything whose position is cached but unverified | no | no |

The rules that generate that table:

1. **A beacon is a claim that going there is useful right now.** An opened
   box fails that; it is still a landmark, so it stays listed and silent.
2. **A beacon must not survive its reason.** Nothing beacons because its
   coordinate is still in a cache.
3. **Beacons are not free.** Every simultaneous beacon costs
   intelligibility. Categories that are read rather than used (signs,
   bookshelves) do not get one.
4. **Hazards invert the sound.** A hole is not a destination; its cue
   means "stop", not "come here". Distinct sound, distinct behaviour.

### 3.3 Wording

Per the brief:

- unnamed NPCs speak as **"A"**, never "NPC A" — the category header
  already said NPCs;
- containers are **"Item box"** and **"Opened item box"**, never named by
  what they contained;
- an opened box loses its interaction wording as well as its beacon;
- an entity whose interactability could not be determined says **"In
  range"**, never "Interaction available" — the current
  `talk_predicate`/`describe_entity` split already implements exactly this
  and is the pattern the other categories should copy.

## 3a. Containers and loose items — IMPLEMENTED 2026-08-09 (Phase 3)

`treasure_entities.py` now implements §3 for pickups. The states are not
collapsed:

| State | Source |
|---|---|
| record exists | `floor_tresure_list`, kind in (1, 2, 3) |
| spawned | `+0x08` general flag, or true when the record carries none |
| collected | `+0x06` general flag, written by `floorEventCtrlTresure` mode 2 |
| live actor exists | a `people_work` actor with `resID == 0x7FFF0000 \| ordinal` |
| visible | that actor's `disp` |
| interactable | spawned and not collected |
| landmark | **kind 1: spawned** (a collected box keeps its actor). **kinds 2/3: spawned and not collected** (a collected loose item is hidden) |
| beacon | interactable — strictly narrower than landmark |
| unresolved | a flag the reader could not answer → published nowhere |

The landmark row is the whole reason "Opened item box" can stay in the
list while "collected loose item" cannot, and it is read off
`floorEventCtrlTresure` mode 0 rather than chosen.

**Both state flags are ordinary general flags**, so collected and spawned
are answerable before the room's actors exist. A script-driven spawn or
collection therefore appears on the next poll with **no room reload** —
the requirement in §7 of the Phase 3 brief.

**Cache lifetimes here**, per §5's rule: the parsed record table is cached
per room and rebuilt on a room change; flags, actor presence, `disp` and
position are re-read every query and never cached.

**The beacon split is now real.** `WarpAugmentedNPCSource` skips any entity
whose `metadata["beacon"]` is False, so an opened box stays in navigation
and goes silent. A source with no opinion keeps the previous
beacon-everything behaviour, so nothing else changed.

## 3b. Hazards (Phase 4, 2026-08-09)

A hazard is a **warning**, not a destination. `hero_fall` regions are holes
a blind player has no way to perceive, and nothing in this project warned
about them before.

| Property | Hazard |
|---|---|
| navigation | **yes** — own `hazard` category, direction and distance |
| beacon | **never** — `metadata["beacon"]` is False |
| interaction wording | **never** — no `interaction_distance`, no verdict, so `describe_entity` cannot say "Interaction available" |
| position | nearest point of the region, like every other region entity |
| inactive | suppressed, same as any unresolved record |

Hazard *navigation* eligibility is deliberately separate from any future
hazard *warning* behaviour: automatic proximity warnings are not
implemented in this phase, and adding them later changes no policy here.

## 4. Distance from this policy today

| Policy | Today | Cause |
|---|---|---|
| beacon separable from listing | **FIXED (Phase 3)** — `WarpAugmentedNPCSource` honours `metadata["beacon"]`; a source with no opinion is unaffected | F / X3 |
| opened box silenced | **FIXED (Phase 3)** — read from the `+0x06` general flag, not inferred from a record vanishing | E |
| collected ≠ unspawned | **FIXED (Phase 3)** — separate `+0x06` and `+0x08` flags | E |
| static record is not proof of presence | violated — `NPCMemorySource` falls back to the static spawn position **and** the stale static visible bit | B |
| unresolved publishes nothing | violated — hardcoded "Healing station" publishes a hand-captured coordinate with no owner (and it is actually a bed) | H1 |
| enabled state respected | not read — `StaticObjectEnableState` answers "always enabled" | H |
| interaction position ≠ world position | implemented for NPCs in `LiveNPCEntitySource`, **which production does not run** | §0.2 |

## 5. Cache lifetimes and invalidation

The brief requires these stated exactly.

**May be cached indefinitely (static geometry):**

| Data | Lifetime | Invalidated by |
|---|---|---|
| `common.rel` interaction records | process | never |
| room `.ccd` triangles and region vertices | process | never |
| room-script function tables / object table | process | never |
| `assets/npc_roles.json`, room ids, entity names | process | never |

**Cached per room visit (static, room-scoped):**

| Data | Lifetime | Invalidated by |
|---|---|---|
| `floor_character` records | room | floor id change |
| `peopleInfoData` records | table identity `(base, count)` | table reallocation |
| unnamed-NPC letters | room visit | floor id change |

**Never cached (live):**

positions, `disp`, actor flags, live talk distance, talk verdicts,
treasure collected/spawn flags, `GScolsys2` enable state, general flags,
bridge alignment, the set of published entities.

**Invalidation triggers, and what each must clear:**

| Trigger | Clears |
|---|---|
| room/floor change | everything room-scoped: letters, static caches, selection, category, opened-box memory |
| story flag change | role and object gating, treasure spawn/collect state |
| NPC moves | nothing — live position is re-read every query by construction |
| NPC spawns / despawns | published set; letters are **kept** so surviving NPCs do not get renamed |
| item spawns / collected | published set, beacon, opened-box memory |
| bridge alignment change | bridge endpoints, `GScolsys2` enable state, **and the routing geometry** |
| object enabled/disabled | that object's entity and the routing geometry |
| dialogue / menu / cutscene / loading / transition | actions suppressed; **selection preserved** (deliberate — see `_refresh_context`) |
| source read failure | that source only, per §6 |

## 6. Failure isolation

Today one source raising `MemoryError` causes
`phase1b_lifecycle.poll_entity_nav` to `clear()` the whole navigator,
discarding the player's category and selection (audit defect X2). The log
shows this firing in production: `ENTITY NAV cleared: entity-nav read
failure`, 2026-08-08 18:26 and 2026-08-09 00:56.

Required behaviour: a failing source contributes **nothing** and is
logged; every other category keeps working; the selection survives if its
own source is healthy. Silence in one category, never collapse of all six.

## 7. Confidence, and the standing rule

Every entity carries which of its inputs were readable. Where a gate could
not be evaluated, it is reported UNKNOWN and **never counted as a pass** —
the rule `talk_predicate` already follows, which is why it says "In range"
rather than "Interaction available" when it cannot see the whole picture.

The rule this whole document exists to serve: **a blind player cannot
visually check a wrong target.** When location, state, identity or
interaction point is uncertain, the entity is omitted or explicitly marked
unresolved. It is never presented as a valid destination.
