"""Runtime object-enable state for CCD collision objects.

`GScolsys2SetObjEnable`/`GScolsys2GetObjEnable` (disassembled 2026-07-31)
let room scripts toggle whether a specific top-level CCD entry ("object")
is currently considered by collision queries -- `GScolsys2WalkGetHeight`
itself skips disabled objects before even examining a walk-model triangle's
geometry (`script.s` calls `GScolsys2SetObjEnable`, confirming this is a
real, dynamic, script-driven mechanism, not dead code). Every
`WalkTriangle`/`CollisionTriangle` carries the `entry_index` this state
would key on.

**Status: STATIC ONLY, not live-validated.** Disassembly of
`GScolsys2GetObjEnable` traces the storage to a `GScolsys2` global near
0x80445C20, with 0x28-byte per-object records and bit 0 of `u16 +0x24`
meaning disabled -- but this has NOT been confirmed against live memory. No
room with a known scripted geometry change was identified as reachable
during this investigation to test it safely, and per the project owner's
explicit instruction, the runtime mapping between file entries and enable
records must not be guessed into production use.

This module exists so that gap is isolated behind one small interface
rather than left as an implicit assumption scattered through
`pathfinding.py`: every consumer asks an `ObjectEnableState`, never reads
memory or a hardcoded address directly. Swapping in a live-verified
implementation later is a one-class change, not a call-site rewrite.
"""


class ObjectEnableState:
    """Interface every implementation must satisfy."""

    def is_enabled(self, floor_id, entry_index):
        raise NotImplementedError


class StaticObjectEnableState(ObjectEnableState):
    """Every object is always enabled -- the honest default until the live
    enable-state global is verified. Room scripts that disable collision
    objects dynamically will not be reflected; that is a known, explicitly
    flagged limitation (see this module's own docstring), not a silent
    gap."""

    def is_enabled(self, floor_id, entry_index):
        return True
