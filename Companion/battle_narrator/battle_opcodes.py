"""The complete `msgctrlcode` dispatch table, as data.

Source of truth
---------------
Transcribed opcode-by-opcode from the shipped table in the ORIGINAL
`main.dol` (`msgctrlcode = .data:0x80404710`, size `0x378` = 111 entries of
8 bytes: `+0x00 u8 flags`, `+0x04 u32 handler`), with every handler address
matched against `xd-decomp/config/GXXE01/symbols.txt`. `flags >> 6` is the
return mode the engine's own `GSmsgMakeGScharStr` switches on:

    0  formatting only -- contributes no characters
    1  handler returns a pointer to GSchar text
    2  handler returns another message ID, spliced in recursively

Every entry below therefore records what the engine actually does, not what
a sentence appears to mean. `MessageRenderer.verify_dispatch_table()`
re-reads the live table and fails loudly if a build moved a handler.

Why the battle half was missing
-------------------------------
`message_render.py` originally transcribed only the non-battle opcodes and
declared 0x0D-0x2A "deliberately NOT implemented", because those handlers
had not been traced. `narrator.py` filled the hole with ~51 retyped English
sentences and a per-message-ID opcode allow-list, which is why every message
nobody enumerated stayed silent. All 47 opcodes that any `fight_common`
message actually uses are covered here.

The two null entries
--------------------
Opcodes 0x0B and 0x0C are used by real messages (20414-20416, 20387-20390)
but their table entries hold flags `0x00` and handler `0x00000000`. Mode 0
means "contributes no text", so they are registered as formatting rather
than treated as unknown -- they are in the shipped table, just inert.

What is NOT here
----------------
Nothing decides an opcode's meaning from the visible sentence. Where a
handler does real work rather than returning a global, the work is recorded
as a `kind` and reproduced by the renderer:

- `msgctrlAttackMons` and its three siblings dereference a
  `FightOutPokemon*` and return `fightOutPokemonGetNicknamePtr(...)`.
- `_msgctrlSideName` maps a `FightOutPokemon*` plus a grammatical particle
  onto one of six whole-side messages (20327-20332).
- `msgctrlDigit` / `msgctrlMoney` format an integer through
  `_msgctrlMakeDigit`; money passes flag 4, which is the branch that
  inserts a thousands separator.
"""

# --- return modes (flags >> 6)
FORMAT_MODE = 0
TEXT_MODE = 1
MESSAGE_MODE = 2

# --- what the renderer must do with the value
NOTHING = "nothing"
"""Pure formatting; contributes no characters."""
SPACE = "space"
"""A line break. The engine starts a new line; speech wants a space."""
PAGE_BREAK = "page-break"
"""Dialogue End / Clear Window. Terminates this page."""
TEXT_POINTER = "text-pointer"
"""Global holds a pointer to GSchar text."""
BATTLER_NICKNAME = "battler-nickname"
"""Global holds a `FightOutPokemon*`; the handler returns its nickname."""
SIDE_NAME = "side-name"
"""Global holds a `FightOutPokemon*`; the handler returns one of the
whole-side messages 20327-20332 depending on side and particle."""
NUMBER = "number"
"""Global holds an integer to format with no grouping."""
MONEY = "money"
"""Global holds an integer to format with thousands grouping."""
TIME = "time"
"""Global holds elapsed seconds; msgctrlTime renders hours and minutes."""
MESSAGE = "message"
"""Global holds a message ID to splice in."""
SPECIES_NAME = "species-name"
MOVE_NAME = "move-name"
ITEM_NAME = "item-name"
PLAYER_NAME = "player-name"
"""Resolved from save data, not from a msgvar."""
UNSUPPORTED = "unsupported"
"""Recognised opcode with no resolution route. Forces suppression."""

# --- particles for the side-name opcodes, matching `_msgctrlSideName`'s
# second argument. The three variants are the Japanese case particles the
# original text used; in English they select between "Foe's party",
# "Foe's party is", and a third identical form.
PARTICLE_HA = 0
PARTICLE_WO = 1
PARTICLE_NO = 2


