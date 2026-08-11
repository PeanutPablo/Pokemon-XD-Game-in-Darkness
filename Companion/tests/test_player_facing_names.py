import unittest
from battle_narrator.player_facing_names import build_room_names, player_facing_npc_name, player_facing_room_name

class PlayerFacingRoomNameTests(unittest.TestCase):
    def test_a_house_with_no_provable_identity_stays_generic(self):
        # Was "Eagun's House, first floor" -- a hand-written claim with no
        # source. Removed 2026-08-10; see test_entity_labels.py.
        self.assertEqual(
            player_facing_room_name("M3_houseA_1F"),
            "house in Agate Village, 1st floor")

    def test_a_house_is_named_by_the_service_its_script_proves(self):
        self.assertEqual(
            player_facing_room_name("M3_houseD_1F", {"M3_houseD_1F": "Day-Care"}),
            "Agate Village Day-Care, 1st floor")
    def test_common_services(self):
        self.assertEqual(player_facing_room_name("M1_shop_1F"), "Phenac City Pokemon Mart, 1st floor")
        self.assertEqual(player_facing_room_name("M6_pc_2F"), "Gateon Port Pokemon Center, 2nd floor")
    def test_outdoor_location(self):
        self.assertEqual(player_facing_room_name("M3_out"), "Agate Village")
    def test_unknown_house_does_not_invent_owner(self):
        self.assertEqual(player_facing_room_name("M3_houseD_1F"), "house in Agate Village, 1st floor")
    def test_battle_variant_has_same_name(self):
        self.assertEqual(player_facing_room_name("M1_out_bf"), "Phenac City")
    def test_builds_id_keyed_map(self):
        self.assertEqual(build_room_names({0x86: "M3_shop_1F"})[0x86], "Agate Village Pokemon Mart, 1st floor")

class PlayerFacingNPCNameTests(unittest.TestCase):
    def test_trainer_class_precedes_name(self):
        self.assertEqual(player_facing_npc_name("Eddy", "Cool Trainer"), "Cool Trainer Eddy")
    def test_name_alone_is_preserved(self):
        self.assertEqual(player_facing_npc_name("Eagun"), "Eagun")

if __name__ == "__main__": unittest.main()

