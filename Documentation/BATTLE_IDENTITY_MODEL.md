# BATTLE_IDENTITY_MODEL.md

**Status:** Phase 2 deliverable, created 2026-08-06. Implemented in
`Companion/battle_narrator/battle_identity.py`; regression coverage in
`Companion/tests/test_battle_identity.py`.

Companion to [BATTLE_SYSTEM_ARCHITECTURE.md](BATTLE_SYSTEM_ARCHITECTURE.md)
and [BATTLE_ACCESSIBILITY_AUDIT.md](BATTLE_ACCESSIBILITY_AUDIT.md).

---

## 1. The seven concepts, kept separate

| # | Concept | Authoritative source | Survives switch? | Survives Baton Pass? | Distinguishes duplicate species? |
|---|---|---|---|---|---|
| 1 | Persistent party Pokémon | `FightPokemon*` + `Pokemon+0x28` personality | yes | yes | **yes** |
| 2 | Trainer-side party position | address arithmetic over the party array | yes | yes | yes (within a trainer) |
| 3 | Live battler slot | active-array index | **no** | no | no |
| 4 | Current battle record | `FightOutPokemon*` | no | **wrapper survives, occupant changes** | no |
| 5 | Message-event subject | the message's own msgctrl opcode | n/a | n/a | only via the resolved record |
| 6 | Send-out / replacement | `_MY_MONS*` / `_ENEMY_MONS*` + occupancy epoch | n/a | n/a | no (text only) |
| 7 | EXP / level-up recipient | `get_exp_fight_pokemon_ptr` | yes | yes | yes |

They correlate in a single battle against one Pokémon and stop correlating
the moment anything interesting happens. Treating any one of them as a
stand-in for another is what produced every bug in this phase.

---

## 2. Identity-source inventory

Everything below was read out of `xd-decomp`'s own disassembly or symbol
table. "Lifetime" is how long the value is meaningful.

### 2a. Message-subject globals holding a `FightOutPokemon*`

Handler resolves to `fightOutPokemonGetNicknamePtr(global)` in every
non-link battle (`msgctrlAttackMons`, 0x801541C4).

| Symbol | Address | Opcode | Identifies | Lifetime | Changes when | Duplicate-safe |
|---|---|---|---|---|---|---|
| `_ATTACK_MONS` | `0x804EB1FC` | 0x0F | acting battler | one action | `fightFloor_SetAttackPokemonPtr` | yes (via record) |
| `_DEFENCE_MONS` | `0x804EB200` | 0x10 | targeted battler | one action | `fightFloor_SetDefensePokemonPtr` | yes |
| `_CLIENT_MONS` | `0x804EB204` | 0x11 | "client" battler | one action | `fightFloorSetStatus` | yes |
| `_TSUIKA_MONS` | `0x804EB208` | 0x12 | secondary-effect subject | one action | `fightFloor_SetTuikakoukaPokemonPtr` | yes |
| `_CLIENTNOWORK` | `0x804EB238` | 0x1E | ability-holder | one message | `msgctrlClientnowork` | yes |

**Known failure case:** all of these read null outside the brief window a
message is open. 2,271 `SAMPLE_REJECTED ... invalid address 0x00000000`
entries in the production log come from readers sampling one of these for a
message that does not use it.

### 2b. Send-out name globals — text, not pointers

| Symbol | Address | Opcode | Stored type |
|---|---|---|---|
| `_MY_MONS` | `0x804EB210` | 0x14 | GSchar text pointer |
| `_MY_MONS2` | `0x804EB214` | 0x15 | GSchar text pointer |
| `_ENEMY_MONS` | `0x804EB218` | 0x16 | GSchar text pointer |
| `_ENEMY_MONS2` | `0x804EB21C` | 0x17 | GSchar text pointer |

Single writer:
`_fightActionFlowKaisiNyuujouPokemonSubAppearMsg` (`0x8020B700`).

Three properties that matter, all from that function's disassembly:

1. It stores the **same** nickname pointer into both members of a pair
   (0x14 with 0x16, or 0x15 with 0x17). So either may be read, and the
   partner is a valid fallback when one is null — not a guess.
