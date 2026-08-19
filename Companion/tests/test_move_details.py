import struct
import unittest
from battle_narrator.resolver import LocalMoveData

class MoveDetailTests(unittest.TestCase):
    def source(self, move_id, pp, type_id, accuracy, power, priority=0):
        obj=LocalMoveData.__new__(LocalMoveData); obj.moves_base=0; obj.data=bytearray((move_id+1)*obj.STRIDE)
        obj.descriptions = {"12345": "The real in-game effect text."}
        # Type names are read from the game's own zokusei table at load
        # (see test_move_type_names.py); these fixtures skip __init__, so
        # they stand in the one entry they exercise.
        obj.type_names = ("Normal",)
        base=move_id*obj.STRIDE
        struct.pack_into(">I", obj.data, base + obj.DESCRIPTION_OFFSET, 12345)
        obj.data[base] = priority & 0xFF
        obj.data[base+obj.PP_OFFSET]=pp; obj.data[base+obj.TYPE_OFFSET]=type_id
        obj.data[base+obj.ACCURACY_OFFSET]=accuracy; struct.pack_into(">H",obj.data,base+obj.POWER_OFFSET,power)
        return obj
    def test_damaging_move_description(self):
        detail=self.source(33,35,0,95,35).details(33)
        self.assertEqual(detail.description,"Normal-type, power 35, 95 percent accuracy, The real in-game effect text.")
    def test_status_move_description(self):
        detail=self.source(45,40,0,100,0).details(45)
        self.assertEqual(detail.description,"Normal-type, status move, 100 percent accuracy, The real in-game effect text.")

    def test_priority_byte_is_not_part_of_extremespeed_pp(self):
        detail = self.source(245, 5, 0, 100, 80, priority=1).details(245)
        self.assertEqual(detail.base_pp, 5)
        self.assertEqual(detail.power, 80)

if __name__ == "__main__": unittest.main()
