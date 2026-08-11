# BATTLE_ACCESSIBILITY_AUDIT.md

**Status:** Phase 1 deliverable, created 2026-08-06. Companion to
[BATTLE_SYSTEM_ARCHITECTURE.md](BATTLE_SYSTEM_ARCHITECTURE.md).

Baseline before any change this pass: **889 automated tests, 0 failures**
(`unittest` discovery rooted at `Companion/tests` with `Companion` on
`sys.path`, run under `Companion/.venv/Scripts/python.exe`).

**After Phase 2: 942 passing.** See
[BATTLE_IDENTITY_MODEL.md](BATTLE_IDENTITY_MODEL.md).
**After Phase 3: 981 passing.** See
[BATTLE_MESSAGE_PIPELINE.md](BATTLE_MESSAGE_PIPELINE.md).
**After the opcode-resolution pass: 1,007 passing.** `_CLIENT_MONS` (0x11),
`_CLIENTNOWORK` (0x1E), the trainer-name distinction and the null opcodes
0x0B/0x0C are all resolved from their writers — see that document's §14.
No behaviour change was needed; the registry's types were already right, but
one profile field name (`trainer_enemy_class_name`) was actively wrong and is
renamed.

> **Phase 3 retired every table in §1a.** The per-ID inventory of what
> replaced each one is in the message-pipeline document's §10. Running the
> new double-encoding detector over the tree also found **six further
> corrupted source lines** beyond the Shadow sentence — including a
> quadruple-encoded `--help` string and a captured live dialogue fixture
> whose `POKéMON` had rotted to `POKÃ©MON`, i.e. a test fixture that had
> silently stopped matching what the game produces. All repaired, with two
> tests keeping them repaired.

---

## 1. Hardcoding inventory

Every fixed string the battle path can speak, classified as the task
requires. "Improper copied game content" means a sentence that exists in the
game's own string table and is being retyped in Python instead of resolved.

### 1a. Improper copied game content — must be removed

| Location | Count | Content | Authoritative replacement |
|---|---|---|---|
| `resolver.FIXED_SENTENCES` | 11 | `"Oh! A Shadow PokÃ©mon!"`, `"It's not a Shadow PokÃ©mon!"`, `"Bursts of light showered from the shadowy aura!"`, `"There are no Master Balls left."`, `"Aww! It appeared to be caught!"` ×2, `"Aargh! Almost had it!"` ×3, `"No! It broke free of the Ball!"`, `"It dodged the thrown Ball! ..."` | These IDs carry **no substitution opcodes**. Read the string table entry directly. |
| `resolver.CATCH_TARGET_TEMPLATES` | 13 | `"A wild {name} appeared!"`, `"Gotcha! {name} was caught!"` ×4, `"The opposing trainer sent out {name}!"`, … | Render the real template with opcode 0x16 → `_ENEMY_MONS`. |
| `resolver.ACTOR_SENTENCE_TEMPLATES` | 8 | `"{name}'s attack missed!"`, `"{name} fainted!"` ×2, `"{name} is hurt by poison!"`, `"{name} flinched!"`, `"{name} became confused!"`, `"{name} is paralyzed! It can't move!"`, `"{name}'s emotions rose to a fever pitch! ..."` | Opcodes 0x0F/0x10/0x12 → `_ATTACK_MONS`/`_DEFENCE_MONS`/`_TSUIKA_MONS`. |
| `narrator.compose` move-learning dict | 7 | `"{name} learned {move}!"`, `"Stop learning {move}?"`, … | Opcodes 0x0D/0x0E, source selected by `ServerWork[7]`. |
| `narrator.compose` inline sentences | 6 | `"Go! {name}!"`, `"Go! {a} and {b}!"`, `"{subject} sent out {name}!"`, `"{name} gained {n} experience points."`, `"{name} grew to level {n}!"`, `"Hit {n} times!"` | Opcodes 0x14/0x15/0x16/0x17/0x0D/0x0E/0x2F. |
| `resolver.VICTORY_SENTENCE` | 1 | `"You won the battle!"` | 20258/20300 real templates + 0x22/0x23. |
| `resolver.PARTIAL_TRAINER_SENTENCES` | 1 | `"A trainer wants to battle!"` | 20301 real template + 0x22/0x23. |
| `resolver.loss_sentence` / `poison_sentence` / `actor_sentence` | 4 | `"{name} is out of usable PokÃ©mon!"` etc. | 20024/20025/20032 real templates. |
| `narrator.compose` `structural_text` | — | Replaces `[Speaker]` with the opponent trainer's name and strips every other `[...]` marker with a regex | Opcode 0x59 → `_Npc` → message ID. The current substitution is a **guess** that the speaker is always the opponent trainer. |
| **Total** | **≈51 sentences** | | |

