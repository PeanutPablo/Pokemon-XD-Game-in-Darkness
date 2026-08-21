import argparse
import json
import time
from pathlib import Path
import wave

import dolphin_memory_engine as dme
from cytolk import tolk

from .battle_identity import (
    BattleIdentityResolver, BattlefieldSlotTracker, IdentityLabeller,
)
from .battle_start import BattleStartAnnouncer, OpponentPartySource
from .diagnostics import make_logger
from .dialogue import DialogueMemorySource, DialogueReader
from .collision_object_enable import LiveObjectEnableState
from .collision_probe import (
    parse_environment_triangles,
    parse_walk_model_triangles,
)
from .authoritative_warps import (
    AuthoritativeDoorEntitySource,
    AuthoritativeElevatorEntitySource,
    AuthoritativePCEntitySource,
    AuthoritativeTextEntitySource,
    AuthoritativeWarpEntitySource,
    load_door_records,
    load_elevator_records,
    load_pc_records,
    load_text_records,
    load_warp_records,
)
from .entity_names import (
    ScriptedSpeakerNameTable, load_entity_names,
)
from .player_facing_names import build_room_names
from .item_database import (
    ItemDatabase, ItemDescriptionResolver, ItemDescriptionTable,
    ItemNameResolver,
)
from .shop_messages import ShopMessageTable
from .pc_menu import PCMenuReader
from .room_announcer import RoomChangeReader
from .world_map import WorldMapCatalog, WorldMapReader
from .bag_menu import BagMenuModel, BagMenuReader, HeroItemArraySource
from .shop_menu import (
    ShopBuyMenuModel, ShopBuyMenuReader,
    ShopBuyQuantityModel, ShopBuyQuantityReader,
    ShopNotificationModel, ShopNotificationReader,
)
from .audio_guide import AudioGuideReader, GuideModes
from .autowalk import AutowalkReader
from .hero_stick import HeroStickOverride
from .teleport import TeleportReader
from .terrain_footsteps import (
    BlockedMovementReader, TerrainFootstepReader, TerrainTonePlayer,
)
from .movement_input import GSinputMovementSource
from .treasure_entities import LiveTreasureEntitySource
from .general_flags import GeneralFlagReader, load_general_flag_layout
from .entity_nav import EntityNavigator
from .interaction_announcer import InteractionAnnouncer
from .interaction_ready import InteractionReadyReader
from .choice_menu import ChoiceMenuReader
from .runtime_messages import RuntimeMessageCatalog
from .entity_sources import (
    CategoryFilteredEntitySource, CombinedEntitySource, FilteredEntitySource,
    GlobalCompanionEntitySource, LiveNPCEntitySource, NPCEntitySource,
    RecategorisedNPCSource, TalkHistory,
    TalkedNPCEntitySource, WarpAugmentedNPCSource, ScriptedPdaEntitySource,
)
from .health import (
    FaintCoordinator, HealthMemorySource, HealthTracker, ProductionHealthReader,
)
from .hotkeys import (
    BattleHPSummary,
    HeartGaugeSummary,
    HotkeyError,
    MoneySummary,
    PartySlotSummary,
    WindowsForegroundHotkey,
    WindowsForegroundProcess,
    parse_hotkey,
)
from .key_capture import LowLevelKeyCapture, MenuKeyPolicy
from .memory import MemoryError
from .message_render import MessageRenderer
from .messages import (
    FightCommonCatalog, LocalDataError, PocketMenuCatalog,
    RoomMessageCatalog, RoutedMessageCatalog,
)
from .menus import ProductionMenuReader
from .narrator import BattleNarrator
from .navigation_service import NavigationService
from .interaction_diagnostics import InteractionDiagnostics
from .line_of_sight import RoomLineOfSight
from .model_parts import NeckPositionResolver
from .bridge_connections import (
    BridgeConnectionEntitySource, derive_layout, parse_pier_enable_table,
)
from .interactables import (
    RoomScriptInteractableSource, load_records as load_interactable_records,
)
from .npc_shadow import NPCSourceShadowReader, SAMPLE_INTERVAL as NPC_SHADOW_INTERVAL
from .people_runtime import PeopleRuntimeSource
from .terrain_footsteps import (
    load_room_triangles, load_walk_model_triangles,
    resolve_blocked_path, resolve_step_paths,
)
from . import npc_beacons
from .npc_beacons import (
    GUIDE_SOUND_FILES, NPCInteractionContext,
    NPCMemorySource, NPCSoundReader,
    PASSIVE_BEACON_SOUND_FILES, SpatialWavePlayer, check_playable,
    resolve_guide_sound_dir,
    resolve_sound_dir,
)
from .party import PartyMemorySource
from .pda import PdaCatalog, PdaReader
from .party_action_menu import PartyActionMenuReader, stone_selection_labels
from .party_list_screen import PartyListScreenReader
from .party_summary_screen import PartySummaryScreenReader
from .phase1b_connection import PersistentDolphinConnection, UnsupportedProfile
from .phase1b_lifecycle import LifecycleController
from .phase1b_tasks import MalformedGSmsg, PersistentGSmsgTasks
from .profile import XD_US_REV0
from . import game_build
from .purify_chamber import PurifyChamberModel, PurifyChamberReader
from .resolver import LocalAbilityData, LocalMoveData, VerifiedResolver
from .settings import SettingsStore, build_categories
from .settings_menu import SettingsMenu
from .sound_library import SoundLibrary, build_cues
from .speech import (
    NVDASpeaker, SpeechCoordinator, SpeechError, SpeechEventClass,
)


def hotkey_value(value):
    try:
        parse_hotkey(value)
    except HotkeyError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc

    return value


def party_slot_hotkeys_value(value):
    """A comma-separated list of one chord per party slot.

    One argument rather than six, because the six are meaningless apart:
    the list has to stay the same length as the party, and validating that
    once here is what stops slot 5 silently having no key. Every chord is
    parsed with the same `parse_hotkey` every other hotkey uses, and
    duplicates are rejected -- a chord bound to two slots would answer for
    whichever one happened to be checked first."""
    chords = [part.strip() for part in str(value).split(",") if part.strip()]
    expected = len(XD_US_REV0.default_party_slot_hotkeys)
    if len(chords) != expected:
        raise argparse.ArgumentTypeError(
            f"expected {expected} comma-separated party slot chords, "
            f"got {len(chords)}")
    seen = set()
    for chord in chords:
        try:
            codes = parse_hotkey(chord)
        except HotkeyError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc
        if codes in seen:
            raise argparse.ArgumentTypeError(
                f"party slot chord {chord!r} is used twice")
        seen.add(codes)
    return tuple(chords)


