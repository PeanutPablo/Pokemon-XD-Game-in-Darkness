import io
import logging
import unittest
from types import SimpleNamespace
from dataclasses import replace

from battle_narrator import battle_opcodes, message_render
from battle_narrator.memory import MemoryReader
from battle_narrator.message_render import MessageRenderer
from battle_narrator.party import PartySlot
from battle_narrator.runtime_messages import RuntimeMessageCatalog
from battle_narrator.phase1b_lifecycle import LifecycleController
from battle_narrator.menus import (
    MenuReadError,
    ProductionMenuReader,
    WindowListWalker,
)
from battle_narrator.profile import XD_US_REV0
from battle_narrator.speech import SpeechCoordinator, SpeechEventClass


def be16(value):
    return value.to_bytes(2, "big")


def be32(value):
    return value.to_bytes(4, "big")


def gschar(value):
    return b"".join(be16(ord(char)) for char in value) + b"\0\0"


class Backend:
    def __init__(self):
        self.data = {}

    def put(self, address, value):
        for offset, byte in enumerate(value):
            self.data[address + offset] = byte

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + i, 0) for i in range(size))


class MoveData:
    def __init__(self, names=None):
        self.names = names or {
            89: "EARTHQUAKE",
            349: "DRAGON DANCE",
            280: "BRICK BREAK",
            337: "DRAGON CLAW",
        }

    def resolve(self, move_id):
        return self.names[move_id], "!"

    def find_id(self, move_name, maximum=None):
        matches = [
            move_id for move_id, name in self.names.items()
            if (maximum is None or move_id <= maximum)
            and name.casefold() == move_name.casefold()
        ]
        return matches[0] if len(matches) == 1 else None

    def details(self, move_id):
        values = {
            89: ("Ground", 100, 100), 349: ("Dragon", 0, 0),
            280: ("Fighting", 75, 100), 337: ("Dragon", 80, 100),
            356: ("Shadow", 0, 100),
        }
        type_name, power, accuracy = values[move_id]
        role = f"power {power}" if power else "status move"
        accuracy_text = f"{accuracy} percent accuracy" if accuracy else "does not use a standard accuracy check"
        return SimpleNamespace(type_name=type_name, power=power, accuracy=accuracy, description=f"{type_name}-type {role}, {accuracy_text}")


class Events:
    def __init__(self):
        self.values = []

    def emit(self, kind, text, deduplicate=False, **kwargs):
        self.values.append((kind, text))
        return True


class Speaker:
    def __init__(self):
        self.values = []

    def speak(self, text, interrupt=False):
        self.values.append((text, interrupt))
        return True


def logger():
    value = logging.getLogger(f"phase1e-{id(object())}")
    value.handlers.clear()
    value.addHandler(logging.StreamHandler(io.StringIO()))
    value.setLevel(logging.DEBUG)
    return value


class Fixture:
    def __init__(self, profile=XD_US_REV0):
        self.profile = profile
        self.backend = Backend()
        self.memory = MemoryReader(self.backend, profile)
        self.events = Events()
        self.reader = ProductionMenuReader(
            self.memory, profile, MoveData(), self.events, logger()
        )
        self.work = 0x80002000
        self.status = 0x80003000
        self.actor = 0x80004000
        self.fight = 0x80005000

    def head(self, pointer):
        self.backend.put(
            self.profile.window_manager + self.profile.window_list_offset,
            be32(pointer),
        )

    def node(self, address, menu_id, next_pointer=0, cursor=0, base=0):
        p = self.profile
        self.backend.put(address + p.window_menu_id_offset, be32(menu_id))
        self.backend.put(address + p.window_next_offset, be32(next_pointer))
        self.backend.put(
            address + p.window_cursor_base_offset, be16(base & 0xFFFF)
        )
        self.backend.put(
            address + p.window_cursor_offset, be16(cursor & 0xFFFF)
        )

    def command(self, cursor=0):
        self.head(self.work)
        self.node(self.work, 58, cursor=cursor)

    def move(self, cursor=0, names=None, current_pp=None):
        p = self.profile
        self.head(self.work)
        self.node(self.work, 57, cursor=cursor)
        self.backend.put(self.work + p.window_alloc_offset, be32(self.status))
        self.backend.put(
            self.status + p.move_status_actor_offset, be32(self.actor)
        )
        self.backend.put(
            self.actor + p.fight_out_pokemon_offset, be32(self.fight)
        )
        move_ids = (89, 349, 280, 337)
        move_names = names or (
            "EARTHQUAKE",
            "DRAGON DANCE",
            "BRICK BREAK",
            "DRAGON CLAW",
        )
        pps = current_pp or (10, 20, 15, 15)
        maximum = (10, 20, 15, 15)
        pokemon = self.fight + p.embedded_pokemon_offset
        for slot, (move_id, name, pp, max_pp) in enumerate(
            zip(move_ids, move_names, pps, maximum)
        ):
            record = (
                self.status
                + p.move_record_base
                + slot * p.move_record_stride
            )
            name_address = 0x80006001 + slot * 0x100
            type_address = 0x80007001 + slot * 0x100
            self.backend.put(record, be32(name_address))
            self.backend.put(record + 4, be32(type_address))
            self.backend.put(record + 8, be16(slot + 1))
            self.backend.put(record + 10, bytes((max_pp, pp)))
            self.backend.put(name_address, gschar(name))
            self.backend.put(type_address, gschar("TYPE"))
            waza = pokemon + p.pokemon_moves_offset + slot * 4
            self.backend.put(waza, be16(move_id) + bytes((pp, 0)))


    def vs_moves(self, invalid_pp=False):
        p=self.profile
        addresses=[self.work+i*0x100 for i in range(4)]
        ids=(p.vs_button_parent_id,p.vs_button_menu_id,
             *p.vs_button_child_ids)
        self.head(addresses[0])
        for index,(address,menu_id) in enumerate(zip(addresses,ids)):
            next_pointer=addresses[index+1] if index+1<len(addresses) else 0
            self.node(address,menu_id,next_pointer)
        move_node=addresses[1]
        self.backend.put(move_node+p.window_alloc_offset,be32(self.status))
        self.fight=self.actor+p.vs_fight_pokemon_embedded_offset
        self.backend.put(self.status+p.vs_move_actor_offset,be32(self.actor))
        self.backend.put(self.actor+p.fight_out_pokemon_offset,be32(self.fight))
        active=p.fight_floor_root+p.active_battler_array_offset
        self.backend.put(active+2*4,be32(self.actor))
        self.backend.put(self.fight+p.nickname_offset,gschar("SALAMENCE"))
        move_ids=(89,349,280,337)
        move_names=("EARTHQUAKE","DRAGON DANCE","BRICK BREAK","DRAGON CLAW")
        maximum=(10,20,15,15); current=(10,20,15,15)
        pokemon=self.fight+p.embedded_pokemon_offset
        for slot,(move_id,name,max_pp,pp) in enumerate(
                zip(move_ids,move_names,maximum,current)):
            record=(self.status+p.vs_move_record_base+
                    slot*p.vs_move_record_stride)
            name_address=0x80006001+slot*0x100
            self.backend.put(record+p.vs_move_record_name_offset,
                             be32(name_address))
            self.backend.put(name_address,gschar(name))
            values=(max_pp, max_pp+1) if invalid_pp and slot==0 else (max_pp,pp)
            self.backend.put(record+p.vs_move_record_max_pp_offset,
                             bytes(values))
            waza=pokemon+p.pokemon_moves_offset+slot*p.pokemon_move_stride
            self.backend.put(waza,be16(move_id)+bytes((pp,0)))
        return addresses

    def vs_targets(self, addresses, occupied=(0,1,2,3), with_hp=False):
        p=self.profile
        self.node(addresses[1],p.vs_target_menu_ids[0],addresses[2])
        statuses=(
            (0,p.vs_player_status_window_ids[1],"RAIKOU"),
            (1,p.vs_top_target_status_window_id,"LATIOS"),
            (2,p.vs_player_status_window_ids[0],"SALAMENCE"),
            (3,p.vs_bottom_target_status_window_id,"KANGASKHAN"),
        )
        hp_for_name={"RAIKOU":(90,150),"LATIOS":(41,160),
                     "SALAMENCE":(142,171),"KANGASKHAN":(0,170)}
        present=[item for item in statuses if item[0] in occupied]
        status_nodes=[0x80001000+i*0x100 for i in range(len(present))]
        if status_nodes:
            self.head(status_nodes[0])
        else:
            self.head(addresses[0])
        for index,((slot,menu_id,name),work) in enumerate(
                zip(present,status_nodes)):
            next_pointer=(
                status_nodes[index+1]
                if index+1<len(status_nodes) else addresses[0]
            )
            self.node(work,menu_id,next_pointer)
            allocation=0x8000A000+slot*0x100
            self.backend.put(work+p.window_alloc_offset,be32(allocation))
            self.backend.put(allocation,gschar(name))
            if with_hp:
                current,maximum=hp_for_name[name]
                self.backend.put(allocation+p.status_max_hp_offset,
                                 be16(maximum)+be16(current))


