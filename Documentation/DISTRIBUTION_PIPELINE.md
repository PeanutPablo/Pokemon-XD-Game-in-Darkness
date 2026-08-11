# DISTRIBUTION_PIPELINE.md

Audit of `pokemon-ngc-rando` (C#/.NET 8, GPLv2) and `pokemon_fsys_tool` (C++, MIT) for disc/packaging pipeline
capability, followed by a design (not implementation) for a future accessibility-installer flow. Investigation
date: 2026-07-24. Citation convention follows [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md): every claim is
**Confirmed** (read directly in code), **Inferred** (reasoned from confirmed code but not executed/tested here),
or **Unknown**, with `file:line` citations into
`Research/ThirdParty/pokemon-ngc-rando/` and `Research/ThirdParty/pokemon_fsys_tool/`.

## Part 1 — Capability audit

### 1. Disc-format detection

**pokemon-ngc-rando:** `ISOExtractor.ExtractISO()` reads two raw bytes straight from the start of the file — no
magic-number/header-signature check of any kind. It seeks to offset 0, reads a `ushort` at offset 1 as the "game"
value and the next byte as "region" (`Common/Utility/Files/ISOExtractor.cs:39-41`). If that ushort doesn't match
one of the two known values it throws `"Unsupported game!"` (`ISOExtractor.cs:46-54`); if the region byte doesn't
match one of three known values it throws `"Unknown region!"` (`ISOExtractor.cs:56-65`). **Confirmed.** There is
no ISO/GameCube-header validation (no check of the six-character game ID, no disc magic word at 0x1C, no size
sanity check) — it is entirely dependent on two bytes at a fixed offset happening to be plausible. A malformed or
truncated file that happens to have byte 1-2 = `0x5858` ("XD") and byte 3 = `0x45` ("US") would pass this check.
**Inferred** (absence of any other validation confirmed by reading the whole method).

**pokemon_fsys_tool:** Has no disc-level logic at all — it operates only on standalone `.fsys` files, never on a
GameCube ISO. **Confirmed** (no ISO/disc code anywhere in `pokemon_fsys_tool.cpp`).

### 2. Region/version validation, game ID checking

Region/game validation is exactly the two-byte switch described above — `Region` enum values are `US = 0x45,
Europe = 0x50, Japan = 0x4A` and `Game` enum values are `XD = 0x5858, Colosseum = 0x4336`
(`Common/Contracts/Metadata.cs:7-18`). **Confirmed.** There is **no revision/version check** anywhere in the
repo — no disc-hash comparison, no build-date/version-string check, no six-character game-ID string comparison
(e.g. `GXXE01`). A `grep` across the whole repo for hash/checksum logic (`SHA1`, `SHA256`, `MD5`, `Checksum`)
returned zero matches outside of unrelated identifier substrings (`Hash` appears only in `.gitignore` and in
unrelated file/dictionary code such as `FSTFileEntry`/`FileStreamExtensions` `GetHashCode`-style calls, not disc
verification). **Confirmed by absence.** This means the tool has no way to distinguish an unmodified retail
GXXE01 disc from a XG-hacked GXXE01-labeled disc, or from a different disc revision that happens to still carry
region byte `0x45` and game bytes `0x5858`/`0x4336` — it will attempt to parse anything that clears that
two-byte gate.

### 3. File extraction — formats/containers

Confirmed extractable container/file types, read directly from `Common/Contracts/FileTypes.cs:9-50`: `RDAT, DAT,
CCD, SAMP, MSG, FNT, SCD, DATS, GTX, GPT1, CAM, REL, PKX, WZX, ISD, ISH, THH, THD, GSW, ATX, BIN`, plus the
container-level types `FSYS, THP, TPL, TEX0, XDS, TOC, DOL, ISO`. The pipeline is ISO → `FST`/`TOC` (file table) →
per-file `FSys` archives → individual typed entries via `FSysFileEntry.ExtractFromFSys`
(`Common/Utility/Files/FSysExtractor.cs:11-35`), with format-specific post-processing for textures (PNG export),
`PKX` (battle-model → `.dat` extraction), `SCD` (script data), and `THH`/`THD` (THP movie reassembly)
(`FSysExtractor.cs:37-70`). **Confirmed** this is a real, working typed-extraction pipeline, not a raw byte dump.

### 4. FSYS extraction specifically

Both tools implement the **same FSYS format independently** (two separate confirmed implementations, useful for
cross-validation):

- **Compression scheme:** classic LZSS (Haruhiko Okumura's 1989 public-domain reference algorithm, both files
  literally credit it in comments) — window size 4096 bytes (`N=4096`), match length up to 18 bytes (`F=18`),
  match threshold 2. Confirmed identically in `pokemon_fsys_tool.cpp:19-24` (`#define N 4096` / `F 18` /
  `THRESHOLD 2`) and in `Common/Utility/Files/LZSSEncoder.cs:26-30` (`EI=12` → `N=1<<12=4096`, `EncodedF=18`,
  `P=2`). Compressed-stream magic is ASCII `'LZSS'` as the first 4 bytes, with uncompressed size, compressed
  size, and an unused/PBR-only field following (`pokemon_fsys_tool.cpp:345-348`,
  `Common/Utility/Files/LZSSEncoder.cs:33-36`).
- **Archive layout:** magic `'FSYS'`, then `version, archive_id, num_files, flags, unk, ofs_table_ofs,
  data_start_ofs, fsys_size` (36-byte header, `pokemon_fsys_tool.cpp:26-36`). An offset table points to a file-index
  list, a string table (names, and optionally overridden filenames if the `FSYS_ENABLE_OVERRIDE` flag `0x1` is
  set), and per-file entries (`id, offset, size, flags, unk, compressed_size, unk2, filename_ofs, type,
  name_ofs`, `pokemon_fsys_tool.cpp:44-55`). The compressed-flag bit is `0x80000000`
  (`pokemon_fsys_tool.cpp:17`). Two archive versions exist: v1 (type IDs capped at 19, 0x50-byte file-entry
  records) and v2 (types up to 26, 0x70-byte records, gated by `version >= 0x200`)
  (`pokemon_fsys_tool.cpp:110-126,486`). **Confirmed**, and independently corroborated by the C# side reading a
  file table via `FSTFileEntry`/`FSys` constructor (`Common/Utility/Files/FSys.cs:130-136`).
- Both tools can pack (rebuild) an FSYS from loose files as well as unpack — `pokemon_fsys_tool` via
  `PackFSYS`/`UnpackFSYS` driven by a companion JSON manifest (`pokemon_fsys_tool.cpp:691-697,863-867`); the C#
  side via `entry.Encode(detailHeader.IsCompressed)` during `RepackISO` (`Common/Utility/Files/FSys.cs:289`,
  see §5 below). **Confirmed.**

### 5. File replacement / rebuilding a modified image

**Confirmed, real, and non-trivial.** `ISOExtractor.RepackISO(ISO iso, string savePath)`
(`Common/Utility/Files/ISOExtractor.cs:87-174`) writes a brand-new ISO: it copies the boot/BI2/apploader region
verbatim, re-encodes and writes the DOL, then walks the reordered FST, and for every file re-writes either the
modified in-memory `FSys` (`fsys.Encode()`) or copies the original bytes from the source ISO for untouched files
(`ISOExtractor.cs:126-152`). It handles size drift when a repacked FSYS grows or shrinks relative to the
original, shifting subsequent file offsets accordingly (`ISOExtractor.cs:133-147`). This is a genuine
selective-rebuild pipeline — it reuses unmodified data and only re-encodes touched containers.

Separately, `LZSSEncoder.Encode`/`Decode` (`Common/Utility/Files/LZSSEncoder.cs:122-236,238-312`) implement an
atomic-swap pattern for standalone file compression: write to a sibling `<name>.bak` temp file, then
`File.Delete(filename); File.Move(outputFilename, filename)` (`LZSSEncoder.cs:225-232`, repeated at
`:303-309`). This protects against a *half-written single file* if the process is interrupted mid-write, but it
is **not** a backup of the user's original disc image — the original ISO itself is never copied or protected
before `RepackISO` writes the new file (note `RepackISO` always writes to a **new/different** `savePath`, so the
source ISO is not overwritten in place, but nothing stops a caller from passing the same path).

**pokemon_fsys_tool** has no rebuild-into-ISO capability — it only packs/unpacks a standalone `.fsys` file, never
touches a disc image.

### 6. Hash verification

**None, in either tool, at any stage.** Confirmed by direct `grep` across both repos for `SHA1/SHA256/MD5/Hash`
— no disc-image hash is computed or compared before extraction, no output-image hash is computed or compared
after rebuild, and no per-file hash (e.g. to confirm a repacked FSYS matches expectations) exists anywhere in
either codebase. This is the single largest gap relative to the installer design in Part 2 below — see the
"biggest gap" summary.

### 7. Backup behavior

Confirmed as described in §5: the only backup-like behavior is the `.bak`-then-swap pattern inside
`LZSSEncoder`, scoped to a single file being (de)compressed in place, not the source disc. There is no
project-level "copy the original before touching it" step anywhere in `ISOExtractor`, `MainForm.cs`, or
`Randomizer.cs`. `MainForm.randomizerButton_Click` (`Randomizer/MainForm.cs:230-241`) always prompts the user
for a **save-as** path via `saveISODialog`, which functionally protects the source file from being clobbered by
the GUI flow specifically (the user cannot pick "overwrite input" through that dialog unless they explicitly
type the same filename) — but this is a GUI convenience, not an engineered backup/restore mechanism, and nothing
in `ISOExtractor.RepackISO` itself would stop an in-place overwrite if called directly (e.g. from a script or a
future CLI).

### 8. Failure handling

Confirmed patterns, both narrow and blunt:

- `OpenFile()` in the GUI wraps ISO loading in a bare `try { ... } catch { MessageBox.Show("Game not
  recognized!"); ...; return false; }` (`Randomizer/MainForm.cs:165-222`) — any exception of any kind (bad file,
  I/O error, permission error, corrupt zip) collapses to the same generic message, with no differentiation and
  no logged exception detail.
- `ISOExtractor.ExtractISO()` throws plain `Exception` with a string message for unrecognized game/region
  (`ISOExtractor.cs:53,64`) — not a typed/custom exception, so a caller cannot distinguish "wrong game" from
  "wrong region" programmatically without string-matching.
- `pokemon_fsys_tool.cpp` fails hard and immediately on any I/O or parse problem via bare `exit(1)` calls after a
  `std::cout` message (e.g. `pokemon_fsys_tool.cpp:203-204, 417-419, 427-430, 442-445` and others) — no
  exception/recovery mechanism, no partial-output cleanup (a failed unpack could leave a partially-written
  output directory).
- Neither tool validates FSYS/LZSS structural integrity beyond the two magic-number checks (`'FSYS'` at
  `pokemon_fsys_tool.cpp:816-819`, `'LZSS'` at `pokemon_fsys_tool.cpp:729-732`) — sizes, offsets, and entry
  counts read from a corrupt file are trusted as-is and used directly for buffer sizing/seeking
  (`ReadFSYSFile`/`DecodeLZSS`, `pokemon_fsys_tool.cpp:721-793`), which is a real crash/OOB-read risk on a
  corrupt or adversarial input file — relevant given this project would eventually process user-obtained ROM
  hack files. **Inferred** (risk assessment) from **Confirmed** code (no bounds checks read).

### 9. Test coverage (`RandomizerTests/`)

**Confirmed**, read directly rather than assumed from the directory listing: `RandomizerTests` is an NUnit
project (`RandomizerTests.csproj`, `[Test]`/`[OneTimeSetUp]`/`[SetUp]` attributes throughout) covering
`Items/ItemTests.cs` and `Trainers/TrainerTests.cs`, backed by `ReferenceData/JSON/items.json` and
`trainers.json` fixtures.

- **Setup dependency:** `BaseTestSetup.Setup()` (`RandomizerTests/BaseTestSetup.cs:23-42`) hardcodes
  `TestConfiguration.TestRomPath = "H:\\ISO\\Gamecube\\Pokemon XD - Gale of Darkness.iso"` (line 26) and loads a
  real ISO from that literal path via `ISOExtractor`/`ExtractISO()`. **This means the test suite is not
  runnable without a specific developer's local, non-redistributed copy of the retail ROM at a hardcoded Windows
  path** — it cannot run in CI or on a clean checkout, and it is not parameterized via config/environment
  variable. This is a notable contrast to `xd-decomp`, whose CI pipeline supplies its own disc image inside a
  container (see `REPOSITORY_AUDIT.md:62`).
- **What the tests actually assert:** they are property/invariant checks run across many random seeds, not
  golden-output snapshot tests. `Helpers.RerunTimes = 100` (`RandomizerTests/Helpers.cs:12`) drives loops like
  `for (int i = 0; i < Helpers.RerunTimes; i++) { Shuffler.Shuffle(...); Assert...(...); }` in both
  `ItemTests.cs` (e.g. `TestOverworldBanBadItems`, `TestOverworldBanBattleCds`,
  `Items/ItemTests.cs:37-59,61-88`) and `TrainerTests.cs` (e.g. `TestNoShadowDuplicates`,
  `Trainers/TrainerTests.cs:14-30`) — i.e. "run the randomizer 100 times with a given setting and check an
  invariant holds every time" (no banned items appear, no duplicate shadow Pokémon, etc.), not "does output byte
  X match expected byte Y." Some tests are explicit placeholders that always pass without exercising real logic:
  `TestOverworldChangeTreasureModel` and `TestMartsSellStones` both open with `Assert.Pass("Not implemented")`
  before any shuffle call (`Items/ItemTests.cs:92,286`) — confirmed dead/stub tests, not full coverage.
- **No test anywhere exercises `RepackISO`, hash verification, or disc-format detection failure paths** —
  coverage is entirely of the in-memory randomization logic (item/trainer/move tables), not of the ISO
  read/write pipeline that would matter most for an installer.

## Part 2 — Designed installer flow (design only, not implemented)

Ten-step flow as specified. For each step: what it must do, which existing tool/library is realistically
reusable **as an external process/tool call**, what has to be written from scratch, and the license
consequence of any GPLv2 reuse.

| # | Step | Reusable from `pokemon-ngc-rando`? | Reusable from `pokemon_fsys_tool`? | From scratch | License note |
|---|---|---|---|---|---|
| 1 | Require user's own clean US XD image | No — the repo never validates disc authenticity beyond 2 bytes (§1-2). Its file-picker UX pattern (`openISODialog`, `MainForm.cs:56-95`) is a reasonable UX reference only. | No | Yes — a real header/game-ID check (parse the actual 6-char GameCube game ID + disc magic word, not 2 bytes) | — |
| 2 | Verify exact input hash | No — confirmed absent entirely (§6) | No | Yes, entirely — compute SHA-256 (or similar) of the user-supplied ISO and compare against a pinned known-good hash for retail US GXXE01, the same pattern `xd-decomp` already uses successfully for its *output* `main.dol` (`config/GXXE01/build.sha1`, see `REPOSITORY_AUDIT.md:22,77`) — that pattern is a good model to copy conceptually (not code) | — |
| 3 | Require separately obtained legitimate XG patch | No — neither tool has any concept of "patch," "hack," or "XG" | No | Yes — patch-application format is Unknown until an XG patch file is actually examined (see `UNKNOWNS_AND_BLOCKERS.md` for what's still unverified about XG) | — |
| 4 | Create a copy | No engineered backup step exists in either tool (§7) — must not model the flow on it | No | Yes — trivial file copy, but must be an explicit, verified step (confirm copy succeeded, e.g. size/hash match) before step 5 touches anything | — |
| 5 | Apply XG | Format-Unknown until an actual XG patch is inspected | No | Yes | — |
| 6 | Verify exact supported XG revision | No — no revision-checking concept exists in either tool (§2) | No | Yes — same hashing approach as step 2, applied post-patch | — |
| 7 | Generate local accessibility indexes | **Partially reusable, as an external tool call, not copied code.** `ISOExtractor`/`FST`/`FSys`/`FSysExtractor` (§3-4) already parse the disc's file table and every typed container (text/`MSG`, scripts/`SCD`, etc.) — this is exactly the kind of structured read an "accessibility index" (e.g. a searchable map of in-game text, menu structure) would need. `pokemon_fsys_tool -u` can also dump a single FSYS to loose files + JSON manifest as a simpler, MIT-licensed alternative extraction path for this one step. | Yes, best fit of the two for this specific step (MIT, no license friction) | Yes — the actual "accessibility index" schema/generation logic itself | GPLv2 reuse of `pokemon-ngc-rando`'s extraction code specifically for this step requires the whole consuming program to be GPL-compatible (see License section below) — the MIT `pokemon_fsys_tool` avoids that problem for FSYS-only needs, but doesn't cover ISO/FST-level parsing |
| 8 | Never redistribute game data | No — orthogonal to both tools; this is a policy/process constraint on *this* project, not something either tool enforces or violates on its own (both operate on user-local files and don't upload/publish anything) | No | Yes — a design/process rule (e.g. installer never bundles the ISO/patch, never uploads extracted assets), not code | — |
| 9 | Install external companion | No — out of scope for both repos entirely | No | Yes | — |
| 10 | Provide restoration and diagnostic logs | No real precedent — closest analog is `Randomizer/Logger.cs`'s settings/run log (not inspected in depth here; not a restore mechanism) and the `.bak`-swap pattern in `LZSSEncoder` (§5, single-file scope only, not disc-level restore) | No | Yes — a real restore-to-backup-copy step (using the copy from step 4) plus a structured diagnostic log (what step failed, expected vs. actual hash, etc.) | — |

### License section — what GPLv2 reuse would actually require

`pokemon-ngc-rando` is licensed under **GPLv2** (confirmed: `Research/ThirdParty/pokemon-ngc-rando/LICENSE:1-7`).
GPLv2 is a copyleft license. Concretely, for this project:

- **Calling `pokemon-ngc-rando`'s compiled tool as a separate external process** (e.g. shelling out to a
  standalone CLI build of it, or the GUI exe, the way one might call `ffmpeg`) does **not** require the calling
  installer program to be GPL-licensed. Mere invocation of an unmodified external program over a process
  boundary is the standard way to use a GPL tool from a non-GPL project without license propagation. This is the
  only safe reuse path if the rest of this accessibility project is (or may become) under a different license.
- **Copying, adapting, or linking any of `pokemon-ngc-rando`'s source** (e.g. lifting `ISOExtractor.cs`,
  `FSys.cs`, `LZSSEncoder.cs` into this project's own codebase, even with modifications) would make the
  resulting combined work a "derivative work" under GPLv2 §2. That has two concrete, non-optional consequences:
  the combined program **must** itself be distributed under GPLv2 (or a GPLv2-compatible license) if it is
  distributed at all, and the **complete corresponding source code** of the combined work must be made available
  to anyone who receives the binary (GPLv2 §3). There is no "just credit the author" or "just add a notice"
  middle ground — GPLv2 is source-available-or-nothing for the derivative work as a whole, and it cannot be
  mixed into a proprietary/closed installer or a permissively-licensed (e.g. MIT) release without relicensing
  the whole combined program under GPLv2.
- **Practical recommendation for this project:** treat `pokemon-ngc-rando` strictly as an external tool to be
  invoked (step 7's FSYS/ISO reads, potentially step 2/6's hashing precedent), never as a source of copied code,
  unless this project is prepared to release its own installer's full source under GPLv2. `pokemon_fsys_tool`
  (MIT) has no such restriction — its code can be copied, modified, and relicensed freely, including into a
  closed or differently-licensed installer, provided the MIT copyright/license notice is retained
  (`Research/ThirdParty/pokemon_fsys_tool/LICENSE:1-21`).

### Biggest gap for the installer design

**Hash verification is completely absent from both tools, at every stage** (§6) — no input-ISO hash check, no
post-patch/pre-play verification, no output-integrity check of any kind. Every one of steps 2, 4, and 6 in the
requested installer flow depends on hashing that neither tool provides even a partial model for in code (only
`xd-decomp`'s unrelated build-verification hash, cited above, is a usable conceptual precedent elsewhere in this
project's own research). This has to be designed and written entirely from scratch, and it is the load-bearing
safety mechanism for the whole flow — every other step (never touching an unverified image, confirming XG
applied correctly, confirming the copy in step 4 actually succeeded) depends on it.
