# Battle Narrator Phase 1B Lifecycle

Phase 1B preserves the Phase 1A message resolver and introduces a persistent
read-only lifecycle entry point:

```powershell
python Companion/run_battle_narrator_phase1b.py
```

This persistent application is now also the canonical default behind `Companion/run_battle_narrator.py`; the numbered launcher remains for compatibility.

The lifecycle distinguishes Dolphin absence, attachment, an unidentified game
header, an unsupported profile, verified GXXE01 with GSmsg unavailable, active
battle narration, temporary battle transitions, disconnection, reconnection,
and clean shutdown.

Null GSmsg manager pointers, zero capacity, and null task-array pointers are
quiet waiting states only while the verified GXXE01 revision-0 profile remains
readable. Invalid nonzero pointers, capacities, or task states remain fatal
structural errors.

NVDA announcements are exactly:

- `Battle narrator connected.`
- `Battle narration ready.`
- `Battle narrator disconnected.`
- `Unsupported game version.` when applicable
- `Battle narrator stopped after an error.` for an unrecoverable configuration
  or structural failure

Waiting and unchanged lifecycle states are written only to the UTF-8 diagnostic
log. Phase 1B continues indefinitely until user shutdown, a conclusively
unsupported profile, or an unrecoverable error.