2. Which pair it picks encodes the entering **position**, and the mapping
   is **inverted between the player's side and the foe's**
   (`fightOutPokemonIsGcHeroFightOutPokemon` selects the branch). So
   "`_ENEMY_MONS` is the enemy's" is false.
3. For a single send-out it always writes 0x14 and 0x16 regardless of side.

**Consequence for the model:** the only thing that says whose send-out it is
is the **message ID** (20312/20313 player, 20304/20305 foe), and the only
thing that gives the two names in the right order is the **message
template's own opcode sequence** (20313 prints 0x15 then 0x14; 20305 prints
0x16 then 0x17). `send_out_names()` replays that sequence, so it needs no
assumption about positions at all.

**Not sufficient as identity.** These are display text. Two identical
nicknames produce identical strings. They are authoritative for *what the
game says* and are matched against live battlers separately.

### 2c. Trainer name globals

| Symbol | Address | Opcode | Notes |
|---|---|---|---|
| `_TRAINER_TYPE` | `0x804EB248` | 0x22 | trainer class, live for the current message |
| `_TRAINER_NAME` | `0x804EB24C` | 0x23 | personal name |

Replaces walking side 1 / trainer 0 in the deck tables, which is only
correct in a single battle against one trainer. 1,142 logged rejections came
from the old route.

### 2d. Persistent records

| Source | Address | Identifies | Notes |
|---|---|---|---|
| Party array | `floor + 0x14 + side*0x6EF0 + 0x64 + trainer*0x3744 + 0x97C + slot*0x300` | party position | never moves; each term confirmed by `fightFloor_GetFightSidePtr` / `fightSide_GetFightTrainerPtr` / `fightTrainer_GetFightPokemonPtr` |
| `Pokemon+0x00` u16 | — | species | `Pokemon::getPokemonDataId` |
| `Pokemon+0x28` u32 | — | **personality (PID)** | `getRnd__7PokemonCFv`; independently corroborated by `Pokemon-XD-Code`'s `kPartyPokemonPIDOffset = 40` |
| `Pokemon+0x4E` | — | nickname | `pokemon_GetNicknamePtr` |
| `FightOutPokemon+0x84F` u8 | — | has-been-switched | `fightOutPokemon_GetIrekaetaFlag` |
| `FightOutPokemon+0x862` s16 | — | incoming party entry | `fightOutPokemon_GetIrekaeTargetEntryId` |
| `get_exp_fight_pokemon_ptr` | `0x804EB964` | EXP recipient | `FightPokemon*`; set/cleared per recipient by `WS_GET_EXP` |
| Active battler array | `floor + 0xDE44`, 8 × u32 | on-field occupancy | **compacts after a faint** |

### 2e. Correction found while doing this

`profile.fight_trainer_first_pokemon_offset` was **`0xA04`, wrong by
`0x10`**. The component sum is `0x14 + 0x64 + 0x97C = 0x9F4`, every term
confirmed by disassembly. Three other places in the codebase already built
the address from components and were always right; only this standalone
constant disagreed. Its one consumer — `health.py`'s "is this the player's
party?" range test for EXP tracking — therefore excluded the player's first
party slot and failed silently. Corrected, and
`test_side_zero_trainer_zero_slot_zero_matches_the_standalone_constant`
now pins the two together.

---

## 3. The canonical model

`BattlerIdentity` (frozen dataclass) carries: `resolution`, `party`
(`PartyPosition(side, trainer, slot)`), `battler_slot`, `epoch`,
`fight_out`, `fight_pokemon`, `pokemon`, `personality`, `species`,
`nickname`, `level`, `switch_pending_entry`.

### The stable key

```python
key = (party, personality)
```

A **composite**, because no single field is universally sufficient:

- the personality value is unique per Pokémon but is unreadable for a
  send-out event that has supplied only a name;
- the party position is always readable but repeats across trainers.

Together they are unique. Either one alone is enough to *reject* a wrong
match, which is the property the tracker actually relies on.

The key is deliberately **not** species, not nickname, not battler slot, not
party order.

### Resolution states

- `RESOLVED` — every field came from an authoritative read.
- `PARTIAL` — true but incomplete (e.g. a `FightPokemon*` outside every
  party range).
- `AMBIGUOUS` — two or more candidates fit. Callers must stay silent.

