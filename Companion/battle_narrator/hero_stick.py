"""The engine's own scripted-stick override, exposed as a held control.

This is the SECOND memory-writing module in a project that is otherwise
strictly read-only (`teleport.py` was the first, and its docstring still
describes itself as the only one -- it is now the only one that writes a
POSITION). Built 2026-08-16 at the project owner's explicit direction, after
an investigation established that the game already contains the mechanism
this needs, so autowalk does not have to synthesise controller input at all.

**What this writes, and why it is not a hack**

`heroMove.s` reads the player's stick through one private accessor,
`_getStickData` (0x8014E7F8). Its first act is to load a flag byte from
`HeroMove+0x3AE` and, when it is non-zero, return four stored bytes
(+0x3AF..+0x3B2) and branch past every `GSinputGetLeftStick*Data` call, the
D-pad translation, and the camera-type checks. The real controller is not
consulted at all on that path.

The matching writer, `_setStickData` (0x8014E7D4), is what the engine itself
uses: `_heroMoveSlowStopFactor` (0x8014EDF4) samples the live stick, scales
it down over successive frames, feeds each decayed value back through
`_setStickData`, and clears the flag when it reaches zero -- the
deceleration you see when the game takes control of the character. So these
five bytes are the game's documented-by-construction way of driving the
hero, and writing them drives the hero the way the game drives it:

- movement runs through the engine's normal locomotion, so collision, the
  walk model's height and layer resolution, animation, footsteps, warp
  triggers, encounter steps and talk cones all behave exactly as they do
  under a real player;
- nothing is written to the player's position, unlike `teleport.py`, which
  moves the model directly and therefore bypasses all of the above.

**Why the byte values are what they are**

The four stick bytes are two X/Y pairs -- on the non-override path they come
from `GSinputGetLeftStickXData`/`YData` called with the second argument 1
and then 0, i.e. the smoothed and unsmoothed reads of the same stick. A
steady hold makes the two equal, so `hold()` writes one value into both
pairs rather than guessing which one locomotion consumes.

Sign convention is cross-verified from two independent directions: the
D-pad branch of `_getStickData` stores Y = -0x38 for PAD_BUTTON_UP (0x8) and
X = -0x38 for LEFT (0x1), and `movement_input.py`'s live 2026-08-03
measurement of the controller cache independently found stick Y negative for
up with positive X toward the camera's right. Both agree, and 0x38 (56) is
also exactly the full deflection that session measured.

**Fail-safe design**

Nothing here is edge-triggered: the flag is level-held, so the engine keeps
using whatever was last written until the flag is cleared. That makes the
release path the one that matters, and it is deliberately the cheapest and
most robust operation in the module -- a single-byte write of zero, safe to
repeat, attempted on every teardown path whether or not this module thinks
it is currently engaged. A missed release would leave the player unable to
move; a redundant one costs a byte.

The address block is verified against the live image before the first write
(`verify()`), not assumed from the vanilla XD decomp. That check is local to
this feature on purpose rather than added to `profile.engine_signatures`: a
build where these bytes differ should lose autowalk, not lose the entire
narrator.
"""
from .memory import MemoryError

SET_STICK_ADDRESS = 0x8014E7D4
SET_STICK_BYTES = bytes.fromhex(
    "3ce08044"  # lis   r7, HeroMove@ha        \  together these pin
    "38000001"  # li    r0, 1                   |  HeroMove = 0x804479F0
    "38e779f0"  # addi  r7, r7, HeroMove@l     /
    "980703ae"  # stb   r0, 0x3ae(r7)   <- override flag
    "986703af"  # stb   r3, 0x3af(r7)   \
    "988703b0"  # stb   r4, 0x3b0(r7)    |  the four stick bytes
    "98a703b1"  # stb   r5, 0x3b1(r7)    |
    "98c703b2"  # stb   r6, 0x3b2(r7)   /
    "4e800020"  # blr
)
"""`_setStickData__FScScScSc` in full. Short enough to pin exactly, and it
encodes every address this module uses: the base, the flag offset, and all
four stick offsets."""

