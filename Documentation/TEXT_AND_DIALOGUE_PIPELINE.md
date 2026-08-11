# TEXT_AND_DIALOGUE_PIPELINE.md

Audit of the text/dialogue pipeline across `xd-decomp/`, `Pokemon-XD-Code/`, and `Research/ThirdParty/XDscriptTools/`, plus a design (not an implementation) for a local extraction tool and a first dialogue vertical slice. Follows the citation convention established in [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md): **Confirmed** (direct code/file read), **Inferred** (plausible but not directly proven), or **Unknown**. All `Pokemon-XD-Code`/`XDscriptTools` findings are for **vanilla XD/Colosseum US only** — see the version-scope warning in `ARCHITECTURE_CODEMAP.md`; nothing here is verified against XG.

---

## 1. The encoding question — resolved (not a disagreement, two different pipeline stages)

The task framed this as an open disagreement between "two-byte Unicode," `xd-decomp`'s GSchar/SJIS code, and `Pokemon-XD-Code`'s decoder. Having read actual function bodies on both sides (not just symbol names), the answer is: **all three are correct simultaneously, describing different stages of the same pipeline.** There is no real contradiction, only an unstated seam between build-time source encoding and shipped-binary runtime encoding.

### 1a. `xd-decomp`'s SDK font layer (Confirmed, real decompiled source) — this is NOT the game's dialogue system

`src/dolphin/os/OSFont.c` (751 lines, fully decompiled, matched) is the **Nintendo GameCube SDK's** generic on-screen-text/debug-font renderer (`OSGetFontTexel`, `OSInitFont`, `OSLoadFont` — used by things like `OSReport`/`OSPanic`'s red-screen text, per category 14 of `ARCHITECTURE_CODEMAP.md`). It supports six selectable "font encode" modes (`OS_FONT_ENCODE_ANSI=0`, `OS_FONT_ENCODE_SJIS=1`, and 3/4/5, all unnamed in the header but handled explicitly in code):

- `ParseStringS` (`OSFont.c:466-496`) — modes 0/1 only: single-byte ANSI, or SJIS lead/trail-byte pairs read directly from an 8-bit `char*` stream (`IsSjisLeadByte`/`IsSjisTrailByte`, `OSFont.c:204-210`).
- `ParseStringW` (`OSFont.c:498-555`) — adds modes 3/4/5, which route through **`src/dolphin/os/OSUtf.c`**: mode 3 = UTF-8 (`OSUTF8to32`, `OSUtf.c:4-61`), **mode 4 = UTF-16 (`OSUTF16to32`, `OSUtf.c:97-125`, full surrogate-pair handling)**, mode 5 = fixed-width UTF-32. Whatever the decoded `utf32` code point is, it is then converted back down to a **single glyph-sheet index** via `OSUTF32toANSI`/`OSUTF32toSJIS` (`OSUtf.c:165-180`, `4475-4488`) so it can be drawn from the SJIS or ANSI glyph sheet loaded by `OSLoadFont`.

**This is the concrete mechanism that reconciles "SJIS" and "Unicode":** the SDK's own font pipeline already treats UTF-16 as one of several *input* encodings, all of which get funneled down to SJIS/ANSI glyph lookups for actual rendering. No call site inside `xd-decomp` proves the game invokes `OSSetFontEncode(4)` specifically (no decompiled game-logic source touches this — **Unknown** which mode the game actually selects at runtime), but the SDK-level capability is Confirmed real code, not conjecture.

### 1b. `xd-decomp`'s game-native "GSchar" text system (Confirmed symbol+address, no decompiled body) — a *different*, higher-level system than OSFont

Separately from the SDK font layer above, `xd-decomp` resolves an entire **"GSchar"** family with no source bodies (`config/GXXE01/symbols.txt:4453-4493`): `SJIStoGSchar__FPUsPc` (`.text:0x8010B320`), `GScharMakeFromSJIS` (`0x80106C8C`), `GScharCat`/`GScharCpy`/`GScharCmp`/`GScharLenCpy`, and message-composition functions `GSmsgMakeGScharStr`, `GSmsgGetGSchar`, `GSmsgGetCharLength`, `GSmsgGetLength`, `GSmsgPrint2`, `GSmsgPrintRect`, etc.

