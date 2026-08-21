# MASTER.md

**The single map of everything this project has built.** One entry per
feature: what it does for the player, which module owns it, how it is
verified, and what is still open.

**Status: 2026-08-17.** This is a snapshot of a project under active
change — two workers were editing the tree while it was written. Where a
number is quoted (test counts, record counts) it is what the code
reported on the date shown. Treat every row as a pointer into the
detailed document beside it, never as a replacement for it.

**What this is not.** It is not the per-screen status inventory — that is
[ACCESSIBILITY_COVERAGE_MATRIX.md](ACCESSIBILITY_COVERAGE_MATRIX.md),
which carries ~100 rows with severity, reachability and live-test state
and remains authoritative for "is screen X accessible yet". It is not the
change history — that is
[IMPLEMENTATION_ATTRIBUTION.md](IMPLEMENTATION_ATTRIBUTION.md). This
document answers a different question: *what exists, and how does it fit
together.*

---

## 1. What the project is

An external, read-only Windows companion for **Pokémon XD: Gale of
Darkness** (US, `GXXE01` rev 0) and the **XG: NeXt Gen** ROM hack, for
blind and low-vision players. Distributed as **Pokémon XD: Game in
Darkness**.

It runs beside an unmodified Dolphin, polls emulated memory through
`dolphin-memory-engine`, and speaks through NVDA via `cytolk`/Tolk. It
does not patch the game, modify the disc image, alter Dolphin, or use the
network.

**Read-only, with two deliberate, documented exceptions.** Both were
authorised explicitly by the project owner and both are narrow:

| Module | What it writes | Why it is not a hack |
|---|---|---|
| `teleport.py` | the player's position, once per activation | the only module that writes a *position* |
| `hero_stick.py` | the engine's own scripted-stick override | writes a control the engine already uses on itself (`_setStickData`, 0x8014E7D4); does not synthesise controller input and does not need Dolphin focus |

Everything else reads. See [ACCESSIBILITY_MASTER_PLAN.md](ACCESSIBILITY_MASTER_PLAN.md)
for the philosophy and [PRODUCTION_INTEGRATION_POLICY.md](PRODUCTION_INTEGRATION_POLICY.md)
for the rule about promoting verified work into the default narrator.

---

## 2. How it is put together

```
Setup.cmd ──▶ setup_companion.py ──▶ bootstrap_game_data.py ──▶ _dialogue_extraction/
                                                                (local game data)
Access Layer.cmd ──▶ launch_accessible.py ──┬──▶ run_accessible_pokemon_xd.py
                                                    │      └─▶ phase1b_app.run()
                                                    └──▶ Dolphin
```

- **`phase1b_app.py`** builds every reader from one place and owns the
  CLI. It is the wiring diagram: read it to find who depends on what.
- **`phase1b_lifecycle.py`** owns the poll loop, Dolphin attach/detach,
  and which readers are allowed to speak in which context.
- **`profile.py`** holds every address, offset and default for the
  supported build. Nothing hardcodes an address anywhere else.
- **`speech.py`** is the single speech gate — priority classes and
  suppression — so two readers cannot talk over each other.
- **`memory.py`** is the single read path, with range checks.
- **`text_safety.py`** is the project's only Unicode boundary.

Deeper: [ARCHITECTURE_CODEMAP.md](ARCHITECTURE_CODEMAP.md),
[ACCESSIBILITY_ARCHITECTURE_V2.md](ACCESSIBILITY_ARCHITECTURE_V2.md).

---

## 3. Battle

| Feature | Owner | State |
|---|---|---|
| Command menu (Fight/Item/Pokémon/Call), move menu with type and PP | `menus.py`, `resolver.py` | Live-tested |
| Message narration from the game's own text | `narrator.py`, `message_render.py`, `messages.py`, `battle_opcodes.py` | Live-tested |
| Settled HP loss as percentages, poison/faint separation | `health.py` | Regression-tested |
| Manual HP summary (`ctrl+h`) | `hotkeys.py` | Live-tested |
| "Which Pokémon is this event about" | `battle_identity.py` | Live-tested |
| Stat-stage changes, paralysis, send-out, level-up, EXP, money, victory/defeat | `narrator.py` | see matrix per row |
| Heart Gauge summary (`ctrl+s`), Shadow status, Reverse/Hyper mode | `hotkeys.py`, `npc_shadow.py` | Implemented |
| Money summary (`ctrl+m`) | `hotkeys.py` | Implemented |

