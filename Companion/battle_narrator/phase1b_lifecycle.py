import time
import wave
from enum import Enum, auto

from .memory import MemoryError
from .messages import LocalDataError
from .phase1b_connection import (
    ConnectionError,
    ProfileNotReady,
    UnsupportedProfile,
)
from .phase1b_tasks import GSmsgUnavailable, MalformedGSmsg
from .speech import SpeechEventClass


class LifecycleState(Enum):
    DOLPHIN_ABSENT = auto()
    ATTACHING = auto()
    PROFILE_PENDING = auto()
    GSMSG_WAITING = auto()
    ACTIVE = auto()
    DISCONNECTED = auto()
    SHUTDOWN = auto()


class LifecycleController:
    def __init__(
        self,
        connection,
        tasks_factory,
        narrator_factory,
        speaker,
        logger,
        waiting_interval=0.5,
        active_interval=0.05,
        menu_factory=None,
        speech=None,
        health_factory=None,
        summary_factory=None,
        battle_start_factory=None,
        dialogue_factory=None,
        npc_sound_factory=None,
        entity_nav_factory=None,
        interaction_announcer_factory=None,
        interaction_ready_factory=None,
        room_change_factory=None,
        choice_menu_factory=None,
        audio_guide_factory=None,
        autowalk_factory=None,
        teleport_factory=None,
        party_summary_factory=None,
        heart_gauge_summary_factory=None,
        party_slot_summary_factory=None,
        money_summary_factory=None,
        party_action_menu_factory=None,
        party_item_action_menu_factory=None,
        party_list_factory=None,
        bag_category_factory=None,
        bag_menu_factory=None,
        shop_buy_menu_factory=None,
        shop_buy_quantity_factory=None,
        shop_notification_factory=None,
        pause_menu_factory=None,
        stone_selection_menu_factory=None,
        pda_factory=None,
        pc_menu_factory=None,
        purify_chamber_factory=None,
        terrain_footstep_factory=None,
        blocked_movement_factory=None,
        interaction_diagnostics_factory=None,
        npc_shadow_factory=None,
        settings=None,
        settings_menu=None,
    ):
        self.connection = connection
        self.tasks_factory = tasks_factory
        self.narrator_factory = narrator_factory
        self.speaker = speaker
        self.logger = logger
        self.waiting_interval = waiting_interval
        self.active_interval = active_interval
        self.menu_factory = menu_factory
        self.speech = speech
        self.health_factory = health_factory
        self.summary_factory = summary_factory
        self.battle_start_factory = battle_start_factory
        self.dialogue_factory = dialogue_factory
        self.npc_sound_factory = npc_sound_factory
        self.entity_nav_factory = entity_nav_factory
        self.interaction_announcer_factory = interaction_announcer_factory
        self.interaction_ready_factory = interaction_ready_factory
        self.room_change_factory = room_change_factory
        self.choice_menu_factory = choice_menu_factory
        self.audio_guide_factory = audio_guide_factory
        self.autowalk_factory = autowalk_factory
        self.teleport_factory = teleport_factory
        self.party_summary_factory = party_summary_factory
        self.heart_gauge_summary_factory = heart_gauge_summary_factory
        self.party_slot_summary_factory = party_slot_summary_factory
        self.money_summary_factory = money_summary_factory
        self.party_action_menu_factory = party_action_menu_factory
        self.party_item_action_menu_factory = party_item_action_menu_factory
        self.party_list_factory = party_list_factory
        self.bag_category_factory = bag_category_factory
        self.bag_menu_factory = bag_menu_factory
        self.shop_buy_menu_factory = shop_buy_menu_factory
        self.shop_buy_quantity_factory = shop_buy_quantity_factory
        self.shop_notification_factory = shop_notification_factory
        self.pause_menu_factory = pause_menu_factory
        self.stone_selection_menu_factory = stone_selection_menu_factory
        self.pda_factory = pda_factory
        self.pc_menu_factory = pc_menu_factory
        self.purify_chamber_factory = purify_chamber_factory
        self.terrain_footstep_factory = terrain_footstep_factory
        self.blocked_movement_factory = blocked_movement_factory
        self.interaction_diagnostics_factory = interaction_diagnostics_factory
        self.npc_shadow_factory = npc_shadow_factory
        self.settings = settings
        """Player settings, or None when the settings menu is disabled. Not
        a factory like everything else here: it holds the player's choices,
        so rebuilding it on every reattach would throw them away."""
        self.settings_menu = settings_menu
        if self.settings_menu is not None:
            self.settings_menu.controller = self
        self._feature_states = {}
        """Last known on/off state per gated feature, so switching one off
        can clear its reader exactly once instead of every tick."""
        self.state = LifecycleState.DOLPHIN_ABSENT
        self.tasks = None
        self.narrator = None
        self.menu_reader = None
        self.health_reader = None
        self.summary_reader = None
        self.battle_start_reader = None
        self.dialogue_reader = None
        self.npc_sound_reader = None
        self.entity_nav_reader = None
        self.interaction_announcer_reader = None
        self.interaction_ready_reader = None
        self.room_change_reader = None
        self.choice_menu_reader = None
        self.audio_guide_reader = None
        self.autowalk_reader = None
        self.teleport_reader = None
        self.party_summary_reader = None
        self.heart_gauge_summary_reader = None
        self.party_slot_summary_reader = None
        self.money_summary_reader = None
        self.party_action_menu_reader = None
        self.party_item_action_menu_reader = None
        self.party_list_reader = None
        self.bag_category_reader = None
        self.bag_menu_reader = None
        self.shop_buy_menu_reader = None
        self.shop_buy_quantity_reader = None
        self.shop_notification_reader = None
        self.pause_menu_reader = None
        self.stone_selection_menu_reader = None
        self.pda_reader = None
        self.pc_menu_reader = None
        self.purify_chamber_reader = None
        self.terrain_footstep_reader = None
        self.blocked_movement_reader = None
        self.interaction_diagnostics_reader = None
        self.npc_shadow_reader = None
        self.attached_build = None
        self.connection_announced = False
        self.ready_announced = False
        self.disconnection_announced = False
        self.stop_requested = False

    @property
    def interval(self):
        if self.state is LifecycleState.ACTIVE:
            return self.active_interval
        if self.settings_menu is not None and self.settings_menu.open:
            # An open menu is someone pressing keys and waiting to be told
            # what happened. The waiting states tick twice a second, which
            # is right for "is Dolphin back yet" and far too slow for that
            # -- and the menu is usable in those states by design, since it
            # needs no game. No key is ever lost either way (they queue),
            # but at half a second the announcements arrive in bursts.
            return self.active_interval
        return self.waiting_interval

    def transition(self, new_state, reason):
        if new_state is not self.state:
            self.logger.debug(
                "LIFECYCLE %s -> %s: %s",
                self.state.name,
                new_state.name,
                reason,
            )
            self.state = new_state

    def emit(self, event_class, text, deduplicate=False):
        if self.speech is not None:
            return self.speech.emit(event_class, text, deduplicate)
        return self.speaker.speak(text, interrupt=False)

    def clear_battle_state(self):
        self.tasks = None
        self.narrator = None

    def _build(self, factory, name):
        """Construct one optional reader, or disable just that reader if its
        own local data cannot be loaded.

        **Live-caught 2026-08-12.** `pda_menu.fsys` contains one entry whose
        LZSS header reads `7f 00 53 53` instead of `4c 5a 53 53`, so
        `parse_fsys` -- which decompresses every entry eagerly -- raised, and
        `PdaCatalog` turned that into a `LocalDataError`. Nothing caught it
        between here and `main`, whose handler logs, says "Battle narrator
        stopped after an error." and exits 1. Observed three times in 61
        seconds: the narrator attached, verified the disc, announced itself,
        hit the PDA and died about a second later, every time.

        One optional catalog being unreadable must not cost the player
        battle narration, menus, dialogue and navigation. A reader that
        cannot be built is left as `None`, which every call site already
        handles -- that is exactly what passing no factory for it does.

        Scoped to `LocalDataError` on purpose: that is the project's own
        "local extracted data is missing or malformed" signal, and it is
        raised only while building a catalog from a file. Anything else
        still propagates, because a reader failing for a reason that is not
        about its data is a real defect and should be loud."""
        if factory is None:
            return None
        try:
            return factory()
        except LocalDataError as exc:
            self.logger.error(
                "%s disabled: %s. Every other feature continues; re-extract "
                "this file to restore it.", name, exc)
            return None

    def clear_menu_state(self, reason):
        if self.menu_reader is not None:
            self.menu_reader.clear(reason)
        self.menu_reader = None

    def clear_health_state(self, reason):
        if self.health_reader is not None:
            self.health_reader.clear(reason)
        self.health_reader = None

    def clear_summary_state(self, reason):
        if self.summary_reader is not None:
            self.summary_reader.clear(reason)
        self.summary_reader = None

    def clear_battle_start_state(self, reason):
        if self.battle_start_reader is not None:
            self.battle_start_reader.clear(reason)
        self.battle_start_reader = None

    def clear_dialogue_state(self, reason):
        if self.dialogue_reader is not None:
            self.dialogue_reader.clear(reason)
        self.dialogue_reader = None

    def clear_npc_sound_state(self, reason):
        if self.npc_sound_reader is not None:
            self.npc_sound_reader.clear(reason)
        self.npc_sound_reader = None

    def clear_entity_nav_state(self, reason):
        if self.entity_nav_reader is not None:
            self.entity_nav_reader.clear(reason)
        self.entity_nav_reader = None

    def clear_npc_shadow_state(self, reason):
        if self.npc_shadow_reader is not None:
            self.npc_shadow_reader.clear(reason)
        self.npc_shadow_reader = None

    def clear_interaction_announcer_state(self, reason):
        if self.interaction_announcer_reader is not None:
            self.interaction_announcer_reader.clear(reason)
        self.interaction_announcer_reader = None

    def clear_interaction_ready_state(self, reason):
        if self.interaction_ready_reader is not None:
            self.interaction_ready_reader.clear(reason)
        self.interaction_ready_reader = None

    def clear_room_change_state(self, reason):
        if self.room_change_reader is not None:
            self.room_change_reader.clear(reason)
        self.room_change_reader = None

    def clear_choice_menu_state(self, reason):
        if self.choice_menu_reader is not None:
            self.choice_menu_reader.clear(reason)
        self.choice_menu_reader = None

    def clear_audio_guide_state(self, reason):
        if self.audio_guide_reader is not None:
            self.audio_guide_reader.clear(reason)
        self.audio_guide_reader = None

    def clear_autowalk_state(self, reason):
        """Unlike the other clears, this one has a real side effect on the
        GAME: it hands the controller back. Dropping the reader without
        calling `clear` would leave the engine's stick override latched and
        the player unable to move, so the reader is cleared first and
        unconditionally -- including on the disconnect path, which is
        exactly when it matters most."""
        if self.autowalk_reader is not None:
            self.autowalk_reader.clear(reason)
        self.autowalk_reader = None

    def clear_teleport_state(self, reason):
        self.teleport_reader = None

    def clear_party_summary_state(self, reason):
        if self.party_summary_reader is not None:
            self.party_summary_reader.clear(reason)
        self.party_summary_reader = None

    def clear_heart_gauge_summary_state(self, reason):
        if self.heart_gauge_summary_reader is not None:
            self.heart_gauge_summary_reader.clear(reason)
        self.heart_gauge_summary_reader = None


    def clear_party_slot_summary_state(self, reason):
        if self.party_slot_summary_reader is not None:
            self.party_slot_summary_reader.clear(reason)
        self.party_slot_summary_reader = None
    def clear_money_summary_state(self, reason):
        if self.money_summary_reader is not None:
            self.money_summary_reader.clear(reason)
        self.money_summary_reader = None

    def clear_party_action_menu_state(self, reason):
        if self.party_action_menu_reader is not None:
            self.party_action_menu_reader.clear(reason)
        self.party_action_menu_reader = None

    def clear_party_item_action_menu_state(self, reason):
        if self.party_item_action_menu_reader is not None:
            self.party_item_action_menu_reader.clear(reason)
        self.party_item_action_menu_reader = None

    def clear_party_list_state(self, reason):
        if self.party_list_reader is not None:
            self.party_list_reader.clear(reason)
        self.party_list_reader = None

    def clear_bag_category_state(self, reason):
        if self.bag_category_reader is not None:
            self.bag_category_reader.clear(reason)
        self.bag_category_reader = None

    def clear_bag_menu_state(self, reason):
        if self.bag_menu_reader is not None:
            self.bag_menu_reader.clear(reason)
        self.bag_menu_reader = None
        if self.shop_buy_menu_reader is not None:
            self.shop_buy_menu_reader.clear(reason)
        self.shop_buy_menu_reader = None
        if self.shop_buy_quantity_reader is not None:
            self.shop_buy_quantity_reader.clear(reason)
        self.shop_buy_quantity_reader = None
        if self.shop_notification_reader is not None:
            self.shop_notification_reader.clear(reason)
        self.shop_notification_reader = None

    def clear_pause_menu_state(self, reason):
        if self.pause_menu_reader is not None:
            self.pause_menu_reader.clear(reason)
        self.pause_menu_reader = None

    def clear_stone_selection_menu_state(self, reason):
        if self.stone_selection_menu_reader is not None:
            self.stone_selection_menu_reader.clear(reason)
        self.stone_selection_menu_reader = None

    def clear_pda_state(self, reason):
        if self.pda_reader is not None:
            self.pda_reader.clear(reason)
        self.pda_reader = None

    def clear_pc_menu_state(self, reason):
        if self.pc_menu_reader is not None:
            self.pc_menu_reader.clear(reason)
        self.pc_menu_reader = None

    def clear_purify_chamber_state(self, reason):
        if self.purify_chamber_reader is not None:
            self.purify_chamber_reader.clear(reason)
        self.purify_chamber_reader = None

    def _feature_enabled(self, key, reader=None, on_disable=None):
        """Whether a settings-gated feature may run this tick.

        Gating here rather than tearing the reader down keeps a toggle
        cheap in both directions -- some of these readers load collision
        geometry or decode sound files to be built. The falling edge is
        detected so the reader can be cleared once, which matters for the
        ones that accumulate state: footstep cadence and the last-announced
        room would otherwise resume mid-stride when the player switches the
        feature back on.

        Defaults to enabled whenever settings are absent, so nothing here
        depends on the settings menu being available."""
        if self.settings is None:
            return True
        enabled = self.settings.enabled(key)
        was_enabled = self._feature_states.get(key, True)
        self._feature_states[key] = enabled
        if was_enabled and not enabled:
            self.logger.info("SETTINGS disabled %s", key)
            if reader is not None:
                reader.clear("disabled in settings")
            if on_disable is not None:
                on_disable()
        elif enabled and not was_enabled:
            self.logger.info("SETTINGS enabled %s", key)
        return enabled

    def poll_settings_menu(self):
        """Polled in every lifecycle state, including before Dolphin is
        running: the menu reads no emulated memory, and a player who wants
        to turn the beacons down should not have to boot a game first.

        Isolated like every reader -- the menu owns keys the game also
        wants, so an exception that killed the poll loop would leave the
        keyboard hook installed with nothing draining it."""
        if self.settings_menu is None:
            return
        try:
            self.settings_menu.poll_once()
        except Exception as exc:
            self.logger.warning("Isolated settings menu failure: %s", exc)

    def _beacons_silenced(self):
        """Whether every non-speech cue should be holding its tongue.

        Two reasons, and they are the same reason: the player is listening
        to speech that a repeating tone would sit on top of.

        - A conversation is open.
        - The settings menu is open. Requested by the project owner
          2026-08-18, and the Sound library heading makes it acute -- that
          screen exists to play cues one at a time so they can be told
          apart, which the ambient beacons were talking over.
        """
        if self.dialogue_reader is not None and self.dialogue_reader.active:
            return True
        return self.settings_menu is not None and self.settings_menu.open

    def poll_menus(self):
        if self.menu_reader is not None:
            self.menu_reader.poll_once()

    def poll_npc_sounds(self):
        if self.npc_sound_reader is None:
            return
        if not self._feature_enabled(
                "sounds.beacons", self.npc_sound_reader,
                # Stops whatever is mid-loop, so switching beacons off is
                # silent immediately rather than after the current sound.
                self.npc_sound_reader.suppress_for_dialogue):
            return
        if self._beacons_silenced():
            self.npc_sound_reader.suppress_for_dialogue()
            return
        try:
            self.npc_sound_reader.poll_once()
        except MemoryError as exc:
            self.logger.debug("Isolated NPC sound read failure: %s", exc)
            self.npc_sound_reader.clear("NPC sound read failure")
        except (ValueError, wave.Error, OSError) as exc:
            # An audio problem must not take the narrator down with it.
            # It did once (2026-08-05): a beacon sound the player could not
            # decode raised ValueError from inside `play`, which is not a
            # MemoryError, so it escaped this handler and killed the whole
            # process mid-session -- speech, menus and all. Losing beacons
            # is an inconvenience; losing the narrator while someone is
            # relying on it to play is not.
            #
            # Logged at WARNING, not DEBUG: unlike a transient memory read,
            # this will not fix itself, and silently dropping beacons for
            # the rest of the session would be its own trap.
            self.logger.warning(
                "NPC beacons disabled for this session -- audio failure: %s",
                exc)
            self.npc_sound_reader.clear("NPC sound playback failure")
            self.npc_sound_reader = None

    def poll_entity_nav(self):
        if self.entity_nav_reader is None:
            return
        dialogue_active = (
            self.dialogue_reader is not None and self.dialogue_reader.active
        )
        try:
            self.entity_nav_reader.poll_once(dialogue_active)
        except MemoryError as exc:
            self.logger.debug("Isolated entity-nav read failure: %s", exc)
            self.entity_nav_reader.clear("entity-nav read failure")

    def poll_interaction_announcer(self):
        if self.interaction_announcer_reader is None:
            return
        dialogue_active = (
            self.dialogue_reader is not None and self.dialogue_reader.active
        )
        try:
            self.interaction_announcer_reader.poll_once(dialogue_active)
        except MemoryError as exc:
            self.logger.debug(
                "Isolated interaction announcer read failure: %s", exc)
            self.interaction_announcer_reader.clear(
                "interaction announcer read failure")

    def poll_interaction_ready(self):
        if self.interaction_ready_reader is None:
            return
        if not self._feature_enabled(
                "speech.interaction_ready", self.interaction_ready_reader):
            return
        dialogue_active = (
            self.dialogue_reader is not None and self.dialogue_reader.active
        )
        try:
            self.interaction_ready_reader.poll_once(dialogue_active)
        except MemoryError as exc:
            self.logger.debug(
                "Isolated interaction ready read failure: %s", exc)
            self.interaction_ready_reader.clear(
                "interaction ready read failure")

    def poll_room_change(self):
        if self.room_change_reader is None:
            return
        if not self._feature_enabled(
                "speech.room_changes", self.room_change_reader):
            return
        try:
            self.room_change_reader.poll_once()
        except MemoryError as exc:
            self.logger.debug("Isolated room-change read failure: %s", exc)

    def poll_choice_menu(self):
        if self.choice_menu_reader is None:
            return
        try:
            self.choice_menu_reader.poll_once()
        except MemoryError as exc:
            self.logger.debug("Isolated choice menu read failure: %s", exc)
            self.choice_menu_reader.clear("choice menu read failure")

    def poll_audio_guide(self):
        if self.audio_guide_reader is None:
            return
        # Goes SILENT while a conversation or the settings menu is up, and
        # resumes afterwards -- it is not turned off; see
        # AudioGuideReader.poll_once.
        try:
            self.audio_guide_reader.poll_once(self._beacons_silenced())
        except MemoryError as exc:
            self.logger.debug("Isolated audio-guide read failure: %s", exc)
            self.audio_guide_reader.clear("audio-guide read failure")

    def poll_autowalk(self):
        """Isolated like every other reader, but with one difference: a read
        failure here stops the walk rather than merely clearing state.
        Steering blind is not a degraded mode worth having -- if the poll
        that decides where to push the stick failed, the right response is
        to stop pushing it."""
        if self.autowalk_reader is None:
            return
        try:
            self.autowalk_reader.poll_once()
        except MemoryError as exc:
            self.logger.debug("Isolated autowalk read failure: %s", exc)
            self.autowalk_reader.clear("autowalk read failure")

    def poll_terrain_footsteps(self):
        if self.terrain_footstep_reader is None:
            return
        if not self._feature_enabled(
                "sounds.footsteps", self.terrain_footstep_reader):
            return
        if self.dialogue_reader is not None and self.dialogue_reader.active:
            self.terrain_footstep_reader.clear("suppressed for dialogue")
            return
        try:
            self.terrain_footstep_reader.poll_once()
        except MemoryError as exc:
            self.logger.debug("Isolated terrain-footstep read failure: %s", exc)
            self.terrain_footstep_reader.clear("terrain-footstep read failure")

    def poll_blocked_movement(self):
        if self.blocked_movement_reader is None:
            return
        if not self._feature_enabled(
                "sounds.blocked_cue", self.blocked_movement_reader):
            return
        if self.dialogue_reader is not None and self.dialogue_reader.active:
            self.blocked_movement_reader.clear("suppressed for dialogue")
            return
        try:
            self.blocked_movement_reader.poll_once()
        except MemoryError as exc:
            self.logger.debug("Isolated blocked-movement read failure: %s", exc)
            self.blocked_movement_reader.clear("blocked-movement read failure")

    def poll_interaction_diagnostics(self):
        """Development-only. Off unless --interaction-diagnostics was
        passed, in which case the factory is None and this returns
        immediately. Isolated like every other reader: a diagnostic must
        never be able to take the narrator down."""
        if self.interaction_diagnostics_reader is None:
            return
        try:
            self.interaction_diagnostics_reader.poll_once()
        except MemoryError as exc:
            self.logger.debug(
                "Isolated interaction-diagnostics read failure: %s", exc)

    def poll_npc_shadow(self):
        """Phase 2 restoration evidence. Speaks nothing, publishes nothing,
        and is gated on the same free-roam context entity navigation uses,
        so it never compares sources during a menu or a cutscene where the
        actor pool is legitimately in flux.

        Isolated like every other reader, and additionally isolated inside
        itself: the comparison must never be able to disturb the thing it
        is comparing."""
        if self.npc_shadow_reader is None:
            return
        context_valid = (
            self.entity_nav_reader is not None
            and self.entity_nav_reader.context_valid
        )
        try:
            self.npc_shadow_reader.poll_once(context_valid)
        except MemoryError as exc:
            self.logger.debug("Isolated NPC shadow read failure: %s", exc)

    def poll_teleport(self):
        if self.teleport_reader is None:
            return
        try:
            self.teleport_reader.poll_once()
        except MemoryError as exc:
            self.logger.debug("Isolated teleport read failure: %s", exc)

    def disconnect(self, reason):
        self.clear_battle_state()
        self.clear_menu_state(reason)
        self.clear_health_state(reason)
        self.clear_summary_state(reason)
        self.clear_battle_start_state(reason)
        self.clear_dialogue_state(reason)
        self.clear_npc_sound_state(reason)
        self.clear_entity_nav_state(reason)
        self.clear_npc_shadow_state(reason)
        self.clear_interaction_announcer_state(reason)
        self.clear_interaction_ready_state(reason)
        self.clear_room_change_state(reason)
        self.clear_choice_menu_state(reason)
        self.clear_audio_guide_state(reason)
        self.clear_autowalk_state(reason)
        self.clear_teleport_state(reason)
        self.clear_party_summary_state(reason)
        self.clear_heart_gauge_summary_state(reason)
        self.clear_party_slot_summary_state(reason)
        self.clear_money_summary_state(reason)
        self.clear_party_action_menu_state(reason)
        self.clear_party_item_action_menu_state(reason)
        self.clear_party_list_state(reason)
        self.clear_bag_category_state(reason)
        self.clear_bag_menu_state(reason)
        self.clear_pause_menu_state(reason)
        self.clear_stone_selection_menu_state(reason)
        self.clear_pda_state(reason)
        self.clear_pc_menu_state(reason)
        self.clear_purify_chamber_state(reason)
        if self.settings_menu is not None:
            # Silently, unlike a player-pressed close: Dolphin has gone, so
            # there is nobody in front of the game to hear it, and the menu
            # must not be left holding the arrow keys for a window that no
            # longer exists.
            self.settings_menu.clear(reason)
        if self.speech is not None:
            self.speech.clear()
        self.connection.close()
        self.transition(LifecycleState.DISCONNECTED, reason)
        if not self.disconnection_announced:
            self.emit(
                SpeechEventClass.LIFECYCLE,
                "Battle narrator disconnected.",
                deduplicate=True,
            )
            self.logger.info("Battle narrator disconnected.")
            self.disconnection_announced = True
        self.connection_announced = False
        self.ready_announced = False

    def step(self):
        if self.stop_requested:
            self.transition(
                LifecycleState.SHUTDOWN, "user-requested shutdown"
            )
            return

        # First, and outside every state test: the settings menu is the one
        # feature that does not need a game, a profile, or an attached
        # Dolphin. It also owns keys Dolphin would otherwise act on, so it
        # must keep draining them even in states where nothing else runs.
        self.poll_settings_menu()

        if self.state in {
            LifecycleState.DOLPHIN_ABSENT,
            LifecycleState.DISCONNECTED,
        }:
            self.transition(
                LifecycleState.ATTACHING, "attempting attachment"
            )

        if self.state is LifecycleState.ATTACHING:
            try:
                self.connection.hook()
            except ConnectionError as exc:
                self.transition(LifecycleState.DOLPHIN_ABSENT, str(exc))
                return
            self.transition(
                LifecycleState.PROFILE_PENDING,
                "Dolphin memory attached",
            )

        if self.state is LifecycleState.PROFILE_PENDING:
            if not self.connection.is_readable():
                self.disconnect("Dolphin became unreadable")
                return
            try:
                attached = self.connection.verify_profile()
                if attached is not None and attached != self.attached_build:
                    label, revision = attached
                    canonical = self.connection.profile.game_id.decode(
                        "ascii", errors="replace")
                    self.logger.info(
                        "Engine verified: disc %s revision %d%s",
                        label, revision,
                        "" if label == canonical
                        else f" (relabelled from {canonical}; "
                             "engine matches, so this is supported)")
                    self.attached_build = attached
            except ProfileNotReady:
                self.clear_menu_state("profile temporarily unavailable")
                return
            except UnsupportedProfile:
                self.clear_menu_state("unsupported profile")
                raise
            except MemoryError as exc:
                self.logger.debug(
                    "Temporary profile read failure: %s", exc
                )
                self.clear_menu_state("profile read failure")
                return
            if not self.connection_announced:
                self.emit(
                    SpeechEventClass.LIFECYCLE,
                    "Battle narrator connected.",
                    deduplicate=True,
                )
                self.logger.info("Battle narrator connected.")
                self.connection_announced = True
                self.disconnection_announced = False
            self.menu_reader = self._build(self.menu_factory, "menu")
            self.health_reader = self._build(self.health_factory, "health")
            self.summary_reader = self._build(self.summary_factory, "summary")
            self.battle_start_reader = self._build(
                self.battle_start_factory, "battle_start")
            self.dialogue_reader = self._build(self.dialogue_factory, "dialogue")
            self.npc_sound_reader = self._build(self.npc_sound_factory, "npc_sound")
            self.entity_nav_reader = self._build(self.entity_nav_factory, "entity_nav")
            self.interaction_announcer_reader = self._build(
                self.interaction_announcer_factory, "interaction_announcer")
            self.interaction_ready_reader = self._build(
                self.interaction_ready_factory, "interaction_ready")
            self.room_change_reader = self._build(self.room_change_factory, "room_change")
            self.choice_menu_reader = self._build(self.choice_menu_factory, "choice_menu")
            # These two take the entity-nav reader as an argument, so they
            # are built through a lambda rather than passed directly -- the
            # LocalDataError guard applies exactly the same way.
            if self.entity_nav_reader is not None:
                self.audio_guide_reader = self._build(
                    self.audio_guide_factory
                    and (lambda: self.audio_guide_factory(self.entity_nav_reader)),
                    "audio_guide")
                self.teleport_reader = self._build(
                    self.teleport_factory
                    and (lambda: self.teleport_factory(self.entity_nav_reader)),
                    "teleport")
                self.autowalk_reader = self._build(
                    self.autowalk_factory
                    and (lambda: self.autowalk_factory(self.entity_nav_reader)),
                    "autowalk")
            self.party_summary_reader = self._build(self.party_summary_factory, "party_summary")
            self.heart_gauge_summary_reader = self._build(self.heart_gauge_summary_factory, "heart_gauge_summary")
            self.party_slot_summary_reader = self._build(
                self.party_slot_summary_factory, "party_slot_summary")
            self.money_summary_reader = self._build(self.money_summary_factory, "money_summary")
            self.party_action_menu_reader = self._build(self.party_action_menu_factory, "party_action_menu")
            self.party_item_action_menu_reader = self._build(self.party_item_action_menu_factory, "party_item_action_menu")
            self.party_list_reader = self._build(self.party_list_factory, "party_list")
            self.bag_category_reader = self._build(self.bag_category_factory, "bag_category")
            self.bag_menu_reader = self._build(self.bag_menu_factory, "bag_menu")
            self.shop_buy_menu_reader = self._build(self.shop_buy_menu_factory, "shop_buy_menu")
            self.shop_buy_quantity_reader = self._build(self.shop_buy_quantity_factory, "shop_buy_quantity")
            self.shop_notification_reader = self._build(self.shop_notification_factory, "shop_notification")
            self.pause_menu_reader = self._build(self.pause_menu_factory, "pause_menu")
            self.stone_selection_menu_reader = self._build(self.stone_selection_menu_factory, "stone_selection_menu")
            self.pda_reader = self._build(self.pda_factory, "pda")
            self.pc_menu_reader = self._build(self.pc_menu_factory, "pc_menu")
            self.purify_chamber_reader = self._build(self.purify_chamber_factory, "purify_chamber")
            self.terrain_footstep_reader = self._build(self.terrain_footstep_factory, "terrain_footstep")
            self.blocked_movement_reader = self._build(self.blocked_movement_factory, "blocked_movement")
            self.npc_shadow_reader = self._build(self.npc_shadow_factory, "npc_shadow")
            self.interaction_diagnostics_reader = self._build(
                self.interaction_diagnostics_factory, "interaction_diagnostics")
            if self.interaction_diagnostics_reader is not None:
                # The dialogue reader is owned here, and the diagnostic
                # needs it to tell "the A press opened a conversation"
                # from "the A press did nothing" -- which is the whole
                # point of the manual marker.
                self.interaction_diagnostics_reader.dialogue_active = (
                    lambda: self.dialogue_reader is not None
                    and self.dialogue_reader.active)
            if self.settings is not None:
                # Every reader above is brand new, holding its constructor
                # defaults. The player's choices live in the store, not in
                # the readers, so they are pushed back in here -- on the
                # first attach and on every reattach after a disconnect.
                self.settings.apply_all(self)
            self.tasks = self.tasks_factory()
            self.transition(
                LifecycleState.GSMSG_WAITING,
                "verified profile; GSmsg not initialized",
            )

        if self.state is LifecycleState.GSMSG_WAITING:
            if not self.connection.is_readable():
                self.disconnect("Dolphin became unreadable while waiting")
                return
            try:
                self.connection.verify_profile()
                self.poll_menus()
                self.poll_npc_sounds()
                self.poll_entity_nav()
                self.poll_interaction_announcer()
                self.poll_interaction_ready()
                self.poll_room_change()
                self.poll_choice_menu()
                self.poll_audio_guide()
                self.poll_autowalk()
                self.poll_teleport()
                self.poll_terrain_footsteps()
                self.poll_blocked_movement()
                self.poll_npc_shadow()
                self.poll_interaction_diagnostics()
                self.tasks.resolve()
            except GSmsgUnavailable as exc:
                self.logger.debug("GSmsg waiting: %s", exc)
                return
            except ProfileNotReady:
                self.clear_menu_state("profile temporarily unavailable")
                self.transition(
                    LifecycleState.PROFILE_PENDING,
                    "profile temporarily unavailable",
                )
                return
            except MalformedGSmsg:
                raise
            except MemoryError as exc:
                if not self.connection.is_readable():
                    self.disconnect(str(exc))
                    return
                self.logger.debug(
                    "Temporary wait-state read failure: %s", exc
                )
                return
            self.narrator = self.narrator_factory(self.tasks)
            if not self.ready_announced:
                self.emit(
                    SpeechEventClass.LIFECYCLE,
                    "Battle narration ready.",
                    deduplicate=True,
                )
                self.logger.info("Battle narration ready.")
                self.ready_announced = True
            self.transition(
                LifecycleState.ACTIVE, "GSmsg initialized"
            )
            return

        if self.state is LifecycleState.ACTIVE:
            if not self.connection.is_readable():
                self.disconnect("Dolphin became unreadable while active")
                return
            try:
                # Focus speech is sampled first. A battle event found in the
                # same tick then interrupts stale focus and cannot be lost.
                if self.dialogue_reader is not None:
                    self.dialogue_reader.poll_once()
                self.poll_menus()
                self.poll_npc_sounds()
                self.poll_entity_nav()
                self.poll_interaction_announcer()
                self.poll_interaction_ready()
                self.poll_room_change()
                self.poll_choice_menu()
                self.poll_audio_guide()
                self.poll_autowalk()
                self.poll_teleport()
                self.poll_terrain_footsteps()
                self.poll_blocked_movement()
                self.poll_npc_shadow()
                self.poll_interaction_diagnostics()
                self.narrator.poll_once()
            except GSmsgUnavailable as exc:
                self.clear_battle_state()
                if self.menu_reader is not None:
                    self.menu_reader.clear("GSmsg transition")
                self.tasks = self.tasks_factory()
                self.transition(
                    LifecycleState.GSMSG_WAITING,
                    f"GSmsg transition: {exc}",
                )
                return
            except MalformedGSmsg:
                raise
            except MemoryError as exc:
                if not self.connection.is_readable():
                    self.disconnect(str(exc))
                    return
                self.logger.debug(
                    "Temporary active read failure: %s", exc
                )
                self.clear_battle_state()
                if self.menu_reader is not None:
                    self.menu_reader.clear("temporary active read failure")
                self.tasks = self.tasks_factory()
                self.transition(
                    LifecycleState.GSMSG_WAITING,
                    "temporary active read failure",
                )
                return
            if self.health_reader is not None:
                try:
                    self.health_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated health read failure: %s", exc)
                    self.health_reader.clear("health read failure")
            if self.summary_reader is not None:
                try:
                    self.summary_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated HP summary read failure: %s", exc)
                    self.summary_reader.clear("HP summary read failure")
            if self.battle_start_reader is not None:
                try:
                    self.battle_start_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug(
                        "Isolated battle start read failure: %s", exc)
                    self.battle_start_reader.clear("battle start read failure")
            if self.party_summary_reader is not None:
                try:
                    self.party_summary_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated party summary read failure: %s", exc)
                    self.party_summary_reader.clear("party summary read failure")
            if self.heart_gauge_summary_reader is not None:
                try:
                    self.heart_gauge_summary_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated Heart Gauge read failure: %s", exc)
                    self.heart_gauge_summary_reader.clear("Heart Gauge read failure")
            if self.party_slot_summary_reader is not None:
                try:
                    self.party_slot_summary_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug(
                        "Isolated party slot read failure: %s", exc)
                    self.party_slot_summary_reader.clear(
                        "party slot read failure")
            if self.money_summary_reader is not None:
                try:
                    self.money_summary_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated money read failure: %s", exc)
                    self.money_summary_reader.clear("money read failure")
            if self.party_action_menu_reader is not None:
                try:
                    self.party_action_menu_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated party action menu read failure: %s", exc)
                    self.party_action_menu_reader.clear("party action menu read failure")
            if self.party_item_action_menu_reader is not None:
                try:
                    self.party_item_action_menu_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated party item action menu read failure: %s", exc)
                    self.party_item_action_menu_reader.clear("party item action menu read failure")
            if self.party_list_reader is not None:
                try:
                    self.party_list_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated party list read failure: %s", exc)
                    self.party_list_reader.clear("party list read failure")
            if self.bag_category_reader is not None:
                try:
                    self.bag_category_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated bag category read failure: %s", exc)
                    self.bag_category_reader.clear("bag category read failure")
            if self.bag_menu_reader is not None:
                try:
                    self.bag_menu_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated bag menu read failure: %s", exc)
                    self.bag_menu_reader.clear("bag menu read failure")
            if self.shop_buy_menu_reader is not None:
                try:
                    self.shop_buy_menu_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug(
                        "Isolated shop buy menu read failure: %s", exc)
                    self.shop_buy_menu_reader.clear(
                        "shop buy menu read failure")
            if self.shop_buy_quantity_reader is not None:
                try:
                    self.shop_buy_quantity_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug(
                        "Isolated shop buy quantity read failure: %s", exc)
                    self.shop_buy_quantity_reader.clear(
                        "shop buy quantity read failure")
            if self.shop_notification_reader is not None:
                try:
                    self.shop_notification_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug(
                        "Isolated shop notification read failure: %s", exc)
                    self.shop_notification_reader.clear(
                        "shop notification read failure")
            if self.pause_menu_reader is not None:
                try:
                    self.pause_menu_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated pause menu read failure: %s", exc)
                    self.pause_menu_reader.clear("pause menu read failure")
            if self.stone_selection_menu_reader is not None:
                try:
                    self.stone_selection_menu_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated stone selection menu read failure: %s", exc)
                    self.stone_selection_menu_reader.clear("stone selection menu read failure")
            if self.pda_reader is not None:
                try:
                    self.pda_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated PDA read failure: %s", exc)
                    self.pda_reader.clear("PDA read failure")
            if self.pc_menu_reader is not None:
                try:
                    self.pc_menu_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug("Isolated PC menu read failure: %s", exc)
                    self.pc_menu_reader.clear("PC menu read failure")
            if self.purify_chamber_reader is not None:
                try:
                    self.purify_chamber_reader.poll_once()
                except MemoryError as exc:
                    self.logger.debug(
                        "Isolated Purify Chamber read failure: %s", exc)
                    self.purify_chamber_reader.clear(
                        "Purify Chamber read failure")
            if self.narrator.stop_requested:
                self.stop_requested = True

    def run(self):
        try:
            while self.state is not LifecycleState.SHUTDOWN:
                self.step()
                if self.state is not LifecycleState.SHUTDOWN:
                    time.sleep(self.interval)
        except KeyboardInterrupt:
            self.stop_requested = True
            self.transition(
                LifecycleState.SHUTDOWN,
                "clean keyboard interruption",
            )
            self.logger.info("Battle narrator stopped.")