The Metrowerks name-mangling on these symbols is itself informative even without a decompiled body: `SJIStoGSchar__FPUsPc` demangles to `SJIStoGSchar(unsigned short*, char*)` — **a function that takes a raw `char*` (SJIS source bytes) and writes into an `unsigned short*` (16-bit-per-character) destination.** `getGScharLen__FPUs` (`symbols.txt:884`) likewise takes a `PUs` (pointer-to-`u16`) argument. **This proves, from the mangled signatures alone (Confirmed, not Inferred), that GSchar is a 16-bit-per-character in-memory string format, built from SJIS source text via an explicit conversion step** (`SJIStoGSchar`/`GScharMakeFromSJIS`), not itself a raw SJIS byte stream. `configure.py`'s `-multibyte`/`sjiswrap` build flags and the raw `sjis_81xx`/`sjis_e0xx` charset rodata tables (`symbols.txt:13675-13676`) confirm the *source* side of this conversion is genuinely SJIS.

Aside: `GBAMakeFromGSchar`/`GScharMakeFromGBA` (`symbols.txt:4454-4455`) are **not** encoding-related to the dialogue question — `GBA*` here is the real Game Boy Advance JOYBUS link-cable subsystem (`GBAInit`/`GBARead`/`GBAWrite`/`GBAReset`, `symbols.txt:10616-10627`), i.e. nickname-charset translation for GBA-linked Pokémon trades, a separate feature.

### 1c. `Pokemon-XD-Code`'s decoder (Confirmed, real working code, reads actual shipped string-table bytes) — the shipped/runtime format

`Objects/file formats/XGStringTable.swift`'s `getStringAtOffset(_:)` (lines 388-434) is the actual byte-level reader, and it is unambiguous: it reads the string table **two bytes at a time** (`stringTable.get2BytesAtOffset(currentOffset)`). If those two bytes equal `0xFFFF`, the *next single byte* is a control-code opcode (`XGSpecialCharacters(rawValue:)`) followed by a code-specific number of extra raw bytes; otherwise the two bytes are appended directly as `.unicode(currChar)` (line 425). `XGUnicodeCharacters.swift:72` then renders that value with `UnicodeScalar(i)` — a **direct, unmapped cast from the 16-bit on-disk value to a Unicode scalar**, not a table lookup into an SJIS codepage. This is what shipped in the retail disc image `Pokemon-XD-Code` was built against, read directly, not inferred from documentation.

### 1d. Reconciliation (Inferred, but now well-supported, not a guess)

Put together, the pipeline most likely is: **source dialogue text is authored/compiled from Shift-JIS (1c confirms `SJIStoGSchar` exists and is signature-proven to consume `char*`/SJIS input) → converted at build time into GSchar, a 16-bit-per-character intermediate (1b, signature-proven u16 width) → the values GSchar actually uses for Latin-script text are themselves valid Unicode code points, since English/localized text has no need for a JIS-specific 16-bit space and the simplest implementation is to just store the Unicode scalar (1c, confirmed by direct byte read of shipped data) → at render time, OSFont's UTF-16 input mode (1a, confirmed real SDK code) is exactly the kind of facility that would consume this 16-bit GSchar stream and resolve each code point down to a glyph.** This was not found stated explicitly as one continuous citation in either project — no single function proven to bridge 1b and 1c/1a directly — so the *linkage* remains Inferred. But it is no longer an unresolved disagreement: **"two-byte Unicode" (1c, what's on disk/in the shipped tables) and "SJIS/GSchar" (1b, the build-time authoring and 16-bit intermediate format) are both true, describing different points in one pipeline, not competing claims about the same artifact.** Nothing here should be read as fully proven end-to-end; the gap is the missing decompiled body of `GSmsgMakeGScharStr`/`SJIStoGSchar` themselves.

---

## 2. String-table file format (Confirmed, `Objects/file formats/XGStringTable.swift`)

Read directly from `XGStringTable.swift:12-434`:

