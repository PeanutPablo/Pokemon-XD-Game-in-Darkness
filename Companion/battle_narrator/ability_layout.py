"""Read the abilities table's record layout out of the game's own code.

The abilities name/description table at `profile.abilities_table_base` is
the one structure this project reads whose SHAPE a ROM hack has been
observed to change. Pokemon XG 1.2.1 packs 106 abilities into the space
vanilla XD used for 78 by dropping a four-byte field from every record:
the stride goes 12 -> 8, the name ID moves from +4 to +0, and the
description ID from +8 to +4.

Nothing else about that hack is detectable from outside. XG keeps the
disc label (GXXE01 revision 0), the internal name (POKeMON XD), the DOL
section layout, and every one of `profile.engine_signatures` -- correctly,
since none of those things is wrong. So the companion cannot select a
layout by asking "which game is this?", and must not: reading vanilla's
layout on XG resolves ability 1 to "Drizzle" instead of "Aerilate", and
every later index to a different wrong answer, which is precisely the
confident-and-wrong failure this project refuses to ship.

What it can do is read the three instructions that ARE the layout. The
engine's three ability accessors are adjacent, tiny, and each encodes one
of the three constants directly in its immediate field:

    0x801442B0  mulli r4, r3, N     the record stride
    0x80144290  lwz   r3, N(r3)     the name ID's offset in the record
    0x80144278  lwz   r3, N(r3)     the description ID's offset

Across the two builds on hand these three words are the ONLY differences
anywhere in the whole accessor cluster (0x80144200-0x801442D0), which is
what makes them a layout description rather than a coincidence: vanilla
reads 12/+4/+8, XG reads 8/+0/+4, and both were confirmed end to end --
decoding XG's table with the derived layout resolves all 101 of its named
abilities to exactly the names XG's own shipped documentation lists, and
zero of them under vanilla's.

Deriving beats detecting. A heuristic that sniffed the table's contents
(say, "is the first word zero?") would be guessing about data a hack is
free to make ambiguous; these instructions are the game telling us what
it does. If any of the three is not the instruction form expected, this
raises rather than falling back to a default -- an unrecognised accessor
means the assumption underneath the whole lookup is gone, and silence is
the correct output for that."""
from dataclasses import dataclass

from .memory import MemoryError

MULLI_OPCODE = 7
LWZ_OPCODE = 32


def _opcode(word):
    return (word >> 26) & 0x3F


def _register(word, shift):
    return (word >> shift) & 0x1F


def _immediate(word):
    value = word & 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


@dataclass(frozen=True)
class AbilityTableLayout:
    stride: int
    name_offset: int
    description_offset: int


def _mulli_multiplier(word, address):
    if _opcode(word) != MULLI_OPCODE:
        raise MemoryError(
            f"ability stride site {address:#010x} is not a mulli "
            f"(word {word:#010x})")
    return _immediate(word)


def _lwz_displacement(word, address, label):
    if _opcode(word) != LWZ_OPCODE:
        raise MemoryError(
            f"ability {label} site {address:#010x} is not a lwz "
            f"(word {word:#010x})")
    if _register(word, 21) != _register(word, 16):
        # Every one of these accessors is the one-line `return x->field`
        # shape, loading through the same register it was handed. A
        # different pair of registers is a different function.
        raise MemoryError(
            f"ability {label} site {address:#010x} loads across registers "
            f"(word {word:#010x})")
    return _immediate(word)


def derive_ability_layout(memory, profile):
    """The live record layout, read from the three accessor instructions."""
    stride = _mulli_multiplier(
        memory.u32(profile.abilities_stride_instruction, "ability stride"),
        profile.abilities_stride_instruction)
    name_offset = _lwz_displacement(
        memory.u32(profile.abilities_name_instruction, "ability name offset"),
        profile.abilities_name_instruction, "name")
    description_offset = _lwz_displacement(
        memory.u32(profile.abilities_description_instruction,
                   "ability description offset"),
        profile.abilities_description_instruction, "description")

    # The three have to describe one coherent record. Each field is a u32
    # and both must fit inside the stride; equal offsets would mean the
    # name and description are the same word, which no build does.
    if stride <= 0:
        raise MemoryError(f"ability record stride {stride} is not positive")
    if name_offset == description_offset:
        raise MemoryError(
            f"ability name and description share offset {name_offset}")
    for label, offset in (("name", name_offset),
                          ("description", description_offset)):
        if offset < 0 or offset + 4 > stride:
            raise MemoryError(
                f"ability {label} offset {offset} does not fit a "
                f"{stride}-byte record")
    return AbilityTableLayout(stride, name_offset, description_offset)
