import logging
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

import pinned_build

from battle_narrator.pda import (
    MAIL_CONTENT_MENU_ID, MAIL_ID_ADDRESS, MAIL_OPEN_FLAG_ADDRESS,
    MAIL_PARENT_MENU_ID, PDA_HOME_CURSOR_ADDRESS, PDA_HOME_MENU_IDS,
    PDA_PARENT_MENU_ID, POKEMON_DATA, POKEMON_DATA_NUMBER,
    POKEMON_NAME_OFFSET, POKEMON_DATA_STRIDE, SHADOW_CURSOR_ADDRESS,
    SHADOW_LIST_OBJECT_ADDRESS, SHADOW_LIST_RECORDS_OFFSET,
    SHADOW_MONITOR_MENU_ID, SPOT_DATA_ADDRESS, SPOT_DATA_COUNT_ADDRESS,
    SPOT_MONITOR_MENU_ID, SPOT_RECORD_SIZE, WORLD_MAP_DATA_ADDRESS,
    WORLD_MAP_FLAG_OFFSET, WORLD_MAP_RECORD_SIZE, STRATEGY_CURSOR_ADDRESS,
    STRATEGY_LIST_MENU_IDS, STRATEGY_LIST_OBJECT_ADDRESS,
    STRATEGY_LIST_RECORDS_OFFSET, PdaCatalog, PdaReader,
)
from battle_narrator.profile import XD_US_REV0 as p


class Backend:
    def __init__(self): self.data = {}
    def put(self, address, value):
        for i, byte in enumerate(value): self.data[address + i] = byte
    def read_bytes(self, address, size):
        return bytes(self.data.get(address + i, 0) for i in range(size))


class Memory:
    def __init__(self, backend): self.backend = backend
    def bytes(self, address, size, label="", alignment=1): return self.backend.read_bytes(address, size)
    def u8(self, address, label=""): return self.bytes(address, 1)[0]
    def u16(self, address, label=""): return int.from_bytes(self.bytes(address, 2), "big")
    def u32(self, address, label=""): return int.from_bytes(self.bytes(address, 4), "big")
    def pointer(self, address, span, label="", alignment=4): return self.u32(address, label)
    def gschar(self, address, maximum, label="", alignment=1):
        raw=self.bytes(address,(maximum+1)*2); out=[]
        for i in range(0,len(raw),2):
            value=int.from_bytes(raw[i:i+2],"big")
            if not value:return "".join(out)
            out.append(chr(value))
        raise RuntimeError


class Catalog:
    def text(self, message_id):
        return {15182:"Strategy Memo",15184:"Shadow Monitor",15359:"Spot Monitor",15383:"Rock",
                15384:"Oasis",15385:"Cave"}[message_id]

    def home_option(self, cursor):
        return {
            0: ("Shadow Monitor", "Display snagged Pokemon data."),
            1: ("Strategy Memo", "Display data on all Pokemon met so far."),
            2: ("Mailbox", "Read received email."),
            3: ("Spot Monitor", "Check the Poke Spots."),
            4: ("Cancel", "Close P star D A."),
        }[cursor]

    def mail(self, mail_id, player):
        return "Krane", "Have you found JOVI?", f"Dear {player.title()}, return to the HQ LAB."


class Speech:
    def __init__(self): self.calls=[]
    def emit(self,*args,**kwargs): self.calls.append((args,kwargs))


def be32(value): return struct.pack(">I",value)


class PdaReaderTests(unittest.TestCase):
    def setUp(self):
        self.backend=Backend(); self.memory=Memory(self.backend); self.speech=Speech()
        log=logging.getLogger("pda-test"); log.addHandler(logging.NullHandler())
        self.reader=PdaReader(self.memory,p,Catalog(),self.speech,log)
        head=0x80100000; child=0x80100100
        self.backend.put(p.window_manager+p.window_list_offset,be32(head))
        self.backend.put(head+p.window_menu_id_offset,be32(MAIL_CONTENT_MENU_ID))
        self.backend.put(head+p.window_next_offset,be32(child))
        self.backend.put(child+p.window_menu_id_offset,be32(MAIL_PARENT_MENU_ID))
        self.backend.put(MAIL_OPEN_FLAG_ADDRESS,b"\x01")
        self.backend.put(MAIL_ID_ADDRESS,be32(2))
        name="LEON".encode("utf-16-be")+b"\0\0"
        savedata=0x80101000
        self.backend.put(p.savedata_pointer_address,be32(savedata))
        self.backend.put(savedata+p.hero_offset+p.hero_name_offset,name)

    def test_announces_open_mail_once_with_live_player_name(self):
        self.reader.poll_once(); self.reader.poll_once()
        self.assertEqual(len(self.speech.calls),1)
        text=self.speech.calls[0][0][1]
        self.assertEqual(text,"Mailbox. From Krane. Subject: Have you found JOVI? Dear Leon, return to the HQ LAB.")

    def test_closing_and_reopening_reannounces(self):
        self.reader.poll_once(); self.backend.put(MAIL_OPEN_FLAG_ADDRESS,b"\0")
        self.reader.poll_once(); self.backend.put(MAIL_OPEN_FLAG_ADDRESS,b"\1")
        self.reader.poll_once(); self.assertEqual(len(self.speech.calls),2)

    def test_wrong_window_pair_is_silent(self):
        self.backend.put(0x80100100+p.window_menu_id_offset,be32(1))
        self.reader.poll_once(); self.assertEqual(self.speech.calls,[])