class VsButtonBattleTests(unittest.TestCase):
    def test_move_buttons_and_pp_are_spoken_once(self):
        f=Fixture(); f.vs_moves(); f.reader.poll_once(); f.reader.poll_once()
        self.assertEqual([value[1] for value in f.events.values],[
            "Salamence moves. C-stick up, Earthquake, 10/10 P P. "
            "C-stick right, Dragon Dance, 20/20 P P. "
            "C-stick down, Brick Break, 15/15 P P. "
            "C-stick left, Dragon Claw, 15/15 P P."
        ])

    def test_invalid_pp_and_incorrect_nesting_are_silent(self):
        f=Fixture(); f.vs_moves(invalid_pp=True); f.reader.poll_once()
        self.assertEqual(f.events.values,[])
        f=Fixture(); addresses=f.vs_moves()
        f.node(addresses[0],999,addresses[1]); f.reader.poll_once()
        self.assertEqual(f.events.values,[])

    def test_live_variant_with_decorative_windows_before_direct_pair(self):
        f=Fixture(); addresses=f.vs_moves()
        p=f.profile
        f.head(addresses[2])
        f.node(addresses[2],p.vs_button_child_ids[0],addresses[3])
        f.node(addresses[3],p.vs_button_child_ids[1],addresses[0])
        f.node(addresses[0],p.vs_button_parent_id,addresses[1])
        f.node(addresses[1],p.vs_button_menu_id)
        f.reader.poll_once()
        self.assertIn("C-stick up, Earthquake",f.events.values[-1][1])

    def test_unverified_deeper_child_suppresses(self):
        f=Fixture(); addresses=f.vs_moves()
        deeper=addresses[-1]+0x100
        f.node(addresses[-1],f.profile.vs_button_child_ids[-1],deeper)
        f.node(deeper,999)
        f.reader.poll_once(); self.assertEqual(f.events.values,[])

    def test_target_buttons_use_live_battler_names(self):
        f=Fixture(); addresses=f.vs_moves(); f.reader.poll_once()
        f.vs_targets(addresses); f.reader.poll_once(); f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1],
            "Targets. D-pad up, Latios. D-pad down, Raikou. D-pad right, Kangaskhan.")

    def test_empty_target_slot_is_omitted(self):
        f=Fixture(); addresses=f.vs_moves(); f.reader.poll_once()
        f.vs_targets(addresses,occupied=(1,2,3)); f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1],
            "Targets. D-pad up, Latios. D-pad right, Kangaskhan.")

    def test_targets_carry_hp_from_their_own_status_panels(self):
        # Without an HP bar to look at, a bare name cannot be chosen
        # between. Each target's HP comes from the panel the game is
        # displaying it in -- no name matching -- so a KO'd target is
        # named as one.
        f=Fixture(); addresses=f.vs_moves(); f.reader.poll_once()
        f.vs_targets(addresses,with_hp=True)
        f.reader.poll_once(); f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1],
            "Targets. D-pad up, Latios, 41 of 160 HP, 26 percent. "
            "D-pad down, Raikou, 90 of 150 HP, 60 percent. "
            "D-pad right, Kangaskhan, 0 of 170 HP, zero percent, fainted.")

    def test_target_without_prior_actor_is_silent(self):
        f=Fixture(); addresses=f.vs_moves(); f.vs_targets(addresses)
        f.reader.poll_once(); self.assertEqual(f.events.values,[])

    def test_close_reopen_rearms_move_panel(self):
        f=Fixture(); f.vs_moves(); f.reader.poll_once()
        f.head(0); f.reader.poll_once()
        f.vs_moves(); f.reader.poll_once()
        self.assertEqual(len(f.events.values),2)


class WalkerTests(unittest.TestCase):
    def test_bounded_traversal(self):
        profile = replace(XD_US_REV0, window_max_nodes=2)
        f = Fixture(profile)
        f.head(0x80002000)
        f.node(0x80002000, 1, 0x80002100)
        f.node(0x80002100, 2, 0x80002200)
        f.node(0x80002200, 3)
        with self.assertRaisesRegex(MenuReadError, "exceeds"):
            WindowListWalker(f.memory, profile).walk()

    def test_cycle_detection(self):
        f = Fixture()
        f.head(f.work)
        f.node(f.work, 58, f.work)
        with self.assertRaisesRegex(MenuReadError, "cycle"):
            f.reader.walker.walk()

    def test_invalid_node(self):
        f = Fixture()
        f.head(0x70000000)
        with self.assertRaises(MenuReadError):
            f.reader.walker.walk()


class CommandTests(unittest.TestCase):
    def test_open_all_indices_and_unchanged_dedup(self):
        f = Fixture()
        expected = ["Fight", "Item", "Pokemon", "Call"]
        for index, label in enumerate(expected):
            f.command(index)
            f.reader.poll_once()
            self.assertEqual(f.events.values[-1][1], label)
            before = len(f.events.values)
            f.reader.poll_once()
            self.assertEqual(len(f.events.values), before)

    def test_close_reopen_rearms(self):
        f = Fixture()
        f.command()
        f.reader.poll_once()
        f.head(0)
        f.reader.poll_once()
        f.command()
        f.reader.poll_once()
        self.assertEqual([x[1] for x in f.events.values], ["Fight", "Fight"])


class StoryTargetTests(unittest.TestCase):
    # Level and major status live on the BATTLER record, not on the status
    # panel, so they are the half of a target's description that has to be
    # matched by nickname. Populated here so the tests cover that path.
    TARGET_LEVELS = {"JOLTEON": 25, "TEDDIURSA": 11, "WINGULL": 14}
    TARGET_CONDITIONS = {"WINGULL": 5}

    def _target_screen(self, f, cursor, actor_name="JOLTEON",
                       opponent_top="WURMPLE"):
        p = f.profile
        target = f.work + 4 * 0x100
        panel_data = (
            (p.vs_player_status_window_ids[1], "TEDDIURSA", 28, 42),
            (p.vs_player_status_window_ids[0], "JOLTEON", 44, 46),
            (p.vs_top_target_status_window_id, opponent_top, 27, 27),
            (p.vs_bottom_target_status_window_id, "WINGULL", 26, 26),
        )
        nodes = [f.work + index * 0x100 for index in range(5)]
        f.head(nodes[0])
        actor_pointer = 0x80010000
        for index, (menu_id, name, hp, maximum) in enumerate(panel_data):
            address = nodes[index]
            allocation = 0x80020000 + index * 0x100
            f.node(address, menu_id, next_pointer=nodes[index + 1])
            f.backend.put(address + p.window_alloc_offset, be32(allocation))
            f.backend.put(allocation, gschar(name))
            f.backend.put(
                allocation + p.status_max_hp_offset,
                be16(maximum) + be16(hp),
            )
            if name == actor_name:
                f.reader.story_actor = actor_pointer
                f.backend.put(
                    actor_pointer + p.health_nickname_offset, gschar(name)
                )
                pokemon = actor_pointer + p.fight_pokemon_embedded_offset
                f.backend.put(
                    pokemon + p.pokemon_current_hp_offset, be16(hp)
                )
                f.backend.put(
                    pokemon + p.pokemon_max_hp_offset, be16(maximum)
                )
        # Menu cursor values are deliberately not used as target identities.
        # The game publishes the selected FightPokemon directly.
        slot_for_name = {
            "JOLTEON": 0,
            opponent_top: 1,
            "TEDDIURSA": 2,
            "WINGULL": 3,
        }
        fight_pokemon_for_name = {}
        active_base = p.fight_floor_root + p.active_battler_array_offset
        for name, slot in slot_for_name.items():
            fight_out = 0x80100000 + slot * 0x1000
            fight_pokemon = 0x80200000 + slot * 0x1000
            f.backend.put(active_base + slot * 4, be32(fight_out))
            f.backend.put(
                fight_out + p.fight_out_fight_pokemon_offset,
                be32(fight_pokemon),
            )
            f.backend.put(
                fight_pokemon + p.health_nickname_offset,
                gschar(name),
            )
            pokemon = fight_pokemon + p.fight_pokemon_embedded_offset
            f.backend.put(
                pokemon + p.pokemon_level_offset,
                bytes((self.TARGET_LEVELS.get(name, 20),)),
            )
            f.backend.put(
                pokemon + p.pokemon_condition_offset,
                bytes((self.TARGET_CONDITIONS.get(name, 0),)),
            )
            fight_pokemon_for_name[name] = fight_pokemon
        eligible = [
            name for name in ("TEDDIURSA", opponent_top, "WINGULL")
            if name != actor_name
        ] if actor_name == "JOLTEON" else [
            "JOLTEON", opponent_top, "WINGULL"
        ]
        selected = (
            fight_pokemon_for_name[eligible[cursor]]
            if 0 <= cursor < len(eligible) else 0
        )
        f.backend.put(p.story_target_fight_pokemon_ptr, be32(selected))
        f.node(target, p.story_target_menu_id, cursor=cursor)
        work = 0x80300000
        f.backend.put(target + p.story_target_work_offset, be32(work))
        status_for_name = {name: menu_id for menu_id, name, _hp, _max in panel_data}
        selected_status = (
            status_for_name[eligible[cursor]]
            if 0 <= cursor < len(eligible) else None
        )
        for index, (item_id, status_id) in enumerate(
            p.story_target_item_to_status
        ):
            record = work + index * p.story_target_item_stride
            flags = 0x0708 if status_id == selected_status else 0x0508
            f.backend.put(
                record + p.story_target_item_flags_offset,
                be16(flags) + be16(item_id),
            )

    def test_jolteon_buttons_follow_live_panel_order_without_actor(self):
        expected = (
            "Target: Player Teddiursa, level 11, 28 of 42 HP, 67 percent.",
            "Target: Opponent Wurmple, level 20, 27 of 27 HP, 100 percent.",
            "Target: Opponent Wingull, level 14, 26 of 26 HP, 100 percent, "
            "paralyzed.",
        )
        for cursor, speech in enumerate(expected):
            with self.subTest(cursor=cursor):
                f = Fixture(); self._target_screen(f, cursor)
                f.reader.poll_once()
                self.assertEqual(f.events.values[-1][1], speech)

    def test_teddiursa_buttons_change_by_removing_teddiursa_panel(self):
        expected = (
            "Target: Player Jolteon, level 25, 44 of 46 HP, 96 percent.",
            "Target: Opponent Wurmple, level 20, 27 of 27 HP, 100 percent.",
            "Target: Opponent Wingull, level 14, 26 of 26 HP, 100 percent, "
            "paralyzed.",
        )
        for cursor, speech in enumerate(expected):
            with self.subTest(cursor=cursor):
                f = Fixture()
                self._target_screen(f, cursor, actor_name="TEDDIURSA")
                f.reader.poll_once()
                self.assertEqual(f.events.values[-1][1], speech)

    def test_replacement_spoink_keeps_opponent_panel_ownership(self):
        f = Fixture()
        self._target_screen(f, 1, opponent_top="SPOINK")
        f.reader.poll_once()
        self.assertEqual(
            f.events.values[-1][1],
            "Target: Opponent Spoink, level 20, 27 of 27 HP, 100 percent."
        )

    def test_selected_item_flag_overrides_disagreeing_cursor_fields(self):
        f = Fixture(); self._target_screen(f, 0)
        p = f.profile; work = 0x80300000
        for index, (item_id, _status_id) in enumerate(
            p.story_target_item_to_status
        ):
            flags = 0x0708 if item_id == 315 else 0x0508
            record = work + index * p.story_target_item_stride
            f.backend.put(
                record + p.story_target_item_flags_offset,
                be16(flags) + be16(item_id),
            )
        f.reader.poll_once()
        self.assertEqual(
            f.events.values[-1][1],
            "Target: Opponent Wingull, level 14, 26 of 26 HP, 100 percent, "
            "paralyzed."
        )
    def test_ambiguous_actor_panel_is_silent(self):
        f = Fixture(); self._target_screen(f, 3)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

