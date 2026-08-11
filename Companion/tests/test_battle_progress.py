import logging
import unittest
from battle_narrator.health import BattlerIdentity, BattlerSample, HealthTracker, StatStageEvent
from battle_narrator.profile import XD_US_REV0

class Source:
    def __init__(self,sample): self.sample=sample
    def battlers(self): return [self.sample]
    def windows(self): return []

def sample(exp=100,stages=(0,0,0,0,0,0,0)):
    identity=BattlerIdentity(0,0x80100000,XD_US_REV0.fight_floor_root+XD_US_REV0.fight_trainer_first_pokemon_offset,XD_US_REV0.fight_floor_root+XD_US_REV0.fight_trainer_first_pokemon_offset+4)
    return BattlerSample(identity,"EEVEE",30,40,0,10,exp,stages)

class BattleProgressTests(unittest.TestCase):
    def setUp(self):
        self.source=Source(sample()); self.tracker=HealthTracker(self.source,XD_US_REV0,logging.getLogger("progress"))
        self.assertEqual(self.tracker.poll(),[])
    def test_experience_delta_does_not_repeat_authoritative_message(self):
        self.source.sample=sample(exp=137)
        self.assertEqual(self.tracker.poll(), [])
    def test_stat_stage_narration_is_off_by_default(self):
        # The battle stat messages (20243/20244/20246/20247) render from
        # their own templates now, so this tracker would be a second voice
        # for the same event -- caught in the production log as two
        # utterances 64ms apart. Sampling continues; narration does not.
        self.source.sample=sample(stages=(-1,0,0,0,0,0,0))
        events=self.tracker.poll()
        self.assertEqual([e for e in events if isinstance(e, StatStageEvent)], [])

    def test_stat_stage_transition_still_available_as_an_opt_in_fallback(self):
        tracker = HealthTracker(
            self.source, XD_US_REV0, logging.getLogger("progress"),
            narrate_stat_stages=True)
        self.assertEqual(tracker.poll(), [])
        self.source.sample=sample(stages=(-1,0,0,0,0,0,0))
        events=tracker.poll()
        stage = next(e for e in events if isinstance(e, StatStageEvent))
        self.assertEqual(stage.sentence, "Eevee's Attack fell!")


if __name__ == "__main__": unittest.main()