- **Header:** bytes `0x00-0x03` unidentified/unused by the reader; **`0x04`** = 2-byte entry count (`numberOfEntries`, line 29, `kNumberOfStringsOffset = 0x04`); entries begin at **`0x10`** (`kEndOfHeader`).
- **Index table:** one 8-byte entry per string, starting at `0x10`: 4-byte big-endian **ID** masked to the low 20 bits (`getWordAtOffset(currentOffset) & 0xFFFFF`, line 321 — `kMaxStringID = 0xFFFFF`), then a 4-byte big-endian **byte offset** into the table where that string's data begins (line 322).
- **String data:** UTF-16BE-like 2-byte code units (section 1c above) terminated by a `0x0000` unit (checked as a one-unit lookahead, `getStringAtOffset`, lines 397-430).
- **File padding:** the table is described as always ending in extra `0x00` padding bytes past the last string's terminator (`extraCharacters`, lines 36-57) — used as free space when adding/lengthening strings without growing the file.
- **Multiple tables can share one host file** (e.g. three separate tables inside `common.rel`, distinguished by `startOffset` + `subFileIndex`, `XGStringTable.swift:63-119`) — the table object itself doesn't "know" its own file; it's handed a `(file, startOffset, fileSize)` triple by the caller.

---

## 3. Message IDs and speaker identifiers

- **Message ID** is the 20-bit value from the index table above (section 2). It is a flat, global-feeling namespace per table, not per-map — `getStringWithID(id:)` (`Objects/managers/XGStringManager.swift:77-101`) linearly searches an ordered list of tables (`allStringTables`) and returns the first match, meaning **the same numeric ID space is reused across every loaded table**, with lookup order breaking ties (common tables first — see section 6).
- **Speaker** is not a table field — it's a **control code inside the string data itself**: `speaker = 0x59` ("Speaker") and `setSpeaker = 0x6A` ("Set Speaker 106") in `XGSpecialCharacters` (`enums/XGSpecialStringCharacters.swift:151,168`). Neither carries extra bytes per the `k2ByteChars`/`k5ByteChars` tables (`extraBytes` property, same file lines 181-198), meaning speaker identity is set through the runtime `setMsgVar` mechanism (section 5 below) rather than embedded as a literal ID in the string bytes.
- **`xd-decomp` runtime state (Confirmed symbol+address, no source):** `_MsgID = .sbss:0x804EB284` (`symbols.txt:17984`), accessed via a tiny 8-byte (2-instruction) getter `msgctrlMsgID = .text:0x801547AC` (`symbols.txt:6780`) — consistent in size/shape with a trivial `lwz`+`blr` field accessor. A parallel `_MenuMsgID`/`_MenuMsgID2` pair (`.sbss:0x804EB2C0`/`0x804EB2C4`) with getters `msgctrlMenuMsgID`/`msgctrlMenuMsgID2` (`.text:0x801536B4`/`0x801536BC`) suggests a **generic, non-menu-specific "message control" (`msgctrl`) subsystem tracking "the currently active message ID" as live state**, distinct from the per-screen `menuTitleStatus`/`menuFightStatus`-style state objects seen elsewhere in the codebase. This is the strongest candidate in either repo for "the live RAM address of the currently displayed message's ID" — flagged Confirmed only at the symbol/address/size level; no decompiled body confirms what it actually holds. Also present: `TitleMsgID = .sbss:0x804EA7E0` (`symbols.txt:17386`) and `ExplanationMsgID` (two instances, `symbols.txt:17447,17477`) — narrower, per-screen message-ID variables of the same general pattern.

---

## 4. Control codes, newlines, formatting codes (Confirmed, `enums/XGSpecialStringCharacters.swift:11-325`)

All control codes share the same on-disk shape: `0xFFFF` (2-byte escape marker) + 1-byte opcode + N extra raw bytes (N is 0 for most codes, 1 for `[0x07, 0x09, 0x38, 0x52, 0x53, 0x5B, 0x5C]`, 4 for `[0x08]` — `k2ByteChars`/`k5ByteChars`, lines 11-12). Fully enumerated opcode table (`XGSpecialCharacters`, lines 60-172), the ones with confirmed semantics:

| Opcode | Name | Notes |
|---|---|---|
| `0x00` | New Line | Rendered as literal `\n` by the reader (`isNewLine`, line 207) |
| `0x02` | Dialogue End | |
| `0x03` | Clear Window | |
| `0x04`/`0x05`/`0x06` | Kanji / Furigana Start / Furigana End | JP-only formatting |
| `0x07` | Change Font (2 bytes: 1=bold, 2=superscript, 3=regular, 4=superscript) | |
| `0x08` | Change Colour, specified RGBA (5 bytes) | |
| `0x09` | Pause (2 bytes; 2nd byte likely tenths-of-a-second duration) | |
| `0x13` | Player name (battle context) | see section 5 |
| `0x14`/`0x15` | Switch-Pokémon message 1/2 | |
| `0x22`/`0x23` | Foe trainer class / foe trainer name | |
| `0x2B` | Player name (field context) | see section 5 |
| `0x2C` | "Rui" (Colosseum only — a named NPC) | |
| `0x38` | Change Colour, predefined palette (2 bytes: 0=white,1=yellow,2=green,3=blue,4=yellow,5=black) | |
| `0x4D` | Loads another `.msg` string as the substitution variable | cross-reference / nested-string mechanism |
| `0x50` | Play a Pokémon species cry as audio, from a species value set via `setMsgVar` | directly cross-referenced in `XDscriptTools`, see section 5 |
| `0x59`/`0x6A` | Speaker / Set Speaker | see section 3 |
| `0x6D` | Wait for key press (dialog box holds until input; typical in battle) | directly relevant to "continuation prompt" handling |

Everything else in the 0x00-0x6E range is either an unlabeled `varXX`/`specialXX` placeholder (present as a raw opcode with no confirmed semantic — genuinely Unknown, not guessed) or a Pokémon/item/move/ability variable slot (section 5).

---

## 5. Player-name, Pokémon/item/move-name substitutions (Confirmed cross-reference between two independent repos)

The string-table control codes above are **placeholders**, not literal text — the actual substitution value is supplied by the running script, not stored in the table. This is proven by a direct, matching cross-reference between the two otherwise-unrelated repos:

- `Pokemon-XD-Code`'s `XGSpecialCharacters.pokemonSpeciesCry = 0x50` is labeled `"Pokemon Cry 80"` (`enums/XGSpecialStringCharacters.swift:31,142` — 80 decimal = `0x50`).
- `XDscriptTools`' `FunctionInfo.py:259-260` documents `Character.displayMsgWithSpeciesSound` with the comment: *"Uses the species cry from `Dialogs::setMsgVar($dialogs, 50, species)`"* — i.e. the field-script API sets a **numbered message variable slot** immediately before requesting the dialogue box, and the in-string control code (opcode `0x50`) is what pulls that slot's value back out at render time.

The same numbering pattern recurs across every other labeled placeholder in `XGSpecialStringCharacters.swift` (`"Player Battle 19"`, `"Player Field 43"`, `"Foe Tr Class 34"`, `"Foe Tr Name 35"`, `"Pokemon 15/16/17/18"`, `"Item 41/45/46"`, `"Move 40"`, `"Ability 26/27/28/29"`, `"Quantity 47"`, `"Wait Input 109"`, `"Set Speaker 106"`) — each decimal number is Inferred (not individually confirmed like the species-cry one) to be the corresponding `setMsgVar(type, value)` slot index. `Dialogs::setMsgVar` itself is Confirmed to exist as a script API: `FunctionInfo.py:329`, `ClassInfo(name="Dialogs", index=40)`, `FunctionInfo(name="setMsgVar", index=28, nbParams=3)`.

Practical meaning for player-name substitution specifically: there is **no single "player name" string baked into any dialogue table**. Every occurrence of the player's name in dialogue is opcode `0x13` (battle) or `0x2B` (field), resolved at render time from whatever the script most recently wrote via `setMsgVar`. An extraction tool cannot show "the real text" for these without also knowing the substituted value at read time (see section 8's `control_codes` field).

---

## 6. Dialogue-choice (yes/no) structures (Confirmed, cross-repo agreement)

Two independently reverse-engineered projects agree on the shape of this call, which is a strong signal:

- **`xd-decomp` (symbol+address, no source):** `dispMsgYesNo__FUl = .text:0x800A4798` (`ARCHITECTURE_CODEMAP.md` category 3; demangles to `dispMsgYesNo(unsigned long)` — **a single `u32` parameter**, i.e. exactly a message ID and nothing else).
- **`XDscriptTools` (real, working Python — parses actual compiled `.scd` script bytecode):** `Dialogs.displayYesNoQuestion`, `index=21`, `nbParams=1` (`FunctionInfo.py:327`) — **also a single parameter, `(int msgID)`** per its own comment.
- **`Character.talk(type, msgID, ...)`** (`FunctionInfo.py:265-272`, `index=73`, variadic): documented type codes include `(8, msgID)` = "yes/no question" as one of ~22 dialogue variants dispatched through a single generic `talk` script call, alongside `(1, msgID)` normal message, `(16, msgID)` informative/no-sound message, `(15, species)` play species cry only.

Together: a yes/no prompt is not a distinct data structure in the string table — it is an ordinary message ID, displayed through a call that tells the engine "render this with two selectable options" rather than "render this and wait for a single confirm." The table-side text itself is presumably followed by however the two option labels are conventionally represented (not confirmed in either repo — genuinely **Unknown** whether "Yes"/"No" are separate embedded strings, a fixed pair the engine hardcodes, or two lines separated by a control code not yet identified above).

---

## 7. Where common strings live vs. map-specific strings (Confirmed, `XGStringManager.swift:14-63`, `CMRelIndexes.swift:103-126`)

`loadAllStrings()` builds one ordered list, `allStringTables`, that `getStringWithID` searches in order (first match wins):

1. **Common tables**, loaded first: `common.rel`'s internal `StringTable1`/`StringTable2`/`StringTable3` (region-dependent internal-pointer-table indices — for US: `StringTable1` index 98, `Script` index 101, `CMRelIndexes.swift:103-126`), plus `main.dol` itself (`XGStringTable.dol()`, hardcoded byte-range offsets per region, `XGStringTable.swift:142-173`) and, for XD specifically, two more `dol`-embedded tables (`dol2`/`dol3`) and a separate `tableres2` resource file's two tables (non-JP, non-demo builds only) — `XGStringManager.swift:25-37`.
2. **Map/per-file tables**, appended after the common set: every extracted file of type `.msg` (`XGFileTypes.swift:17,91` — `case msg = 0x0a // string table`), enumerated via `XGFiles.allFilesWithType(.msg)` (`XGStringManager.swift:58`). `.msg` files are individually-packaged string tables extracted from per-map `FSYS` resource containers (the file-type description in `XGFileTypes.swift:146` states this directly: *"Files containing game text... The search will look through msg files one at a time until it finds the one containing the id it needs."*).

Practically: **item/move/species/ability names and other globally-reused strings live in the common tables (`common.rel`, `main.dol`, `tableres2`); actual room/NPC dialogue lives in per-map `.msg` files bundled with that map's other FSYS resources.** A lookup by message ID must fall back through common tables and then every loaded map's `.msg` table, in that order — exactly mirroring `getStringWithID`'s real search loop.

---

## 8. Runtime message-request/render functions — the best-supported lead

Two independent layers were found, and they agree with each other in shape (both take a message ID as the primary/only identifying parameter):

**Field/overworld scripting layer (`XDscriptTools`, real working bytecode parser, not just symbol names):** the `Dialogs` script class (`FunctionInfo.py:320-339`, class index 40) is the actual API game scripts call to request dialogue:
- `displayMsgBox(msgID, isInForeground, dontDisplayCharByChar, textSoundPitchLevel)` — index 17
- `displatSilentMsgBox(msgID, isInForeground, dontDisplayCharByChar)` — index 16 (sic, typo preserved from source)
- `displayYesNoQuestion(msgID)` — index 21
- `setMsgVar(type, val)` — index 28 (the substitution mechanism, section 5)
- `Character.talk(type, msgID, ...)` — index 73, a second, generic multi-purpose dialogue dispatcher (section 6)