GET_STICK_ADDRESS = 0x8014E7F8
GET_STICK_BYTES = bytes.fromhex(
    "9421ffd0"  # stwu  r1, -0x30(r1)
    "7c0802a6"  # mflr  r0
    "3ce08044"  # lis   r7, HeroMove@ha
    "90010034"  # stw   r0, 0x34(r1)
    "bf010010"  # stmw  r24, 0x10(r1)
    "7c791b78"  # mr    r25, r3
    "386779f0"  # addi  r3, r7, HeroMove@l
    "7c9a2378"  # mr    r26, r4
    "7cbb2b78"  # mr    r27, r5
    "7cdc3378"  # mr    r28, r6
    "880303ae"  # lbz   r0, 0x3ae(r3)  <- the override flag, read FIRST
    "28000000"  # cmplwi r0, 0
    "41820018"  # beq   .L_8014E840    <- only then read the real controller
)
"""`_getStickData__FRScRScRScRSc`'s prologue through the override test. The
last three instructions are the whole reason this feature exists: they are
what makes a write to the flag byte take priority over the player's own
controller. Truncated after the branch deliberately -- everything past it is
the ordinary controller path, which this module neither uses nor cares about
the exact shape of."""

UNVERIFIED_MESSAGE = (
    "Autowalk is unavailable on this build: the game's own movement "
    "override is not where this version expects it."
)


def _stick_byte(value):
    """One signed stick axis as the engine stores it, clamped to the same
    full deflection the engine's own D-pad path uses. Clamping rather than
    wrapping matters: a bug that produced 200 here would otherwise become a
    hard shove in the OPPOSITE direction, which for a blind player walking
    unseen terrain is the worst possible failure."""
    limit = 0x38
    clamped = max(-limit, min(limit, int(round(value))))
    return clamped + 256 if clamped < 0 else clamped


class HeroStickOverride:
    """Holds the engine's scripted-stick override on behalf of one caller.

    Not a context manager, because its lifetime is a player-facing mode
    spanning many polls rather than a block of code -- but `release()` obeys
    the same discipline a context manager's exit would, and is safe to call
    at any time, including when nothing was ever engaged."""

    def __init__(self, memory, profile, logger):
        self.memory = memory
        self.profile = profile
        self.logger = logger
        self.engaged = False
        self._verified = None

    @property
    def _flag_address(self):
        return self.profile.hero_move_base + self.profile.hero_move_stick_override_offset

    def verify(self):
        """True when this build's `HeroMove` accessors are byte-identical to
        the ones these addresses were derived from.

        Cached after the first successful check: it reads two small,
        never-rewritten stretches of `.text`, so re-reading them every poll
        would cost real memory traffic to re-answer a question that cannot
        have changed. A FAILED check is deliberately not cached -- the game
        may simply not have finished booting, and that must not permanently
        disable the feature for the session."""
        if self._verified:
            return True
        try:
            setter = self.memory.bytes(
                SET_STICK_ADDRESS, len(SET_STICK_BYTES), "_setStickData")
            getter = self.memory.bytes(
                GET_STICK_ADDRESS, len(GET_STICK_BYTES), "_getStickData")
        except MemoryError as exc:
            self.logger.debug("HERO STICK verify unreadable: %s", exc)
            return False
        if setter != SET_STICK_BYTES or getter != GET_STICK_BYTES:
            self.logger.warning(
                "HERO STICK signature mismatch: _setStickData %s, "
                "_getStickData %s",
                "ok" if setter == SET_STICK_BYTES else "differs",
                "ok" if getter == GET_STICK_BYTES else "differs",
            )
            return False
        self._verified = True
        return True

    def hold(self, x, y):
        """Push the stick to (x, y) and keep it there until told otherwise.

        Flag and values go out as ONE write so the engine can never observe
        the flag set against stale stick bytes -- ordering the two writes
        separately would leave exactly that window open for a frame."""
        data = bytes((
            1,
            _stick_byte(x), _stick_byte(y),
            _stick_byte(x), _stick_byte(y),
        ))
        self.memory.write_bytes(
            self._flag_address, data, "hero stick override hold")
        self.engaged = True

    def release(self):
        """Hand the controller back. Idempotent, and never raises.

        Callers reach this from failure paths -- a dropped Dolphin
        connection, an unexpected exception mid-walk, shutdown -- where
        propagating an error would leave the override latched and the player
        unable to move. Reporting the failure and continuing is strictly
        better than that, so a failed release is logged, not raised."""
        try:
            self.memory.write_bytes(
                self._flag_address, b"\x00", "hero stick override release")
        except Exception as exc:
            # Deliberately broader than `MemoryError`, unlike everywhere
            # else in this project. `MemoryReader.write_bytes` converts
            # backend failures, so that alone would normally be enough --
            # but this method's contract is that it CANNOT raise, and a
            # contract that holds only as long as a conversion two modules
            # away keeps holding is not one worth stating. If this address
            # is unwritable the emulator is gone, which also means the
            # override is gone; there is nothing useful left to try.
            self.logger.debug("HERO STICK release failed: %s", exc)
        finally:
            self.engaged = False
