"""Render a live message ID to the text the game itself would draw.

Why this exists
---------------
`RuntimeMessageCatalog.text()` resolves a message ID to its raw GSchar bytes
out of the game's own loaded string tables. That is only half the job: the
shipped strings are *templates*. "Sparky opened the door to its heart!" is
stored as

    <FFFF>0x32 opened the door to its heart!<FFFF>0x03

where `0x32` is a placeholder the engine fills in at draw time. A reader
that drops control codes speaks "opened the door to its heart!" with no
subject; a reader that keeps them speaks mojibake. Neither is usable.

How the engine does it
----------------------
`GSmsgMakeGScharStr` (0x80105FEC) walks the raw string; on the `0xFFFF`
escape it reads the next byte as an opcode and indexes `msgctrlcode`, whose
pointer lives at `[[0x804E8348] + 0x24]`. Each entry's flag bits 6-7 select
what the handler returns: nothing, a GSchar pointer, or another message ID.
Every handler is an accessor over one global in the `msgvar` block
(0x804EB1F0-0x804EB2CC), which the running code writes immediately before
asking for the box. Reproducing the substitution is therefore a matter of
reading the same global the same handler would.

That whole table is transcribed in `battle_opcodes.REGISTRY`, including the
battle half (0x0D-0x2A) this module used to decline.

The safety contract
-------------------
`render()` returns a `Rendering`, and a caller may speak it only when
`is_speakable` is true. That requires: every opcode recognised, every
required argument resolved, the result nonempty, and the result free of the
double-encoding signature. An unresolved opcode suppresses the WHOLE
message -- there is no partial output, because "Go! " and
"It doesn't affect..." are worse than silence. `Rendering.unresolved` names
exactly which opcode failed and why, so a gap is diagnosable from the log
instead of merely audible.

On msgCtrlVal, and a correction
-------------------------------
`fightMsgctrlSetValue` (fightMenu.s:0x802370EC) diverts writes for opcodes
0x0F/0x0D/0x28/0x0E into a four-entry cache at `msgCtrlVal` (0x804187D0)
while `ServerWork[7] == 2`. An earlier pass read that as "these opcodes have
two possible READ sources". They do not. `fightMenuOpenMsg`
(fightMenu.s:0x80237264) flushes every non-zero cache entry back through
`msgctrlSetValue` into the ordinary msgvar **and zeroes the cache** before
the window is opened. By the time a message is visible -- the only time this
project can see it -- the values are always in the ordinary globals. That is
why `resolver.move_learning_sample`, which read the cache directly, logged
`invalid address 0x00000000` for most of its samples.
"""
from .battle_opcodes import (
    BATTLER_NICKNAME,
    ITEM_NAME,
    MESSAGE,
    MONEY,
    MOVE_NAME,
    NOTHING,
    NUMBER,
    PAGE_BREAK,
    PLAYER_NAME,
    REGISTRY,
    SIDE_NAME,
    SIDE_NAME_MESSAGES,
    SPACE,
    SPECIES_NAME,
    TIME,
    TEXT_POINTER,
    UNSUPPORTED,
    EXTRA_BYTES,
)
from .memory import MemoryError
from .text_safety import is_double_encoded

MANAGER_ROOT = 0x804E8348
CTRL_TABLE_OFFSET = 0x24
"""`msgctrlcode` pointer lives at [[MANAGER_ROOT] + 0x24]."""
CTRL_TABLE_ENTRIES = 111
CTRL_TABLE_STRIDE = 8
CTRL_HANDLER_OFFSET = 0x04

MAX_STRING_CHARS = 512
MAX_NESTED_LOOKUPS = 4
"""A mode-2 substitution splices in another string, which may itself
contain control codes. The engine bounds its own control stack at 4
(`GSmsgMakeGScharStr` panics past depth 3); match that rather than
recursing until something blows up."""

MAX_NICKNAME_CHARS = 11

