import logging
import unittest
from battle_narrator.dialogue import (
    DialogueClosed, DialogueDecodeError, DialogueMemorySource, DialogueReader,
    DialogueSnapshot, decode_page,
)
from battle_narrator.memory import MemoryError, MemoryReader
from battle_narrator.profile import XD_US_REV0

def chars(text): return text.encode('utf-16-be')
def ctrl(op,*extra): return b'\xff\xff'+bytes((op,*extra))
def page(*parts): return b''.join(parts)+ctrl(3)

LIVE_PAGE_1=page(ctrl(0x59),chars(': Yes, sir!'),ctrl(0),chars('That was a well-played battle!'),ctrl(0),ctrl(0x2b),chars(', your battle skills have improved'),ctrl(0),chars('by an amazing amount.'))
LIVE_PAGE_2=page(ctrl(0x59),chars(': I mean, it was impressive the way you handled'),ctrl(0),chars('that big POKéMON with aplomb.'),ctrl(0),chars('You took command of it as if it were the same'),ctrl(0),chars('as your EEVEE.'))

class Speech:
 def __init__(self): self.items=[]
 def emit(self,event,text,interrupt=False): self.items.append((text,interrupt))
class Source:
 def __init__(self,values,name='DAVID'): self.values=list(values);self.name=name
 def snapshot(self):
  value=self.values.pop(0) if len(self.values)>1 else self.values[0]
  if isinstance(value,Exception): raise value
  return value
 def player_name(self):
  if isinstance(self.name,Exception): raise self.name
  return self.name
def snap(raw=LIVE_PAGE_1,start=0x809a4ebd,complete=True): return DialogueSnapshot(0x80834b80,start,start+len(raw)-3,raw,complete)

def reader(values,name='DAVID'):
 speech=Speech(); source=Source(values,name); return DialogueReader(source,speech,logging.getLogger('dialogue-test')),speech

class DialogueDecoderTests(unittest.TestCase):
 def test_single_page(self): self.assertEqual(decode_page(page(chars('Hello.')),'DAVID'),'Hello.')
 def test_multiline_normalized(self): self.assertEqual(decode_page(page(chars('Hello,'),ctrl(0),chars('traveler.')),'DAVID'),'Hello, traveler.')
 def test_player_name(self): self.assertEqual(decode_page(page(ctrl(0x2b),chars(', welcome.')),'DAVID'),'DAVID, welcome.')
 def test_live_page_one(self): self.assertEqual(decode_page(LIVE_PAGE_1,'DAVID'),'Yes, sir! That was a well-played battle! DAVID, your battle skills have improved by an amazing amount.')
 def test_live_page_two(self): self.assertEqual(decode_page(LIVE_PAGE_2,'DAVID'),'I mean, it was impressive the way you handled that big POKéMON with aplomb. You took command of it as if it were the same as your EEVEE.')
 def test_verified_speaker_visual_code(self): self.assertEqual(decode_page(page(ctrl(0x59),chars(': Hello.')),'DAVID'),'Hello.')
 def test_wait_input_is_nonverbal(self): self.assertEqual(decode_page(page(chars('Wait.'),ctrl(0x6d)),'DAVID'),'Wait.')
 def test_dialogue_end_terminates(self): self.assertEqual(decode_page(chars('Done.')+ctrl(2)+chars('garbage'),'DAVID'),'Done.')
 def test_unknown_control_suppressed(self):
  with self.assertRaises(DialogueDecodeError): decode_page(page(chars('A'),ctrl(0x44),chars('B')),'DAVID')
 def test_truncated_control_suppressed(self):
  with self.assertRaises(DialogueDecodeError): decode_page(b'\xff\xff','DAVID')
 def test_empty_player_name_suppressed(self):
  with self.assertRaises(DialogueDecodeError): decode_page(page(ctrl(0x2b)),'')
 def test_empty_page_suppressed(self):
  with self.assertRaises(DialogueDecodeError): decode_page(ctrl(3),'DAVID')
 def test_punctuation_preserved(self): self.assertEqual(decode_page(page(chars("Don't you? Yes!")),'DAVID'),"Don't you? Yes!")
 def test_set_speaker_before_speaker_is_noop_and_suppresses_punctuation(self):
  self.assertEqual(decode_page(page(ctrl(0x6a),ctrl(0x59),chars(': Oh! Big brother!'),ctrl(0),chars('What are you doing here?')),'DAVID'),'Oh! Big brother! What are you doing here?')

