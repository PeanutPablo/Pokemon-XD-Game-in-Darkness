import logging
import unittest

from battle_narrator.gateon_bridge import ALIGNMENTS, alignment_text, control_pads


class GateonBridgeModelTests(unittest.TestCase):
    def test_all_four_script_states_have_complete_descriptions(self):
        self.assertEqual(set(ALIGNMENTS), {0, 1, 2, 3})
        for state in ALIGNMENTS:
            text = alignment_text(state)
            self.assertIn("northern bridge connects", text)
            self.assertIn("southern bridge connects", text)
            self.assertIn("center passage", text)

    def test_each_state_exposes_four_exact_script_control_regions(self):
        for state in ALIGNMENTS:
            pads = control_pads(state)
            self.assertEqual(len(pads), 4)
            self.assertTrue(all(pad.next_state in ALIGNMENTS for pad in pads))
            self.assertTrue(all(pad.next_state != state for pad in pads))

    def test_known_northern_pad_transition_from_state_three(self):
        pad = next(p for p in control_pads(3) if p.contains(-240, 135))
        self.assertEqual(pad.bridge, "northern")
        self.assertEqual(pad.next_state, 2)

    def test_known_southern_pad_transition_from_state_zero(self):
        pad = next(p for p in control_pads(0) if p.contains(-265, -90))
        self.assertEqual(pad.bridge, "southern")
        self.assertEqual(pad.next_state, 3)


if __name__ == "__main__":
    unittest.main()