`battle_opcodes.py` carries the complete `msgctrlcode` dispatch table as
data — the reason messages are *rendered* rather than pattern-matched.

Detail: [BATTLE_SYSTEM_ARCHITECTURE.md](BATTLE_SYSTEM_ARCHITECTURE.md),
[BATTLE_MESSAGE_PIPELINE.md](BATTLE_MESSAGE_PIPELINE.md),
[BATTLE_IDENTITY_MODEL.md](BATTLE_IDENTITY_MODEL.md),
[PHASE_1F_HEALTH_NARRATION.md](PHASE_1F_HEALTH_NARRATION.md),
[SHADOW_POKEMON_SYSTEM_INVESTIGATION.md](SHADOW_POKEMON_SYSTEM_INVESTIGATION.md).

---

## 4. Overworld navigation

The largest subsystem, and the one with the most independent parts.

### 4.1 Knowing what is there

`entities.py` defines the source-agnostic entity; `entity_sources.py`
composes the sources. Each category has an owner with its own identity
key and position rule — that map is
[ENTITY_NAVIGATION_ARCHITECTURE.md](ENTITY_NAVIGATION_ARCHITECTURE.md),
which is authoritative and should be read before touching any source.

| Category | Source |
|---|---|
| NPCs (live actors) | `people_runtime.py` — the game's own `tagPeopleWork` pool |
| Warps, doors, elevators, PCs, signs | `authoritative_warps.py` — from `common.rel` |
| Ground pickups and item boxes | `treasure_entities.py` |
| Room-script objects and hazards | `interactables.py`, `interactable_roles.py` |
| Gateon Port bridge piers | `bridge_connections.py` |
| Roles (nurse, mart clerk…) | `npc_roles.py` |

`npc_shadow.py` runs the canonical NPC source alongside the production
one, speaking nothing, and logs disagreements — the evidence needed
before the two can be swapped.

### 4.2 Selecting and describing

`entity_nav.py` owns the cycle (`ctrl+.` / `ctrl+,`, categories with
shift, repeat with `ctrl+/`). `entity_names.py` and
`player_facing_names.py` turn engine identifiers into words.
`region_geometry.py` keeps a whole interaction region rather than
collapsing it to a centroid, and `region_target.py` decides *which
component* of a multi-part region the player is being sent to — so that
what navigation says and what the route targets are the same decision,
which they previously were not.

### 4.3 Getting there

| Mode | Keys | Owner |
|---|---|---|
| Plain beacon on the selection | `ctrl+g` | `audio_guide.py` |
| Routed navigation guide | `ctrl+n` | `audio_guide.py` + `navigation_service.py` |
| Autowalk (toggle) | `ctrl+shift+/` | `autowalk.py` + `hero_stick.py` |
| Teleport | `ctrl+t` | `teleport.py` |

`navigation_service.py` and `pathfinding.py` are the routing core (the
two largest modules in the project at ~1,500 and ~2,000 lines). Routing
is swept-passability against real CCD geometry with the pinned 3.5 hero
collision radius. `collision_probe.py`, `collision_object_enable.py`,
`line_of_sight.py` and `traversal_log.py` supply and check the geometry.

Autowalk deliberately asks `NavigationService` the same question the
routed guide asks, so a player can verify one against the other by ear.
It holds its own service instance rather than sharing the guide's.

### 4.4 Feeling where you are

