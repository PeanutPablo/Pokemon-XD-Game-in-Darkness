"""The project's single Unicode boundary.

Where text enters
-----------------
Game text is UTF-16BE ("GSchar"). `memory.gschar()` decodes it **once**, one
code unit at a time, into a Python `str`. That is the only decode. From
there the string stays `str` all the way to Tolk, and every file this
project writes is opened with an explicit `encoding="utf-8"`.

What went wrong before
----------------------
Nothing on that runtime path was broken. The corruption came from *source
code*: `resolver.FIXED_SENTENCES[20430]` contained the literal
`"Oh! A Shadow PokÃ©mon!"` -- the UTF-8 bytes of `é` (`C3 A9`) stored as the
two cp1252 characters `Ã` and `©`, then re-encoded as UTF-8. The production
log proves both spellings were spoken from the same message ID: 28 with
`PokÃ©mon`, 1 with `Pokémon`. A hand-typed copy of game text had drifted
from the game's own, and because the result was still *valid* UTF-8, nothing
failed.

The same mechanism bit this project again while writing documentation:
PowerShell's `Get-Content` defaults to the system ANSI codepage, so
`Add-Content -Encoding utf8` on a UTF-8 file double-encodes every non-ASCII
character silently.

The rule
--------
Decode once, at `memory.gschar`. Never re-encode and re-decode. And because
"still valid UTF-8" is not the same as "correct", check: `is_double_encoded`
recognises the signature and the renderer refuses to speak a string that
carries it, rather than reading mojibake aloud.

This check is cheap and one-directional: legitimate game text such as
"Pokémon" cannot be mistaken for double-encoded, because `é` alone is not a
valid UTF-8 sequence when re-encoded through cp1252 (see the tests).
"""

# The characters a cp1252 misread of UTF-8 lead bytes produces. Their
# presence is necessary, not sufficient -- the round-trip below decides.
_MOJIBAKE_LEAD = frozenset("ÂÃÅâãåÐ")


def is_double_encoded(text):
    """True when `text` looks like UTF-8 bytes that were decoded as cp1252
    and then re-encoded.

    Detected by attempting the exact inverse: if the string survives
    `encode("cp1252")` and the resulting bytes are themselves valid
    multi-byte UTF-8, it almost certainly *was* those bytes. A string of
    genuine Latin-1 accented characters fails the decode and is passed
    through untouched."""
    if not text or not any(char in _MOJIBAKE_LEAD for char in text):
        return False
    try:
        raw = text.encode("cp1252")
    except UnicodeEncodeError:
        return False
    try:
        repaired = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    # A pure-ASCII round trip is a no-op, not evidence of anything.
    return repaired != text


def repair_double_encoded(text):
    """The original text behind a double-encoded string, or `text` when it
    is not double-encoded. Diagnostic only -- production suppresses rather
    than repairs, because a string needing repair came from a source that
    should not have been trusted."""
    if not is_double_encoded(text):
        return text
    return text.encode("cp1252").decode("utf-8")


def is_speakable(text):
    """A rendered string is safe to speak only when it is nonempty after
    normalisation and shows no sign of a codec round trip."""
    if not text or not text.strip():
        return False
    return not is_double_encoded(text)
