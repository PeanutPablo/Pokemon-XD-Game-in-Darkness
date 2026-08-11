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

## Phase 0C — Menu-selection discovery

### `0x804FFCEF` / `0x804FFCEE`: Confirmed false candidate — stack-local scratch space, permanently rejected

The blind-diff-scanning candidate identified earlier in this session (single byte at `0x804FFCEF`, mirrored at `0x804FFCEE` observed as always-zero) passed every *paused, single-step* test cleanly (`0 → 1 → 2 → 1 → 0`, symmetric, repeatable) but showed unexplained behavior under real continuous play: values changing without input, and a one-press lag on reaching certain options. A GDB-stub write watchpoint (see "GDB remote-debugging investigation" below) resolved this definitively.

**Evidence:** a write watchpoint on `0x804FFCEF`, set immediately after boot and left active while emulation ran uninterrupted, captured **34 writes in approximately one second**, entirely during early boot before any menu existed. Every hit's stack pointer (`SP`/`r1`) sat within roughly ±0x407 bytes of the watch address (as close as `0xF`, as far as `0x407`, and in several cases the watch address was *below* the current `SP` entirely) — confirming the address is stack-relative, not a fixed global.

The 34 writer PCs, cross-referenced against `xd-decomp`'s symbol map (exact match or nearest-containing named `.text` function):

| PC | SP (r1) | Δ (watch − SP) | Containing function |
|---|---|---|---|
| `0x800DA3D0` | `0x804FFCC8` | `+0x27` | `__div2i` |
| `0x800AE388` (×2) | `0x804FF8E8` / `0x804FF8F8` | `+0x407` / `+0x3F7` | `OSDisableInterrupts` |
| `0x800E98B0` | `0x804FF938` | `+0x3B7` | `WriteUARTN` |
| `0x800AAA6C` | `0x804FFD38` | `-0x49` | (LR `0x800AA9E0`, unresolved) |
| `0x800E3254` | `0x804FF9B0` | `+0x33F` | `fwide` |
| `0x800E117C` | `0x804FFA10` | `+0x2DF` | `long2str` |
| `0x800DFBD0` | `0x804FFA10` | `+0x2DF` | `__pformatter` |
| `0x80005530` | `0x804FF9A8` | `+0x347` | (unresolved, near boot entry) |
| `0x80005498` (×2) | `0x804FFCE0` / `0x804FFCA0` | `+0xF` / `+0x4F` | (unresolved, near boot entry) |
| `0x800A841C` | `0x804FFCF0` | `-0x1` | (unresolved) |
| `0x800A8DE4` (×2) | `0x804FFCE0` | `+0xF` | `addfreeCellList` (`GSmemHeapDesc`, heap allocator) |
| `0x800AE3C0` | `0x804FF8C8` | `+0x427` | `OSRestoreInterrupts` |
| `0x802AF04C` (×2) | `0x804FFD20` | `-0x31` | `GSgfxVideoInit` |
| `0x800B1550` | `0x804FFCE0` | `+0xF` | `SelectThread` |
| `0x800AAC8C` (×3) | `0x804FFD30` / `0x804FFCD0` (×2) | `-0x41` / `+0x1F` (×2) | `DCFlushRange` |
| `0x800C66D0` | `0x804FFCF8` | `-0x9` | `GXInit` |
| `0x800C6D6C` | `0x804FFC58` | `+0x97` | (unresolved) |
| `0x800DA05C` | `0x804FFC80` | `+0x6F` | `__cvt_fp2unsigned` |
| `0x800E6458` | `0x804FFCC0` | `+0x2F` | `cos` |
| `0x802BDAB4` | `0x804FFCC0` | `+0x2F` | `GSgfx_GCReset` |
| `0x8000550C` | `0x804FFCE0` | `+0xF` | (unresolved, near boot entry) |
| `0x802ACA04` | `0x804FFC90` | `+0x5F` | `GSgfxPerfbarCPUEntry` |
| `0x802AF18C` | `0x804FFCE0` | `+0xF` | `_videoUpdateViewport` |
| `0x800DF39C` | `0x804FF970` | `+0x37F` | `__memrchr` |
| `0x800BCED0` | `0x804FFA70` | `+0x27F` | `__ARChecksize` |
| `0x800AADC4` | `0x804FFD30` | `-0x41` | `__LCEnable` |
| `0x802A65F4` | `0x804FFCB0` | `+0x3F` | `GSlogWrite` |
| `0x802B0178` | `0x804FFCF0` | `-0x1` | (unresolved — 34th hit, client exited before full capture) |

**Conclusion: Confirmed false candidate.** `0x804FFCEF` is stack-local scratch space, reused as an incidental local variable by dozens of completely unrelated subsystems — the OS scheduler, interrupt handling, cache flush, graphics/video init, the C runtime's math and string libraries, and the game's own debug logger (`GSlogWrite`) — none of which have anything to do with menu selection. **Why the earlier `0 → 1 → 2 → 1 → 0` paused-test sequence looked clean:** at each sparse, human-timed pause point, whichever function's stack frame happened to be active at that instant held a value that, by coincidence, matched the real selection index closely enough across a handful of samples to look like a stable signal. Under continuous execution the same address is rewritten dozens of times per second by unrelated code, which is exactly the "idle cycling" and lag behavior observed in live testing. **This address (and its `0x804FFCEE` mirror) is permanently rejected as a menu-selection candidate — do not reuse it, including against XG.**

### GDB remote-debugging investigation (Dolphin's built-in stub)

Since the user has no usable vision and no sighted assistant, Dolphin's GUI debugger (which would otherwise be the natural tool here) was ruled out entirely. Instead, Dolphin's built-in GDB Remote Serial Protocol stub (`Source/Core/Core/PowerPC/GDBStub.cpp`, compiled unconditionally into all builds including the Windows release) was used via a from-scratch, strictly read-only Python RSP client (`Companion/_phase0_scratch_gdb_watchpoint.py`).

**Enablement:** `Dolphin.ini` → `[General]` → `GDBPort = 55555` (was `-1`/absent, i.e. disabled, by default). Confirmed present in `Source/Core/Core/Config/MainSettings.cpp` as `Config::MAIN_GDB_PORT`.

**Safety measures taken, both confirmed in place before the stub was ever activated:**
- The stub binds `INADDR_ANY` (all interfaces) with no authentication — confirmed directly in `GDBStub.cpp` source. Since this can't be restricted via config (hardcoded), the user added a Windows Firewall inbound block rule for TCP port 55555 themselves (`New-NetFirewallRule -DisplayName "Block Dolphin GDBStub external access" -Direction Inbound -Protocol TCP -LocalPort 55555 -Action Block`) — verified active via `Get-NetFirewallRule` before use. Loopback (127.0.0.1) traffic is unaffected by Windows Firewall inbound rules, so this didn't block the client itself.
- The client's outgoing packet set is a strict allowlist: `? g p m Z0 z0 Z2 z2 c s D` only (extended from the original `Z2/z2`-only set to add execution breakpoints and single-step once the investigation moved from watchpoints to symbol-first execution tracing — both are execution-control, not memory/register writes). No function in the client file sends `M`, `X`, `G`, or `P` (memory-write/register-write) packets, nor any `qRcmd` monitor command — verified by code review, not just by convention. The stub itself *does* implement writes (nothing prevents another client from using them), which is exactly why the network-exposure mitigation above mattered.
- Confirmed via source inspection: enabling the stub does not require a specific CPU core: memory watchpoints use the same `TMemCheck` mechanism as Dolphin's GUI memory-breakpoint feature, which is JIT-compatible. The current session runs `JIT64 SC` (single core), matching community debugging best-practice, unchanged.
- Confirmed empirically: the installed Dolphin was not listening on any port before the change; after the `Dolphin.ini` edit and a restart, it was confirmed listening on `0.0.0.0:55555` via `Get-NetTCPConnection`.
- A further, unresearched-but-observed behavior: the GDB stub boots the CPU **paused** (`CPUSetInitialExecutionState(system, true)` in `Source/Core/Core/Core.cpp`) whenever `GDBPort > 0` — the client's first `continue` is what starts emulation running at all.

