import logging
import unittest
from battle_narrator.health import (
    BattlerIdentity, BattlerSample, StatusSample, HealthEvent, HealthTracker, FaintCoordinator,
    loss_sentence, round_percent,
)
from battle_narrator.profile import XD_US_REV0

class Source:
    def __init__(self):
        self.bs=[]; self.ws=[]
    def battlers(self): return self.bs
    def windows(self): return self.ws

class Clock:
    def __init__(self): self.value=0.0
    def __call__(self): return self.value

class HealthTests(unittest.TestCase):
    def setUp(self):
        self.source=Source(); self.clock=Clock()
        self.tracker=HealthTracker(self.source, XD_US_REV0,
                                   logging.getLogger('health-test'), self.clock)
        self.a=BattlerIdentity(0,0x80100000,0x80101000,0x80101004)
    def battler(self,hp=100,maxhp=100,name='SALAMENCE',identity=None,
                condition=0,level=50):
        return BattlerSample(identity or self.a,name,hp,maxhp,condition,level)
    def window(self,target=50,old=100,duration=0,name='SALAMENCE',maxhp=100,
               address=0x80200000,allocation=0x80300000):
        return StatusSample(address,allocation,name,maxhp,target,old,duration,0)
    def baseline(self):
        self.source.bs=[self.battler()]; self.assertEqual(self.tracker.poll(),[])
    def test_two_identical_settled_samples_required(self):
        self.baseline(); self.source.bs=[self.battler(50)]; self.source.ws=[self.window()]
        self.assertEqual(self.tracker.poll(),[])
        events=self.tracker.poll(); self.assertEqual(len(events),1)
        self.assertEqual(events[0].sentence,'Salamence lost 50 percent. 50 percent remaining.')
        self.assertEqual(self.tracker.poll(),[])
    def test_animation_must_settle(self):
        self.baseline(); self.source.bs=[self.battler(50)]; self.source.ws=[self.window(duration=5)]
        self.assertEqual(self.tracker.poll(),[])
        self.source.ws=[self.window(duration=0)]
        self.assertEqual(self.tracker.poll(),[]); self.assertEqual(len(self.tracker.poll()),1)
    def test_dynamic_window_reconstruction(self):
        self.baseline(); self.source.bs=[self.battler(50)]
        self.source.ws=[self.window(address=0x80201000,allocation=0x80301000)]
        self.tracker.poll()
        self.source.ws=[self.window(address=0x80202000,allocation=0x80302000)]
        self.assertEqual(len(self.tracker.poll()),1)
    def test_ambiguous_mapping_suppresses(self):
        self.baseline(); self.source.bs=[self.battler(50)]
        self.source.ws=[self.window(),self.window(address=0x802000BC,allocation=0x80300100)]
        self.assertEqual(self.tracker.poll(),[]); self.assertFalse(self.tracker.pending)
    def test_battler_replacement_rebaselines(self):
        self.baseline(); b=BattlerIdentity(0,0x80110000,0x80111000,0x80111004)
        self.source.bs=[self.battler(30,80,'METAGROSS',b)]; self.source.ws=[]
        self.assertEqual(self.tracker.poll(),[]); self.assertEqual(self.tracker.baselines[b],30)

    def test_fainted_battler_then_empty_slot_clears_state(self):
        self.baseline()
        self.source.bs=[self.battler(0)]
        self.source.ws=[self.window(target=0,old=100)]
        self.tracker.poll()
        events=self.tracker.poll()
        self.assertEqual(len(events),1)
        self.assertEqual(events[0].new_hp,0)
        self.source.bs=[]
        self.source.ws=[]
        self.assertEqual(self.tracker.poll(),[])
        self.assertNotIn(self.a,self.tracker.baselines)
        self.assertNotIn(self.a,self.tracker.pending)
        self.assertNotIn(0,self.tracker.slot_identities)

    def test_healthier_replacement_in_damaged_slot_is_not_healing(self):
        self.source.bs=[self.battler(25)]
        self.tracker.poll()
        replacement=BattlerIdentity(
            0,0x80130000,0x80131000,0x80131004)
        self.source.bs=[
            self.battler(100,120,'TYRANITAR',replacement)]
        self.source.ws=[]
        self.assertEqual(self.tracker.poll(),[])
        self.assertEqual(self.tracker.baselines[replacement],100)
        self.assertNotIn(self.a,self.tracker.baselines)
        self.assertFalse(self.tracker.pending)

    def test_multi_hit_groups_to_final_target(self):
        self.baseline(); self.source.bs=[self.battler(80)]; self.source.ws=[]; self.tracker.poll()
        self.source.bs=[self.battler(60)]; self.source.ws=[self.window(target=60)]
        self.assertEqual(self.tracker.poll(),[]); events=self.tracker.poll()
        self.assertEqual(events[0].old_hp,100); self.assertEqual(events[0].new_hp,60)
    def test_ordinary_healing_speaks_once_and_deduplicates(self):
        self.source.bs=[self.battler(50)]; self.tracker.poll()
        self.source.bs=[self.battler(75)]; self.source.ws=[self.window(target=75,old=50)]
        self.assertEqual(self.tracker.poll(),[])
        events=self.tracker.poll()
        self.assertEqual(
            [event.sentence for event in events],
            ['Player Salamence recovered 25 HP, 25 percent, now 75 of 100, 75 percent.'])
        self.assertEqual(self.tracker.poll(),[])
        self.assertEqual(self.tracker.baselines[self.a],75)

    def test_healing_exactly_to_maximum(self):
        self.source.bs=[self.battler(60)]; self.tracker.poll()
        self.source.bs=[self.battler(100)]
        self.source.ws=[self.window(target=100,old=60)]
        self.tracker.poll(); events=self.tracker.poll()
        self.assertEqual(events[0].sentence,
                         'Player Salamence recovered 40 HP, 40 percent, now 100 of 100, 100 percent.')

    def test_attempted_healing_at_full_hp_has_no_event(self):
        self.baseline()
        self.source.ws=[self.window(target=100,old=100)]
        self.assertEqual(self.tracker.poll(),[])
        self.assertEqual(self.tracker.poll(),[])

    def test_transient_healing_values_group_to_final_settlement(self):
        self.source.bs=[self.battler(40)]; self.tracker.poll()
        for hp in (50,65,80):
            self.source.bs=[self.battler(hp)]
            self.source.ws=[self.window(target=hp,old=40,duration=3)]
            self.assertEqual(self.tracker.poll(),[])
        self.source.ws=[self.window(target=80,old=40,duration=0)]
        self.assertEqual(self.tracker.poll(),[])
        events=self.tracker.poll()
        self.assertEqual((events[0].old_hp,events[0].new_hp),(40,80))

    def test_damage_then_healing_same_battler(self):
        self.baseline(); self.source.bs=[self.battler(50)]
        self.source.ws=[self.window(target=50,old=100)]
        self.tracker.poll(); damage=self.tracker.poll()
        self.source.bs=[self.battler(75)]
        self.source.ws=[self.window(target=75,old=50)]
        self.tracker.poll(); healing=self.tracker.poll()
        self.assertIn('lost 50 percent',damage[0].sentence)
        self.assertIn('recovered 25 HP',healing[0].sentence)

    def test_healing_then_damage_same_battler(self):
        self.source.bs=[self.battler(50)]; self.tracker.poll()
        self.source.bs=[self.battler(75)]
        self.source.ws=[self.window(target=75,old=50)]
        self.tracker.poll(); healing=self.tracker.poll()
        self.source.bs=[self.battler(25)]
        self.source.ws=[self.window(target=25,old=75)]
        self.tracker.poll(); damage=self.tracker.poll()
        self.assertIn('recovered 25 HP',healing[0].sentence)
        self.assertIn('lost 50 percent',damage[0].sentence)

    def test_two_battlers_heal_independently(self):
        b=BattlerIdentity(2,0x80120000,0x80121000,0x80121004)
        self.source.bs=[self.battler(40),self.battler(50,120,'METAGROSS',b)]
        self.tracker.poll()
        self.source.bs=[self.battler(70),self.battler(90,120,'METAGROSS',b)]
        self.source.ws=[
            self.window(target=70,old=40),
            self.window(target=90,old=50,name='METAGROSS',maxhp=120,
                        address=0x802000BC,allocation=0x80300100)]
        self.tracker.poll(); events=self.tracker.poll()
        self.assertEqual(
            [event.sentence for event in events],
            ['Player Salamence recovered 30 HP, 30 percent, now 70 of 100, 70 percent.',
             'Opponent Metagross recovered 40 HP, 33 percent, now 90 of 120, 75 percent.'])

    def test_drain_damage_and_healing_remain_separate(self):
        attacker=BattlerIdentity(2,0x80120000,0x80121000,0x80121004)
        self.source.bs=[self.battler(100),
                        self.battler(30,name='KINGDRA',identity=attacker)]
        self.tracker.poll()
        self.source.bs=[self.battler(60),
                        self.battler(50,name='KINGDRA',identity=attacker)]
        self.source.ws=[
            self.window(target=60,old=100),
            self.window(target=50,old=30,name='KINGDRA',
                        address=0x802000BC,allocation=0x80300100)]
        self.tracker.poll(); events=self.tracker.poll()
        self.assertEqual(len(events),2)
        self.assertIn('lost 40 percent',events[0].sentence)
        self.assertEqual(events[1].sentence,
                         'Opponent Kingdra recovered 20 HP, 20 percent, now 50 of 100, 50 percent.')

    def test_identity_change_during_pending_healing_rebaselines(self):
        self.source.bs=[self.battler(40)]; self.tracker.poll()
        self.source.bs=[self.battler(70)]
        self.source.ws=[self.window(target=70,old=40,duration=4)]
        self.tracker.poll()
        replacement=BattlerIdentity(0,0x80130000,0x80131000,0x80131004)
        self.source.bs=[self.battler(90,120,'TYRANITAR',replacement)]
        self.source.ws=[]
        self.assertEqual(self.tracker.poll(),[])
        self.assertFalse(self.tracker.pending)
        self.assertEqual(self.tracker.baselines[replacement],90)

    def test_battle_initialization_at_full_hp_is_baseline_only(self):
        self.source.bs=[self.battler(100)]
        self.assertEqual(self.tracker.poll(),[])
        self.assertEqual(self.tracker.poll(),[])

    def test_invalid_current_hp_above_maximum_is_silent(self):
        self.source.bs=[self.battler(101)]
        self.assertEqual(self.tracker.poll(),[])
        self.assertNotIn(self.a,self.tracker.baselines)

    def test_incomplete_healing_does_not_speak(self):
        self.source.bs=[self.battler(40)]; self.tracker.poll()
        self.source.bs=[self.battler(70)]
        self.source.ws=[self.window(target=70,old=40,duration=2)]
        self.assertEqual(self.tracker.poll(),[])
        self.assertEqual(self.tracker.poll(),[])
        self.assertIn(self.a,self.tracker.pending)

    def test_major_condition_changes_require_stability_and_deduplicate(self):
        self.source.bs=[self.battler(condition=0)]
        self.assertEqual(self.tracker.poll(),[])
        for condition,label in ((7,'frozen'),(5,'paralyzed'),(6,'burned')):
            self.source.bs=[self.battler(condition=condition)]
            self.assertEqual(self.tracker.poll(),[])
            events=self.tracker.poll()
            self.assertEqual([event.sentence for event in events],
                             [f'Salamence was {label}!'])
            self.assertEqual(self.tracker.poll(),[])

    def test_replacement_with_existing_condition_is_baseline_only(self):
        self.source.bs=[self.battler(condition=0)]
        self.tracker.poll()
        replacement=BattlerIdentity(
            0,0x80130000,0x80131000,0x80131004)
        self.source.bs=[self.battler(
            name='KINGDRA',identity=replacement,condition=7)]
        self.assertEqual(self.tracker.poll(),[])
        self.assertEqual(self.tracker.poll(),[])

    def test_existing_settled_damage_sentence_is_unchanged(self):
        self.baseline(); self.source.bs=[self.battler(50)]
        self.source.ws=[self.window(target=50,old=100)]
        self.tracker.poll(); events=self.tracker.poll()
        self.assertEqual(events[0].sentence,
                         'Salamence lost 50 percent. 50 percent remaining.')
    def test_round_half_up_and_edge_phrases(self):
        self.assertEqual(round_percent(1,8)[1],13)
        self.assertEqual(loss_sentence('A',1,0,201),'A lost less than one percent. zero percent remaining.')
        self.assertEqual(loss_sentence('A',100,0,100),'A lost 100 percent. zero percent remaining.')
    def test_simultaneous_battlers_are_independent(self):
        b=BattlerIdentity(1,0x80120000,0x80121000,0x80121004)
        self.source.bs=[self.battler(),self.battler(name='METAGROSS',identity=b)]
        self.tracker.poll()
        self.source.bs=[self.battler(50),self.battler(75,name='METAGROSS',identity=b)]
        self.source.ws=[self.window(),self.window(target=75,name='METAGROSS',address=0x802000BC,allocation=0x80300100)]
        self.tracker.poll(); events=self.tracker.poll()
        self.assertEqual([e.raw_nickname for e in events],['SALAMENCE','METAGROSS'])