class Opcode:
    """One row of `msgctrlcode`."""

    __slots__ = ("code", "name", "handler", "mode", "kind", "source",
                 "extra_bytes", "particle", "width")

    def __init__(self, code, name, handler, mode, kind, source=None,
                 extra_bytes=0, particle=None, width=4):
        self.code = code
        self.name = name
        self.handler = handler
        self.mode = mode
        self.kind = kind
        # Attribute name on the profile, resolved late so a profile can
        # move an address without touching this table.
        self.source = source
        self.extra_bytes = extra_bytes
        self.particle = particle
        # Size of the msgvar itself, from symbols.txt. Getting this wrong
        # is silent: a u16 read as u32 picks up the neighbouring variable's
        # high bytes and yields a plausible-looking wrong ID.
        self.width = width

    @property
    def contributes_text(self):
        return self.kind not in (NOTHING, SPACE, PAGE_BREAK)

    def __repr__(self):
        return f"<Opcode 0x{self.code:02X} {self.name} {self.kind}>"


def _o(code, name, handler, mode, kind, source=None, extra_bytes=0,
       particle=None, width=4):
    return Opcode(code, name, handler, mode, kind, source, extra_bytes,
                  particle, width)


REGISTRY = {entry.code: entry for entry in (
    # --- formatting -----------------------------------------------------
    _o(0x00, "new line", 0x80154E60, FORMAT_MODE, SPACE),
    _o(0x01, "new line", 0x80154E60, FORMAT_MODE, SPACE),
    _o(0x02, "dialogue end", 0x80154DDC, FORMAT_MODE, PAGE_BREAK),
    _o(0x03, "clear window", 0x80154B90, FORMAT_MODE, PAGE_BREAK),
    _o(0x04, "kanji", 0x80154B4C, FORMAT_MODE, NOTHING),
    _o(0x05, "furigana start", 0x80154B3C, FORMAT_MODE, NOTHING),
    _o(0x06, "furigana end", 0x80154B2C, FORMAT_MODE, NOTHING),
    _o(0x07, "change font", 0x80154AC4, FORMAT_MODE, NOTHING, extra_bytes=1),
    _o(0x08, "change colour", 0x80154A50, FORMAT_MODE, NOTHING, extra_bytes=4),
    _o(0x09, "pause", 0x801548DC, FORMAT_MODE, NOTHING, extra_bytes=1),
    # 0x0B / 0x0C: RESOLVED 2026-08-06 as inert layout markers, zero
    # argument bytes. Their shipped table entries hold flags 0x00 and
    # handler 0x00000000 -- mode 0, "contributes no characters" -- and the
    # nine messages that use them are all MENU PANELS rather than battle
    # sentences, each opening with the marker immediately before a colour
    # code: 20387 "<SCOL>[0x0C]PP TYPE/", 20388, 20389 "Which move should
    # be forgotten?", 20390 "Yes\nNo", 20391 "Switch which moves?", 20392,
    # and 20414/20415/20416 "Win"/"Loss"/"Tie". Consistent with a panel
    # layout directive. Zero extra bytes is confirmed the same way every
    # other opcode's width is: they are absent from the string format's
    # k2ByteChars/k5ByteChars sets, and the surrounding text of all nine
    # decodes cleanly on that assumption.
    #
    # Aside for the Yes/No work: 20390 is the battle Yes/No panel's own
    # label string, which is an authoritative resource for the labels
    # `menus.yes_no_focus` currently hardcodes.
    _o(0x0B, "panel layout marker", 0x00000000, FORMAT_MODE, NOTHING),
    _o(0x0C, "panel layout marker", 0x00000000, FORMAT_MODE, NOTHING),

    # --- battle event strings -------------------------------------------
    _o(0x0D, "event string 0", 0x8015426C, TEXT_MODE, TEXT_POINTER,
       "ev_str_buf0"),
    _o(0x0E, "event string 1", 0x80154264, TEXT_MODE, TEXT_POINTER,
       "ev_str_buf1"),
    _o(0x41, "event string 2", 0x8015425C, TEXT_MODE, TEXT_POINTER,
       "ev_str_buf2"),

    # --- battler subjects (FightOutPokemon* -> nickname) ------------------
    _o(0x0F, "attacking Pokemon", 0x801541C4, TEXT_MODE, BATTLER_NICKNAME,
       "attack_mons"),
    _o(0x10, "defending Pokemon", 0x8015412C, TEXT_MODE, BATTLER_NICKNAME,
       "defence_mons"),
    # 0x11: the Pokemon whose MOVE OR ACTION IS UNAVAILABLE. Resolved from
    # its four writers, not from the sentences. Three are branches of
    # `fightSeqAttackPokemonJoutaiCheck` -- Disable, Taunt and Imprison --
    # each of which calls `fightOutPokemonInitJoutaiKeep`, sets a
    # `*NoAttackFlag`, ORs 0x8 into `ServerStatusFlag`, and passes the
    # BLOCKED battler; the other two are the player's own command/move menu
    # in the branch where `fightOutPokemonCheckFightActionWazaSelect` /
    # `fightOutPokemonCheckCanOutOkWazaBanme` says the move cannot be
    # chosen. All six shipped templates that use it agree: 20197 "has no
    # moves left!", 20198 "is disabled!", 20199 TORMENT, 20200 TAUNT,
    # 20201 "sealed". Nothing to do with a link-battle "client".
    _o(0x11, "blocked Pokemon", 0x80154094, TEXT_MODE, BATTLER_NICKNAME,
       "client_mons"),
    _o(0x12, "secondary-effect Pokemon", 0x80153FFC, TEXT_MODE,
       BATTLER_NICKNAME, "tsuika_mons"),
    # 0x1E: the FightFloor's APPOINTED Pokemon -- the one the current effect
    # is happening to or because of. Its canonical setter is
    # `fightFloor_SetAppointPokemonPtr` (指定 = appointed/designated), which
    # writes this opcode AND opcode 0x1C (`_SPEABI_NAMEC`) as a PAIR: 0x1E
    # gets the battler, 0x1C gets that same battler's ability name via
    # `fightOutPokemonGetTokuseiDataId -> pokemonTokuseiDataBiosGetName`.
    # When the pointer is invalid BOTH are zeroed together. `EscapeNGCheck`
    # and `fightFloorSetStatus` do the same. That pairing is why most of
    # its 41 templates read "[0x1E]'s [Ability 28] ...", but it is NOT
    # only an ability holder -- 20144 "[0x1E] is hurt by SPIKES!" and
    # 20185 "SNATCHED [0x1E]'s move!" have no ability at all, so the
    # accurate name is the game's own.
    _o(0x1E, "appointed Pokemon", 0x80153F0C, TEXT_MODE, BATTLER_NICKNAME,
       "clientnowork"),

    # --- names the game has already rendered to text ----------------------
    _o(0x13, "player battle name", 0x80153FF4, TEXT_MODE, TEXT_POINTER,
       "my_name"),
    _o(0x14, "sent-out Pokemon", 0x80153FEC, TEXT_MODE, TEXT_POINTER,
       "my_mons"),
    _o(0x15, "sent-out Pokemon 2", 0x80153FE4, TEXT_MODE, TEXT_POINTER,
       "my_mons2"),
    _o(0x16, "foe sent-out Pokemon", 0x80153FDC, TEXT_MODE, TEXT_POINTER,
       "enemy_mons"),
    _o(0x17, "foe sent-out Pokemon 2", 0x80153FD4, TEXT_MODE, TEXT_POINTER,
       "enemy_mons2"),
    _o(0x18, "foe team Pokemon", 0x80153FCC, TEXT_MODE, TEXT_POINTER,
       "enemy_tmons"),
    _o(0x19, "foe team Pokemon 2", 0x80153FC4, TEXT_MODE, TEXT_POINTER,
       "enemy_tmons2"),
    _o(0x1A, "ability A", 0x80153FBC, TEXT_MODE, TEXT_POINTER,
       "speabi_name_a"),
    _o(0x1B, "ability D", 0x80153FB4, TEXT_MODE, TEXT_POINTER,
       "speabi_name_d"),
    _o(0x1C, "ability C", 0x80153FAC, TEXT_MODE, TEXT_POINTER,
       "speabi_name_c"),
    _o(0x1D, "ability T", 0x80153FA4, TEXT_MODE, TEXT_POINTER,
       "speabi_name_t"),
    # Two distinct ways the engine names trainers, resolved from the
    # writers (all of `fightActionFlowSyuuryou`, `KaisiPre`,
    # `KaisiNyuujouPokemon`, `WS_POKE_HPDEC_RATE`, `WS_POKE_HPMAX_RATE` and
    # `fightSeqItemExec` follow the same order):
    #
    #   0x22 = fightTrainerGetPrefixNamePtr(trainer)  the CLASS  ("Cipher Peon")
    #   0x23 = fightTrainerGetNamePtr(trainer)        its NAME   ("Greesix")
    #   0x25 = fightTrainerGetNamePtr(otherTrainer)   a SECOND trainer's NAME
    #   0x26 = a THIRD trainer's name, same accessor
    #
    # So 0x22+0x23 describe ONE trainer as class+name, while 0x25/0x26 are
    # two DIFFERENT trainers, both proper names, no class. That is how a
    # two-trainer side is represented: 20309 "[0x25] sent out [0x18]!
    # [0x26] sent out [0x19]!" pairs each trainer's name with its own
    # Pokemon global, where 20305 "[0x22] [0x23] sent out [0x16] and
    # [0x17]!" is ONE trainer sending two.
    _o(0x22, "trainer class", 0x80153BF8, TEXT_MODE, TEXT_POINTER,
       "trainer_type_name"),
    _o(0x23, "trainer name", 0x80153BF0, TEXT_MODE, TEXT_POINTER,
       "trainer_personal_name"),
    _o(0x24, "defeated trainer", 0x80153BE8, TEXT_MODE, TEXT_POINTER,
       "trainer_lose_name"),
    _o(0x25, "first trainer name", 0x80153BE0, TEXT_MODE, TEXT_POINTER,
       "trainer_first_name"),
    _o(0x26, "second trainer name", 0x80153BD8, TEXT_MODE, TEXT_POINTER,
       "trainer_second_name"),
    _o(0x27, "trainer client no", 0x80153BD0, TEXT_MODE, TEXT_POINTER,
       "trainer_client_no_name"),
    _o(0x28, "move name", 0x80153BC8, TEXT_MODE, TEXT_POINTER, "waza_name"),
    _o(0x29, "item name", 0x80153BC0, TEXT_MODE, TEXT_POINTER, "item_name"),
    _o(0x2A, "PC name", 0x80153BB8, TEXT_MODE, TEXT_POINTER, "paso_name"),
    _o(0x4D, "string", 0x80153800, TEXT_MODE, TEXT_POINTER, "msg_string"),
    _o(0x57, "string 2", 0x801536AC, TEXT_MODE, TEXT_POINTER, "msg_string2"),
    _o(0x32, "Pokemon", 0x801547A4, TEXT_MODE, TEXT_POINTER, "msg_pokemon"),
    _o(0x33, "Pokemon 2", 0x8015479C, TEXT_MODE, TEXT_POINTER,
       "msg_pokemon2"),
    _o(0x36, "menu Pokemon", 0x8015472C, TEXT_MODE, TEXT_POINTER,
       "menu_pokemon"),
    _o(0x37, "menu message", 0x80154724, TEXT_MODE, TEXT_POINTER,
       "menu_msg"),
    _o(0x51, "menu message 2", 0x8015471C, TEXT_MODE, TEXT_POINTER,
       "menu_msg2"),

    # --- whole-side qualifiers -------------------------------------------
    _o(0x1F, "attacking side (ha)", 0x80153CC8, TEXT_MODE, SIDE_NAME,
       "side_attack_name_ha", particle=PARTICLE_HA),
    _o(0x20, "attacking side (wo)", 0x80153CA0, TEXT_MODE, SIDE_NAME,
       "side_attack_name_wo", particle=PARTICLE_WO),
    _o(0x21, "attacking side (no)", 0x80153C78, TEXT_MODE, SIDE_NAME,
       "side_attack_name_no", particle=PARTICLE_NO),
    _o(0x42, "defending side (ha)", 0x80153C50, TEXT_MODE, SIDE_NAME,
       "side_defence_name_ha", particle=PARTICLE_HA),
    _o(0x43, "defending side (wo)", 0x80153C28, TEXT_MODE, SIDE_NAME,
       "side_defence_name_wo", particle=PARTICLE_WO),
    _o(0x44, "defending side (no)", 0x80153C00, TEXT_MODE, SIDE_NAME,
       "side_defence_name_no", particle=PARTICLE_NO),

    # --- numbers ----------------------------------------------------------
    _o(0x2F, "quantity", 0x801547E8, TEXT_MODE, NUMBER, "msg_digit"),
    _o(0x30, "quantity 2", 0x801547B4, TEXT_MODE, NUMBER, "msg_digit2"),
    _o(0x34, "menu quantity", 0x80154768, TEXT_MODE, NUMBER, "menu_digit"),
    _o(0x35, "menu quantity 2", 0x80154734, TEXT_MODE, NUMBER, "menu_digit2"),
    _o(0x4B, "money", 0x80153A18, TEXT_MODE, MONEY, "msg_money"),
    _o(0x50, "menu money", 0x80153770, TEXT_MODE, MONEY, "menu_money"),

    # --- database lookups (mode 2) ----------------------------------------
    _o(0x2D, "item", 0x80154850, MESSAGE_MODE, ITEM_NAME, "msg_item",
       width=2),
    _o(0x2E, "item 2", 0x8015481C, MESSAGE_MODE, ITEM_NAME, "msg_item2",
       width=2),
    _o(0x39, "move", 0x801546F4, MESSAGE_MODE, MOVE_NAME, "msg_waza",
       width=2),
    _o(0x4E, "species", 0x801537D8, MESSAGE_MODE, SPECIES_NAME,
       "msg_pokemon_id", width=2),
    _o(0x31, "message", 0x801547AC, MESSAGE_MODE, MESSAGE, "msg_id"),
    _o(0x55, "menu message id", 0x801536BC, MESSAGE_MODE, MESSAGE,
       "menu_msg_id"),
    _o(0x56, "menu message id 2", 0x801536B4, MESSAGE_MODE, MESSAGE,
       "menu_msg_id2"),
    # Speaker. Mode 2: `_Npc` holds a NAME MESSAGE ID, not a trainer record
    # and not a pointer. In battle it is written by
    # `fightTrainerSetNameHearFlag` (fightTrainer.s:0x801F8DDC) from
    # `fightTrainerDB_GetName(trainerDataId)`; in the field it is the
    # already-proven overworld speaker route. Cleared by `_fightFinalize`.
    _o(0x59, "speaker", 0x8015367C, MESSAGE_MODE, MESSAGE, "msg_npc",
       width=2),
    _o(0x58, "tribe", 0x80153684, MESSAGE_MODE, MESSAGE, "msg_tribe",
       width=2),

    # --- player name from save data ---------------------------------------
    _o(0x2B, "player field name", 0x801548B0, TEXT_MODE, PLAYER_NAME),

    # --- remaining formatting ---------------------------------------------
    _o(0x38, "palette", 0x80154954, FORMAT_MODE, NOTHING, extra_bytes=1),
    _o(0x3D, "sound off", 0x80153B8C, FORMAT_MODE, NOTHING),
    _o(0x3E, "sound on", 0x80153B84, FORMAT_MODE, NOTHING),
    _o(0x52, "shadow", 0x80153744, FORMAT_MODE, NOTHING, extra_bytes=1),
    _o(0x53, "align", 0x801536F0, FORMAT_MODE, NOTHING, extra_bytes=1),
    _o(0x54, "talk sound", 0x801536C4, FORMAT_MODE, NOTHING),
    _o(0x5A, "indent off", 0x8015366C, FORMAT_MODE, NOTHING),
    _o(0x5B, "line space", 0x8015363C, FORMAT_MODE, NOTHING, extra_bytes=1),
    _o(0x5C, "baseline bias", 0x8015360C, FORMAT_MODE, NOTHING,
       extra_bytes=1),
    _o(0x5D, "play sound", 0x801535C8, FORMAT_MODE, NOTHING),
    _o(0x5E, "wait sound", 0x80153564, FORMAT_MODE, NOTHING),
    _o(0x6A, "set speaker flag", 0x80153B94, FORMAT_MODE, NOTHING),
    _o(0x6D, "wait input", 0x80154D50, FORMAT_MODE, NOTHING),
    _o(0x6E, "check wait", 0x80154C70, FORMAT_MODE, NOTHING),

    # --- recognised but not resolvable -------------------------------------
    # `msgctrlHizuki` returns Rui's name; XD has no Rui and no global was
    # traced. `msgctrlTime` formats a clock value this project has never
    # needed. Registered so they are RECOGNISED (the renderer knows their
    # argument width) but marked unsupported, which suppresses the whole
    # message rather than dropping a subject silently.
    _o(0x2C, "Rui", 0x80154884, TEXT_MODE, UNSUPPORTED),
    # msgctrlTime divides _Time by 3600 and the remainder by 60, emitting
    # unpadded hours, a colon, and two minute digits.
    _o(0x4C, "time", 0x80153808, TEXT_MODE, TIME, "msg_time"),
    _o(0x64, "time (H)", 0x80154310, TEXT_MODE, UNSUPPORTED),
)}