The next live step (in progress as of this document) uses the same client, extended with execution-breakpoint support (`Z0`/`z0`, still read-only, plus `s` for single-step) to breakpoint `menuTitleGetSelect` and related symbolized functions directly, per the symbol-first strategy in the section below — rather than continuing to blind-scan.

### Symbol-first strategy: known menu-related symbols (from `xd-decomp`, addresses and sizes confirmed via `config/GXXE01/symbols.txt`)

| Symbol | Address | Size | Notes |
|---|---|---|---|
| `menuTitleGetSelect` | `0x800A3194` | `0x18` (6 instructions) | Precisely disassembled and live-tested — **confirmed never called** during boot/title/navigation (see below) |
| `menuTitleSetSelect` | `0x800A31AC` | `0x18` (6 instructions) | Same instruction pattern as the getter; not separately execution-breakpoint-tested (the array it targets was tested directly via write watchpoint instead — see below) |
| `menuTitle` | `0x800A35FC` | `0x330` | Main title-screen function |
| `menuFightMainCtrl` | `0x8001D088` | `0x2FC` | Main battle-command-menu controller |
| `menuFightOpenTop` | `0x8001E3E0` | `0x404` | Opens the battle command menu |
| `menuFightSetStatus` | `0x8001EBB4` | `0x8` (2 instructions) | Trivial setter |
| `menuFightGetStatus` | `0x8001EBBC` | `0x8` (2 instructions) | Trivial getter |
| `menuTopSelectCtrl` | `0x8002F330` | `0xA4` | Overworld system-menu cursor controller |
| `menuTopSetInitCursor` | `0x80030324` | `0x8` | |
| `_menuTopSelectCursor` | `0x804EA798` | `0x4` (data, `.sbss`) | **A real static global**, not stack-relative — a structurally stronger candidate than the rejected address, not yet live-tested |

**Precise disassembly of `menuTitleGetSelect`/`menuTitleSetSelect` (0x800A3194/0x800A31AC), extracted directly from the verified `build/GXXE01/main.elf` via a purpose-built PowerPC disassembler (`Companion/_phase0_scratch_disasm.py`), then confirmed live:**
```
menuTitleGetSelect(index):                    menuTitleSetSelect(index, value):
  lis    r4, 0x8044                             lis    r5, 0x8044
  rlwinm r0, r3, 1, 0, 30   # r0 = index*2       rlwinm r0, r3, 1, 0, 30   # r0 = index*2
  addi   r3, r4, -0x2D58    # r3 = _menuTitleWork addi   r3, r5, -0x2D58    # r3 = _menuTitleWork
  add    r3, r3, r0         # r3 += index*2       add    r3, r3, r0         # r3 += index*2
  lha    r3, 0x40(r3)       # signed 16-bit load  sth    r4, 0x40(r3)       # 16-bit store
  blr                                            blr
```
Both functions take an **index parameter in r3** — this is not a single "current selection" scalar, it's an accessor for a **4-entry array** at `_menuTitleWork + 0x40` (base `0x8043D2E8`), each slot 2 bytes (`index*2` stride), covering `0x8043D2E8`–`0x8043D2EF` for indices 0–3.

### Menu-selection candidates tested and rejected for the title screen

| # | Address | Hypothesis | Live result |
|---|---|---|---|
| 2 | `0x804EA798` (`_menuTopSelectCursor`) | Known "Top"-menu (overworld system menu) cursor global, tested as a title-screen candidate | One write to `0` on screen load (context init); **no write on cursor movement** across multiple confirmed presses |
| 3 | `0x8043D2E8` (single 16-bit slot, index 0 only) | Naive read of `menuTitleGetSelect`'s target before the index parameter was understood | `0000→FFFF→0000` during screen load only; **no write on cursor movement** |
| 4 | `0x8043D2E8`–`0x8043D2EF` (full 4-slot array, all indices) | Corrected hypothesis after precise disassembly | Initialized once, during load, to `[0]=0x0000 [1]=0x0001 [2]=0x0002 [3]=0x0003` — reads as an identity/lookup table, not a per-item highlight flag; **no write on cursor movement** |

**CORRECTION (superseded by the sanity check below): the earlier claim that `menuTitleGetSelect` was "confirmed never called" via execution breakpoint is retracted.** An execution breakpoint (`Z0`) was set on `0x800A3194` through boot/title/a cursor press and never fired — but a later sanity check (see "Execution breakpoints (Z0) are unreliable" below) proved `Z0` does not fire reliably at all in this Dolphin/GDBStub configuration, even on `PADRead`, which unconditionally executes every frame. The non-call of `menuTitleGetSelect` is therefore **Unconfirmed**, not a real negative result — it may or may not be called; the mechanism used to test it was broken.

**Net result: the title-screen investigation is inconclusive after four independently-tested hypotheses, all methodically ruled out with live evidence, not abandoned by assumption.** Per the user's direction, the investigation is pausing on the title screen (without another broad blind scan for now) and moving to the battle command menu instead, using the same symbol-first execution-breakpoint methodology starting from `menuFightMainCtrl` (`0x8001D088`). See "Battle command menu investigation" below for that work as it proceeds.

## Battle command menu investigation (in progress)

### Execution breakpoints (`Z0`) are unreliable in this Dolphin/GDBStub configuration — critical methodology finding

An initial symbol-first pass set `Z0` execution breakpoints on 15 `menuFight*` symbols simultaneously (`menuFightMainCtrl`, `menuFightOpenTop`, `menuFightCloseTop`, `menuFightSetStatus`, `menuFightGetStatus`, `menuFightDrawCmdMsg`, `menuFightDrawNew`, `menuFightStatusCtrl`, `menuFightCtrlTimer`, `menuFightDrawWaza`, `menuFightDrawType`, `menuFightDrawPP`, `menuFightOpenTarget`, `menuFightOpenPokemon`, `menuFightOpenWaza`) across two full attempts, including confirmed real navigation (a Down press at the actual battle menu). **Zero hits on any of the 15 breakpoints in either attempt.**

Before treating that as a real negative result, a sanity check was run: a single `Z0` breakpoint on `PADRead` (`0x800BB348`, real decompiled SDK source in `xd-decomp`, `src/dolphin/pad/Pad.c`), which **must** execute every single frame for the game to read controller input at all. **It did not fire within 10 seconds either.**

