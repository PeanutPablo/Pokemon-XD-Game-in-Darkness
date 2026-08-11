"""Bounded read-only inventory for launch/VS menu window structures."""
import logging
import time
from pathlib import Path
import dolphin_memory_engine as dme
from battle_narrator.memory import MemoryReader, MemoryError, valid_range
from battle_narrator.menus import WindowListWalker
from battle_narrator.profile import XD_US_REV0

LOG = Path(__file__).parent / "logs" / "vs_menu_structure_inventory.log"

def logger():
    value=logging.getLogger("vs_menu_inventory"); value.setLevel(logging.DEBUG)
    handler=logging.FileHandler(LOG,encoding="utf-8"); handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    value.handlers[:]=[handler]; return value

def s16(value): return value-0x10000 if value&0x8000 else value

def strings(memory, blob, base, label):
    found=[]; seen=set()
    for offset in range(0,len(blob)-3,4):
        pointer=int.from_bytes(blob[offset:offset+4],"big")
        if pointer in seen or not valid_range(pointer,2,XD_US_REV0.mem1_start,XD_US_REV0.mem1_end): continue
        seen.add(pointer)
        try:
            text=memory.gschar(pointer,48,f"{label} string",1)
        except MemoryError: continue
        clean=" ".join(text.split())
        if clean and all(ch.isprintable() for ch in clean): found.append((offset,pointer,clean))
    return found

def main():
    log=logger(); dme.hook()
    if not dme.is_hooked(): raise RuntimeError("Dolphin unavailable")
    memory=MemoryReader(dme,XD_US_REV0); walker=WindowListWalker(memory,XD_US_REV0)
    previous=None; log.info("START read-only bounded window inventory")
    while True:
        try:
            nodes=walker.walk(); snapshot=[]
            for node in nodes:
                raw=memory.bytes(node.address,XD_US_REV0.window_node_size,"window",4)
                base=s16(int.from_bytes(raw[XD_US_REV0.window_cursor_base_offset:XD_US_REV0.window_cursor_base_offset+2],"big"))
                cursor=s16(int.from_bytes(raw[XD_US_REV0.window_cursor_offset:XD_US_REV0.window_cursor_offset+2],"big"))
                alloc=int.from_bytes(raw[XD_US_REV0.window_alloc_offset:XD_US_REV0.window_alloc_offset+4],"big")
                node_strings=tuple(strings(memory,raw,node.address,"node"))
                alloc_strings=()
                if valid_range(alloc,0x100,XD_US_REV0.mem1_start,XD_US_REV0.mem1_end,4):
                    alloc_raw=memory.bytes(alloc,0x100,"menu allocation",4)
                    alloc_strings=tuple(strings(memory,alloc_raw,alloc,"allocation"))
                snapshot.append((node.address,node.menu_id,base,cursor,base+cursor,alloc,node_strings,alloc_strings))
            snapshot=tuple(snapshot)
            if snapshot!=previous:
                log.info("STATE nodes=%d",len(snapshot))
                for item in snapshot:
                    log.info("NODE addr=0x%08X id=%d base=%d cursor=%d logical=%d alloc=0x%08X node_strings=%r alloc_strings=%r",*item)
                previous=snapshot
        except Exception as exc:
            log.warning("READ %s",exc); previous=None
        time.sleep(0.05)
if __name__=="__main__": main()