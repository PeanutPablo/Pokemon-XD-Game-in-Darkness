# XG_COMPATIBILITY.md

First real answer to the question this project has carried since it
started: **does any of what we built actually work on Pokémon XG?**

Established 2026-08-11, entirely from static analysis of the patched
image, apart from §8, which records the first live finding (2026-08-12);
see [§9](#9-what-is-still-unverified) for what remains open.

**Verdict: yes, with three defects found and fixed.** XG keeps the engine
layout the whole project depends on. All three defects were real, all
three would have hit a player in their first minutes of use, and none was
detectable without an actual XG image to test against.

---

## Data sourcing rules (normative)

**The accessibility layer must work with vanilla XD and XG from one code
path.** There is no game-identity switch and there must not be one: the
two discs share a label (`GXXE01` revision 0), an internal name, a
section layout, a `.bss`, and all 8 engine signatures. Nothing reliable
distinguishes them from outside, so every per-build fact is *derived* at
load or read live, never selected by asking which game this is.

The two data sets diverge in different ways, and the difference decides
what the code has to do about each.

### MOVES

- **Same ID space as vanilla XD.** 373 resolvable IDs on both, highest
  374, zero IDs present in one build and absent from the other.
- **XG replaces the contents of existing move records rather than
  extending the ID space.** 183 of 373 slots hold a different move;
  190 are unchanged. `profile.maximum_move_id = 374` therefore remains
  correct for both.
- **Names and descriptions must always come from XG's authoritative game
  data** — the player's own extracted `common.rel` and `dol_strings.json`
  — never from a table in this repository.
- **No XG-specific move-name mapping is permitted.** If a move reads
  wrong, the fault is in the record layout or the extraction source, and
  that is what gets fixed.

### ABILITIES

- **XG expands the ability count and changes the underlying table record
  layout.** 106 abilities against vanilla's 78, achieved by shrinking the
  record from 12 bytes to 8.
- **The XG-specific stride/layout must be derived from engine code**, not
  configured, detected by content sniffing, or branched on game identity.
  See `ability_layout.py`.
- **Ability names and descriptions still come from authoritative game data
  once the correct layout is known.** The layout derivation exists only to
  find the records; it never supplies text.

### The general rule these two are instances of

Where a hack can change the *contents* of a structure, read the contents
live or from the player's own extraction. Where a hack can change the
*shape* of a structure, derive the shape from the engine's own code.
Never encode either in this repository as a constant that happens to be
true of one build — that is the failure mode all three defects below
share.

---

## 1. Producing the image

XG 1.2.1 ships as a UPS patch. It was applied by
`Tools/apply_ups_patch.py`, written for this purpose rather than
downloading a patcher binary — UPS is a small documented format, and
doing it in-project means the three CRC32s the format carries (patch,
input, output) are all checked and reported instead of trusted.

| | CRC32 |
|---|---|
| patch file, self-check | `620EDA1E` (stored == computed) |
| required input | `C0F69D18` |
| produced output | `9B232C01` (matched exactly) |

This settled a question [MILESTONE_SAVE_INDEX.md] could not: **which of
the two same-sized `GXXE01` images on this machine is the real base.**

| image | CRC32 | verdict |
|---|---|---|
| `Pokemon XD - Gale of Darkness (USA).iso` | `C0F69D18` | the base XG is built against |
| `XD-US.iso` | `844840A8` | a different build; would produce a corrupt patch result |

The correct base is the same image `Companion/_dialogue_extraction` was
generated from, so the project's existing reference data and XG share an
ancestor. The base file was copied first and re-hashed afterwards:
unchanged.

Artifacts (outside the repo, per the `.gitignore` rule on disc images):

- `GameImages/Pokemon XG v1.2.1.iso`
- `GameImages/Pokemon XD - Gale of Darkness (USA) BACKUP.iso`

## 2. The compatibility gate passes

`Companion/check_image_compatibility.py` (new) applies the same gate
`check_game_compatibility.py` applies to a running Dolphin, but reads it
out of `main.dol` instead, so it can be answered before the game is ever
launched and can diff two images directly.

**All 8 of `profile.engine_signatures` match at their exact addresses.**
Beyond that, nothing moved at all:

| section | address | size | bytes changed |
|---|---|---|---|
| text0 | `0x80003100` | 9,472 | 0 (0.00%) |
| text1 | `0x800056a0` | 3,033,312 | 5,964 (0.20%) |
| data0–data4 | — | 73,760 | 0 (0.00%) |
| data5 | `0x802fbf00` | 1,197,728 | 68,227 (5.70%) |
| data6 | `0x804e7e20` | 2,464 | 5 (0.20%) |
| data7 | `0x804ebdc0` | 16,064 | 20 (0.12%) |

Every section keeps its address and its size, and `.bss` is identical in
both builds (`0x804205c0`, `0xcf7c4` bytes), as is the entry point
(`0x80003154`). XG is an in-place hack, not a relink.

Of the 104 addresses in `profile.py`, **none** falls inside a changed
region. That result is weaker than it looks and is qualified in §7.

## 3. Defect 1 — one malformed archive entry broke every loader

**Symptom.** On XG, every offline table failed to load: species names,
moves, items, warps, dialogue, all of it. `IndexError: index out of
range` from `decode_lzss`.

**Cause.** XG's `common.fsys` contains one entry,
`DeckData_DarkPokemon_EU.bin`, whose declared uncompressed size is 500
bytes in both the FSYS entry and the LZSS header, from a stream that
encodes exactly 208. 208 is not arbitrary: the decoded bytes begin with a
`DECK` header whose own length field reads 208, so the stream is complete
for the data that exists and only the outer size fields disagree. The
console never notices — it decompresses into a fixed-size allocation and
reads only the length the `DECK` header gives — and a US build never
reads the EU deck at all.

The damage was disproportionate because every loader reaches its own
table through `parse_fsys`, which decodes *every* entry in the archive.
One short stream in a file nothing reads took down the 26 entries around
it, including `common_rel`, which decodes perfectly and is what almost
every loader actually wants.

**Fix.** `_dialogue_extraction_tool.decode_lzss` now stops when either
the output buffer is full or the input runs out, zero-padding the
remainder, which is what the console's fixed-size allocation contains
anyway. A back-reference that would overrun the buffer is also bounded.
Covered by `tests/test_fsys_lzss.py` (7 tests), including the specific
shape of this failure.

**Regression.** Regenerating the vanilla extraction after the change
reproduced **all 189 files byte-for-byte** against the existing tree.

## 4. Defect 2 — XG repacks the abilities table

**Symptom.** Ability narration on the Pokémon summary screen would speak
the wrong ability for every Pokémon: XG's ability 1 read as "Drizzle"
instead of "Aerilate", and every later index as a different wrong answer.
Confidently wrong, which for a blind player is worse than silent.

**Cause.** XG fits 106 abilities into the space vanilla used for 78 by
dropping a four-byte field from every record. Stride 12 → 8, name ID
+4 → +0, description ID +8 → +4.

**Why this could not be solved by detecting the game.** XG is identical
to vanilla in the disc label (`GXXE01` revision 0), the internal name
(`POKeMON XD`), the DOL section layout, `.bss`, and every engine
signature — correctly, since none of those is wrong. There is nothing
outside the table itself to select a layout by.

**Fix.** `battle_narrator/ability_layout.py` (new) derives the layout
from the three engine accessors that *are* the layout, each carrying one
constant in its immediate field:

| address | vanilla | XG | constant |
|---|---|---|---|
| `0x801442B0` | `mulli r4,r3,12` | `mulli r4,r3,8` | record stride |
| `0x80144290` | `lwz r3,4(r3)` | `lwz r3,0(r3)` | name ID offset |
| `0x80144278` | `lwz r3,8(r3)` | `lwz r3,4(r3)` | description ID offset |

These three words are the **only** differences anywhere in the accessor
cluster `0x80144200`–`0x801442D0`, which is what makes them a layout
description rather than a coincidence. Deriving beats sniffing the
table's contents: a heuristic would be guessing about data a hack is free
to make ambiguous, while these instructions are the game stating what it
does. An unrecognised instruction form raises rather than falling back.

**Verification.** Driving the real `LocalAbilityData.resolve` against
each image's own `main.dol`:

- XG derives 8/+0/+4 and resolves **101 of 101** named abilities to
  exactly the names XG's own shipped documentation lists.
- vanilla derives 12/+4/+8 and still resolves ability 50 to
  `RUN AWAY` / `Makes escaping easier.` — the project's existing
  live-verified result, unchanged.

Covered by `tests/test_ability_layout.py` (9 tests), which pins the real
instruction words from both images.

## 5. Defect 3 — a missing description suppressed the ability name

Found while verifying §4. XG's ability 57, Trickster (Drowzee), has no
description — its own documentation prints one as `-`. `resolve()`
required both fields, so the player heard "ability 57" instead of
"Trickster". It now degrades to the name with an empty description, which
is a shape the caller already produces itself.

## 6. What was checked and found compatible

Every offline loader the narrator builds at startup was constructed
against both images. **15 of 15 build on XG**, with identical record
counts:

| loader | XG | vanilla |
|---|---|---|
| warps / doors / elevators / PCs / texts | 280 / 150 / 46 / 26 / 89 | identical |
| world map | 47 | 47 |
| general flag layout | 3 | 3 |
| ability name table (`common.rel`) | 1,957 | 1,931 |
| move 1 resolves to | `Bullet Punch` | `POUND` |

Other assumptions checked directly against XG:

- **Move IDs.** `profile.maximum_move_id = 374`; XG's highest move index
  is exactly 374. Unchanged.
- **Species stats stride (`0x124`).** Holds. XG's Pikachu reads abilities
  9 and 31 — Static and Lightningrod — and XG's own documentation lists
  Pikachu under both. XG's Eevee reads 81, Adaptability, likewise
  matching.
- **`msgctrlcode` dispatch table** (`0x80404710`, `0x378` bytes):
  byte-identical.
- **`common.rel`**: identical size (704,448) with the species-stats and
  string-table pointers at identical offsets.
- **Collision rooms: 169 on XG vs 177 on vanilla, and this is correct.**
  The 8 absent rooms (`M2_cave_1F_1`, `_1F_2`, `_2F_1`, `_2F_2`,
  `_3F_1`, `_3F_2`, `Script_test`, `tv_test`) are still named in XG's
  file table, but XG replaced each archive with a 96-byte empty FSYS stub
  containing zero entries. The extraction is skipping genuinely empty
  maps, not failing to parse populated ones.

## 7. Move fields: where each announced value comes from

A targeted audit of every move field the narrator actually speaks, run
because §6 established that XG rewrote 183 move records. The question was
not "are XG's moves different" — they are — but "does every field we
announce come from XG's own data, or does one of them quietly inherit a
vanilla assumption?"

One did. See defect 4 below.

| field | source | build-safe? |
|---|---|---|
| move ID | live: `pokemon_waza + pokemon_move_id_offset` | yes, live |
| current PP | live, **twice**: the menu record and `pokemon_waza`, and `menus.py` refuses to announce if they disagree | yes, live |
| max PP (battle) | live: menu record `move_record_max_pp_offset` | yes, live |
| max PP (party screen) | derived: base PP from the player's extraction + live PP Ups | yes, XG data |
| name | live `gschar` off the menu record, cross-checked against the player's extraction; refuses on mismatch | yes, both |
| base PP | player's extraction (`common.rel`) | yes, XG data |
| base power | player's extraction (`common.rel` +0x18) | yes, XG data |
| accuracy | player's extraction (`common.rel` +0x04) | yes, XG data |
| effect description | player's extraction (`dol_strings.json`) | yes, XG data |
| **type name** | **was a hardcoded tuple in this repo** | **no — fixed below** |

**Verified against XG's own shipped move documentation**, which lists
name, type, base power, accuracy and PP for all 375 indices:

- **name, base PP, base power, accuracy: 0 disagreements** across every
  documented move. All four already came from XG's own data.
- Sampled explicitly, including replaced moves and Shadow moves: 1
  (`Bullet Punch`, Steel, 30 PP, 40 power, 100%), 3 (`Focus Blast`), 15
  (`Poison Jab`), 22 (`Drain Punch`), 24 (`First Impression`), and the
  Shadow moves 365 (`Shadow Chill`), 368 (`Shadow Bully`, 5 PP, power 1,
  95%) and 373 (`Shadow Hunter`). Every field matched.
- Shadow moves carry **type ID 0 (Normal)** in *both* builds; their Shadow
  typing is applied at runtime. The old hardcoded `TYPE_NAMES[18] =
  "Shadow"` was therefore never reachable from move data at all.

### Defect 4 — the move-type name was the one vanilla assumption left

`LocalMoveData.TYPE_NAMES` was a tuple in this repository, and its index 9
read `"Unknown"`. Vanilla leaves slot 9 unused (`?`); **XG puts Fairy
there.** 15 XG moves — `Play Rough`, `Disarming Voice`, `Baby Doll Eyes`,
`Sing`, `Lovely Kiss` among them — would have been announced as
"Unknown-type".

Fixed by reading the game's own type table: `zokuseiData`, REL pointer
130 in `common.rel`, 0x30-byte records with a u32 name message ID at
+0x08, 18 entries in both builds. The shape was not invented — it is what
`purify_chamber.py` already reads live — and the pointer index was found
offline by searching every REL pointer for the one base whose 18
consecutive records all resolve to short, control-free strings. Exactly
one does, in both images.

The game stores battle-UI labels, which are truncated to fit the widget
(`FIGHT`, `ELECTR`, `PSYCHC`). Those are display truncations rather than
names, so a small expansion map turns them into words. It is keyed **on
the game's own text, not on a type index**, which is what keeps it from
becoming the same bug again: a build whose slot 9 says `Fairy` falls
straight through to "Fairy".

Result, one code path over both builds:

| slot | vanilla | XG |
|---|---|---|
| 9 | `?` | `Fairy` |
| all other 17 | unchanged from what it always spoke | identical to vanilla |

Vanilla's spoken names are unchanged in 17 of 18 entries; the only
difference is slot 9, which now reports the game's actual `?` instead of
the invented "Unknown", and which no real vanilla move reaches. All 18 XG
type IDs now agree with XG's documentation, with no ambiguous IDs.

Covered by `tests/test_move_type_names.py` (10 tests), including a guard
that fails if any hardcoded list of type names is reintroduced.

**Not re-verified across all 373 moves beyond the field comparison above,
deliberately** — the audit's purpose was to prove sourcing, not to build
an offline XG move database.

## 8. First live evidence — the extraction must match the disc you play

Reported live, 2026-08-12: **Metagross's moves were not being read in the
move menu, except Substitute.** This is the project's first live finding
against XG, and it was not a code defect.

The log names the cause outright, once per poll:

```
MENU SAMPLE REJECTED: move-name disagreement live='Zen Headbutt' local='MEGA PUNCH'
```

`menus.py` reads the move name twice — live from the menu record, and
from the player's extraction via the move ID — and refuses to announce
anything when the two disagree. That check did exactly its job. The
companion was attached to XG, but `Companion/_dialogue_extraction` had
been generated from the **vanilla** disc, so move ID 5 was `Zen Headbutt`
in memory and `MEGA PUNCH` on disk.

Why only Substitute survived: XG replaces 183 of 373 move records and
leaves 190 alone. Substitute (ID 164) is one of the untouched slots, so
its two readings agreed and it announced normally. Metagross's other
moves sit in slots XG rewrote — `Zen Headbutt` is ID 5, vanilla's Mega
Punch; `Bullet Punch` is ID 1, vanilla's Pound — so each was dropped.
**Only 192 of 373 move IDs agree between the two extractions**, so this
would have affected most of the game, not one Pokémon.

Battle narration was unaffected throughout, and the same log shows why:
`Metagross used Zen Headbutt!` was spoken correctly, because that
sentence is rendered from live GSmsg text and never consults the
extraction.

**Fix: regenerate the extraction from the disc actually being played.**

```
Companion\.venv\Scripts\python.exe bootstrap_game_data.py --disc "<your XG image>"
```

Verified after regenerating: move 1 `Bullet Punch` (Steel, power 40,
100%), move 5 `Zen Headbutt` (Psychic, 80, 90%), 118 `Hammer Arm`
(Fighting, 100, 90%), 309 `Meteor Mash` (Steel, 90, 90%), 164
`Substitute`, and the type table carrying `Fairy` at slot 9.

**It then happened in the opposite direction the next day.** 2026-08-13,
playing vanilla against the XG extraction regenerated above:

```
move-name disagreement live='MINIMIZE'   local='Payback'
move-name disagreement live='SOFTBOILED' local='Psychic Fangs'
```

Blissey's moves silent except Fury Cutter — another of the 192 shared
IDs. The symptom is symmetric because the cause is: the extraction
describes one build and the running game is the other. Live text in caps
(`SOFTBOILED`) versus title case (`Psychic Fangs`) is the quickest way to
read which direction it is, since XG re-cased the whole text.

**Because this is now twice in two days, the reader says so out loud.** A
disagreement between the live reading and the offline table raises
`menus.GameDataMismatch`, and the move reader speaks once per session:

> "Accessibility game data does not match the game that is running, so
> move names cannot be read. Re-run the game data setup against the disc
> image you are playing."

The refusal to announce is unchanged and must stay — speaking the local
name would mean saying "MEGA PUNCH" for Zen Headbutt. What changed is
only that the silence now explains itself. `GameDataMismatch` subclasses
`MenuReadError`, so every existing handler still treats it as an ordinary
rejected sample; it is raised only where a live reading and the offline
table disagree about the same move ID, which cannot be a transient.
Covered by `tests/test_game_data_mismatch.py`.

**Resolved 2026-08-13: data now lives one tree per disc, and the
companion picks the right one itself.** `bootstrap_game_data.py` writes
into `_dialogue_extraction/<GAMEID>-<fingerprint>/` and stamps it with a
`build_id.json`; at startup `phase1b_app.resolve_data_root` fingerprints
the *running* game and loads the tree that matches. Generating data from
a second disc adds a tree rather than replacing the first, so switching
discs needs nothing at all — no scripts to choose between, no
regeneration.

### How the build is identified, and what was ruled out

Everything easier was tried against the two real images and measured to
fail:

| candidate | why not |
|---|---|
| disc label | identical — both `GXXE01` rev 0, `POKeMON XD` |
| `engine_signatures` | all 8 match both builds; they answer "readable at all", not "which" |
| Dolphin's config | records the game-list folder, not what is booted; would go stale |
| `main.dol` string tables | rewritten in place at load (offsets become pointers), so live matches neither disc |
| hashing a whole code section | live `text1` matches neither disc either — the game patches 4 of its own pages |

What works is sampling code the engine leaves alone. Measured against a
running vanilla disc, exactly **4 of `text1`'s 740 pages** are written
after load, clustered at pages 448–457. Thirty-two evenly spaced 4 KB
samples step over that cluster, match the disc byte for byte, and
separate the builds:

| build | fingerprint |
|---|---|
| vanilla US XD | `8FF9D518` |
| Pokémon XG 1.2.1 | `7BB1937C` |

The sample count is pinned by that measurement, not chosen for taste: 64
samples land on page 451 and match nothing. `tests/test_game_build.py`
asserts the sampling never touches a known runtime-written page.

Selection never guesses. An unrecognised build selects nothing and is
reported, because guessing would restore the exact silent-wrong-data
failure this whole section is about. If Dolphin is not running yet the
fingerprint cannot be taken, and it falls back to the single installed
tree — the behaviour that existed before — with the in-game mismatch
warning still catching a wrong pairing.

Two consequences worth knowing:

- Some tests pin real shipped sentences, which are build-specific. They
  now identify the installed build by one template's raw bytes and skip
  rather than fail — see `tests/pinned_build.py`. On an XG install 97
  tests skip, each individually reported.
- Some data cannot be regenerated from a disc at all: the `rooms/`
  script disassembly (424 files) and `collision_slice/` came from a
  third-party disassembler in earlier sessions, so a fresh tree cannot
  contain them and the features they support would vanish on any build
  but the one they were made from. `_dialogue_extraction/shared/` is
  where such a file goes, and the build's own tree always wins over it.
- **Gateon Port's bridges are shared, and provably safely so.** XG
  recompressed `M6_out.fsys` — 1,467,912 of its 1,485,632 bytes differ —
  but **every decoded entry inside it is byte-identical to vanilla's**,
  collision geometry and room script alike. So `shared/rooms/M6_out.txt`
  is not vanilla data lent to XG; it is the same data. Checked, not
  assumed: the sharing decision was made only after comparing the two
  discs entry by entry.
- Only that one file is shared. The rest of `rooms/` stays in the vanilla
  tree, because its other consumer (room→service derivation) reads room
  scripts XG is free to have rewritten, and nothing has established that
  it did not. `collision_slice/` likewise stays vanilla-only; it feeds
  the development-only collision probe, which simply stays off on XG.
- The old flat `_dialogue_extraction/*` files are left in place. They are
  ignored once a stamped tree matches, and they still hold ~700 files
  from earlier sessions that the bootstrap cannot regenerate, so deleting
  them is the player's call, not an automatic cleanup.

## 9. What is still unverified

**Almost nothing has been confirmed live.** One live session has now
happened (§8), and it confirmed three things: the companion attaches to
XG and runs; battle narration renders XG's own message text correctly
(`Metagross used Zen Headbutt!`); and the live-vs-local move-name
cross-check works. Everything else below is still static analysis plus
offline loader construction.

**The 104-address result in §2 is mostly vacuous, and should not be
quoted without this qualification.** Only **8** of those 104 addresses
sit inside a loaded DOL section and were therefore actually checkable.
The other **96** live in `.bss`/`.sbss`, which is zero-filled at boot and
contains no bytes in the image to compare. Their addresses are strongly
implied to be intact — `.bss` starts and ends identically, no section
moved, and the `@sda21` displacements in the surrounding code are
unchanged — but *implied* is the correct word, and each one is only
really confirmed by a live read.

Of the 8 that were checkable, 7 matched and the 8th was the abilities
table of §4.

**The move-type fix is offline-verified only.** The derived type table
was read from each image's extracted `common.rel`, and the live
`move_record_type_name_offset` pointer that `menus.py` already reads is
still used only for validation, not as the announced text. Confirming
that the live pointer's text agrees with the derived table is a cheap
live check worth doing on the first XG run.

Specifically still open:

0. Re-test the move menu live now that the extraction matches the disc —
   §8's fix is verified offline but has not been heard.
1. Run `check_game_compatibility.py` against live XG.
2. Confirm the `.sbss` msgvar block (`0x804EB1F0`–`0x804EB2CC`) still
   carries what the battle narration expects.
3. Confirm the ability layout derivation returns 8/+0/+4 from live
   memory, not just from the DOL.
4. XG has 122 Shadow Pokémon to vanilla's 83, and adds abilities beyond
   vanilla's range. The narrator reads both from live tables, so this is
   expected to work, but it has not been observed.
5. `data5` has a 96 KB changed region (`0x80377fd3`–`0x8038f879`) that
   has not been identified. It is not referenced by any profile address.

## 10. Files

New:

- `Tools/apply_ups_patch.py` — verifying UPS applier
- `Companion/check_image_compatibility.py` — static compatibility gate and DOL diff
- `Companion/battle_narrator/ability_layout.py` — abilities layout derivation
- `Companion/tests/test_fsys_lzss.py`, `Companion/tests/test_ability_layout.py`,
  `Companion/tests/test_move_type_names.py`

Changed:

- `Companion/_dialogue_extraction_tool.py` — truncated-stream tolerance
- `Companion/battle_narrator/resolver.py` — derived ability layout; derived
  move-type names; ability name survives a missing description
- `Companion/battle_narrator/profile.py` — the three accessor addresses
- `Companion/tests/test_move_details.py` — fixture carries a type table

Full suite after all changes: **1,387 passing**, 0 failures.
