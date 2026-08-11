import unittest

from battle_narrator.entity_names import ScriptedSpeakerNameTable


def make_table(strings):
    table = ScriptedSpeakerNameTable.__new__(ScriptedSpeakerNameTable)
    table.strings = strings
    return table


def chars(text):
    return [("char", ord(ch)) for ch in text]


class ScriptedSpeakerNameTableTests(unittest.TestCase):
    def test_resolves_plain_name(self):
        table = make_table({6003: chars("JOVI")})
        self.assertEqual(table.resolve(6003), "Jovi")

    def test_unrevealed_placeholder_returns_none(self):
        table = make_table({6002: [("char", 0x2031)]})
        self.assertIsNone(table.resolve(6002))

    def test_missing_message_id_returns_none(self):
        table = make_table({})
        self.assertIsNone(table.resolve(9999))

    def test_control_code_tokens_rejected(self):
        table = make_table({100: [("ctrl", 0x2B, b"")] + chars("X")})
        self.assertIsNone(table.resolve(100))

    def test_empty_rendered_text_returns_none(self):
        table = make_table({100: [("char", 0x0A)]})
        self.assertIsNone(table.resolve(100))


if __name__ == "__main__":
    unittest.main()
