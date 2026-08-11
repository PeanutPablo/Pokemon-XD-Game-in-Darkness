# ENTITY_IDENTITY_MODEL.md

How every navigable entity is identified, and how duplicates are rejected.
**Phase 2, 2026-08-06. Revised 2026-08-09.** NPCs are complete *in code*;
the other categories carry the Phase 1 audit's findings and are filled in
as their phases land.

> **⚠ §2 describes code production does not run.** `LiveNPCEntitySource`
> was reverted out of `phase1b_app.build_overworld_sources` on 2026-08-06.
> Production identifies NPCs as `("npc", floor_id, index)` — the key whose
> `[1]` element is the **floor id**, which is exactly what the
> duplicate-clerk predicate matches on. See
> [ENTITY_NAVIGATION_AUDIT.md](ENTITY_NAVIGATION_AUDIT.md) §0.2.
>
> **Rule 6 warning (2026-08-09).** The actor-vs-static `people_info_id`
> cross-check is a project-invented consistency rule the engine does not
> apply. It is the single rule most able to empty the NPC category if
> `people_work +0x1C` is not what the profile assumes — and emptying the
> category is precisely what forced the revert. Before Phase 2 is
> re-enabled, rule 6 must either be live-confirmed or demoted from a
> rejection to a logged warning.

---

## 1. The requirement

An identity key must survive ordinary polling — the player walking, the
NPC walking, the actor being hidden and shown — and must change when the
runtime entity behind it is genuinely replaced. It must never be a name, a
rounded coordinate, a list position, or the room.

## 2. NPCs — `(groupID, resID)`

**Source:** `people_work +0x14` and `+0x18`.

This is the engine's own key, not a convention this project invented:
`floorCharacterBiosFindByResID(groupID, resID)` is the function
`peopleTalkCheck` itself calls to get from a live actor to its static
record, and `floorDataBiosGetCharInfo` resolves `resID` as a direct index
into the current room's `floor_character` array
(`charBase + resID * 0x24`, bounds-checked).

Published as `("npc", groupID, resID)`.

### Validity rules, in the order applied