class Speech:
    def __init__(self): self.items=[]
    def emit(self,event_class,text,interrupt=False): self.items.append(text)

class FaintCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock(); self.speech=Speech()
        self.coordinator=FaintCoordinator(
            self.speech,logging.getLogger('faint-test'),self.clock,1.0)
        self.identity=BattlerIdentity(1,0x80100000,0x80101000,0x80101004)
    def event(self,name='SALAMENCE'):
        return HealthEvent(self.identity,name,50,0,100,'ordinary health fallback')
    def test_open_dialogue_uses_current_unique_zero_hp_identity(self):
        salamence=BattlerSample(self.identity,'SALAMENCE',92,155)
        metagross=BattlerSample(
            BattlerIdentity(1,0x80200000,0x80201000,0x80201004),
            'METAGROSS',0,140)
        self.coordinator.note_target_faint()
        self.coordinator.submit_current_battlers([salamence,metagross])
        self.assertEqual(self.speech.items,['Metagross fainted!'])
    def test_dialogue_then_unique_zero_speaks_faint_once(self):
        self.coordinator.note_target_faint()
        self.coordinator.submit_health_events([self.event()])
        self.assertEqual(
            self.speech.items,['ordinary health fallback Salamence fainted!'])
        self.assertFalse(self.coordinator.pending_messages)
        self.assertFalse(self.coordinator.pending_zeroes)
    def test_zero_then_dialogue_speaks_faint_once(self):
        self.coordinator.submit_health_events([self.event('KINGDRA')])
        self.assertEqual(self.speech.items,[])
        self.coordinator.note_target_faint()
        self.assertEqual(
            self.speech.items,['ordinary health fallback Kingdra fainted!'])
    def test_current_battlers_reports_loss_percentage_from_baseline(self):
        salamence=BattlerSample(self.identity,'SALAMENCE',0,100)
        self.coordinator.note_target_faint()
        self.coordinator.submit_current_battlers(
            [salamence],{self.identity:22})
        self.assertEqual(
            self.speech.items,
            ['Salamence lost 22 percent. zero percent remaining. '
             'Salamence fainted!'])
    def test_unmatched_zero_falls_back_after_grace(self):
        self.coordinator.submit_health_events([self.event()])
        self.clock.value=1.0
        self.coordinator.submit_health_events([])
        self.assertEqual(
            self.speech.items,['ordinary health fallback Salamence fainted!'])
    def test_simultaneous_zeroes_are_not_assigned_by_order(self):
        other=HealthEvent(BattlerIdentity(2,2,3,4),'KINGDRA',20,0,80,'other fallback')
        self.coordinator.note_target_faint()
        self.coordinator.submit_health_events([self.event(),other])
        self.assertEqual(self.speech.items,[])
        self.clock.value=1.0
        self.coordinator.submit_health_events([])
        self.assertEqual(self.speech.items,[
            'ordinary health fallback Salamence fainted!',
            'other fallback Kingdra fainted!',
        ])
if __name__ == '__main__': unittest.main()