class MoveTests(unittest.TestCase):
    def test_open_and_all_four_slots(self):
        f = Fixture()
        expected = [
            "Earthquake, 10/10 P P. Ground-type power 100, 100 percent accuracy.",
            "Dragon Dance, 20/20 P P. Dragon-type status move, does not use a standard accuracy check.",
            "Brick Break, 15/15 P P. Fighting-type power 75, 100 percent accuracy.",
            "Dragon Claw, 15/15 P P. Dragon-type power 80, 100 percent accuracy.",
        ]
        for slot, text in enumerate(expected):
            f.move(slot)
            f.reader.poll_once()
            self.assertEqual(f.events.values[-1][1], text)

    def test_name_disagreement_is_suppressed(self):
        """The move is never announced when the two readings disagree.

        Unchanged guarantee, and the important one: speaking the local
        name would mean saying "MEGA PUNCH" for Zen Headbutt. What is new
        is that the reader now also says, once, WHY it went quiet -- see
        test_game_data_mismatch.py. So the assertion is that no MENU_FOCUS
        was emitted, not that nothing at all was."""
        f = Fixture()
        f.move(names=("WRONG", "DRAGON DANCE", "BRICK BREAK", "DRAGON CLAW"))
        f.reader.poll_once()
        focus = [
            event for event in f.events.values
            if event[0] is SpeechEventClass.MENU_FOCUS
        ]
        self.assertEqual(focus, [])
        self.assertEqual(
            [event[0] for event in f.events.values],
            [SpeechEventClass.WARNING])

    def test_shadow_menu_name_resolves_its_displayed_move_id(self):
        """The embedded ordinary ID must not hide a live Shadow override."""
        f = Fixture()
        f.reader.move_data.names[356] = "SHADOW STEALTH"
        f.move(names=(
            "SHADOW STEALTH", "DRAGON DANCE", "BRICK BREAK", "DRAGON CLAW"
        ))
        f.reader.poll_once()
        self.assertEqual(
            f.events.values[-1][1],
            "Shadow Stealth, 10/10 P P. Shadow-type status move, "
            "100 percent accuracy.",
        )

    def test_empty_record_is_never_spoken(self):
        f = Fixture()
        f.head(f.work)
        f.node(f.work, 57)
        f.backend.put(f.work + f.profile.window_alloc_offset, be32(f.status))
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_zero_pp_is_spoken_without_invented_state(self):
        f = Fixture()
        f.move(current_pp=(0, 20, 15, 15))
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "Earthquake, 0/10 P P. Ground-type power 100, 100 percent accuracy.")

    def test_close_reopen_rearms(self):
        f = Fixture()
        f.move()
        f.reader.poll_once()
        f.head(0)
        f.reader.poll_once()
        f.move()
        f.reader.poll_once()
        self.assertEqual(len(f.events.values), 2)

    def test_command_to_move_transition(self):
        f = Fixture()
        f.command()
        f.reader.poll_once()
        f.move()
        f.reader.poll_once()
        self.assertEqual(
            [x[1] for x in f.events.values],
            ["Fight", "Earthquake, 10/10 P P. Ground-type power 100, 100 percent accuracy."],
        )

    def test_clear_rearms_after_disconnect(self):
        f = Fixture()
        f.move()
        f.reader.poll_once()
        f.reader.clear("disconnect")
        f.reader.poll_once()
        self.assertEqual(len(f.events.values), 2)

    def test_unsupported_menu_is_silent(self):
        f = Fixture()
        f.head(f.work)
        f.node(f.work, 999)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])


class VsMenuTests(unittest.TestCase):
    def open_vs(self, f, cursor=0, base=0, parent=None, child=None):
        parent = parent or f.work
        child = child or f.work + 0x100
        f.head(parent)
        f.node(parent, 281, next_pointer=child)
        f.node(child, 280, cursor=cursor, base=base)
        return parent, child

    def test_verified_context_and_every_option(self):
        expected = ["Quick Battle", "Group Battle", "Cancel"]
        for index, label in enumerate(expected):
            with self.subTest(index=index):
                f = Fixture()
                self.open_vs(f, base=index + 1, cursor=-1)
                f.reader.poll_once()
                self.assertEqual([x[1] for x in f.events.values], [label])

    def test_initial_focus_and_unchanged_dedup(self):
        f = Fixture()
        self.open_vs(f)
        f.reader.poll_once()
        f.reader.poll_once()
        self.assertEqual([x[1] for x in f.events.values], ["Quick Battle"])

    def test_focus_movement(self):
        f = Fixture()
        _parent, child = self.open_vs(f)
        f.reader.poll_once()
        f.node(child, 280, cursor=1)
        f.reader.poll_once()
        f.node(child, 280, cursor=2)
        f.reader.poll_once()
        self.assertEqual(
            [x[1] for x in f.events.values],
            ["Quick Battle", "Group Battle", "Cancel"],
        )

    def test_out_of_range_cursor_is_suppressed(self):
        for cursor in (-1, 3):
            with self.subTest(cursor=cursor):
                f = Fixture()
                self.open_vs(f, cursor=cursor)
                f.reader.poll_once()
                self.assertEqual(f.events.values, [])

    def test_nested_vs_context_has_priority_over_reused_title_id(self):
        f = Fixture()
        title = f.work
        reused = title + 0x100
        parent = title + 0x200
        child = title + 0x300
        f.head(title)
        f.node(title, 17, next_pointer=reused)
        f.node(reused, 278, next_pointer=parent)
        f.node(parent, 281, next_pointer=child)
        f.node(child, 280, cursor=1)
        f.reader.poll_once()
        self.assertEqual([x[1] for x in f.events.values], ["Group Battle"])

    def test_close_reopen_rearms_initial_focus(self):
        f = Fixture()
        self.open_vs(f)
        f.reader.poll_once()
        f.head(0)
        f.reader.poll_once()
        self.open_vs(f)
        f.reader.poll_once()
        self.assertEqual(
            [x[1] for x in f.events.values],
            ["Quick Battle", "Quick Battle"],
        )

    def test_title_and_options_reused_ids_are_silent(self):
        for menu_id in (278, 279):
            with self.subTest(menu_id=menu_id):
                f = Fixture()
                f.head(f.work)
                f.node(f.work, menu_id)
                f.reader.poll_once()
                self.assertEqual(f.events.values, [])

    def test_missing_parent_is_suppressed(self):
        f = Fixture()
        f.head(f.work)
        f.node(f.work, 280)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_missing_child_is_suppressed(self):
        f = Fixture()
        f.head(f.work)
        f.node(f.work, 281)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_incorrect_nesting_is_suppressed(self):
        f = Fixture()
        child = f.work + 0x100
        f.head(f.work)
        f.node(f.work, 280, next_pointer=child)
        f.node(child, 281)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_ambiguous_separated_ids_are_suppressed(self):
        f = Fixture()
        middle = f.work + 0x100
        child = f.work + 0x200
        f.head(f.work)
        f.node(f.work, 281, next_pointer=middle)
        f.node(middle, 999, next_pointer=child)
        f.node(child, 280)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

class QuickBattleMenuTests(unittest.TestCase):
    def open_menu(self, f, cursor=0, parent=None, child=None):
        parent = parent or f.work
        child = child or f.work + 0x100
        f.head(parent)
        f.node(parent, f.profile.quick_battle_parent_id, next_pointer=child)
        f.node(child, f.profile.quick_battle_menu_id)
        f.backend.put(f.profile.quick_battle_cursor, bytes((cursor,)))
        return parent, child

    def test_verified_context_and_every_option(self):
        expected = ["Battle VS CPU", "2-Player Battle", "Cancel"]
        for index, label in enumerate(expected):
            with self.subTest(index=index):
                f = Fixture()
                self.open_menu(f, index)
                f.reader.poll_once()
                self.assertEqual([x[1] for x in f.events.values], [label])

    def test_initial_focus_and_unchanged_dedup(self):
        f = Fixture()
        self.open_menu(f)
        f.reader.poll_once()
        f.reader.poll_once()
        self.assertEqual([x[1] for x in f.events.values], ["Battle VS CPU"])

    def test_focus_movement(self):
        f = Fixture()
        self.open_menu(f)
        f.reader.poll_once()
        for cursor in (1, 2):
            f.backend.put(f.profile.quick_battle_cursor, bytes((cursor,)))
            f.reader.poll_once()
        self.assertEqual(
            [x[1] for x in f.events.values],
            ["Battle VS CPU", "2-Player Battle", "Cancel"],
        )

    def test_out_of_range_cursor_is_suppressed(self):
        for cursor in (3, 0xFF):
            with self.subTest(cursor=cursor):
                f = Fixture()
                self.open_menu(f, cursor)
                f.reader.poll_once()
                self.assertEqual(f.events.values, [])

    def test_close_reopen_rearms_initial_focus(self):
        f = Fixture()
        self.open_menu(f)
        f.reader.poll_once()
        f.head(0)
        f.reader.poll_once()
        self.open_menu(f)
        f.reader.poll_once()
        self.assertEqual(
            [x[1] for x in f.events.values],
            ["Battle VS CPU", "Battle VS CPU"],
        )

    def test_challenge_window_has_innermost_priority(self):
        f = Fixture()
        _parent, child = self.open_menu(f)
        downstream = child + 0x100
        f.node(child, f.profile.quick_battle_menu_id, next_pointer=downstream)
        f.node(downstream, 262)
        f.reader.poll_once()
        self.assertEqual([x[1] for x in f.events.values], ["Ultimate"])

    def test_missing_parent_is_suppressed(self):
        f = Fixture()
        f.head(f.work)
        f.node(f.work, f.profile.quick_battle_menu_id)
        f.backend.put(f.profile.quick_battle_cursor, b"\0")
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_missing_child_is_suppressed(self):
        f = Fixture()
        f.head(f.work)
        f.node(f.work, f.profile.quick_battle_parent_id)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_incorrect_nesting_is_suppressed(self):
        f = Fixture()
        child = f.work + 0x100
        f.head(f.work)
        f.node(
            f.work,
            f.profile.quick_battle_menu_id,
            next_pointer=child,
        )
        f.node(child, f.profile.quick_battle_parent_id)
        f.backend.put(f.profile.quick_battle_cursor, b"\0")
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_ambiguous_separated_ids_are_suppressed(self):
        f = Fixture()
        middle = f.work + 0x100
        child = f.work + 0x200
        f.head(f.work)
        f.node(
            f.work,
            f.profile.quick_battle_parent_id,
            next_pointer=middle,
        )
        f.node(middle, 999, next_pointer=child)
        f.node(child, f.profile.quick_battle_menu_id)
        f.backend.put(f.profile.quick_battle_cursor, b"\0")
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_reused_id_outside_context_is_suppressed(self):
        f = Fixture()
        outer = f.work
        reused = f.work + 0x100
        f.head(outer)
        f.node(outer, 17, next_pointer=reused)
        f.node(reused, f.profile.quick_battle_menu_id)
        f.backend.put(f.profile.quick_battle_cursor, b"\0")
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

