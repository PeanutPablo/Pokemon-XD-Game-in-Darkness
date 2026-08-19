from dataclasses import dataclass
import re

from .battle_targets import TargetFactsSource, status_panel_hp, target_detail
from .memory import MemoryError, require_range
from .resolver import display_case, normalize
from .speech import SpeechEventClass


class MenuReadError(MemoryError):
    pass


class GameDataMismatch(MenuReadError):
    """The installed game data describes a different build than is running.

    A subclass so every existing handler keeps treating it as an ordinary
    rejected sample -- refusing to speak is still the correct immediate
    behaviour, because the alternative is announcing "MEGA PUNCH" for Zen
    Headbutt. What it adds is a name for the one cause that will never fix
    itself by waiting, so the reader can say so out loud instead of going
    quiet and leaving the player with no idea why.

    Raised only where a LIVE reading and the OFFLINE table disagree about
    the same move ID. That combination cannot be a transient: both are
    read from the same settled sample, and a partially-built menu fails
    the pointer and PP checks well before this one.

    Seen twice for real, in both directions: a vanilla extraction against
    XG (live 'Zen Headbutt' / local 'MEGA PUNCH', 2026-08-12) and an XG
    extraction against vanilla (live 'SOFTBOILED' / local 'Psychic Fangs',
    2026-08-13). Only 192 of 373 move IDs name the same move in both
    builds, so most of the menu goes silent while the handful of shared
    IDs -- Substitute, Fury Cutter -- keep working, which is a genuinely
    confusing symptom to be left alone with."""


GAME_DATA_MISMATCH_ADVICE = (
    "Accessibility game data does not match the game that is running, so "
    "move names cannot be read. Re-run the game data setup against the "
    "disc image you are playing."
)


@dataclass(frozen=True)
class WindowNode:
    address: int
    menu_id: int


@dataclass(frozen=True)
class CommandFocus:
    work: int
    menu_id: int
    index: int
    label: str


@dataclass(frozen=True)
class TitleScreenFocus:
    label: str = "Pokemon XD: Gale of Darkness. Press A to start."


@dataclass(frozen=True)
class HealthSafetyFocus:
    label: str = (
        "Warning: Health and Safety. Before playing, read the Health and "
        "Safety Precautions Booklet for important information about your "
        "health and safety."
    )


@dataclass(frozen=True)
class NotificationFocus:
    message_id: int
    label: str


@dataclass(frozen=True)
class OptionFocus:
    work: int
    menu_id: int
    index: int
    label: str
    value: str | None

    @property
    def speech(self):
        return (
            f"{self.label}, {self.value}"
            if self.value is not None else self.label
        )


@dataclass(frozen=True)
class NameKeyboardFocus:
    work: int
    menu_id: int
    index: int
    label: str
    entered_name: str

    @property
    def speech(self):
        return self.label


@dataclass(frozen=True)
class MoveFocus:
    work: int
    menu_id: int
    status: int
    slot: int
    move_id: int
    live_name: str
    local_name: str
    current_pp: int
    maximum_pp: int
    type_name: str
    power: int
    accuracy: int
    description: str

    @property
    def speech(self):
        return (
            f"{display_case(self.local_name)}, "
            f"{self.current_pp}/{self.maximum_pp} P P. {self.description}."
        )



@dataclass(frozen=True)
class VsButtonPanel:
    work: int
    menu_id: int
    allocation: int
    actor: int
    actor_name: str
    moves: tuple

    @property
    def speech(self):
        items = ". ".join(
            f"{button}, {display_case(name)}, {current}/{maximum} P P"
            for button, name, current, maximum in self.moves
        )
        return f"{display_case(self.actor_name)} moves. {items}."


@dataclass(frozen=True)
class VsTargetPanel:
    work: int
    menu_id: int
    actor: int
    targets: tuple
    """(button, name, detail) per selectable target. `detail` is
    `battle_targets.target_detail`'s clause -- level, HP, percent and
    status -- or "" when none of it could be established, in which case
    the sentence is exactly what it used to be."""

    @property
    def speech(self):
        items = ". ".join(
            f"{button}, {display_case(name)}"
            + (f", {detail}" if detail else "")
            for button, name, detail in self.targets
        )
        return f"Targets. {items}."


@dataclass(frozen=True)
class StoryTargetFocus:
    work: int
    menu_id: int
    target: int
    slot: int
    name: str
    ownership: str
    detail: str = ""
    """Trailing and defaulted so every existing construction site stays
    valid -- the same reason `health.BattlerSample.owner` and
    `party.PartySlot.species` are placed last."""

    @property
    def speech(self):
        suffix = f", {self.detail}" if self.detail else ""
        return f"Target: {self.ownership} {display_case(self.name)}{suffix}."


class WindowListWalker:
    def __init__(self, memory, profile):
        self.memory = memory
        self.profile = profile

    def walk(self):
        p = self.profile
        pointer = self.memory.u32(
            p.window_manager + p.window_list_offset, "window-list head"
        )
        nodes = []
        seen = set()
        for _ in range(p.window_max_nodes):
            if pointer == 0:
                return nodes
            if pointer in seen:
                raise MenuReadError(
                    f"window list cycle at 0x{pointer:08X}"
                )
            try:
                require_range(
                    pointer,
                    p.window_node_size,
                    "window work",
                    p,
                    alignment=4,
                )
            except MemoryError as exc:
                raise MenuReadError(str(exc)) from exc
            seen.add(pointer)
            menu_id = self.memory.u32(
                pointer + p.window_menu_id_offset, "window menu ID"
            )
            nodes.append(WindowNode(pointer, menu_id))
            pointer = self.memory.u32(
                pointer + p.window_next_offset, "next window work"
            )
        if pointer != 0:
            raise MenuReadError(
                f"window list exceeds {p.window_max_nodes} nodes"
            )
        return nodes