| Feature | Owner |
|---|---|
| Passive per-category ambient beacons | `npc_beacons.py`, `npc_sounds.py` |
| Terrain footsteps (on by default) | `terrain_footsteps.py` |
| Blocked-movement cue (opt-in, `--collision-feedback`) | `terrain_footsteps.py`, `movement_input.py` |
| Room name on entering | `room_announcer.py` |
| World map | `world_map.py` |

Six categories beacon — NPC, Poké Mart, item, door, warp, elevator — each
with its own sound in `sounds/`. **A category with no sound of its own is
silent by design**, never given a borrowed tone: a wrong cue is worse
than no cue because the player acts on it. Doors that share a collision
region with a warp do not beacon (72 of 150 do), because the two would
play from the identical point.

Detail: [WORLD_NAVIGATION_ARCHITECTURE.md](WORLD_NAVIGATION_ARCHITECTURE.md),
[ENTITY_IDENTITY_MODEL.md](ENTITY_IDENTITY_MODEL.md),
[ENTITY_POSITION_AND_INTERACTION_POINTS.md](ENTITY_POSITION_AND_INTERACTION_POINTS.md),
[ENTITY_STATE_AND_BEACON_POLICY.md](ENTITY_STATE_AND_BEACON_POLICY.md),
[NPC_PROXIMITY_SOUNDS.md](NPC_PROXIMITY_SOUNDS.md),
[COLLISION_DETECTION_INVESTIGATION.md](COLLISION_DETECTION_INVESTIGATION.md),
[INTERACTABLE_OBJECTS.md](INTERACTABLE_OBJECTS.md),
[GATEON_BRIDGE_ACCESSIBILITY.md](GATEON_BRIDGE_ACCESSIBILITY.md).

---

## 5. Interaction

`talk_predicate.py` reproduces the game's own talk-eligibility test
companion-side — the engine's real three-term threshold, not an
approximation — so `interaction_ready.py` can tell the player when
pressing A will actually do something. `interaction_announcer.py` says
what just started ("Talked to X."). `model_parts.py` reads the neck joint
for the position those tests need.
`interaction_diagnostics.py` (`--interaction-diagnostics`) is
development-only: it scores manual A-presses against the prediction.

Detail: [INTERACTION_DIAGNOSTIC.md](INTERACTION_DIAGNOSTIC.md).

---

## 6. Dialogue and text

`dialogue.py` follows the field message task's moving page pointers,
waits for the authoritative completed state, speaks each page once,
interrupts obsolete pages, and re-arms on closure. `runtime_messages.py`
resolves IDs against the game's own loaded string tables;
`message_render.py` renders a live ID to the text the game itself would
draw. `shop_messages.py` covers greetings and farewells.

Detail: [TEXT_AND_DIALOGUE_PIPELINE.md](TEXT_AND_DIALOGUE_PIPELINE.md),
[OVERWORLD_NPC_DIALOGUE_VERTICAL_SLICE.md](OVERWORLD_NPC_DIALOGUE_VERTICAL_SLICE.md).

---

## 7. Menus and screens

| Screen | Owner |
|---|---|
| Title, main options, save notifications | `menus.py` |
| Generic yes/no and multiple-choice popups | `choice_menu.py` |
| Bag, categories, item lists | `bag_menu.py` |
| Shops: buy grid, quantity, notifications | `shop_menu.py` |
| Party list / action popup / summary pages | `party_list_screen.py`, `party_action_menu.py`, `party_summary_screen.py` |
| PC and box grid | `pc_menu.py` |
| Purify Chamber | `purify_chamber.py` |
| P✩DA, mail, monitors | `pda.py` |
| World travel map | `world_map.py` |

Item identity is shared infrastructure: `item_database.py` resolves
names, descriptions and IDs once for the bag, shops and party screens
rather than each re-deriving them.

Detail: [PDA_ACCESSIBILITY.md](PDA_ACCESSIBILITY.md),
[PC_AND_PURIFY_CHAMBER_RESEARCH.md](PC_AND_PURIFY_CHAMBER_RESEARCH.md),
[TITLE_MAIN_OPTIONS_ACCESSIBILITY.md](TITLE_MAIN_OPTIONS_ACCESSIBILITY.md).

