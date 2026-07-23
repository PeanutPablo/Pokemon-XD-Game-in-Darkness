"""
Phase 0B follow-up: g_pHero (.sbss:0x804EBBE0) is confirmed live (non-null
during gameplay). This reads the actual Hero instance it points to, rather
than the static _orreHero/_menuCtrlHero guesses (which turned out not to be
the live instance).

Read-only. No writes.
"""
import dolphin_memory_engine as dme

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
        hero_addr = dme.read_word(G_P_HERO_ADDR)
        print(f"g_pHero currently points to: 0x{hero_addr:08X}")
        if hero_addr == 0:
            print("NULL -- no active Hero instance right now.")
        else:
            for slot in range(6):
                party_n = hero_addr + PARTY_OFFSET + slot * POKEMON_SIZE
                raw_dataid = dme.read_bytes(party_n, 2)
                dataid_val = int.from_bytes(raw_dataid, byteorder="big")
                if dataid_val == 0:
                    continue  # empty slot
                raw_hp = dme.read_bytes(party_n + HP_OFFSET, 2)
                raw_maxhp = dme.read_bytes(party_n + MAXHP_OFFSET, 2)
                raw_condition = dme.read_bytes(party_n + CONDITION_OFFSET, 1)
                hp_val = int.from_bytes(raw_hp, byteorder="big")
                maxhp_val = int.from_bytes(raw_maxhp, byteorder="big")
                condition_val = raw_condition[0]
                print(f"\npartyPokemon[{slot}] at 0x{party_n:08X}:")
                print(f"  dataID (species): {dataid_val}")
                print(f"  hp: {hp_val}")
                print(f"  maxHp: {maxhp_val}")
                print(f"  condition: {condition_val}")
finally:
    dme.un_hook()
    print("\nun_hook() called.")
