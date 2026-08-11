# NPC Proximity Sounds

## Status

Production-integrated and live-memory validated on 2026-07-26.

Every visible, talkable NPC in the loaded room is discovered through the generic floor-character table. No NPC names, dialogue keys, room-specific lists, or character addresses are hard-coded.

## Behavior

- Every NPC uses the same confirmed-audible cue: `263124__mossy4__sine-octaves-up-beep.wav`. Stereo direction, distance volume, and vertical pitch vary dynamically; the underlying NPC sound does not.
- A cue is queued when the player enters a 22-world-unit radius.
- Multiple newly nearby NPCs play in nearest-first order without overlapping.
- A cue rearms only after that NPC leaves the radius.
- Hidden characters and records without a talk function remain silent.
- Leaving a room, disconnecting, or reconnecting clears proximity state.
- NPC read failures are isolated and cannot stop dialogue or battle narration.

## Verified generic structures

- Leader selector: `0x804479F0`
- Leader model resource IDs: `100`, `101`, `104`, `105`
- Resource-list head: `0x804EB008`
- Resource node: group `+0x08`, ID `+0x0C`, model pointer `+0x04`, next `+0x14`
- Live model position: model `+0x18` (`x`, `y`, `z` floats)
- Active-camera pointer: `0x804EAEE0`; camera rotation is at camera `+0x84`, with Y yaw at `+0x88` in radians
- Current floor ID: `0x80814AB6`
- Floor-data count/table roots: `0x804E8A30` / `0x804E8A34`
- Floor-data stride: `0x40`; character-table slot: `+0x0C`
- Character stride: `0x24`
- Character visibility: high bit of byte `+0x00`
- Talk function ID: `+0x14`
- Character position: `+0x18`, `+0x1C`, `+0x20`

In the live validation room, floor 141 contained nine records: six visible talkable NPCs and three hidden records. The live player position resolved independently through the leader model.

## Dialogue suppression and immediate speech

When an ordinary NPC dialogue box is open, `SpatialWavePlayer.stop()` is called and beacon polling is suspended until closure. Dialogue pages are decoded and spoken as soon as their prepared page buffer appears, without waiting for the visual typewriter animation to finish. Each spoken page is prefixed with the current interactable entity name, for example, “Lily: ...”. Page identity and transient-read protections remain active to prevent repetition.

## People/name resolution

Character name indexes are resolved from the game's own `common.rel` PeopleIDs table and common string table. Named entities use their real game name; entries with no supplied name use “NPC.” Interaction radius comes from each entity's `peopleInfoData + 0x24` talk-distance field. A verified 1.5-unit collision allowance is added because live validation found the player/NPC collision boundaries held their centers at 3.05 units while the raw talk distance was 3.0.

## Sound attribution

The supplied “Video game beeps” pack is by Freesound user Mossy4 and is licensed under Creative Commons Attribution 4.0:

- Author: https://freesound.org/people/Mossy4/
- Pack: https://freesound.org/people/Mossy4/packs/16196/
- License: https://creativecommons.org/licenses/by/4.0/

The original `_readme_and_license.txt` remains beside the WAV files.

## Implementation and verification

Primary implementation:

- `Companion/battle_narrator/npc_beacons.py`
- `Companion/battle_narrator/profile.py`
- `Companion/battle_narrator/phase1b_lifecycle.py`
- `Companion/battle_narrator/phase1b_app.py`

Focused tests: `Companion/tests/test_npc_sounds.py`.

Full suite result after rapid interaction pulses and named immediate dialogue: **178 tests passed**.

## Signature

Prepared from static PowerPC disassembly, live read-only Dolphin memory, production implementation, and automated regression tests.

**Signed: Codex (OpenAI)**  
**Date: 2026-07-26**








## Reserved sound language for additional overworld entities

The following category-level mapping is reserved so a blind player can identify an entity by sound before reaching it. Every entity in a category uses the same sound, and no two listed categories share a sound:

| Category | Sound |
|---|---|
| Ordinary NPC | `263124__mossy4__sine-octaves-up-beep.wav` |
| Item | `263129__mossy4__sine-up-flutter-beep.wav` |
| Door | `263126__mossy4__tone-beep-lower-slower.wav` |
| Warp | `263655__mossy4__upward-beep-chromatic-fifths.wav` |
| Nurse or healing station | `263132__mossy4__tri-tone-up-beep.wav` |
| Store clerk | `263125__mossy4__sine-fifths-up-beep.wav` |
| Poké Box | `263128__mossy4__tone-beep-amb-verb.wav` |