def parser():
    value = argparse.ArgumentParser(
        description="Persistent read-only Pokémon XD battle narrator"
    )
    value.add_argument(
        "--dialogue-debug",
        action="store_true",
        help="log meaningful overworld dialogue state changes",
    )
    value.add_argument(
        "--terrain-footsteps",
        dest="terrain_footsteps",
        action="store_true",
        help=(
            "accessibility-only synthetic footstep cues, independent of the "
            "game's native sound. ON BY DEFAULT since 2026-08-10 at the "
            "project owner's request -- accepted only so existing launchers "
            "that pass it keep working; it is now a no-op"
        ),
    )
    value.add_argument(
        "--no-terrain-footsteps",
        dest="terrain_footsteps",
        action="store_false",
        help=(
            "disable the footstep cues. They are on by default: they were "
            "opt-in while the cadence and distance thresholds were being "
            "tuned live, and that tuning is done"
        ),
    )
    value.set_defaults(terrain_footsteps=True)
    value.add_argument(
        "--collision-feedback",
        action="store_true",
        help=(
            "experimental: blocked-forward-movement cue, gated on an "
            "UNVERIFIED movement-input read (see movement_input.py) -- "
            "kept fully separate from --terrain-footsteps and off by "
            "default; do not enable for live testing until that input "
            "source is confirmed"
        ),
    )
    value.add_argument(
        "--interaction-diagnostics",
        action="store_true",
        help=(
            "development only: log the full talk-eligibility state of the "
            "selected NPC, and score manual A presses marked with "
            "--interaction-mark-hotkey against the prediction. Read-only, "
            "never sends input, off by default"
        ),
    )
    value.add_argument(
        "--no-npc-shadow",
        dest="npc_shadow",
        action="store_false",
        help=(
            "disable the NPC source shadow comparison. On by default: it "
            "speaks nothing and publishes nothing, and logs whether the "
            "canonical NPC source would have agreed with the one currently "
            "running -- the evidence needed before the two can be swapped"
        ),
    )
    value.set_defaults(npc_shadow=True)
    value.add_argument(
        "--stop-after-loss",
        action="store_true",
        help="stop after a resolved battle-loss message",
    )
    value.add_argument(
        "--log",
        type=Path,
        default=Path(__file__).parents[1]
        / "logs"
        / "battle_narrator_phase1b.log",
    )
    value.add_argument(
        "--hp-summary-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_hp_summary_hotkey,
        help="foreground-only battle HP summary chord (default: ctrl+h)",
    )
    value.add_argument(
        "--heart-gauge-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_heart_gauge_hotkey,
        help=(
            "on-demand Shadow Pokemon Heart Gauge check, usable anywhere "
            "in the overworld (default: ctrl+s)"
        ),
    )
    value.add_argument(
        "--money-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_money_hotkey,
        help=(
            "on-demand Pokedollar balance check, usable anywhere in the "
            "overworld (default: ctrl+m)"
        ),
    )
    value.add_argument(
        "--party-slot-hotkeys",
        type=party_slot_hotkeys_value,
        default=XD_US_REV0.default_party_slot_hotkeys,
        help=(
            "comma-separated chords, one per party slot, each speaking that "
            "slot's name, level, HP, status, Heart Gauge, held item and "
            "ability (default: ctrl+1,ctrl+2,ctrl+3,ctrl+4,ctrl+5,ctrl+6)"
        ),
    )
    value.add_argument(
        "--entity-next-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_entity_next_hotkey,
        help="entity navigation: select next entity (default: ctrl+period)",
    )
    value.add_argument(
        "--entity-prev-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_entity_prev_hotkey,
        help="entity navigation: select previous entity (default: ctrl+comma)",
    )
    value.add_argument(
        "--entity-next-category-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_entity_next_category_hotkey,
        help="entity navigation: next category (default: ctrl+shift+period)",
    )
    value.add_argument(
        "--entity-prev-category-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_entity_prev_category_hotkey,
        help="entity navigation: previous category (default: ctrl+shift+comma)",
    )
    value.add_argument(
        "--entity-repeat-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_entity_repeat_hotkey,
        help="entity navigation: repeat current selection (default: ctrl+slash)",
    )
    value.add_argument(
        "--entity-auto-repeat-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_entity_auto_repeat_hotkey,
        help="entity navigation: toggle re-announcing the selection when "
             "you stop moving (default: ctrl+l)",
    )
    # `--entity-refresh-hotkey` was removed on 2026-08-16 along with the
    # action itself; see entity_nav.EntityNavigator's docstring. Not kept as
    # an accepted no-op: unlike `--terrain-footsteps`, no launcher passes it.
    value.add_argument(
        "--autowalk-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_autowalk_hotkey,
        help=(
            "toggle autowalk to the entity-nav selection; any movement "
            "input stops it (default: ctrl+shift+slash)"
        ),
    )
    value.add_argument(
        "--interaction-mark-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_interaction_mark_hotkey,
        help=(
            "development only, requires --interaction-diagnostics: mark the "
            "moment you press A so the log can score the talk-eligibility "
            "prediction against whether dialogue actually opened "
            "(default: ctrl+k)"
        ),
    )
    value.add_argument(
        "--audio-guide-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_audio_guide_hotkey,
        help=(
            "toggle a direct beacon on the entity-nav selection -- straight "
            "line, no routing (default: ctrl+g)"
        ),
    )
    value.add_argument(
        "--navigation-guide-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_navigation_guide_hotkey,
        help=(
            "toggle obstacle-aware routed navigation to the entity-nav "
            "selection (default: ctrl+n)"
        ),
    )
    value.add_argument(
        "--teleport-hotkey",
        type=hotkey_value,
        default=XD_US_REV0.default_teleport_hotkey,
        help="teleport to the entity-nav selection (default: ctrl+t)",
    )
    value.add_argument(
        "--no-settings-menu",
        dest="settings_menu",
        action="store_false",
        help=(
            "disable the F1 settings menu, including its keyboard hook. On "
            "by default. This is the escape hatch: the menu is the only "
            "part of the companion that takes keys away from Dolphin "
            "(F1 is Load State Slot 1 in a stock configuration), so there "
            "has to be a way to run without it"
        ),
    )
    value.set_defaults(settings_menu=True)
    return value


def hotkey_reference(args):
    """(label, chord) for the settings menu's read-only Hotkeys category.

    Built from the parsed arguments rather than from the profile defaults so
    it describes the keys THIS session is actually listening for, including
    any the player overrode on the command line. A reference list that can
    disagree with reality is worse than no list."""
    return (
        ("Open this menu", "f1"),
        ("Battle HP summary", args.hp_summary_hotkey),
        ("Heart Gauge check", args.heart_gauge_hotkey),
        ("Money check", args.money_hotkey),
        *(
            (f"Read party slot {index + 1}", chord)
            for index, chord in enumerate(args.party_slot_hotkeys)
        ),
        ("Next entity", args.entity_next_hotkey),
        ("Previous entity", args.entity_prev_hotkey),
        ("Next entity category", args.entity_next_category_hotkey),
        ("Previous entity category", args.entity_prev_category_hotkey),
        ("Repeat selection", args.entity_repeat_hotkey),
        ("Repeat on stop, on or off", args.entity_auto_repeat_hotkey),
        ("Beacon on selection", args.audio_guide_hotkey),
        ("Routed navigation guide", args.navigation_guide_hotkey),
        ("Autowalk to selection", args.autowalk_hotkey),
        ("Teleport to selection", args.teleport_hotkey),
    )


def build_sound_library(base, logger):
    """The listenable catalogue behind the settings menu's Sound library.

    Every path comes from the same constant the feature itself uses --
    `PASSIVE_BEACON_SOUND_FILES` for the ambient beacons,
    `GUIDE_SOUND_FILES` for the navigation cues, and terrain_footsteps'
    own path resolvers for the movement cues -- so the library cannot
    offer a sound nothing plays, or miss one that something does.

    The footstep entry is the FIRST clip of several: `TerrainTonePlayer`
    picks one at random per step and pitches it by terrain, so no single
    file is "the" footstep sound. The label says as much rather than
    implying the player will only ever hear this one.

    Returns None if the catalogue comes out empty, so the settings menu
    shows no heading at all rather than an empty one."""
    sound_dir = resolve_sound_dir(base)
    guide_dir = resolve_guide_sound_dir(base)
    asset_dir = base / "logs" / "terrain_footsteps" / "generated_tones"
    paths = {
        f"beacon.{category}": sound_dir / filename
        for category, filename in PASSIVE_BEACON_SOUND_FILES.items()
    }
    paths.update({
        f"guide.{name}": guide_dir / filename
        for name, filename in GUIDE_SOUND_FILES.items()
    })
    try:
        steps = resolve_step_paths(
            asset_dir, footstep_sounds_dir=sound_dir / "footsteps",
            logger=logger)
        paths["footstep"] = steps[0]
        paths["blocked"] = resolve_blocked_path(asset_dir)
    except (OSError, ValueError, wave.Error) as exc:
        # Movement cues are generated/converted on demand, so unlike the
        # rest they can fail on a read-only or full disk. That must cost
        # their two entries, not the whole library.
        logger.warning("SOUND LIBRARY movement cues unavailable: %s", exc)
    cues = build_cues(
        paths, logger,
        # Matches the trim the warp beacon actually plays at, so the
        # example sounds like the thing it is teaching.
        gains={"beacon.warp": npc_beacons.PASSIVE_BEACON_CATEGORY_GAIN.get(
            "warp", 1.0)},
    )
    if not cues:
        logger.warning("SOUND LIBRARY is empty; no sound files were usable")
        return None
    return SoundLibrary(cues, SpatialWavePlayer, logger)


def build_settings_store(args, base, logger, on_save_error=None):
    """Load the player's settings, then let this session's command line
    override two of them.

    The CLI flags are treated as a SESSION override and are deliberately not
    written back: `--no-terrain-footsteps` on one launcher shortcut should
    not silently rewrite a preference the player set in the menu. Whatever
    they change inside the menu afterwards is saved as normal."""
    store = SettingsStore(
        build_categories(
            hotkey_reference(args),
            sound_library=build_sound_library(base, logger),
        ),
        path=base / "companion_settings.json",
        logger=logger,
        on_save_error=on_save_error,
    ).load()
    if not args.terrain_footsteps:
        store.values["sounds.footsteps"] = False
    if args.collision_feedback:
        store.values["sounds.blocked_cue"] = True
    return store