---

## 8. The companion's own settings menu

**F1**, implemented 2026-08-16. `settings.py` is the model,
`settings_menu.py` the presentation, `key_capture.py` the input.

Navigation follows NVDA browse-mode convention rather than a game-menu
idiom: up/down move item by item across category boundaries and announce
a new heading on entry; `H`/`shift+H` jump by heading; left/right change
in place; enter/space toggle; escape or F1 close. Movement stops at the
ends and says so.

It needs a `WH_KEYBOARD_LL` hook rather than the polled
`WindowsForegroundHotkey` everything else uses, because these keys are
already the game's: F1 is Load State Slot 1, the arrows are the analog
stick, H is D-pad right, Return is Start. Polling would observe the press
without stopping Dolphin acting on it — the menu would load a save state
on open and walk the player around as they moved through the list. The
keys have to be *taken*, not noticed.

Settings apply to live readers and are re-applied whenever the lifecycle
rebuilds them, so a Dolphin reattach loses nothing. On/off toggles are
deliberately *not* applied — the lifecycle reads them at poll time, so
switching one off never tears down an expensive reader.

Preferences live in `Companion/companion_settings.json`, alongside the
paths Setup records; both writers merge rather than overwrite.

Detail: [SETTINGS_MENU.md](SETTINGS_MENU.md). **Not yet live-tested.**

---

## 9. Running on XG

The question the project carried from the start, answered 2026-08-11:
**yes, with defects found and fixed.**

The normative rule that came out of it: **one code path serves vanilla
and XG, with no game-identity switch.** The two discs share a label
(`GXXE01` rev 0), an internal name, a section layout and all eight
`profile.engine_signatures` — correctly, since the code those check is
unchanged. Nothing outside the data distinguishes them, so every
per-build fact is *derived at load* or *read live*, never selected by
asking which game this is.

| Module | What it derives |
|---|---|
| `game_build.py` | which build is running, by fingerprinting the running code — needed because pointing XG data at vanilla (or the reverse) produces a mostly-silent move menu rather than a loud failure, which happened twice in both directions |
| `ability_layout.py` | the abilities record layout, read from the three engine accessors' immediate fields — XG 1.2.1 packs 106 abilities where vanilla had 78 by dropping a field, moving stride 12→8 |
| `check_image_compatibility.py` | the same gate as `check_game_compatibility.py` but against a disc file, before booting, and can diff two images |
| `Tools/apply_ups_patch.py` | applies a UPS patch verifying all three CRC32s, so "the hack built correctly" is proven rather than assumed |

Detail: [XG_COMPATIBILITY.md](XG_COMPATIBILITY.md) — read its data-sourcing
rules before touching any loader, and its §8/§9 before quoting any result.

---

## 10. Distribution and first run

The release is allowlist-built and contains **no game data of any kind**.

| Step | Owner |
|---|---|
| Build the archive | `Tools/Build Accessibility Release.ps1` |
| Stage the bundled interpreter | `Tools/build_runtime.py` |
| Find Dolphin and the player's game | `Companion/setup_discovery.py` |
| First-run setup | `Setup.cmd` → `Companion/setup_companion.py` |
| Generate game data from the player's own disc | `Companion/bootstrap_game_data.py` |
| Launch | `Access Layer.cmd` → `Companion/launch_accessible.py` |

**First run, as of 2026-08-18: extract, `Setup.cmd`, `Launch Accessible
XD.cmd`.** No Python to install — a release carries its own in `Runtime/`
— and no paths to type: setup finds Dolphin and the disc image and asks
the player to confirm or pick a number. Extracting the release inside the
Dolphin folder makes it a single Enter. Verified end to end on 2026-08-18
from a clean extraction with no Python on the path; the live *launch* path
from a bundled release is still untested. Detail and the unverified list:
[FIRST_RUN_AND_RUNTIME.md](FIRST_RUN_AND_RUNTIME.md).