class ChallengeLevelMenuTests(unittest.TestCase):
    def open_menu(self, f, cursor=0, base=0):
        parent = f.work
        quick = parent + 0x100
        challenge = parent + 0x200
        f.head(parent)
        f.node(parent, 281, next_pointer=quick)
        f.node(quick, 164, next_pointer=challenge)
        f.node(challenge, 262, cursor=cursor, base=base)
        return parent, quick, challenge

    def test_verified_context_and_every_option(self):
        expected = ["Ultimate", "Hard", "Normal", "Easy", "Cancel"]
        for index, label in enumerate(expected):
            with self.subTest(index=index):
                f = Fixture()
                self.open_menu(f, cursor=-1, base=index + 1)
                f.reader.poll_once()
                self.assertEqual([x[1] for x in f.events.values], [label])

    def test_initial_focus_and_unchanged_dedup(self):
        f = Fixture()
        self.open_menu(f)
        f.reader.poll_once()
        f.reader.poll_once()
        self.assertEqual([x[1] for x in f.events.values], ["Ultimate"])

    def test_focus_movement(self):
        f = Fixture()
        _parent, _quick, challenge = self.open_menu(f)
        for cursor in range(5):
            f.node(challenge, 262, cursor=cursor)
            f.reader.poll_once()
        self.assertEqual(
            [x[1] for x in f.events.values],
            ["Ultimate", "Hard", "Normal", "Easy", "Cancel"],
        )

    def test_invalid_cursor_is_suppressed(self):
        for cursor in (-1, 5):
            with self.subTest(cursor=cursor):
                f = Fixture()
                self.open_menu(f, cursor=cursor)
                f.reader.poll_once()
                self.assertEqual(f.events.values, [])

    def test_outer_quick_battle_is_suppressed(self):
        f = Fixture()
        self.open_menu(f)
        f.backend.put(f.profile.quick_battle_cursor, b"\x02")
        f.reader.poll_once()
        self.assertEqual([x[1] for x in f.events.values], ["Ultimate"])

    def test_close_reopen_rearms(self):
        f = Fixture()
        self.open_menu(f)
        f.reader.poll_once()
        f.head(0)
        f.reader.poll_once()
        self.open_menu(f)
        f.reader.poll_once()
        self.assertEqual(
            [x[1] for x in f.events.values],
            ["Ultimate", "Ultimate"],
        )

    def test_deeper_child_suppresses(self):
        f = Fixture()
        _parent, _quick, challenge = self.open_menu(f)
        deeper = challenge + 0x100
        f.node(challenge, 262, next_pointer=deeper)
        f.node(deeper, 999)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_missing_or_separated_nesting_is_suppressed(self):
        for ids in ((164, 262), (281, 262), (281, 999, 164, 262)):
            with self.subTest(ids=ids):
                f = Fixture()
                addresses = [
                    f.work + index * 0x100 for index in range(len(ids))
                ]
                f.head(addresses[0])
                for index, (address, menu_id) in enumerate(
                    zip(addresses, ids)
                ):
                    next_pointer = (
                        addresses[index + 1]
                        if index + 1 < len(addresses)
                        else 0
                    )
                    f.node(address, menu_id, next_pointer=next_pointer)
                f.reader.poll_once()
                self.assertEqual(f.events.values, [])

    def test_reversed_nesting_is_suppressed(self):
        f = Fixture()
        addresses = (f.work, f.work + 0x100, f.work + 0x200)
        f.head(addresses[0])
        f.node(addresses[0], 262, next_pointer=addresses[1])
        f.node(addresses[1], 164, next_pointer=addresses[2])
        f.node(addresses[2], 281)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_reused_262_outside_context_is_suppressed(self):
        f = Fixture()
        f.head(f.work)
        f.node(f.work, 262)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])


class QuickBattleConfirmationTests(unittest.TestCase):
    def open_menu(self, f, cursor=0, base=0):
        parent = f.work
        confirm = parent + 0x100
        f.head(parent)
        f.node(parent, 281, next_pointer=confirm)
        f.node(confirm, 165, cursor=cursor, base=base)
        return parent, confirm

    def test_verified_context_yes_and_no_signed_sum(self):
        for index, label in enumerate(("YES", "NO")):
            with self.subTest(index=index):
                f = Fixture()
                self.open_menu(f, cursor=-1, base=index + 1)
                f.reader.poll_once()
                self.assertEqual([x[1] for x in f.events.values], [label])

    def test_initial_focus_and_unchanged_dedup(self):
        f = Fixture()
        self.open_menu(f)
        f.reader.poll_once()
        f.reader.poll_once()
        self.assertEqual([x[1] for x in f.events.values], ["YES"])

    def test_focus_movement(self):
        f = Fixture()
        _parent, confirm = self.open_menu(f)
        f.reader.poll_once()
        f.node(confirm, 165, cursor=1)
        f.reader.poll_once()
        f.node(confirm, 165, cursor=0)
        f.reader.poll_once()
        self.assertEqual(
            [x[1] for x in f.events.values],
            ["YES", "NO", "YES"],
        )

    def test_invalid_cursor_is_suppressed(self):
        for cursor in (-1, 2):
            with self.subTest(cursor=cursor):
                f = Fixture()
                self.open_menu(f, cursor=cursor)
                f.reader.poll_once()
                self.assertEqual(f.events.values, [])

    def test_outer_menus_are_suppressed(self):
        f = Fixture()
        self.open_menu(f)
        f.backend.put(f.profile.quick_battle_cursor, b"\x02")
        f.reader.poll_once()
        self.assertEqual([x[1] for x in f.events.values], ["YES"])

    def test_close_reopen_rearms(self):
        f = Fixture()
        self.open_menu(f)
        f.reader.poll_once()
        f.head(0)
        f.reader.poll_once()
        self.open_menu(f)
        f.reader.poll_once()
        self.assertEqual(
            [x[1] for x in f.events.values],
            ["YES", "YES"],
        )

    def test_deeper_child_suppresses(self):
        f = Fixture()
        _parent, confirm = self.open_menu(f)
        deeper = confirm + 0x100
        f.node(confirm, 165, next_pointer=deeper)
        f.node(deeper, 999)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_missing_or_separated_nesting_is_suppressed(self):
        for ids in ((165,), (281, 999, 165)):
            with self.subTest(ids=ids):
                f = Fixture()
                addresses = [
                    f.work + index * 0x100 for index in range(len(ids))
                ]
                f.head(addresses[0])
                for index, (address, menu_id) in enumerate(
                    zip(addresses, ids)
                ):
                    next_pointer = (
                        addresses[index + 1]
                        if index + 1 < len(addresses)
                        else 0
                    )
                    f.node(address, menu_id, next_pointer=next_pointer)
                f.reader.poll_once()
                self.assertEqual(f.events.values, [])

    def test_reversed_nesting_is_suppressed(self):
        f = Fixture()
        parent = f.work
        child = parent + 0x100
        f.head(parent)
        f.node(parent, 165, next_pointer=child)
        f.node(child, 281)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_reused_165_outside_context_is_suppressed(self):
        f = Fixture()
        parent = f.work
        child = parent + 0x100
        f.head(parent)
        f.node(parent, 17, next_pointer=child)
        f.node(child, 165)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])


