"""Read-only, controller-agnostic movement-input detection.

`BlockedMovementReader` needs to know whether the player is *actively
holding* a movement direction, not just standing still -- stillness alone
cannot tell "pushing into a wall" apart from "let go of the stick near a
wall." Global keyboard state (as used by this project's hotkeys, e.g.
`hotkeys.py`) is explicitly wrong for this: it would silently fail for
anyone playing with a real GameCube/USB controller, and polling keyboard
state independently of Dolphin's own input handling risks reading the
wrong thing if Dolphin isn't foreground-focused.

Instead, this reads the GAME's own cached controller-input state --
`GSinput`, the same abstraction layer the game itself uses for the Control
Stick, buttons, and rumble (`GSinputGetLeftStickXData`/`GSinputRead`/etc.,
per `xd-decomp`'s symbol table). Since Dolphin translates every supported
input method (keyboard, real GameCube controller, other pads) into the
same emulated controller state before the game ever sees it, reading the
game's own cache works uniformly regardless of what device the player
actually uses -- unlike reading Windows keyboard state directly.

Derived from static disassembly of
`GSinputGetLeftStickXData`/`GSinputGetLeftStickYData` (0x80104154 /
0x801040F8 in vanilla `GXXE01` rev 0) and their shared per-controller
lookup (0x80105548, a linear search over up to 4 controller-slot structs
starting at 0x80444AF8, stride 0x7C, matched by an ID field at each
struct's own offset +0x00).

STATUS: address chain LIVE-VERIFIED 2026-08-03.

  - Slot 0 carried 964 deflected samples across a live session while slots
    1-3 stayed identically zero, confirming both the table base/stride and
    the "port 0 is the player" assumption.
  - Direction was cross-checked against real movement: over 909 samples
    where the stick was deflected and the player actually moved, the
    reading predicted travel direction with a 4.62-degree median error
    (next-best sign convention: 76.71 degrees). Sustained single-axis
    holds resolved the signs -- stick Y is NEGATIVE for up, and positive
    X is the camera's +right.

STILL UNCALIBRATED: the deadzone below. Observed full deflection was
+/-56, not the +/-127 an 8-bit range would suggest, so this player's input
method may not produce intermediate values at all; a device that does
could sit under the threshold while genuinely held. Calibrate against an
analogue controller before relying on partial deflection.
"""
from .memory import MemoryError

CONTROLLER_TABLE_BASE = 0x80444AF8
CONTROLLER_STRIDE = 0x7C
CONTROLLER_INDEX = 0  # assumed player 1; unconfirmed
STICK_X_OFFSET = 0x36
STICK_Y_OFFSET = 0x37
STICK_DEADZONE = 24  # see module docstring: still uncalibrated for analogue
                     # input (observed full deflection was +/-56, not +/-127)


def _to_signed_byte(value):
    return value - 256 if value >= 128 else value


class GSinputMovementSource:
    """EXPERIMENTAL -- see module docstring. Fails safe: any read error is
    treated as "no direction held" rather than raised, since a missed
    blocked-cue is far less harmful than one that can never be trusted."""

    def __init__(self, memory):
        self.memory = memory

    def is_direction_held(self):
        base = CONTROLLER_TABLE_BASE + CONTROLLER_INDEX * CONTROLLER_STRIDE
        try:
            x = _to_signed_byte(
                self.memory.u8(base + STICK_X_OFFSET, "movement input stick x"))
            y = _to_signed_byte(
                self.memory.u8(base + STICK_Y_OFFSET, "movement input stick y"))
        except MemoryError:
            return False
        return abs(x) > STICK_DEADZONE or abs(y) > STICK_DEADZONE


class NeverHeldMovementSource:
    """Safe placeholder used whenever no verified input source is wired in
    -- guarantees BlockedMovementReader's cue can never fire, rather than
    silently falling back to the rejected stillness-only heuristic."""

    def is_direction_held(self):
        return False