EXTRA_BYTES = {code: entry.extra_bytes
               for code, entry in REGISTRY.items() if entry.extra_bytes}
"""Argument bytes that follow an opcode in the string itself
(k2ByteChars / k5ByteChars in the string-table format). Kept complete and
separate from the substitution source: skipping the wrong number of
argument bytes desynchronises the rest of the string into garbage, so an
opcode this project chooses not to resolve must still know its width."""

SIDE_NAME_MESSAGES = {
    # (is_host_side, particle) -> message id, from `_msgctrlSideName`
    # (0x80153CF0). Host side is the player's.
    (True, PARTICLE_HA): 0x4F6A,
    (True, PARTICLE_WO): 0x4F6C,
    (True, PARTICLE_NO): 0x4F68,
    (False, PARTICLE_HA): 0x4F69,
    (False, PARTICLE_WO): 0x4F6B,
    (False, PARTICLE_NO): 0x4F67,
}
"""20327-20332. Live text: "Foe's party" / "Ally's party" / "Foe's party is"
/ "Ally's party is" -- whole-side qualifiers, NOT per-battler labels."""

BATTLE_SUBJECT_OPCODES = frozenset(
    code for code, entry in REGISTRY.items()
    if entry.kind == BATTLER_NICKNAME
)
"""Opcodes whose global is a live battler, and which therefore have a
canonical identity the caller can use for disambiguation."""

SEND_OUT_OPCODES = frozenset({0x14, 0x15, 0x16, 0x17})
"""Opcodes naming a Pokemon entering the field. Text only -- see
battle_identity.SEND_OUT_TEXT_OPCODES for the pairing rule."""


def opcode_for(code):
    return REGISTRY.get(code)


def is_recognised(code):
    return code in REGISTRY