**Field engine layer (`xd-decomp`, symbol+address only, no decompiled body):** `CInfoWindow` class handles the actual on-screen textbox (`exec__11CInfoWindowFR9CMetaMenuUlb = 0x8001FA14`, `draw__11CInfoWindowFv = 0x8001FAA4`, `open__11CInfoWindowFUlb`, `close__11CInfoWindowFv`, `isMsgEnd__11CInfoWindowFv = 0x8001FC2C` — this last one, "is message end," is a strong candidate for detecting the "waiting for input to continue" state described in section 4's `0x6D` opcode); free functions `dispMsg__FUl = 0x800A481C` and `dispMsgYesNo__FUl = 0x800A4798` both take exactly one `u32` (message ID) per their mangled signatures (section 6); `_MsgID`/`msgctrlMsgID` (section 3) as the best live-state candidate.

**This combination — `Dialogs::displayMsgBox`/`displayYesNoQuestion` at the script layer, `CInfoWindow`/`dispMsg*` at the engine layer, and `_MsgID`/`msgctrlMsgID` as the plausible live-state holder — is the single best-supported message-ID/rendering-function lead in this audit.** It is corroborated by two independently-authored tools agreeing on call shape, not a single unverified source. None of these addresses/names are verified against XG.

---

## 9. Extraction tool concept (design only, not implemented)

A local, read-only Python tool, conceptually layered on the *already-working* logic in `Objects/file formats/XGStringTable.swift` (reimplemented, not literally reused, since that file is Swift and this project's other tooling is Python/PowerShell per `Companion/`) rather than reverse-engineered from scratch:

1. **Table locator** — given a target file (`common.rel`, `main.dol`, a specific `.msg` file extracted from an FSYS container) and the offset/size pairs documented in section 2/7 (region- and game-dependent — XD US values are cited throughout `CMRelIndexes.swift`/`XGStringTable.swift`, **unverified for XG**), slice out the raw table bytes.
2. **Header/index parser** — read entry count at `0x04`, then the 8-byte-per-entry `(id: u32 masked to 0xFFFFF, offset: u32)` table starting at `0x10` (section 2).
3. **String decoder** — for each offset, walk 2-byte units until a `0x0000` terminator; on `0xFFFF`, read the 1-byte opcode plus its fixed extra-byte count (section 4's table) and emit a structured control-code token instead of a character; otherwise emit the 2-byte value as a Unicode code point (section 1c).
4. **Metadata emitter** — for each decoded string, emit one JSON record shaped as requested:
   ```json
   {
     "source_file": "common.rel",
     "table_id": "StringTable1",
     "message_id": 1234,
     "speaker": null,
     "decoded_text": "Hello, [Player Field 43]! Would you like a [Pokemon 15]?",
     "control_codes": [
       {"opcode": "0x2B", "name": "Player Field 43", "offset_in_string": 7, "extra_bytes": []},
       {"opcode": "0x0F", "name": "Pokemon 15", "offset_in_string": 33, "extra_bytes": []}
     ]
   }
   ```
   - `speaker` stays `null` unless a `0x59`/`0x6A` (Speaker/Set Speaker) code is present in the string, in which case it records the opcode occurrence, not a resolved name (the actual speaker identity is script-supplied at runtime per section 5, not stored in the table).
   - `decoded_text` renders substitution codes as bracketed placeholders (mirroring `Pokemon-XD-Code`'s own `XGUnicodeCharacters.string` convention, `enums/XGUnicodeCharacters.swift:75-87`) rather than guessing a resolved value, since the tool has no access to live script state while doing static extraction.
5. **Output** — one JSON file per source table, or one combined file per game build, written to a local, gitignored directory (see section 11).

This tool would run entirely offline against a locally-extracted copy of the user's own legally-owned XG files — it does not touch a running game or Dolphin, and is a strictly separate concern from the live-memory-reading vertical slice below.

---

## 10. First dialogue vertical slice (design only, not implemented)

Mirrors the phased structure and constraints already established in [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md) (Route B: external Windows companion, read-only, `dolphin_memory_engine`, `cytolk`/NVDA) — this section extends that same methodology to dialogue instead of menu-cursor state, and assumes Phase 0/Phase 1 of that document (address-discovery workflow, tooling, safety rules) are already understood.

1. **Local extraction (offline, one-time, per map):** using the design in section 9, extract one known map's `.msg` table locally against the user's own XG files. Output stays local (see section 11) — this step never touches a running game.
2. **Identify the runtime message-ID/text-buffer source:** starting from the leads in section 8 (`_MsgID`/`msgctrlMsgID` in `xd-decomp`, `CInfoWindow`'s `isMsgEnd`), run the same **address-discovery experiment already defined in `FIRST_VERTICAL_SLICE.md` Phase 0** (interactive scan via Dolphin's built-in debugger or Dolphin Memory Engine, changed-value narrowing, restart-stability check) but targeted at dialogue: trigger one known dialogue box repeatedly, and look for a value that changes exactly when — and only when — the message ID changes, using the vanilla-XD leads above as a prioritized shortlist rather than a blind scan. This step is XG-specific and cannot be pre-verified from either repo (same caveat as the menu-cursor slice).
3. **Trigger one dialogue box** in-game (user-driven, one exact action, acknowledged before proceeding — same interaction discipline as `FIRST_VERTICAL_SLICE.md`'s Phase 0C).
4. **Read the active ID/state without writing memory** — poll the address found in step 2 read-only, via `dolphin_memory_engine`'s `read_word()`-style calls (already proven working in `Companion/test_dolphin_connection.py` per `FIRST_VERTICAL_SLICE.md`'s "Current implementation status"). No write API is ever called, consistent with the existing project rule.
5. **Resolve through the local table:** look up the observed message ID in the JSON produced by step 1, falling back through common-table-then-map-table order (section 7) if the ID isn't in the current map's table.
6. **Speak it through NVDA once:** `tolk.load()` + `tolk.speak(decoded_text, interrupt=True)` — the exact sequence already confirmed working in `Companion/test_speech.py`.
7. **Deduplicate repeated frames:** same debounce pattern already designed in `FIRST_VERTICAL_SLICE.md` Phase 1 ("How changes are detected without repeatedly speaking unchanged text") — track `last_message_id`, only speak on change.
8. **Handle continuation/choice prompts:** use the `0x6D` (Wait for key press) control code and/or `CInfoWindow::isMsgEnd` (section 4/8) as the signal that the box is holding for input rather than mid-animation; for yes/no prompts (section 6), the extraction/speak step would need to additionally announce that a choice is pending — the exact mechanism for reading *which* option is highlighted is a **new, separate discovery target**, not yet identified in either repo (no "yes/no cursor" address or symbol was found in this audit — flag as Unknown, analogous to the still-open battle-command-cursor question in `ARCHITECTURE_CODEMAP.md`'s Phase 0 runtime-correction note).
9. **Stop after user confirms the result** — same "small, verifiable, user-supervised step" discipline as the rest of this project's design docs; no autonomous looping beyond one dialogue box until the user reviews the outcome.

---

## 11. Legal/storage note — local extraction data must stay gitignored

Per the project's existing `.gitignore` (root of the repo), the established convention for locally-generated, potentially-copyright-sensitive game data is an explicit, path-specific ignore entry with a comment citing its source doc — e.g. `/Companion/_phase0_scratch_snapshots/` and `/Companion/logs/`, both commented *"may contain substantial copyrighted game data; local-only per FIRST_VERTICAL_SLICE.md"*. Any local dialogue/string database produced by section 9's tool (extracted text, decoded message tables, per-map JSON dumps) is squarely the same category of data — full in-game dialogue text is copyrighted content — and **must** follow the identical convention: a dedicated path (e.g. `/Companion/_dialogue_extraction/`, matching the existing `_phase0_scratch_snapshots` naming pattern) added to `.gitignore` with a comment pointing at this document, before any such extraction is actually run. This document does not add that line itself (design only, per instructions) — flagging the exact convention to follow when the extraction tool in section 9 is actually implemented.

---

## 12. Summary of what remains genuinely unresolved

- **Unknown:** which `OSSetFontEncode` mode (section 1a) the shipped game actually selects at runtime — no game-logic call site is decompiled.
- **Unknown:** the exact function body of `SJIStoGSchar`/`GSmsgMakeGScharStr` — the SJIS→GSchar conversion is signature-proven (section 1b) but not body-proven.
- **Unknown:** how Yes/No option labels are represented (section 6) — literal embedded text, hardcoded engine strings, or a control code not yet catalogued.
- **Unknown:** which live address (if any) holds the currently-highlighted Yes/No choice index — a new discovery target, not yet attempted.
- **Unknown, and out of scope for this audit per instructions:** everything about XG specifically — every citation above is vanilla XD/Colosseum US, unverified against the user's actual XG image, exactly as flagged throughout `ARCHITECTURE_CODEMAP.md` and `UNKNOWNS_AND_BLOCKERS.md`.
