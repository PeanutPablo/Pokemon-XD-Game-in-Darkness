"""Runtime object-enable state for CCD collision objects.

`GScolsys2SetObjEnable`/`GScolsys2GetObjEnable` let room scripts toggle
whether a specific top-level CCD entry ("object") is currently considered by
collision queries. Every `WalkTriangle`/`CollisionTriangle` carries the
`entry_index` this state keys on.

**Status: live, derived from disassembly 2026-08-13.** The structure below
was re-derived from `GScolsys2.s` rather than carried over from the earlier
static-only note, and three of that note's assumptions turned out to be
wrong or unproven. What the disassembly actually says:

    GScolsys2 @ 0x80445C20              (`GScolsys2@ha`/`@l` in every accessor)
      +0x000  CCD_FILEHEAD*  curCCD     NULL => GetObjEnable returns error 1
      +0x004  GSCOLSYS2_FLOOR floor     0xDC0 bytes
                +0x000  GSCOLSYS2_OBJ obj[64]   stride 0x28
                          +0x00  f32[9]  transform, copied from the CCD entry
                          +0x24  u16     flags -- bit 0 SET means DISABLED
                +0xA00  <other>[48]     stride 0x14, unrelated to obj enable
      +0xDC4  s32   curFloor            see below
      +0xDC8  GSgfxVF*
      +0xDCC  void* displayList         GSgfxDLFree'd by GScolsys2UnloadCCD

`GScolsys2GetObjEnable(index, out_u8)` reads `flags & 1` and stores the
INVERSE into `*out_u8`: bit set -> 0, bit clear -> 1. So the out-parameter is
"enabled" while the stored bit is "disabled". `SetObjEnable(index, enable)`
clears bit 0 when `enable != 0` and sets it otherwise. Return codes: 0 ok,
1 no CCD loaded, 2 index out of range -- and on both error paths the
out-parameter is left untouched, which is why this module raises rather than
defaulting when it cannot answer.

**Object index is the CCD entry index, identically.** `GScolsys2LoadCCD`
walks the CCD entry array (stride 0x40) and the OBJ array (stride 0x28) in
lockstep, writing entry `i` into record `i`; `GScolsys2WalkGetHeight` and the
hit-model sweep both loop `i` over `[0, count)` calling
`GScolsys2GetObjEnable(i, ...)` and `continue` when it reports 0, BEFORE
looking at any geometry. `count` is `*(u32*)(curCCD + 0x04)` -- the same
entry count `collision_probe.py` already parses out of the file.

**One record serves both model slots.** The walk path (CCD +0x24) and the
hit path (CCD +0x28/+0x34) consult the same `obj[i].flags`, so a disabled
object withdraws its walkable ground and its walls together. Filtering only
the wall slot would be wrong.

**Lifetime.** `GScolsys2LoadCCD` stores 0 into `obj[i].flags` for every one
of the `count` objects, so **every object starts enabled on room load** and
the room script's `preprocess` then disables the ones that story state calls
for. `GScolsys2UnloadCCD` only nulls `curCCD`; it leaves the flag words
alone, which is safe precisely because the next `LoadCCD` rewrites them.
Object state can also change mid-room at any time -- Gateon Port's rotating
piers are exactly that -- so a snapshot is never valid indefinitely.

**Save/load carries it.** `_gscolsysMakeStateData`/`_gscolsysRestoreStateData`
are registered with `floorRegisterModule`; mode 3 serialises exactly 64 u16
flag words (size 0x84 = 4 + 64*2) and modes 1/2 memcpy the whole 0xDC0 floor
block. Object enable state therefore survives a save/load rather than being
re-derived, which is the independent confirmation that the record stride is
0x28 and the flags word sits at +0x24: the mode-3 loop stores to
`GScolsys2 + 0x28 + i*0x28`, which is `floor + i*0x28 + 0x24`.

**Corrections to the previous static-only note.** It described "0x28-byte
per-object records and bit 0 of u16 +0x24", which is right, but it did not
establish the record BASE (`+0x04`, not `+0x00`), the object CAPACITY (64),
the index MAPPING (identity with the file's entry index), or that walk and
hit share one record. Those are the four facts a live implementation
actually needs, and none of them were previously pinned.

**The +0xDC4 field is not a bank selector.** `GScolsys2GetCurFloor` accepts
it only when it is exactly 0 (`cmpwi 0; blt fail` then `cmpwi 1; blt ok`),
returning NULL otherwise, and the only write to it in the whole module is
`GScolsys2Init` storing 0. The `* 0xDC0` scaling in the accessors is
therefore vestigial -- there is one floor slot. This module still reads and
validates the field rather than assuming it, because a non-zero value would
mean the structure is not what this code believes and guessing past that is
exactly the failure this module exists to prevent.
"""


