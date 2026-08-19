import logging
import unittest

from battle_narrator.battle_identity import party_slot_address
from battle_narrator.health import BattlerIdentity, BattlerSample
from battle_narrator.hotkeys import (
    BattleHPSummary, HotkeyError, WindowsForegroundHotkey, parse_hotkey
)
from battle_narrator.profile import XD_US_REV0
from battle_narrator.phase1b_lifecycle import LifecycleController

class Source:
    def __init__(self, samples): self.samples=samples
    def battlers(self): return list(self.samples)

class Hotkey:
    def __init__(self): self.fire=False
    def poll(self):
        result=self.fire; self.fire=False; return result

class Speech:
    def __init__(self): self.calls=[]
    def emit(self, event, text, interrupt=None):
        self.calls.append((event,text,interrupt))


def battler(slot,name,hp,maximum,condition=0,level=50):
    base=0x80100000+slot*0x1000
    return BattlerSample(BattlerIdentity(slot,base,base+0x100,base+0x104),
                         name,hp,maximum,condition,level)


def party_battler(slot,name,hp,maximum,side,party_slot,condition=0,level=50):
    """A battler whose FightPokemon pointer really lands on a party-array
    cell, so ownership is DERIVED rather than falling back to the
    positional tuple. `side` 0 is the player, 1 the opponent."""
    fight_pokemon=party_slot_address(XD_US_REV0,side,0,party_slot)
    base=0x80100000+slot*0x1000
    return BattlerSample(
        BattlerIdentity(slot,base,fight_pokemon,
                        fight_pokemon+XD_US_REV0.fight_pokemon_embedded_offset),
        name,hp,maximum,condition,level)

class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.samples=[
            battler(1,'MIGHTYENA',64,120),
            battler(2,'METAGROSS',128,155,3),
            battler(0,'SALAMENCE',142,171),
            battler(3,'GOLBAT',0,110),
        ]
        self.source=Source(self.samples); self.hotkey=Hotkey(); self.speech=Speech()
        self.summary=BattleHPSummary(self.source,XD_US_REV0,self.hotkey,
                                     self.speech,logging.getLogger('summary-test'))
    def press(self):
        self.hotkey.fire=True; self.summary.poll_once(); self.summary.poll_once()
    def test_stable_double_battle_order_and_one_combined_utterance(self):
        self.press(); self.assertEqual(len(self.speech.calls),1)
        text=self.speech.calls[0][1]
        expected=(
          'Player Salamence, level 50, 142 of 171 HP, 83 percent. '
          'Player Mightyena, level 50, 64 of 120 HP, 53 percent. '
          'Opponent Metagross, level 50, 128 of 155 HP, 83 percent, poisoned. '
          'Opponent Golbat, level 50, 0 of 110 HP, zero percent, fainted.')
        self.assertEqual(text,expected)
    def test_single_battle_omits_empty_slots(self):
        self.source.samples=[self.samples[2],self.samples[0]]
        self.press(); text=self.speech.calls[0][1]
        self.assertEqual(text.count('.'),2)
        self.assertNotIn('right',text.casefold())
    def test_changed_second_sample_is_suppressed(self):
        self.hotkey.fire=True; self.summary.poll_once()
        self.source.samples[0]=battler(1,'MIGHTYENA',63,120)
        self.summary.poll_once(); self.assertEqual(self.speech.calls,[])
    def test_changed_level_between_samples_is_suppressed(self):
        self.hotkey.fire=True; self.summary.poll_once()
        original=self.source.samples[0]
        self.source.samples[0]=battler(
            original.identity.slot,original.raw_nickname,
            original.hp,original.max_hp,original.condition,51)
        self.summary.poll_once(); self.assertEqual(self.speech.calls,[])

    def test_one_press_does_not_repeat(self):
        self.press(); self.summary.poll_once(); self.summary.poll_once()
        self.assertEqual(len(self.speech.calls),1)
    def test_sides_come_from_the_party_array_not_the_slot_index(self):
        # The active array has compacted: the OPPONENT holds slots 0 and 1
        # and the PLAYER holds 2 and 3 -- exactly the interleaving the
        # positional `summary_slot_ownership` tuple gets backwards. Each
        # battler's FightPokemon lands on a real party cell, so the derived
        # answer is available and must win.
        self.source.samples=[
            party_battler(0,'GOLBAT',40,110,side=1,party_slot=0),
            party_battler(1,'METAGROSS',128,155,side=1,party_slot=1),
            party_battler(2,'SALAMENCE',142,171,side=0,party_slot=0),
            party_battler(3,'MIGHTYENA',64,120,side=0,party_slot=1),
        ]
        self.press()
        text=self.speech.calls[0][1]
        self.assertTrue(text.startswith('Player Salamence'),text)
        self.assertIn('Player Mightyena',text)
        self.assertIn('Opponent Golbat',text)
        self.assertIn('Opponent Metagross',text)
        self.assertNotIn('Player Golbat',text)
        self.assertNotIn('Opponent Salamence',text)
        # Player side is spoken first even though it occupies the higher
        # active-array slots.
        self.assertLess(text.index('Player Salamence'),text.index('Opponent'))

    def test_status_names(self):
        expected={3:'poisoned',4:'badly poisoned',5:'paralyzed',6:'burned',7:'frozen',8:'asleep'}
        for condition,name in expected.items():
            line=self.summary._line('Player',battler(0,'TEST',1,2,condition))
            self.assertIn(name,line)
    def test_lifecycle_accepts_summary_factory(self):
        factory = lambda: self.summary
        controller = LifecycleController(
            object(), lambda: None, lambda tasks: None, object(),
            logging.getLogger('lifecycle-summary-test'), summary_factory=factory
        )
        self.assertIs(controller.summary_factory, factory)
        self.assertIsNone(controller.summary_reader)
    def test_hotkey_never_fires_from_another_foreground_app(self):
        hotkey = object.__new__(WindowsForegroundHotkey)
        hotkey.process_name = 'dolphin.exe'
        hotkey.held = False
        state = {'pressed': True, 'process': 'notepad.exe'}
        hotkey._pressed = lambda: state['pressed']
        hotkey._foreground_process = lambda: state['process']
        self.assertFalse(hotkey.poll())
        state['process'] = 'dolphin.exe'
        self.assertFalse(hotkey.poll())  # held chord cannot leak across focus
        state['pressed'] = False
        self.assertFalse(hotkey.poll())
        state['pressed'] = True
        self.assertTrue(hotkey.poll())
        self.assertFalse(hotkey.poll())  # edge-triggered once
    def test_hotkey_requires_modifier_and_is_configurable(self):
        self.assertEqual(parse_hotkey('ctrl+h'),(0x11,ord('H')))
        self.assertEqual(parse_hotkey('alt+f12'),(0x12,0x7B))
        with self.assertRaises(HotkeyError): parse_hotkey('h')

if __name__ == '__main__': unittest.main()