---

## 4. `_msgctrlSideName` — hypothesis tested and disproven

Phase 1 expected messages 20327–20332 to supply a per-battler position word
usable for duplicate disambiguation. Reading them out of the shipped
`fight_common` table shows they are not:

| ID | Text | ID | Text |
|---|---|---|---|
| 20327 | `Foe's party` | 20330 | `Ally's party is` |
| 20328 | `Ally's party` | 20331 | `Foe's party` |
| 20329 | `Foe's party is` | 20332 | `Ally's party` |

Three grammatical variants (the Japanese particles *ha* / *wo* / *no*) of a
**whole-side** qualifier, chosen by `_msgctrlSideName(FightOutPokemon*,
particle)` via `fightTargetIsHostSide`. They are used by side-wide messages
such as `[0x1F] covered by a veil!` (20071), not to name an individual.

**The game has no built-in way to tell two identical species apart**, because
a sighted player simply looks at the screen. So:

- the **side word** (`the foe's` / `your`) mirrors the game's own "Foe's
  party" / "Ally's party" wording and is reused;
- the **tie-breaking ordinal** is accessibility-owned connective language.
  That is the correct category for it: there is no game text being copied,
  and the audit's "do not invent a label unless no authoritative distinction
  exists" bar is met because the absence has now been established rather
  than assumed.

### Label policy (`IdentityLabeller`)

Escalates only as far as needed:

1. **bare nickname** when no peer on the field answers to it — the common
   case, and no more verbose than today;
2. **side + nickname** (`the foe's Oddish`) when the clash is across sides;
3. **side + ordinal + nickname** (`the foe's second Gardevoir`) when the
   clash is within one side.

The ordinal is **first-appearance order within a trainer**, assigned once
when a Pokémon first reaches the field and never revised. Party slot would
be invisible to the player; active-array index reorders when the array
compacts after a faint. Appearance order does neither, which satisfies "do
not invent labels that can silently change when slots reorder".

When a clash exists and the identity did **not** resolve, `label()` returns
`None`. The caller speaks the game's own name (never wrong, merely
incomplete) and logs `SEND OUT AMBIGUOUS`. It never falls back to the
species name, because that is precisely the case where two Pokémon share it.

---

## 5. Send-out / replacement lifecycle

```
trainer party record        FightTrainer party array (persistent)
  -> selected replacement   FightOutPokemon+0x862 incoming entry id
  -> new live record        active array slot's FightOutPokemon*
  -> battlefield position   active-array index (unstable; epoch-tagged)
  -> name globals           _MY_MONS* / _ENEMY_MONS*, written by
                            _fightActionFlowKaisiNyuujouPokemonSubAppearMsg
  -> displayed message      20312 / 20313 / 20304 / 20305
  -> settled HP baseline    HealthTracker, re-baselined silently
```

`BattlefieldSlotTracker` implements the required behaviour:

1. **Detect** — each poll compares every occupied slot's
   `(fight_pokemon, personality)` against the published occupant.
2. **Invalidate immediately** — on the *first sight* of a change the settled
   entry is **removed** and the slot's epoch is incremented. Nothing is
   published during the transition, so no consumer can read the outgoing
   Pokémon as current for even one extra sample. This is the specific fix
   for "a replacement announcement reads the outgoing Pokémon's health".
3. **Wait for agreement** — the incoming occupant is published only after
   `identity_stable_samples` (2, matching `health_stable_samples`)
   consecutive identical reads. Mid-switch the array briefly exposes a
   wrapper with no Pokémon attached; announcing from that is the "wrong
   Pokémon" symptom.
4. **Announce from the event** — the send-out subject comes from the
   message's own globals, not from the array.
5. **Re-baseline silently** — `HealthTracker` already emits no event when it
   first sees an identity, and drops baselines when a slot's identity
   changes. Pinned by
   `NoFalseHealthDuringReplacementTests`.
6. **Later events follow the new battler** — `is_current(identity)` is false
   for any identity whose epoch or occupancy no longer matches its slot.

The narrator advances the tracker at the **top** of `poll_once`, before any
message is interpreted, so a message opening in the same tick as a
replacement already sees the new generation.

---

## 6. Baton Pass