GAME_WAIT_SECONDS = 120
"""How long to wait at startup for a game to be booted before giving up
and loading data unidentified. Generous on purpose: the alternative is
loading the wrong tables, and the narrator has nothing to do until a game
is running anyway."""


def wait_for_booted_game(backend, logger, speech=None,
                         timeout=GAME_WAIT_SECONDS, sleep=time.sleep):
    """Block until Dolphin has a game booted, or the timeout expires.

    Exists because the build fingerprint can only be taken from a running
    game, and the narrator is commonly started from a desktop shortcut
    before the disc is loaded. Without this the startup order silently
    decided which data got loaded: start first and it fell back to
    whatever tree was left over, which is how a vanilla tree came to be
    loaded against XG.

    Announced rather than silent -- a blind player given a frozen
    launcher has no way to tell waiting from hung."""
    announced = False
    waited = 0.0
    while waited <= timeout:
        try:
            backend.hook()
            if backend.is_hooked():
                header = backend.read_bytes(XD_US_REV0.mem1_start, 8)
                if header[:6] != b"\0" * 6:
                    return True
        except Exception as exc:
            logger.debug("WAITING for game: %s", exc)
        if not announced:
            announced = True
            logger.info("Waiting up to %ds for a game to be booted", timeout)
            if speech is not None:
                speech.emit(
                    SpeechEventClass.LIFECYCLE,
                    "Waiting for the game to start.", interrupt=False)
        sleep(1.0)
        waited += 1.0
    logger.warning(
        "No game booted after %ds; loading game data without identifying "
        "the build", timeout)
    return False


def resolve_data_root(base, backend, logger):
    """Pick the data tree describing the game that is actually running.

    The offline tables describe one disc. Loaded against another they do
    not fail loudly -- they disagree, and the move reader goes quiet
    rather than announce a wrong name. That happened twice in two days,
    in both directions, so the choice is made here instead of being left
    to the player to remember.

    Best-effort by design. Dolphin may not be running yet, and the
    lifecycle is built to tolerate that, so a fingerprint that cannot be
    taken is not an error: it falls back to whatever single tree exists,
    exactly as before this function existed. Being wrong is still caught
    downstream -- `menus.GameDataMismatch` says so out loud -- so the
    worst case here is the behaviour we already had, not a new one."""
    root = Path(base) / "_dialogue_extraction"
    fingerprint = None
    try:
        backend.hook()
        if backend.is_hooked():
            header = backend.read_bytes(XD_US_REV0.mem1_start, 8)
            if header[:6] != b"\0" * 6:
                fingerprint = game_build.fingerprint_from_memory(
                    backend.read_bytes)
    except Exception as exc:  # not running, not booted, not readable
        logger.debug("BUILD FINGERPRINT unavailable: %s", exc)

    if fingerprint:
        directory, stamp, reason = game_build.select(root, fingerprint)
        if directory is not None:
            logger.info("GAME DATA %s (%s)", directory.name, reason)
            return directory
        logger.warning("GAME DATA selection failed: %s", reason)
    else:
        logger.debug("GAME DATA chosen without a live fingerprint")

    stamped = [
        directory for directory in game_build.candidate_directories(root)
        if game_build.read_stamp(directory) is not None
    ]
    if len(stamped) == 1:
        logger.info("GAME DATA %s (only installed build)", stamped[0].name)
        return stamped[0]
    if (root / "raw" / "files" / "common.fsys").is_file():
        logger.info("GAME DATA %s (unstamped tree)", root)
        return root
    if stamped:
        logger.warning(
            "GAME DATA %s (first of %d installed builds; the running game "
            "was not identified)", stamped[0].name, len(stamped))
        return stamped[0]
    return root


def shared_or_local(data_root, base, *parts):
    """A data file from this build's tree, falling back to `shared/`.

    Most data is build-specific and must never be shared -- that is the
    entire point of per-build trees. A few files are neither generated by
    the bootstrap nor derivable from the disc (they came from a
    third-party disassembler in an earlier session), so a fresh tree
    cannot contain them and the feature they support would silently
    disappear on any build but the one they were made from.

    `shared/` is where such a file goes once it has been CHECKED to be the
    same in every build in hand -- not assumed. Gateon Port's
    Gateon Port script and collision data qualify: XG recompressed
    `M6_out.fsys` (1,467,912 of its 1,485,632 bytes differ) but every decoded
    entry inside it is byte-identical to vanilla's. Sharing those decoded
    files is not a compromise; they are the same data.

    The build's own tree still wins, so dropping a real per-build copy in
    later overrides the shared one without touching this code."""
    local = Path(data_root).joinpath(*parts)
    if local.exists():
        return local
    return Path(base) / "_dialogue_extraction" / "shared" / Path(*parts)