class DialogueReaderTests(unittest.TestCase):
 def test_initial_page_spoken_once(self):
  r,s=reader([snap()]);r.poll_once();r.poll_once();self.assertEqual(len(s.items),1)
 def test_typewriter_page_spoken_immediately(self):
  r,s=reader([snap(complete=False)]);r.poll_once();self.assertEqual(len(s.items),1)
 def test_stable_completed_text_spoken(self):
  r,s=reader([snap(complete=False),snap()]);r.poll_once();r.poll_once();self.assertEqual(len(s.items),1)
 def test_speaker_name_prefix(self):
  speech=Speech(); source=Source([snap()]); r=DialogueReader(source,speech,logging.getLogger("dialogue-test"),speaker_name_provider=lambda:"Lily"); r.poll_once(); self.assertTrue(speech.items[0][0].startswith("Lily: "))
 def test_two_page_transition_rearms(self):
  r,s=reader([snap(),snap(LIVE_PAGE_2,0x809a4f8f)]);r.poll_once();r.poll_once();self.assertEqual(len(s.items),2)
 def test_new_page_interrupts_obsolete_speech(self):
  r,s=reader([snap(),snap(LIVE_PAGE_2,0x809a4f8f)]);r.poll_once();r.poll_once();self.assertEqual([x[1] for x in s.items],[True,True])
 def test_close_clears(self):
  r,s=reader([snap(),DialogueClosed('closed')]);r.poll_once();r.poll_once();self.assertFalse(r.active)
 def test_reopen_identical_dialogue(self):
  r,s=reader([snap(),DialogueClosed('closed'),snap()]);r.poll_once();r.poll_once();r.poll_once();self.assertEqual(len(s.items),2)
 def test_transient_invalid_sample_does_not_rearm_page(self):
  r,s=reader([snap(),MemoryError('invalid bounds'),snap()]);r.poll_once();r.poll_once();r.poll_once();self.assertEqual(len(s.items),1)
 def test_invalid_buffer_is_silent(self):
  bad=page(chars('A'),ctrl(0x44));r,s=reader([snap(bad)]);r.poll_once();self.assertEqual(s.items,[])
 def test_player_name_transient_failure_is_silent_not_uncaught(self):
  # player_name() can transiently fail (e.g. a null pointer) even when
  # the page itself decodes fine -- this used to escape poll_once()
  # uncaught (only DialogueDecodeError was caught around this call),
  # crashing the whole narrator. Must be swallowed like any other
  # transient MemoryError, and must NOT mark the page as already-seen
  # so it gets spoken once the name becomes readable again.
  speech=Speech(); source=Source([snap()],name=MemoryError('invalid address 0x00000000'))
  r=DialogueReader(source,speech,logging.getLogger('dialogue-test'))
  r.poll_once()
  self.assertEqual(speech.items,[])
  self.assertTrue(r.active)
  self.assertIsNone(r.last_page_key)
 def test_page_without_player_name_opcode_speaks_even_if_player_name_unreadable(self):
  # player_name() used to be called unconditionally for every page, so
  # ANY page failed while it was unreadable, even ones that never touch
  # player name at all. Only pages that actually contain the PLAYER_NAME
  # (0x2B) control code should ever need it.
  no_name_page=page(chars('Hello, traveler.'))
  speech=Speech(); source=Source([snap(no_name_page)],name=MemoryError('invalid address 0x00000000'))
  r=DialogueReader(source,speech,logging.getLogger('dialogue-test'))
  r.poll_once()
  self.assertEqual([x[0] for x in speech.items],['Hello, traveler.'])
 def test_battle_context_suppressed(self):
  r,s=reader([MemoryError('battle context')]);r.poll_once();self.assertEqual(s.items,[])
 def test_menu_context_suppressed(self):
  r,s=reader([MemoryError('unsupported dialogue window signature [280]')]);r.poll_once();self.assertEqual(s.items,[])
 def test_cutscene_context_suppressed(self):
  r,s=reader([MemoryError('unsupported dialogue controller type')]);r.poll_once();self.assertEqual(s.items,[])

class WindowBackend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + offset, 0) for offset in range(size))


def be32(value):
    return value.to_bytes(4, "big")


