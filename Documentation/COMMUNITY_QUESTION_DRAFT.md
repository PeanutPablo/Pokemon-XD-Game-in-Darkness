# Draft community question — NOT SENT

Status: draft only, per explicit instruction. Do not post this to the Orre modding Discord (`https://discord.gg/xCPjjnv`) or anywhere else without the user's separate, explicit go-ahead on the final wording.

## Context for the user before sending

This is written to be posted as-is, but you should read it over first — it's your voice, not mine, and you may want to add your own framing or trim it. It deliberately does not ask for or accept copyrighted files (ROMs, extracted assets, dumps) — only for pointers to existing public research, tools, or documentation.

## Draft text

> Hi all — I'm building an accessibility companion for Pokémon XD/XG for a blind player (NVDA screen reader on Windows), using read-only Dolphin memory access plus statically-extracted data from my own legally-owned game image. Not asking for or distributing any copyrighted files — just hoping to avoid re-deriving research that already exists.
>
> A few things I'd love pointers to, if anyone's looked at them:
>
> 1. **Live menu/cursor state** — has anyone identified the actual runtime object or variable that tracks the current battle-command-menu selection (Fight/Bag/Pokémon/Run) in vanilla XD (GXXE01)? I've been symbol-tracing from `menuFightMainCtrl` via `xd-decomp`'s symbol map plus Dolphin's GDB stub, with partial but unconfirmed results so far.
> 2. **Active message/dialogue ID** — is there a known runtime pointer or ID for "which string table entry is currently displaying," separate from the string table format itself?
> 3. **Dialogue presentation functions** — any known entry points for "show this message" / "show this yes/no choice," by name or address?
> 4. **Player coordinates and facing** — known live struct/address for overworld position + facing direction?
> 5. **Map object placement, warps, and collision geometry** — for the map/model side, I've found `StarsMmd/Blender-Addon-Gamecube-Models` for `.dat`/`.fsys` import — does anyone know whether the map data it reads includes collision/walkable geometry as distinct from render geometry, or is that tracked separately?
> 6. **XG main.dol modifications** — is there any public map of what Pokémon XG: NeXt Gen actually changes relative to vanilla XD (relocated code, expanded sections, new symbols)? I'm treating `xd-decomp`'s vanilla symbol map as unverified for XG until I can check it directly.
> 7. **Ghidra projects / symbol databases** — does anyone maintain a public Ghidra project or symbol DB for XD/XG beyond what's in `xd-decomp`?
> 8. **Windows GoD Tool builds** — any current working Windows build/fork of GoD Tool (I see `PekanMmd/Pokemon-XD-Code` is the source) beyond what's already on GitHub?
>
> Happy to share back anything useful I find along the way. Thanks!

## Notes on scope compliance

- No request for ROM/ISO files, extracted dialogue, models, or other copyrighted assets anywhere in the draft.
- Frames the ask around *pointers to existing research*, not "please dump data for me."
- States the accessibility purpose plainly, which is both honest and likely to get a more helpful reception than an unexplained technical ask.
- References only repos/tools already audited in this project (`xd-decomp`, `Pokemon-XD-Code`/GoD Tool, the Blender addon) so the question reads as informed, not a cold ask.
