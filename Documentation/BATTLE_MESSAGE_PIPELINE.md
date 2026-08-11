# BATTLE_MESSAGE_PIPELINE.md

**Status:** Phase 3 deliverable, created 2026-08-06. Implemented in
`battle_narrator/battle_opcodes.py`, `message_render.py`, `text_safety.py`
and `narrator.py`; regression coverage in `tests/test_battle_messages.py`.

Companion to [BATTLE_SYSTEM_ARCHITECTURE.md](BATTLE_SYSTEM_ARCHITECTURE.md),
[BATTLE_ACCESSIBILITY_AUDIT.md](BATTLE_ACCESSIBILITY_AUDIT.md) and
[BATTLE_IDENTITY_MODEL.md](BATTLE_IDENTITY_MODEL.md).

---

## 1. The pipeline

```
GSmsg task array          the message ID currently on screen
  -> FightCommonCatalog   ownership test + template for the log
  -> RuntimeMessageCatalog  address of the shipped GSchar bytes
  -> MessageRenderer      decode, substituting through battle_opcodes.REGISTRY
       |-> msgvar globals    0x804EB1F0 - 0x804EB2CC
       |-> battler pointers  FightOutPokemon* -> nickname
       |-> databases         item / move / species id -> name message id
       |-> nested messages   mode-2 opcodes, bounded at depth 4
  -> Rendering            text + every opcode seen + why anything failed
  -> BattleNarrator       safety contract, stability gate, dedup
  -> IdentityLabeller     clarifier appended only on a real name clash
  -> SpeechCoordinator    ordering and interruption
```

There is exactly one renderer. The progress-notification reader (evolution,
purification, item acquisition) and the battle narrator use the same
`MessageRenderer` over the same registry; nothing can render the same event
two different ways.

---

## 2. Battle opcode registry

`battle_opcodes.REGISTRY` transcribes all 111 entries of `msgctrlcode`
(`.data:0x80404710`) from the original `main.dol`, each handler matched to a
symbol. It covers **all 47 opcodes any of the 1,161 `fight_common` messages
actually uses** — sized from the shipped data, not from one playthrough.
`RegistryTests.test_every_opcode_fight_common_uses_is_registered` pins that.

### The battle range, 0x0D–0x2A

| Op | Handler | Source global | Address | Supplies |
|---|---|---|---|---|
| 0x0D | `msgctrlEvStrBuf0` | `_EV_STR_BUF0` | `0x804EB1F0` | GSchar text pointer |
| 0x0E | `msgctrlEvStrBuf1` | `_EV_STR_BUF1` | `0x804EB1F4` | GSchar text pointer |
| 0x0F | `msgctrlAttackMons` | `_ATTACK_MONS` | `0x804EB1FC` | `FightOutPokemon*` → nickname |
| 0x10 | `msgctrlDeffenceMons` | `_DEFENCE_MONS` | `0x804EB200` | `FightOutPokemon*` → nickname |
| 0x11 | `msgctrlClientMos` | `_CLIENT_MONS` | `0x804EB204` | `FightOutPokemon*` → nickname |
| 0x12 | `msgctrlTsuikaMons` | `_TSUIKA_MONS` | `0x804EB208` | `FightOutPokemon*` → nickname |
| 0x13 | `msgctrlMyName` | `_MY_NAME` | `0x804EB20C` | GSchar text pointer |
| 0x14 | `msgctrlMyMons` | `_MY_MONS` | `0x804EB210` | GSchar text pointer |
| 0x15 | `msgctrlMyMons2` | `_MY_MONS2` | `0x804EB214` | GSchar text pointer |
| 0x16 | `msgctrlEnemyMons` | `_ENEMY_MONS` | `0x804EB218` | GSchar text pointer |
| 0x17 | `msgctrlEnemyMons2` | `_ENEMY_MONS2` | `0x804EB21C` | GSchar text pointer |
| 0x18 | `msgctrlEnemyTmons` | `_ENEMY_TMONS` | `0x804EB220` | GSchar text pointer |
| 0x19 | `msgctrlEnemyTmons2` | `_ENEMY_TMONS2` | `0x804EB224` | GSchar text pointer |
| 0x1A–0x1D | `msgctrlSpeabiName*` | `_SPEABI_NAME{A,D,C,T}` | `0x804EB228`–`0x804EB234` | ability-name text |
| 0x1E | `msgctrlClientnowork` | `_CLIENTNOWORK` | `0x804EB238` | `FightOutPokemon*` → nickname |
| 0x1F–0x21 | `msgctrlSideAttackName{ha,wo,no}` | `_SIDE_ATTACK_NAME*` | `0x804EB23C`–`0x804EB244` | side qualifier (§4) |
| 0x22 | `msgctrlTrainerType` | `_TRAINER_TYPE` | `0x804EB248` | trainer class text |
| 0x23 | `msgctrlTrainerName` | `_TRAINER_NAME` | `0x804EB24C` | trainer name text |
| 0x24 | `msgctrlTrainerLose` | `_TRAINER_LOSE` | `0x804EB250` | text pointer |
| 0x25/0x26 | `msgctrlTrainerEnename{,2}` | `_TRAINER_ENENAME{,2}` | `0x804EB254`/`58` | text pointer |
| 0x27 | `msgctrlTrainerClientno` | `_TRAINER_CLIENTNO` | `0x804EB25C` | text pointer |
| 0x28 | `msgctrlWazaName` | `_WAZA_NAME` | `0x804EB260` | move-name text |
| 0x29 | `msgctrlItemName` | `_ITEM_NAME` | `0x804EB264` | item-name text |
| 0x2A | `msgctrlPasoName` | `_PASO_NAME` | `0x804EB268` | text pointer |