GSCOLSYS2_ADDRESS = 0x80445C20
"""`GScolsys2`, from `lis rX, GScolsys2@ha; addi rY, rX, GScolsys2@l` at the
head of every accessor in `GScolsys2.s`."""

CUR_CCD_OFFSET = 0x000
FLOOR_OFFSET = 0x004
CUR_FLOOR_OFFSET = 0xDC4
OBJ_STRIDE = 0x28
OBJ_FLAGS_OFFSET = 0x24
OBJ_DISABLED_BIT = 0x0001
MAX_OBJECTS = 64
"""Capacity of `GSCOLSYS2_FLOOR.obj[]`: the floor block is 0xDC0 bytes, of
which the OBJ array is 64 * 0x28 = 0xA00, and `_gscolsysRestoreStateData`
mode 3 iterates exactly 64 flag words. A CCD reporting more entries than
this is not a room we understand -- `LoadCCD` would run off the end of the
array -- so it is refused rather than clamped."""

CCD_ENTRY_COUNT_OFFSET = 0x04
"""`*(u32*)(curCCD + 0x04)`, the bound `GetObjEnable` range-checks against.
The same field `collision_probe.parse_environment_triangles` reads as
`entry_count`."""


class EnableStateUnavailable(RuntimeError):
    """The engine's collision-object enable state could not be read or could
    not be correlated with the room being asked about.

    Raised rather than defaulted, deliberately. Defaulting to "everything is
    enabled" is not a neutral fallback: it is the exact defect this module
    replaces -- it reinstates collision objects the running game has switched
    off, which walls off real routes (Agate's Relic Stone cave mouth was
    sealed into a 26-node pocket by one such object). Defaulting the other
    way is worse still: it would delete real walls and route a blind player
    through them. There is no safe guess, so callers get an exception and
    fall back to direct guidance with the reason logged."""


class ObjectEnableState:
    """Interface every implementation must satisfy."""

    def is_enabled(self, floor_id, entry_index):
        raise NotImplementedError


class StaticObjectEnableState(ObjectEnableState):
    """Every object is always enabled.

    **Not suitable for live routing** -- kept for tests and for offline tools
    that analyse a `.ccd` file on its own, where there is no running game to
    ask and "the file as shipped" is the intended subject. Using it against a
    live session reintroduces the disabled-object defect."""

    def is_enabled(self, floor_id, entry_index):
        return True


class ObjectEnableSnapshot:
    """One consistent read of every object's enable bit, plus the identity of
    what was read, so a later query can refuse to answer about a different
    room instead of silently answering about the wrong one."""

    __slots__ = ("floor_id", "cur_ccd", "count", "flags")

    def __init__(self, floor_id, cur_ccd, count, flags):
        self.floor_id = floor_id
        self.cur_ccd = cur_ccd
        self.count = count
        self.flags = tuple(flags)

    @property
    def signature(self):
        """Cheap value identifying this exact enable configuration. Geometry
        caches compare signatures to decide whether a rebuild is owed; it
        changes when any object toggles, when the room's CCD changes, or when
        the object count does."""
        return (self.floor_id, self.cur_ccd, self.count, self.flags)

    def is_enabled(self, entry_index):
        if not isinstance(entry_index, int) or not 0 <= entry_index < self.count:
            raise EnableStateUnavailable(
                f"entry index {entry_index} outside the running room's object "
                f"table (count={self.count}) -- the parsed .ccd and the loaded "
                f"room disagree")
        return not (self.flags[entry_index] & OBJ_DISABLED_BIT)

    def disabled_entries(self):
        return tuple(
            index for index, word in enumerate(self.flags)
            if word & OBJ_DISABLED_BIT)