**Why setup needs the player's disc.** The companion reads the game's own
text, item, move and collision tables. Those are copyrighted and are
never packaged; the release ships the code that reads them and each
player generates the data locally. `bootstrap_game_data.py` produces the
runtime subset in about five seconds — *not* the 264 MB development tree.
Plain `.iso`/`.gcm` are read directly; compressed formats go through
DolphinTool to a temporary ISO that is then deleted.

**Required** (the narrator refuses to start without them):
`raw/files/{common,fight_common,pocket_menu}.fsys` and
`dol_strings.json`. **Optional** (each disables only its own feature):
collision CCDs, worldmap, P✩DA, `battle_disk`.

The builder refuses to produce an archive unless three checks pass: no
forbidden content (disc images, saves, extracted data, `.venv`,
research); every beacon sound the *staged* code declares is staged, read
back out of `PASSIVE_BEACON_SOUND_FILES` so a new category cannot ship
silent; and the staged tree compiles and its setup-path entry points
import.

Detail: [FIRST_RUN_AND_RUNTIME.md](FIRST_RUN_AND_RUNTIME.md),
[README-DISTRIBUTION.md](../README-DISTRIBUTION.md),
[DISTRIBUTION_PIPELINE.md](DISTRIBUTION_PIPELINE.md),
`Tools/release-manifest.txt`.

---

## 11. How anything here gets believed

The project's standing methodology is static-first, ownership before
observation, no blind memory diffing. Concretely:

- **Address and layout facts** are derived from the game's own code or
  data, never pinned to a constant that happened to be true of one build.
  The abilities layout and the DOL string tables are both examples of a
  scan replacing a hardcoded address for exactly this reason.
- **Every change ships with tests.** 1,695 as of 2026-08-17, run after
  every change, of which 2 are currently failing (see §12). Use
  `unittest.TestCase`, never bare `def test_*` — bare pytest-style
  functions are silently not collected, which is how a real PC box-grid
  bug survived. Note that `tests/` has no `__init__.py` and the tests
  import `battle_narrator.*`, so discovery must put `Companion` on
  `sys.path` and use `tests/` as its own top-level directory; the obvious
  invocations collect nothing.
- **Live testing is recorded separately from implementation.** A feature
  is "Implemented" until someone's ears confirm it; the coverage matrix
  tracks the two states apart on purpose.
- **Generated data is verified against an oracle where one exists.** The
  bootstrap was proven by regenerating the whole local tree from the disc
  and getting all 189 files byte-identical.

See [feedback_reverse_engineering_philosophy] in the project's standing
rules, [VERTICAL_SLICE_TEMPLATE.md](VERTICAL_SLICE_TEMPLATE.md), and
[MILESTONE_SAVE_INDEX.md](MILESTONE_SAVE_INDEX.md) for the saves used to
re-test.

---

## 12. What is open

Read [ACCESSIBILITY_BACKLOG.md](ACCESSIBILITY_BACKLOG.md) and
[PLAYTHROUGH_BARRIER_LOG.md](PLAYTHROUGH_BARRIER_LOG.md) for the live
lists. As of this snapshot:

- **Two failing tests** in `tests/test_passability.py`
  (`DestinationProjectionTests`): a cross-level target gets no guidance
  at all, and partial guidance routes to a floor above the target. Both
  are in the region-routing work in flight on 2026-08-12+, not
  independent regressions.
- **Region-aware routing is not live-tested** —
  [REGION_ROUTING_LIVE_TEST_PLAN.md](REGION_ROUTING_LIVE_TEST_PLAN.md)
  is written and deliberately not started.
- **The settings menu is not live-tested**, and one claim in
  SETTINGS_MENU.md §3 needs live confirmation.
- **Gateon Port bridges are disabled in a release.** The feature needs
  `rooms/M6_out.txt`, which comes from a third-party disassembler the
  bootstrap does not carry. It degrades to silence, as designed.
- **XG verification is largely static.** Only 8 of 104 profile addresses
  were checkable that way.
- **No end-to-end live run of a built release.** Everything claimed
  about the archive is static verification plus loader construction.