class ProductionMenuReader:
    def __init__(
        self, memory, profile, move_data, speech, logger,
        title_messages=None, shop_messages=None, item_name_resolver=None,
        party_source=None, player_name_provider=None,
        message_renderer=None,
    ):
        self.memory = memory
        self.profile = profile
        self.move_data = move_data
        self.speech = speech
        self.logger = logger
        self.title_messages = title_messages or {}
        self.shop_messages = shop_messages
        self.item_name_resolver = item_name_resolver
        self.party_source = party_source
        self.player_name_provider = player_name_provider
        # Optional: `progress_notification_focus` is the only user, and it
        # returns None without one rather than falling back to a
        # paraphrase. Every existing test that constructs this reader
        # without a renderer therefore keeps its current behaviour of
        # "this screen is not a progress notification".
        self.message_renderer = message_renderer
        # Battle-target enrichment (level and major status). Constructed
        # here rather than injected because it needs nothing this reader
        # does not already hold, and it is read-only and per-slot tolerant
        # -- see battle_targets.TargetFactsSource.
        self.target_facts = TargetFactsSource(memory, profile)
        self.walker = WindowListWalker(memory, profile)
        self.identity = None
        self.yes_no_prompt_key = None
        self.unsupported = set()
        self.vs_actor = None
        self.vs_actor_name = None
        self.story_actor = None

    def _displayed_move(self, embedded_id, live_name):
        """Resolve the move the menu displays, which may be a Shadow override.

        Ordinary Pokemon use the ID in their embedded move slot. Shadow
        Pokemon can leave that ordinary ID there while the menu displays a
        different move. In that case the live name is resolved back through
        this build's own move table. An absent or non-unique name remains a
        hard mismatch; it is never guessed.
        """
        embedded_name, _suffix = self.move_data.resolve(embedded_id)
        if normalize(live_name) == normalize(embedded_name):
            return embedded_id, embedded_name
        find_id = getattr(self.move_data, "find_id", None)
        displayed_id = (
            find_id(live_name, self.profile.maximum_move_id)
            if find_id is not None else None
        )
        if displayed_id is None:
            raise GameDataMismatch(
                f"move-name disagreement live={live_name!r} "
                f"local={embedded_name!r}"
            )
        displayed_name, _suffix = self.move_data.resolve(displayed_id)
        return displayed_id, displayed_name

    def clear(self, reason="menu state cleared"):
        if self.identity is not None:
            self.logger.debug("MENU CLEAR reason=%s", reason)
        self.identity = None
        self.yes_no_prompt_key = None
        self.unsupported.clear()
        self.vs_actor = None
        self.vs_actor_name = None
        self.story_actor = None

    def _cursor(self, work):
        p = self.profile
        base = self.memory.u16(work + p.window_cursor_base_offset, "cursor base")
        cursor = self.memory.u16(work + p.window_cursor_offset, "cursor offset")
        if base & 0x8000:
            base -= 0x10000
        if cursor & 0x8000:
            cursor -= 0x10000
        return base, cursor, base + cursor

    def command_focus(self, node):
        base, cursor, logical = self._cursor(node.address)
        labels = self.profile.command_labels
        if logical < 0 or logical >= len(labels):
            raise MenuReadError(
                f"command cursor invalid base={base} cursor={cursor}"
            )
        return CommandFocus(
            node.address, node.menu_id, logical, labels[logical]
        )

    def mapped_focus(self, node, labels):
        base, cursor, logical = self._cursor(node.address)
        if logical < 0 or logical >= len(labels):
            raise MenuReadError(
                f"mapped cursor invalid base={base} cursor={cursor}"
            )
        return CommandFocus(
            node.address, node.menu_id, logical, labels[logical]
        )

    def direct_mapped_focus(self, node, cursor_address, labels):
        logical = self.memory.u8(cursor_address, "direct menu cursor")
        if logical >= len(labels):
            raise MenuReadError(
                f"direct mapped cursor invalid cursor={logical}"
            )
        return CommandFocus(
            node.address, node.menu_id, logical, labels[logical]
        )

    def name_keyboard_focus(self, node):
        p = self.profile
        column = self.memory.u32(
            p.name_keyboard_column_address,
            "name keyboard hover column",
        )
        row = self.memory.u32(
            p.name_keyboard_row_address,
            "name keyboard hover row",
        )
        rows = (
            None,  # row 0 uses the sparse coordinate table below
            None,  # row 1 uses the sparse coordinate table below
            ("U", "V", "W", "X", "Y", "Z", "Space", "Space", "Space", "Space"),
            ("1", "2", "3", "4", "5", "Exclamation mark", "Question mark", "Male symbol", "Female symbol", "Space"),
            ("6", "7", "8", "9", "0", "Left double quote", "Right double quote", "Left single quote", "Right single quote", "Space"),
            ("Space", "Space", "Space", "Space", "Space", "Slash", "Hyphen", "Ellipsis", "Period", "Comma"),
        )
        first_letter_row = {
            0: "A", 1: "B", 2: "C", 3: "D", 4: "E", 5: "Space",
            # XG live entry, 2026-08-13: selecting the cell announced as F
            # at column 5 inserted Space; column 6 inserted F.  The row has
            # the same visual separator after its first five letters that
            # row 1 has after O.
            6: "F", 7: "G", 8: "H", 9: "I", 10: "J",
        }
        second_letter_row = {
            0: "K", 1: "L", 2: "M", 3: "N", 4: "O", 5: "Space",
            # Name Rater live entry, 2026-08-12: selecting 5 inserted Space;
            # 6 inserted P; 7-10 inserted Q-T respectively.
            6: "P", 7: "Q", 8: "R", 9: "S", 10: "T",
        }
        if row == 0 and column in first_letter_row:
            label = first_letter_row[column]
        elif row == 1 and column in second_letter_row:
            label = second_letter_row[column]
        elif row == 6:
            label = "Back"
        elif row == 7:
            label = "Done"
        elif row < len(rows) and rows[row] is not None and 0 <= column < 10:
            label = rows[row][column]
        else:
            raise MenuReadError(
                f"name keyboard hover invalid column={column} row={row}"
            )
        entered_name = self.memory.gschar(
            p.name_input_address,
            p.name_input_maximum,
            "entered player name",
            2,
        )
        return NameKeyboardFocus(
            node.address,
            node.menu_id,
            (row << 16) | column,
            label,
            entered_name,
        )

    def active_gsmsg_prompt(self):
        p = self.profile
        manager = self.memory.u32(p.manager_root, "GSmsg manager pointer")
        if not manager:
            return 0, ""
        task_array = self.memory.pointer(
            manager + p.manager_tasks_offset,
            p.task_capacity * p.task_stride,
            "GSmsg task array",
            4,
        )
        for index in range(p.task_capacity):
            task = task_array + index * p.task_stride
            if self.memory.u8(task + p.task_state_offset, "GSmsg state") not in (1, 2):
                continue
            message_id = self.memory.u32(
                task + p.task_id_offset, "prompt packed message ID"
            ) & 0xFFFFFF
            if message_id == 15130:
                name = self.memory.gschar(
                    p.name_input_address,
                    p.name_input_maximum,
                    "entered player name",
                    2,
                )
                return message_id, f"Is {name} OK?" if name else "Is this name OK?"
            if message_id == 17113:
                return message_id, "Is it okay to start a new Story?"
            if (
                message_id in p.daycare_choice_prompt_message_ids
                and self.message_renderer is not None
            ):
                text = self.message_renderer.text(message_id)
                if text:
                    return message_id, text
            source = self.title_messages.get(message_id, "")
            text = re.sub(r"\[[^]]+\]", " ", source)
            text = " ".join(text.split()).strip()
            if not text and self.message_renderer is not None:
                # Most in-game confirmations are backed by the currently
                # loaded runtime message table, not the small title-screen
                # catalog above.  Resolve that live text instead of growing
                # a list of prompt IDs for every place the reusable Yes/No
                # widget can appear.
                text = self.message_renderer.text(message_id) or ""
            return message_id, text
        return 0, ""

    def continue_summary(self):
        if self.message_renderer is None:
            return ""
        fields = []
        for label_id, value_id in self.profile.continue_summary_message_pairs:
            label = self.message_renderer.text(label_id)
            value = self.message_renderer.text(value_id)
            if not label or not value:
                return ""
            fields.append(f"{label}: {value}")
        return ". ".join(fields)

    def move_teacher_focus(self, node):
        if self.message_renderer is None:
            raise MenuReadError("move-teacher message renderer unavailable")
        _base, _cursor, logical = self._cursor(node.address)
        count = self.memory.u16(
            self.profile.move_teacher_count_address,
            "move-teacher row count",
        )
        if logical < 0 or logical >= count:
            raise MenuReadError(
                f"move-teacher cursor {logical} outside row count {count}"
            )
        records = self.memory.pointer(
            self.profile.move_teacher_list_address,
            count * self.profile.move_teacher_record_stride,
            "move-teacher row records",
            4,
        )
        record = records + logical * self.profile.move_teacher_record_stride
        move_id = self.memory.u16(
            record + self.profile.move_teacher_move_offset,
            "move-teacher row move ID",
        )
        if move_id:
            try:
                label, _suffix = self.move_data.resolve(move_id)
            except MemoryError as exc:
                raise MenuReadError(
                    f"move-teacher row move {move_id} did not resolve"
                ) from exc
        else:
            # The terminal non-move row owns a regular message-table ID.
            # Move rows do not: the 2026-08-10 live EXTREMESPEED capture
            # proved their +4 word can be 0xB5353535 poison data.
            message_id = self.memory.u32(
                record + self.profile.move_teacher_message_offset,
                "move-teacher terminal-row message ID",
            )
            label = self.message_renderer.text(message_id)
            if not label:
                raise MenuReadError(
                    f"move-teacher terminal row message {message_id} "
                    "did not render"
                )
        return CommandFocus(node.address, node.menu_id, logical, label)

    def bag_action_focus(self, node):
        if self.message_renderer is None:
            raise MenuReadError("Bag-action message renderer unavailable")
        work = self.memory.pointer(
            node.address + self.profile.window_param_offset,
            8,
            "Bag-action work",
            4,
        )
        records = self.memory.u32(work, "Bag-action record pointer")
        count = self.memory.u32(work + 4, "Bag-action row count")
        if count < 1 or count > 16:
            raise MenuReadError(f"Bag-action row count invalid: {count}")
        require_range(
            records,
            count * self.profile.bag_action_record_stride,
            "Bag-action records",
            self.profile,
            alignment=4,
        )
        _base, _cursor, logical = self._cursor(node.address)
        if logical < 0 or logical >= count:
            raise MenuReadError(
                f"Bag-action cursor {logical} outside row count {count}"
            )
        message_id = self.memory.u32(
            records
            + logical * self.profile.bag_action_record_stride
            + self.profile.bag_action_message_offset,
            "Bag-action message ID",
        )
        label = self.message_renderer.text(message_id)
        if not label:
            raise MenuReadError(
                f"Bag-action message {message_id} did not render"
            )
        return CommandFocus(node.address, node.menu_id, logical, label)

    def bag_number_focus(self, node):
        value = self.memory.u32(
            self.profile.bag_number_value_address,
            "Bag numeric-input value",
        )
        # The game prints this value a digit at a time.  Reading the same
        # backing value avoids inventing a label and ignores digit-column
        # cursor movement that does not change the displayed number.
        if value > 999999999:
            raise MenuReadError(f"Bag numeric-input value invalid: {value}")
        return CommandFocus(node.address, node.menu_id, value, str(value))

    def yes_no_focus(self, node, include_prompt=True, initial_prefix="",
                     repeat_prompt=False, prompt_override=None):
        base, cursor, logical = self._cursor(node.address)
        if logical not in (0, 1):
            raise MenuReadError(
                f"yes/no cursor invalid base={base} cursor={cursor}"
            )
        message_id, prompt = self.active_gsmsg_prompt()
        if prompt_override:
            prompt = prompt_override
        choice = ("Yes", "No")[logical]
        prompt_key = (node.address, message_id, prompt)
        first_focus = prompt_key != self.yes_no_prompt_key
        self.yes_no_prompt_key = prompt_key
        label = (
            f"{prompt} {choice}"
            if (first_focus or repeat_prompt) and include_prompt and prompt
            else choice
        )
        if first_focus and initial_prefix:
            label = f"{initial_prefix}. {label}"
        return CommandFocus(node.address, node.menu_id, logical, label)

    def title_notification_focus(self, title_status):
        p = self.profile
        manager = self.memory.u32(p.manager_root, "GSmsg manager pointer")
        if not manager:
            return None
        task_array = self.memory.pointer(
            manager + p.manager_tasks_offset,
            p.task_capacity * p.task_stride,
            "GSmsg task array",
            4,
        )
        for index in range(p.task_capacity):
            task = task_array + index * p.task_stride
            if self.memory.u8(task + p.task_state_offset, "GSmsg state") not in (1, 2):
                continue
            packed = self.memory.u32(
                task + p.task_id_offset, "title packed message ID"
            )
            message_id = packed & 0xFFFFFF
            if (
                title_status not in p.title_notification_statuses
                and message_id not in p.global_save_notification_message_ids
            ):
                continue
            source = self.title_messages.get(message_id)
            if not source:
                continue
            text = re.sub(r"\[[^]]+\]", " ", source)
            text = " ".join(text.split()).strip()
            if text:
                return NotificationFocus(message_id, text)
        return None

    def progress_notification_focus(self):
        """Resolve evolution, purification, and acquisition info windows.

        These use the global GSmsg task array rather than the ordinary
        dialogue window, so DialogueReader cannot see them.

        The text is the GAME'S OWN, read out of its loaded string tables
        and substituted through `MessageRenderer` -- not a paraphrase.
        The previous implementation matched on message ID and spoke a
        typed-in English sentence per ID, which was wrong three ways:
        it silently desynchronised from what was actually drawn, it made
        the purification-ceremony results unreadable in practice
        (50503/50510/50511 all collapsed to one generic "Purification
        ceremony results for X", losing the EXP total and the regained
        move outright), and in a ROM hack the shipped text need not be
        the vanilla text the paraphrase was written from.

        `progress_notification_message_ids` stays an explicit set rather
        than "speak whatever GSmsg task is active". Three readers share
        this one task array -- this one, `ShopNotificationReader`
        (`shop_notification_message_ids`), and `title_notification_focus`
        -- and `DialogueReader` reads the same underlying task for
        ordinary field dialogue. The ID set is how ownership is
        partitioned between them; dropping it would double-speak every
        NPC line and every shop notice.
        """
        p = self.profile
        if self.message_renderer is None:
            return None
        manager = self.memory.u32(p.manager_root, "progress GSmsg manager")
        if not manager:
            return None
        tasks = self.memory.pointer(
            manager + p.manager_tasks_offset,
            p.task_capacity * p.task_stride, "progress GSmsg tasks", 4)
        for index in range(p.task_capacity):
            task = tasks + index * p.task_stride
            if self.memory.u8(task + p.task_state_offset, "progress message state") not in (1, 2):
                continue
            message_id = self.memory.u32(
                task + p.task_id_offset, "progress message ID") & 0xFFFFFF
            if message_id not in (
                p.progress_notification_message_ids
                | p.daycare_notification_message_ids
            ):
                continue
            text = self.message_renderer.text(message_id)
            if not text:
                # Not loaded (a map-local table that is not resident) or it
                # renders empty. Staying silent is right: speaking a
                # made-up stand-in is exactly the failure being removed
                # here. Logged so a genuinely missing table is findable
                # rather than invisible.
                self.logger.debug(
                    "PROGRESS NOTIFICATION unresolved id=%d", message_id)
                continue
            return NotificationFocus(message_id, text)
        return None

    def title_message_active(self, title_status):
        p = self.profile
        if title_status not in p.title_notification_statuses:
            return False
        manager = self.memory.u32(p.manager_root, "GSmsg manager pointer")
        if not manager:
            return False
        task_array = self.memory.pointer(
            manager + p.manager_tasks_offset,
            p.task_capacity * p.task_stride,
            "GSmsg task array",
            4,
        )
        return any(
            self.memory.u8(
                task_array + index * p.task_stride + p.task_state_offset,
                "GSmsg state",
            ) in (1, 2)
            for index in range(p.task_capacity)
        )

    def title_option_focus(self, node):
        p = self.profile
        base, cursor, logical = self._cursor(node.address)
        if logical < 0 or logical >= len(p.title_option_labels):
            raise MenuReadError(
                f"title option cursor invalid base={base} cursor={cursor}"
            )
        value = None
        if logical == 0:
            audio = self.memory.u8(
                p.audio_mode_address, "title option audio mode"
            )
            value = "Mono" if audio & p.audio_stereo_mask else "Stereo"
        elif logical == 1:
            manager = self.memory.pointer(
                p.game_data_root,
                p.game_data_save_offset
                + p.game_data_no_vibration_offset + 1,
                "game data root",
                4,
            )
            no_vibration = self.memory.u8(
                manager + p.game_data_save_offset
                + p.game_data_no_vibration_offset,
                "no-vibration option",
            )
            if no_vibration not in (0, 1):
                raise MenuReadError(
                    f"invalid no-vibration option {no_vibration}"
                )
            value = "Off" if no_vibration else "On"
        return OptionFocus(
            node.address,
            node.menu_id,
            logical,
            p.title_option_labels[logical],
            value,
        )

    def move_focus(self, node):
        p = self.profile
        base, cursor, slot = self._cursor(node.address)
        if slot < 0 or slot >= p.move_slot_count:
            raise MenuReadError(
                f"move cursor invalid base={base} cursor={cursor}"
            )
        status = self.memory.pointer(
            node.address + p.window_alloc_offset,
            p.move_status_size,
            "MENU_WAZA_STATUS",
            4,
        )
        record = status + p.move_record_base + slot * p.move_record_stride
        name_pointer = self.memory.u32(
            record + p.move_record_name_offset, "move-name pointer"
        )
        type_pointer = self.memory.u32(
            record + p.move_record_type_name_offset, "move-type pointer"
        )
        type_id = self.memory.u16(
            record + p.move_record_type_id_offset, "move type ID"
        )
        maximum_pp = self.memory.u8(
            record + p.move_record_max_pp_offset, "maximum PP"
        )
        current_pp = self.memory.u8(
            record + p.move_record_current_pp_offset, "current PP"
        )
        if (
            name_pointer == 0
            and type_pointer == 0
            and type_id == 0
            and maximum_pp == 0
            and current_pp == 0
        ):
            return None
        if name_pointer == 0 or type_pointer == 0:
            raise MenuReadError("partially populated move record")
        if maximum_pp == 0 or current_pp > maximum_pp:
            raise MenuReadError(
                f"invalid PP {current_pp}/{maximum_pp}"
            )
        acting = self.memory.pointer(
            status + p.move_status_actor_offset,
            p.fight_out_pokemon_offset + 4,
            "FightOutPokemon",
            4,
        )
        fight_pokemon = self.memory.pointer(
            acting + p.fight_out_pokemon_offset,
            p.embedded_pokemon_offset + p.pokemon_moves_offset
            + p.move_slot_count * p.pokemon_move_stride,
            "FightPokemon",
            4,
        )
        self.story_actor = fight_pokemon
        pokemon = fight_pokemon + p.embedded_pokemon_offset
        pokemon_waza = (
            pokemon + p.pokemon_moves_offset + slot * p.pokemon_move_stride
        )
        move_id = self.memory.u16(
            pokemon_waza + p.pokemon_move_id_offset, "move ID"
        )
        pokemon_pp = self.memory.u8(
            pokemon_waza + p.pokemon_move_pp_offset,
            "PokemonWaza current PP",
        )
        if move_id <= 0 or move_id > p.maximum_move_id:
            raise MenuReadError(f"move ID {move_id} outside verified range")
        if pokemon_pp != current_pp:
            raise MenuReadError(
                f"PP disagreement menu={current_pp} pokemon={pokemon_pp}"
            )
        require_range(
            name_pointer,
            (p.maximum_move_name_chars + 1) * 2,
            "live move name",
            p,
            alignment=1,
        )
        live_name = self.memory.gschar(
            name_pointer,
            p.maximum_move_name_chars,
            "live move name",
            alignment=1,
        )
        move_id, local_name = self._displayed_move(move_id, live_name)
        menu_after = self.memory.u32(
            node.address + p.window_menu_id_offset, "menu ID after sample"
        )
        status_after = self.memory.u32(
            node.address + p.window_alloc_offset,
            "move-status pointer after sample",
        )
        if menu_after != node.menu_id or status_after != status:
            raise MenuReadError("move menu changed during sample")
        details = self.move_data.details(move_id)
        return MoveFocus(
            node.address, node.menu_id, status, slot, move_id, live_name,
            local_name, current_pp, maximum_pp, details.type_name,
            details.power, details.accuracy, details.description,
        )

    def vs_button_panel(self, node):
        p = self.profile
        allocation = self.memory.pointer(
            node.address + p.window_alloc_offset,
            max(p.vs_move_actor_search_offsets) + 4,
            "VS move allocation",
            4,
        )
        active_base = (
            p.fight_floor_root + p.active_battler_array_offset
        )
        active = {
            self.memory.u32(
                active_base + slot * 4,
                f"VS active battler {slot}",
            )
            for slot in range(p.active_battler_slots)
        }
        actor_matches = {
            candidate
            for offset in p.vs_move_actor_search_offsets
            if (
                candidate := self.memory.u32(
                    allocation + offset,
                    "VS actor candidate",
                )
            ) in active
            and candidate != 0
        }
        if len(actor_matches) != 1:
            raise MenuReadError(
                f"VS actor match count is {len(actor_matches)}"
            )
        actor = actor_matches.pop()
        fight_pokemon = actor + p.vs_fight_pokemon_embedded_offset
        require_range(
            fight_pokemon,
            p.embedded_pokemon_offset + p.pokemon_moves_offset
            + p.move_slot_count * p.pokemon_move_stride,
            "VS embedded FightPokemon",
            p,
            alignment=4,
        )
        actor_name = self.memory.gschar(
            fight_pokemon + p.nickname_offset,
            p.maximum_nickname_chars,
            "VS actor nickname",
            2,
        )
        if not actor_name.strip():
            raise MenuReadError("VS actor nickname is empty")
        pokemon = fight_pokemon + p.embedded_pokemon_offset
        moves = []
        for slot, button in enumerate(p.vs_move_buttons):
            record = (
                allocation + p.vs_move_record_base
                + slot * p.vs_move_record_stride
            )
            name_pointer = self.memory.u32(
                record + p.vs_move_record_name_offset,
                "VS move-name pointer",
            )
            maximum_pp = self.memory.u8(
                record + p.vs_move_record_max_pp_offset,
                "VS maximum PP",
            )
            current_pp = self.memory.u8(
                record + p.vs_move_record_current_pp_offset,
                "VS current PP",
            )
            pokemon_waza = (
                pokemon + p.pokemon_moves_offset
                + slot * p.pokemon_move_stride
            )
            move_id = self.memory.u16(
                pokemon_waza + p.pokemon_move_id_offset,
                "VS move ID",
            )
            pokemon_pp = self.memory.u8(
                pokemon_waza + p.pokemon_move_pp_offset,
                "VS PokemonWaza current PP",
            )
            if (
                name_pointer == 0 and maximum_pp == 0
                and current_pp == 0 and move_id == 0
            ):
                continue
            if move_id <= 0 or move_id > p.maximum_move_id:
                raise MenuReadError(
                    f"VS move ID {move_id} outside verified range"
                )
            if maximum_pp == 0 or current_pp > maximum_pp:
                raise MenuReadError(
                    f"VS invalid PP {current_pp}/{maximum_pp}"
                )
            if pokemon_pp != current_pp:
                raise MenuReadError(
                    f"VS PP disagreement menu={current_pp} "
                    f"pokemon={pokemon_pp}"
                )
            live_name = self.memory.gschar(
                name_pointer,
                p.maximum_move_name_chars,
                "VS live move name",
                1,
            )
            move_id, local_name = self._displayed_move(move_id, live_name)
            moves.append((
                button, local_name, current_pp, maximum_pp
            ))
        if not moves:
            raise MenuReadError("VS move panel has no populated moves")
        return VsButtonPanel(
            node.address, node.menu_id, allocation,
            actor, actor_name, tuple(moves)
        )

    def _target_facts(self):
        """Live level/status per nickname, or {} if the field cannot be
        read. Never raises: this is enrichment, and losing it must not cost
        the player the target name itself."""
        try:
            return self.target_facts.facts()
        except MemoryError as exc:
            self.logger.debug("TARGET FACTS unavailable: %s", exc)
            return {}

    def _target_detail(self, name, allocation, facts, label):
        """The clause describing one target: HP straight off the panel it
        is displayed in, level and status from the matching battler."""
        current, maximum = status_panel_hp(
            self.memory, self.profile, allocation, label)
        return target_detail(
            facts.get(normalize(name)), current, maximum)

    def story_target_focus(self, node, nodes):
        """Resolve menu 92 through its live selected target-item record."""
        p = self.profile
        work = self.memory.pointer(
            node.address + p.story_target_work_offset,
            p.story_target_item_stride * len(p.story_target_item_to_status),
            "story target item records",
            4,
        )
        selected_ids = []
        valid_ids = dict(p.story_target_item_to_status)
        for index in range(len(p.story_target_item_to_status)):
            record = work + index * p.story_target_item_stride
            flags = self.memory.u16(
                record + p.story_target_item_flags_offset,
                f"story target item {index} flags",
            )
            item_id = self.memory.u16(
                record + p.story_target_item_id_offset,
                f"story target item {index} ID",
            )
            if item_id not in valid_ids:
                raise MenuReadError(f"story target item ID {item_id} unsupported")
            if flags & p.story_target_selected_mask:
                selected_ids.append(item_id)
        if len(selected_ids) != 1:
            raise MenuReadError(
                f"story selected target-item count {len(selected_ids)}"
            )

        status_id = valid_ids[selected_ids[0]]
        status_matches = [item for item in nodes if item.menu_id == status_id]
        if len(status_matches) != 1:
            raise MenuReadError(
                f"story selected status panel {status_id} match count "
                f"{len(status_matches)}"
            )
        status_node = status_matches[0]
        allocation = self.memory.pointer(
            status_node.address + p.window_alloc_offset,
            p.status_allocation_size,
            "story selected status allocation",
            4,
        )
        name = self.memory.gschar(
            allocation,
            p.health_nickname_max_chars,
            "story selected target nickname",
            2,
        )
        if not name.strip():
            raise MenuReadError("story selected target nickname is empty")
        ownership = (
            "Player"
            if status_id in p.vs_player_status_window_ids else "Opponent"
        )
        detail = self._target_detail(
            name, allocation, self._target_facts(),
            "story selected target")
        return StoryTargetFocus(
            node.address, node.menu_id, allocation,
            selected_ids[0], name, ownership, detail,
        )

    def vs_target_panel(self, node, nodes):
        p = self.profile
        if self.vs_actor is None:
            raise MenuReadError("VS target screen lacks acting battler")
        names = {}
        allocations = {}
        for status_node in nodes:
            if status_node.menu_id not in (
                *p.vs_player_status_window_ids,
                p.vs_top_target_status_window_id,
                p.vs_bottom_target_status_window_id,
            ):
                continue
            allocation = self.memory.pointer(
                status_node.address + p.window_alloc_offset,
                (p.health_nickname_max_chars + 1) * 2,
                "VS status allocation",
                4,
            )
            name = self.memory.gschar(
                allocation,
                p.health_nickname_max_chars,
                "VS status nickname",
                2,
            )
            if not name.strip() or status_node.menu_id in names:
                raise MenuReadError(
                    "VS status nickname is empty or ambiguous"
                )
            names[status_node.menu_id] = name
            allocations[status_node.menu_id] = allocation
        actor_name = next(
            (
                name for menu_id, name in names.items()
                if menu_id in p.vs_player_status_window_ids
                and normalize(name) == normalize(self.vs_actor_name)
            ),
            None,
        )
        if actor_name is None:
            raise MenuReadError(
                "VS actor does not match a player status window"
            )
        teammate = next(
            (
                name for menu_id, name in names.items()
                if menu_id in p.vs_player_status_window_ids
                and normalize(name) != normalize(actor_name)
            ),
            None,
        )
        target_items = [
            ("D-pad up", names.get(p.vs_top_target_status_window_id)),
            ("D-pad down", teammate),
            ("D-pad right", names.get(p.vs_bottom_target_status_window_id)),
        ]
        by_name = {name: allocation
                   for menu_id, name in names.items()
                   for allocation in (allocations[menu_id],)}
        facts = self._target_facts()
        targets = tuple(
            (button, name,
             self._target_detail(
                 name, by_name[name], facts, "VS target"))
            for button, name in target_items
            if name is not None
        )
        if not targets:
            raise MenuReadError("VS target screen has no valid targets")
        return VsTargetPanel(
            node.address, node.menu_id, self.vs_actor, targets
        )

    def poll_once(self):
        try:
            nodes = self.walker.walk()
            supported_ids = set(self.profile.command_menu_ids) | set(
                self.profile.move_menu_ids
            )
            supported_ids.update(self.profile.move_teacher_menu_ids)
            supported_ids.add(self.profile.bag_action_menu_id)
            supported_ids.update(self.profile.bag_number_menu_ids)
            supported_ids.update((
                self.profile.nintendo_warning_menu_id,
                self.profile.title_menu_parent_id,
                self.profile.title_menu_id,
                self.profile.title_option_menu_id,
                *self.profile.new_game_confirmation_parent_ids,
                self.profile.new_game_confirmation_menu_id,
                self.profile.name_screen_parent_id,
                self.profile.name_list_menu_id,
                self.profile.name_keyboard_menu_id,
            ))
            # Menu 53 is the game's reusable two-choice Yes/No widget.  Its
            # parent identifies the caller, not the widget shape, and new
            # callers must not need another hardcoded parent ID.  Treat each
            # live immediate parent as structural support for this sample.
            supported_ids.update(
                nodes[index - 1].menu_id
                for index, node in enumerate(nodes)
                if index > 0
                and node.menu_id == self.profile.new_game_confirmation_menu_id
            )
            vs_node = None
            quick_battle_node = None
            challenge_node = None
            quick_confirm_node = None
            vs_button_node = None
            vs_target_node = None
            story_target_node = None
            ids = tuple(node.menu_id for node in nodes)
            for index, node in enumerate(nodes):
                direct_vs_parent = (
                    index > 0
                    and ids[index - 1] == self.profile.vs_button_parent_id
                    and ids[index + 1:] in (
                        (), self.profile.vs_button_child_ids
                    )
                )
                # The target screen's parent differs from the move-button
                # screen's in one of its two known (menu_id, parent) pairs
                # -- see profile.py's vs_target_menu_ids/vs_target_alt_
                # parent_id comment. Checked separately from
                # direct_vs_parent so the move-button screen's own
                # detection stays exactly as before.
                target_direct_parent = direct_vs_parent or (
                    index > 0
                    and ids[index - 1] == self.profile.vs_target_alt_parent_id
                    and ids[index + 1:] in (
                        (), self.profile.vs_button_child_ids
                    )
                )
                if (
                    node.menu_id == self.profile.vs_button_menu_id
                    and direct_vs_parent
                ):
                    vs_button_node = node
                if node.menu_id == self.profile.story_target_menu_id:
                    story_target_node = node
                if (
                    node.menu_id in self.profile.vs_target_menu_ids
                    and target_direct_parent
                ):
                    vs_target_node = node
                if (
                    node.menu_id == self.profile.vs_menu_id
                    and index > 0
                    and index == len(nodes) - 1
                    and nodes[index - 1].menu_id
                    == self.profile.vs_menu_parent_id
                ):
                    vs_node = node
                if (
                    node.menu_id == self.profile.quick_battle_menu_id
                    and index > 0
                    and index == len(nodes) - 1
                    and nodes[index - 1].menu_id
                    == self.profile.quick_battle_parent_id
                ):
                    quick_battle_node = node
                if (
                    node.menu_id == self.profile.challenge_menu_id
                    and index >= 2
                    and index == len(nodes) - 1
                    and tuple(
                        item.menu_id for item in nodes[index - 2:index]
                    ) == self.profile.challenge_menu_parent_ids
                ):
                    challenge_node = node
                if (
                    node.menu_id == self.profile.quick_confirm_menu_id
                    and index > 0
                    and index == len(nodes) - 1
                    and nodes[index - 1].menu_id
                    == self.profile.quick_confirm_parent_id
                ):
                    quick_confirm_node = node
            if vs_node is not None:
                supported_ids.update((
                    self.profile.vs_menu_parent_id,
                    self.profile.vs_menu_id,
                ))
            if quick_battle_node is not None:
                supported_ids.update((
                    self.profile.quick_battle_parent_id,
                    self.profile.quick_battle_menu_id,
                ))
            if challenge_node is not None:
                supported_ids.update((
                    *self.profile.challenge_menu_parent_ids,
                    self.profile.challenge_menu_id,
                ))
            if quick_confirm_node is not None:
                supported_ids.update((
                    self.profile.quick_confirm_parent_id,
                    self.profile.quick_confirm_menu_id,
                ))
            if vs_button_node is not None:
                supported_ids.update((
                    self.profile.vs_button_parent_id,
                    self.profile.vs_button_menu_id,
                    *self.profile.vs_button_child_ids,
                ))
            if story_target_node is not None:
                supported_ids.add(self.profile.story_target_menu_id)
            if vs_target_node is not None:
                supported_ids.update((
                    self.profile.vs_button_parent_id,
                    self.profile.vs_target_alt_parent_id,
                    *self.profile.vs_target_menu_ids,
                    *self.profile.vs_button_child_ids,
                ))
            present_unsupported = {
                node.menu_id
                for node in nodes
                if node.menu_id not in supported_ids
            }
            for menu_id in sorted(present_unsupported - self.unsupported):
                self.logger.debug("UNSUPPORTED MENU id=%d; silent", menu_id)
            self.unsupported = present_unsupported

            move_node = next(
                (n for n in nodes if n.menu_id in self.profile.move_menu_ids),
                None,
            )
            command_node = next(
                (n for n in nodes if n.menu_id in self.profile.command_menu_ids),
                None,
            )
            move_teacher_node = next(
                (n for n in nodes
                 if n.menu_id in self.profile.move_teacher_menu_ids),
                None,
            )
            bag_action_node = next(
                (n for n in nodes
                 if n.menu_id == self.profile.bag_action_menu_id),
                None,
            )
            bag_number_node = next(
                (n for n in nodes
                 if n.menu_id in self.profile.bag_number_menu_ids),
                None,
            )
            yes_no_node = next(
                (n for index, n in enumerate(nodes)
                 if n.menu_id
                 == self.profile.new_game_confirmation_menu_id
                 and index > 0),
                None,
            )
            # A shop's greeting ("Welcome! ...") opens the SAME generic
            # small-list cursor widget under the same parent ids as the
            # yes/no overlay above, but project-owner-confirmed live
            # (2026-07-30) to carry three items -- Buy/Sell/Quit -- not
            # two, and under a DIFFERENT cursor menu_id (89 observed, vs
            # yes/no's fixed 53) that yes_no_focus's 2-item assumption
            # rejects. Disambiguated from a real yes/no by the active
            # GSmsg prompt's own message ID rather than by the cursor's
            # own menu_id -- see shop_menu_message_ids's own comment in
            # profile.py for why the cursor id itself isn't a reliable
            # signal here.
            # The prompt text is resolved from `shop_messages` (the
            # real, derived `pocket_menu.fsys` local message table --
            # see shop_messages.py), NOT from `active_gsmsg_prompt()`'s
            # own title_messages/hardcoded-id lookup (that path is for
            # the DOL string catalog, a different, disjoint message-ID
            # source that doesn't contain shop text). `active_gsmsg_
            # prompt()` is still used here only for its message_id,
            # which is what shop_menu_node's own detection needs.
            shop_message_id, _ = self.active_gsmsg_prompt()
            shop_prompt_text = (
                self.shop_messages.resolve(shop_message_id)
                if self.shop_messages is not None else None
            ) or ""
            shop_menu_node = next(
                (n for index, n in enumerate(nodes)
                 if shop_message_id in self.profile.shop_menu_message_ids
                 and index > 0
                 and nodes[index - 1].menu_id
                 in self.profile.yes_no_confirmation_parent_ids),
                None,
            )
            name_list_node = next(
                (n for index, n in enumerate(nodes)
                 if n.menu_id == self.profile.name_list_menu_id
                 and index > 0
                 and nodes[index - 1].menu_id
                 == self.profile.name_screen_parent_id),
                None,
            )
            name_keyboard_node = next(
                (n for index, n in enumerate(nodes)
                 if n.menu_id == self.profile.name_keyboard_menu_id
                 and index > 0
                 and nodes[index - 1].menu_id
                 == self.profile.name_screen_parent_id),
                None,
            )
            title_status = self.memory.u32(
                self.profile.title_status_address, "title menu status"
            )
            health_safety_visible = any(
                node.menu_id == self.profile.nintendo_warning_menu_id
                for node in nodes
            )
            title_context = (
                title_status == self.profile.title_main_menu_status
            )
            title_node = next(
                (n for index, n in enumerate(nodes)
                 if title_context
                 and n.menu_id == self.profile.title_menu_id
                 and index > 0
                 and nodes[index - 1].menu_id
                 == self.profile.title_menu_parent_id),
                None,
            )
            title_option_node = next(
                (n for n in nodes
                 if title_context
                 and n.menu_id == self.profile.title_option_menu_id),
                None,
            )
            new_game_confirmation_node = next(
                (n for index, n in enumerate(nodes)
                 if title_context
                 and n.menu_id
                 == self.profile.new_game_confirmation_menu_id
                 and index >= 2
                 and tuple(
                     node.menu_id for node in nodes[index - 2:index]
                 ) == self.profile.new_game_confirmation_parent_ids),
                None,
            )
            focus = self.progress_notification_focus()
            if focus is None:
                focus = self.title_notification_focus(title_status)
            if focus is not None:
                pass
            elif health_safety_visible:
                focus = HealthSafetyFocus()
            elif new_game_confirmation_node is not None:
                focus = self.mapped_focus(
                    new_game_confirmation_node,
                    self.profile.new_game_confirmation_labels,
                )
            elif shop_menu_node is not None:
                shop_labels = (
                    self.profile.shop_coupon_menu_labels
                    if shop_message_id
                    in self.profile.shop_coupon_menu_message_ids
                    else self.profile.shop_menu_labels
                )
                base_focus = self.mapped_focus(
                    shop_menu_node, shop_labels
                )
                # Prepends the greeting text (when resolved) the same way
                # yes_no_focus already does for ordinary yes/no prompts
                # ("Would you like to save your progress? Yes") -- spoken
                # on every cursor move for consistency with that existing
                # pattern, not just the first.
                label = (
                    f"{shop_prompt_text} {base_focus.label}"
                    if shop_prompt_text else base_focus.label
                )
                focus = CommandFocus(
                    base_focus.work, base_focus.menu_id, base_focus.index,
                    label,
                )
            elif yes_no_node is not None:
                yes_no_index = nodes.index(yes_no_node)
                dialogue_prompt = (
                    yes_no_index > 0
                    and nodes[yes_no_index - 1].menu_id
                    == self.profile.dialogue_window_id
                )
                active_prompt_id, _active_prompt_text = self.active_gsmsg_prompt()
                # Day-Care choices use the ordinary dialogue parent (82),
                # but their text never reaches DialogueReader's page buffer.
                # This reader therefore owns both prompt and choice.
                daycare_prompt = (
                    active_prompt_id
                    in self.profile.daycare_choice_prompt_message_ids
                )
                global_save_prompt = (
                    active_prompt_id
                    in self.profile.global_save_prompt_message_ids
                )
                continue_prompt = (
                    active_prompt_id
                    == self.profile.continue_confirmation_message_id
                    or (
                        self.yes_no_prompt_key is not None
                        and self.yes_no_prompt_key[1]
                        == self.profile.continue_confirmation_message_id
                    )
                    or (
                        yes_no_index > 0
                        and nodes[yes_no_index - 1].menu_id == 52
                    )
                    or (
                        yes_no_index >= 2
                        and nodes[yes_no_index - 1].menu_id == 52
                        and nodes[yes_no_index - 2].menu_id
                        == self.profile.continue_summary_menu_id
                    )
                )
                focus = self.yes_no_focus(
                    yes_no_node,
                    include_prompt=(
                        not dialogue_prompt
                        or daycare_prompt
                        or global_save_prompt
                        or continue_prompt
                    ),
                    initial_prefix=(
                        self.continue_summary() if continue_prompt else ""
                    ),
                    repeat_prompt=continue_prompt,
                    prompt_override=(
                        _active_prompt_text if continue_prompt else None
                    ),
                )
                if continue_prompt and focus.label in ("Yes", "No"):
                    source = self.title_messages.get(
                        self.profile.continue_confirmation_message_id, "")
                    prompt_text = re.sub(r"\[[^]]+\]", " ", source)
                    prompt_text = " ".join(prompt_text.split()).strip()
                    if prompt_text:
                        focus = CommandFocus(
                            focus.work, focus.menu_id, focus.index,
                            f"{prompt_text} {focus.label}",
                        )
            elif (
                title_status == self.profile.title_press_start_status
                and self.memory.u32(
                    self.profile.title_start_status_address,
                    "title start status",
                ) == 1
                and not self.title_message_active(title_status)
            ):
                focus = TitleScreenFocus()
            elif title_option_node is not None:
                focus = self.title_option_focus(title_option_node)
            elif title_node is not None:
                focus = self.mapped_focus(
                    title_node, self.profile.title_menu_labels
                )

            elif name_keyboard_node is not None:
                focus = self.name_keyboard_focus(name_keyboard_node)
            elif name_list_node is not None:
                focus = self.mapped_focus(
                    name_list_node,
                    self.profile.name_list_labels,
                )
            elif move_teacher_node is not None:
                focus = self.move_teacher_focus(move_teacher_node)
            elif bag_action_node is not None:
                focus = self.bag_action_focus(bag_action_node)
            elif bag_number_node is not None:
                focus = self.bag_number_focus(bag_number_node)
            elif story_target_node is not None:
                focus = self.story_target_focus(story_target_node, nodes)
            elif move_node is not None:
                focus = self.move_focus(move_node)
            elif command_node is not None:
                focus = self.command_focus(command_node)
            elif vs_button_node is not None:
                focus = self.vs_button_panel(vs_button_node)
                self.vs_actor = focus.actor
                self.vs_actor_name = focus.actor_name
            elif vs_target_node is not None:
                focus = self.vs_target_panel(vs_target_node, nodes)
            elif quick_confirm_node is not None:
                focus = self.mapped_focus(
                    quick_confirm_node,
                    self.profile.quick_confirm_labels,
                )
            elif challenge_node is not None:
                focus = self.mapped_focus(
                    challenge_node,
                    self.profile.challenge_menu_labels,
                )
            elif quick_battle_node is not None:
                focus = self.direct_mapped_focus(
                    quick_battle_node,
                    self.profile.quick_battle_cursor,
                    self.profile.quick_battle_labels,
                )
            elif vs_node is not None:
                focus = self.mapped_focus(
                    vs_node, self.profile.vs_menu_labels
                )
            if focus is None:
                if self.identity is not None:
                    self.logger.debug("MENU CLOSED; speech re-armed")
                self.identity = None
                self.yes_no_prompt_key = None
                return
            previous_identity = self.identity
            if isinstance(focus, NotificationFocus):
                identity = ("title-notification", focus.message_id)
            elif isinstance(focus, HealthSafetyFocus):
                identity = ("health-safety", focus.label)
            elif isinstance(focus, TitleScreenFocus):
                identity = ("title-screen", focus.label)
            elif isinstance(focus, OptionFocus):
                identity = (
                    "title-option", focus.work, focus.menu_id,
                    focus.index, focus.value,
                )
            elif isinstance(focus, NameKeyboardFocus):
                identity = (
                    "name-keyboard", focus.work, focus.menu_id,
                    focus.index, focus.entered_name,
                )
            elif isinstance(focus, MoveFocus):
                identity = (
                    "move", focus.work, focus.menu_id,
                    focus.status, focus.slot,
                )
            elif isinstance(focus, VsButtonPanel):
                identity = (
                    "vs-moves", focus.work, focus.menu_id,
                    focus.allocation, focus.actor, focus.moves,
                )
            elif isinstance(focus, StoryTargetFocus):
                identity = ("story-target", focus.work, focus.target, focus.slot)
            elif isinstance(focus, VsTargetPanel):
                identity = (
                    "vs-targets", focus.work, focus.menu_id,
                    focus.actor, focus.targets,
                )
            else:
                identity = (
                    "command", focus.work, focus.menu_id, focus.index,
                )
            if identity == self.identity:
                return
            self.identity = identity
            if (
                isinstance(focus, NameKeyboardFocus)
                and isinstance(previous_identity, tuple)
                and len(previous_identity) == 5
                and previous_identity[0] == "name-keyboard"
                and previous_identity[4] != focus.entered_name
            ):
                current = focus.entered_name if focus.entered_name else "blank"
                text = f"Name: {current}"
            else:
                text = (
                    focus.speech
                    if isinstance(focus, (MoveFocus, VsButtonPanel, VsTargetPanel, StoryTargetFocus, OptionFocus, NameKeyboardFocus))
                    else focus.label
                )
            if (
                isinstance(focus, CommandFocus)
                and focus.menu_id == self.profile.new_game_confirmation_menu_id
                and isinstance(previous_identity, tuple)
                and len(previous_identity) >= 4
                and previous_identity[0] == "command"
                and previous_identity[1:3] == (focus.work, focus.menu_id)
            ):
                text = ("Yes", "No")[focus.index]
            self.logger.info(text)
            self.logger.debug("MENU FOCUS %r", focus)
            if (
                isinstance(focus, CommandFocus)
                and focus.menu_id == self.profile.new_game_confirmation_menu_id
            ):
                self.speech.emit(
                    SpeechEventClass.MENU_FOCUS, text, interrupt=False
                )
            else:
                self.speech.emit(SpeechEventClass.MENU_FOCUS, text)
        except MemoryError as exc:
            self.logger.debug("MENU SAMPLE REJECTED: %s", exc)
            if isinstance(exc, GameDataMismatch):
                self._warn_game_data_mismatch(exc)
            self.identity = None

    def _warn_game_data_mismatch(self, exc):
        """Say once why the move menu has gone quiet.

        Every other rejection is a transient worth waiting out, so the
        reader stays silent about them. This one never resolves on its
        own, and its symptom -- most moves silent, the occasional one
        read normally -- gives the player nothing to act on. Spoken once
        per session rather than per poll, because it repeats at the poll
        rate for as long as the menu is open."""
        if getattr(self, "_game_data_mismatch_warned", False):
            return
        self._game_data_mismatch_warned = True
        self.logger.warning("GAME DATA MISMATCH: %s", exc)
        self.speech.emit(
            SpeechEventClass.WARNING, GAME_DATA_MISMATCH_ADVICE,
            interrupt=False,
        )

















