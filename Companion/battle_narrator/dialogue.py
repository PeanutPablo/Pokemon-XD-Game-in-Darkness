"""Context-safe overworld dialogue page decoding and narration."""
from dataclasses import dataclass
from .memory import MemoryError, require_range
from .speech import SpeechEventClass

EXTRA_BYTES={0x07:1,0x09:1,0x38:1,0x52:1,0x53:1,0x5B:1,0x5C:1,0x08:4}
NEWLINE=0x00; DIALOGUE_END=0x02; CLEAR_WINDOW=0x03
PLAYER_NAME=0x2B; SPEAKER=0x59; WAIT_INPUT=0x6D
# "Set Speaker" (0x6A): observed live preceding the SPEAKER (0x59) marker
# on a page that doesn't open with a player-name/direct-address line
# (e.g. an NPC's own opening line, "Oh! Big brother!"). Carries no extra
# bytes in the one observed instance and produces no visible text of its
# own -- a no-op marker, same treatment as SPEAKER's own punctuation-
# suppression handling below.
SET_SPEAKER=0x6A
# Observed live at the start of the second page of a PDA/letter message
# ("Dear <PLAYER_NAME>, You appear to have traveled..."), immediately
# after the FFFF-terminated first page ("Have you found JOVI?"). Carries
# 1 extra byte (already in EXTRA_BYTES) and produces no visible text of
# its own in the one observed instance -- treated as a no-op, same as
# SET_SPEAKER, pending a second example to confirm its exact meaning.
LETTER_FORMAT=0x07
SUPPORTED_CONTROLS={NEWLINE,DIALOGUE_END,CLEAR_WINDOW,PLAYER_NAME,SPEAKER,WAIT_INPUT,SET_SPEAKER,LETTER_FORMAT}

class DialogueDecodeError(MemoryError): pass
class DialogueClosed(MemoryError): pass

@dataclass(frozen=True)
class DialogueSnapshot:
    task:int; page_start:int; page_end:int; raw:bytes; complete:bool
    context:str="overworld_npc"
    @property
    def page_key(self): return self.task,self.page_start,self.page_end,self.raw

def _tokens(raw):
    result=[]; offset=0
    while offset<len(raw):
        if offset+2>len(raw): raise DialogueDecodeError("truncated dialogue character")
        value=int.from_bytes(raw[offset:offset+2],"big"); offset+=2
        if value==0: break
        if value!=0xFFFF:
            result.append(("char",chr(value))); continue
        if offset>=len(raw): raise DialogueDecodeError("truncated dialogue control")
        opcode=raw[offset]; offset+=1; count=EXTRA_BYTES.get(opcode,0)
        if offset+count>len(raw): raise DialogueDecodeError(f"truncated dialogue control 0x{opcode:02X}")
        extra=raw[offset:offset+count]; offset+=count
        result.append(("control",opcode,extra))
        if opcode in {DIALOGUE_END,CLEAR_WINDOW}: break
    return result

def decode_page(raw,player_name):
    output=[]; at_start=True; suppress_speaker_punctuation=False
    for token in _tokens(raw):
        if token[0]=="char":
            value=token[1]
            if suppress_speaker_punctuation:
                if value in {":"," "}: continue
                suppress_speaker_punctuation=False
            output.append(value); at_start=False; continue
        opcode=token[1]
        if opcode not in SUPPORTED_CONTROLS:
            raise DialogueDecodeError(f"unknown meaning-changing control 0x{opcode:02X}")
        if opcode==NEWLINE: output.append("\n")
        elif opcode==PLAYER_NAME:
            if not player_name.strip(): raise DialogueDecodeError("player name is empty")
            output.append(player_name)
        elif opcode==SPEAKER and at_start: suppress_speaker_punctuation=True
    lines=[" ".join(line.split()) for line in "".join(output).splitlines()]
    text=" ".join(line for line in lines if line).strip()
    if not text: raise DialogueDecodeError("decoded dialogue page is empty")
    return text

