import unittest
from battle_narrator.player_facing_names import build_room_names, player_facing_npc_name, player_facing_room_name

class PlayerFacingRoomNameTests(unittest.TestCase):
    def test_a_house_with_no_provable_identity_stays_generic(self):
        # Was "Eagun's House, first floor" -- a hand-written claim with no
        # source. Removed 2026-08-10; see test_entity_labels.py.
        self.assertEqual(
            player_facing_room_name("M3_houseA_1F"),
            "house, 1st floor")

    def test_a_house_is_named_by_the_service_its_script_proves(self):
        self.assertEqual(
            player_facing_room_name("M3_houseD_1F", {"M3_houseD_1F": "Day-Care"}),
            "Day-Care, 1st floor")
    def test_common_services(self):
        self.assertEqual(player_facing_room_name("M1_shop_1F"), "Pokemon Mart, 1st floor")
        self.assertEqual(player_facing_room_name("M6_pc_2F"), "Pokemon Center, 2nd floor")
    def test_outdoor_location(self):
        self.assertEqual(player_facing_room_name("M3_out"), "Agate Village")
    def test_unknown_house_does_not_invent_owner(self):
        self.assertEqual(player_facing_room_name("M3_houseD_1F"), "house, 1st floor")
    def test_battle_variant_has_same_name(self):
        self.assertEqual(player_facing_room_name("M1_out_bf"), "Phenac City")
    def test_builds_id_keyed_map(self):
        self.assertEqual(build_room_names({0x86: "M3_shop_1F"})[0x86], "Pokemon Mart, 1st floor")

class PlayerFacingNPCNameTests(unittest.TestCase):
    def test_trainer_class_precedes_name(self):
        self.assertEqual(player_facing_npc_name("Eddy", "Cool Trainer"), "Cool Trainer Eddy")
    def test_name_alone_is_preserved(self):
        self.assertEqual(player_facing_npc_name("Eagun"), "Eagun")

class MtBattleNameTests(unittest.TestCase):
    """Named by the project owner 2026-08-18, corroborated from the rooms'
    own scripts -- see the comment on these entries in
    `player_facing_names.EXACT_ROOM_NAMES`."""

    def test_the_entrance_is_not_announced_as_a_pokemon_center(self):
        # D2_pc_1F reuses a Center's building template, so the generic `pc`
        # rule called it one. Its script declares mtbtl_chart and
        # mtbtl_menu_1/2/3 -- it is the Mt. Battle reception.
        self.assertEqual(
            player_facing_room_name("D2_pc_1F"), "Mt. Battle entrance")

    def test_real_pokemon_centres_are_untouched(self):
        self.assertEqual(
            player_facing_room_name("M3_pc_1F"), "Pokemon Center, 1st floor")

    def test_the_outdoor_area_is_distinguished_from_the_location(self):
        # Both were "Mt. Battle", so a warp leading back out announced the
        # same words as the place the player was already standing in.
        self.assertEqual(
            player_facing_room_name("D2_out"), "Mt. Battle outside")

    def test_other_mt_battle_rooms_are_unaffected(self):
        self.assertEqual(player_facing_room_name("D2_rest_1"), "rest 1")


if __name__ == "__main__": unittest.main()