class DialogueWindowTests(unittest.TestCase):
    """#Yes/No confirmation prompts (e.g. "Save the game?") add a second,
    separate selection-cursor window alongside the ordinary dialogue
    window. The window check must accept that sibling window rather than
    rejecting the whole screen as unsupported -- this is the fix for the
    reported bug where Yes/No screens were never narrated at all."""

    def _put_window(self, backend, address, menu_id, next_address=0):
        p = XD_US_REV0
        backend.put(address + p.window_menu_id_offset, be32(menu_id))
        backend.put(address + p.window_next_offset, be32(next_address))

    def test_dialogue_window_alone_is_found(self):
        p = XD_US_REV0
        backend = WindowBackend()
        backend.put(p.window_manager + p.window_list_offset, be32(0x80700000))
        self._put_window(backend, 0x80700000, p.dialogue_window_id)
        source = DialogueMemorySource(MemoryReader(backend, p), p)
        self.assertEqual(source._window(), 0x80700000)

    def test_sibling_window_alongside_dialogue_is_accepted(self):
        p = XD_US_REV0
        backend = WindowBackend()
        backend.put(p.window_manager + p.window_list_offset, be32(0x80700000))
        self._put_window(backend, 0x80700000, p.dialogue_window_id, next_address=0x80700100)
        self._put_window(backend, 0x80700100, 53)  # Yes/No selection cursor
        source = DialogueMemorySource(MemoryReader(backend, p), p)
        self.assertEqual(source._window(), 0x80700000)

    def test_no_dialogue_window_present_is_closed(self):
        p = XD_US_REV0
        backend = WindowBackend()
        backend.put(p.window_manager + p.window_list_offset, be32(0x80700000))
        self._put_window(backend, 0x80700000, 53)
        source = DialogueMemorySource(MemoryReader(backend, p), p)
        with self.assertRaises(DialogueClosed):
            source._window()

    def test_duplicate_dialogue_windows_is_closed(self):
        p = XD_US_REV0
        backend = WindowBackend()
        backend.put(p.window_manager + p.window_list_offset, be32(0x80700000))
        self._put_window(backend, 0x80700000, p.dialogue_window_id, next_address=0x80700100)
        self._put_window(backend, 0x80700100, p.dialogue_window_id)
        source = DialogueMemorySource(MemoryReader(backend, p), p)
        with self.assertRaises(DialogueClosed):
            source._window()


class DialogueSnapshotTests(unittest.TestCase):
    """Full synthetic snapshot() construction, covering both verified
    page-terminator styles: the usual FFFF+opcode sequence, and the plain
    null word observed live on a Yes/No confirmation prompt."""

    def _build(self, content, terminator, start=0x80900000):
        # `end` marks where the committed text content stops; the
        # terminator itself (either 3-byte FFFF+opcode, or a 2-byte null
        # word) lives in the 3-byte padding zone starting AT `end`, not
        # within the counted content span -- matching the live-verified
        # byte layout (see the dialogue.py fix comment for both styles).
        p = XD_US_REV0
        backend = WindowBackend()
        backend.put(p.dialogue_type_address, bytes([p.dialogue_type]))
        window = 0x80700000
        backend.put(p.window_manager + p.window_list_offset, be32(window))
        backend.put(window + p.window_menu_id_offset, be32(p.dialogue_window_id))
        backend.put(window + p.window_next_offset, be32(0))
        backend.put(window + p.dialogue_printing_offset, bytes([0]))
        backend.put(window + p.dialogue_advancing_offset, bytes([0]))
        manager = 0x80710000
        backend.put(p.dialogue_manager_root, be32(manager))
        interior = 0x80720000 + p.dialogue_task_back_offset
        backend.put(manager + p.dialogue_manager_tasks_offset, be32(interior))
        task = interior - p.dialogue_task_back_offset
        end = start + len(content)
        backend.put(task + p.dialogue_page_start_offset, be32(start))
        backend.put(task + p.dialogue_page_end_offset, be32(end))
        backend.put(start, content)
        backend.put(end, terminator)
        return DialogueMemorySource(MemoryReader(backend, p), p)

    def test_control_terminated_page_is_accepted(self):
        content = b"\xFF\xFF\x59" + "Hi.".encode("utf-16-be")
        source = self._build(content, b"\xFF\xFF\x02")
        snapshot = source.snapshot()
        self.assertTrue(snapshot.complete)

    def test_null_terminated_yes_no_page_is_accepted(self):
        content = b"\xFF\xFF\x59" + "Save the game?".encode("utf-16-be")
        source = self._build(content, b"\x00\x00")
        snapshot = source.snapshot()
        self.assertTrue(snapshot.complete)

    def test_plain_text_page_with_no_speaker_marker_is_accepted(self):
        # Environmental/sign text with no speaker at all, e.g.
        # "DR. KAMINKO's inventions are number one in the world!" --
        # confirmed live; no opening-signature check is required anymore.
        content = "No speaker here.".encode("utf-16-be")
        source = self._build(content, b"\xFF\xFF\x03")
        snapshot = source.snapshot()
        self.assertTrue(snapshot.complete)


if __name__=='__main__': unittest.main()