class TitleMenuTests(unittest.TestCase):
    def test_health_and_safety_warning_announces_once_when_visible(self):
        f = Fixture()
        f.head(f.work)
        f.node(f.work, f.profile.nintendo_warning_menu_id)
        f.reader.poll_once()
        f.reader.poll_once()
        self.assertEqual(len(f.events.values), 1)
        # Names the screen first, then reads it, then says what to do.
        said = f.events.values[0][1]
        self.assertIn("Health and safety notice", said)
        self.assertIn("Press any button to continue", said)

    def test_press_start_screen_announces_once_when_visible(self):
        f = Fixture()
        f.head(0)
        f.backend.put(f.profile.title_status_address, be32(f.profile.title_press_start_status))
        f.backend.put(f.profile.title_start_status_address, be32(1))
        f.reader.poll_once()
        f.reader.poll_once()
        self.assertEqual(len(f.events.values), 1)
        self.assertEqual(
            f.events.values[0][1],
            "Title screen. Pokemon XD: Gale of Darkness. Press A to start.",
        )

    def test_press_start_reannounces_after_screen_transition(self):
        f = Fixture()
        f.head(0)
        f.backend.put(f.profile.title_status_address, be32(f.profile.title_press_start_status))
        f.backend.put(f.profile.title_start_status_address, be32(1))
        f.reader.poll_once()
        f.backend.put(f.profile.title_start_status_address, be32(0))
        f.reader.poll_once()
        f.backend.put(f.profile.title_start_status_address, be32(1))
        f.reader.poll_once()
        self.assertEqual(len(f.events.values), 2)
        self.assertTrue(all(
            "Press A to start" in value[1] for value in f.events.values
        ))

    def test_active_unknown_title_message_suppresses_press_start(self):
        f = Fixture()
        f.head(0)
        f.backend.put(f.profile.title_status_address, be32(f.profile.title_press_start_status))
        f.backend.put(f.profile.title_start_status_address, be32(1))
        manager = 0x80008000
        tasks = 0x80008100
        f.backend.put(f.profile.manager_root, be32(manager))
        f.backend.put(manager + f.profile.manager_tasks_offset, be32(tasks))
        f.backend.put(tasks + f.profile.task_state_offset, bytes([1]))
        f.backend.put(tasks + f.profile.task_id_offset, be32(17113))
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_memory_card_notification_uses_local_text(self):
        f = Fixture()
        f.reader.title_messages = {
            129: "[Change Font]The Memory Card in Slot A has been read![Dialogue End]"
        }
        f.head(0)
        f.backend.put(
            f.profile.title_status_address,
            be32(f.profile.title_notification_statuses[0]),
        )
        manager = 0x80008000
        tasks = 0x80008100
        f.backend.put(f.profile.manager_root, be32(manager))
        f.backend.put(manager + f.profile.manager_tasks_offset, be32(tasks))
        f.backend.put(tasks + f.profile.task_state_offset, bytes([1]))
        f.backend.put(tasks + f.profile.task_id_offset, be32(129))
        f.reader.poll_once()
        f.reader.poll_once()
        self.assertEqual(
            [value[1] for value in f.events.values],
            ["The Memory Card in Slot A has been read!"],
        )

    def test_memory_card_yes_no_takes_focus_over_its_notification(self):
        f = Fixture()
        choices = f.work + 0x100
        f.head(f.work)
        f.node(f.work, 17, next_pointer=choices)
        f.node(
            choices, f.profile.new_game_confirmation_menu_id, cursor=1)
        f.backend.put(
            f.profile.title_status_address,
            be32(f.profile.title_notification_statuses[0]),
        )
        manager = 0x80008000
        tasks = 0x80008100
        f.backend.put(f.profile.manager_root, be32(manager))
        f.backend.put(manager + f.profile.manager_tasks_offset, be32(tasks))
        f.backend.put(tasks + f.profile.task_state_offset, bytes([1]))
        f.backend.put(tasks + f.profile.task_id_offset, be32(131))
        prompt = (
            "There is no POKeMON XD save file on the Memory Card in Slot A. "
            "Would you like to create a new save file?"
        )
        f.reader.title_messages = {131: prompt}

        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], f"{prompt} No")

        f.node(
            choices, f.profile.new_game_confirmation_menu_id, cursor=0)
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "Yes")

    def test_new_game_confirmation_speaks_prompt_and_no(self):
        f = Fixture()
        f.backend.put(
            f.profile.title_status_address,
            be32(f.profile.title_main_menu_status),
        )
        text = f.work + 0x100
        choice = f.work + 0x200
        f.head(f.work)
        f.node(f.work, 17, next_pointer=text)
        f.node(text, 51, next_pointer=choice)
        f.node(choice, 53, cursor=1)
        f.reader.poll_once()
        self.assertEqual(
            f.events.values[-1][1],
            "Is it okay to start a new Story? No",
        )

    def test_new_game_confirmation_speaks_yes_on_cursor_change(self):
        f = Fixture()
        f.backend.put(
            f.profile.title_status_address,
            be32(f.profile.title_main_menu_status),
        )
        text = f.work + 0x100
        choice = f.work + 0x200
        f.head(f.work)
        f.node(f.work, 17, next_pointer=text)
        f.node(text, 51, next_pointer=choice)
        f.node(choice, 53, cursor=1)
        f.reader.poll_once()
        f.node(choice, 53, cursor=0)
        f.reader.poll_once()
        self.assertEqual(
            [value[1] for value in f.events.values],
            [
                "Is it okay to start a new Story? No",
                "Yes",
            ],
        )

    def test_main_menu_uses_verified_window_cursor(self):
        f = Fixture()
        f.backend.put(
            f.profile.title_status_address,
            be32(f.profile.title_main_menu_status),
        )
        child = f.work + 0x100
        f.head(f.work)
        f.node(
            f.work, f.profile.title_menu_parent_id,
            next_pointer=child,
        )
        f.node(child, f.profile.title_menu_id, cursor=3)
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "Options")

    def test_main_menu_includes_live_verified_exit_item(self):
        f = Fixture()
        f.backend.put(
            f.profile.title_status_address,
            be32(f.profile.title_main_menu_status),
        )
        child = f.work + 0x100
        f.head(f.work)
        f.node(
            f.work, f.profile.title_menu_parent_id,
            next_pointer=child,
        )
        f.node(child, f.profile.title_menu_id, cursor=4)
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "Exit")

    def test_sound_value_changes_are_announced(self):
        f = Fixture()
        f.backend.put(
            f.profile.title_status_address,
            be32(f.profile.title_main_menu_status),
        )
        f.head(f.work)
        f.node(f.work, f.profile.title_option_menu_id, cursor=0)
        f.backend.put(f.profile.audio_mode_address, bytes([0x04]))
        f.reader.poll_once()
        f.backend.put(f.profile.audio_mode_address, bytes([0x00]))
        f.reader.poll_once()
        self.assertEqual(
            [value[1] for value in f.events.values],
            ["Sound, Mono", "Sound, Stereo"],
        )

    def test_rumble_reads_saved_no_vibration_flag(self):
        f = Fixture()
        f.backend.put(
            f.profile.title_status_address,
            be32(f.profile.title_main_menu_status),
        )
        manager = 0x80007000
        f.head(f.work)
        f.node(f.work, f.profile.title_option_menu_id, cursor=1)
        f.backend.put(f.profile.game_data_root, be32(manager))
        address = (
            manager + f.profile.game_data_save_offset
            + f.profile.game_data_no_vibration_offset
        )
        f.backend.put(address, bytes([0]))
        f.reader.poll_once()
        f.backend.put(address, bytes([1]))
        f.reader.poll_once()
        self.assertEqual(
            [value[1] for value in f.events.values],
            ["Rumble, On", "Rumble, Off"],
        )