class DialogueMemorySource:
    def __init__(self,memory,profile,logger=None): self.memory,self.profile,self.logger=memory,profile,logger
    def _window(self):
        # Only require exactly one dialogue-ID window to be present -- a
        # Yes/No confirmation prompt (e.g. "Save the game?") uses the same
        # dialogue_type=3 and dialogue window ID as ordinary field
        # dialogue, but adds a second, separate selection-cursor window
        # alongside it. The stricter original check (window list must
        # contain ONLY the dialogue window, nothing else) rejected any
        # such prompt outright as "unsupported," so Yes/No screens were
        # silently never narrated. Sibling windows are otherwise ignored
        # here; this reader only ever reads the one confirmed dialogue
        # window's own text.
        p=self.profile; pointer=self.memory.u32(p.window_manager+p.window_list_offset,"dialogue window-list head")
        seen=set(); found=[]; menu_ids=[]
        for _ in range(p.window_max_nodes):
            if pointer==0: break
            if pointer in seen: raise MemoryError("dialogue window list contains a cycle")
            require_range(pointer,p.window_node_size,"dialogue window",p,4); seen.add(pointer)
            menu_id=self.memory.u32(pointer+p.window_menu_id_offset,"dialogue window ID")
            menu_ids.append(menu_id)
            if menu_id==p.dialogue_window_id: found.append(pointer)
            pointer=self.memory.u32(pointer+p.window_next_offset,"dialogue next window")
        if len(found)!=1:
            raise DialogueClosed(f"expected exactly one dialogue window, found {len(found)} (menu IDs seen: {menu_ids!r})")
        return found[0]
    def snapshot(self):
        p=self.profile
        if self.memory.u8(p.dialogue_type_address,"dialogue type")!=p.dialogue_type:
            raise DialogueClosed("unsupported dialogue controller type")
        window=self._window()
        printing=self.memory.u8(window+p.dialogue_printing_offset,"dialogue printing")
        advancing=self.memory.u8(window+p.dialogue_advancing_offset,"dialogue advancing")
        manager=self.memory.pointer(p.dialogue_manager_root,p.dialogue_manager_tasks_offset+4,"dialogue manager",4)
        interior=self.memory.pointer(manager+p.dialogue_manager_tasks_offset,p.dialogue_task_back_offset,"dialogue task interior",4)
        task=interior-p.dialogue_task_back_offset
        require_range(task,p.dialogue_task_size,"dialogue task",p,4)
        start=self.memory.u32(task+p.dialogue_page_start_offset,"dialogue page start")
        end=self.memory.u32(task+p.dialogue_page_end_offset,"dialogue page end")
        if end<start or end-start>p.dialogue_max_page_bytes: raise MemoryError("invalid dialogue page bounds")
        require_range(start,end-start+3,"dialogue page bytes",p,1)
        raw=self.memory.bytes(start,end-start+3,"dialogue page bytes",1)
        # No opening-signature check: live testing found at least three
        # distinct, all genuinely valid opening patterns -- plain SPEAKER
        # (0x59); SET_SPEAKER (0x6A) immediately before SPEAKER (an NPC's
        # own opening line, "Oh! Big brother!"); and plain text with no
        # speaker marker at all (environmental/sign text with no
        # speaker, "DR. KAMINKO's inventions are number one..."). A
        # signature requirement narrow enough to reject invalid data
        # was also narrow enough to reject real, valid dialogue every
        # time a new pattern turned up -- decode_page()'s own opcode
        # and truncation checks (called by DialogueReader right after
        # this) are the real safety net; this pre-check added nothing
        # decode_page() doesn't already verify more robustly.
        # Two verified terminator styles: the usual FFFF+opcode sequence,
        # and a plain null word -- observed live on a Yes/No confirmation
        # prompt ("Big brother, you got lost, didn't you?"), which simply
        # ends the string without a DIALOGUE_END/CLEAR_WINDOW control code
        # (the page stays open awaiting the Yes/No selection instead of
        # closing or advancing).
        tail=raw[-3:]
        terminated_by_control=tail[:2]==b"\xFF\xFF" and tail[2] in {DIALOGUE_END,CLEAR_WINDOW}
        terminated_by_null=tail[:2]==b"\x00\x00"
        if not (terminated_by_control or terminated_by_null):
            raise MemoryError("dialogue page lacks verified terminator")
        return DialogueSnapshot(task,start,end,raw,printing==0 and advancing==0)
    def player_name(self):
        p=self.profile
        savedata=self.memory.pointer(
            p.savedata_pointer_address,
            p.hero_offset+24,
            "dialogue player name savedata",
            4,
        )
        return self.memory.gschar(
            savedata+p.hero_offset+p.hero_name_offset,11,"dialogue player name",2
        )