def run(argv=None, backend=dme, speech_backend=tolk):
    args = parser().parse_args(argv)
    base = Path(__file__).parents[1]
    logger = make_logger(args.log)
    speaker = NVDASpeaker(speech_backend)
    speech = SpeechCoordinator(speaker, logger)
    connection = PersistentDolphinConnection(backend, XD_US_REV0)
    code = 0
    # Bound before the try so the `finally` can always remove the keyboard
    # hook. Leaving a low-level hook installed after the process that owns
    # it has stopped draining is the one failure here with consequences
    # outside this program.
    key_capture = None
    try:
        logger.debug("Screen reader: %s", speaker.open())
        # Which data to load depends on which game is running, so this has
        # to happen after the screen reader is available (so the wait can
        # be announced) and before any table is opened.
        wait_for_booted_game(backend, logger, speech)
        data_root = resolve_data_root(base, backend, logger)
        catalog = FightCommonCatalog(data_root)
        pocket_message_catalog = PocketMenuCatalog(
            data_root / "raw" / "files" /
            "pocket_menu.fsys")
        # One room's own dialogue (the Name Rater). Optional on purpose:
        # this is a single screen's text, and losing it must not stop the
        # narrator from starting. It did exactly that once -- the file had
        # only ever been hand-extracted into one data tree, so every
        # generated tree lacked it and startup aborted with a message
        # about a missing .fsys that told the player nothing actionable.
        try:
            name_rater_message_catalog = RoomMessageCatalog(
                data_root / "rooms" / "files" /
                "M3_houseD_1F.fsys",
                "M3_houseD_1F",
            )
        except LocalDataError as exc:
            name_rater_message_catalog = None
            logger.warning(
                "NAME RATER dialogue unavailable, continuing without it: %s",
                exc)
        move_data = LocalMoveData(data_root, catalog)
        ability_data = LocalAbilityData(data_root)
        faint_coordinator = FaintCoordinator(speech, logger)
        interaction_context = NPCInteractionContext()
        scripted_speaker_names = ScriptedSpeakerNameTable(
            data_root / "raw" / "files" / "common.fsys"
        )
        item_database = ItemDatabase(
            data_root / "raw" / "files" / "common.fsys"
        )
        item_name_resolver = ItemNameResolver(item_database, scripted_speaker_names)
        item_description_table = ItemDescriptionTable(
            data_root / "raw" / "files" / "pocket_menu.fsys"
        )
        item_description_resolver = ItemDescriptionResolver(
            item_database, item_description_table)
        shop_message_table = ShopMessageTable(
            data_root / "raw" / "files" / "pocket_menu.fsys"
        )

        def dialogue_speaker_name():
            talk_history.mark(interaction_context.identity)
            # Prefer the direct, authoritative scripted-speaker read (see
            # profile.py's scripted_speaker_message_id) -- it also covers
            # ordinary free-roam NPC talk (peopleTalkMsg fires for both),
            # not just cutscenes. Falls back to the older proximity-based
            # guess (interaction_context.name) only if that read is
            # unavailable or the name hasn't been revealed yet.
            try:
                message_id = connection.memory.u16(
                    XD_US_REV0.scripted_speaker_message_id,
                    "scripted speaker name message id",
                )
            except MemoryError:
                message_id = None
            name = (
                scripted_speaker_names.resolve(message_id)
                if message_id is not None else None
            )
            return name or interaction_context.name
        room_codes = {
            int(key, 16): value
            for key, value in json.loads(
                (base / "assets" / "room_ids.json").read_text(encoding="utf-8")
            ).items()
        }
        def load_room_services():
            """Room -> service, DERIVED from each room's own script. The
            hand-written table had "Agate Village Day-Care" on the wrong
            house; this follows `Daycare::depositPkm` instead."""
            path = base / "assets" / "room_services.json"
            if not path.exists():
                logger.warning(
                    "ROOM SERVICES unavailable: %s is missing; run "
                    "build_room_service_table.py", path)
                return {}
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("ROOM SERVICES unavailable: %s", exc)
                return {}

        room_services = load_room_services()
        room_names = build_room_names(room_codes, room_services)
        common_fsys_path = data_root / "raw" / "files" / "common.fsys"
        flag_reader = GeneralFlagReader(
            connection.memory, load_general_flag_layout(common_fsys_path))
        # One shared history for the whole session: `dialogue_speaker_name`
        # marks an NPC as talked-to, and both entity-nav factories read it
        # back through TalkedNPCEntitySource. All three are deferred
        # closures, so defining it here (right after the flag_reader it
        # needs) is in scope for every one of them.
        talk_history = TalkHistory(flag_reader)
        warp_records = load_warp_records(common_fsys_path)
        elevator_records = load_elevator_records(common_fsys_path)
        door_records = load_door_records(common_fsys_path)
        pc_records = load_pc_records(common_fsys_path)
        text_records = load_text_records(common_fsys_path)
        warp_collision_dir = data_root / "collision"
        # ONE navigation service, shared by the routed guide and by every
        # region-backed entity source. That sharing is the point: the
        # component entity navigation SPEAKS must be the component the
        # route is TARGETING, and they can only agree if both ask the same
        # graph. See `region_target.RegionTargetSelector`.
        # The enable state is read from the engine, never assumed: rooms
        # disable collision objects through their own scripts (Agate's Relic
        # Stone cave doorway, Gateon Port's piers), and treating those objects
        # as present rebuilds walls the game has switched off. See
        # `collision_object_enable.py`.
        collision_enable_state = LiveObjectEnableState(
            connection.memory, logger, time.monotonic,
            address=XD_US_REV0.gscolsys2)
        # Which regions in each room MOVE THE PLAYER somewhere else, from
        # the same authoritative `common.rel` records the "Exits" category
        # is built from -- so the regions routing avoids and the regions the
        # player can select are the same set by construction. Routing
        # crosses everything else freely; see `NavigationService.
        # room_change_regions` for the Gateon Port parts-shop case that
        # made this necessary.
        room_change_regions = {}
        for record in (*warp_records, *door_records, *elevator_records):
            room_change_regions.setdefault(
                record.room_id, set()).add(record.region_index)
        room_change_regions = {
            room_id: frozenset(indices)
            for room_id, indices in room_change_regions.items()
        }
        navigation_service = NavigationService(
            warp_collision_dir, room_codes, logger,
            enable_state=collision_enable_state,
            room_change_regions=lambda floor_id: room_change_regions.get(
                floor_id, frozenset()))

        def warp_source(pose_source):
            return AuthoritativeWarpEntitySource(
                connection.memory, XD_US_REV0, pose_source, warp_records,
                warp_collision_dir, room_codes, room_names,
                reachability=navigation_service.region_component_cost,
            )

        def elevator_source(pose_source):
            return AuthoritativeElevatorEntitySource(
                connection.memory, XD_US_REV0, pose_source, elevator_records,
                warp_collision_dir, room_codes, room_names,
                reachability=navigation_service.region_component_cost,
            )

        def door_source(pose_source):
            # `warp_records` is what lets the source tell an entrance (a
            # door sharing its region with a warp) from a plain interior
            # door; the former is published silent. See the class docstring.
            return AuthoritativeDoorEntitySource(
                connection.memory, XD_US_REV0, pose_source, door_records,
                warp_collision_dir, room_codes, room_names,
                warp_records=warp_records,
                reachability=navigation_service.region_component_cost,
            )

        def pc_source(pose_source):
            return AuthoritativePCEntitySource(
                connection.memory, XD_US_REV0, pose_source, pc_records,
                warp_collision_dir, room_codes, room_names,
                reachability=navigation_service.region_component_cost,
            )

        def text_source(pose_source):
            return AuthoritativeTextEntitySource(
                connection.memory, XD_US_REV0, pose_source, text_records,
                warp_collision_dir, room_codes, room_names,
                reachability=navigation_service.region_component_cost,
            )

        # `NPCRoleResolver` is NOT constructed, 2026-08-18. It is the
        # principled half of role detection -- talk script ->
        # `Dialogs::openPokemartMenu` / `Character::101`, derived from the
        # game's own room scripts by build_room_service_table.py -- and it
        # is the obvious starting point when this is picked back up. But
        # the project owner asked for no clerk or nurse titles at all until
        # detection is settled, and passing it here is what puts a title in
        # front of a player (`entity_sources` uses the resolved role as the
        # entity's LABEL). Left unwired rather than deleted: the module,
        # its asset and its tests all remain.

        def load_bridge_layout():
            """Decks, segments and the flag->enable table for Gateon Port's
            piers, all derived from the room's own script and `.ccd`.

            Loaded once (static geometry, permanently cacheable per
            ENTITY_STATE_AND_BEACON_POLICY.md); the ALIGNMENT is read live
            on every query. A missing file disables the category rather
            than degrading it -- an unavailable bridge list is silence, and
            silence is the correct failure here."""
            room_id = next(
                (code for code, name in room_codes.items() if name == "M6_out"),
                None)
            script = shared_or_local(data_root, base, "rooms", "M6_out.txt")
            collision = shared_or_local(
                data_root, base, "collision", "M6_out.ccd")
            if room_id is None or not script.exists() or not collision.exists():
                logger.warning(
                    "BRIDGE CONNECTIONS disabled: missing M6_out room id, "
                    "script or collision data")
                return None
            try:
                table = parse_pier_enable_table(
                    script.read_text(encoding="utf-8", errors="replace"))
                if not table:
                    raise ValueError("pier_def produced no enable table")
                data = collision.read_bytes()
                decks, segments = derive_layout(
                    parse_walk_model_triangles(data),
                    parse_environment_triangles(data),
                    {entry for row in table.values() for entry in row},
                )
                if not decks or not segments:
                    raise ValueError("no pier decks or segments derived")
            except Exception as exc:
                logger.warning("BRIDGE CONNECTIONS disabled: %s", exc)
                return None
            logger.info(
                "BRIDGE CONNECTIONS ready: %d alignments, %d decks, "
                "%d segments in room 0x%02X",
                len(table), len(decks), len(segments), room_id)
            return room_id, table, decks, segments

        bridge_layout = load_bridge_layout()

        def bridge_source(pose_source):
            if bridge_layout is None:
                return None
            room_id, table, decks, segments = bridge_layout
            source = BridgeConnectionEntitySource(
                connection.memory, XD_US_REV0, flag_reader, pose_source,
                room_id, decks, segments, logger=logger)
            source.enable_table = table
            return source

        def load_interactables():
            """The generated room-script object table. A missing asset
            disables both categories rather than degrading them."""
            path = base / "assets" / "interactables.json"
            if not path.exists():
                logger.warning(
                    "INTERACTABLES disabled: %s is missing; run "
                    "build_interactable_table.py", path)
                return ()
            try:
                records = load_interactable_records(path)
            except Exception as exc:
                logger.warning("INTERACTABLES disabled: %s", exc)
                return ()
            publishable = [r for r in records if r.publishable]
            logger.info(
                "INTERACTABLES ready: %d records, %d publishable "
                "(%d hazards)", len(records), len(publishable),
                sum(1 for r in publishable if r.is_hazard))
            return records

        interactable_records = load_interactables()

        def interactable_source(pose_source, category):
            if not interactable_records:
                return None
            return RoomScriptInteractableSource(
                connection.memory, XD_US_REV0, pose_source,
                interactable_records, warp_collision_dir, room_codes,
                category=category, logger=logger)

        line_of_sight = RoomLineOfSight(
            warp_collision_dir, room_codes, load_room_triangles,
            load_walk_model_triangles, logger)

        entity_nav_parts = {}
        """Handles the entity-nav factory publishes for the interaction
        diagnostic, which needs the same runtime/pose objects the navigator
        is actually using rather than a second set with its own caches."""

        def build_overworld_sources():
            """The one definition of the overworld category -> source map.

            Previously duplicated verbatim between `entity_nav_factory` and
            `overworld_entity_sources`, ~45 lines apart, so every fix had to
            be applied twice or they silently diverged (audit defect X1).
            Still built fresh per caller, so no two readers share a cache."""
            entity_names = load_entity_names(
                data_root / "raw" / "files" / "common.fsys"
            )
            pose_source = NPCMemorySource(connection.memory, XD_US_REV0)
            runtime = PeopleRuntimeSource(connection.memory, XD_US_REV0)
            # ------------------------------------------------------------
            # REVERTED TO THE PRE-PHASE-2 NPC SOURCE, 2026-08-06, at the
            # project owner's request: they were mid-dungeon and needed the
            # NPC category back immediately.
            #
            # `LiveNPCEntitySource` (people_runtime + talk_predicate +
            # model_parts + npc_roles) is complete and passes 1106 tests,
            # but it had NOT been live-validated even once, and it is
            # strictly MORE selective than this source -- it publishes only
            # NPCs with a live actor that survives eight validity rules and
            # the full talk predicate. Any single wrong offset in that chain
            # empties the category, which is exactly the failure the owner
            # hit. A stricter unvalidated source is the wrong thing to have
            # running while someone is trying to finish a dungeon.
            #
            # Nothing is deleted: every Phase 2 module and test stays in the
            # tree, and the diagnostic below still observes this source. To
            # re-enable after live validation, swap `npc_source` back to
            # LiveNPCEntitySource and restore the metadata-based role split
            # (git history has both).
            # ------------------------------------------------------------
            npc_source = NPCEntitySource(
                connection.memory, XD_US_REV0, entity_names)
            # ROLE LABELLING REMOVED 2026-08-18, at the project owner's
            # request: "make the clerks and nurses npc's and remove their
            # titles as clerks and nurses until you are able to find out
            # how to detect a clerk and a nurse."
            #
            # What stood here was
            #   role_rooms = {0x85: "Pokemon Center nurse",
            #                 0x86: "Pokemon Mart clerk"}
            # matched against `entity.identity[1]`, the FLOOR ID -- the
            # exact guess `npc_roles.py`'s own docstring was written to
            # replace, and which `npc_beacons.py` separately records as one
            # that "both mislabels every other NPC in those two rooms and
            # misses every other Pokemon Center". It survived both of those
            # write-ups and was still live. Every NPC standing anywhere in
            # Agate's Mart was announced as a clerk.
            #
            # Every NPC is now simply an NPC, named or lettered like any
            # other. Nothing that identifies a role has been deleted --
            # `npc_roles.py`, `assets/npc_roles.json` and the talk-script
            # derivation behind them are untouched and still tested -- it
            # is only no longer used to put a title in front of a player.
            # A confident wrong title is worse than none: it sends someone
            # across a room to buy from a bystander.
            ordinary_npcs = TalkedNPCEntitySource(npc_source, talk_history)
            pcs = FilteredEntitySource(
                pc_source(pose_source), lambda entity: True,
                category="interact")
            # Two hardcodes RETIRED 2026-08-10, both superseded by the
            # Phase 4 room-script object source:
            #
            #   healing = npc_beacons.HEALING {0x8A: <one coordinate>}
            #       INTERACTABLE_OBJECTS.md proved room 0x8A is
            #       `M5_apart_1F`, whose only interaction record is
            #       `check_mana_bed` -- a BED, not a healing station. Real
            #       healing machines now come from `Character::101`.
            #
            #   relic = "every sign in room 0x87 is the Relic Stone"
            #       The Relic Stone is `check_shrine`, identified by
            #       `Player::countPurfiedPkm`, and published with its own
            #       region. The room-id guess is no longer needed.
            #
            # Exits absorbs elevators and warps; Interactables absorbs
            # signs. Doors and Gateon's live bridge connections are their
            # own cycling categories.
            # `Entity.category` is deliberately UNCHANGED -- the beacon
            # sounds, `interaction_announcer`'s verbs and
            # `interaction_ready`'s walk-into set all key on it, so
            # regrouping the CYCLE must not rewrite what each entity IS.
            exits = [elevator_source(pose_source), warp_source(pose_source)]
            bridge = bridge_source(pose_source)
            interactables = [pcs, text_source(pose_source)]
            objects = interactable_source(pose_source, "interact")
            if objects is not None:
                interactables.append(objects)
            sources = {
                "npc": CombinedEntitySource(
                    ordinary_npcs,
                    GlobalCompanionEntitySource(pose_source, runtime)),
                # `runtime` supplies the live pickup actors: position,
                # display and the talk-flag bit the engine sets on a
                # collected box. Flags answer collected/spawned even
                # before those actors exist.
                "item": CombinedEntitySource(
                    LiveTreasureEntitySource(
                        connection.memory, XD_US_REV0, flag_reader,
                        runtime=runtime, logger=logger),
                    ScriptedPdaEntitySource(
                        connection.memory, XD_US_REV0, flag_reader)),
                "door": door_source(pose_source),
                "interact": CombinedEntitySource(*interactables),
                "exit": CombinedEntitySource(*exits),
            }
            if bridge is not None:
                sources["bridge"] = bridge
            hazards = interactable_source(pose_source, "hazard")
            if hazards is not None:
                sources["hazard"] = hazards
            return sources, npc_source, pose_source, runtime

        def tasks_factory():
            return PersistentGSmsgTasks(connection.memory, XD_US_REV0)

        def menu_factory():
            title_messages = json.loads(
                (data_root / "dol_strings.json")
                .read_text(encoding="utf-8")
            )
            title_messages = {
                int(key): value for key, value in title_messages.items()
            }
            title_messages.setdefault(
                152, "Checking the Memory Card in Slot A."
            )
            player_name_provider = DialogueMemorySource(
                connection.memory, XD_US_REV0, logger).player_name
            return ProductionMenuReader(
                connection.memory, XD_US_REV0, move_data, speech, logger,
                title_messages=title_messages,
                shop_messages=shop_message_table,
                item_name_resolver=item_name_resolver,
                party_source=PartyMemorySource(
                    connection.memory, XD_US_REV0, move_data, ability_data),
                player_name_provider=player_name_provider,
                message_renderer=MessageRenderer(
                    connection.memory, XD_US_REV0,
                    RuntimeMessageCatalog(connection.memory, XD_US_REV0),
                    player_name_provider),
            )

        def narrator_factory(tasks):
            identity = BattleIdentityResolver(connection.memory, XD_US_REV0)
            slot_tracker = BattlefieldSlotTracker(
                identity, XD_US_REV0, logger)
            resolver = VerifiedResolver(
                connection.memory, XD_US_REV0, catalog, move_data,
                identity=identity, slot_tracker=slot_tracker,
            )
            return BattleNarrator(
                connection,
                tasks,
                catalog,
                resolver,
                speech,
                logger,
                stop_after_loss=args.stop_after_loss,
                faint_coordinator=faint_coordinator,
                slot_tracker=slot_tracker,
                labeller=IdentityLabeller(),
                # Battle messages now render from the game's own templates
                # through the same MessageRenderer the progress-notification
                # reader uses. One renderer, one dispatch table.
                renderer=MessageRenderer(
                    connection.memory, XD_US_REV0,
                    RuntimeMessageCatalog(connection.memory, XD_US_REV0),
                    DialogueMemorySource(
                        connection.memory, XD_US_REV0, logger).player_name),
                supplemental_catalog=RoutedMessageCatalog((
                    (pocket_message_catalog, lambda: (
                        BagMenuModel(
                            connection.memory, XD_US_REV0,
                            HeroItemArraySource(connection.memory, XD_US_REV0),
                        )._find_window() is not None
                    )),
                    # These IDs are owned by this room archive and are
                    # invoked only by its field script. Rendering them here
                    # removes the delayed generic-dialogue fallback.
                ) + ((
                    (name_rater_message_catalog, None),
                ) if name_rater_message_catalog is not None else ())),
                # Item-use text is owned by pocket_menu only while the Bag
                # remains in the window stack. This prevents shop text from
                # racing the dedicated shop reader, without ID allowlists.
                supplemental_active=None,
            )

        def health_factory():
            source = HealthMemorySource(connection.memory, XD_US_REV0)
            tracker = HealthTracker(source, XD_US_REV0, logger)
            return ProductionHealthReader(
                tracker, speech, logger, faint_coordinator)

        def summary_factory():
            source = HealthMemorySource(connection.memory, XD_US_REV0)
            hotkey = WindowsForegroundHotkey(args.hp_summary_hotkey)
            return BattleHPSummary(
                source, XD_US_REV0, hotkey, speech, logger
            )

        def battle_start_factory():
            return BattleStartAnnouncer(
                BattleIdentityResolver(connection.memory, XD_US_REV0),
                OpponentPartySource(connection.memory, XD_US_REV0, logger),
                XD_US_REV0, speech, logger)

        def party_summary_factory():
            source = PartyMemorySource(
                connection.memory, XD_US_REV0, move_data, ability_data)
            return PartySummaryScreenReader(
                connection.memory, XD_US_REV0, source, speech, logger)

        def heart_gauge_summary_factory():
            source = PartyMemorySource(
                connection.memory, XD_US_REV0, move_data, ability_data)
            hotkey = WindowsForegroundHotkey(args.heart_gauge_hotkey)
            return HeartGaugeSummary(source, hotkey, speech, logger)

        def money_summary_factory():
            hotkey = WindowsForegroundHotkey(args.money_hotkey)
            return MoneySummary(
                connection.memory, XD_US_REV0, hotkey, speech, logger)

        def party_slot_summary_factory():
            source = PartyMemorySource(
                connection.memory, XD_US_REV0, move_data, ability_data)
            hotkeys = {
                index: WindowsForegroundHotkey(chord)
                for index, chord in enumerate(args.party_slot_hotkeys)
            }
            return PartySlotSummary(
                source, hotkeys, speech, logger,
                item_names=item_name_resolver)

        def party_action_menu_factory():
            return PartyActionMenuReader(
                connection.memory, XD_US_REV0, speech, logger)

        def party_item_action_menu_factory():
            return PartyActionMenuReader(
                connection.memory, XD_US_REV0, speech, logger,
                menu_id=XD_US_REV0.party_item_action_menu_id,
                labels=XD_US_REV0.party_item_action_labels)

        def bag_category_factory():
            # No longer wired into LifecycleController below -- superseded
            # by bag_menu_factory's BagMenuReader, which reads this exact
            # same window+cursor signal and already announces the
            # category name as part of its own, richer utterance
            # ("<Category>. <Item name>. Quantity <N>."). Wiring both
            # would announce the category twice on every tab change.
            # Left defined (unused) rather than deleted in case a future
            # screen wants the plain category-only announcement on its
            # own.
            return PartyActionMenuReader(
                connection.memory, XD_US_REV0, speech, logger,
                menu_id=XD_US_REV0.bag_menu_id,
                labels=XD_US_REV0.bag_category_labels,
                index_offset=XD_US_REV0.bag_category_index_offset)

        def pause_menu_factory():
            return PartyActionMenuReader(
                connection.memory, XD_US_REV0, speech, logger,
                menu_id=XD_US_REV0.pause_menu_id,
                labels=XD_US_REV0.pause_menu_labels,
                entry_map=XD_US_REV0.pause_menu_entry_map,
                entry_stride=XD_US_REV0.pause_menu_entry_stride)

        def stone_selection_menu_factory():
            try:
                labels = stone_selection_labels(
                    connection.memory, XD_US_REV0, item_name_resolver,
                    scripted_speaker_names, ability_data)
            except (MemoryError, ValueError) as exc:
                raise LocalDataError(
                    f"Could not resolve evolution choices: {exc}") from exc
            return PartyActionMenuReader(
                connection.memory, XD_US_REV0, speech, logger,
                menu_id=XD_US_REV0.stone_selection_menu_id,
                labels=labels)

        def bag_menu_factory():
            item_source = HeroItemArraySource(connection.memory, XD_US_REV0)
            model = BagMenuModel(connection.memory, XD_US_REV0, item_source)
            return BagMenuReader(
                connection.memory, XD_US_REV0, model, item_name_resolver,
                speech, logger, description_resolver=item_description_resolver)

        def shop_buy_menu_factory():
            model = ShopBuyMenuModel(connection.memory, XD_US_REV0)
            return ShopBuyMenuReader(
                connection.memory, XD_US_REV0, model, item_database,
                item_name_resolver, speech, logger)

        def shop_buy_quantity_factory():
            buy_model = ShopBuyMenuModel(connection.memory, XD_US_REV0)
            model = ShopBuyQuantityModel(
                connection.memory, XD_US_REV0, buy_model)
            return ShopBuyQuantityReader(
                connection.memory, XD_US_REV0, model, item_database,
                item_name_resolver, speech, logger)

        def shop_notification_factory():
            model = ShopNotificationModel(connection.memory, XD_US_REV0)
            return ShopNotificationReader(
                connection.memory, XD_US_REV0, model, shop_message_table,
                speech, logger)

        def pc_menu_factory():
            source = PartyMemorySource(
                connection.memory, XD_US_REV0, move_data, ability_data)
            map_catalog = WorldMapCatalog(
                data_root / "worldmap" / "files" / "worldmap.fsys")
            map_reader = WorldMapReader(
                connection.memory, map_catalog, speech, logger)
            return PCMenuReader(
                connection.memory, XD_US_REV0, speech, logger, source, map_reader)

        def purify_chamber_factory():
            model = PurifyChamberModel(connection.memory, XD_US_REV0)
            return PurifyChamberReader(
                connection.memory, XD_US_REV0, model,
                RuntimeMessageCatalog(connection.memory, XD_US_REV0),
                speech, logger)

        def pda_factory():
            catalog = PdaCatalog(
                data_root / "pda" / "files"
                / "pda_menu.fsys"
            )
            return PdaReader(
                connection.memory, XD_US_REV0, catalog, speech, logger,
                flag_reader=flag_reader,
                runtime_catalog=RuntimeMessageCatalog(
                    connection.memory, XD_US_REV0),
            )

        def party_list_factory():
            source = PartyMemorySource(
                connection.memory, XD_US_REV0, move_data, ability_data)
            return PartyListScreenReader(
                connection.memory, XD_US_REV0, source, speech, logger)

        def dialogue_factory():
            source = DialogueMemorySource(
                connection.memory, XD_US_REV0, logger)
            return DialogueReader(
                source, speech, logger, debug=args.dialogue_debug,
                speaker_name_provider=dialogue_speaker_name,
                message_renderer=MessageRenderer(
                    connection.memory, XD_US_REV0,
                    RuntimeMessageCatalog(connection.memory, XD_US_REV0),
                    player_name_provider=source.player_name))
        def npc_sound_factory():
            """Passive ambient beacons for the categories the project owner
            asked for: NPCs, Poke Marts, items, doors, warps, and -- since
            2026-08-10, when `sounds/elevators.wav` was added -- elevators.

            Each gets its own named sound from the project's `sounds/`
            directory, and all of them play at a quarter of the navigation
            beacon's volume (npc_beacons.PASSIVE_BEACON_GAIN_SCALE) so they
            never mask the beacon the player is actively steering by.

            `beacon_categories` restricts the stream to exactly the
            categories with a sound of their own. The source also carries
            "healing" entries, which have none; without the restriction
            they would fall back to the generic NPC tone and cue the player
            toward the wrong kind of thing."""
            sound_dir = resolve_sound_dir(base)
            category_sound_paths = {
                category: sound_dir / filename
                for category, filename in PASSIVE_BEACON_SOUND_FILES.items()
            }
            # Check the files are USABLE, not merely present. An existence
            # check passed happily and then the narrator died minutes into
            # play, from inside the poll loop, the first time one of these
            # categories came into range -- the sounds are 24-bit and the
            # player only read 16-bit. Failing here names the file and the
            # reason before anything starts.
            unusable = []
            for path in sorted(category_sound_paths.values()):
                try:
                    check_playable(path)
                except FileNotFoundError:
                    unusable.append(f"{path.name}: missing")
                except (ValueError, wave.Error) as exc:
                    unusable.append(str(exc))
            if unusable:
                raise LocalDataError(
                    f"Passive beacon sounds in {sound_dir} cannot be played: "
                    + "; ".join(unusable))
            npc_memory_source = NPCMemorySource(connection.memory, XD_US_REV0)
            # Doors, warps and elevators are not in the NPC stream at all,
            # so they are APPENDED. Mart clerks already are ordinary NPCs in
            # it, so they are RE-LABELLED in place -- appending would beacon
            # the same character twice from one spot. Items come from the
            # live treasure source: NPCMemorySource's own curated ITEMS
            # table is empty, so relying on it would mean no item beacons
            # at all.
            augmented_source = RecategorisedNPCSource(
                WarpAugmentedNPCSource(
                    WarpAugmentedNPCSource(
                        WarpAugmentedNPCSource(
                            WarpAugmentedNPCSource(
                                npc_memory_source,
                                warp_source(npc_memory_source)),
                            door_source(npc_memory_source), category="door"),
                        elevator_source(npc_memory_source),
                        category="elevator"),
                    LiveTreasureEntitySource(
                        connection.memory, XD_US_REV0, flag_reader,
                        runtime=PeopleRuntimeSource(
                            connection.memory, XD_US_REV0),
                        logger=logger,
                        # Names key items lying on the floor, and only
                        # those. Reuses the resolver the bag already builds
                        # rather than opening the item tables a second time.
                        key_item_name=item_name_resolver.resolve_key_item_name,
                        on_loose_appeared=lambda state: speech.emit(
                            SpeechEventClass.WARNING,
                            f"{state.label} dropped on the floor.",
                            interrupt=False)),
                    category="item"),
                # POKE MART BEACON DISABLED 2026-08-18, same request and
                # same reason as the role titles above. The predicate was
                # `npc.floor_id in XD_US_REV0.pokemart_room_ids` -- a
                # room-id guess again, so every NPC standing in a Mart
                # sounded like the clerk, and a Mart in a room not on the
                # list sounded like nobody.
                #
                # `lambda npc: False` rather than removing the wrapper:
                # this is the seam the talk-script version plugs into, one
                # line, once detection is settled --
                #   role_resolver.resolve(npc.floor_id, npc.talk_id)
                #       == "Pokemon Mart clerk"
                # and `npc.talk_id` is already `floor_character +0x14`, the
                # field `floorCharacterBiosGetTalkSctID` reads.
                lambda npc: False,
                "pokemart")
            return NPCSoundReader(
                augmented_source,
                [sound_dir / PASSIVE_BEACON_SOUND_FILES["npc"]],
                SpatialWavePlayer(),
                logger,
                max_distance=XD_US_REV0.npc_sound_max_distance,
                speech=speech,
                entity_names=load_entity_names(
                    data_root / "raw" / "files"
                    / "common.fsys"),
                interaction_context=interaction_context,
                foreground_active=WindowsForegroundProcess().is_active,
                category_sound_paths=category_sound_paths,
                beacon_categories=PASSIVE_BEACON_SOUND_FILES.keys(),
                room_names=room_names,
            )

        def entity_nav_factory():
            sources, npc_source, pose_source, runtime = build_overworld_sources()
            entity_nav_parts["npc_source"] = npc_source
            entity_nav_parts["pose_source"] = pose_source
            entity_nav_parts["runtime"] = runtime
            hotkeys = {
                "next": WindowsForegroundHotkey(args.entity_next_hotkey),
                "prev": WindowsForegroundHotkey(args.entity_prev_hotkey),
                "next_category": WindowsForegroundHotkey(
                    args.entity_next_category_hotkey
                ),
                "prev_category": WindowsForegroundHotkey(
                    args.entity_prev_category_hotkey
                ),
                "repeat": WindowsForegroundHotkey(args.entity_repeat_hotkey),
                "auto_repeat": WindowsForegroundHotkey(
                    args.entity_auto_repeat_hotkey
                ),
            }
            navigator = EntityNavigator(
                connection.memory, XD_US_REV0, sources, hotkeys, speech, logger,
            )
            entity_nav_parts["navigator"] = navigator
            return navigator

        def overworld_entity_sources():
            return build_overworld_sources()[0]

        def interaction_announcer_factory():
            return InteractionAnnouncer(
                connection.memory, XD_US_REV0, overworld_entity_sources(),
                speech, logger)

        def choice_menu_factory():
            # menus.py narrates the generic yes/no overlay (its own menu_id
            # 53 is stable, unlike the engine-allocated ids this widget
            # usually gets) from typed-in labels, so it is excluded here to
            # avoid two readers speaking the same prompt.
            return ChoiceMenuReader(
                connection.memory, XD_US_REV0,
                RuntimeMessageCatalog(connection.memory, XD_US_REV0),
                speech, logger,
                ignored_menu_ids=(XD_US_REV0.new_game_confirmation_menu_id,))

        def interaction_ready_factory():
            return InteractionReadyReader(
                connection.memory, XD_US_REV0, overworld_entity_sources(),
                speech, logger)

        controller = None

        def room_change_factory():
            # Uses `room_names` -- the same player-facing names entity-nav
            # already speaks for warps/doors/elevators -- so a door
            # announced as "Mt. Battle Pokemon Center, 1st floor" leads to a
            # room that calls itself exactly that. See room_announcer.py for
            # why this no longer lives inside the (muted) beacon reader.
            # The title line names whichever game is running, derived
            # from the abilities table's shape. Passed as a callable so it
            # is read on the title screen itself, not at construction --
            # the reader is built before a game is necessarily booted.
            def title_line():
                reader = getattr(controller, "menu_reader", None)
                if reader is None:
                    return None
                try:
                    return reader.title_label()
                except Exception as problem:
                    logger.debug("TITLE line unavailable: %s", problem)
                    return None

            return RoomChangeReader(
                NPCMemorySource(connection.memory, XD_US_REV0),
                room_names, speech, logger, title_provider=title_line)

        def audio_guide_factory(entity_nav_reader):
            sound_dir = resolve_guide_sound_dir(base)
            # ctrl+g -- a plain beacon on the entity itself. No
            # NavigationService at all: nothing to route, so nothing that
            # can mis-route.
            beacon = AudioGuideReader(
                entity_nav_reader, SpatialWavePlayer(),
                sound_dir / GUIDE_SOUND_FILES["beacon"],
                WindowsForegroundHotkey(args.audio_guide_hotkey),
                speech, logger, None,
                NPCMemorySource(connection.memory, XD_US_REV0),
                max_distance=XD_US_REV0.audio_guide_max_distance,
                arrival_distance=XD_US_REV0.audio_guide_arrival_distance,
                name="Beacon",
            )
            # ctrl+n -- the obstacle-aware routed guide, with its own
            # sound so the two modes are distinguishable by ear alone.
            navigation = AudioGuideReader(
                entity_nav_reader, SpatialWavePlayer(),
                sound_dir / GUIDE_SOUND_FILES["navigation"],
                WindowsForegroundHotkey(args.navigation_guide_hotkey),
                speech, logger,
                navigation_service,
                NPCMemorySource(connection.memory, XD_US_REV0),
                max_distance=XD_US_REV0.audio_guide_max_distance,
                arrival_distance=XD_US_REV0.audio_guide_arrival_distance,
                waypoint_sound_path=sound_dir / GUIDE_SOUND_FILES["waypoint"],
                name="Navigation",
            )
            return GuideModes(beacon, navigation)

        def autowalk_factory(entity_nav_reader):
            # Its own NavigationService, not the one the ctrl+n guide holds:
            # a service owns exactly one active route, so sharing would mean
            # each feature silently retargeted and cleared the other's. See
            # autowalk.py's module docstring.
            autowalk_navigation = NavigationService(
                warp_collision_dir, room_codes, logger,
                enable_state=collision_enable_state,
                room_change_regions=lambda floor_id: room_change_regions.get(
                    floor_id, frozenset()))
            pose_source = NPCMemorySource(connection.memory, XD_US_REV0)
            return AutowalkReader(
                entity_nav_reader,
                HeroStickOverride(connection.memory, XD_US_REV0, logger),
                WindowsForegroundHotkey(args.autowalk_hotkey),
                speech, logger, autowalk_navigation, pose_source,
                GSinputMovementSource(connection.memory),
                arrival_distance=XD_US_REV0.default_autowalk_arrival_distance,
                full_deflection=XD_US_REV0.hero_move_stick_full_deflection,
            )

        def teleport_factory(entity_nav_reader):
            hotkey = WindowsForegroundHotkey(args.teleport_hotkey)
            npc_source_for_teleport = NPCMemorySource(connection.memory, XD_US_REV0)
            return TeleportReader(
                connection.memory, XD_US_REV0, npc_source_for_teleport,
                entity_nav_reader, hotkey, speech, logger,
            )

        terrain_tone_player = TerrainTonePlayer(
            SpatialWavePlayer(),
            base / "logs" / "terrain_footsteps" / "generated_tones",
            footstep_sounds_dir=resolve_sound_dir(base) / "footsteps",
            logger=logger,
        )
        # Stated once, at startup, whichever way it went. A player who
        # reports "the beacons work but I get no footsteps" can then be
        # answered from the log instead of from guesswork -- the fallback
        # click is quiet enough to be heard as nothing at all.
        logger.info(
            "TERRAIN FOOTSTEPS using %s",
            "the recorded footsteps"
            if terrain_tone_player.using_real_footsteps
            else "the SYNTHESIZED CLICK (no usable recordings found)")

        def terrain_footstep_factory():
            pose_source = NPCMemorySource(connection.memory, XD_US_REV0)
            return TerrainFootstepReader(
                connection.memory, XD_US_REV0, pose_source,
                warp_collision_dir, room_codes, terrain_tone_player, logger,
            )

        def blocked_movement_factory():
            pose_source = NPCMemorySource(connection.memory, XD_US_REV0)
            movement_input_source = GSinputMovementSource(connection.memory)
            return BlockedMovementReader(
                connection.memory, XD_US_REV0, pose_source,
                movement_input_source, warp_collision_dir, room_codes,
                terrain_tone_player, logger,
            )

        def interaction_diagnostics_factory():
            """Observes the navigator that is actually running -- the same
            runtime/pose objects, not a second set with their own caches --
            so what it logs is what the player heard, not a re-derivation."""
            navigator = entity_nav_parts.get("navigator")
            npc_source = entity_nav_parts.get("npc_source")
            pose_source = entity_nav_parts.get("pose_source")
            runtime = entity_nav_parts.get("runtime")
            if npc_source is None or navigator is None:
                logger.warning(
                    "INTERACTION DIAG disabled: entity navigation is not "
                    "available to observe")
                return None

            def selection():
                state = navigator.state
                if state.category_key != "npc":
                    return None
                return state.selected_identity

            def selection_label():
                identity = selection()
                if identity is None:
                    return None
                for entity in npc_source.entities():
                    if entity.identity == identity:
                        return entity.label
                return None

            reader = InteractionDiagnostics(
                connection.memory, XD_US_REV0, runtime,
                NeckPositionResolver(connection.memory, XD_US_REV0),
                pose_source, selection,
                WindowsForegroundHotkey(args.interaction_mark_hotkey),
                logger,
                wall_test=lambda hero, target, radius: line_of_sight.blocked(
                    runtime.current_floor_id(), hero, target, radius),
            )
            reader.selection_label = selection_label
            logger.info(
                "INTERACTION DIAG enabled; mark hotkey=%s",
                args.interaction_mark_hotkey)
            return reader

        def npc_shadow_factory():
            """Phase 2 restoration evidence, ON by default.

            The canonical NPC source was reverted out of production on
            2026-08-06 because it is strictly more selective and can empty
            the NPC category outright. The evidence needed to swap it back
            safely was supposed to come from `--interaction-diagnostics`,
            which -- per the 2026-08-09 re-audit -- has never once run: not
            a single diagnostic line exists in three days of production
            log. An off-by-default validator validates nothing.

            So this one is on by default. It speaks nothing, publishes
            nothing, samples every five seconds, and its whole job is to
            log whether the canonical source would have agreed. Its
            `NPC SHADOW STARVED` warning is the go/no-go signal for the
            swap. `--no-npc-shadow` turns it off."""
            observed = entity_nav_parts.get("npc_source")
            runtime = entity_nav_parts.get("runtime")
            pose_source = entity_nav_parts.get("pose_source")
            if observed is None or runtime is None or pose_source is None:
                logger.warning(
                    "NPC SHADOW disabled: entity navigation is not "
                    "available to observe")
                return None
            entity_names = load_entity_names(
                data_root / "raw" / "files" / "common.fsys"
            )
            canonical = LiveNPCEntitySource(
                runtime, pose_source, entity_names,
                neck_resolver=NeckPositionResolver(
                    connection.memory, XD_US_REV0),
                wall_test=lambda hero, target, radius: line_of_sight.blocked(
                    runtime.current_floor_id(), hero, target, radius),
                logger=logger,
            )
            logger.info(
                "NPC SHADOW enabled; comparing %s against "
                "LiveNPCEntitySource every %.0fs",
                type(observed).__name__, NPC_SHADOW_INTERVAL)
            return NPCSourceShadowReader(observed, canonical, logger)

        settings_store = None
        settings_menu = None
        if args.settings_menu:
            def announce_save_failure(exc):
                speech.emit(
                    SpeechEventClass.WARNING,
                    "Settings could not be saved. They will still apply "
                    "until the companion closes.",
                    interrupt=False)

            settings_store = build_settings_store(
                args, base, logger, announce_save_failure)
            key_capture = LowLevelKeyCapture(
                MenuKeyPolicy(),
                # The same foreground rule every other hotkey follows: keys
                # are only ever taken while Dolphin has focus.
                WindowsForegroundProcess().is_active,
                logger)
            if key_capture.start():
                settings_menu = SettingsMenu(
                    settings_store, key_capture, speech, logger)
            else:
                # The settings still apply -- the store is kept, so stored
                # preferences and the CLI overrides are honoured -- but they
                # cannot be changed without the keyboard hook.
                key_capture = None
                speech.emit(
                    SpeechEventClass.WARNING,
                    "The settings menu could not start. Your saved settings "
                    "are still in effect.", interrupt=False)

        controller = LifecycleController(
            connection,
            tasks_factory,
            narrator_factory,
            speaker,
            logger,
            menu_factory=menu_factory,
            speech=speech,
            health_factory=health_factory,
            summary_factory=summary_factory,
            battle_start_factory=battle_start_factory,
            dialogue_factory=dialogue_factory,
            # Re-enabled 2026-08-05. It had been muted at the project
            # owner's request when every category shared one loud tone at
            # full beacon volume; it now plays one distinct named sound per
            # category at a quarter of the navigation beacon's volume.
            npc_sound_factory=npc_sound_factory,
            entity_nav_factory=entity_nav_factory,
            interaction_announcer_factory=interaction_announcer_factory,
            interaction_ready_factory=interaction_ready_factory,
            room_change_factory=room_change_factory,
            choice_menu_factory=choice_menu_factory,
            audio_guide_factory=audio_guide_factory,
            autowalk_factory=autowalk_factory,
            teleport_factory=teleport_factory,
            party_summary_factory=party_summary_factory,
            heart_gauge_summary_factory=heart_gauge_summary_factory,
            party_slot_summary_factory=party_slot_summary_factory,
            money_summary_factory=money_summary_factory,
            party_action_menu_factory=party_action_menu_factory,
            party_item_action_menu_factory=party_item_action_menu_factory,
            party_list_factory=party_list_factory,
            bag_menu_factory=bag_menu_factory,
            shop_buy_menu_factory=shop_buy_menu_factory,
            shop_buy_quantity_factory=shop_buy_quantity_factory,
            shop_notification_factory=shop_notification_factory,
            pause_menu_factory=pause_menu_factory,
            stone_selection_menu_factory=stone_selection_menu_factory,
            pda_factory=pda_factory,
            pc_menu_factory=pc_menu_factory,
            purify_chamber_factory=purify_chamber_factory,
            # Both readers are always BUILT and gated by their settings
            # instead of by the flags, so the menu's switches are real ones.
            # `--no-terrain-footsteps` and `--collision-feedback` now set the
            # starting value of those settings (see build_settings_store);
            # with the menu disabled entirely, the flags are all there is,
            # so the factories fall back to gating on them directly.
            terrain_footstep_factory=(
                terrain_footstep_factory
                if (settings_store is not None or args.terrain_footsteps)
                else None
            ),
            blocked_movement_factory=(
                blocked_movement_factory
                if (settings_store is not None or args.collision_feedback)
                else None
            ),
            interaction_diagnostics_factory=(
                interaction_diagnostics_factory
                if args.interaction_diagnostics else None
            ),
            npc_shadow_factory=(
                npc_shadow_factory if args.npc_shadow else None
            ),
            settings=settings_store,
            settings_menu=settings_menu,
        )
        controller.run()
    except UnsupportedProfile as exc:
        logger.error(str(exc))
        if speaker.loaded:
            speaker.speak("Unsupported game version.", interrupt=False)
        code = 2
    except (MalformedGSmsg, LocalDataError, SpeechError) as exc:
        logger.error(str(exc))
        if speaker.loaded:
            speaker.speak(
                "Battle narrator stopped after an error.", interrupt=False
            )
        code = 1
    except Exception:
        logger.exception("Battle narrator stopped after an unexpected error.")
        if speaker.loaded:
            speaker.speak(
                "Battle narrator stopped after an error.", interrupt=False
            )
        code = 1
    finally:
        if key_capture is not None:
            key_capture.stop()
        connection.close()
        speaker.close()
    return code