class NameEntryMenuTests(unittest.TestCase):
    def test_preset_name_list_uses_live_direct_pair(self):
        f = Fixture()
        child = f.work + 0x100
        f.head(f.work)
        f.node(f.work, f.profile.name_screen_parent_id, next_pointer=child)
        f.node(child, f.profile.name_list_menu_id, cursor=2)
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "David")

    def keyboard(self, f, column, row):
        child = f.work + 0x100
        f.head(f.work)
        f.node(f.work, f.profile.name_screen_parent_id, next_pointer=child)
        f.node(child, f.profile.name_keyboard_menu_id, cursor=0)
        f.backend.put(f.profile.name_keyboard_column_address, be32(column))
        f.backend.put(f.profile.name_keyboard_row_address, be32(row))

    def test_keyboard_speaks_live_hover_coordinates(self):
        f = Fixture()
        expected = []
        for column, row, label in (
            (0, 0, "A"), (1, 0, "B"), (4, 0, "E"),
            (5, 0, "Space"), (6, 0, "F"), (7, 0, "G"),
            (10, 0, "J"),
            (0, 1, "K"), (1, 1, "L"), (2, 1, "M"), (3, 1, "N"),
            (4, 1, "O"), (5, 1, "Space"), (6, 1, "P"),
            (7, 1, "Q"), (8, 1, "R"), (9, 1, "S"), (10, 1, "T"),
            (5, 2, "Z"), (6, 2, "Space"),
            (5, 3, "Exclamation mark"), (7, 3, "Male symbol"),
            (8, 6, "Back"), (8, 7, "Done"),
        ):
            self.keyboard(f, column, row)
            f.reader.poll_once()
            expected.append(label)
        self.assertEqual(
            [value[1] for value in f.events.values], expected
        )

    def test_footleg_coordinates_do_not_insert_the_first_row_gap(self):
        """Live defect: the old contiguous A-J map announced column 5 as F
        and column 6 as G, while the game inserted Space and F.  Pin the
        actual hover labels used to enter FOOTLEG."""
        f = Fixture()
        for column, row in (
            (6, 0),             # F
            (4, 1), (4, 1),    # OO
            (10, 1),            # T
            (1, 1),             # L
            (4, 0),             # E
            (7, 0),             # G
        ):
            self.keyboard(f, column, row)
            f.reader.poll_once()
        self.assertEqual(
            [value[1] for value in f.events.values],
            ["F", "O", "T", "L", "E", "G"],
        )

    def test_keyboard_second_row_has_no_silent_letter_gaps(self):
        f = Fixture()
        for column in (5, 6, 7, 8, 9, 10):
            self.keyboard(f, column, 1)
            f.reader.poll_once()
        self.assertEqual(
            [value[1] for value in f.events.values],
            ["Space", "P", "Q", "R", "S", "T"],
        )

    def test_sparse_s_and_t_do_not_collide_with_u_and_v(self):
        f = Fixture()
        for column, row in ((9, 1), (0, 2), (10, 1), (1, 2)):
            self.keyboard(f, column, row)
            f.reader.poll_once()
        self.assertEqual(
            [value[1] for value in f.events.values],
            ["S", "U", "T", "V"],
        )

    def test_keyboard_reannounces_when_entered_name_changes(self):
        f = Fixture()
        self.keyboard(f, 0, 0)
        f.reader.poll_once()
        f.backend.put(
            f.profile.name_input_address,
            "A\0".encode("utf-16-be"),
        )
        f.reader.poll_once()
        self.assertEqual(
            [value[1] for value in f.events.values],
            ["A", "Name: A"],
        )

    def test_name_rater_reports_characters_after_player_name_limit(self):
        f = Fixture()
        self.keyboard(f, 6, 1)
        f.backend.put(
            f.profile.name_input_address,
            "ABCDEFG\0".encode("utf-16-be"),
        )
        f.reader.poll_once()
        f.backend.put(
            f.profile.name_input_address,
            "ABCDEFGP\0".encode("utf-16-be"),
        )
        f.reader.poll_once()
        self.assertEqual(
            [value[1] for value in f.events.values],
            ["P", "Name: ABCDEFGP"],
        )

    def yes_no_overlay(self, f, message_id, cursor, parent_id=None):
        keyboard = f.work + 0x100
        text = f.work + 0x200
        choices = f.work + 0x300
        f.head(f.work)
        f.node(f.work, f.profile.name_screen_parent_id, next_pointer=keyboard)
        f.node(keyboard, f.profile.name_keyboard_menu_id, next_pointer=text)
        f.node(text, 51 if parent_id is None else parent_id,
               next_pointer=choices)
        f.node(choices, 53, cursor=cursor)
        manager = 0x80008000
        tasks = 0x80008100
        f.backend.put(f.profile.manager_root, be32(manager))
        f.backend.put(manager + f.profile.manager_tasks_offset, be32(tasks))
        f.backend.put(tasks + f.profile.task_state_offset, bytes([2]))
        f.backend.put(tasks + f.profile.task_id_offset, be32(message_id))

    def test_name_confirmation_yes_no_uses_live_name(self):
        f = Fixture()
        self.yes_no_overlay(f, 15130, 0)
        f.backend.put(
            f.profile.name_input_address,
            "MC O\0".encode("utf-16-be"),
        )
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "Is MC O OK? Yes")

    def test_generic_yes_no_uses_active_local_prompt(self):
        f = Fixture()
        f.reader.title_messages = {
            15416: "[Change Font]Your progress will be saved. Is that okay?"
        }
        self.yes_no_overlay(f, 15416, 1)
        f.reader.poll_once()
        self.assertEqual(
            f.events.values[-1][1],
            "Your progress will be saved. Is that okay? No",
        )

    def test_daycare_choice_uses_game_rendered_dynamic_prompt(self):
        class Renderer:
            def text(self, message_id):
                return {
                    50713: "It will cost 1,200 POKe Dollars. Is that okay?"
                }.get(message_id)

        f = Fixture()
        f.reader.message_renderer = Renderer()
        self.yes_no_overlay(f, 50713, 1, parent_id=82)
        f.reader.poll_once()
        self.assertEqual(
            f.events.values[-1][1],
            "It will cost 1,200 POKe Dollars. Is that okay? No",
        )

    def test_continue_confirmation_parent_52_is_narrated(self):
        # Live 2026-08-08: direct windows 219 -> 52 -> 53, active GSmsg
        # 17134, cursor 1. Parent 52 is structurally distinct from the
        # already-covered save (51) and dialogue (82) confirmations.
        f = Fixture()
        f.reader.title_messages = {17134: "Is it okay to continue from here?"}
        prompt = f.work + 0x100
        choices = f.work + 0x200
        f.head(f.work)
        f.node(f.work, f.profile.continue_summary_menu_id,
               next_pointer=prompt)
        f.node(prompt, 52, next_pointer=choices)
        f.node(choices, 53, cursor=1)
        manager = 0x80008000
        tasks = 0x80008100
        f.backend.put(f.profile.manager_root, be32(manager))
        f.backend.put(manager + f.profile.manager_tasks_offset, be32(tasks))
        f.backend.put(tasks + f.profile.task_state_offset, bytes([2]))
        f.backend.put(tasks + f.profile.task_id_offset, be32(17134))
        f.reader.poll_once()
        self.assertEqual(
            f.events.values[-1][1],
            "Is it okay to continue from here? No",
        )

    def test_continue_confirmation_reads_game_rendered_save_summary(self):
        class Renderer:
            values = {
                231: "Name", 235: "LEON",
                232: "Play Time", 236: "27:10",
                233: "Snagged POKéMON", 237: "22",
                234: "Purified POKéMON", 238: "13",
            }

            def text(self, message_id):
                return self.values.get(message_id)

        f = Fixture()
        f.reader.message_renderer = Renderer()
        f.reader.title_messages = {17134: "Is it okay to continue from here?"}
        summary = f.work
        prompt = f.work + 0x100
        choices = f.work + 0x200
        f.head(summary)
        f.node(summary, 219, next_pointer=prompt)
        f.node(prompt, 52, next_pointer=choices)
        f.node(choices, 53, cursor=1)
        manager = 0x80008000
        tasks = 0x80008100
        f.backend.put(f.profile.manager_root, be32(manager))
        f.backend.put(manager + f.profile.manager_tasks_offset, be32(tasks))
        f.backend.put(tasks + f.profile.task_state_offset, bytes([2]))
        f.backend.put(tasks + f.profile.task_id_offset, be32(17134))

        f.reader.poll_once()

        self.assertEqual(
            f.events.values[-1][1],
            "Name: LEON. Play Time: 27:10. Snagged POKéMON: 22. "
            "Purified POKéMON: 13. Is it okay to continue from here? No",
        )

    def test_move_teacher_reads_move_id_despite_live_poison_word(self):
        class Renderer:
            def text(self, message_id):
                return {12002: "Cancel"}.get(message_id)

        f = Fixture()
        f.reader.move_data = MoveData({245: "EXTREMESPEED"})
        f.reader.message_renderer = Renderer()
        records = 0x80009000
        f.head(f.work)
        f.node(f.work, 228, cursor=0)
        f.backend.put(f.profile.move_teacher_count_address, be16(2))
        f.backend.put(f.profile.move_teacher_list_address, be32(records))
        f.backend.put(
            records + f.profile.move_teacher_move_offset,
            be16(245),
        )
        # Exact impossible value captured in production on 2026-08-10. It
        # is not a message ID and must never be sent to MessageRenderer.
        f.backend.put(
            records + f.profile.move_teacher_message_offset,
            be32(0xB5353535),
        )
        f.backend.put(
            records + f.profile.move_teacher_record_stride
            + f.profile.move_teacher_message_offset,
            be32(12002),
        )

        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "EXTREMESPEED")

        # The final row is not a move and still uses its own message ID.
        f.backend.put(
            records + f.profile.move_teacher_record_stride
            + f.profile.move_teacher_move_offset,
            be16(0),
        )
        f.node(f.work, 228, cursor=1)
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "Cancel")

    def test_bag_action_reads_selected_records_own_message(self):
        class Renderer:
            def text(self, message_id):
                return {50620: "USE", 50621: "GIVE"}.get(message_id)

        f = Fixture()
        f.reader.message_renderer = Renderer()
        action_work = 0x80009000
        records = 0x80009100
        f.head(f.work)
        f.node(f.work, f.profile.bag_action_menu_id, cursor=0)
        f.backend.put(
            f.work + f.profile.window_param_offset,
            be32(action_work),
        )
        f.backend.put(action_work, be32(records))
        f.backend.put(action_work + 4, be32(2))
        f.backend.put(records, be32(50620))
        f.backend.put(
            records + f.profile.bag_action_record_stride,
            be32(50621),
        )

        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "USE")
        f.node(f.work, f.profile.bag_action_menu_id, cursor=1)
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "GIVE")

    def test_bag_number_reads_backing_value_not_digit_cursor(self):
        f = Fixture()
        f.head(f.work)
        f.node(f.work, 49, cursor=0)
        f.backend.put(f.profile.bag_number_value_address, be32(3))

        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "3")

        # Moving between digit columns leaves the drawn value unchanged and
        # therefore must not repeat it.
        f.node(f.work, 49, cursor=1)
        f.reader.poll_once()
        self.assertEqual(len(f.events.values), 1)

        f.backend.put(f.profile.bag_number_value_address, be32(4))
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "4")

    def test_name_ids_without_direct_parent_are_silent(self):
        f = Fixture()
        f.head(f.work)
        f.node(f.work, f.profile.name_keyboard_menu_id, cursor=0)
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_dialogue_triggered_yes_no_uses_active_local_prompt(self):
        # A Yes/No confirmation raised from ordinary NPC dialogue (parent
        # window = dialogue_window_id, 82) rather than the pre-existing
        # menu-triggered save-confirmation path (parent 51) -- confirmed
        # live, then fixed by widening yes_no_confirmation_parent_ids to
        # cover both instead of a single hardcoded parent ID.
        f = Fixture()
        choices = f.work + 0x100
        f.head(f.work)
        f.node(f.work, f.profile.dialogue_window_id, next_pointer=choices)
        f.node(choices, 53, cursor=0)
        manager = 0x80008000
        tasks = 0x80008100
        f.backend.put(f.profile.manager_root, be32(manager))
        f.backend.put(manager + f.profile.manager_tasks_offset, be32(tasks))
        f.backend.put(tasks + f.profile.task_state_offset, bytes([2]))
        f.backend.put(tasks + f.profile.task_id_offset, be32(15417))
        f.reader.title_messages = {15417: "Save the game?"}
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "Yes")

    def test_global_save_prompt_is_not_hidden_by_dialogue_parent(self):
        f = Fixture()
        choices = f.work + 0x100
        f.head(f.work)
        f.node(f.work, f.profile.dialogue_window_id, next_pointer=choices)
        f.node(choices, 53, cursor=0)
        manager = 0x80008000
        tasks = 0x80008100
        f.backend.put(f.profile.manager_root, be32(manager))
        f.backend.put(manager + f.profile.manager_tasks_offset, be32(tasks))
        f.backend.put(tasks + f.profile.task_state_offset, bytes([2]))
        f.backend.put(tasks + f.profile.task_id_offset, be32(15346))
        f.reader.title_messages = {
            15346: "[Change Font]Would you like to save your progress?"
        }
        f.reader.poll_once()
        self.assertEqual(
            f.events.values[-1][1],
            "Would you like to save your progress? Yes",
        )

    def test_global_saved_notice_is_spoken_outside_title_screen(self):
        f = Fixture()
        f.head(0)
        manager = 0x80008000
        tasks = 0x80008100
        f.backend.put(f.profile.manager_root, be32(manager))
        f.backend.put(manager + f.profile.manager_tasks_offset, be32(tasks))
        f.backend.put(tasks + f.profile.task_state_offset, bytes([2]))
        f.backend.put(tasks + f.profile.task_id_offset, be32(145))
        f.reader.title_messages = {
            145: "[Change Font]Your progress has been saved![Dialogue End]"
        }
        f.backend.put(f.profile.title_status_address, be32(0))
        f.reader.poll_once()
        self.assertEqual(
            f.events.values[-1][1], "Your progress has been saved!"
        )

    def test_yes_no_accepts_unseen_parent_and_renders_runtime_prompt(self):
        f = Fixture()
        choices = f.work + 0x100
        f.head(f.work)
        # 83 is a caller observed in the move-learning flow.  The reader
        # must classify the reusable child widget, not enumerate callers.
        f.node(f.work, 83, next_pointer=choices)
        f.node(choices, f.profile.new_game_confirmation_menu_id, cursor=0)
        manager = 0x80008000
        tasks = 0x80008100
        f.backend.put(f.profile.manager_root, be32(manager))
        f.backend.put(manager + f.profile.manager_tasks_offset, be32(tasks))
        f.backend.put(tasks + f.profile.task_state_offset, bytes([2]))
        f.backend.put(tasks + f.profile.task_id_offset, be32(20012))

        class Renderer:
            def text(self, message_id):
                return (
                    "Stop learning Baby Doll Eyes?"
                    if message_id == 20012 else None
                )

        f.reader.message_renderer = Renderer()
        f.reader.poll_once()
        self.assertEqual(
            f.events.values[-1][1],
            "Stop learning Baby Doll Eyes? Yes",
        )