# --- database roots, for the mode-2 handlers that map an ID to a name
# message ID. Counts are a DOUBLE indirection ([[symbol]]) and bases a
# single one ([symbol]); that asymmetry is straight off the disassembly of
# pokemonDataBiosGetPtr / wazaDataBiosGetPtr / itemDataBiosGetPtr, and
# reading both the same way silently yields garbage.
POKEMON_DATA_NUMBER, POKEMON_DATA = 0x804EA634, 0x804EA638
POKEMON_DATA_STRIDE, POKEMON_NAME_OFFSET = 0x124, 0x18
WAZA_DATA_NUMBER, WAZA_DATA = 0x804E87F0, 0x804E87F4
WAZA_DATA_STRIDE, WAZA_NAME_OFFSET = 0x38, 0x20
ITEM_INDEX_NUMBER, ITEM_INDEX = 0x804E8A00, 0x804E8A04
ITEM_PRIME_NUMBER, ITEM_PRIME = 0x804E8A08, 0x804E8A0C
ITEM_DATA_STRIDE, ITEM_NAME_OFFSET = 0x28, 0x10
ITEM_FALLBACK_MESSAGE = 0x3AD2
"""msgctrlItem substitutes message 15058 when the item lookup yields 0 --
the engine's own "nothing" name, not a value invented here."""


class Rendering:
    """One attempt at rendering one message.

    `subjects` maps a battler-nickname opcode to the `FightOutPokemon*` it
    resolved through, so a caller can hand that to the canonical identity
    layer for duplicate disambiguation without this module knowing anything
    about identity.
    """

    __slots__ = ("message_id", "text", "opcodes", "unresolved", "subjects")

    def __init__(self, message_id, text, opcodes, unresolved, subjects):
        self.message_id = message_id
        self.text = text
        self.opcodes = tuple(opcodes)
        self.unresolved = tuple(unresolved)
        self.subjects = dict(subjects)

    @property
    def is_speakable(self):
        return bool(self.text) and not self.unresolved

    def __repr__(self):
        return (f"<Rendering {self.message_id} text={self.text!r} "
                f"unresolved={self.unresolved!r}>")