Two of these literals (`"Oh! A Shadow PokÃ©mon!"`,
`"It's not a Shadow PokÃ©mon!"`) additionally contain mojibake — UTF-8 bytes
for `é` stored as two cp1252 characters. The log proves both forms have been
spoken: 28 occurrences of `PokÃ©mon` and 1 of `Pokémon`, i.e. the literal has
been corrupted by a codec round-trip at least once during editing. **This is
the concrete demonstration of why retyped game text cannot be trusted**: the
string drifted from the game's without anything failing.

### 1b. Proven-immutable game UI labels — none

No battle label in the codebase currently meets this bar.

### 1c. Unverified label tuples — must be derived or justified

| Location | Value | Problem |
|---|---|---|
| `profile.command_labels` | `("Fight", "Item", "Pokemon", "Call")` | Index→word mapping never independently verified; this is the exact pattern already caught and corrected for `shop_menu_labels` on 2026-07-30. |
| `menus.yes_no_focus` | `("Yes", "No")` | Cursor 0/1 assumed. `choice_menu.ChoiceMenuReader` already reads real option message IDs generically from the same class of widget. |
| `profile.new_game_confirmation_labels` | two full sentences | Out of battle scope; noted for completeness. |

### 1d. Accessibility-owned connective language — legitimate, keep

| Location | Examples | Why it is fine |
|---|---|---|
| `health.loss_sentence` / `recovery_sentence` | `"X lost 22 percent. 78 percent remaining."` | The game shows an animated HP bar, not a sentence. There is no game text to copy. |
| `health` stat-stage wording | `"rose sharply"`, `"harshly fell"` | Borderline — messages 20239/20241/20380/20240/20242 *are* the game's own words for magnitude and direction, and `validate_stat` already resolves them. This duplicate wording should be retired in favour of the message path. |
| `health` condition names | `{5: "paralyzed", 6: "burned", 7: "frozen"}` | Borderline — a fallback for when the message path fails. Should become a fallback only, not a parallel source. |
| `hotkeys` summaries | `"No Shadow Pokemon in your party."` | Accessibility-only feature with no game-text equivalent. |
| `resolver.MoveDetails.description` | `"Normal-type, power 60, 100 percent accuracy"` | Assembled from verified numeric fields; the prose effect text comes from the game's own description table. |

### 1e. Structural gate that behaves like hardcoding

`narrator.VERIFIED_OPCODES` is a per-message-ID allow-list of opcode sets
(~60 entries). Any message whose opcode set is not enumerated is suppressed
outright. This is not a string, but it has the same failure mode: coverage is
bounded by what somebody typed. The log shows **118 distinct message IDs**
suppressed by it. A generic renderer that can resolve every opcode makes the
allow-list unnecessary; the remaining safety check becomes "did every opcode
in this string resolve?", which is a property of the data, not of a list.

---

## 2. Issues grouped by shared root cause

Five root causes account for all 21 reported battle issues.

### RC-1 — The battle half of `msgctrlcode` was never implemented — **FIXED (Phase 3)**
*Issues 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 21*

`message_render.MessageRenderer` implements the general control opcodes and
explicitly declines 0x0D–0x2A. `narrator.py` compensates with per-ID English.
Every missing message in the report is a message whose only unresolved
opcodes are in that declined range.
**Fixed once**, in `battle_narrator/battle_opcodes.py` (the registry) and a
rewritten `message_render.py`. All 47 opcodes any shipped `fight_common`
message uses are covered, and `narrator.py` now has one mode instead of
seventeen. Issue 5's mojibake was a source-file literal that had drifted
from the game's; issue 5's *missing leading letter* turned out to be a
separate fault — a self-interrupting speech race, found in the log with
timestamps and fixed in `SpeechCoordinator`.

### RC-2 — Send-out and trainer identity read the wrong source — **FIXED (Phase 2)**
*Issues 12, 13, 14; issue 9 remains, see below*

`trainer_party_names(side, n)` returns the first *n* named slots of the
persistent party array. Send-out messages use text-pointer globals
`_MY_MONS`/`_MY_MONS2`/`_ENEMY_MONS`/`_ENEMY_MONS2` that name exactly the
Pokémon entering the field. `_TSUIKA_MONS` is sampled where `_ENEMY_MONS` is
required, producing 2,271 logged `invalid address 0x00000000` rejections
across 20470/20473/20448/20304/20312.
**Fixed once**, in `battle_narrator/battle_identity.py`. The send-out subject
now comes from the message's own opcode globals, read in the message
template's own opcode order. Duplicate species are disambiguated by the
game's side word plus a first-appearance ordinal — `_msgctrlSideName`'s
messages turned out to be whole-side qualifiers, not per-battler labels, so
the Phase 1 plan for them was dropped. Issue 9 (`A wild X appeared`) shares
the root cause but is still routed through the old `catch_target` mode; it
closes in Phase 3 with the rest of the message families.