### The rest of the battle-relevant set

| Op | Handler | Source | Supplies | Note |
|---|---|---|---|---|
| 0x2B | `msgctrlHero` | save data | player field name | not a msgvar |
| 0x2D/0x2E | `msgctrlItem{,2}` | `_Item`/`_Item2` **u16** | item ID → name message | mode 2 |
| 0x2F/0x30 | `msgctrlDigit{,2}` | `_Digit`/`_Digit2` | integer, **no grouping** | §3 |
| 0x39 | `msgctrlWaza` | `_Waza` **u16** | move ID → name message | mode 2 |
| 0x41 | `msgctrlEvStrBuf2` | `_EV_STR_BUF2` | text pointer | stat direction |
| 0x42–0x44 | `msgctrlSideDefenceName*` | `_SIDE_DEFENCE_NAME*` | side qualifier | §4 |
| 0x4B | `msgctrlMoney` | `_Money` | integer, **grouped** | §3 |
| 0x4D/0x57 | `msgctrlString{,2}` | `_String`/`_String2` | text pointer | |
| 0x4E | `msgctrlPokemonID` | `_PokemonID` **u16** | species ID → name message | mode 2 |
| 0x59 | `msgctrlNpc` | `_Npc` **u16** | **message ID** | §5 |
| 0x0B, 0x0C | *(null handler)* | — | nothing | present in the shipped table with mode 0; used by 20387–20390 and 20414–20416 |

Six globals are **u16** (`_Item`, `_Item2`, `_Waza`, `_PokemonID`, `_Tribe`,
`_Npc`). Reading one as u32 picks up the neighbouring variable's bytes and
produces a plausible-looking wrong ID; the width is recorded per opcode and
pinned by a test.

### Recognised but not resolvable

`0x2C` (`msgctrlHizuki`, Rui's name — XD has no Rui and no global was
traced), `0x4C`/`0x64` (`msgctrlTime`). Registered so the renderer knows
their argument width, and marked `UNSUPPORTED` so a message using one is
**suppressed whole** rather than losing a subject silently. No
`fight_common` message uses any of them.

---

## 3. Number formatting — a corrected assumption

`msgctrlDigit` calls `_msgctrlMakeDigit(buffer, 16, _Digit, 0)`;
`msgctrlMoney` calls it with flag `4`. That function only takes its
separator-inserting branch for flag `4` or `0xA`.