The spatial treatment remains shared: camera-relative stereo, forward/back pitch, distance volume and cadence, rapid interaction-range pulses, and silence during dialogue. Personnel with a special role use their role sound instead of the ordinary-NPC sound.

Documented and reserved by **Codex (OpenAI)** on **2026-07-26**.

### SUPERSEDED for the shipping beacons (2026-08-05)

The table above is the original *reserved* language. What actually plays is
now `npc_beacons.PASSIVE_BEACON_SOUND_FILES`, a smaller set of categories
the project owner named, using the project's own `sounds/` directory rather
than the numbered placeholder clips:

| Category | Sound |
|---|---|
| NPC | `sounds/npcs.wav` |
| Poké Mart | `sounds/pokemarts.wav` |
| Item | `sounds/items.wav` |
| Door | `sounds/doors.wav` — *interior doors only, see 2026-08-10 below* |
| Warp | `sounds/warps.wav` |
| Elevator | `sounds/elevators.wav` — *added 2026-08-10* |

Three consequences worth stating plainly:

- **Categories outside this set are silent.** "healing" entries still reach
  the reader but have no sound of their own, and `beacon_categories` skips
  them rather than letting them fall back to the generic NPC tone. A wrong
  cue is worse than no cue — the player acts on it. ("elevator" was the
  other standing example until it got a file on 2026-08-10.)
- **Poké Mart is a re-label, not an extra entity.** Mart NPCs are already
  in the NPC stream, so `RecategorisedNPCSource` changes their category in
  place. Appending them (the way doors and warps are appended) would have
  left one character beaconing twice from the same spot. The identifying
  signal is the room id (`profile.pokemart_room_ids`), matching the
  definition entity-nav already uses for its "Pokemon Mart clerk"
  interactable — role NPCs carry no distinguishing interaction record.
- **Items come from the live treasure source.** `NPCMemorySource`'s own
  curated `ITEMS` table is empty, so relying on it would have meant no item
  beacons at all.

The beacon reader was also re-enabled here; it had been muted at the
project owner's request back when every category shared one loud tone.

### Elevators gain a sound, entrance doors lose theirs (2026-08-10)

Both at the project owner's request, after live listening.

**Elevators now beacon** with `sounds/elevators.wav`. They were the worked
example of a silent category above for as long as they had no file of their
own; `AuthoritativeElevatorEntitySource` has always published them, so the
change is the sound plus one more `WarpAugmentedNPCSource` link in
`npc_sound_factory`'s chain. All 46 elevator records in the game resolve
against real CCD data.

**A door that shares its collision region with a warp no longer beacons.**
In this game's data a building entrance is *both* records at once — the
Door record animates the doorway, the Warp record moves you — so the two
beacons played from the identical point and the player heard a doubled cue
at every entrance. Measured over the real interaction table, **72 of 150
doors** are attached to a warp this way; the other 78 (interior doors,
scenery) are untouched and still beacon.

The warp is the one kept: it is what the player is navigating *to*, and it
names its destination ("to Pokémon HQ Lab"), which a door cannot.

Mechanically, `AuthoritativeDoorEntitySource` now takes the warp records
and publishes an attached door with `metadata["beacon"] = False` rather
than dropping it. That is the existing contract from
`entity_sources.WarpAugmentedNPCSource` — beacon eligibility is not
navigation eligibility — so the door stays a known entity for anything that
wants to reason about it, and only the sound goes. (Doors are not in the
entity-nav cycle either way; they were removed from it on 2026-08-05.)

Region indices are per-room, so the match is on `(room_id, region_index)`;
comparing on region alone would silence doors all over the game. Coverage:
`AuthoritativeDoorEntitySourceTests` in `tests/test_authoritative_warps.py`.

### Sound file format (fixed the same day, after a live crash)

`SpatialWavePlayer.play` originally accepted **16-bit PCM only** and raised
`ValueError` on anything else. The project's `sounds/` files are **24-bit**,
so the first beacon that came into range killed the narrator outright —
speech, menus and all — several minutes into play, in a category-dependent
and therefore awkward-to-reproduce way. Three separate defects, all fixed:

1. **Format support.** `_decode_pcm` now normalises 8-, 16-, 24- and 32-bit
   PCM to the 16-bit scale on load (`SUPPORTED_SAMPLE_WIDTHS`). Nothing
   downstream ever needed 16-bit input, so the restriction was a trap
   rather than a constraint — dropping a new sound in should not require
   knowing the project's internal sample format. Amplitude is normalised
   across depths, so swapping a file's bit depth does not change how loud
   it is. Note 8-bit WAV is the one depth stored *unsigned*, with 128 as
   silence.
2. **Fail fast.** `check_playable()` runs as a startup pre-flight over
   every beacon sound, naming the file and the reason. The previous check
   only tested that files *existed*, which passed happily and deferred the
   real failure to the poll loop.
3. **Contain the blast radius.** `poll_npc_sounds` caught only
   `MemoryError`, so a playback `ValueError` escaped and terminated the
   process. It now also catches `ValueError`/`wave.Error`/`OSError`,
   disables beacons for the session and logs at WARNING. Losing beacons is
   an inconvenience; losing the whole narrator while someone is relying on
   it to play is not.

Regression coverage: `tests/test_npc_interactions.py::WaveFormatTests`
renders every supported width through the real player, checks the real
`sounds/` files pass the pre-flight, and asserts depths agree on level.

### Long clips masked every other beacon (2026-08-05)

Reported as "doors have no sound, or maybe the volume is really low". It
was neither: doors resolved to `doors.wav` at gain 0.35-0.53 and, measured,
played 14 times in 20 simulated seconds. They were **masked**.

The cause is clip length. The scheduler's interaction-range pulse repeats
every 0.18s and blocks for a flat 0.12s — sized for the original ~0.29s
placeholder cues. The project's own sounds run to 2.20s (`npcs.wav`) and
2.25s (`pokemarts.wav`), so standing near any NPC stacked **twelve
simultaneous copies of the same sound** into a continuous drone at the
loudest gain in the mix, and everything else disappeared underneath it.

Two constants fix it:

- `SELF_REPEAT_GAP_SECONDS` — a repeat interval is now at least the
  sound's own length, so a beacon can never overlap **itself**. Different
  entities sharing a sound may still overlap: two doors in different
  directions is information, one door playing over itself is a drone.
- `MAX_BEACON_BLOCK_SECONDS` — one beacon may hold the single scheduler
  slot for at most 0.45s, so a long clip ringing on does not stop other
  categories starting. `SpatialWavePlayer` mixes on concurrent channels,
  so this is purely about when a NEW beacon may begin.

Measured effect, same scenario: peak simultaneous sounds **12 → 3**, and
`npcs.wav` plays **66 → 9**, while doors stay at 14. Coverage:
`BeaconOverlapTests`.

**Standing caveat:** a 2.2s beacon cannot pulse rapidly, so the
interaction-range "you are in range" cadence is now effectively one pulse
per clip length for the long sounds. That is a property of the audio, not
something the scheduler can paper over — shorter clips would restore it.

## Beacon volume: full scale, with a per-category trim (2026-08-05)

Supersedes the "quarter-scale" note below, which set an absolute
multiplier. Volume is now expressed as a **relationship** to the navigation
beacon's own curve, with two knobs on top:

```
navigation_gain(proximity) = 0.25 + 0.55 * proximity     # 0.25 far, 0.80 arrived
passive gain = PASSIVE_BEACON_GAIN_SCALE                 # global, currently 1.0
             * PASSIVE_BEACON_CATEGORY_GAIN[category]    # per-category, default 1.0
             * navigation_gain(proximity)
```

`navigation_gain` lives in `npc_beacons.py` and is imported by
`audio_guide.py`, so retuning the curve moves both together instead of
silently changing the ratio between them. These two constants are exactly
what the planned user-settings UI needs to expose.

They were first set to a global 0.25, then raised to full at the project
owner's request after hearing them in game. Warps carry a 0.5 trim: they
are the densest category in the game — a room can hold a great many, and
unlike an NPC or an item they are rarely the thing being looked for — so at
parity they crowd out the categories that matter. That is a mix decision,
not a statement about importance.

Resulting playback gain (warp trim set by ear: 0.5 was still too loud, now
0.20):

| Category | On top | Half range | Max range |
|---|---|---|---|
| NPC / Poké Mart / Item / Door | 0.800 | 0.525 | 0.349 |
| Warp | 0.160 | 0.105 | 0.070 |

The max-range column is the 0.18 proximity floor, not zero: an entity at
the edge of range stays faintly audible, which is the point of an ambient
beacon.
## Beacon volume quarter-scale and reliable nearest interaction name (2026-07-26)