**Conclusion: `Z0`/`z0` execution breakpoints do not work reliably via Dolphin's GDB stub in this setup.** Root cause not diagnosed (could be a Dolphin/GDBStub limitation under JIT64, a request-format issue, or something else). **Every execution-breakpoint-based negative result obtained this session — including the "menuTitleGetSelect confirmed never called" claim above and all 15 `menuFight*` non-hits — is retracted to Unconfirmed, not treated as real evidence.** `Z2`/`z2` write watchpoints, by contrast, use Dolphin's separate, GUI-shared `TMemCheck` mechanism and have proven reliable throughout (the `0x804FFCEF` stack-scratch rejection above was obtained this way and remains a valid negative result). **Going forward, all live battle-menu testing uses `Z2` write watchpoints exclusively; `Z0` is not used again pending a fix.**

### `menuFightStatus` (`0x804EA728`, `.sbss`, confirmed real static global, size `0x4`): tested and rejected

Live write watchpoint (`Z2`), left armed for the full 10-minute connection window while the user pressed Down, then Right, then Up at the battle command menu (confirmed real input, not idle time). **Zero writes across all three presses.** This is a valid negative result — obtained via the proven-reliable `Z2` mechanism, not the broken `Z0` one. `menuFightStatus` is not the live per-press cursor field.

### Offline save-state diffing — a new, complementary read-only technique

The user made three Dolphin save states at consecutive points in a real navigation sequence (`save.sav` baseline → 1× Down → 1× Down+Right → 1× Down+Right+Up), each a full snapshot of emulated memory + CPU state frozen to disk. This enabled **fully offline, static diffing** with no live emulator connection at all — a useful complement to live watchpoints since it surfaces every changed byte in one pass instead of one candidate at a time.

**Format reverse-engineered directly from Dolphin's own upstream source** (`Source/Core/Core/State.h`/`.cpp`, fetched from `dolphin-emu/dolphin` for this purpose, `STATE_VERSION=192`): `StateHeaderLegacy` (24B: `game_id[6]`, `reserved1[2]`, `lzo_size` u32 @8 — 0 for the modern format, `reserved2[4]`, `time` double @16) → `StateHeaderVersion` (8B: `version_cookie` u32, `version_string_length` u32) → version string → `StateExtendedBaseHeader` (16B: `header_version` u16, `compression_type` u16 [0=none, 1=LZ4], `payload_offset` u32 @4, `uncompressed_size` u64 @8) → payload: LZ4-compressed in `[int32 len][data]` chunks (single chunk in practice, since `LZ4_MAX_INPUT_SIZE` vastly exceeds these ~60MB payloads).

The decompressed payload is Dolphin's full `PointerWrap`-serialized machine state (Wii flag, Movie, video backend string, CoreTiming, all of `HW::DoState`, PowerPC, etc.) — rather than reimplementing that entire serialization order to locate the 24MB MEM1 (GameCube RAM) array precisely, an **anchor-byte search** was used instead: two long (512-byte), independently-chosen runs of known-static code were extracted from the verified `main.elf` (`PADRead` at `0x800BB348`, `menuFightMainCtrl` at `0x8001D088`), searched for in the decompressed buffer, and cross-checked against each other — both located the same MEM1 base offset in every one of the 4 save states tested (offsets varied slightly file-to-file, ~0xD1E4F0–0xD1E544, due to minor preceding-section size differences, confirming the anchor approach was necessary rather than assuming a fixed offset). Implementation: `Companion/_phase0_scratch_savestate_diff.py` (parse+decompress+locate+extract) and `Companion/_phase0_scratch_savestate_mem1_diff.py` / `_phase0_scratch_savestate_smallval_filter.py` (diff logic). Extracted raw MEM1 dumps are gitignored (`Companion/logs/`) — they contain substantial copyrighted game data.

A raw full-MEM1 diff between consecutive states produced hundreds of thousands of changed words per transition — overwhelmingly noise from particle/physics/animation systems, floating-point transforms, and the live CPU stack (which differs on every save purely from differing call depth, the same false-positive class as the original `0x804FFCEF` rejection). Filtering to addresses holding a **small, plausible index value (≤0x20) in all four snapshots, that changed on at least one transition**, cut this to 409 candidates — still requiring symbol cross-reference (below) to separate real leads from graphics-pipeline scratch (e.g. one early top candidate, `0x804197A4`, turned out to sit inside `tevdesc$1248`, a GX texture-environment descriptor reused by every textured draw call — ruled out).

### Named-symbol candidates identified this way, cross-referenced against `config/GXXE01/symbols.txt`

| Symbol | Address | Section | Values across base→Down→+Right→+Up | Verdict |
|---|---|---|---|---|
| `gSelected_row` | `0x804EA698` | `.sbss` | `0,0,0,0` (unchanged) | **Rejected for this menu** — likely used by a different menu screen |
| `gSelected_column` | `0x804EA69C` | `.sbss` | `0,0,0,0` (unchanged) | **Rejected for this menu** — likely used by a different menu screen |
| `gSelectedMenu_column` | `0x804EA6A0` | `.sbss` | `0,0,0,0` (unchanged) | **Rejected for this menu** |
| `_menuToolSelect` | `0x804EA680` | `.sbss` | `0,0,0,0` (unchanged) | **Rejected for this menu** |
| `_menuTopSelectCursor` | `0x804EA798` | `.sbss` | `0,0,0,0` (unchanged) | Consistent with the title-screen finding above — reused overworld-menu global, not this menu |
| **`gLastSelectedIndex`** | **`0x804E84CC`** | **`.sdata`** | **`1 → 1 → 0 → 0`** (changed exactly on the Right press; unchanged on Down and Up) | **Strongest lead — live-tested below, partially confirmed** |

### `gLastSelectedIndex` — REJECTED (fully confirmed via controlled live re-test)

**Client bug fixed first.** The crash that paused this investigation was root-caused, not just patched around: `RSPClient.read_memory()` treated any response starting with the character `"E"` as a GDB error packet. A real GDB RSP error reply is always exactly `E` + 2 hex digits (3 characters total) — but a successful memory-read response is `length*2` hex characters, which can legitimately start with `"E"` too (e.g. a byte value `0xE0`-`0xEF`). The disassembly-window read that crashed had received a valid 32-byte dump that happened to start with byte `0xE0`, and the client misidentified it as an error. Fixed in `Companion/_phase0_scratch_gdb_watchpoint.py`'s `read_memory()` by additionally requiring `len(resp) <= 3` before treating a leading `"E"` as an error — no other code in the file was touched, per instruction.

**Static identification of the original crash-hit's writer context, done before any live re-test:** `PC=0x800B35E4` sits at the exact entry of `PSVECScale` (`.text:0x800B35E4`, size `0x1C`) — a generic paired-single vector-math SDK utility, uninformative by itself. But `LR=0x801A6070` (the return address, i.e. the actual caller) lands inside `_battleCameraStartRandom__FP13ModelSequence` (`.text:0x801A5CD0`, size `0x11D8`) — a **battle camera** function. This was the first concrete evidence pointing away from "menu selection" and toward "battle camera," predating the live re-test below.

**Controlled live re-test:** Dolphin was relaunched from the user's original baseline save state (clean starting position, no prior presses this session) and a `Z2` write watchpoint was armed on `0x804E84CC`. Initial value: `1` (recorded as the "initial selection" baseline). The user then performed, one at a time with explicit confirmation between each: Down, Up, Right, Left, and a genuine ~60-second no-input idle period. **15 watchpoint hits were captured in total, spanning the entire sequence including the idle period.** Every hit's `PC` and/or `LR` was resolved against `config/GXXE01/symbols.txt`:

| Hit | Time | Old→New | PC function | LR (caller) function |
|---|---|---|---|---|
| 1 (Down) | 15:28:38 | 1→0 | `battleGridResetModelVisibilityFlags` | `_battleCameraStartRandom__FP13ModelSequence` |
| 2 | 15:29:06 | 0→1 | `update__23CameraAnimation<5GSvec>Ff` | `cameraUpdate` |
| 3 | 15:29:34 | 1→0 | `cameraSetFov` | `cameraSetFov` (recursive/loop-internal) |
| 4 | 15:29:57 | 0→1 | `floorDataBiosGetPtr` | `exec__16FloorModuleEntryF10FloorStateUi14FloorEnterMode` |
| 5 | 15:30:25 | 1→0 | `getTopOfStack__14FloorStackListFv` | `getCurrentStack__14FloorStackListFv` |
| 6 (Right) | 15:30:53 | 0→1 | `cameraSetType` | `_battleCameraStartRandom__FP13ModelSequence` |
| 7 | 15:31:19 | 1→0 | `getCurrentFloorID__12FloorManagerFv` | `floorGetCurrent` |
| 8 | 15:31:46 | 0→1 | `_wazaSequenceCameraCalculateParams__FP13ModelSequenceiP24wazaSequenceCameraParams` | (same function, internal) |
| 9 (Left) | 15:32:15 | 1→0 | `stop__23CameraAnimation<5GSvec>Fv` | `cameraMoveStop` |
| 10 | 15:32:52 | 0→1 | `_partFindJObjCB__FP9_HSD_JObjPPvi` | `HSD_JObjWalkTree0` |
| 11 (idle) | 15:33:30 | 1→0 | `_battleCameraStartRandom__FP13ModelSequence` (internal) | (same function) |
| 12 (idle) | 15:33:59 | 0→1 | `cameraSetFov` | `cameraSetFov` (recursive/loop-internal) |
| 13 (idle) | 15:34:23 | 1→0 | `PSVECScale` | `_battleCameraStartRandom__FP13ModelSequence` (identical to the original interrupted-session hit) |
| 14 (idle) | 15:34:41 | 0→1 | `__ieee754_atan2` | `atan2` |
| 15 (idle) | 15:35:05 | 1→0 | `cameraSetFov` | `cameraMoveStop` (via `_battleCameraStartRandom`) |

**Every single one of 15 independent hits traces to battle-camera-system code** (`cameraUpdate`/`cameraSetFov`/`cameraSetType`/`cameraMoveStop`/`_battleCameraStartRandom`/`_wazaSequenceCameraCalculateParams`/`CameraAnimation<GSvec>`), camera-target-lookup math (`atan2`, `HSD_JObjWalkTree0`, `_partFindJObjCB`), or battle-floor-position bookkeeping (`floorGetCurrent`/`FloorStackList`/`FloorManager`) that these camera routines consult to pick a target. **Zero hits trace to any menu, input, or command-selection code.**

**Idle-stability test result: failed outright.** Hits fired at a near-regular ~20–30 second cadence (15:29:06, :34, :57, 15:30:25, :53, 15:31:19, :46, 15:32:15, :52, 15:33:30, :59, 15:34:23, :41, 15:35:05) continuously through Right, Left, and a genuine, confirmed 60-second period with **zero controller input at all**. The toggling never stopped or paused for the no-input window — it is a free-running timer-driven cycle (almost certainly the battle-idle "randomly vary the camera angle every so often" system calling `_battleCameraStartRandom` on a fixed interval), completely uncorrelated with any specific button press.

**CLASSIFICATION: REJECTED.** `gLastSelectedIndex` is not a battle-command selection tracker. It is a battle-camera state variable (most likely "last selected camera angle/model-sequence index," consistent with its generic name) that changes on its own on a periodic timer, independent of player input. It fails both applicable rejection criteria simultaneously: camera-related (15/15 hits) and unstable (changes with zero input). The apparent correlation with the Right press in the original offline save-state diff (§ above, "1 → 1 → 0 → 0") is now understood to have been **coincidental timing** — the periodic camera timer happened to tick between two of those save-state captures, not a response to the Right input itself.

**No further menu-address search follows from this result, per instruction.** The next investigation step (dialogue: `_MsgID`/`msgctrlMsgID` at `0x804EB284`) is designed and ready but explicitly gated on the user's approval before starting.

## Phase 0D — Read-only speech proof: CONFIRMED (2026-07-24)

Deliberately narrow scope, per instruction: exactly one field, no generalization to other message fields yet.

**Implementation:** `Companion/phase0d_nvda_wazakouka_poc.py`. Polls `0x804AF560` (the confirmed Wazakouka/effectiveness message-ID field from the tracing above) via `dolphin_memory_engine.read_word()` every 0.05s — no GDB stub, no watchpoints, no pausing, full normal game speed. On a `0 -> nonzero` transition, looks the value up in the already-extracted, gitignored local table (`Companion/_dialogue_extraction/fight_common_strings.json`) and speaks the resolved text via `cytolk.tolk.speak(text, interrupt=True)` (the same load/detect/speak/unload sequence already confirmed working in `Companion/test_speech.py`). Re-arms only after observing the field return to exactly `0`, deduplicating repeated polls of the same still-nonzero event.

**Read-only, by construction:** the only `dolphin_memory_engine` calls anywhere in the script are `hook()`, `is_hooked()`, `get_status()`, `read_word()`, and `un_hook()` — no `write_*` function is imported or called anywhere in the file.

**Live test result — full success, logged verbatim:**
```
[18:06:16.910] Screen reader detected: NVDA
[18:06:16.910] Polling every 0.05s. Waiting for the confirmed event...
[18:06:41.640] EVENT: old=0 new=20256 (0x4F20)  resolved_text="It's super effective!"  spoken=True
[18:06:45.221]   field returned to 0 (was 20256, held for ~3584.2ms) -- re-armed
```

**Event tested:** Earthquake (Ground) on Metagross (Steel/Psychic) — the same confirmed super-effective matchup from the tracing session. NVDA spoke "It's super effective!" aloud, confirmed by the user.

**Field lifetime measurement (per instruction, in case polling ever misses a transient write):** the field stayed nonzero for **~3.58 seconds** before resetting to 0 — far longer than the 50ms poll interval, so there was no meaningful risk of missing this particular event. This lifetime is plausibly tied to how long the message text stays on-screen (a human-readable display duration), not a single-frame transient — but this has only been measured once and is not yet established as a general guarantee for all message types or timings (e.g. faster message chains during multi-hit moves are untested).

**Scope discipline maintained:** no memory writes anywhere in this implementation; no other message fields (Attack/Critical) wired up yet; no broad scanning or code injection used or considered necessary, since polling caught the event cleanly on the first attempt.

**Stopping here, per instruction** — one successful spoken event confirmed and documented; coverage has not been expanded to the other known fields (`0x804AF558` Attack, `0x804AF55C` Critical) or to any other message category (faint, status, stat-change) yet. That would be the natural next step, pending direction.

## Battle-text message-ID tracing (2026-07-24) — CONFIRMED end-to-end