The old renderer formatted **every** numeric opcode with thousands
separators. Corrected: quantities render as `1450`, money as `$1,350`. One
existing test asserted the old behaviour and was updated with the
disassembly citation.

---

## 4. Conditional opcode behaviour — Phase 1's reading was wrong

Phase 1 recorded that opcodes 0x0D/0x0E/0x0F/0x28 "have two possible read
sources depending on `ServerWork[7]`". **They do not.** Full trace:

`fightMsgctrlSetValue` (`fightMenu.s:0x802370EC`) diverts *writes* into a
four-entry cache while `ServerWork[7] == 2`:

```
ServerWork[7] == 2 ?  0x0F -> msgCtrlVal[0]   0x804187D0
                      0x0D -> msgCtrlVal[1]   0x804187D4
                      0x28 -> msgCtrlVal[2]   0x804187D8
                      0x0E -> msgCtrlVal[3]   0x804187DC
              else :  msgctrlSetValue(opcode, value)  -> the real msgvar
```

But `fightMenuOpenMsg` (`fightMenu.s:0x80237264`), which opens every battle
message box, **flushes the cache back through `msgctrlSetValue` into the
ordinary msgvars and zeroes each entry** before the window appears:

```
if ServerWork[7] == 2: wait msgFrame; ServerWork[7] = 0; fightMenuCloseMsg()
for (slot, opcode) in [(0,0x0F), (1,0x0D), (2,0x28), (3,0x0E)]:
    if msgCtrlVal[slot]: msgctrlSetValue(opcode, msgCtrlVal[slot]);
                         msgCtrlVal[slot] = 0
```

So `msgCtrlVal` is a **deferred write buffer**, not an alternate read
source. By the time a message is on screen — the only time this project can
observe it — the values are always in the ordinary globals and the cache is
empty. **The renderer needs no branch at all.**

This also explains a live symptom: `resolver.move_learning_sample` read
`msgCtrlVal[1]`/`msgCtrlVal[3]` directly and logged `invalid address
0x00000000` for 490 of 723 samples on message 20010, 291 of 351 on 20009,
and so on. The successes were races against the flush.

**Every value `ServerWork[7]` ever takes**, from a sweep of every
`r13-0x7860` access in the fight subsystem:

| Value | Written by |
|---|---|
| 0 | `_fightUpdate`, `fightMenuOpenMsg`, `WS_MESSAGE_WAIT`, `WS_WAZAKOUKA_MESSAGE`, `WS_ATTACK_MESSAGE2` |
| 1 | `WS_WAZAKOUKA_MESSAGE`, `fightSeqOpenMsg` |
| 2 | `WS_ATTACK_MESSAGE` only |

Read by `_fightUpdate`, `fightMsgctrlSetValue`, `fightMenuOpenMsg`,
`WS_MESSAGE_WAIT`. The domain is `{0, 1, 2}`; nothing else exists to
characterise.

---

## 5. Speaker opcode 0x59

Mode **2** — `_Npc` (`0x804EB2CA`, u16) holds a **name message ID**, not a
trainer record and not a pointer. In battle its writer is
`fightTrainerSetNameHearFlag` (`fightTrainer.s:0x801F8DDC`):

```
fightEncountDataBiosGetFightTrainerDataId(encount, 1)
  -> fightTrainerDB_GetName(trainerDataId)      a name message id
  -> fightMsgctrlSetValue(0x59, that id)
```

cleared by `_fightFinalize`. The renderer looks the ID up in the same string
tables as any other mode-2 opcode.

Retired: `narrator.compose`'s `structural_text` branch, which replaced the
literal marker `[Speaker]` with `opponent_trainer_full_name()` and stripped
every other `[...]` with a regex. That was a guess that happened to look
right for trainer defeat lines and had no defence anywhere else.

---

## 6. The safety contract, as implemented

`MessageRenderer.render()` returns a `Rendering`, speakable only when all of:

1. the message ID resolved to loaded GSchar bytes;
2. every opcode in the string is in `REGISTRY` (an unregistered opcode has
   unknown argument width, so the remainder of the string may already be
   garbage — refused before rendering);
3. every substitution resolved (a null global, a detached battler, an
   out-of-range database ID all raise);
4. the text is nonempty after normalisation;
5. the text carries no double-encoding signature.

When anything fails, `text` is set to **`None`** — the partial string is
discarded, not merely flagged, so no caller can read `.text` without
checking and speak `"Go! "` or `"is frozen solid!"`. `unresolved` carries
`(opcode, reason)` pairs for the log.

`narrator.suppress()` deduplicates on `(message_id, reasons)`, so an
unresolvable message on screen writes one line, not one every 50 ms.
`narrator.clear()` re-arms it at a battle transition.

---

## 7. Message lifecycle identity

The event identity is **(task slot, packed message ID, rendered text)**:

- `EventTracker` supplies open / id_change / close per task slot;
- `StabilityGate` double-samples the **rendered string**, so a substitution
  still being written re-arms instead of speaking a half-formed name;
- the rendered string *is* the argument snapshot — the same message ID with
  a different subject produces different text and speaks again, and the same
  ID with identical arguments settles once and stays quiet.

That is why 20023 speaks twice for two different prize amounts, and why
20044 speaks twice for two different Pokémon, without any per-message
bookkeeping.

---

## 8. Self-interruption — found, not guessed

The reported `"Oh! A Shadow Pokémon!"` arriving as `"h! A Shadow Pokémon!"`
is a playback race, not a text fault. The production log holds the pair with
timestamps:

```
00:05:50.837 DEBUG SPEECH class=BATTLE_EVENT interrupt=False text="Blastoise's Accuracy fell!"
00:05:50.901 DEBUG SPEECH class=BATTLE_EVENT interrupt=True  text="Blastoise's accuracy fell!"
```

64 ms apart. `BATTLE_EVENT` defaulted to `interrupt=True`, so the second
utterance silenced the first mid-word. The full text was in the log both
times, which is what proves the loss is in playback.

Two fixes, both root-cause:

1. **`SpeechCoordinator` no longer lets a battle event interrupt another
   battle event.** It still interrupts stale menu speech — that was the
   point of the interrupt. Consecutive battle facts are all information the
   player needs, so they queue.
2. **The duplicate voice is gone.** That log pair is one event spoken twice:
   `health.HealthTracker`'s stat-stage watcher *and* battle message 20244.
   The watcher existed as a fallback because the message used to fail (1,790
   logged rejections for 20247, which reads opcode 0x10 — the old code
   sampled the wrong global). With the message resolving, the fallback is a
   duplicate; `narrate_stat_stages` now defaults to `False`. Sampling
   continues and re-enabling is a constructor argument, because whether any
   stat change exists with *no* message has not been established.

No text was sliced to compensate, per the instruction.

---

## 9. Encoding boundary

Documented in `text_safety.py`. Game text is UTF-16BE; `memory.gschar()`
decodes it **once**; the value stays `str` to Tolk; every file write names
`encoding="utf-8"`.

The corruption never came from that path — it came from *source code*.
`resolver.FIXED_SENTENCES[20430]` held `"Oh! A Shadow PokÃ©mon!"`: the UTF-8
bytes of `é` stored as two cp1252 characters. The log proves both spellings
were spoken from the same message ID (28 × `PokÃ©mon`, 1 × `Pokémon`).

`is_double_encoded()` detects the signature by attempting the exact inverse
(`encode("cp1252")` then `decode("utf-8")`); genuine Latin-1 text fails that
decode and passes through. The renderer refuses to speak a string that
carries it.

**Running the check over the tree found six further genuinely corrupted
lines**, all repaired:

| File | Was | Now |
|---|---|---|
| `phase1b_app.py` `--help` | `PokÃƒÆ’Ã†â€™...Â©mon` (**four** round trips) | `Pokémon` |
| `profile.py` ×2 (comments) | `PokÃƒÂ©mart`, `PokÃƒÂ©dollar` | `Pokémart`, `Pokédollar` |
| `test_phase1e_menus.py` ×2 | `POKÃ©MON MART` | `POKéMON MART` |
| `test_dialogue.py` ×2 | `POKÃ©MON` in a **captured live fixture** | `POKéMON` |

Seven modules also carried a UTF-8 BOM — the same Windows-writer artefact —
now stripped. Two tests keep both clean permanently.

---

## 10. Legacy hardcoding removed

| Retired | Count | Replaced by |
|---|---|---|
| `resolver.FIXED_SENTENCES` | 11 | real templates; these IDs have **no** substitution opcodes, so the text needed no code at all |
| `resolver.CATCH_TARGET_TEMPLATES` | 13 | real templates + opcode 0x16 (`_ENEMY_MONS`) |
| `resolver.ACTOR_SENTENCE_TEMPLATES` | 8 | real templates + opcodes 0x0F/0x10/0x12 |
| `resolver.VICTORY_SENTENCE` | 1 | 20258/20300 + opcodes 0x22/0x23/0x25 |
| `resolver.PARTIAL_TRAINER_SENTENCES` | 1 | 20301 + opcodes 0x22/0x23 |
| `resolver.loss_sentence` / `poison_sentence` / `actor_sentence` | 4 | 20024/20025/20032/20034/20021 |
| `resolver.validate_stat` | 1 builder | 20243/20244/20246/20247 + 0x0D/0x0E/0x41 |
| `narrator.compose` move-learning dict | 7 | 20007–20013 + 0x0D/0x0E |
| `narrator.compose` inline sentences | 6 | 20003/20006/20026/20312/20313/20304/20305 |
| `narrator.compose` `structural_text` | 1 regex + guess | opcode 0x59 |
| `narrator.VERIFIED_OPCODES` | ~60 entries | registry membership + resolution success |
| `resolver.move_learning_sample` etc. | 3 samplers | generic rendering (and they read the wrong addresses — §4) |

**≈51 retyped sentences removed.** `RetiredTableTests` asserts every name is
absent from `resolver`, that `narrator` has no allow-list, and that no
retired message ID appears as a dict key mapping to a string literal.

### Fixed wording that remains, and why

| Where | Text | Justification |
|---|---|---|
| `health.loss_sentence` / `recovery_sentence` | "X lost 22 percent. 78 percent remaining." | The game draws an animated HP bar, not a sentence. There is no game text to render. |
| `health` condition names | `paralyzed` / `burned` / `frozen` | Opt-in fallback for a condition change with no message; not on the message path. |
| `IdentityLabeller` | "the foe's second Gardevoir" | Accessibility-owned. The game has no per-battler disambiguation because a sighted player looks at the screen (§4 of the identity model). |
| `hotkeys` summaries | "No Shadow Pokemon in your party." | Accessibility-only feature, no game equivalent. |
| `profile.command_labels` | Fight/Item/Pokemon/Call | **Still unverified.** Not touched this phase; it is a menu, not a message. Flagged for the menu work. |
| `menus.yes_no_focus` | Yes/No | **Still unverified.** Phase 4 owns it. |

---

## 11. Integration with the canonical identity model

The renderer does **not** contain an identity mapper. It records which
`FightOutPokemon*` each battler-nickname opcode dereferenced in
`Rendering.subjects`, and the narrator hands those to
`BattleIdentityResolver.from_fight_out()`.

