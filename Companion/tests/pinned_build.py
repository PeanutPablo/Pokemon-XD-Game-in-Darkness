"""Which build's game data is installed, for tests pinned to one of them.

Some tests here deliberately assert against REAL shipped message
templates rather than sentences typed into Python -- see
`test_battle_messages.py`'s own docstring for why that is the right call.
The cost of it is that the expected sentence belongs to whichever game
generated `Companion/_dialogue_extraction`, and a player running Pokemon
XG regenerates that tree from their XG disc. XG rewrites the dialogue: it
turns "EXP. Points!" into "Exp. Points!", among 181 replaced move names
and a great deal else. Those tests then fail, and the failure says
nothing about the code.

Committing a fixture instead is not open to us -- the templates are
copyrighted game data that must never enter this repository -- so the
tests can only read whatever the player installed. What they can do is
say which build they were pinned against, and skip rather than fail when
that is not what is installed.

The fingerprint is the raw GSchar bytes of one shipped template, not a
game ID or a disc label: the disc label is identical between the two
builds, and the bytes are exactly the thing the expectations depend on.
A build whose template bytes match is a build whose decoded sentences
match.
"""
from pathlib import Path

from battle_narrator.messages import FightCommonCatalog

EXTRACTION = Path(__file__).resolve().parents[1] / "_dialogue_extraction"

FINGERPRINT_MESSAGE_ID = 20003
"""The battle EXP message. Chosen because it carries opcodes as well as
text, so it moves if either the wording or the substitution scheme does."""

VANILLA_US_FINGERPRINT = (
    "ffff0d0020006700610069006e006500640020ffff0effff00ffff2f0020004500580050"
    "002e00200050006f0069006e007400730021ffff030000"
)
"""Vanilla US XD's bytes for that message ("... EXP. Points!").
Pokemon XG 1.2.1 differs here ("Exp. Points!")."""


def _fingerprint_of(directory):
    try:
        message = FightCommonCatalog(directory).get(FINGERPRINT_MESSAGE_ID)
    except Exception:
        return None
    return message.raw.hex() if message is not None else None


def installed_fingerprint():
    """The default tree's bytes for the fingerprint message, or None."""
    return _fingerprint_of(EXTRACTION)


def vanilla_extraction():
    """The installed data tree generated from vanilla US XD, or None.

    Searched rather than assumed, because data now lives in one
    subdirectory per disc (see `battle_narrator/game_build.py`) and the
    player may have several installed, in any order. Tests that assert
    against vanilla's shipped text need that specific tree, not whichever
    one happens to be first."""
    candidates = [EXTRACTION]
    try:
        candidates += sorted(
            child for child in EXTRACTION.iterdir() if child.is_dir())
    except OSError:
        pass
    for directory in candidates:
        if _fingerprint_of(directory) == VANILLA_US_FINGERPRINT:
            return directory
    return None


def is_vanilla_us():
    return vanilla_extraction() is not None


SKIP_REASON = (
    "these expectations are pinned to vanilla US XD's shipped text, and "
    "Companion/_dialogue_extraction was generated from a different build "
    "(template {id} does not match). This is a fixture limitation, not a "
    "product failure: the narrator reads whichever build is installed. "
    "Re-pin them by running this suite against a vanilla extraction."
).format(id=FINGERPRINT_MESSAGE_ID)
