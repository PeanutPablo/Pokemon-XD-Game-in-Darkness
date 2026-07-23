"""
One-off, read-only verification: confirms the loaded game's disc header
(game ID + version byte) via the well-documented, fixed GameCube disc-header
location at 0x80000000 in MEM1. This is not a guessed/static game-logic
offset -- it is the standard GC/Wii disc header layout, identical across all
GameCube titles, used only to confirm which disc is actually running.

Read-only. No writes. Not part of production code -- a Phase 0A scratch check.
"""
import dolphin_memory_engine as dme

dme.hook()
try:
    if not dme.is_hooked():
        print("ERROR: not hooked.")
    else:
        header = dme.read_bytes(0x80000000, 0x20)
        game_id = header[0:6].decode("ascii", errors="replace")
        disc_id = header[0]
        maker_code = header[4:6].decode("ascii", errors="replace")
        disc_number = header[6]
        game_revision = header[7]
        print(f"Raw header bytes[0:32]: {header.hex()}")
        print(f"Game ID (6 chars): {game_id}")
        print(f"Maker code: {maker_code}")
        print(f"Disc number: {disc_number}")
        print(f"Game revision/version byte: {game_revision}")
finally:
    dme.un_hook()
    print("un_hook() called.")