Baton Pass is not a distinct sequence step. The `WS_*` step table contains
no Baton-Pass entry; the switch family is
`WS_POKE_RESHUFFLE` / `WS_RESHUFFLE_CHECK` / `WS_POKE_RESHUFFLE_WAIT` /
`WS_POKE_RESHUFFLE_END` / `WS_RESHUFFLE_NICKNAME`, driven by
`fightFloor_SetIrekaePokemonPtr` and `fightOutPokemon_SetIrekaeTargetEntryId`.

What transfers and what does not follows from where the state lives:

| State | Where it lives | Transfers on Baton Pass |
|---|---|---|
| Stat stages | `FightOutPokemon + 0x7B0` | **yes** — the wrapper is retained |
| Volatile/substitute/effects | `FightOutPokemon` | yes, same reason |
| Live record pointer | active array slot | unchanged (same wrapper) |
| Party Pokémon | `FightOutPokemon + 0x04` → `FightPokemon*` | **changes** |
| Persistent identity | `FightPokemon` + PID | changes |
| Message-subject globals | `_ATTACK_MONS` etc. | repointed per action |
| Active-array ordering | index | unchanged |

So the shape of a Baton Pass, from the identity model's point of view, is:
**the wrapper address stays the same while the `FightPokemon*` behind it
changes.** That is exactly why the tracker keys occupancy on
`(fight_pokemon, personality)` and not on the wrapper — keying on the
wrapper would merge the two Pokémon into one identity and is the mechanism
behind "Baton Pass corrupts ordering for later send-outs".

The reported ordering corruption itself had a second, larger cause: the old
send-out path read `trainer_party_names(side, n)`, i.e. party order. Baton
Pass makes party order and field order diverge permanently, which is why the
symptom showed up there first.

Regression: `test_baton_pass_keeps_the_wrapper_and_swaps_the_pokemon`,
`test_baton_pass_then_an_ordinary_switch_keeps_ordering_correct`,
`test_baton_pass_then_faint_and_replacement`.

**Not yet live-observed.** The wrapper-retention model is derived from where
the stat-stage array physically lives plus the absence of any distinct
sequence step, not from watching a real Baton Pass. It is marked *awaiting
live trigger*. Note that the tracker is correct either way: if a real Baton
Pass turns out to allocate a fresh wrapper, that is just an ordinary
replacement, which is already covered.

---

## 7. Level-up recipient

`WS_GET_EXP` (`fightSeqBasis.s`), per recipient, in order:

```
fightPokemonToMenuLvupStatus(recipient, &old_menu_lvup_status)   snapshot old stats
get_exp_fight_pokemon_ptr = recipient                            <- publishes recipient
figthPokemonGetExp / fightPokemonGetLevelToExp
fightPokemonGrowBasisStatus(recipient, ...)                      applies the level-up
fightMsgctrlSetValue(0x0D, fightPokemonGetNicknamePtr(recipient))
... opens 20003 / 20006 ...
get_exp_fight_pokemon_ptr = 0                                    <- cleared
... loop to the next party member
```