class ShopMenuTests(unittest.TestCase):
    """A shop's greeting opens the same small-list cursor widget as the
    yes/no overlay (same parent ids), but carries three items -- Buy/Sell/
    Quit -- not two. Disambiguated from a real yes/no by the active GSmsg
    message ID (50601, live-observed) rather than by the cursor's own
    menu_id, since the engine allocates a different cursor id here (89
    observed) than the fixed 53 every other yes/no path uses -- see
    shop_menu_message_ids's own comment in profile.py.

    These tests only check that the code speaks the tuple it's given --
    they can't prove the tuple's index order is correct (that would be
    circular). The order itself was verified separately: static
    disassembly (xd-decomp's menuShop.s) first, then live confirmation
    2026-07-30 by selecting each position and checking what screen
    actually opened, not by trusting a spoken label -- see
    shop_menu_labels's own comment in profile.py for the full chain."""

    def shop(self, f, cursor, message_id=50601, parent=51):
        choices = f.work + 0x100
        f.head(f.work)
        f.node(f.work, parent, next_pointer=choices)
        f.node(choices, 89, cursor=cursor)
        manager = 0x80008000
        tasks = 0x80008100
        f.backend.put(f.profile.manager_root, be32(manager))
        f.backend.put(manager + f.profile.manager_tasks_offset, be32(tasks))
        f.backend.put(tasks + f.profile.task_state_offset, bytes([2]))
        f.backend.put(tasks + f.profile.task_id_offset, be32(message_id))

    def test_buy_sell_quit_spoken_by_cursor_position(self):
        f = Fixture()
        spoken = []
        for cursor in (0, 1, 2):
            self.shop(f, cursor)
            f.reader.poll_once()
            spoken.append(f.events.values[-1][1])
        self.assertEqual(spoken, ["Buy", "Sell", "Quit"])

    def test_coupon_exchange_menu_has_its_own_labels(self):
        f = Fixture()
        spoken = []
        for cursor in (0, 1, 2):
            self.shop(f, cursor, message_id=50615)
            f.reader.poll_once()
            spoken.append(f.events.values[-1][1])
        self.assertEqual(spoken, ["Exchange", "Info", "Quit"])

    def test_third_item_does_not_raise_unlike_a_real_yes_no(self):
        # This is exactly the case that motivated the fix: routed through
        # yes_no_focus, a cursor of 2 raises MenuReadError (only 0/1 are
        # valid) and goes silent -- live-confirmed via
        # "MENU SAMPLE REJECTED: yes/no cursor invalid base=0 cursor=2".
        f = Fixture()
        self.shop(f, 2)
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "Quit")

    def test_dialogue_window_parent_also_recognized(self):
        f = Fixture()
        self.shop(f, 0, parent=f.profile.dialogue_window_id)
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "Buy")

    def test_greeting_text_prefixed_when_resolved(self):
        # The greeting text (message 50601) is resolved via
        # `shop_messages` -- a real, derived read from `pocket_menu.
        # fsys`'s own local message table (see shop_messages.py), found
        # by searching that already-extracted file for the exact text
        # the project owner read off-screen live 2026-07-30. NOT
        # `title_messages` (the DOL string catalog) -- that table
        # doesn't contain shop text at all, confirmed by direct search.
        f = Fixture()

        class FakeShopMessages:
            def resolve(self, message_id, player_name=""):
                if message_id == 50601:
                    return (
                        "Hello! Welcome to our POKéMON MART. "
                        "How may I serve you?"
                    )
                return None

        f.reader.shop_messages = FakeShopMessages()
        self.shop(f, 0)
        f.reader.poll_once()
        self.assertEqual(
            f.events.values[-1][1],
            "Hello! Welcome to our POKéMON MART. "
            "How may I serve you? Buy",
        )

    def test_no_resolved_text_falls_back_to_bare_label(self):
        f = Fixture()
        self.shop(f, 0)
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "Buy")

    def test_unrecognized_message_id_falls_back_to_real_yes_no(self):
        # Same parent, but with the REAL yes/no cursor id (53, not the
        # shop's 89) and a message ID not confirmed to be a shop greeting
        # -- must resolve through the pre-existing generic yes/no path
        # ("Yes"/"No"), not be mislabeled as Buy/Sell/Quit.
        f = Fixture()
        choices = f.work + 0x100
        f.head(f.work)
        f.node(f.work, 51, next_pointer=choices)
        f.node(choices, 53, cursor=0)
        manager = 0x80008000
        tasks = 0x80008100
        f.backend.put(f.profile.manager_root, be32(manager))
        f.backend.put(manager + f.profile.manager_tasks_offset, be32(tasks))
        f.backend.put(tasks + f.profile.task_state_offset, bytes([2]))
        f.backend.put(tasks + f.profile.task_id_offset, be32(99999))
        f.reader.poll_once()
        self.assertEqual(f.events.values[-1][1], "Yes")


class SpeechTests(unittest.TestCase):
    def test_rapid_focus_interrupts_old_focus(self):
        speaker = Speaker()
        coordinator = SpeechCoordinator(speaker, logger())
        coordinator.emit(SpeechEventClass.MENU_FOCUS, "Fight")
        coordinator.emit(SpeechEventClass.MENU_FOCUS, "Pokemon")
        self.assertEqual(speaker.values, [("Fight", True), ("Pokemon", True)])

    def test_battle_event_prioritizes_over_stale_focus(self):
        speaker = Speaker()
        coordinator = SpeechCoordinator(speaker, logger())
        coordinator.emit(SpeechEventClass.MENU_FOCUS, "Earthquake")
        coordinator.emit(
            SpeechEventClass.BATTLE_EVENT,
            "Salamence used Earthquake!",
        )
        self.assertEqual(
            speaker.values[-1], ("Salamence used Earthquake!", True)
        )

    def test_lifecycle_dedup(self):
        speaker = Speaker()
        coordinator = SpeechCoordinator(speaker, logger())
        coordinator.emit(
            SpeechEventClass.LIFECYCLE, "Ready", deduplicate=True
        )
        coordinator.emit(
            SpeechEventClass.LIFECYCLE, "Ready", deduplicate=True
        )
        self.assertEqual(speaker.values, [("Ready", False)])


class LifecycleMenuTests(unittest.TestCase):
    def test_disconnect_clears_menu_state(self):
        class Connection:
            def __init__(self): self.readable = True
            def hook(self): self.readable = True
            def verify_profile(self): return None
            def is_readable(self): return self.readable
            def close(self): self.readable = False
        class Tasks:
            def resolve(self): return None
        class Narrator:
            stop_requested = False
            def poll_once(self): return None
        class Menu:
            def __init__(self): self.cleared = []
            def poll_once(self): return None
            def clear(self, reason): self.cleared.append(reason)
        connection = Connection()
        speaker = Speaker()
        menus = []
        def menu_factory():
            menu = Menu()
            menus.append(menu)
            return menu
        controller = LifecycleController(
            connection, lambda: Tasks(), lambda _tasks: Narrator(),
            speaker, logger(), waiting_interval=0, active_interval=0,
            menu_factory=menu_factory,
        )
        controller.step()
        connection.readable = False
        controller.step()
        self.assertTrue(menus[0].cleared)
        self.assertIsNone(controller.menu_reader)

def control(opcode, *extra):
    """One GSchar control code: the 0xFFFF escape, the opcode, then the
    opcode's own argument bytes."""
    return b"\xFF\xFF" + bytes([opcode]) + bytes(extra)


def template(*parts):
    """Build a raw shipped-format message from literal text and controls."""
    out = b""
    for part in parts:
        out += part if isinstance(part, bytes) else b"".join(
            be16(ord(c)) for c in part)
    return out + b"\0\0"