Per user feedback, beacon gain was halved again: the distance curve now uses a 0.25 maximum multiplier instead of 0.50. Live restart verification showed the same nearby beacon fall from gain 0.38 to 0.19, exactly half its prior playback gain.

The interaction announcement previously depended only on set entry. That could miss a newly relevant entity when the player remained inside overlapping interaction zones and the nearest target changed. Production now tracks the nearest in-range interaction identity and announces whenever that nearest identity changes. `NPCInteractionContext.name` follows the same nearest entity for dialogue prefixes. New diagnostics record floor, NPC index, name ID, resolved name, and distance for every interaction announcement.

Tests verify exact-radius single announcement, nearest-target changes from Krane to Lily while both remain in range, and the new 0.25 maximum gain. Full suite: 223 passing. At live restart the nearest current NPC was 28.80 units away, outside the interaction radius, so no false name announcement was emitted.

Implemented, tested, live-verified, and documented by **Codex (OpenAI)** on **2026-07-26**.

## Constant-duration pitch shifting (2026-07-26)

Beacon pitch no longer changes playback speed. The old renderer changed the WAV sample rate to `rate * pitch`, which necessarily shortened high-pitched cues and lengthened low-pitched cues. Production now shifts the waveform spectrum at the original sample count and writes the original sample rate. Stereo pan and gain are applied afterward. Scheduler busy duration also uses the source duration directly rather than dividing by pitch.

Live output verification: source and pitched render were both 44,100 Hz, 16,365 frames, and 0.3711 seconds. Automated rendering verifies preserved rate, frame count, 16-bit samples, and stereo output. Full suite remains 223 passing.

Implemented, live-verified, and documented by **Codex (OpenAI)** on **2026-07-26**.

## Foreground-only beacon playback (2026-07-26)

Positional entity beacons now play only while Dolphin.exe owns the foreground window. Losing focus immediately stops the current beacon and clears its timing and interaction state. Returning focus resumes from a clean schedule, avoiding queued or rapid catch-up sounds. This gate applies to beacon audio; it does not disable the companion's other accessibility readers.

Implementation: NPCSoundReader accepts an injectable foreground predicate, while production uses WindowsForegroundProcess to identify the foreground executable. Automated coverage verifies immediate one-time stopping while unfocused and clean playback after focus returns.

Signed: **Codex (OpenAI)** — 2026-07-26

## Elevator beacon and map announcements (2026-07-26)

Implemented a distinct elevator beacon and automatic room announcements. Static analysis of the user's extracted Pokémon XD/XG assets identified the Pokémon HQ Lab 1F elevator as common interaction point 687 (room 0x8C, collision region 10) with collision-center coordinates x=0.0, y=15.0, z=-140.00003. Lab 2F uses interaction region 10 at x=0.0, y=15.0, z=16.1. These are injected as named Elevator entities and use 263131__mossy4__tone-beep-slower-lower-amb-verb.wav, distinct from the NPC sound. They retain stereo, pitch, distance cadence, dialogue suppression, and foreground-only gating.

NPCSoundReader now reads the current floor independently of NPC availability and announces a map only when its floor ID changes. The full 285-entry XD room-ID catalog is stored at Companion/assets/room_ids.json; broad area codes are expanded to names such as Pokémon HQ Lab, and room components are spoken in readable form. Unknown XG-added IDs safely fall back to Map plus the numeric ID.

Validation: automated tests cover one-time map-change announcements and elevator category-sound routing; full suite passes 226 tests.

Signed: **Codex (OpenAI)** — 2026-07-26

## P★DA item beacon (2026-07-26)

Implemented a named item beacon for the opening P★DA pickup in the player's bedroom. The authoritative room catalog places the bedroom in Pokémon HQ Lab Residential Wing 1F, floor ID 0x8A (M5_apart_1F). Static analysis of that room's script identified functions look_pda, in_heroroom, se_get_pda, and get_pda. The in_heroroom function tests the hero against x=-35..-25 and z=-114..-94 before invoking look_pda; the implemented beacon uses the exact zone center x=-30, y=15, z=-104 with interaction radius 10.

The virtual entity is labeled 'P star D A' for clear NVDA pronunciation and uses the dedicated item sound 263129__mossy4__sine-up-flutter-beep.wav. It inherits foreground-only playback, dialogue suppression, camera-relative stereo, direction pitch, distance gain, and proximity cadence. Automated coverage locks the room ID, center, and label; full suite passes 227 tests.

Signed: **Codex (OpenAI)** — 2026-07-26