So the pointer is non-null for exactly the span in which that recipient's
messages are displayed, and the level read while it is set is post-growth,
i.e. the new one. Two independent routes agree on who the recipient is (the
pointer, and opcode 0x0D's nickname), which is the cross-check.

`resolve_level_up_recipient()` returns the canonical identity. It resolves
even for a Pokémon that is not on the field (Exp. Share, a participant that
fainted), and carries the battlefield slot and epoch when it *is* on the
field so HP-related readers can line the two up.

`level_sample()` **raises** rather than falling back to `_ATTACK_MONS`. A
silent fallback to a source known to be wrong would reintroduce the bug with
no way to notice.

Phase 4 will add stat gains from `old_menu_lvup_status` (`0x804B0A20`) — not
implemented here, per scope.

---

## 8. Consumers audited

| Consumer | Identity source before | Now | Migrated? |
|---|---|---|---|
| Send-outs (20312/20313/20304/20305) | party array order | message opcodes + epoch-tracked records | **yes** |
| Level-up recipient | `_ATTACK_MONS` | `get_exp_fight_pokemon_ptr` | **yes** |
| Healing ownership prefix | positional slot tuple | derived from party address | **yes** |
| HP loss / gain / settle | `(slot, fight_out, fight_pokemon, pokemon)` | unchanged | no — already correct |
| Fainting | `FaintCoordinator` unique-zero rule | unchanged | no — already refuses ambiguity |
| Status / conditions | per-identity, keyed on the same tuple | unchanged | no |
| Stat stages | per-identity | unchanged | no |
| Move use | `_ATTACK_MONS` (correct for this event) | unchanged | no |
| Move panel | window allocation | unchanged | no |
| Target selection | status-window identities | unchanged | no |
| Experience (20003) | `_EV_STR_BUF0` (correct opcode) | unchanged | no |
| Shadow messages | fixed sentences | unchanged | Phase 3 |
| Capture flow | `_TSUIKA_MONS` | unchanged | Phase 3 (needs 0x16) |
| Ctrl+Shift+H summary | `summary_slot_order` speaking order | unchanged | no — ordering only, not side attribution |

Deliberately not rewritten: anything already resolving its subject from the
correct authoritative source. Phase 2's rule was to fix the identity model
once, not to churn working sentence generation.

---

## 9. Ambiguity behaviour

| Situation | Behaviour |
|---|---|
| Two live battlers share a nickname on one side | send-out name still spoken (it is the game's); live-record attribution withheld; `SEND OUT AMBIGUOUS` logged with the name, side, and peer count |
| Clash with no appearance order recorded | `label()` returns `None`; caller speaks the bare name |
| A send-out global is unwritten | sample **rejected**, message stays silent — never "Go! !" |
| Level-up recipient pointer null | `MemoryError`, logged as `SAMPLE_REJECTED`; no fallback to the attacker |
| Wrapper present but detached (`FightPokemon* == 0`) | `AMBIGUOUS`; never inherits the previous occupant |
| `FightPokemon*` outside every party range | `PARTIAL`; ownership falls back to the positional tuple rather than raising |
| Slot mid-replacement | nothing published for that slot at all |

Never: fall back to species name when two matching active Pokémon exist;
associate HP from one epoch with identity from another; announce a
subjectless event.

---

## 10. Files changed

| File | Change |
|---|---|
| `battle_narrator/battle_identity.py` | **new** — model, resolver, slot tracker, labeller |
| `battle_narrator/profile.py` | send-out/trainer globals, party geometry, PID/species offsets, switch-state offsets, `exp_recipient_pointer_address`, `identity_stable_samples`; **corrected** `fight_trainer_first_pokemon_offset` |
| `battle_narrator/resolver.py` | `send_out_event()`, `level_up_recipient()`; `level_sample()` rewritten; `LevelSample.actor` → `.recipient`; 20304 removed from `CATCH_TARGET_TEMPLATES`; send-out ID sets |
| `battle_narrator/narrator.py` | four send-out messages collapsed into one opcode-driven mode; level-up names the recipient; slot tracker driven from `poll_once`; disambiguation helpers |
| `battle_narrator/health.py` | `BattlerSample.owner`; `owner_for_battler()`; `recovery_sentence` derives ownership |
| `battle_narrator/phase1b_app.py` | wires resolver, tracker, labeller into production |
| `tests/test_battle_identity.py` | **new**, 50 tests |
| `tests/test_battle_narrator.py` | send-out and level-up tests rewritten to the new contract; duplicate-species coverage |
| `tests/test_resolver.py` | level-up recipient tests on real party geometry |

**Full suite: 942 passing** (baseline 889).

---

## 11. Awaiting live validation

| Case | Why it cannot be closed statically |
|---|---|
| Baton Pass wrapper retention | derived from where stat stages live; never observed live |
| Duplicate opposing species | needs a real battle with two of one species |
| Two trainers on one side | the trainer-index distinction is derived, not seen |
| Send-out globals populated at message time | the opcode → global mapping is certain; the exact frame they are written on is not |
| `_TRAINER_TYPE` / `_TRAINER_NAME` content | never read live before; expected to give the full "Cipher Peon Greesix" |
| Corrected `0x9F4` party base | the correction follows from disassembly; a live read of the player's slot-0 nickname would confirm it directly |
| Level-up recipient in doubles | the reported symptom; needs a double battle where both party members level |
