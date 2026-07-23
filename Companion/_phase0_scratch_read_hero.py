"""
Read-only Phase 0B baseline check. Sources (all from xd-decomp's own
resolved symbol map, config/GXXE01/symbols.txt):
    _orreHero = .bss:0x8043C930   size 0x978  (static Hero instance)
    _menuCtrlHero = .bss:0x804B00A4 size 0x978 (static Hero instance, menu-context)
    g_pHero   = .sbss:0x804EBBE0  size 0x4    (global pointer, scope:global)

Hero struct (include/game/pxdvs/app/hero/hero.hpp):
    partyPokemon[6] at +0x30, each Pokemon struct is 0xC4 bytes
    (confirmed by (0x4c8 - 0x30) / 6 == 0xC4, matching Pokemon-XD-Code's
    independently-derived kSizeOfPartyPokemonData == 0xc4)

Pokemon struct (include/game/pxdvs/app/pokemon/pokemon.hpp):
    hp at +0x4 (u16), condition at +0x16 (u8), maxHp at +0x90 (u16)

This script only reads. No writes performed anywhere.
"""
import dolphin_memory_engine as dme

ORRE_HERO_ADDR = 0x8043C930
MENU_CTRL_HERO_ADDR = 0x804B00A4
G_P_HERO_ADDR = 0x804EBBE0
PARTY_OFFSET = 0x30
POKEMON_SIZE = 0xC4
HP_OFFSET = 0x4
CONDITION_OFFSET = 0x16
MAXHP_OFFSET = 0x90

dme.hook()
try:
    if not dme.is_hooked():
        print("ERROR: not hooked.")
    else:
        g_pHero_value = dme.read_word(G_P_HERO_ADDR)
        print(f"g_pHero (at 0x{G_P_HERO_ADDR:08X}) currently holds: 0x{g_pHero_value:08X}")
        print(f"  Compare to _orreHero address:     0x{ORRE_HERO_ADDR:08X} -> {'MATCH' if g_pHero_value == ORRE_HERO_ADDR else 'no match'}")
        print(f"  Compare to _menuCtrlHero address:  0x{MENU_CTRL_HERO_ADDR:08X} -> {'MATCH' if g_pHero_value == MENU_CTRL_HERO_ADDR else 'no match'}")

        for label, base in [("_orreHero", ORRE_HERO_ADDR), ("_menuCtrlHero", MENU_CTRL_HERO_ADDR)]:
            print(f"\n--- {label} (base 0x{base:08X}) ---")
            party0 = base + PARTY_OFFSET
            hp = dme.read_word(party0 + HP_OFFSET) if False else None
            # hp/maxHp are 16-bit; read as bytes and interpret big-endian (PowerPC is big-endian)
            raw_hp = dme.read_bytes(party0 + HP_OFFSET, 2)
            raw_maxhp = dme.read_bytes(party0 + MAXHP_OFFSET, 2)
            raw_condition = dme.read_bytes(party0 + CONDITION_OFFSET, 1)
            raw_dataid = dme.read_bytes(party0, 2)
            hp_val = int.from_bytes(raw_hp, byteorder="big")
            maxhp_val = int.from_bytes(raw_maxhp, byteorder="big")
            condition_val = raw_condition[0]
            dataid_val = int.from_bytes(raw_dataid, byteorder="big")
            print(f"  partyPokemon[0] dataID (species, +0x0, u16 BE): {dataid_val}")
            print(f"  partyPokemon[0] hp        (+0x4,  u16 BE): {hp_val}")
            print(f"  partyPokemon[0] maxHp     (+0x90, u16 BE): {maxhp_val}")
            print(f"  partyPokemon[0] condition (+0x16, u8):     {condition_val}")
finally:
    dme.un_hook()
    print("\nun_hook() called.")