The rendered sentence keeps the game's own nickname text — that is the
authoritative wording. The identity model is used for two separate things:
lifecycle tracking (Phase 2's epochs), and appending a clarifier **only**
when two battlers on the field answer to the same name:

```
GARDEVOIR is frozen solid! The foe's first Gardevoir.
```

A unique name gets nothing appended. An unresolvable clash logs
`SUBJECT AMBIGUOUS` and appends nothing, rather than guessing.

---

## 12. Tests

`tests/test_battle_messages.py`, 65 tests. The fixtures plant each message's
**own shipped GSchar bytes** (`FightCommonCatalog.Message.raw`) into a
synthetic runtime string table laid out the way `GSmsgGetGSchar` reads one,
set the msgvars its opcodes name, and let the real renderer decode it.
Nothing types a game sentence into Python; the asserted strings were
produced by running the fixture and pinning what the shipped data decodes
to.

Groups: registry completeness and widths; status/effect messages; Shadow;
rewards and capture; send-outs and trainers; side names; the safety
contract; encoding; lifecycle; disambiguation; speech sequencing; and the
retired-table guard.

**Full suite: 981 passing** (Phase 2 left it at 942).

---

## 13. Awaiting live triggers

Everything below renders correctly from shipped data and is automated-test
validated. None is live-tested.

Frozen · drowsy · fell asleep · is asleep · woke up · badly poisoned ·
immunity · Call family (20432/20433/20435) · Shadow discovery ·
Reverse Mode · Snag Ball · money reward · wild appeared · capture success ·
nickname prompt · EXP and level-up text · all four send-outs ·
trainer challenge and class/name · speaker opcode 0x59 · side-name
qualifiers · the no-self-interrupt change.

A narrator restart is required for any of it to take effect.

---

## 14. The identity-sensitive opcodes, resolved (2026-08-06)

All four unknowns this section previously listed are closed. Each was
resolved from the **writer's call chain**, then cross-checked against every
shipped template that uses it. None of them required a behaviour change —
the registry's *types* were already right; what was missing was the
*meaning*, and one profile field name was actively misleading.

### 0x11 `_CLIENT_MONS` — the Pokémon whose move or action is unavailable

Not a link-battle "client". Four writers, all agreeing:

| Writer | Passes |
|---|---|
| `fightSeqAttackPokemonJoutaiCheck` (Disable branch) | the blocked battler, after `fightOutPokemonInitJoutaiKeep` + `SetKanashibariNoAttackFlag` + `ServerStatusFlag \|= 0x8` |
| same (Taunt branch) | ditto, `SetChouhatsuNoAttackFlag` |
| same (Imprison branch) | ditto, `SetHuuinNoAttackFlag` |
| `_fightMenuFightTrainerGcHeroOpenMenuSubMain` / `SubWaza`, `menuFight._menuFightIsUse` | the battler, in the branch where `fightOutPokemonCheckFightActionWazaSelect` / `CheckCanOutOkWazaBanme` says the move cannot be chosen |

All **six** shipped templates agree: 20197 `has no moves left!`,
20198 `'s [Move] is disabled!`, 20199 TORMENT, 20200 TAUNT, 20201 `sealed`,
20384 (bare name). It is a **third role**, independent of attacker and
defender — a test plants all three differently to prove it.

### 0x1E `_CLIENTNOWORK` — the FightFloor's *appointed* Pokémon

Canonical setter `fightFloor_SetAppointPokemonPtr` (指定 = appointed). It
writes this opcode **and opcode 0x1C (`_SPEABI_NAMEC`) as a pair**:

```
if fightOutPokemonCheckValid(pokemon):
    0x1E = pokemon
    0x1C = GSmsgGetGSchar(pokemonTokuseiDataBiosGetName(
               pokemonTokuseiDataBiosGetPtr(
                   fightOutPokemonGetTokuseiDataId(pokemon))))
else:
    0x1E = 0 ; 0x1C = 0        # both cleared together
```

`fightFloorSetStatus` and `EscapeNGCheck` do the same. That pairing is why
most of its **41** templates read `[0x1E]'s [Ability] …`. But
"ability holder" is too narrow: 20144 `[0x1E] is hurt by SPIKES!`,
20093 `is protected by MIST!`, 20185 `SNATCHED [0x1E]'s move!` and the item
family (20191/20192) have no ability at all. The registry name is now the
game's own word, "appointed Pokémon".

Because 0x1E and 0x1C are written and cleared together, a template using
both and resolving only one is not a state the game produces — the renderer
suppresses, and a test pins it.

### Trainer names — one field name was wrong in a way that mattered

Every writer (`fightActionFlowSyuuryou`, `KaisiPre`,
`KaisiNyuujouPokemon`, `WS_POKE_HPDEC_RATE`, `WS_POKE_HPMAX_RATE`,
`fightSeqItemExec`) emits the same sequence:

```
0x22 = fightTrainerGetPrefixNamePtr(trainer)   the CLASS   "Cipher Peon"
0x23 = fightTrainerGetNamePtr(trainer)         its NAME    "Greesix"
0x25 = fightTrainerGetNamePtr(otherTrainer)    a SECOND trainer's NAME
0x26 = a THIRD trainer's name, same accessor
```

So **0x25/0x26 are two different trainers, both proper names, no class**.
`profile.trainer_enemy_class_name` / `trainer_enemy_personal_name` claimed
otherwise and are renamed `trainer_first_name` / `trainer_second_name`. The
"ene" in `_TRAINER_ENENAME` is 敵 (enemy) — *whose* name, not what kind.

This exposes a message family the project had never distinguished:

| Form | Template | Trainers | Pokémon globals |
|---|---|---|---|
| One trainer sends two | 20305 | 0x22 + 0x23 | 0x16, 0x17 |
| **Two trainers each send one** | **20309** | **0x25, 0x26** | **0x18, 0x19** |

with 20259/20261/20263 (`Player beat [0x25] and [0x26]!`) as the matching
result messages. Nothing currently swaps or duplicates them — the renderer
reads each opcode's own global, and a test asserts the class appears exactly
once.

One shipped-data quirk worth recording: 20303 is
`[0x25] and [0x25] want to battle!` — the *same* opcode twice, so both names
render identically. The renderer reproduces what the game does rather than
"correcting" it to 0x26.

### 0x0B / 0x0C — conclusively inert

Shipped entries hold flags `0x00` and handler `0x00000000` (mode 0,
"contributes no characters"), and **zero argument bytes** — they are absent
from the string format's `k2ByteChars`/`k5ByteChars` sets, and all nine
messages that use them decode cleanly on that assumption. Tests confirm they
neither suppress a message nor consume the following bytes.

All nine are **menu panels, not battle sentences**: 20387 `PP TYPE/`,
20388, 20389 `Which move should be forgotten?`, 20390 `Yes No`,
20391 `Switch which moves?`, 20392, and 20414/20415/20416
`Win`/`Loss`/`Tie`. Consistent with a panel-layout directive.

**A separate finding while confirming this.** Six of the nine also contain
the *literal ASCII text* `<SCOL=0x0d0e0f>` — menu-panel markup written into
the string data, not the binary colour opcode 0x08. The renderer passes it
through faithfully. Stripping it belongs to whoever consumes these panels,
where the markup grammar can be established; a regex that eats anything in
angle brackets would be a guess, and no battle message uses this form.

**Directly useful for the Yes/No work:** message **20390** is the battle
Yes/No panel's own label string, i.e. an authoritative resource for the
labels `menus.yes_no_focus` currently hardcodes — pending the markup
question above.

---

## 15. Remaining unknowns

1. **Whether any stat change has no message**, the one thing that would
   justify re-enabling `narrate_stat_stages`.
2. **`profile.command_labels`** remains an unverified index→word tuple.
3. **The `<SCOL=…>` markup grammar** in the nine panel strings.
4. **`_TRAINER_LOSE` (0x24)** and **`_TRAINER_CLIENTNO` (0x27)** — one and
   two templates respectively (20002; 20311/20325, the link-battle
   send-out/withdraw forms). Both are plain text pointers and render, but
   their writers were not traced because no single-player message uses them.
5. **Dead code:** `resolver.trainer_party_names`,
   `opponent_trainer_full_name` and `opponent_trainer_name` are no longer
   called by anything in production (opcodes 0x22/0x23 supersede the last
   two). They are inert, not a second speech path. Cleanup, not a bug.
