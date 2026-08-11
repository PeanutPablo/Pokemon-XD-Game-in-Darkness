import unittest

from battle_narrator.shop_messages import ShopMessageTable


def chars(text):
    return [("char", ord(ch)) for ch in text]


def make_table(strings):
    table = ShopMessageTable.__new__(ShopMessageTable)
    table.strings = strings
    return table


class ShopMessageTableTests(unittest.TestCase):
    def test_resolves_plain_text(self):
        table = make_table({1: chars("Buy something?")})
        self.assertEqual(table.resolve(1), "Buy something?")

    def test_letter_format_and_speaker_tokens_are_suppressed(self):
        # Real, live-observed token shape for message 50601 (the shop
        # greeting): LETTER_FORMAT then SPEAKER, followed by a literal
        # ": " the SPEAKER-at-start rule swallows -- matching
        # dialogue.py's decode_page exactly, not new semantics invented
        # for this file.
        tokens = (
            [("ctrl", 7, b"\x00"), ("ctrl", 89, b"")]
            + chars(": Hello!")
            + [("ctrl", 0, b"")]
            + chars("Welcome to our POK")
            + [("char", 233)]
            + chars("MON MART.")
            + [("ctrl", 0, b"")]
            + chars("How may I serve you?")
        )
        table = make_table({50601: tokens})
        self.assertEqual(
            table.resolve(50601),
            "Hello! Welcome to our POKéMON MART. How may I serve you?",
        )

    def test_newline_tokens_collapse_to_spaces(self):
        tokens = chars("Line one") + [("ctrl", 0, b"")] + chars("line two")
        table = make_table({2: tokens})
        self.assertEqual(table.resolve(2), "Line one line two")

    def test_player_name_token_is_substituted(self):
        tokens = chars("Hi ") + [("ctrl", 0x2B, b"")] + chars("!")
        table = make_table({3: tokens})
        self.assertEqual(table.resolve(3, player_name="LEON"), "Hi LEON!")

    def test_unknown_message_id_returns_none(self):
        table = make_table({1: chars("known")})
        self.assertIsNone(table.resolve(999))

    def test_empty_rendered_text_returns_none(self):
        table = make_table({1: [("ctrl", 7, b"\x00")]})
        self.assertIsNone(table.resolve(1))


if __name__ == "__main__":
    unittest.main()
