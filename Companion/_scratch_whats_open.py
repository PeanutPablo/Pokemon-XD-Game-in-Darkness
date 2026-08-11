"""One-off, read-only diagnostic: dump every currently open window's menu
ID and its +0x9F selection-index byte, and name it if it matches a known,
already-mapped menu from profile.py."""
import dolphin_memory_engine as dme

from battle_narrator.memory import MemoryReader
from battle_narrator.menus import WindowListWalker
from battle_narrator.pda import MAIL_CONTENT_MENU_ID, MAIL_PARENT_MENU_ID, PDA_HOME_MENU_IDS
from battle_narrator.profile import XD_US_REV0

dme.hook()
if not dme.is_hooked():
    raise SystemExit("Dolphin is not readable.")
memory = MemoryReader(dme, XD_US_REV0)

KNOWN = {
    XD_US_REV0.party_action_menu_id: "party action popup (Summary/Switch/Item/Cancel)",
    XD_US_REV0.party_item_action_menu_id: "item action popup (Give/Take/Cancel)",
    XD_US_REV0.bag_menu_id: "bag category tabs",
    XD_US_REV0.pause_menu_id: "pause menu",
    XD_US_REV0.party_list_menu_id: "party list screen",
    XD_US_REV0.party_summary_menu_id: "party summary screen",
    MAIL_PARENT_MENU_ID: "PDA mail list",
    MAIL_CONTENT_MENU_ID: "PDA mail content",
    XD_US_REV0.title_menu_id: "title menu",
    XD_US_REV0.new_game_confirmation_menu_id: "yes/no confirmation",
}
for menu_id in PDA_HOME_MENU_IDS:
    KNOWN.setdefault(menu_id, "PDA home menu")

nodes = WindowListWalker(memory, XD_US_REV0).walk()
if not nodes:
    print("No windows open.")
else:
    print(f"{len(nodes)} window(s) open:")
    for node in nodes:
        try:
            index = memory.u8(node.address + 0x9F, "selection index")
        except Exception:
            index = None
        known = KNOWN.get(node.menu_id, "(unmapped)")
        print(f"  menu_id={node.menu_id} (0x{node.menu_id:X}) address=0x{node.address:08X} index@+0x9F={index}  -- {known}")