Follow-on investigation after the `gLastSelectedIndex` rejection above, aimed at tracing the real battle-message-display path via debugger evidence rather than arithmetic ID-offset guessing (explicitly prohibited by the user's instructions for this pass).

### Offline extraction pipeline — built and verified working

A complete, from-scratch, read-only Python extraction pipeline was built for the user's own vanilla US disc image, cross-checked directly against source (not assumed):
- **FSYS container parsing** (`Companion/_dialogue_extraction_tool.py`), ported from `Research/ThirdParty/pokemon_fsys_tool/pokemon_fsys_tool.cpp`'s real struct layouts and LZSS decompression algorithm.
- **REL (relocatable module) parsing**, including the relocation-command-walking algorithm that reconstructs the `CommonIndexes` pointer table, ported from `Pokemon-XD-Code/Objects/file formats/XGRelocationTable.swift`.
- **String-table decoding** (header, index table, 2-byte-unit character data, `0xFFFF`-escaped control codes), ported from `Pokemon-XD-Code/Objects/file formats/XGStringTable.swift` and `enums/XGSpecialStringCharacters.swift`.
- Files extracted from the disc image via `DolphinTool.exe extract` (already installed alongside Dolphin; handles the RVZ format natively) into `Companion/_dialogue_extraction/` (gitignored per the legal-boundary rule in `TEXT_AND_DIALOGUE_PIPELINE.md` section 11).

**Verified correct** by decoding genuine, readable English text: save-file/memory-card error messages from `main.dol`'s embedded string tables (859+3688+5 = 4552 strings), and **1,161 real battle-message strings from `fight_common.fsys`'s dedicated message table** (file type 5, name `fight`) — including directly-matched, unambiguous strings: `"It's super effective!"` (id 20256), `"It's not very effective..."` (id 20255), `"A critical hit!"` (id 20250), `"[Pokemon 15] fainted!"` (id 20021), `"[Pokemon 15]'s attack missed!"` (id 20015).

### Live debugger trace of the battle-message write path

Using the proven-reliable `Z2` write-watchpoint mechanism (`Z0` execution breakpoints remain confirmed broken this session — see the `gLastSelectedIndex` section above), a new script (`Companion/_phase0_scratch_gdb_battlemsg_trace.py`) armed a wide watchpoint over the next several slots of what was previously called a "ring buffer" and is now confirmed, via live stack-symbol resolution, to be a real named symbol: **`_fight_action_fifo`** (`.sbss`, base `0x804AFA48`-ish region, exact base not yet pinned to a named size). Each entry is 0x30 bytes; a `type` field and (for `type==0x13` entries) a `msgid` field were established earlier this session via structural offset analysis (not arithmetic ID guessing — verified by observing the exact same field position hold a plausible value across three independent tests).

**On every one of three independent test runs** (fresh Dolphin restart each time, from the same baseline save state, with different specific user actions), **the exact same pair of values was written**: `msgid=0x59 (89)` then `msgid=0xBC (188)`, both tagged `type=0x13`. This reproducibility across genuinely different user inputs is itself informative — it suggests these two entries are likely **generic, always-fired messages tied to entering the battle-command/action-selection phase itself** (e.g., a trainer-send-out or turn-start announcement), not messages specific to whichever move the user chose, which would explain why they never varied.

**Call-chain context (via live stack-dump symbol resolution, not inference):** the writes occur somewhere within a call chain involving `fightFloorLoopValidFightTrainer`, `fightFloorGetValidFightSidePtr`, and `fightActionFlowAllFightTrainerSelectFightAction` — i.e., the **trainer-AI/valid-target action-selection system**, not a code path with `dispMsg`/`msgctrl`/`CInfoWindow` in its immediate visible call stack. A stable pointer value, `0x80444D08`, recurs as an argument (r7) across multiple unrelated-looking functions in this chain; a direct memory read at that address showed pointer-shaped data (not character data), so it is very likely a shared "battle-turn context" struct pointer passed through this pipeline, not a string pointer — this was verified by direct read, not assumed.

**Watchpoint-timing limitation, confirmed again:** in every hit, the reported PC lands on code that has already moved past the actual triggering write (matching the same pattern first noted in the `gLastSelectedIndex` investigation) — LR is frequently self-referential (clobbered by an internal call within the same trapped function) rather than pointing at a true external caller. A stack-scan for saved return addresses was added specifically to work around this, and did surface real caller symbols, but not a call site that obviously sets up a message ID as an immediate argument.

### What was NOT found (explicit negative results, not silently dropped)

- **No direct match**: the observed values (89, 188) do **not** exist as literal keys in the 1,161-entry `fight_common.fsys` table, whose real IDs start around 20000.
- **No offset guessing performed**, per instruction — `20000 + value` and similar arithmetic transforms were explicitly not attempted again after the prior session's inconclusive/wrong-context result.
- **No nearby 20000+-range value found**: the two live memory snapshots captured earlier this session (`Companion/logs/battlemsg_snapshot_{A,B,C}.bin`, covering `0x80490000`-`0x804D0000`) were re-scanned specifically for any changed 32-bit word in the `[20000, 26000]` range that might represent a separately-stored, fully-resolved string ID written alongside the small FIFO value. None was found.

### Round 2 — static consumer analysis, then one narrow confirmed live test

Per explicit instruction, this round did no further blind memory scanning and made no arithmetic ID guesses. It instead statically traced `_fight_action_fifo`'s producer/consumer/init functions from the symbol map, found the exact writer, and confirmed it with one narrow, targeted `Z2` watchpoint.

**`_fight_action_fifo` fully characterized, statically, from `fightActionFifoInit`'s disassembly:** base `0x804AFA48`, 32 slots × `0x30` bytes, dedicated write-index (`0x804AB8EC`) and read-index (`0x804AB8E8`) counters (both distinct from `_MsgID`/`msgctrlMsgID`, confirming this is a wholly separate mechanism from the general dialogue system audited in `TEXT_AND_DIALOGUE_PIPELINE.md`). Per-slot layout confirmed by disassembling the copy loops in `fightActionFifoIn`/`fightActionFifoOut`: a 2-byte "kind" tag at offset `0x0`, a pointer at offset `0x8`, and (for kind `0x13`) the message ID at offset `0x10` — this matches, field-for-field, what was empirically observed live earlier this session.

**Producer/consumer/init classification (by symbol and disassembly, not inference):**

| Function | Address | Role |
|---|---|---|
| `fightActionFifoIn` | `0x802087DC` | **Producer/enqueue** — copies a caller-supplied action record into the next write-index slot |
| `fightActionFifoOut` | `0x80208734` | **Consumer/dequeue** — copies the current read-index slot out to a caller buffer, advances read-index |
| `fightActionFifoInit` | `0x802088B8` | **Initialization/reset** — zeroes both indices, then calls `fightActionInit` on all 32 slots |
| `fightActionDispFifo` / `fightActionDispFifoAll` | `0x80208618` / `0x802085A0` | **Consumer wrapper** — calls `FifoOut` then dispatches the dequeued entry via `fightActionDisp` |
| `fightActionFlowFifo` | `0x80208654` | Producer-side flow control (enqueues via `FifoIn`, then runs `_fightActionFlowSub`) — **unknown/secondary**, not the path that led to the confirmed result |

**Strongest consumer traced forward, statically, to a real dispatch table:** `fightActionDisp` reads the dequeued entry's "kind" (offset `0x0`, confirmed identical to the previously-observed `type` field), looks it up in a **static, compile-time-initialized dispatch table** at `0x80413AA8` (stride `0xC` bytes/entry — read directly from `main.elf`, no live connection needed for this step), and indirectly calls the per-kind "Disp" function pointer. For `kind=0x13`, that pointer resolves to `fightActionDispFightOutPokemonOutWaza` (`0x8020BFA8`) — **a 2-instruction no-op stub** (`li r3,1; blr`). The same table row's other function-pointer field ("Flow", not "Disp") is `fightActionFlowFightOutPokemonOutWaza` (`0x80209AC4`), which does the real work.

**Tracing `fightActionFlowFightOutPokemonOutWaza` forward** (resolving all ~19 of its call targets by symbol) leads to its call to **`fightSeqWazaExec`** (`0x8020ED04`, 976 bytes — the actual move-execution routine: target/attacker/defender setup, then move effects). Resolving all ~30 of *that* function's call targets surfaced the exact writer functions: **`fightFloor_SetAttackMsgId`** (`0x801F6708`), **`fightFloor_SetCriticakMsgId`** (`0x801F66CC`, sic — typo preserved from the original binary's naming convention), and **`fightFloor_SetWazakoukaMsgId`** (`0x801F6690`, "kouka" = effectiveness) — higher-level wrappers around the low-level setters found earlier this session (`fightFloorBiosSetWazakoukaMsgId` etc.), confirmed to write to the same fields. The one call site to all three inside `fightSeqWazaExec` passes literal `r3=0, r4=0` — a **reset-to-zero**, not the final value; when called with a null pointer they resolve via `fightFloorBiosGetFightFloorPtr()` to the fixed base `0x804A1730`, landing at `0x804AF558`/`0x804AF55C`/`0x804AF560` for Attack/Critical/Wazakouka respectively.

