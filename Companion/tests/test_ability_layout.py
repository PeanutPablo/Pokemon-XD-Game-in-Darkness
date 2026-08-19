"""Tests for deriving the abilities-table layout from the game's code.

The instruction words below are not invented: they were read out of the
two disc images on this machine, at the three addresses the profile
names. Vanilla US XD encodes 12/+4/+8 and Pokemon XG 1.2.1 encodes
8/+0/+4, and those three words are the only differences anywhere in the
accessor cluster 0x80144200-0x801442D0. Pinning the real words here is
the point of the file: a refactor that broke the decoding would otherwise
only be caught by a live run against a hack."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.ability_layout import (
    AbilityTableLayout, derive_ability_layout,
)
from battle_narrator.memory import MemoryError
from battle_narrator.profile import XD_US_REV0

# Real words, as read from each image.
VANILLA = {
    XD_US_REV0.abilities_stride_instruction: 0x1C83000C,       # mulli r4,r3,12
    XD_US_REV0.abilities_name_instruction: 0x80630004,         # lwz r3,4(r3)
    XD_US_REV0.abilities_description_instruction: 0x80630008,  # lwz r3,8(r3)
}
XG = {
    XD_US_REV0.abilities_stride_instruction: 0x1C830008,       # mulli r4,r3,8
    XD_US_REV0.abilities_name_instruction: 0x80630000,         # lwz r3,0(r3)
    XD_US_REV0.abilities_description_instruction: 0x80630004,  # lwz r3,4(r3)
}


class FakeMemory:
    def __init__(self, words):
        self.words = dict(words)

    def u32(self, address, label="u32"):
        if address not in self.words:
            raise MemoryError(f"unmapped {label} at {address:#010x}")
        return self.words[address]


class DeriveAbilityLayoutTests(unittest.TestCase):
    def test_vanilla_words_give_the_documented_vanilla_layout(self):
        layout = derive_ability_layout(FakeMemory(VANILLA), XD_US_REV0)
        self.assertEqual(layout, AbilityTableLayout(12, 4, 8))
        # The profile's own constants still describe vanilla, which is
        # what makes them a usable cross-check rather than dead values.
        self.assertEqual(layout.stride, XD_US_REV0.abilities_table_stride)
        self.assertEqual(layout.name_offset,
                         XD_US_REV0.abilities_name_id_offset)
        self.assertEqual(layout.description_offset,
                         XD_US_REV0.abilities_description_id_offset)

    def test_xg_words_give_the_repacked_layout(self):
        layout = derive_ability_layout(FakeMemory(XG), XD_US_REV0)
        self.assertEqual(layout, AbilityTableLayout(8, 0, 4))

    def test_the_two_builds_do_not_derive_the_same_layout(self):
        """The whole reason this module exists.

        Both images pass every engine signature and carry the same disc
        label, so if these two ever derived alike the companion would have
        no way left to tell the layouts apart."""
        self.assertNotEqual(
            derive_ability_layout(FakeMemory(VANILLA), XD_US_REV0),
            derive_ability_layout(FakeMemory(XG), XD_US_REV0))

    def test_rejects_a_stride_site_that_is_not_a_mulli(self):
        words = dict(VANILLA)
        words[XD_US_REV0.abilities_stride_instruction] = 0x4E800020  # blr
        with self.assertRaises(MemoryError):
            derive_ability_layout(FakeMemory(words), XD_US_REV0)

    def test_rejects_a_field_site_that_is_not_a_lwz(self):
        words = dict(VANILLA)
        words[XD_US_REV0.abilities_name_instruction] = 0x88630004  # lbz
        with self.assertRaises(MemoryError):
            derive_ability_layout(FakeMemory(words), XD_US_REV0)

    def test_rejects_a_load_through_a_different_register(self):
        words = dict(VANILLA)
        words[XD_US_REV0.abilities_name_instruction] = 0x80640004  # lwz r3,4(r4)
        with self.assertRaises(MemoryError):
            derive_ability_layout(FakeMemory(words), XD_US_REV0)

    def test_rejects_a_field_that_does_not_fit_the_record(self):
        words = dict(VANILLA)
        # stride 8 with the description still at +8 cannot be one record.
        words[XD_US_REV0.abilities_stride_instruction] = 0x1C830008
        with self.assertRaises(MemoryError):
            derive_ability_layout(FakeMemory(words), XD_US_REV0)

    def test_rejects_name_and_description_sharing_an_offset(self):
        words = dict(VANILLA)
        words[XD_US_REV0.abilities_description_instruction] = 0x80630004
        with self.assertRaises(MemoryError):
            derive_ability_layout(FakeMemory(words), XD_US_REV0)

    def test_rejects_a_non_positive_stride(self):
        words = dict(VANILLA)
        words[XD_US_REV0.abilities_stride_instruction] = 0x1C830000  # x0
        with self.assertRaises(MemoryError):
            derive_ability_layout(FakeMemory(words), XD_US_REV0)


if __name__ == "__main__":
    unittest.main()