class PdaHomeReaderTests(unittest.TestCase):
    def setUp(self):
        self.backend=Backend(); self.memory=Memory(self.backend); self.speech=Speech()
        log=logging.getLogger("pda-home-test"); log.addHandler(logging.NullHandler())
        self.reader=PdaReader(self.memory,p,Catalog(),self.speech,log)
        addresses=(0x80100000,0x80100100,0x80100200)
        for index,(address,menu_id) in enumerate(zip(addresses,PDA_HOME_MENU_IDS)):
            next_address=addresses[index+1] if index+1<len(addresses) else 0
            self.backend.put(address+p.window_menu_id_offset,be32(menu_id))
            self.backend.put(address+p.window_next_offset,be32(next_address))
        self.backend.put(p.window_manager+p.window_list_offset,be32(addresses[0]))

    def select(self, cursor):
        self.backend.put(PDA_HOME_CURSOR_ADDRESS,be32(cursor)); self.reader.poll_once()
        return self.speech.calls[-1][0][1]

    def test_announces_every_confirmed_home_option(self):
        self.assertEqual(self.select(0),"Shadow Monitor. Display snagged Pokemon data.")
        self.assertEqual(self.select(1),"Strategy Memo. Display data on all Pokemon met so far.")
        self.assertEqual(self.select(2),"Mailbox. Read received email.")
        self.assertEqual(self.select(3),"Spot Monitor. Check the Poke Spots.")
        self.assertEqual(self.select(4),"Cancel. Close P star D A.")

    def test_unchanged_cursor_is_deduplicated(self):
        self.select(2); self.reader.poll_once(); self.assertEqual(len(self.speech.calls),1)

    def test_invalid_cursor_is_rejected(self):
        self.backend.put(PDA_HOME_CURSOR_ADDRESS,be32(9))
        with self.assertRaises(Exception): self.reader.poll_once()


@unittest.skipUnless(pinned_build.is_vanilla_us(), pinned_build.SKIP_REASON)
class PdaCatalogTests(unittest.TestCase):
    """P*DA text read from the installed archive.

    Pinned to vanilla US XD's wording, so it skips on another build --
    see pinned_build.py. Only this class reads shipped text; the rest of
    this module drives the reader with synthetic messages and runs
    everywhere."""

    def test_owned_catalog_resolves_current_mail(self):
        path=Path(__file__).parents[1]/"_dialogue_extraction/pda/files/pda_menu.fsys"
        catalog=PdaCatalog(path); sender,subject,body=catalog.mail(2,"LEON")
        self.assertEqual((sender,subject),("Krane","Have you found JOVI?"))
        self.assertIn("Dear Leon",body)

    def test_home_options_come_from_owned_catalog_messages(self):
        path=Path(__file__).parents[1]/"_dialogue_extraction/pda/files/pda_menu.fsys"
        catalog=PdaCatalog(path)
        self.assertEqual(catalog.home_option(0),(
            "Shadow Monitor", "Display snagged POKéMON data."
        ))


class FlagReader:
    def __init__(self, values): self.values = values
    def value(self, flag_id): return self.values.get(flag_id)


class RuntimeCatalog:
    def __init__(self, values): self.values = values
    def text(self, message_id): return self.values.get(message_id)