### Narrow live confirmation (one watchpoint, one address, one event)

A dedicated script (`Companion/_phase0_scratch_gdb_wazakouka_trace.py`) armed a `Z2` watchpoint on **only** `0x804AF560` (the Wazakouka/effectiveness message-ID field), pre-programmed to auto-continue past the expected reset-to-zero and capture full evidence on the next write. The user performed one distinctive, independently-verifiable event: **Earthquake (Ground-type) on Metagross (Steel/Psychic) — a confirmed super-effective matchup.**

```
HIT #1: old=0 new=0     (expected reset, auto-continued)
  PC=joutaiDataBiosGetDataPtr  LR=joutaiDataBiosGetUseBanme+0x10

HIT #2: old=0 new=20256  <-- captured
  PC=0x8010AE04 [_msgGetCodeInfo__FP13MSG_TASK_WORKUsPP12tagFONT_INFO+0x6C]
  LR=0x80107A94 [GSmsgGetRect+0x540]
  r3=0x8032F5E0 r4=0x76 r5=0 r6=0x8032EE88 r7=0x8032EE98 r8=0 r9=0xE9 r10=0xE9
```

`20256` is an **exact, direct match** (no arithmetic transform of any kind) to `fight_common.fsys`'s extracted id `20256`: `"It's super effective!"`. The capturing PC/LR context — `_msgGetCodeInfo`/`GSmsgGetRect` — is itself strong independent corroboration: this is literally the text-rendering pipeline computing the on-screen rectangle for a message, which requires the message ID to already be resolved at that point.

### Full confirmed chain

**Super-effective hit → `fightSeqWazaExec` → `fightFloor_SetWazakoukaMsgId` → `0x804AF560` → live value `20256` → `fight_common.fsys` id `20256` → "It's super effective!"**

### Is `_fight_action_fifo`/this call chain useful for accessibility?

**Yes, with caveats.** `0x804AF558`/`0x804AF55C`/`0x804AF560` (Attack/Critical/Wazakouka message-ID fields, all hanging off the fixed, always-valid `fightFloorBiosGetFightFloorPtr()` base `0x804A1730`) are now a **live-verified, pollable source of real battle message IDs**, directly resolvable through the already-working `fight_common.fsys` extraction. This is a materially stronger foundation than the earlier `_fight_action_fifo`-only approach, which surfaced an unrelated, always-firing pair of values (89/188) tied to trainer-AI/action-selection, not to text. The three known fields cover attack-announcement, critical-hit, and effectiveness messages specifically — a real but partial slice of all battle text (faint messages, stat-change messages, status-condition messages, etc. are not yet known to route through these same three fields, and would each need their own confirmation before being trusted).

**Per instruction, this session stops here — no NVDA speech implementation has been started.**

## Phase 0E — attack-message field (`0x804AF558`) validation: INCONCLUSIVE, with a well-evidenced structural explanation

Per instruction, the critical-hit field (`0x804AF55C`) was deliberately deprioritized (random, would need repetitive forced testing) in favor of controlled validation of the attack-message field.

### Static grounding before any live test

`fightFloor_SetAttackMsgId` (`0x801F6708`) / `fightFloorBiosGetAttackMsgId` (`0x801F60AC`) were confirmed, by disassembly, to follow the **identical offset pattern** as the already-confirmed Wazakouka field: offset `+0xDE28` from the fixed `FightFloorPtr` base (`0x804A1730`), landing at `0x804AF558`. Same wrapper structure, same reset-to-zero call site inside `fightSeqWazaExec` (`li r3,0; li r4,0`, same instruction group as the Critical/Wazakouka resets). This confirms it is a genuine message-ID slot in the same family — it does **not** confirm what text it carries, and per instruction no assumption was made about that ahead of the live test.

### Live test (`Companion/phase0e_nvda_attackmsg_poc.py`, adapted directly from the Phase 0D script)