class DialogueReader:
    def __init__(self,source,speech,logger,debug=False,speaker_name_provider=None,
                 message_renderer=None):
        self.source,self.speech,self.logger,self.debug=source,speech,logger,debug
        self.speaker_name_provider=speaker_name_provider
        self.message_renderer=message_renderer
        self.active=False; self.last_page_key=None; self.last_text=None; self.last_transient_reason=None
    def clear(self,reason):
        if self.active and self.debug: self.logger.debug("DIALOGUE CLOSED reason=%s",reason)
        self.active=False; self.last_page_key=None; self.last_text=None; self.last_transient_reason=None
    def poll_once(self):
        try: snapshot=self.source.snapshot()
        except DialogueClosed as exc:
            self.clear(str(exc)); return
        except MemoryError as exc:
            reason = str(exc)
            if self.debug and reason != self.last_transient_reason:
                self.logger.debug("DIALOGUE TRANSIENT reason=%s", reason)
            self.last_transient_reason = reason
            return
        self.last_transient_reason = None
        self.active=True
        if snapshot.page_key==self.last_page_key: return
        # player_name() is only actually needed if this specific page uses
        # the PLAYER_NAME control code (0x2B) -- most pages don't. Calling
        # it unconditionally meant every page failed whenever that pointer
        # was transiently unreadable, even pages that never touch player
        # name at all. Only call it when the page's own raw bytes contain
        # the marker, so unrelated pages keep speaking regardless.
        needs_player_name = bytes((0xFF, 0xFF, PLAYER_NAME)) in snapshot.raw
        try:
            player_name = self.source.player_name() if needs_player_name else ""
        except MemoryError as exc:
            if self.debug and str(exc) != self.last_transient_reason:
                self.logger.debug("DIALOGUE PLAYER NAME TRANSIENT reason=%s", exc)
            self.last_transient_reason = str(exc)
            self.active=True; return
        try: text=decode_page(snapshot.raw,player_name)
        except DialogueDecodeError as exc:
            rendering = (self.message_renderer.render_bytes(snapshot.raw)
                         if self.message_renderer is not None else None)
            if rendering is None or not rendering.is_speakable:
                if self.debug: self.logger.warning("DIALOGUE PAGE SUPPRESSED start=0x%08X raw=%s reason=%s rendering=%r",snapshot.page_start,snapshot.raw.hex(),exc,rendering)
                self.last_page_key=snapshot.page_key; self.active=True; return
            text = rendering.text
        if self.debug: self.logger.debug("DIALOGUE PAGE task=0x%08X start=0x%08X end=0x%08X text=%r raw=%s",snapshot.task,snapshot.page_start,snapshot.page_end,text,snapshot.raw.hex())
        name=(self.speaker_name_provider() if self.speaker_name_provider is not None else None)
        if name: text=f"{name}: {text}"
        if text != self.last_text:
            self.speech.emit(SpeechEventClass.DIALOGUE,text,interrupt=True)
        self.last_text=text
        self.last_page_key=snapshot.page_key; self.active=True