### RC-3 — Level-up recipient and stat gains have an unused authoritative owner
*Issue 15 **FIXED (Phase 2)**; issue 16 remains for Phase 4*

`level_sample()` reads `_ATTACK_MONS` — the Pokémon that attacked, not the
one that levelled. In a double battle where both party members gain EXP, that
is exactly the reported "switched" behaviour. The real recipient is
`get_exp_fight_pokemon_ptr` (`0x804EB964`), and the displayed stat gains are
`fightPokemonToMenuLvupStatus(recipient) - old_menu_lvup_status`
(`0x804B0A20`).
**Phase 2** switched `level_sample()` to `get_exp_fight_pokemon_ptr`, which
`WS_GET_EXP` sets and clears once per recipient around exactly the messages
that name it. It now raises rather than falling back to `_ATTACK_MONS`, so
the bug cannot silently return. Stat gains from `old_menu_lvup_status` are
Phase 4.

### RC-4 — No generic Yes/No or prompt reader is wired into battle
*Issues 17, 18, 19*

`ChoiceMenuReader` already does this correctly and generically for the
Mt. Battle prompt. `menus.yes_no_focus` does it with a hardcoded pair. The
move-learn prompt (`OboeWazaNo` = `0x804EB93C`) and the battle item
confirmation both need it.
**Fix once:** one verified reusable choice/confirmation reader, then point
move-learning and battle items at it.

### RC-5 — The in-battle bag is a different module from the one modelled
*Issues 19, 20*

`bag_menu.py` reads the hero's save-data item arrays (the overworld
`menuPocket2` model). The battle bag is `menuPocketBattleDisk`, with its own
filtered/paged list (`getItemIDFromMenuPos`, `getNbItemSlot`), its own name
lookup (`getItemNameMsg`), and a used-mark (`diskUsedMarkDisplay`). Reading
the save arrays cannot show the disk's filtering, ordering, or post-use
refresh.
**Fix once:** a battle-disk model reusing `item_database.py`'s existing
authoritative name/description chain.

---

## 3. Answers to the completion test

> *"If the user had never told me the visible sentence, would the
> implementation still derive the correct Pokémon, move, item, amount, state,
> and localized text?"*

| Area | Today | After the planned repair |
|---|---|---|
| Status/effect messages | **No** — English is retyped per ID | Yes — string table + opcode sources |
| Send-outs | **No** — party order guessed | Yes — `_MY_MONS`/`_ENEMY_MONS` |
| Trainer class/name | **No** — omitted or generic | Yes — `_TRAINER_TYPE`/`_TRAINER_NAME` |
| Level-up recipient | **No** — attacker assumed | Yes — `get_exp_fight_pokemon_ptr` |
| Stat gains | n/a — absent | Yes — `old_menu_lvup_status` diff |
| Move learning | **No** — 7 retyped sentences | Yes — opcodes 0x0D/0x0E + `OboeWazaNo` |
| Yes/No | **No** — pair hardcoded | Yes — option message IDs from the widget |
| Battle items | n/a — absent | Yes — `getItemNameMsg` chain |
| Shadow/purification | **No** — 11 retyped literals, 2 with mojibake | Yes — these IDs have no opcodes at all |

---

## 4. What must not regress

Confirmed working from the log and preserved by the plan:

- HP loss / recovery / percentage narration (`health.py`) — 1,245 move
  messages and thousands of settled HP events.
- Faint coordination (`FaintCoordinator`).
- Move use (20333, n=1245), effectiveness (20255/20256, n=480),
  critical hits (20250, n=64).
- Stat-change messages 20243/20246 via `validate_stat`.
- Battle command menu and move panel focus.
- VS-mode C-stick move/target panels.
- Overworld dialogue, entity navigation, shops, PC, purify chamber,
  footsteps, beacons, teleport — **untouched by this work**.

---

## 5. Evidence sources used

- `Companion/logs/battle_narrator_phase1b.log` — 3,673,576 lines; full
  inventory of `OPEN` / `SUPPRESSED` / `SPOKEN` / `SAMPLE_REJECTED` by
  message ID, with the game's own templates and opcode lists.
- `xd-decomp/config/GXXE01/symbols.txt` — 21,539 symbols.
- `xd-decomp/orig/GXXE01/sys/main.dol` — `msgctrlcode` table.
- `xd-decomp/build/GXXE01/asm/` — disassembly of `msgctrl.s`,
  `fightMenu.s`, `fightSeqSpAction.s`, `fightSeqBasis.s`, `menuUseItem.s`,
  `fightOutPokemon` accessors.
- Existing project documentation: `IMPLEMENTATION_ATTRIBUTION.md`
  (2026-07-28 / 07-30 battle entries), `ACCESSIBILITY_COVERAGE_MATRIX.md`,
  `PLAYTHROUGH_BARRIER_LOG.md`, `CLAUDE_HANDOFF_2026-07-25.md`.

No live memory was read during Phase 1, and no production code was changed.