Same 50ms poll interval, dedup/re-arm logic, and read-only `dolphin_memory_engine` usage as Phase 0D, polling only `0x804AF558`. The user performed one ordinary, non-effectiveness-notable move-use. **Result: the field never left `0` for the entire event.** This is a real, logged negative result, not a script failure — the PoC itself was confirmed working moments earlier on the same Dolphin session (Phase 0D's field, on the same build).

### Statically tracing the writer, per instruction (not broadening into a blind scan)

Following `fightSeqWazaExec`'s remaining unexplored large call, `fightSeq_CallWazaSeqCustom` (`0x80223688`), it's a thin one-call wrapper around **`fightSeqExec`** (`0x8020E2E8`, `0xF0` bytes). Disassembling `fightSeqExec` revealed it is a **generic, per-move opcode-dispatch interpreter**, not a fixed procedural code path:

```
lis r3,32816; addi r30,r3,-29960     -> r30 = 0x802F8AF8 (a function-pointer jump table)
bl 0x802236F8                          -> get current sequence-script byte pointer
lbz r0,0(r3)                           -> read ONE OPCODE BYTE from the move's own sequence data
rlwinm r0,r0,2,14,29                   -> r0 = opcode * 4 (word index)
lwzx r12,r30,r0                        -> r12 = jump_table[opcode]  (load handler function pointer)
mtspr CTR,r12; bcctrl                  -> CALL the opcode's handler indirectly
```

This is architecturally fundamentally different from how the Wazakouka field gets set: effectiveness is a **universal type-matchup calculation applied to essentially every attacking move** (which is exactly why the Phase 0D test succeeded on the very first attempt), whereas `AttackMsgId` is set — if at all — by a **specific opcode inside that move's own, individually-authored sequence script** (matching the earlier-found `wazaDB_GetSeqId`/`wazaSequenceSysFreeAllWaza` symbols, confirming each move references its own named sequence). An ordinary damage-only move's sequence may simply never execute an opcode that touches this field at all — the observed all-zero result is therefore plausibly **correct, expected behavior for that specific move**, not evidence of a broken hook or a wrong address.

**Stopping here, per instruction.** Confirming exactly which opcode(s) write `AttackMsgId`, and for which specific moves, would require enumerating and disassembling the jump table's handler functions at `0x802F8AF8` — a materially broader investigation than "trace its statically identified writers," and was not attempted.

### Documentation package for this round

- **All FIFO/message-field references found:** see the "Battle-text message-ID tracing" section above for `_fight_action_fifo`; this section for `fightFloor_SetAttackMsgId`/`GetAttackMsgId` and the `fightSeqExec` opcode-dispatch discovery.
- **Producer/consumer:** `fightSeqWazaExec` resets `AttackMsgId` to 0 unconditionally at the start of every move (confirmed); the real setter, if any, is data-driven per-move via `fightSeqExec`'s opcode table (not yet individually identified).
- **Observed data transformation:** none — the field stayed at `0` throughout the one tested ordinary move.
- **Debugger evidence:** `Companion/logs/phase0e_nvda_attackmsg_poc.log` (no EVENT line logged — faithfully reflects the all-zero result).
- **Passive validation left pending, per instruction:** `0x804AF55C` (Critical) is left unwired for active testing; if/when a critical hit occurs naturally during broader play, log whether it becomes id `20250` ("A critical hit!") without deliberately forcing it.

### Second attempt — Dragon Dance, then a full poison/faint sequence — also all-zero

Same script, same field, re-armed on the same live session (no relaunch needed — `dolphin_memory_engine` reported `hooked` throughout). The user used Dragon Dance, then the encounter continued through a Sludge Bomb hit, poisoning, a poison-damage tick, and fainting — a materially richer and more varied set of event types than the first attempt. **`0x804AF558` stayed at `0` through all of it.** This is a second clean negative result, now covering: an ordinary damage move, a pure stat-boost move (Dragon Dance), a status-condition application (poison), a damage-over-time tick (poison damage), and a faint — none of which wrote to this field.

This strengthens, rather than contradicts, the `fightSeqExec` opcode-interpreter explanation above: it suggests `AttackMsgId` may be reserved for a narrower category of move-specific flavor text than initially guessed (or possibly a category not yet triggered at all in this session), while faint/status/damage-tick messages likely route through entirely different fields or mechanisms not yet identified, consistent with `ACCESSIBILITY_HOOKS.md`'s existing framing of battle turn-messages as needing their own per-category discovery pass rather than one shared field.

**Stopping further live retries on this specific field here** — per instruction, this was not broadened into a blind memory scan; two distinct, purposeful tests were run and both are honestly reported as negative. The next step, if pursued, would be the static opcode-jump-table enumeration flagged above, or shifting focus to identifying the faint/status-message field(s) directly (a new, separate discovery target, not a variant of this one).

## Pokémon party-switch cursor (`CMenuPokemonCursor`) discovery — IN PROGRESS (2026-07-25)

Task #2 from the current implementation order (Pokémon Switching). The Battle Command Menu (Task #1) was confirmed already implemented, tested, and live-validated first (all four labels — Fight/Item/Call/Pokemon — spoken correctly via the running production narrator). This section covers the still-open discovery work needed before switching itself can be narrated.

### Confirmed: this screen does not use the standard window-node cursor convention

A live, read-only window-list walk (`WindowListWalker`) while the party/switch screen was open found exactly 7 window nodes (`menu_id` 70, 71, 72, 73, 75, 76, 77 — no 74), each exactly `0xBC` bytes apart. Reading `window_cursor_base_offset` (`0x9C`), `window_cursor_offset` (`0x9E`), and `window_alloc_offset` (`0xB8`) for all 7 returned **zero for every node**. This rules out reusing the existing `ProductionMenuReader` cursor-reading logic for this screen; a different mechanism is confirmed in use.

A full non-zero-word dump of all 7 window nodes (read-only, `dolphin_memory_engine.read_bytes` only) showed the non-zero fields are a static per-slot layout table, not a live selection index: five of the seven nodes carry a per-window pointer at `+0x68` into a fixed table starting at `0x804280E8` with a `0x30`-byte stride and 6 distinct entries — matching the 6 party slots exactly. This is layout/position data, not the cursor state, and was ruled out as a candidate for the live selected-slot index.

### Real class identified via static symbols: `CMenuPokemonCursor`

`config/GXXE01/symbols.txt` names a real C++ class, `CMenuPokemonCursor`, with methods including `setPositionIndex__18CMenuPokemonCursorFl` (`0x8001F8E4`, size `0x3C`), `init__18CMenuPokemonCursorFv` (`0x8001F9A0`, size `0x74`), `setPokemon__18CMenuPokemonCursorFP7Pokemon` (`0x8001F7C8`), `setPositionTable__18CMenuPokemonCursorFP12PocketVec<s>l` (`0x8001F920`), `setPositionTableDummy__18CMenuPokemonCursorFv` (`0x8001F8A0`), `draw__18CMenuPokemonCursorFv` (`0x8001F214`), plus `deletePokemon`/`isCatchPokemon`/`setBeforAnt`/`setAnimationOff`. Entry point for this screen: `menuFightOpenPokemon` (`0x8001DCC8`).

Disassembling `setPositionIndex` (`Companion/_phase0_scratch_disasm.py` against `xd-decomp/build/GXXE01/main.elf`) revealed the object layout directly:

- `this+0x0C`: current selected-slot index (32-bit word — this is the live field that needs to be polled)
- `this+0x10`: previous index (backed up before the new one is stored, for animation/interpolation)
- `this+0x14` / `this+0x16`: current X/Y screen position (signed 16-bit each), looked up from the position table using the *old* index
- `this+0x18`: pointer to the active position table

Disassembling `init` confirmed the same layout: it clears the object (`memset`-style call, `0x150` bytes), sets an active/initialized flag at `+0x0`, resets `+0x14`/`+0x16` to `0`, and stores a computed address into `+0x18`: `r13 - 22220` (`0x804EFE20 - 0x56CC = 0x804EA754`). This computed address is an **exact match** for the named static symbol `defaultPositionTbl__18CMenuPokemonCursor = .sbss:0x804EA754` — direct static confirmation that the struct-offset interpretation above is correct, and that `+0x18` defaults to this static fallback table before any real per-screen table is assigned via `setPositionTable`.

### Dead end 1: `menuFightOpenPokemon` does not directly call any `CMenuPokemonCursor` method

A full disassembly of `menuFightOpenPokemon` (`0x8001DCC8`, `0x290` bytes) contains no `bl` to `init`, `setPositionIndex`, or `setPokemon`. The cursor object must be owned/initialized by a different function in the same translation unit not yet identified by name (this codebase mixes named global C++ methods with unnamed local-scope state functions, as already seen with `CMenuPokemonLeave`/`CMenuPokemonChange` elsewhere in `symbols.txt`).

### Dead end 2: `menuPokemonCursor` (`0x80014898`) is unrelated

Despite the name, disassembly showed this plain (non-mangled) function only reads and writes a signed 16-bit field at a generic window's `+0x9E` — the same standard cursor offset already used by `ProductionMenuReader` for other menus. It contains no calls into any `CMenuPokemonCursor` method and no references to `0x804EA754`. Ruled out.

### Dead end 3 (so far): live pointer scan for the default table came back empty

Reasoning: if `+0x18` still held the default table pointer (`0x804EA754`) while the real screen was open, a read-only scan of all of MEM1 (`0x80000000`–`0x81800000`) for the literal big-endian bytes `80 4E A7 54` would land on `match_address − 0x18`, directly giving the live instance base. The scan (ad-hoc read-only script, `hook`/`is_hooked`/`read_bytes` only, not saved as a tracked file) found **zero occurrences** anywhere in MEM1. Most likely explanation: `setPositionTable` (the non-"Dummy" variant) overwrites `+0x18` with the real per-screen table pointer as soon as the screen opens, so the default value doesn't persist long enough to be found this way. This is a negative result, reported honestly, not silently dropped.

### Current state: diff-based approach in progress, no controller input requested yet beyond this checkpoint

A non-invasive re-check confirmed the same 7 window nodes are still present at the same addresses, meaning the party/switch screen was still open at time of writing. Following the same diff methodology already validated earlier in this project (Phase 0B/0C), a full read-only baseline snapshot of MEM1 (25,165,824 bytes, `0x80000000`–`0x81800000`) was taken **before** requesting any input. The user has been asked for exactly one D-pad Down press so a second snapshot can be diffed against the baseline, filtered for small-integer word changes consistent with a slot-index field. No second snapshot has been taken yet; no claim is made about the instance address until that diff completes.

**Nothing about this field has been wired into speech output.** No live index has been confirmed. This section will be updated with either a CONFIRMED or REJECTED/INCONCLUSIVE outcome once the diff is run.

## No-writes audit

**Updated 2026-07-25 to cover the full session — see below for why the table below was previously incomplete.** Every script used during this investigation, and what it calls from `dolphin_memory_engine`:

| Script | Calls used | Writes? |
|---|---|---|
| `Companion/test_dolphin_connection.py` | `hook`, `is_hooked`, `get_status`, `un_hook` | No |
| `Companion/_phase0_scratch_read_header.py` | `hook`, `is_hooked`, `read_bytes`, `un_hook` | No |
| `Companion/_phase0_scratch_read_titlemenu.py` | `hook`, `is_hooked`, `read_bytes`, `un_hook` | No |
| `Companion/_phase0_scratch_read_hero.py` | `hook`, `is_hooked`, `read_bytes`, `un_hook` | No |
| `Companion/_phase0_scratch_read_hero2.py` | `hook`, `is_hooked`, `read_word`, `read_bytes`, `un_hook` | No |
| `Companion/_phase0_scratch_hexdump.py` | `hook`, `is_hooked`, `read_bytes`, `un_hook` | No |
| `Companion/_phase0_scratch_snapshot.py` | `hook`, `is_hooked`, `read_bytes`, `un_hook` | No |
| `Companion/_phase0_scratch_msgid_poll.py` | `hook`, `is_hooked`, `get_status`, `read_word`, `un_hook` | No |
| `Companion/_phase0_scratch_battlemsg_poll.py` | `hook`, `is_hooked`, `get_status`, `read_word`, `un_hook` | No |
| `Companion/_phase0_scratch_battlemsg_poll2.py` | `hook`, `is_hooked`, `get_status`, `read_word`, `un_hook` | No |
| `Companion/_phase0_scratch_battlemsg_ringbuffer_poll.py` | `hook`, `is_hooked`, `get_status`, `read_word`, `un_hook` | No |
| `Companion/_phase0_scratch_live_snapshot.py` | `hook`, `is_hooked`, `get_status`, `read_bytes`, `un_hook` | No |
| `Companion/phase0d_nvda_wazakouka_poc.py` | `hook`, `is_hooked`, `get_status`, `read_word`, `un_hook` | No |
| `Companion/phase0e_nvda_attackmsg_poc.py` | `hook`, `is_hooked`, `get_status`, `read_word`, `un_hook` | No |
| `Companion/_phase0_scratch_diff.py` | (local file comparison only — no Dolphin connection) | No |
| `Companion/_phase0_scratch_diff_region.py` | (local file comparison only) | No |
| `Companion/_phase0_scratch_double_decrease.py` | (local file comparison only) | No |
| `Companion/_phase0_scratch_window.py` | (local file comparison only) | No |
| `Companion/_phase0_scratch_savestate_diff.py` | (local file comparison/parsing only — parses `.sav` files already on disk, no Dolphin connection) | No |
| `Companion/_phase0_scratch_savestate_mem1_diff.py` | (local file comparison only) | No |
| `Companion/_phase0_scratch_savestate_smallval_filter.py` | (local file comparison only) | No |
| `Companion/_dialogue_extraction_tool.py` | (local file parsing only — parses FSYS/REL/string-table files already extracted from the disc image via `DolphinTool.exe`, no Dolphin connection) | No |

No script in this list imports or calls `write_byte`, `write_word`, `write_bytes`, `write_float`, or `write_double`. All scripts prefixed `_phase0_scratch_` are exploratory/diagnostic, kept separate from the two production-track diagnostics (`test_speech.py`, `test_dolphin_connection.py`) described in [FIRST_VERTICAL_SLICE.md](FIRST_VERTICAL_SLICE.md). `phase0d_nvda_wazakouka_poc.py` and `phase0e_nvda_attackmsg_poc.py` are the two read-only NVDA proof-of-concept scripts (see their own sections above); they use `dolphin_memory_engine` exclusively, with no GDB stub involved at all.

### GDB RSP-based scripts — separate mechanism, audited separately

These scripts don't call `dolphin_memory_engine` at all — they use Dolphin's built-in GDB Remote Serial Protocol stub via `Companion/_phase0_scratch_gdb_watchpoint.py`'s `RSPClient` class, under the strict outgoing-packet allowlist documented in the "GDB remote-debugging investigation" section above (`? g p m Z2 z2 c s D` only — `Z0`/`z0` also technically allowlisted but confirmed unreliable and unused after that discovery; **never** `M`/`X`/`G`/`P`/`qRcmd`, the packet types capable of writing memory or registers or running arbitrary monitor commands).

| Script | Packets actually used | Writes? |
|---|---|---|
| `Companion/_phase0_scratch_gdb_watchpoint.py` | `?` `g` `p` `m` `Z2` `z2` `c` `D` (the shared `RSPClient` class other scripts import) | No |
| `Companion/_phase0_scratch_gdb_sanity.py` | `?` `Z0` `z0` `c` `p` `D` (no `g` — the `PADRead` sanity check reads only `p` registers, never full GPRs; proved `Z0` unreliable) | No |
| `Companion/_phase0_scratch_gdb_battlemenu.py` | `?` `Z0` `z0` `c` `p` `g` `D` (the 15-breakpoint `menuFight*` attempt, later understood as a false negative from broken `Z0`) | No |
| `Companion/_phase0_scratch_gdb_execbp.py` | `?` `Z0` `z0` `s` `c` `p` `g` `m` `D` (the original `menuTitleGetSelect` single-step trace) | No |
| `Companion/_phase0_scratch_gdb_battlemsg_trace.py` | `?` `m` `Z2` `z2` `c` `g` `p` `D` (imports `RSPClient`; the `_fight_action_fifo` wide-range trace) | No |
| `Companion/_phase0_scratch_gdb_wazakouka_trace.py` | `?` `m` `Z2` `z2` `c` `g` `p` `D` (imports `RSPClient`; the narrow single-address trace that confirmed id `20256`) | No |

Verified by direct code review of every file in both tables, not by convention alone.
