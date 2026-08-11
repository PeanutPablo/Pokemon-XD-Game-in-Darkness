import logging
import unittest

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
        self.assertEqual(parse_hotkey('ctrl+shift+h'),(0x11,0x10,ord('H')))
        self.assertEqual(parse_hotkey('alt+f12'),(0x12,0x7B))
        with self.assertRaises(HotkeyError): parse_hotkey('h')

if __name__ == '__main__': unittest.main()