class PdaMonitorReaderTests(unittest.TestCase):
    def setUp(self):
        self.backend=Backend(); self.memory=Memory(self.backend); self.speech=Speech()
        self.log=logging.getLogger("pda-monitor-test")
        self.log.addHandler(logging.NullHandler())

    def windows(self, *menu_ids):
        addresses=[0x80100000+i*0x100 for i in range(len(menu_ids))]
        for index,(address,menu_id) in enumerate(zip(addresses,menu_ids)):
            self.backend.put(address+p.window_menu_id_offset,be32(menu_id))
            self.backend.put(address+p.window_next_offset,
                             be32(addresses[index+1] if index+1<len(addresses) else 0))
        self.backend.put(p.window_manager+p.window_list_offset,be32(addresses[0]))

    def species(self, names):
        base,count_pointer=0x80110000,0x8010F000
        self.backend.put(POKEMON_DATA_NUMBER,be32(count_pointer))
        self.backend.put(count_pointer,be32(max(names)+1))
        self.backend.put(POKEMON_DATA,be32(base))
        messages={}
        for species_id,(message_id,name) in names.items():
            self.backend.put(base+species_id*POKEMON_DATA_STRIDE+POKEMON_NAME_OFFSET,
                             be32(message_id))
            messages[message_id]=name
        return RuntimeCatalog(messages)

    def test_spot_monitor_reads_game_locations_species_and_flag_values(self):
        self.windows(PDA_PARENT_MENU_ID,SPOT_MONITOR_MENU_ID)
        records=0x80120000
        count_pointer=0x8011F000
        self.backend.put(SPOT_DATA_COUNT_ADDRESS,be32(count_pointer))
        self.backend.put(count_pointer,be32(3))
        self.backend.put(SPOT_DATA_ADDRESS,be32(records))
        world=0x80121000
        self.backend.put(WORLD_MAP_DATA_ADDRESS,be32(world))
        values={10:3,11:27,20:0,21:0,30:7,31:104,
                40:1,41:1,42:1}
        for world_index,flag_id in zip((15,16,17),(40,41,42)):
            self.backend.put(world+world_index*WORLD_MAP_RECORD_SIZE
                             +WORLD_MAP_FLAG_OFFSET,be32(flag_id))
        for index,(food_flag,species_flag) in enumerate(((10,11),(20,21),(30,31))):
            record=records+index*SPOT_RECORD_SIZE
            self.backend.put(record,be32(food_flag))
            self.backend.put(record+0x0C,be32(species_flag))
        reader=PdaReader(self.memory,p,Catalog(),self.speech,self.log,
                         FlagReader(values),self.species({27:(60027,"Sandshrew"),104:(60104,"Cubone")}))
        reader.poll_once(); reader.poll_once()
        self.assertEqual(len(self.speech.calls),1)
        self.assertEqual(self.speech.calls[0][0][1],
                         "Spot Monitor. Rock: Sandshrew: 3. Oasis: 0. Cave: Cubone: 7")

    def test_shadow_monitor_tracks_sorted_list_cursor(self):
        self.windows(PDA_PARENT_MENU_ID,SHADOW_MONITOR_MENU_ID)
        obj,records=0x80130000,0x80131000
        self.backend.put(SHADOW_LIST_OBJECT_ADDRESS,be32(obj))
        self.backend.put(obj,be32(2))
        self.backend.put(obj+SHADOW_LIST_RECORDS_OFFSET,be32(records))
        self.backend.put(records+4,(27).to_bytes(2,"big"))
        self.backend.put(records+12,(104).to_bytes(2,"big"))
        runtime=self.species({27:(60027,"Sandshrew"),104:(60104,"Cubone")})
        reader=PdaReader(self.memory,p,Catalog(),self.speech,self.log,
                         FlagReader({}),runtime)
        self.backend.put(SHADOW_CURSOR_ADDRESS,b"\0\0\0\0")
        reader.poll_once()
        self.backend.put(SHADOW_CURSOR_ADDRESS,b"\0\1\0\0")
        reader.poll_once(); reader.poll_once()
        self.assertEqual([call[0][1] for call in self.speech.calls],
                         ["Shadow Monitor. Sandshrew", "Shadow Monitor. Cubone"])

    def test_spot_monitor_omits_locked_world_map_spots(self):
        self.windows(PDA_PARENT_MENU_ID,SPOT_MONITOR_MENU_ID)
        records,world=0x80120000,0x80121000
        count_pointer=0x8011F000
        self.backend.put(SPOT_DATA_COUNT_ADDRESS,be32(count_pointer))
        self.backend.put(count_pointer,be32(3))
        self.backend.put(SPOT_DATA_ADDRESS,be32(records))
        self.backend.put(WORLD_MAP_DATA_ADDRESS,be32(world))
        values={10:2,11:27,40:1,41:0,42:0}
        for world_index,flag_id in zip((15,16,17),(40,41,42)):
            self.backend.put(world+world_index*WORLD_MAP_RECORD_SIZE
                             +WORLD_MAP_FLAG_OFFSET,be32(flag_id))
        self.backend.put(records,be32(10)); self.backend.put(records+0x0C,be32(11))
        reader=PdaReader(self.memory,p,Catalog(),self.speech,self.log,
                         FlagReader(values),self.species({27:(60027,"Sandshrew")}))
        reader.poll_once()
        self.assertEqual(self.speech.calls[0][0][1],
                         "Spot Monitor. Rock: Sandshrew: 2")

    def test_strategy_memo_tracks_native_sorted_species_and_cursor(self):
        self.windows(*STRATEGY_LIST_MENU_IDS)
        obj,records=0x80140000,0x80141000
        self.backend.put(STRATEGY_LIST_OBJECT_ADDRESS,be32(obj))
        self.backend.put(obj+STRATEGY_LIST_RECORDS_OFFSET,be32(records))
        self.backend.put(records,(27).to_bytes(2,"big"))
        self.backend.put(records+2,(104).to_bytes(2,"big"))
        runtime=self.species({27:(60027,"Sandshrew"),104:(60104,"Cubone")})
        reader=PdaReader(self.memory,p,Catalog(),self.speech,self.log,
                         FlagReader({}),runtime)
        self.backend.put(STRATEGY_CURSOR_ADDRESS,b"\0\0\0\0")
        reader.poll_once()
        self.backend.put(STRATEGY_CURSOR_ADDRESS,b"\0\1\0\0")
        reader.poll_once()
        self.assertEqual([call[0][1] for call in self.speech.calls],
                         ["Strategy Memo. Sandshrew", "Strategy Memo. Cubone"])


if __name__ == "__main__": unittest.main()