| # | Rule | Rejection reason recorded |
|---|---|---|
| 1 | slot occupied (`+0x00`) | not published |
| 2 | `groupID != 0` | `global/follower slot (groupID 0)` |
| 3 | `resID` does not carry the `0x7FFF0000` marker | `treasure actor (Phase 3 owns these)` |
| 4 | `groupID` is one of the current floor's group ids | `groupID does not belong to the current floor` |
| 5 | `resID` is inside this floor's character array | `resID outside this floor's character array` |
| 6 | actor's people-info id equals the static record's | `people-info mismatch: actor N vs static M` |
| 7 | a live model position is readable | `no readable live model position` |
| 8 | no other slot already published this identity | `duplicate identity already published from another slot` |

Rule 4 replaces the previous code's `identity_a != 0`. The engine compares
`groupID` against `floorDataBiosGetGroupID(currentFloor)` — an exact match
against `floorData + 0x2C + 4 * L`, where `L` is a language index derived
from `pokecoloGetLanguage()`. **That language global has not been
located**, so this project reads the whole 5-slot range and tests
membership. Weaker than the engine's exact comparison, strictly stronger
than "not zero", and it cannot pick the wrong language's id by guessing.
The diagnostic logs the actual `groupID`, so the slot can be pinned from
evidence and this tightened.

Rule 6 is an independent cross-check rather than a restatement: the live
actor's type (`people_work +0x1C`) and the static record's type
(`floor_character +0x06`) are written from different places, so a
disagreement means the *correlation* is wrong. Publishing an entity the
engine would not recognise is worse than publishing none.

Rule 8 is the deduplication rule. Note what it is not: two actors are
**never** merged for sharing a name, a species, a model, a role, or a
position. `test_people_runtime.test_separate_actors_stay_separate` pins
that with two NPCs sharing a name at coordinates 0.14 units apart.

### Generation (epoch)

`generation` increments when the `(slot, model pointer)` binding for an
identity changes — i.e. the runtime entity was reallocated. It does **not**
move when the NPC walks, is hidden, or is re-read. Exposed in
`Entity.metadata["generation"]` so a consumer can tell "the same NPC moved"
from "a different NPC now holds this identity".

### What is deliberately *not* the identity

- **The `floor_character` index alone.** It is `resID`, but without
  `groupID` it does not distinguish this room's character 3 from a lingering
  actor from another floor group. That ambiguity is the mechanism by which
  a stale actor could previously clobber a live one's position.
- **The floor id.** Using it as a *role* identifier is exactly the defect
  Phase 2 removed; see `ENTITY_NAVIGATION_AUDIT.md` cause A.

## 3. Roles are an attribute, not an identity

An NPC's role (Poké Mart clerk, Pokémon Centre nurse) is resolved from its
own **talk script id** (`floor_character +0x14`,
`floorCharacterBiosGetTalkSctID`) against a table derived from the game's
own room scripts: a talk function that reaches
`Dialogs::openPokemartMenu` is a clerk; one that reaches `Character::101`
(`useHealingMachine`) is a nurse. See
[`INTERACTABLE_OBJECTS.md`](INTERACTABLE_OBJECTS.md) once Phase 4 lands for
the object-side equivalent.

The derived table covers **15 rooms and 16 role NPCs**, generated by
`Companion/build_npc_role_table.py` into
`Companion/assets/npc_roles.json`. Agate's Mart (`0x86`) resolves to
exactly **one** clerk script and Agate's Centre (`0x85`) to exactly one
nurse script, against the three and three NPCs those rooms actually
contain.

**Remaining assumption, stated plainly:** the extracted dumps name script
functions `talk_<N>_<description>`, and this project reads `<N>` as the
talk script id. The numbers are per-room-unique and sit in a
global-looking range rather than being small table indices, which is
consistent — but it is **not confirmed against a live
`floor_character +0x14`**. Until it is, an unmatched id resolves to *no
role*, and the NPC keeps its ordinary name or letter. Nothing is guessed
into a role. The interaction diagnostic logs live `talk_sct=` values
precisely so this can be settled.

## 4. Unnamed-NPC letters

Letters are a *label*, never an identity. They are issued by
`entity_sources.LetterRegistry`:

- assigned per canonical identity, in first-seen order by identity;
- **remembered** for the room visit, so an NPC despawning cannot rename
  the ones after it (the previous code recomputed them from the live set
  every call, so the player's "B" silently became someone else's while they
  were walking toward it);
- consumed only by NPCs that actually need one — a clerk or a named NPC
  never burns a letter, so there are no gaps;
- reset on a room change;
- spoken bare: **"A"**, not "NPC A". The category header already said NPCs.

An NPC whose name becomes resolvable mid-visit simply stops asking for a
letter. Its retired letter is not reissued, so nobody inherits a label the
player has already learned.

## 5. Other categories

Unchanged from Phase 1 and carried here for completeness.

| Category | Identity | Status |
|---|---|---|
| Item / treasure | should be the **global `floor_tresure_list` index**, which `peopleBiosSetTresureID` puts on the actor and which does not renumber per room; the per-room ordinal in `resID` is the secondary key. Is currently `("item", room, kind, x, y, z)` with raw floats | **Phase 3**, revised 2026-08-09 |
| Room-script interactable | `(room_id, region_index)` — both in the interaction record; the handler name is the *subtype*, not the identity | **Phase 4**, see [INTERACTABLE_OBJECTS.md](INTERACTABLE_OBJECTS.md) |
| Warp / cutscene warp | `("warp", common.rel record index)` | authoritative |
| Door / elevator / PC / sign | `(kind, common.rel record index)` | authoritative |
| Healing station | none — one hardcoded coordinate | **unresolved**, Phase 4 |
| Bridge endpoint | none defined | **Phase 5** |

Per the standing rule: a source with no authoritative identity is marked
unresolved rather than given an invented one.