class MessageRenderer:
    """Read-only. Holds no cache: the msgvars are overwritten before every
    box, and string tables are swapped as maps load, so a cached render
    would speak the previous message's subject."""

    def __init__(self, memory, profile, catalog, player_name_provider=None):
        self.memory = memory
        self.profile = profile
        self.catalog = catalog
        self.player_name_provider = player_name_provider

    # -- plumbing ---------------------------------------------------------

    def _valid(self, pointer):
        return (
            isinstance(pointer, int)
            and self.profile.mem1_start <= pointer < self.profile.mem1_end
        )

    def _u16(self, address, label):
        return self.memory.u16(address, label)

    def _u32(self, address, label):
        return self.memory.u32(address, label)

    def _global(self, opcode):
        """Address of the msgvar this opcode reads, or None when the
        profile does not name one."""
        if opcode.source is None:
            return None
        return getattr(self.profile, opcode.source, None)

    def _value(self, opcode):
        address = self._global(opcode)
        if address is None:
            raise MemoryError(f"no profile field for {opcode.source!r}")
        if opcode.width == 2:
            return self._u16(address, opcode.name)
        return self._u32(address, opcode.name)

    def verify_dispatch_table(self):
        """Check the live `msgctrlcode` table still holds the handler
        addresses `REGISTRY` was transcribed from.

        Returns a list of (opcode, expected, found) mismatches, empty when
        the table matches. Callers should treat a non-empty result as "do
        not substitute" rather than as a crash: a hack that relocated the
        message system would otherwise have this module confidently reading
        the wrong global and speaking a plausible-looking wrong name."""
        work = self._u32(MANAGER_ROOT, "message work pointer")
        if not self._valid(work):
            raise MemoryError("message work pointer is not in MEM1")
        table = self._u32(work + CTRL_TABLE_OFFSET, "msgctrlcode pointer")
        if not self._valid(table):
            raise MemoryError("msgctrlcode pointer is not in MEM1")
        mismatches = []
        for code, opcode in sorted(REGISTRY.items()):
            if code >= CTRL_TABLE_ENTRIES:
                continue
            found = self._u32(
                table + code * CTRL_TABLE_STRIDE + CTRL_HANDLER_OFFSET,
                f"msgctrlcode handler 0x{code:02X}")
            if found != opcode.handler:
                mismatches.append((code, opcode.handler, found))
        return mismatches

    # -- the individual substitution sources -------------------------------

    def _gschar_at(self, address, depth):
        """Decode GSchar text at `address`, recursively expanding any
        control codes it contains itself.

        Nested failures are raised rather than accumulated, so the opcode
        that pulled this text in is the one recorded as unresolved -- a
        caller reading the log then sees which substitution broke, not an
        anonymous inner opcode."""
        raw = self.memory.bytes(
            address, MAX_STRING_CHARS * 2, "substituted text", 1)
        text, _seen, unresolved, _subjects = self._decode(raw, depth)
        if unresolved:
            raise MemoryError(
                f"substituted text has unresolved opcodes "
                f"{[code for code, _ in unresolved]}")
        return text

    def _player_name(self):
        if self.player_name_provider is None:
            raise MemoryError("no player-name provider")
        name = self.player_name_provider()
        if not name:
            raise MemoryError("player name is empty")
        return name

    def _species_name_id(self, data_id):
        count_pointer = self._u32(POKEMON_DATA_NUMBER, "species count pointer")
        if not self._valid(count_pointer):
            raise MemoryError("species count pointer is not in MEM1")
        if data_id >= self._u32(count_pointer, "species count"):
            raise MemoryError(f"species id {data_id} is out of range")
        base = self._u32(POKEMON_DATA, "species data base")
        if not self._valid(base):
            raise MemoryError("species data base is not in MEM1")
        return self._u32(
            base + data_id * POKEMON_DATA_STRIDE + POKEMON_NAME_OFFSET,
            "species name message id")

    def _move_name_id(self, move_id):
        count_pointer = self._u32(WAZA_DATA_NUMBER, "move count pointer")
        base = self._u32(WAZA_DATA, "move data base")
        if not self._valid(count_pointer) or not self._valid(base):
            raise MemoryError("move data pointers are not in MEM1")
        # wazaDataBiosGetPtr returns record 0 -- not NULL -- for an
        # out-of-range ID, so an invalid move speaks the placeholder name
        # the game itself would show rather than vanishing.
        count = self._u32(count_pointer, "move count")
        record = base if move_id >= count else base + move_id * WAZA_DATA_STRIDE
        return self._u32(record + WAZA_NAME_OFFSET, "move name message id")

    def _item_name_id(self, item_id):
        index_count_pointer = self._u32(ITEM_INDEX_NUMBER, "item index count pointer")
        index_base = self._u32(ITEM_INDEX, "item index base")
        prime_count_pointer = self._u32(ITEM_PRIME_NUMBER, "item count pointer")
        prime_base = self._u32(ITEM_PRIME, "item data base")
        for pointer in (index_count_pointer, index_base,
                        prime_count_pointer, prime_base):
            if not self._valid(pointer):
                return ITEM_FALLBACK_MESSAGE
        if item_id >= self._u32(index_count_pointer, "item index count"):
            return ITEM_FALLBACK_MESSAGE
        dense = self._u16(index_base + item_id * 2, "item dense index")
        if dense >= self._u32(prime_count_pointer, "item count"):
            return ITEM_FALLBACK_MESSAGE
        name_id = self._u32(
            prime_base + dense * ITEM_DATA_STRIDE + ITEM_NAME_OFFSET,
            "item name message id")
        return name_id or ITEM_FALLBACK_MESSAGE

    def _battler_nickname(self, opcode, subjects):
        """`msgctrlAttackMons` and its siblings, which in every non-link
        battle reduce to `fightOutPokemonGetNicknamePtr(<global>)`."""
        p = self.profile
        fight_out = self._value(opcode)
        if not self._valid(fight_out):
            raise MemoryError(
                f"{opcode.name}: FightOutPokemon 0x{fight_out:08X}")
        fight_pokemon = self._u32(
            fight_out + p.fight_out_fight_pokemon_offset,
            f"{opcode.name} FightPokemon")
        if not self._valid(fight_pokemon):
            raise MemoryError(f"{opcode.name}: no FightPokemon attached")
        nickname = self.memory.gschar(
            fight_pokemon + p.health_nickname_offset,
            MAX_NICKNAME_CHARS, f"{opcode.name} nickname", 2)
        if not nickname.strip():
            raise MemoryError(f"{opcode.name}: nickname is empty")
        subjects[opcode.code] = fight_out
        return nickname

    def _side_name(self, opcode, depth):
        """`_msgctrlSideName`: a whole-side qualifier ("Foe's party" /
        "Ally's party"), chosen by `fightTargetIsHostSide` and the opcode's
        grammatical particle. Side is derived here from which trainer's
        party array the battler physically sits in, which is the same
        answer without needing to call into the game."""
        from .battle_identity import party_position

        p = self.profile
        fight_out = self._value(opcode)
        if not self._valid(fight_out):
            raise MemoryError(f"{opcode.name}: FightOutPokemon is null")
        fight_pokemon = self._u32(
            fight_out + p.fight_out_fight_pokemon_offset,
            f"{opcode.name} FightPokemon")
        position = party_position(p, fight_pokemon)
        if position is None:
            raise MemoryError(f"{opcode.name}: battler is not in a party")
        message_id = SIDE_NAME_MESSAGES[
            (position.is_player_side, opcode.particle)]
        return self._message(message_id, depth + 1)

    def _substitute(self, opcode, depth, subjects):
        """Text this control code contributes. Raises `MemoryError` when a
        required value cannot be resolved -- the caller turns that into a
        suppressed message, never a gap in a sentence."""
        kind = opcode.kind
        if kind == NOTHING:
            return ""
        if kind == SPACE:
            return " "
        if kind == UNSUPPORTED:
            raise MemoryError(f"{opcode.name}: no resolution route")
        if kind == PLAYER_NAME:
            return self._player_name()
        if kind == NUMBER:
            return f"{self._value(opcode)}"
        if kind == MONEY:
            # msgctrlMoney passes flag 4 to _msgctrlMakeDigit, the branch
            # that inserts the locale separator every three digits.
            return f"{self._value(opcode):,}"
        if kind == TIME:
            hours, remainder = divmod(self._value(opcode), 3600)
            return f"{hours}:{remainder // 60:02d}"
        if depth >= MAX_NESTED_LOOKUPS:
            raise MemoryError(f"{opcode.name}: nesting limit reached")
        if kind == BATTLER_NICKNAME:
            return self._battler_nickname(opcode, subjects)
        if kind == SIDE_NAME:
            return self._side_name(opcode, depth)
        if kind == TEXT_POINTER:
            pointer = self._value(opcode)
            if not self._valid(pointer):
                raise MemoryError(
                    f"{opcode.name}: text pointer 0x{pointer:08X}")
            return self._gschar_at(pointer, depth + 1)
        if kind == MESSAGE:
            return self._message(self._value(opcode), depth + 1)
        if kind == SPECIES_NAME:
            return self._message(
                self._species_name_id(self._value(opcode)), depth + 1)
        if kind == MOVE_NAME:
            return self._message(
                self._move_name_id(self._value(opcode)), depth + 1)
        if kind == ITEM_NAME:
            return self._message(
                self._item_name_id(self._value(opcode)), depth + 1)
        raise MemoryError(f"{opcode.name}: unhandled kind {kind!r}")

    # -- decoding ----------------------------------------------------------

    def _decode(self, raw, depth, seen=None, unresolved=None, subjects=None):
        seen = seen if seen is not None else []
        unresolved = unresolved if unresolved is not None else []
        subjects = subjects if subjects is not None else {}
        out = []
        index = 0
        while index + 1 < len(raw):
            value = (raw[index] << 8) | raw[index + 1]
            if value == 0:
                break
            if value != 0xFFFF:
                # A control opcode is only meaningful straight after the
                # 0xFFFF escape. Comparing a bare character against the
                # opcode set eats real letters -- 0x59 is both the SPEAKER
                # opcode and the letter "Y".
                out.append(chr(value))
                index += 2
                continue
            if index + 2 >= len(raw):
                break
            code = raw[index + 2]
            index += 3 + EXTRA_BYTES.get(code, 0)
            opcode = REGISTRY.get(code)
            seen.append(code)
            if opcode is None:
                # Not in the shipped table at all. Its argument width is
                # unknown, so the rest of this string may already be
                # garbage -- refuse the whole message.
                unresolved.append((code, "opcode is not in msgctrlcode"))
                continue
            if opcode.kind == PAGE_BREAK:
                # Dialogue End / Clear Window terminate the page. Later
                # pages are separate boxes and get their own announcement.
                break
            try:
                out.append(self._substitute(opcode, depth, subjects))
            except MemoryError as exc:
                unresolved.append((code, str(exc)))
        return "".join(out), seen, unresolved, subjects

    def _message(self, message_id, depth):
        """Nested lookup. Failures here propagate as MemoryError so the
        enclosing opcode is recorded as unresolved."""
        if not message_id:
            raise MemoryError("nested message id is zero")
        address = self.catalog.address_of(message_id)
        if address is None:
            raise MemoryError(f"message {message_id} is not loaded")
        raw = self.memory.bytes(
            address, MAX_STRING_CHARS * 2, "message text", 1)
        text, _seen, nested_unresolved, _subjects = self._decode(raw, depth)
        if nested_unresolved:
            raise MemoryError(
                f"message {message_id} has unresolved opcodes "
                f"{[code for code, _ in nested_unresolved]}")
        return text

    # -- public ------------------------------------------------------------

    def render(self, message_id):
        """Full result for `message_id`, including why it failed if it did."""
        address = self.catalog.address_of(message_id)
        if address is None:
            return Rendering(message_id, None, (),
                             ((None, "message is not loaded"),), {})
        raw = self.memory.bytes(
            address, MAX_STRING_CHARS * 2, "message text", 1)
        rendered, seen, unresolved, subjects = self._decode(raw, 0)
        text = " ".join(rendered.split()).strip()
        # A page whose speaker marker was consumed can open with a bare
        # ": " -- the same artefact runtime_messages.py and shop_messages.py
        # both swallow rather than speak.
        if text.startswith(": "):
            text = text[2:].strip()
        if text and is_double_encoded(text):
            unresolved = list(unresolved) + [
                (None, "rendered text carries a double-encoding signature")]
        if not text:
            unresolved = list(unresolved) + [(None, "rendered text is empty")]
        if unresolved:
            # `text` is DISCARDED, not merely flagged. Leaving a partial
            # sentence on the result is a footgun: some caller eventually
            # reads `.text` without checking `.is_speakable` and speaks
            # "Go! " or "is frozen solid!". The reason survives in
            # `unresolved`, which is what the log needs.
            text = None
        return Rendering(message_id, text, seen, unresolved, subjects)

    def render_bytes(self, raw):
        """Render one already-located GSchar page through live msgvars."""
        rendered, seen, unresolved, subjects = self._decode(bytes(raw), 0)
        text = " ".join(rendered.split()).strip()
        if text.startswith(": "):
            text = text[2:].strip()
        if text and is_double_encoded(text):
            unresolved = list(unresolved) + [
                (None, "rendered text carries a double-encoding signature")]
        if not text:
            unresolved = list(unresolved) + [(None, "rendered text is empty")]
        if unresolved:
            text = None
        return Rendering(None, text, seen, unresolved, subjects)

    def text(self, message_id):
        """Speech-ready text, or None when the message cannot be rendered
        completely. Kept for callers that only need the happy path."""
        rendering = self.render(message_id)
        return rendering.text if rendering.is_speakable else None