class ProgressNotificationTests(unittest.TestCase):
    """These notifications speak the GAME'S OWN text, substituted the way
    the engine substitutes it -- not a per-ID English paraphrase.

    So the fixture builds a real string table, real msgvar globals and real
    item/species databases in fake memory, and drives a real
    `RuntimeMessageCatalog` + `MessageRenderer` through
    `ProductionMenuReader`. Nothing about the substitution is mocked: if
    the opcode table, the msgvar addresses or the database chains drift,
    these fail. The previous version of this class asserted typed-in
    English against a party-slot double, and so passed for the entire life
    of the feature while it crashed the narrator in production.

    Message bodies below are the real shipped templates for these IDs, read
    out of a local extraction of the project owner's own image."""

    MANAGER, TASKS = 0x80008000, 0x80008100
    WORK, TABLE = 0x80009000, 0x8000A000
    CTRL_TABLE = 0x8000B000
    SPECIES_COUNT, SPECIES_BASE = 0x8000C000, 0x8000C100
    ITEM_INDEX_COUNT, ITEM_INDEX = 0x8000E000, 0x8000E100
    ITEM_COUNT, ITEM_BASE = 0x8000E400, 0x8000E500
    NICKNAME = 0x8000F000

    # id -> raw shipped bytes. 0x07 = change font (1 argument byte),
    # 0x00 = new line, 0x02 = dialogue end, 0x2B = player name,
    # 0x2D = item, 0x2F = quantity, 0x32 = Pokemon, 0x4E = species.
    MESSAGES = {
        50201: template(control(0x07, 0x01), "What?", control(0x00),
                        control(0x32), " is evolving!"),
        16002: template(control(0x07, 0x01), "Your ", control(0x32),
                        " in the PURIFY CHAMBER", control(0x00),
                        "is now ready for purification!", control(0x00),
                        "Hurry to the POKeMON HQ LAB!", control(0x02)),
        54006: template(control(0x07, 0x01), control(0x2B), " obtained",
                        control(0x00), "the ", control(0x2F), " ",
                        control(0x2D), "s!", control(0x02)),
        50504: template(control(0x32), " regained ", control(0x2F),
                        " EXP Points!", control(0x03)),
        50202: template(control(0x07, 0x01), "Congratulations!", control(0x00),
                        "Your ", control(0x32), " evolved into",
                        control(0x00), control(0x4E), "!", control(0x02)),
        5013: template("POTION"),
        900: template("PIKACHU"),
        # A real ID this reader does NOT own -- ShopNotificationReader does.
        50602: template("May I help you with anything else?"),
    }

    def fixture(self, message_id, quantity=3):
        f = Fixture()
        f.reader.player_name_provider = lambda: "LEON"
        put = f.backend.put

        # --- the active GSmsg task carrying this message id
        put(f.profile.manager_root, be32(self.MANAGER))
        put(self.MANAGER + f.profile.manager_tasks_offset, be32(self.TASKS))
        put(self.TASKS + f.profile.task_state_offset, bytes([1]))
        put(self.TASKS + f.profile.task_id_offset, be32(message_id))

        # --- one loaded string table, laid out the way GSmsgGetGSchar
        # reads it: u16 table id, u16 entry count, next pointer at +0x08,
        # then 8-byte (id, offset) entries from +0x10 sorted ascending.
        put(self.MANAGER + 0x04, be32(self.TABLE))
        entries = sorted(self.MESSAGES)
        put(self.TABLE + 0x00, be16(0))
        put(self.TABLE + 0x04, be16(len(entries)))
        put(self.TABLE + 0x08, be32(0))
        body = 0x10 + len(entries) * 8
        for index, mid in enumerate(entries):
            put(self.TABLE + 0x10 + index * 8, be32(mid))
            put(self.TABLE + 0x10 + index * 8 + 4, be32(body))
            put(self.TABLE + body, self.MESSAGES[mid])
            body += len(self.MESSAGES[mid])

        # --- msgvars, exactly the globals the engine's own handlers read
        # The msgvar addresses now live on the profile, named after the
        # symbol each msgctrlcode handler reads, rather than being repeated
        # as module constants here.
        put(self.NICKNAME, template("SPARKY"))
        put(f.profile.msg_pokemon, be32(self.NICKNAME))    # 0x32
        put(f.profile.msg_item, be16(13))                  # 0x2D
        put(f.profile.msg_digit, be32(quantity))           # 0x2F
        put(f.profile.msg_pokemon_id, be16(25))            # 0x4E

        # --- species database: count is [[sym]], base is [sym]
        put(message_render.POKEMON_DATA_NUMBER, be32(self.SPECIES_COUNT))
        put(self.SPECIES_COUNT, be32(400))
        put(message_render.POKEMON_DATA, be32(self.SPECIES_BASE))
        put(self.SPECIES_BASE + 25 * message_render.POKEMON_DATA_STRIDE
            + message_render.POKEMON_NAME_OFFSET, be32(900))

        # --- item database: raw id -> dense index -> record -> name id
        put(message_render.ITEM_INDEX_NUMBER, be32(self.ITEM_INDEX_COUNT))
        put(self.ITEM_INDEX_COUNT, be32(600))
        put(message_render.ITEM_INDEX, be32(self.ITEM_INDEX))
        put(self.ITEM_INDEX + 13 * 2, be16(7))
        put(message_render.ITEM_PRIME_NUMBER, be32(self.ITEM_COUNT))
        put(self.ITEM_COUNT, be32(300))
        put(message_render.ITEM_PRIME, be32(self.ITEM_BASE))
        put(self.ITEM_BASE + 7 * message_render.ITEM_DATA_STRIDE
            + message_render.ITEM_NAME_OFFSET, be32(5013))

        f.reader.message_renderer = MessageRenderer(
            f.memory, f.profile,
            RuntimeMessageCatalog(f.memory, f.profile),
            f.reader.player_name_provider)
        return f

    def spoken(self, message_id, **kwargs):
        f = self.fixture(message_id, **kwargs)
        f.reader.poll_once()
        return f.events.values[-1][1] if f.events.values else None

    def test_evolution_start_substitutes_the_live_nickname(self):
        self.assertEqual(
            self.spoken(50201), "What? SPARKY is evolving!")

    def test_evolution_finish_substitutes_species_through_its_database(self):
        # 0x4E is a mode-2 opcode: the global holds a species id, which
        # resolves to a NAME MESSAGE ID through the species database, which
        # then resolves to text. Two chained lookups, neither hardcoded.
        self.assertEqual(
            self.spoken(50202),
            "Congratulations! Your SPARKY evolved into PIKACHU!")

    def test_purification_ready_speaks_the_shipped_sentence(self):
        self.assertEqual(
            self.spoken(16002),
            "Your SPARKY in the PURIFY CHAMBER is now ready for "
            "purification! Hurry to the POKeMON HQ LAB!")

    def test_purification_ceremony_keeps_the_exp_total(self):
        # The old paraphrase collapsed 50503/50504/50510/50511 into one
        # generic "Purification ceremony results for X", throwing away the
        # EXP total and the regained move -- the entire content of the
        # screen. This is the regression guard for that.
        #
        # "1450", not "1,450". Corrected 2026-08-06: the old renderer
        # formatted every numeric opcode with thousands separators, which
        # was an assumption. `msgctrlDigit` (opcode 0x2F) calls
        # `_msgctrlMakeDigit(buf, 16, _Digit, 0)` -- and that function only
        # takes its separator-inserting branch for flag 4 or 0xA.
        # `msgctrlMoney` (0x4B) is the one that passes 4, so grouping now
        # applies to money and not to plain quantities, matching the game.
        self.assertEqual(
            self.spoken(50504, quantity=1450),
            "SPARKY regained 1450 EXP Points!")

    def test_obtained_item_resolves_player_item_and_quantity(self):
        self.assertEqual(
            self.spoken(54006), "LEON obtained the 3 POTIONs!")

    def test_message_owned_by_another_reader_is_left_alone(self):
        # 50602 is real, loaded and active here, but belongs to
        # ShopNotificationReader. Speaking it would double up.
        self.assertIsNone(self.spoken(50602))

    def test_daycare_nonchoice_message_uses_game_renderer(self):
        class Renderer:
            def text(self, message_id):
                return {
                    50715: "FARQUAD came back from the DAY-CARE!"
                }.get(message_id)

        f = self.fixture(50201)
        f.reader.message_renderer = Renderer()
        f.backend.put(self.TASKS + f.profile.task_id_offset, be32(50715))
        f.reader.poll_once()
        self.assertEqual(
            f.events.values[-1][1],
            "FARQUAD came back from the DAY-CARE!",
        )

    def test_held_item_and_tm_information_windows_are_spoken(self):
        messages = {
            15051: "The Potion was taken and replaced with the Berry.",
            15052: "SPARKY was given the Potion to hold.",
            15053: "Received the Potion from SPARKY.",
            15054: "SPARKY isn't holding anything.",
            15055: "You have no room for it.",
            15056: "SPARKY is in Hyper Mode! It won't accept an item!",
            50037: "Booted up a TM.",
            50038: "Booted up an HM.",
            50039: "It contained Bite. Would you like to teach Bite to a Pokemon?",
        }

        class Renderer:
            def text(self, message_id):
                return messages.get(message_id)

        for message_id, expected in messages.items():
            with self.subTest(message_id=message_id):
                f = self.fixture(50201)
                f.reader.message_renderer = Renderer()
                f.backend.put(
                    self.TASKS + f.profile.task_id_offset,
                    be32(message_id),
                )
                f.reader.poll_once()
                self.assertEqual(f.events.values[-1][1], expected)

    def test_unloaded_message_is_silent_rather_than_invented(self):
        # 50503 is in this reader's ID set but lives in the Relic Stone
        # map's own table, absent here. Silence is correct; a stand-in
        # sentence is the exact failure this rework removes.
        f = self.fixture(50201)
        f.backend.put(self.TASKS + f.profile.task_id_offset, be32(50503))
        f.reader.poll_once()
        self.assertEqual(f.events.values, [])

    def test_dispatch_table_mismatch_is_reported(self):
        f = self.fixture(50201)
        f.backend.put(self.MANAGER + 0x24, be32(self.CTRL_TABLE))
        for code, opcode in battle_opcodes.REGISTRY.items():
            f.backend.put(
                self.CTRL_TABLE + code * 8 + 4, be32(opcode.handler))
        self.assertEqual(f.reader.message_renderer.verify_dispatch_table(), [])
        f.backend.put(self.CTRL_TABLE + 0x32 * 8 + 4, be32(0x80000000))
        self.assertEqual(
            f.reader.message_renderer.verify_dispatch_table(),
            [(0x32, 0x801547A4, 0x80000000)])

if __name__ == "__main__":
    unittest.main()