class LiveObjectEnableState(ObjectEnableState):
    """Reads the engine's own per-object enable bits.

    Read-only: this never calls `write_bytes`, and there is deliberately no
    setter. The companion observes the game's collision state; it does not
    author it.

    Usage is two-phase so that a route build never triggers a memory read of
    its own: `refresh(floor_id)` once per poll takes one consistent snapshot,
    and `is_enabled` answers from it. That keeps `build_room_geometry` -- which
    calls `is_enabled` once per triangle, thousands of times -- entirely in
    Python, and makes "did anything change since the last build" a single
    tuple comparison.

    `stale_after_s` bounds how long a snapshot may outlive a failed refresh.
    Transient `MemoryError`s are normal while Dolphin is running (the reader
    already converts them), and dropping to direct guidance on every hiccup
    would be its own accessibility regression -- rebuilding `M6_out`'s
    geometry costs seconds, so churning it per hiccup is not affordable
    either. So a failed refresh keeps the last VERIFIED snapshot briefly,
    which is materially different from inventing one, and then gives up
    honestly."""

    DEFAULT_STALE_AFTER_S = 3.0

    def __init__(self, reader, logger, clock, address=GSCOLSYS2_ADDRESS,
                 stale_after_s=DEFAULT_STALE_AFTER_S):
        self.reader = reader
        self.logger = logger
        self.clock = clock
        self.address = address
        self.stale_after_s = stale_after_s
        self._snapshot = None
        self._snapshot_at = None
        self._last_failure = None

    # ---------------------------------------------------------------- read
    def _read_snapshot(self, floor_id):
        reader = self.reader
        base = self.address
        cur_floor = reader.u32(base + CUR_FLOOR_OFFSET, "GScolsys2.curFloor")
        if cur_floor != 0:
            # GScolsys2GetCurFloor itself returns NULL for anything but 0.
            raise EnableStateUnavailable(
                f"GScolsys2.curFloor is {cur_floor}, not 0 -- the floor block "
                f"is not where this build expects it")
        cur_ccd = reader.u32(base + CUR_CCD_OFFSET, "GScolsys2.curCCD")
        if cur_ccd == 0:
            raise EnableStateUnavailable("no CCD is loaded (curCCD is NULL)")
        count = reader.u32(cur_ccd + CCD_ENTRY_COUNT_OFFSET, "CCD entry count")
        if not 0 < count <= MAX_OBJECTS:
            raise EnableStateUnavailable(
                f"CCD reports {count} objects, outside 1..{MAX_OBJECTS}")
        block = reader.bytes(
            base + FLOOR_OFFSET, count * OBJ_STRIDE, "GScolsys2.floor.obj")
        flags = []
        for index in range(count):
            offset = index * OBJ_STRIDE + OBJ_FLAGS_OFFSET
            flags.append((block[offset] << 8) | block[offset + 1])
        return ObjectEnableSnapshot(floor_id, cur_ccd, count, flags)

    def refresh(self, floor_id):
        """Take a fresh snapshot for `floor_id`. Returns the current
        signature, or `None` if no usable snapshot is available.

        Callers compare the returned signature against the one their cached
        geometry was built from; a difference means the engine toggled an
        object and the graph is stale."""
        try:
            snapshot = self._read_snapshot(floor_id)
        except Exception as exc:
            self._note_failure(floor_id, exc)
            return self._stale_signature()
        self._snapshot = snapshot
        self._snapshot_at = self.clock()
        if self._last_failure is not None:
            self.logger.info(
                "COLLISION enable-state read recovered floor=0x%X", floor_id)
            self._last_failure = None
        return snapshot.signature

    def _note_failure(self, floor_id, exc):
        message = f"{type(exc).__name__}: {exc}"
        if self._last_failure != message:
            # Once per distinct cause, not once per poll -- this runs in the
            # per-poll path and an unreadable global would otherwise flood
            # the log (this project has produced a 275 MB one before).
            self.logger.warning(
                "COLLISION enable-state unreadable floor=0x%X: %s", floor_id,
                message)
            self._last_failure = message

    def _stale_signature(self):
        snapshot = self._snapshot
        if snapshot is None:
            return None
        age = self.clock() - (self._snapshot_at or 0.0)
        if age > self.stale_after_s:
            self._snapshot = None
            self._snapshot_at = None
            self.logger.warning(
                "COLLISION enable-state snapshot expired after %.1fs without a "
                "successful read -- routing falls back to direct guidance", age)
            return None
        return snapshot.signature

    # --------------------------------------------------------------- query
    @property
    def signature(self):
        snapshot = self._snapshot
        return snapshot.signature if snapshot is not None else None

    @property
    def snapshot(self):
        return self._snapshot

    def is_enabled(self, floor_id, entry_index):
        snapshot = self._snapshot
        if snapshot is None:
            raise EnableStateUnavailable(
                f"no collision enable-state snapshot for floor 0x{floor_id:X}"
                if isinstance(floor_id, int) else
                f"no collision enable-state snapshot for floor {floor_id!r}")
        if floor_id is not None and snapshot.floor_id != floor_id:
            # The engine holds exactly one loaded CCD, so a snapshot is only
            # ever evidence about the room it was taken in. Answering across
            # rooms would silently apply Agate's disabled objects to Gateon.
            raise EnableStateUnavailable(
                f"snapshot is for floor {snapshot.floor_id!r}, not "
                f"{floor_id!r}")
        return snapshot.is_enabled(entry_index)
