"""Shop message text (greetings, farewells) -- a genuinely derived read,
not typed-in text. Message 50601's real text ("Hello! Welcome to our
POKeMON MART. How may I serve you?") was found live 2026-07-30 by
searching this project's own already-extracted `pocket_menu.fsys` (the
same file `item_database.ItemDescriptionTable` already reads for item
descriptions) for the exact phrase the project owner read off-screen --
confirming which file/table/message-ID the text actually lives in,
per the project owner's explicit instruction that OCR'd text is a search
key to locate the real source, never something to hardcode as the fix.

`ItemDescriptionTable.resolve()` can't be reused as-is: its control-token
filter rejects anything but a bare newline, but shop messages open with
LETTER_FORMAT (0x07, "[Change Font]") and SPEAKER (0x59) tokens -- the
same opcodes `dialogue.py` already decodes correctly for live NPC
dialogue. Rather than inventing new semantics, this reuses `dialogue`'s
own opcode constants and the exact SPEAKER-at-start punctuation-suppression
rule (`decode_page`'s own comment explains why: a page can open directly
with ": " before the first word, meant to be swallowed, not spoken)."""
from pathlib import Path

import _dialogue_extraction_tool as extraction

from .dialogue import LETTER_FORMAT, NEWLINE, PLAYER_NAME, SET_SPEAKER, SPEAKER
from .messages import LocalDataError

SHOP_FSYS_ENTRY_TYPE = 5
SHOP_FSYS_ENTRY_NAME = "pocket_menu"

# Shop-template substitution opcodes -- not in dialogue.py (ordinary field
# dialogue doesn't use these), found live 2026-07-30 by inspecting message
# 50604's raw tokens ("[ITEM], okay. And you wanted [QTY]. That will be
# $[PRICE]. Is that okay?") and message 50609's ("We can pay you $[PRICE]
# for your merchandise..."). Opcode 0x4B cross-confirmed independently:
# the same code appears in dol_strings.json's "prize money of
# $[opcode_0x4B]" (battle winnings), so it's a general "insert an amount"
# placeholder, not shop-specific -- and shopBuyMain's own disassembly
# passes literal 0x2d/0x2f as arguments to menuShopGetMsgID, matching
# item-name/quantity exactly.
ITEM_NAME_PLACEHOLDER = 0x2D
QUANTITY_PLACEHOLDER = 0x2F
PRICE_PLACEHOLDER = 0x4B


def _render(tokens, player_name="", item_name=None, quantity=None, price=None):
    output = []
    at_start = True
    suppress_speaker_punctuation = False
    for kind, *rest in tokens:
        if kind == "char":
            codepoint = rest[0]
            value = chr(codepoint)
            if suppress_speaker_punctuation:
                if value in {":", " "}:
                    continue
                suppress_speaker_punctuation = False
            output.append(value)
            at_start = False
            continue
        opcode = rest[0]
        if opcode == NEWLINE:
            output.append("\n")
        elif opcode == PLAYER_NAME:
            output.append(player_name)
        elif opcode == ITEM_NAME_PLACEHOLDER and item_name is not None:
            output.append(item_name)
        elif opcode == QUANTITY_PLACEHOLDER and quantity is not None:
            output.append(str(quantity))
        elif opcode == PRICE_PLACEHOLDER and price is not None:
            output.append(str(price))
        elif opcode == SPEAKER and at_start:
            suppress_speaker_punctuation = True
        elif opcode == SET_SPEAKER:
            pass
        elif opcode == LETTER_FORMAT:
            pass
    lines = [" ".join(line.split()) for line in "".join(output).splitlines()]
    return " ".join(line for line in lines if line).strip()


class ShopMessageTable:
    """Message ID -> rendered shop text, read from `pocket_menu.fsys`'s
    own local message table (the same file/table
    `item_database.ItemDescriptionTable` already reads, a disjoint
    message-ID range from `common.rel`'s general table)."""

    def __init__(self, pocket_menu_fsys_path):
        path = Path(pocket_menu_fsys_path)
        try:
            files = extraction.parse_fsys(path.read_bytes())
            entry = next(
                item for item in files
                if item["type"] == SHOP_FSYS_ENTRY_TYPE
                and item["name"] == SHOP_FSYS_ENTRY_NAME
            )
            self.strings = extraction.decode_string_table(entry["data"])
        except Exception as exc:
            raise LocalDataError(
                f"Could not load shop message table: {exc}") from exc

    def resolve(self, message_id, player_name="", item_name=None,
                quantity=None, price=None):
        tokens = self.strings.get(message_id)
        if not tokens:
            return None
        text = _render(
            tokens, player_name, item_name=item_name, quantity=quantity,
            price=price)
        return text or None
