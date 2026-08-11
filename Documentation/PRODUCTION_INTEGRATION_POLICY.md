# Production Integration Policy

## Rule

From 2026-07-25 forward, every accessibility feature that completes its bounded validation must be integrated into the canonical battle narrator unless the project owner explicitly keeps it diagnostic-only.

The canonical user entry point is:

```powershell
python Companion/run_battle_narrator.py
```

That launcher must never silently lag behind a numbered phase launcher. Numbered PoCs and phase entry points remain preserved for evidence, regression isolation, and historical reproduction, but they are not the ordinary user-facing narrator.

## Required integration checklist

For each verified update:

1. Preserve the diagnostic PoC and its evidence unchanged.
2. Move reusable behavior into a separate production module where practical.
3. Centralize verified profile addresses, offsets, bounds, and formats.
4. Wire the feature into the persistent lifecycle.
5. Isolate feature-specific read failures so unrelated narration continues.
6. Preserve read-only memory access.
7. Add synthetic regression coverage for success, deduplication, malformed data, lifecycle reset, and known edge cases.
8. Run the complete automated suite.
9. Perform one bounded live production regression when required.
10. Update phase documentation and `IMPLEMENTATION_ATTRIBUTION.md`.

## Current canonical feature set

The default narrator currently includes:

- persistent Dolphin attachment, disconnection, and reconnection;
- strict vanilla `GXXE01` revision-0 profile validation;
- GSmsg shared battle-message narration;
- verified Pokémon, move, suffix, stat, target, and player-name substitutions;
- primary battle-command focus;
- move focus with move name, type, and PP;
- generic settled percentage-based HP-loss narration;
- foreground-only configurable manual live HP/status summaries;
- silent health re-baselining after verified healing;
- NVDA output through cytolk;
- UTF-8 diagnostic logging;
- read-only Dolphin memory access.

## Compatibility behavior

`Companion/battle_narrator/app.py` is now a compatibility alias to the persistent production application. Older imports therefore receive the complete narrator rather than the obsolete one-shot implementation.

`Companion/run_battle_narrator_phase1b.py` remains available for historical compatibility, but it invokes the same production application as the canonical launcher.

## Signed implementation

The canonical-launcher migration and this policy were implemented by **Codex (OpenAI)** on 2026-07-25 at the project owner’s request.