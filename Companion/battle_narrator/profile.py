from dataclasses import dataclass


@dataclass(frozen=True)
class AddressProfile:
    title: str = "Pokemon XD: Gale of Darkness"
    region: str = "US"
    game_id: bytes = b"GXXE01"
    revision: int = 0
    # --- what this profile is actually compatible with -------------------
    #
    # `game_id`/`revision` are the DISC LABEL. They are reported and logged
    # but are deliberately NOT the compatibility gate, because the label
    # answers the wrong question. Every address in this profile is a
    # position in the game's CODE, so what has to be true for the narrator
    # to be safe is "this binary is laid out the way our addresses assume"
    # -- and a ROM hack built on the US release (XG, which this whole
    # project exists for) keeps that layout while being free to relabel the
    # disc. Gating on the label refuses builds that are perfectly fine and,
    # worse, would accept a build that shared a label but moved its code.
    #
    # So the gate is `engine_signatures`: exact byte matches at fixed
    # addresses, in small engine-internal functions that data-editing hacks
    # have no reason to touch, one per subsystem the narrator depends on.
    # All must match. Bytes were taken from xd-decomp's matching GXXE01
    # build, and every one of these functions lives at a DIFFERENT address
    # in the only other build with a published map (the JP demo disc,
    # NXXJ01), so the set genuinely discriminates rather than matching any
    # Orre-engine binary.
    #
    # This is a safety mechanism, not a convenience one. Reading a PAL or
    # JP retail image with these addresses would not fail loudly -- it
    # would speak confident nonsense, which for a blind player is worse
    # than refusing to start.
    engine_signatures: tuple = (
        # message substitution -- the whole progress-notification path
        ("msgctrlPokemon", 0x801547A4,
         bytes.fromhex("806db4684e800020")),
        # message control-code dispatch table install
        ("GSmsgSetCtrlFunc", 0x80109000,
         bytes.fromhex("808d852890640024386000004e800020")),
        # type chart -- Purify Chamber Tempo
        ("zokuseiBiosGetWazaJoutai", 0x80117B28,
         bytes.fromhex("80ad89a8800500007c0300404180000c")),
        # Purify Chamber Tempo bar thresholds
        ("relivehallTempoToLevel", 0x8003AAA4,
         bytes.fromhex("2c03001a4181000c386000004e800020")),
        # Purify Chamber SET addressing
        ("CReliveHall::getStage", 0x8028D4D8,
         bytes.fromhex("1c0403d87c6302144e800020")),
        # PC box capacity
        ("pcboxGetNbPokemonBox", 0x801570C0,
         bytes.fromhex("386000084e800020")),
        # Pokemon record identity
        ("Pokemon::getPokemonDataId", 0x8014B87C,
         bytes.fromhex("a06300004e800020")),
        # save-data section table
        ("savedataGetStatus", 0x801CEFB4,
         bytes.fromhex("9421fff07c0802a6900100145480043e")),
        # collision-object enable state. These four instructions ARE the
        # `gscolsys2` address below: `lis r5, GScolsys2@ha` carries 0x8044 and
        # `addi r6, r5, GScolsys2@l` carries 0x5C20, so a build that moved the
        # global fails this signature rather than silently reading whatever
        # now sits at 0x80445C20 and reporting its low bits as walls.
        ("GScolsys2GetObjEnable", 0x80117BAC,
         bytes.fromhex("3ca0804438c55c2080a6000028050000")),
    )
    mem1_start: int = 0x80000000
    mem1_end: int = 0x81800000
    gscolsys2: int = 0x80445C20
    """`GScolsys2` -- the collision system's own global, holding which CCD
    objects the engine currently considers. Verified by the
    `GScolsys2GetObjEnable` signature above, which encodes this exact value.
    See `collision_object_enable.py` for the structure."""
    manager_root: int = 0x804E8348
    attack_mons: int = 0x804EB1FC
    defence_mons: int = 0x804EB200
    waza_name: int = 0x804EB260
    # RENAMED 2026-08-06. These were `trainer_enemy_class_name` and
    # `trainer_enemy_personal_name`, which was wrong in a way that would
    # have mattered: NEITHER is a class. Every writer sets both through
    # `fightTrainerGetNamePtr` -- a PROPER NAME -- and the pair exists to
    # carry TWO DIFFERENT TRAINERS, not a class and a name for one.
    # `fightActionFlowSyuuryou` / `KaisiNyuujouPokemon` / `WS_POKE_*_RATE`
    # all do, in order:
    #     0x22 = fightTrainerGetPrefixNamePtr(trainer)   <- the class
    #     0x23 = fightTrainerGetNamePtr(trainer)         <- its name
    #     0x25 = fightTrainerGetNamePtr(otherTrainer)    <- a SECOND name
    # confirmed by the templates: 20259 "Player beat [0x25] and [0x26]!",
    # 20309 "[0x25] sent out [0x18]! [0x26] sent out [0x19]!". The "ene"
    # in _TRAINER_ENENAME is 敵 (enemy) -- whose name it is, not what kind
    # of string it holds.
    trainer_first_name: int = 0x804EB254      # _TRAINER_ENENAME   op 0x25
    trainer_second_name: int = 0x804EB258     # _TRAINER_ENENAME2  op 0x26
    # Authoritative trainer-class route used by fightTrainerGetPrefixNamePtr:
    # FightTrainer.data_id -> DeckTrainer[data_id].kind (+0x05) ->
    # fight_trainer_kind_data[kind].prefix_message_id (+0x04).
    deck_trainer_pointer: int = 0x804EBB58
    deck_trainer_size: int = 0x804EBB68
    deck_trainer_stride: int = 0x38
    deck_trainer_kind_offset: int = 0x05
    trainer_kind_data_pointer: int = 0x804E8954
    trainer_kind_count_pointer: int = 0x804E8950
    trainer_kind_stride: int = 0x0C
    trainer_kind_title_id_offset: int = 0x04
    ev_str_buf0: int = 0x804EB1F0
    ev_str_buf1: int = 0x804EB1F4
    ev_str_buf2: int = 0x804EB1F8
    tsuika_mons: int = 0x804EB208
    # _MY_NAME (.sbss) -- confirmed by static trace to be fed by
    # msgctrlSetValue(19, ...), never opcode 0x2B/"Player Field 43".
    # Zero callers pass msgVar 19 anywhere in main.dol, so this is set
    # from a battle .rel -- only ever confirmed working in battle
    # messages (LOSS_ID/WHITEOUT_ID via resolver.player_sample()). Do
    # NOT use this for overworld/field dialogue; see
    # dialogue_player_name_savedata_ptr below for that.
    my_name: int = 0x804EB20C
    # The four send-out name globals, msgctrl opcodes 0x14/0x15/0x16/0x17.
    # Transcribed from the shipped `msgctrlcode` dispatch table
    # (.data:0x80404710, 111 x 8 bytes, dumped from the original main.dol)
    # and named against xd-decomp's symbols.txt: opcode 0x14 dispatches to
    # `msgctrlMyMons` (0x80153FEC), an 8-byte accessor that simply returns
    # `_MY_MONS`. These hold a POINTER TO GSchar TEXT, not a
    # FightOutPokemon* -- which is why every previous attempt to read them
    # as battler pointers found "unaligned" garbage.
    #
    # Their single writer is
    # `_fightActionFlowKaisiNyuujouPokemonSubAppearMsg`
    # (fightActionFlow.s:0x8020B700), which stores the SAME nickname
    # pointer into both members of a pair (0x14 with 0x16, 0x15 with 0x17)
    # for the Pokemon currently entering the field. The pair chosen encodes
    # the entering POSITION, not the side -- the message ID is what says
    # whose Pokemon it is (20312/20313 player, 20304/20305 foe). Reading
    # `_ENEMY_MONS` as "the opponent's" without checking the message ID
    # would be wrong.
    my_mons: int = 0x804EB210
    my_mons2: int = 0x804EB214
    enemy_mons: int = 0x804EB218
    enemy_mons2: int = 0x804EB21C
    # msgctrl opcodes 0x22/0x23 -> msgctrlTrainerType/msgctrlTrainerName,
    # both 8-byte accessors returning these text pointers directly. These
    # are the live source for "[Foe Tr Class 34] [Foe Tr Name 35]", which
    # this project previously could only approximate by walking the
    # persistent deck-trainer tables.
    trainer_type_name: int = 0x804EB248
    trainer_personal_name: int = 0x804EB24C
    # --- the rest of the msgvar block ------------------------------------
    # Every remaining global named by `battle_opcodes.REGISTRY`. Addresses
    # are verbatim from xd-decomp's `config/GXXE01/symbols.txt` .sbss
    # listing (0x804EB1F0-0x804EB2CC, one contiguous run), and each is
    # reached by exactly one msgctrlcode handler. Names here are the
    # project's, mapped to the symbol in the comment.
    client_mons: int = 0x804EB204            # _CLIENT_MONS      op 0x11
    clientnowork: int = 0x804EB238           # _CLIENTNOWORK     op 0x1E
    enemy_tmons: int = 0x804EB220            # _ENEMY_TMONS      op 0x18
    enemy_tmons2: int = 0x804EB224           # _ENEMY_TMONS2     op 0x19
    speabi_name_a: int = 0x804EB228          # _SPEABI_NAMEA     op 0x1A
    speabi_name_d: int = 0x804EB22C          # _SPEABI_NAMED     op 0x1B
    speabi_name_c: int = 0x804EB230          # _SPEABI_NAMEC     op 0x1C
    speabi_name_t: int = 0x804EB234          # _SPEABI_NAMET     op 0x1D
    side_attack_name_ha: int = 0x804EB23C    # _SIDE_ATTACK_NAMEHA  op 0x1F
    side_attack_name_wo: int = 0x804EB240    # _SIDE_ATTACK_NAMEWO  op 0x20
    side_attack_name_no: int = 0x804EB244    # _SIDE_ATTACK_NAMENO  op 0x21
    trainer_lose_name: int = 0x804EB250      # _TRAINER_LOSE     op 0x24
    trainer_client_no_name: int = 0x804EB25C  # _TRAINER_CLIENTNO op 0x27
    item_name: int = 0x804EB264              # _ITEM_NAME        op 0x29
    paso_name: int = 0x804EB268              # _PASO_NAME        op 0x2A
    side_defence_name_ha: int = 0x804EB26C   # _SIDE_DEFENCE_NAMEHA op 0x42
    side_defence_name_wo: int = 0x804EB270   # _SIDE_DEFENCE_NAMEWO op 0x43
    side_defence_name_no: int = 0x804EB274   # _SIDE_DEFENCE_NAMENO op 0x44
    msg_item: int = 0x804EB278               # _Item      u16    op 0x2D
    msg_item2: int = 0x804EB27A              # _Item2     u16    op 0x2E
    msg_digit: int = 0x804EB27C              # _Digit            op 0x2F
    msg_digit2: int = 0x804EB280             # _Digit2           op 0x30
    msg_id: int = 0x804EB284                 # _MsgID            op 0x31
    msg_pokemon: int = 0x804EB288            # _Pokemon          op 0x32
    msg_pokemon2: int = 0x804EB28C           # _Pokemon2         op 0x33
    menu_digit: int = 0x804EB290             # _MenuDigit        op 0x34
    menu_digit2: int = 0x804EB294            # _MenuDigit2       op 0x35
    menu_pokemon: int = 0x804EB298           # _MenuPokemon      op 0x36
    menu_msg: int = 0x804EB29C               # _MenuMsg          op 0x37
    menu_msg2: int = 0x804EB2A0              # _MenuMsg2         op 0x51
    msg_waza: int = 0x804EB2A4               # _Waza      u16    op 0x39
    msg_money: int = 0x804EB2A8              # _Money            op 0x4B
    msg_time: int = 0x804EB2AC               # _Time             op 0x4C
    msg_string: int = 0x804EB2B0             # _String           op 0x4D
    msg_string2: int = 0x804EB2B4            # _String2          op 0x57
    msg_pokemon_id: int = 0x804EB2B8         # _PokemonID u16    op 0x4E
    menu_money: int = 0x804EB2BC             # _MenuMoney        op 0x50
    menu_msg_id: int = 0x804EB2C0            # _MenuMsgID        op 0x55
    menu_msg_id2: int = 0x804EB2C4           # _MenuMsgID2       op 0x56
    msg_tribe: int = 0x804EB2C8              # _Tribe     u16    op 0x58
    msg_npc: int = 0x804EB2CA                # _Npc       u16    op 0x59
    # now_savedata_ptr (.sbss) -- the live save-data blob's base address.
    # Static trace found `savedataBiosSetNowSavedataPtr`'s one call site
    # (pokecolo.s) deliberately RANDOMIZES this every boot:
    # pokecolo_savedata + (OSGetTime_lo & 0x7E0) -- 64 possible 32-byte-
    # aligned offsets. This is why any *hardcoded* downstream address
    # (e.g. the old hero_party_base scan result) only ever survives one
    # boot -- it must always be re-derived from this pointer, never
    # cached as a constant.
    savedata_pointer_address: int = 0x804EB6F8
    # savedataBiosGetHeroPtr: savedata + 0x140 -- the live "hero" struct
    # (player name, party, etc; heroBiosCopy bounds it at 0x978 bytes
    # total). Player's own name (used by field dialogue's PLAYER_NAME
    # opcode 0x2B / msgVar 43, via msgctrlHero -> savedataGetStatus(0,2))
    # is hero+0x00, 11x-u16 (22 bytes) null-terminated UTF-16BE --
    # completely separate from the battle-only `my_name` above. Live-
    # verified: resolved to "LEON", matching the player's actual name.
    hero_offset: int = 0x140
    hero_name_offset: int = 0x00
    # u32, hero+0x8E4 -- derived from xd-decomp's `heroBiosGetPokedoru`
    # (game/pxdvs/app/hero/heroBios.cpp, `lwz r3, 0x8e4(r3)`), the function
    # `getMoney__Fv` calls via `heroGetStatus(0, 0xc, 0)`. Same "hero"
    # struct base bag_menu.py's own `_hero_base()` already resolves
    # (`savedata_pointer_address` -> `+hero_offset`), no new address chain.
    hero_pokedoru_offset: int = 0x8E4
    # u32, hero+0x8E8 -- the adjacent Poké Coupon balance. Confirmed by
    # LibPkmGC's XD PlayerData layout and independent load/save code.
    hero_poke_coupon_offset: int = 0x8E8
    manager_capacity_offset: int = 0x00
    manager_tasks_offset: int = 0x1C
    task_capacity: int = 2
    task_stride: int = 0x6C
    task_state_offset: int = 0x00
    task_id_offset: int = 0x1C
    fight_out_pokemon_offset: int = 0x04
    nickname_offset: int = 0x52
    current_move_id_offset: int = 0x64C
    window_manager: int = 0x80445A68
    window_list_offset: int = 0x10
    window_node_size: int = 0xBC
    window_next_offset: int = 0x10
    window_menu_id_offset: int = 0x04
    window_cursor_base_offset: int = 0x9C
    window_cursor_offset: int = 0x9E
    window_alloc_offset: int = 0xB8
    window_param_offset: int = 0x68
    # Nintendo health-and-safety warning opened by _NintendoWarningInit.
    nintendo_warning_menu_id: int = 0x112
    title_menu_parent_id: int = 17
    title_menu_id: int = 278
    title_menu_labels: tuple = (
        "New Game", "Continue", "VS Mode", "Options", "Exit",
    )
    title_status_address: int = 0x804EAA38
    title_start_status_address: int = 0x804EAA30
    title_press_start_status: int = 32
    title_main_menu_status: int = 41
    title_notification_statuses: tuple = (32, 200)
    # These DOL-table save strings also run during normal gameplay.
    global_save_prompt_message_ids: frozenset = frozenset({15346, 15347})
    global_save_notification_message_ids: frozenset = frozenset({144, 145})
    continue_confirmation_message_id: int = 17134
    title_option_menu_id: int = 279
    title_option_labels: tuple = ("Sound", "Rumble", "Exit")
    new_game_confirmation_parent_ids: tuple = (17, 51)
    new_game_confirmation_menu_id: int = 53
    new_game_confirmation_labels: tuple = (
        "Is it okay to start a new Story? Yes",
        "Is it okay to start a new Story? No",
    )
    # Generic in-game Yes/No overlay (menu_id 53, same node type as the
    # title's New Story confirmation above, but reused for ordinary
    # gameplay prompts -- e.g. a save-game confirmation, parent 51; the
    # title Continue confirmation, parent 52 (live-captured 2026-08-08 as
    # direct windows 219 -> 52 -> 53 with active message 17134); or an
    # NPC-dialogue-triggered question, parent 82 == dialogue_window_id.
    # Kept as a set so more parent contexts can be added here as they're
    # found, without touching the detection logic itself.
    yes_no_confirmation_parent_ids: tuple = (51, 52, 82)
    # menuSaveLoad's Continue panel draws these DOL label/value messages;
    # SaveParameterSet populates their live substitutions before display.
    continue_summary_menu_id: int = 219
    continue_summary_message_pairs: tuple = (
        (231, 235), (232, 236), (233, 237), (234, 238),
    )
    # menuScriptWazaOshie: both variants draw record+4 as a GSmsg ID.
    move_teacher_menu_ids: tuple = (228, 229)
    move_teacher_count_address: int = 0x804E7FA8  # _WazaNum (u16)
    move_teacher_list_address: int = 0x804EA8D8   # _wazalist (pointer)
    move_teacher_record_stride: int = 0x18
    move_teacher_move_offset: int = 0x00
    move_teacher_message_offset: int = 0x04
    bag_action_menu_id: int = 45
    bag_action_work_param: int = 0
    bag_action_record_stride: int = 0x0C
    bag_action_message_offset: int = 0
    # menuPocket2NumCtrl variants all display and mutate Data+0x34.  The
    # cursor fields select a digit column; they are not the entered value.
    bag_number_menu_ids: tuple = (46, 47, 48, 49)
    bag_number_value_address: int = 0x80438318
    # A shop's "Welcome! ..." greeting opens the SAME generic small-list
    # cursor widget as the yes/no overlay above (same parent ids, live-
    # confirmed 2026-07-30), but with three items -- Buy/Sell/Quit, project-
    # owner-confirmed live from actual gameplay -- not two, so it cannot be
    # read through yes_no_focus's hardcoded 2-item assumption. Disambiguated
    # from a real yes/no by the active GSmsg prompt's own message ID (50601
    # observed at the shopkeeper's greeting) rather than by the cursor's own
    # menu_id, since the cursor id the engine allocates for this widget (89
    # observed) is not itself a meaningful signal -- see menus.py's
    # _cursor()/mapped_focus(), which never inspect a node's own menu_id.
    # Kept as a set, matching yes_no_confirmation_parent_ids's own comment,
    # so more shop-greeting message IDs (other Mart locations may use a
    # different one) can be added here as they're confirmed live, without
    # touching the detection logic.
    shop_menu_message_ids: tuple = (50601, 50615)
    shop_coupon_menu_message_ids: tuple = (50615,)
    # Index order verified, not assumed -- static disassembly first
    # (xd-decomp build/GXXE01/asm/game/menuShop.s, shopProc/selectDealMode
    # at 0x80063028/0x80062FC8), then confirmed live 2026-07-30 by
    # selecting each position and checking the RESULTING screen, not by
    # trusting a spoken label: index 0 opened a distinct new window (ids
    # 60/61, matching shopBuyMain's item-grid/price flow in the
    # disassembly) -- Buy; index 1 opened this project's own already-
    # verified Bag Menu reader, which spoke real inventory ("Items.
    # Potion. Quantity 2...") -- matching menuPocket2Call/_execSell in the
    # disassembly -- Sell; index 2 is determined by elimination (the only
    # remaining word of the three the project owner confirmed are on
    # screen), not by a further guess.
    shop_menu_labels: tuple = ("Buy", "Sell", "Quit")
    shop_coupon_menu_labels: tuple = ("Exchange", "Info", "Quit")
    # Selecting "Buy" opens a completely different, standalone widget (not
    # the shared yes/no/small-list cursor widget above) -- a single window
    # node whose own menu_id was live-confirmed 2026-07-30 (id 60), with no
    # GSmsg task backing it (unlike the greeting) and none of the generic
    # window_alloc_offset/window_cursor_base_offset machinery populated in
    # the way other menus use it. Derived from xd-decomp's real disassembly
    # (game/menuShop.s): `menuShopCursor` (0x80061F90) reads a "this"
    # pointer's own +0x68 as a `SHOP_MENU_ARG*`, and `getItem__F...`
    # (0x80061590) shows that struct's +0x08 is a pointer to a u16 item-ID
    # array and +0xC is the item count -- `lwz r3,0x8(r30)` /
    # `lhzx r3,r3,r0` (index*2) and `lwz r3,0xc(r3)` respectively.
    # `menuShopCursor` also reveals the absolute list index is the window's
    # own window_cursor_base_offset (+0x9C, "page") PLUS window_cursor_offset
    # (+0x9E, "in-page position") added together -- confirmed live by
    # moving the cursor down one row and seeing +0x9E go 0->1 while the
    # resolved item ID array/count/price all cross-checked against this
    # series' well-known real Pokémart prices (Potion=300, Super Potion=
    # 700, Antidote=100, etc. -- not just internally self-consistent).
    shop_buy_menu_id: int = 60
    shop_buy_arg_pointer_offset: int = 0x68
    shop_buy_arg_item_array_offset: int = 0x08
    shop_buy_arg_item_count_offset: int = 0x0C
    # Selecting a real item (not Cancel) opens a SECOND window alongside
    # the item grid (menu_id 60 stays in the list, unchanged, underneath)
    # for quantity entry -- derived from xd-decomp's `inputBuyNum__Fiiii`
    # (game/menuShop.s:1002), which calls `menuOpenCustom(0x3d, ...)`
    # (0x3d == 61 decimal, live-confirmed 2026-07-30 as this window's own
    # menu_id) and stores the chosen quantity into a global `NumValue`.
    # `symbols.txt` has two same-named `NumValue` symbols (different
    # translation units); live-disambiguated by reading both while raising
    # the quantity by one and keeping the address that actually moved
    # (0x804EA910: 1->2; the other candidate, 0x804EA9A4, stayed 0 the
    # whole time). The still-open item-grid window's own cursor position
    # is reused (via ShopBuyMenuModel) to know which item this quantity
    # applies to -- no separate item-identity read needed here.
    shop_buy_quantity_menu_id: int = 61
    shop_buy_quantity_value_address: int = 0x804EA910
    # Simple one-shot shop notifications -- no menu/cursor structure, just
    # "this message ID became the active GSmsg task, speak its resolved
    # text once." Found live 2026-07-30 in the SAME pocket_menu.fsys table
    # as the greeting (message 50601), sequentially numbered right after
    # it: "May I help you with anything else?" (50602) and "We look
    # forward to your next visit." (50603) were both independently
    # confirmed live earlier the same session as real, recurring active
    # GSmsg message IDs during ordinary shop play (visible in the
    # OPEN/CLOSE log cycle) well before their text was known. 50605-50608
    # (thank-you, insufficient-money, bag-full, bonus-item) are the same
    # table's own adjacent entries, real text but not yet independently
    # seen live -- kept as a set for exactly this reason (matching
    # yes_no_confirmation_parent_ids's own comment), so nothing breaks if
    # one turns out unused and more can be added once seen.
    shop_notification_message_ids: tuple = (
        50602, 50603, 50605, 50606, 50607, 50608,
        50616, 50617, 50618, 50619, 50622, 50623, 50624, 50625,
    )
    # Info-window messages `menus.progress_notification_focus` owns on the
    # shared GSmsg task array (see that method for why ownership is
    # partitioned by ID at all). Text is NOT stored here -- it is read from
    # the game's own loaded string tables at speak time. These are only the
    # IDs this reader is responsible for.
    #
    # Grouped by the table they live in, since that decides when they can
    # resolve at all:
    #   16001/16002, 50023, 50201-50203, 50459, 54001-54009  -- main.dol,
    #       always resident (purify-ready notices, level-up, evolution,
    #       item/money acquisition).
    #   50502, 50503-50511  -- the purification-ceremony family, in the
    #       Relic Stone map's own table (M3_shrine_1F/hologram_menu). Only
    #       resolvable while that map is loaded, which is exactly when they
    #       are shown. 50502/50507/50508/50509 were missing before: the
    #       ceremony's "opened the door to its heart", EXP total, RIBBON,
    #       nickname prompt and regained-move lines are the whole point of
    #       the screen, and the two "door isn't closed"/"can't be opened
    #       yet" refusals are the only feedback for a failed attempt.
    # All confirmed present in a local extraction of the owner's own image
    # (2026-08-04) and each one's raw template read back live through
    # RuntimeMessageCatalog.
    progress_notification_message_ids: frozenset = frozenset({
        16001, 16002,
        # Party held-item results from pocket_menu.fsys.  The preceding
        # 15050 switch prompt is owned by the reusable Yes/No reader;
        # these are the non-choice result/information windows it cannot
        # see.
        15051, 15052, 15053, 15054, 15055, 15056,
        50023,
        # TM/HM startup and the contained-move prompt.  XG renders these
        # through GSmsg rather than the ordinary dialogue page buffer.
        50037, 50038, 50039,
        50201, 50202, 50203,
        50459,
        50502, 50503, 50504, 50505, 50506, 50507, 50508, 50509, 50510, 50511,
        54001, 54002, 54003, 54004, 54005, 54006, 54007, 54008, 54009,
    })
    # Agate Day-Care map-local GSmsg ownership. The ordinary dialogue
    # reader can see 50709/50708 in its page buffer, but the middle flow is
    # rendered through windows 82/216 and never enters that buffer.
    daycare_choice_prompt_message_ids: frozenset = frozenset({50711, 50713})
    daycare_notification_message_ids: frozenset = frozenset({
        50710, 50712, 50714, 50715, 50716, 50717,
    })
    name_screen_parent_id: int = 104
    name_list_menu_id: int = 101
    name_list_labels: tuple = (
        "New Name", "Michael", "David", "Adam", "Exit",
    )
    name_keyboard_menu_id: int = 102
    name_keyboard_column_address: int = 0x804EA7A4
    name_keyboard_row_address: int = 0x804EA7A8
    name_input_address: int = 0x80429794
    # Player names stop at 7, but this same keyboard/buffer is reused by the
    # Name Rater for Pokemon nicknames, whose live struct allows 10 visible
    # characters. Reading only 7 made a successfully entered eighth-or-later
    # character look as though the key had done nothing.
    name_input_maximum: int = 10
    name_keyboard_labels: tuple = (
        "A", "B", "C", "D", "E", "F", "G", "H", "I", "J",
        "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T",
        "U", "V", "W", "X", "Y", "Z",
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
        "Exclamation mark", "Question mark", "Male symbol", "Female symbol",
        "Left double quote", "Right double quote",
        "Left single quote", "Right single quote",
        "Slash", "Hyphen", "Ellipsis", "Period", "Comma",
        "Back", "Done",
    )
    audio_mode_address: int = 0x8044DA73
    audio_stereo_mask: int = 0x04
    game_data_root: int = 0x804E88D8
    game_data_save_offset: int = 0xA8
    game_data_no_vibration_offset: int = 0x21
    window_max_nodes: int = 64
    # 58 is ordinary battle-command UI; 142 is its verified alternate.
    command_menu_ids: tuple = (58, 142)
    move_menu_ids: tuple = (57,)
    command_labels: tuple = ("Fight", "Item", "Pokemon", "Call")
    vs_menu_parent_id: int = 281
    vs_menu_id: int = 280
    vs_menu_labels: tuple = ("Quick Battle", "Group Battle", "Cancel")
    quick_battle_parent_id: int = 281
    quick_battle_menu_id: int = 164
    quick_battle_cursor: int = 0x804349CF
    quick_battle_labels: tuple = (
        "Battle VS CPU",
        "2-Player Battle",
        "Cancel",
    )
    challenge_menu_parent_ids: tuple = (281, 164)
    challenge_menu_id: int = 262
    challenge_menu_labels: tuple = (
        "Ultimate",
        "Hard",
        "Normal",
        "Easy",
        "Cancel",
    )
    quick_confirm_parent_id: int = 281
    quick_confirm_menu_id: int = 165
    quick_confirm_labels: tuple = ("YES", "NO")
    # VS Quick Battle uses direct C-stick move buttons and D-pad targets.
    vs_button_parent_id: int = 162
    vs_button_menu_id: int = 158
    # The target-selection screen (menuFightOpenTarget in menuFight.s) opens
    # one of two (menu_id, parent_id) pairs depending on which battler is
    # choosing a target: (0xA0/160, 0xA2/162) or (0xA3/163, 0x9F/159), per
    # static disassembly. Only the first pair has ever been seen live (one
    # 2026-07-25 sample) and handled by this project. The second pair is
    # NOT yet confirmed live -- added defensively since it's disassembly-
    # grounded, not a guess, but do not treat its presence here as proof
    # it's correct until an actual live sample is seen.
    vs_target_menu_ids: tuple = (160, 163)
    vs_target_alt_parent_id: int = 159
    # Ordinary Story-mode move targeting, live-confirmed menu ID 92.
    story_target_menu_id: int = 92
    story_target_fight_pokemon_ptr: int = 0x804EA650
    story_target_work_offset: int = 0x24
    story_target_item_stride: int = 0x78
    story_target_item_flags_offset: int = 0x04
    story_target_item_id_offset: int = 0x06
    story_target_selected_mask: int = 0x0200
    story_target_item_to_status: tuple = (
        (312, 55), (313, 64), (314, 56), (315, 65),
    )
    # Live-confirmed 2026-08-03: menu 92's logical cursor is already in
    # active-battler order: player 1, player 2, opponent 1, opponent 2.
    # HUD draw-order remapping caused Feebas to be announced while the game
    # selected Teddiursa.
    story_target_cursor_slots: tuple = (0, 1, 2, 3)
    vs_button_child_ids: tuple = (66, 68)
    vs_move_buttons: tuple = (
        "C-stick up", "C-stick right", "C-stick down", "C-stick left",
    )
    vs_move_record_base: int = 0x04
    vs_move_record_stride: int = 0x0C
    vs_move_record_name_offset: int = 0x00
    vs_move_record_max_pp_offset: int = 0x0A
    vs_move_record_current_pp_offset: int = 0x0B
    vs_move_actor_offset: int = 0x4C
    vs_move_actor_search_offsets: tuple = (
        0x40, 0x44, 0x48, 0x4C, 0x50, 0x54, 0x58, 0x5C,
    )
    vs_fight_pokemon_embedded_offset: int = 0x08
    vs_player_status_window_ids: tuple = (55, 64)
    vs_top_target_status_window_id: int = 56
    vs_bottom_target_status_window_id: int = 65
    move_status_size: int = 0x48
    move_record_base: int = 0x04
    move_record_stride: int = 0x0C
    move_record_name_offset: int = 0x00
    move_record_type_name_offset: int = 0x04
    move_record_type_id_offset: int = 0x08
    move_record_max_pp_offset: int = 0x0A
    move_record_current_pp_offset: int = 0x0B
    move_status_actor_offset: int = 0x40
    embedded_pokemon_offset: int = 0x04
    pokemon_moves_offset: int = 0x80
    pokemon_move_stride: int = 0x04
    pokemon_move_id_offset: int = 0x00
    pokemon_move_pp_offset: int = 0x02
    pokemon_move_pp_ups_offset: int = 0x03
    move_slot_count: int = 4
    maximum_move_id: int = 374
    maximum_move_name_chars: int = 32
    fight_floor: int = 0x804A1730
    fight_floor_battlers_offset: int = 0xDE44
    battler_slot_count: int = 8
    fight_pokemon_pokemon_offset: int = 0x04
    pokemon_current_hp_offset: int = 0x04
    pokemon_max_hp_offset: int = 0x90
    maximum_pokemon_hp: int = 9999
    maximum_nickname_chars: int = 11
    status_allocation_nickname_offset: int = 0x00
    status_allocation_max_hp_offset: int = 0x18
    status_allocation_target_hp_offset: int = 0x1A
    status_window_work_offset: int = 0xA8
    status_work_old_hp_offset: int = 0x00
    status_work_duration_offset: int = 0x02
    status_work_progress_offset: int = 0x04
    # Phase 1F semantic aliases and validation policy.
    fight_floor_root: int = 0x804A1730
    active_battler_array_offset: int = 0xDE44
    fight_trainer_side_stride: int = 0x6EF0
    # CORRECTED 2026-08-06 from 0xA04, which was 0x10 too high. Every term
    # is now confirmed by disassembly: fightFloor_GetFightSidePtr adds 0x14
    # (`addi r3, r3, 0x14` after `mulli r3, r0, 0x6ef0`),
    # fightSide_GetFightTrainerPtr adds 0x64, and
    # fightTrainer_GetFightPokemonPtr adds 0x97C -- 0x14 + 0x64 + 0x97C =
    # 0x9F4. Three other places in this codebase already built the address
    # from those components and so were always right; only this constant
    # disagreed, and its one consumer (health.py's "is this the player's
    # party?" range test for EXP tracking) failed silently by excluding the
    # player's first party slot. Prefer battle_identity.party_slot_address
    # over this constant.
    fight_trainer_first_pokemon_offset: int = 0x9F4
    fight_trainer_pokemon_stride: int = 0x300
    active_battler_slots: int = 8
    fight_out_fight_pokemon_offset: int = 0x04
    # fightSeqBasis sets these substitutions before opening message 20003.
    # _Digit is opcode 0x2F; msgCtrlVal+4 is opcode 0x0D's name pointer.
    fight_message_name_pointer_address: int = 0x804187D4
    # msgctrl opcode 0x0D (_EV_STR_BUF0), statically traced through
    # msgctrlSetValue's dispatch table; battle EXP message 20003 uses this.
    fight_message_ev_str0_address: int = 0x804EB1F0
    fight_message_move_pointer_address: int = 0x804187DC
    fight_message_digit_address: int = 0x804EB27C
    fight_pokemon_min_size: int = 0x96
    fight_pokemon_embedded_offset: int = 0x04
    health_nickname_offset: int = 0x52
    health_nickname_max_chars: int = 11
    maximum_plausible_hp: int = 9999
    status_allocation_size: int = 0x1C
    status_copied_nickname_offset: int = 0x00
    status_max_hp_offset: int = 0x18
    status_target_hp_offset: int = 0x1A
    status_animation_work_offset: int = 0xA8
    status_animation_old_hp_offset: int = 0x00
    status_animation_duration_offset: int = 0x02
    status_animation_progress_offset: int = 0x04
    health_stable_samples: int = 2
    health_remap_timeout_seconds: float = 2.0
    pokemon_level_offset: int = 0x11
    pokemon_condition_offset: int = 0x16
    pokemon_exp_offset: int = 0x20
    fight_out_stat_stages_offset: int = 0x7B0
    stat_stage_neutral_value: int = 6
    stat_stage_names: tuple = (
        "Attack", "Defense", "Special Attack", "Special Defense",
        "Speed", "Accuracy", "Evasion",
    )
    valid_major_conditions: tuple = (0, 3, 4, 5, 6, 7, 8)
    # Live-confirmed active-battler order: player 1, player 2, opponent 1, opponent 2.
    #
    # RETAINED FOR THE Ctrl+H SUMMARY'S SPEAKING ORDER ONLY. It is no
    # longer the source of truth for which SIDE a battler belongs to: the
    # 2026-07-25 handoff recorded the opposite interleaving ("player 0,
    # opponent 1, player 2, opponent 3"), and a positional tuple cannot be
    # right in both cases. `battle_identity.BattleIdentityResolver` now
    # derives ownership from the battler's own FightPokemon address
    # instead, which is exact and needs no assumption about array order.
    summary_slot_order: tuple = (0, 1, 2, 3)
    summary_slot_ownership: tuple = ("Player", "Player", "Opponent", "Opponent")
    # --- canonical battle identity (see battle_identity.py) --------------
    # FightFloor -> FightSide (+0x14, stride 0x6EF0) -> FightTrainer
    # (+0x64, stride 0x3744) -> party array (+0x97C, stride 0x300, 6 slots).
    # side 0 / trainer 0 / slot 0 therefore lands at floor + 0x9F4, which is
    # what fight_trainer_first_pokemon_offset now holds.
    fight_side_offset: int = 0x14
    fight_side_stride: int = 0x6EF0
    fight_trainer_offset: int = 0x64
    fight_trainer_stride: int = 0x3744
    fight_trainer_party_offset: int = 0x97C
    fight_trainer_party_slots: int = 6
    fight_sides: int = 2
    fight_trainers_per_side: int = 2
    # Pokemon struct fields used as identity. Species is already proven by
    # `Pokemon::getPokemonDataId` (0x8014B87C, `lhz r3, 0x0(r3)`), which
    # this profile's own verification signature table checks byte-for-byte.
    # The personality value comes from `getRnd__7PokemonCFv` (0x8014B874,
    # `lwz r3, 0x28(r3)`) and is independently corroborated by
    # Pokemon-XD-Code's `kPartyPokemonPIDOffset = 40`.
    pokemon_personality_offset: int = 0x28
    pokemon_species_offset: int = 0x00
    # FightOutPokemon switch state, from fightOutPokemon_GetIrekaetaFlag
    # (0x80148718, `lbz r3, 0x84f(r3)`) and
    # fightOutPokemon_GetIrekaeTargetEntryId (0x80148670,
    # `lha r3, 0x862(r3)`).
    fight_out_switched_flag_offset: int = 0x84F
    fight_out_switch_target_entry_offset: int = 0x862
    # get_exp_fight_pokemon_ptr (.sbss:0x804EB964) -- a FightPokemon*, the
    # Pokemon the game itself is crediting with experience. Written by
    # WS_STATUS_WINDOW (fightSeqSpAction.s:0x8021A1BC), which passes exactly
    # this pointer to fightPokemonToMenuLvupStatus before opening the
    # level-up stat window. Resolved from its @sda21 displacement
    # (r13 - 0x44BC) with r13 = 0x804EFE20, itself derived from
    # `lwz r30, -0x4C24(r13)` resolving to _ATTACK_MONS = 0x804EB1FC.
    exp_recipient_pointer_address: int = 0x804EB964
    # How many consecutive polls a battlefield slot's occupant must agree
    # before its identity is treated as settled. Matches
    # health_stable_samples so the two cannot disagree about when a
    # replacement has finished.
    identity_stable_samples: int = 2
    default_hp_summary_hotkey: str = "ctrl+h"
    # On-demand Shadow Pokemon Heart Gauge check (party.py's
    # heart_gauge_percent) -- usable anywhere in the overworld, not just
    # battle, per the project owner's explicit "both" request (Summary
    # screen narration + a dedicated hotkey), 2026-07-30.
    # Moved from ctrl+j to ctrl+s on 2026-08-16 at the project owner's
    # request. Nothing else claims ctrl+s -- every default lives in this
    # file, so check both this block and the entity-navigation block below
    # before assigning another.
    default_heart_gauge_hotkey: str = "ctrl+s"
    # One chord per party slot (Ctrl+1 .. Ctrl+6): speaks that slot's
    # nickname, level, HP, status, Heart Gauge and held item
    # without opening a single menu -- the project owner's explicit
    # request, 2026-08-18. Digits were free: every other default in this
    # file is a letter or punctuation, and Dolphin's own stock bindings
    # put save states on the function keys, not on Ctrl+digit.
    default_party_slot_hotkeys: tuple = (
        "ctrl+1", "ctrl+2", "ctrl+3", "ctrl+4", "ctrl+5", "ctrl+6",
    )
    # On-demand Pokédollar balance check, usable anywhere in the overworld
    # -- project owner's explicit request, 2026-07-30, during the shop
    # accessibility work.
    default_money_hotkey: str = "ctrl+m"
    # Overworld party roster (Hero.partyPokemon[6], NOT the FightPokemon
    # battle-wrapper struct -- these offsets are relative directly to the
    # raw Pokemon struct start, matching xd-decomp's pokemon.hpp layout).
    # SUPERSEDED an earlier hardcoded `hero_party_base` (0x80478F30), found
    # via a live plausibility-filtered MEM1 scan -- that address broke
    # mid-session because `now_savedata_ptr` (see savedata_pointer_address
    # above) is deliberately re-randomized every boot, so any fixed
    # address downstream of it is only ever valid for one boot. Static
    # trace of the real accessor, `heroBiosGetPokemonPtr`
    # (party[i] = hero + 0x30 + i*0xC4, bounds-checked against 6 slots),
    # confirms the array is INLINE in the hero struct, not a separate
    # allocation -- cross-checked against `heroBiosGetItemNormalPtr`
    # (hero+0x4C8), which is exactly 0x30 + 6*0xC4, i.e. the party array
    # ends precisely where the next field begins. Live-verified after the
    # old address went stale: resolved to a real, current party (Eevee
    # level 11, Teddiursa level 11). Must always be computed fresh via
    # `savedata_pointer_address` + `hero_offset` + `hero_party_offset`,
    # never cached, for the same randomization reason as hero_offset.
    hero_party_offset: int = 0x30
    hero_party_stride: int = 0xC4
    hero_party_slots: int = 6
    party_species_offset: int = 0x00
    party_current_hp_offset: int = 0x04
    party_max_hp_offset: int = 0x90
    party_level_offset: int = 0x11
    party_condition_offset: int = 0x16
    # The Pokemon record's own resolved ability index. Randomizers can
    # change this independently of vanilla species/personality ability
    # slots, so summary narration must prefer this live per-Pokemon byte.
    party_ability_index_offset: int = 0x1D
    party_nickname_offset: int = 0x4E
    party_nickname_max_chars: int = 11
    # Shadow ("Dark") Pokemon move override. `pokemonBiosGetDarkpokemonDataId`
    # (pokemonBios.s) reads a u16 at +0xBA on the normal Pokemon struct --
    # nonzero means this individual has a slot in the separate, persistent
    # `_deckDarkPokemon` array (deck.s/darkPokemonBios.s; pointer address
    # confirmed via xd-decomp's own config/GXXE01/symbols.txt), which holds
    # up to 4 "Dark Waza" (Shadow move) IDs per move slot, stride 0x18,
    # offset 0x0C. Live-confirmed 2026-07-30 against the project owner's
    # own Teddiursa: its normal move1-4 slots read {216, 287, 122, 232}
    # (122/232 = Lick/Metal Claw, already correctly narrated) while
    # _deckDarkPokemon[dark_id]'s waza array read {356, 369, 0, 0} -- the
    # first two slots' *real*, currently-usable moves, with the {0, 0} in
    # the last two slots confirming (not guessed) that a slot's own waza
    # value being 0 is precisely what distinguishes "not currently
    # shadow-locked" from "shadow-locked" -- no separate purification-flag
    # lookup needed, since a purified slot's own entry going to 0 is
    # exactly this same signal, self-updating without extra plumbing.
    dark_pokemon_data_id_offset: int = 0xBA
    deck_dark_pokemon_pointer_address: int = 0x804EBB60
    deck_dark_pokemon_stride: int = 0x18
    deck_dark_pokemon_waza_offset: int = 0x0C
    deck_dark_pokemon_init_dark_point_offset: int = 0x08
    # Heart Gauge (live purification progress). A *third*, separate
    # save-relative runtime array (distinct from both the normal Pokemon
    # struct and _deckDarkPokemon above): `DarkPokemon::getDarkPointDirect`
    # (pokemonStatusPokemon.s) reads a plain s32 at +0x24 of a record in
    # this array, indexed by the same dark_pokemon_data_id_offset ID.
    # Array base = savedata_base + darkpokemon_array_savedata_offset
    # (savedataBiosGetDarkpokemonPtr, savedataBios.s -- confirmed by reading
    # savedataGetStatus's actual .rodata jump table data directly, not by
    # inferring index-to-case order from code layout, after a first-pass
    # inference attempt risked a real off-by-several-indices mistake).
    # Denominator is the same deck_dark_pokemon_waza_offset record's
    # InitDarkPoint (+0x8) already used for the move override above.
    # Direction confirmed 2026-07-30 directly by the project owner: live
    # reading of 0 (fully drained) for their own Teddiursa matched their
    # own independent knowledge that it should currently be ready to
    # purify after extensive walking -- so dark point counts DOWN from
    # InitDarkPoint toward 0, and 0 means "fully open, ready to purify".
    darkpokemon_array_savedata_offset: int = 0xE380
    dark_pokemon_stride: int = 0x48
    # Byte 0 contains independent lifecycle flags, least-significant bit
    # first: bit 5 encountered, bit 6 caught, bit 7 purified. This is not a
    # low-three-bit enum. A caught, purified record commonly reads 0xE0.
    # The Pokemon's dark-data ID can remain nonzero after purification.
    dark_pokemon_flags_offset: int = 0x00
    dark_pokemon_purified_flag: int = 0x80
    dark_point_direct_offset: int = 0x24
    # Additional fields cross-checked directly against xd-decomp's real
    # decompiled `Pokemon` struct (include/game/pxdvs/app/pokemon/pokemon.hpp)
    # AND live-verified against the project owner's own OCR of the Info page:
    # `exp` read live as 1305 (matching OCR "1305" exactly, garbled by OCR as
    # "1 305"), `catchTrainerName` read live as "LEON" (matching OCR OT field
    # exactly), and nature computed as `rnd % 25` indexed into the standard
    # Gen 3 nature name order landed on "Bashful" (matching OCR exactly) --
    # this is strong independent confirmation of both the field offsets and
    # the personality-value-based nature formula, not a guess.
    party_item_offset: int = 0x02
    party_exp_offset: int = 0x20
    party_personality_offset: int = 0x28
    party_ot_offset: int = 0x38
    party_ot_max_chars: int = 11
    # Ribbon bitfield location matches pokemon.hpp exactly (+0x7C, right
    # before the already-verified `wazas` array at +0x80), but the live
    # value read back didn't plausibly decode as "no ribbons yet" for a
    # freshly-caught level-10 Eevee -- left unimplemented pending further
    # investigation into the Ribbon union's bit layout rather than shipping
    # a guess.
    party_ribbon_offset: int = 0x7C
    # Live-embedded abilities name/description table -- see resolver.py's
    # `LocalAbilityData` docstring for the full derivation and live
    # verification (Eevee's ability, index 50, resolved to "Run Away" /
    # "Makes escaping easier.", matching the project owner's OCR exactly).
    abilities_table_base: int = 0x803FFC50
    # The RECORD LAYOUT below is vanilla's, and is no longer read directly
    # by the lookup: Pokemon XG repacks this one table (stride 12 -> 8,
    # name +4 -> +0, description +8 -> +4) to fit 106 abilities where
    # vanilla had 78, while keeping the disc label, the DOL layout and
    # every engine signature identical -- so nothing outside the table can
    # tell the two builds apart. `ability_layout.derive_ability_layout`
    # reads the real values out of the three accessor instructions named
    # below instead. These three fields are kept as the documented vanilla
    # values and as the expectation the derivation is checked against.
    abilities_table_stride: int = 12
    abilities_name_id_offset: int = 4
    abilities_description_id_offset: int = 8
    # The three one-line accessors whose immediate fields ARE the layout;
    # see ability_layout.py for the full derivation and its verification.
    abilities_stride_instruction: int = 0x801442B0       # mulli r4, r3, N
    abilities_name_instruction: int = 0x80144290         # lwz r3, N(r3)
    abilities_description_instruction: int = 0x80144278  # lwz r3, N(r3)
    # "Do what with <Pokemon>?" action popup, opened from the party list.
    # Same custom-widget selection-index convention as the summary screen
    # (`+0x9F`), live-confirmed: incremented 0->1 on one D-pad-Down press.
    # Unlike the summary screen's 4 pages, this menu WRAPS (confirmed live
    # by the project owner: "menu wraps"). Labels and order confirmed via
    # the project owner's own OCR of the live menu.
    party_action_menu_id: int = 79
    party_action_index_offset: int = 0x9F
    party_action_labels: tuple = ("Summary", "Switch", "Item", "Cancel")
    # "Do what with an item?" popup, reached via the action menu's "Item"
    # option. Same widget/mechanism as party_action_menu_id above (same
    # class, `PartyActionMenuReader`, instantiated a second time with these
    # values) -- live-confirmed separately (own `menu_id` 93, index byte at
    # the same `+0x9F` offset changed 0->1 on request). Labels/order
    # confirmed via the project owner's own OCR ("GIVE"/"TAKE"(OCR-garbled
    # as "DTAKE")/"CANCEL").
    party_item_action_menu_id: int = 93
    party_item_action_labels: tuple = ("Give", "Take", "Cancel")
    # Bag/item menu's category tab row (accessed by moving the cursor up
    # from the item list into the tab row, then left/right). Same
    # `PartyActionMenuReader` widget pattern and `+0x9F` index convention,
    # reused a third time. Index-to-name mapping is NOT simple visual
    # left-to-right order -- it's a fixed per-category ID, confirmed one
    # category at a time via the project owner's own OCR at each step
    # (earlier rapid unverified text confirmations produced contradictory
    # readings for the same category, so this mapping was re-derived
    # slowly and carefully): 0=Items, 1=Balls, 2=TMs, 3=Berries,
    # 4=Key Items. Only the category itself is covered here -- scrolling
    # through the list of items WITHIN a category is a separate, harder,
    # still-unsolved problem (the item list appears to use a small number
    # of recycled/virtualized row render-nodes rather than one simple
    # index, unlike every other widget solved so far this session).
    bag_menu_id: int = 44
    bag_category_index_offset: int = 0x9F
    bag_category_labels: tuple = ("Items", "Balls", "TMs", "Berries", "Key Items")
    # Item-list row selection and per-category array layout, derived
    # entirely from static PowerPC disassembly (2026-07-29, per the
    # project's reverse-engineering philosophy) rather than blind memory
    # diffing -- see ACCESSIBILITY_COVERAGE_MATRIX.md's "Item name
    # resolution infrastructure" entry for the full derivation and
    # citations. `menuPocket2Cursor` reads the row position not from the
    # window struct at all, but from a small fixed global array
    # (`_cursor`, `cursorBios.s`), indexed by a per-category "cursor ID"
    # read from `menuPocket.cpp`'s own static `TabTbl` (cross-confirmed
    # against the already-OCR-verified category order: Items/Balls/
    # TMs/Berries/Key Items). Each cursor slot packs TWO halfwords
    # (`cursorBiosGetPos`'s x/y) that the game itself ADDS together to
    # get the true absolute row index within the filtered (empty-slot-
    # skipped) list -- x alone is only correct at zero scroll, so both
    # halfwords must be read and summed, not just the first.
    pocket_cursor_table_address: int = 0x80445BE0
    pocket_cursor_stride: int = 4
    bag_category_cursor_ids: tuple = (3, 4, 5, 6, 7)
    # Per-category hero-save item arrays, traced through
    # heroItemGetItemKindToItemAryPtr's kind dispatch into
    # heroGetStatus's own statusCode dispatch and its semantically-named
    # heroBiosGetItem*Ptr accessors (ItemNormal/ItemBall/ItemSkill/
    # ItemSeed/ExtraItem for Items/Balls/TMs/Berries/Key Items
    # respectively) -- each returns `hero + offset + index*4`, where
    # `hero` is the exact same base address `PartyMemorySource._hero_base`
    # already resolves (independently cross-confirmed: the party array's
    # own offset, 0x30 + 6*0xC4 party slots, lands exactly on 0x4C8,
    # where the Items array begins).
    bag_category_array_offsets: tuple = (0x4C8, 0x5EC, 0x62C, 0x72C, 0x540)
    bag_category_slot_counts: tuple = (30, 16, 64, 46, 43)
    # Each hero item-array slot is a plain 4-byte record: item ID
    # (u16) then quantity (u16); a zero item ID marks an empty slot to
    # be skipped when counting rows (item_GetItemDataId/item_GetNum,
    # itemCheckValid).
    hero_item_record_stride: int = 4
    hero_item_record_id_offset: int = 0x0
    hero_item_record_quantity_offset: int = 0x2
    # Overworld pause menu (`menu_id` 87). Same `+0x9F` convention.
    # Live-confirmed mapping: 0=Pokemon, 1=P?DA, 2=Items, 3=Save,
    # 4=Exit. The project owner confirmed the exact P?DA name.
    pause_menu_id: int = 87
    pause_menu_labels: tuple = ("Pokemon", "P star D A", "Items", "Save", "Exit")
    # These five are the CANDIDATE entries, not the on-screen rows. The
    # menu hides any the player has not unlocked -- before the P*DA is
    # obtained the screen shows only Pokemon/Items/Save/Exit -- so reading
    # the cursor position straight into the tuple above named the wrong
    # option for every row after the first (project owner, 2026-08-13:
    # "its everything but pda. pokemon items save exit").
    #
    # The game keeps the mapping itself. `menuTop` (0x8002F718) walks all
    # five candidates, tests each with `menuItemBiosGetSelectFlag`, and for
    # each visible one calls `menuTitleSetSelect(row, candidate)`, which
    # stores a s16 at `_menuTitleWork+0x40` indexed by row*2
    # (`sth r4, 0x40(r3)` at 0x800A31BC; `menuTitleGetSelect` reads the
    # same place with `lha`). So row -> candidate is a live read, and the
    # tuple above is only the candidate NAMES.
    #
    # _menuTitleWork = 0x8043D2A8 (lis 0x8044 / addi -0x2D58), +0x40 for
    # the array. Live-confirmed on a save that owns the P*DA: the table
    # reads (0, 1, 2, 3, 4) -- identity, which is exactly right when
    # nothing is hidden. It is in .bss, whose placement is identical in
    # both known builds.
    pause_menu_entry_map: int = 0x8043D2E8
    pause_menu_entry_stride: int = 2
    # Eevee evolution-stone selection screen (a dedicated 5-option menu,
    # not the general Bag) -- own new `menu_id`, live-confirmed the same
    # `+0x9F` index convention (diffed a full memory snapshot before/after
    # one real cursor move, then captured all 5 distinct index values
    # across a full cycle). The owning M6_junk_1F field script supplies the
    # item ID for each Dialogs::58 result: indices 0..4 select 97, 96, 95,
    # 517 and 516 respectively. Production resolves those IDs through the
    # loaded build's ItemDatabase; no English option names live here.
    stone_selection_menu_id: int = 175
    stone_selection_item_ids: tuple = (97, 96, 95, 517, 516)
    # Evolved-form IDs paired with the script's item order above. These are
    # the forms in Eevee's own evolution records, not display strings.
    stone_selection_species_ids: tuple = (134, 135, 136, 197, 196)
    # Party list screen itself (the 7-window screen shown when opening the
    # party from the overworld menu). Same `+0x9F` selection-index
    # convention as the summary screen and action popup; live-confirmed on
    # the screen's first/head window (menu_id 76): moving the selection
    # changed the index from 6 back to 0. With `hero_party_slots` == 6
    # (indices 0-5), index 6 is the one position beyond the last real
    # party slot -- interpreted as a "Cancel"/exit selection, not
    # independently confirmed by OCR (unlike the other two screens) since
    # the project owner only reported the index changing, not what index 6
    # visually is. Flagged as an inference, not a verified fact.
    party_list_menu_id: int = 76
    party_list_index_offset: int = 0x9F
    # Automatic (not hotkey-triggered) narration for the Pokemon summary
    # screen -- reacts to real page navigation, matching the project's
    # standing UX convention that in-game menus should be narrated by
    # tracking actual state changes, not read out on demand (the one
    # existing exception, BattleHPSummary, is a hotkey precisely because
    # battle HP is a passively-displayed value with nothing to navigate to,
    # unlike this screen which the player actively pages through).
    # `party_summary_menu_id` identifies the screen is open at all (found
    # live: this window's menu_id was 94 while the summary screen was
    # showing; the party list screen uses menu_ids 70-76 and never 94).
    # `party_summary_page_offset` is a live-confirmed page-index byte
    # (0=Info, 1=Status, 2=Moves, 3=Ribbons -- confirmed via the project
    # owner's own OCR of all 4 real pages, not guessed): watched 0->1->2->3
    # in lockstep with 3 real D-pad-Right presses, and stopped incrementing
    # at 3 (confirmed 4 total pages, no wraparound).
    party_summary_menu_id: int = 94
    move_learning_menu_id: int = 98
    party_summary_page_offset: int = 0x9F
    party_summary_page_count: int = 4
    # Static symbol `_menuStatus` (.bss:0x804297C8, size 0x48) -- the file-
    # static struct `_menuPokemonStatusOpen` populates when the summary
    # screen opens, and `menuPokemonStatusDrawStatus`/the L-R page-switch
    # callback both read from. `+0x0C` is the live `Pokemon*` currently
    # displayed -- NOT necessarily a party slot at all (PC box and
    # opponent summaries reuse the exact same field), so this is read
    # directly with PartyMemorySource.slot_for_pointer() rather than
    # mapped back to a party index. Confirmed by static trace that this
    # is written on open, on every L/R party-switch, and is the sole
    # source the draw code reads -- this replaces the old hardcoded
    # "always slot 0" behavior that broke once a second party member
    # existed. Window ID 0x5E (94) matches party_summary_menu_id exactly,
    # corroborating the derivation.
    party_summary_pokemon_pointer: int = 0x804297D4
    # Stat block immediately after max HP (+0x90): 5 more u16 values,
    # live-confirmed plausible (level 10 Eevee: 18/18/14/18/18) and matching
    # xd-decomp's documented "stats(0x90-0x9a)" field range exactly. Field
    # ORDER (Attack/Defense/SpAtk/SpDef/Speed) is the standard Gen 3 stat
    # layout convention, assumed but not independently distinguished field-
    # by-field from the live data (the sampled values were too close to each
    # other to disambiguate order); re-verify against a Pokemon with more
    # asymmetric stats if this order is ever in doubt.
    party_attack_offset: int = 0x92
    party_defense_offset: int = 0x94
    party_special_attack_offset: int = 0x96
    party_special_defense_offset: int = 0x98
    party_speed_offset: int = 0x9A
    # Move slots, live-confirmed against real resolved move names (Tackle,
    # Tail Whip, Bite, Sand-Attack -- all genuine early-level Eevee moves).
    # Reuses the already-verified battle-context field layout (pokemon_moves_
    # offset/pokemon_move_stride/pokemon_move_id_offset/pokemon_move_pp_offset,
    # defined above) since it's the same underlying Pokemon struct, not a
    # battle-specific wrapper.
    # Verified field-dialogue controller (ordinary Character.talk path).
    dialogue_manager_root: int = 0x804E8348
    dialogue_manager_tasks_offset: int = 0x1C
    dialogue_task_back_offset: int = 0x20
    dialogue_task_size: int = 0x80
    dialogue_message_start_offset: int = 0x48
    dialogue_page_start_offset: int = 0x4C
    dialogue_page_end_offset: int = 0x50
    dialogue_type_address: int = 0x804E8380
    dialogue_type: int = 3
    dialogue_window_id: int = 82
    dialogue_printing_offset: int = 0xA4
    dialogue_advancing_offset: int = 0xA5
    dialogue_max_page_bytes: int = 0x1000
    # Scripted/cutscene dialogue speaker name: msgctrl.cpp's "_Npc" .sbss
    # global (msgVar 89), set by peopleTalkMsg -> charNameBiosGetNameID ->
    # msgctrlSetValue(89, nameMsgID). Resolves through the general
    # common.rel message table (entity_names.ScriptedSpeakerNameTable),
    # not the PeopleIDs-keyed table load_entity_names builds. Address
    # found by disassembling msgctrlSetValue's jump table (case 89-13=76);
    # live-verified reading "JOVI" during a real conversation, matching
    # the actual on-screen speaker.
    scripted_speaker_message_id: int = 0x804EB2CA
    # Verified generic overworld player/NPC structures.
    hero_leader: int = 0x804479F0
    hero_model_resource_ids: tuple = (100, 101, 104, 105)
    resource_list_head: int = 0x804EB008
    resource_node_size: int = 0x18
    resource_state_offset: int = 0x01
    resource_data_offset: int = 0x04
    resource_group_offset: int = 0x08
    resource_id_offset: int = 0x0C
    resource_next_offset: int = 0x14
    resource_max_nodes: int = 4096
    model_position_offset: int = 0x18
    model_rotation_offset: int = 0x24
    # The camera's world yaw, as the engine itself reads it: cameraGetRotY()
    # is `lwz r3, pCamWork; lfs f1, 0x14(r3)`. pCamWork is written exactly
    # once, at camera init, to _cameraWork -- but it is dereferenced here
    # rather than hardcoded, matching the engine.
    #
    # This replaces an earlier `_activeCamera + 0x88` read that was verified
    # live to be a dead field: it held exactly 0.0 across 811 samples while
    # the real yaw swung through 67 degrees. Cross-checked against
    # gCameraRotY (0x804EB128) and against the same struct's height/distance
    # at +0x40/+0x44, which match gCameraHeight/gCameraDistance exactly.
    camera_work_pointer: int = 0x804E84B0
    camera_work_rot_y_offset: int = 0x14
    current_floor_id: int = 0x80814AB6
    floor_data_count_root: int = 0x804E8A30
    floor_data_root: int = 0x804E8A34
    floor_data_stride: int = 0x40
    floor_data_max_records: int = 1024
    floor_id_offset: int = 0x02
    floor_character_slot_offset: int = 0x0C
    floor_character_stride: int = 0x24
    floor_character_max_records: int = 256
    floor_character_visible_mask: int = 0x80
    floor_character_people_info_offset: int = 0x06
    floor_character_name_offset: int = 0x08
    people_info_count_root: int = 0x804E88A0
    people_info_root: int = 0x804E88A4
    people_info_stride: int = 0x34
    people_info_talk_distance_offset: int = 0x24
    people_info_max_records: int = 4096
    people_info_id_offset: int = 0x04
    """The record's OWN id. `peopleInfoBiosGetPtr` linear-searches for a
    record whose +0x04 equals the requested id -- it is not an array
    index, which is how `NPCMemorySource` read it. See
    people_runtime.PeopleRuntimeSource.people_info."""
    people_info_neck_index_offset: int = 0x01
    """`peopleInfoBiosGetNeckIndex` -- SIGNED byte. Negative means the
    actor has no neck joint and the engine falls back to its base
    position."""
    people_info_col_ball_offset: int = 0x10
    """`peopleInfoBiosGetColBallSize`. Two of these -- the hero's and the
    target's -- are terms in the game's own talk-distance threshold."""
    floor_data_group_id_offset: int = 0x2C
    floor_data_group_id_slots: int = 5
    """`floorDataBiosGetGroupID` reads `floorData + 0x2C + 4 * L` for a
    language index L derived from `pokecoloGetLanguage()`. That global has
    not been located, so the whole slot range is read and membership is
    the test rather than guessing L. Documented in
    people_runtime.floor_group_ids; widen to an exact slot once the
    diagnostic pins which one matches."""
    default_interaction_radius: float = 10.0
    interaction_collision_allowance: float = 1.5
    interaction_ready_default_radius: float = 10.0
    """Zone radius for interactables that carry no interaction_distance of
    their own (PCs, signs, the Relic Stone). Entities that DO carry one --
    NPCs, treasure -- use theirs plus interaction_collision_allowance
    instead. Not derived from game data; expect to tune by ear."""
    interaction_ready_hysteresis: float = 3.0
    """Distance margin before an announced target counts as left, so
    standing on the edge of a zone cannot re-announce repeatedly."""
    interaction_ready_facing_hysteresis: float = 15.0
    # Room ID changes before the old room's actor array is replaced. Live
    # 2026-08-15: that gap falsely exposed Jovi for 1.2 seconds in Lab 1F.
    interaction_ready_map_change_grace: float = 2.0
    """Extra degrees on top of talk_cone_degrees before an announced target
    counts as turned away. Facing changes with every step in a game with no
    turn-in-place, so without this the cue would retrigger constantly while
    the player shuffles in place."""
    talk_cone_degrees: float = 40.0
    """Half-angle of the cone the game itself requires the player to be
    facing within before an NPC will talk. NOT a guess: `updateChat()`
    (heroMove.s, 0x8014FCF8) calls `peopleTalkCheck` with the literal float
    constants 0.3 and 40.0, and peopleTalkCheck (0x802A3444) computes
    `f26 = 0.017453292 * 40.0` -- that constant is pi/180, so f26 is
    radians(40). It then rejects the talk outright when
    `fabs(peopleVecCalcRotY(playerPos, npcNeckPos, playerRotY)) > f26`,
    where peopleVecCalcRotY returns the signed angle between the direction
    to the NPC and the player's own rotation, normalised to (-pi, pi].

    Since this game has no turn-in-place, the player's facing is just
    whichever way they last walked -- so arriving beside an NPC while
    pointed the wrong way is the normal outcome of navigating by audio, and
    entity-nav previously reported "In interaction range" on distance alone
    with no hint that the game would refuse.

    The game's distance rule in the same function is
    `distance(player, npcNeckPos) <= 0.3 + talkDistance + colBallSize`
    (colBallSize = people_info + 0x10, talkDistance = people_info + 0x24).
    This project still approximates that with a horizontal distance against
    `interaction_collision_allowance` instead; it has matched live
    behaviour so far, so it is deliberately left alone rather than changed
    speculatively alongside the facing fix."""
    floor_character_talk_offset: int = 0x14
    """The NPC's talk SCRIPT id -- `floorCharacterBiosGetTalkSctID` is
    `lwz r3, 0x14(r3)`. This is what identifies a role: an NPC whose talk
    script calls `Dialogs::openPokemartMenu` is a Mart clerk, in every
    shop in the game. See npc_roles.py. It replaced a `pokemart_room_ids`
    room list here and a `{0x85: nurse, 0x86: clerk}` table in
    phase1b_app, both of which labelled every NPC in the room."""
    floor_character_position_offset: int = 0x18
    npc_sound_max_distance: float = 120.0
    # Restored 2026-08-06 alongside the NPC-source revert: the passive Mart
    # beacon uses this again rather than the (correct but unvalidated)
    # talk-script role table, so the whole NPC path is back to exactly what
    # was live-validated. Known-wrong: it gives the Mart beacon to every NPC
    # in Agate's shop and to no clerk anywhere else. Replace it with
    # npc_roles.NPCRoleResolver once Phase 2 is live-validated.
    pokemart_room_ids: tuple = (0x86,)
    # Live "people" runtime-actor table (pxdvs/app/people/peopleBios.cpp's
    # _pPeopleWorkTop / _people_num, addresses from xd-decomp's own
    # config/GXXE01/symbols.txt). Cross-referenced against floor_character
    # records by index because floor_character's own "visible" bit is
    # confirmed (live, two independent room samples) to go stale once a
    # story event hides a character without a matching update to that bit
    # -- e.g. Krane stayed "visible=True" in floor_character on the Lab 2F
    # after being kidnapped, while this table's disp byte correctly read 0.
    # identity_a_offset == 0 is the game's own sentinel for the special
    # partner/follower character slots (see floorCharacterBiosFindByResID's
    # groupID==0 branch, which redirects to _globalCharacter instead of the
    # normal per-floor character array) -- excluded so those reserved IDs
    # never collide with a real room's small per-index identity_b values.
    people_work_count_address: int = 0x804EBBB8
    people_work_root_address: int = 0x804EBBBC
    people_work_stride: int = 0x1B0
    people_work_max_records: int = 256
    people_work_occupied_offset: int = 0x00
    people_work_disp_offset: int = 0x0D
    people_work_identity_a_offset: int = 0x14
    people_work_identity_b_offset: int = 0x18
    people_work_flags_offset: int = 0x10
    """`peopleBiosCheckFlag(actor, mask)` is `(*(u32*)(actor+0x10)) & mask`.
    `peopleTalkCheck` skips any actor with bit 0 set, so an NPC can be
    fully spawned, displayed and in range and still be untalkable."""
    people_work_people_info_offset: int = 0x1C
    """The actor's people-info ID, passed to `peopleInfoBiosGetPtr`. Must
    agree with the paired `floor_character +0x06`; a mismatch means the
    live/static correlation is wrong."""
    people_work_rot_y_offset: int = 0x40
    """The actor's own facing. `peopleTalkCheck` reads it from the HERO's
    record (`lfs f1, 0x40(r31)`) for the talk-cone test."""
    people_work_talk_distance_offset: int = 0x178
    """`peopleGetTalkDistance` is `lfs f1, 0x178(r3)` on the people_work
    record -- a LIVE per-actor field. Not `people_info +0x24`, which is
    what this project read before. Whether the static field initialises
    this one is unverified; the diagnostic logs both."""
    people_work_model_offset: int = 0x08
    """The actor's model pointer -- the route to where the NPC ACTUALLY is,
    as opposed to floor_character's scripted spawn position. Straight from
    the engine: peopleBiosGetPosPtr (0x80297724) is `lwz r3, 0x8(r3)`
    followed by GSmodelGetPositionPtr (0x800F7B30), which is just
    `addi r3, r3, 0x18` -- i.e. model_position_offset, the same offset the
    hero model already uses here."""
    # Entity navigation ("item navigation"): read-only selection/description
    # of overworld entities. Never sends input. NPC category only in this
    # slice; treasure category to be added after live verification.
    default_entity_next_hotkey: str = "ctrl+period"
    default_entity_prev_hotkey: str = "ctrl+comma"
    default_entity_next_category_hotkey: str = "ctrl+shift+period"
    default_entity_prev_category_hotkey: str = "ctrl+shift+comma"
    default_entity_repeat_hotkey: str = "ctrl+slash"
    # There is no refresh hotkey. It held ctrl+shift+slash until
    # 2026-08-16, when the project owner asked for autowalk on that chord
    # and then, told what refresh had been for, removed it outright rather
    # than rehome it. Nothing was lost that had ever worked: `ctrl+slash`
    # (repeat) matched every ctrl+shift+slash press, and `poll_once` tested
    # repeat first, so refresh had never once run in production. Picking up
    # entities that appeared after a category was activated is still
    # reachable -- switching category away and back re-reads the live list.
    default_autowalk_hotkey: str = "ctrl+shift+slash"
    """Autowalk toggle, moved here from ctrl+w on 2026-08-16 at the project
    owner's request. It had taken over ctrl+w from the Lab 2F
    forward-collision diagnostic, which was deleted in that change -- a
    single-room development probe whose one real consumer,
    `predict_forward_collision`, is used directly by
    `terrain_footsteps.BlockedMovementReader` and `pathfinding.py` and was
    untouched by its removal. ctrl+w is now unbound.

    This chord only became usable the same day: until then `ctrl+slash`
    (repeat) matched every ctrl+shift+slash press too, because a chord was
    tested with `all(held)` and never checked that the modifiers it does
    NOT name were up. See `hotkeys.WindowsForegroundHotkey._pressed`."""
    default_interaction_mark_hotkey: str = "ctrl+k"
    """Development-only marker for the interaction diagnostic. Deliberately
    NOT one of the entity-nav chords: it has to be pressable immediately
    before or after A without disturbing the selection being measured.
    `ctrl+m` was the obvious pick and is already the money summary --
    every other default is listed in this same block, so check here before
    adding another."""
    # Audio guide: continuous "hot/cold" spatial tone toward whatever is
    # currently selected in entity navigation (works for any category,
    # including doors/warps -- selecting a door and guiding to it, then
    # selecting the real target in the new room, is how cross-room
    # guidance composes with the already-existing category system without
    # needing separate automatic room-to-room routing).
    # Two modes, split 2026-08-04 at the project owner's request. "g" is a
    # plain beacon sitting ON the selected entity: the straight line to it,
    # nothing else. "n" is the obstacle-aware routed navigation (waypoints,
    # walk-model routing, the whole navigation_service stack) that "g" used
    # to carry. Only one runs at a time -- see audio_guide.py's `peer`.
    default_audio_guide_hotkey: str = "ctrl+g"
    default_navigation_guide_hotkey: str = "ctrl+n"
    audio_guide_max_distance: float = 120.0
    audio_guide_arrival_distance: float = 4.0
    # Teleport to whatever entity-nav currently has selected -- the only
    # memory WRITE in this project, at the project owner's explicit
    # request/risk acceptance. See teleport.py's module docstring for the
    # full safety scoping (entity-nav-resolved targets only, never a
    # free-typed coordinate; player's own Y used for non-NPC categories
    # since their Y is a CCD trigger centroid, not real floor height).
    default_teleport_hotkey: str = "ctrl+t"
    # Autowalk: the SECOND memory-writing feature, added 2026-08-16 at the
    # project owner's explicit direction ("you may void the read only
    # philosophy for this time"). Unlike teleport it does not write the
    # player's position at all -- it writes the game's OWN scripted-stick
    # override and lets the engine walk the character normally. See
    # hero_stick.py for the full derivation; the short version is below.
    #
    # `HeroMove` (0x804479F0, pinned by the lis/addi pair at the top of both
    # accessors) carries a five-byte block the engine uses to drive the hero
    # from script instead of from the controller:
    #
    #   +0x3AE  override active flag
    #   +0x3AF  left stick X   \  written together by _setStickData
    #   +0x3B0  left stick Y    | (0x8014E7D4), read back by _getStickData
    #   +0x3B1  left stick X'   | (0x8014E7F8), which checks the flag FIRST
    #   +0x3B2  left stick Y'  /  and returns these instead of the pad.
    #
    # The pairs are the smoothed and unsmoothed reads of the same stick
    # (GSinputGetLeftStick{X,Y}Data called with the second argument 1 then
    # 0 on the non-override path); a steady hold makes them equal, which is
    # what autowalk writes. The game uses this itself in
    # _heroMoveSlowStopFactor (0x8014EDF4), which captures the live stick,
    # decays it over successive frames through _setStickData, then clears
    # the flag -- i.e. this is the engine's own path, not an injected one.
    hero_move_base: int = 0x804479F0
    hero_move_stick_override_offset: int = 0x3AE
    hero_move_stick_data_offset: int = 0x3AF
    # Full stick deflection, as the engine itself writes it: _getStickData's
    # D-pad path stores +/-0x38 (56) for each direction. Independently
    # matches the +/-56 full deflection movement_input.py measured live from
    # the controller cache on 2026-08-03.
    hero_move_stick_full_deflection: int = 0x38
    default_autowalk_arrival_distance: float = 4.0
    """Shared with the audio guide's own arrival radius on purpose: "close
    enough to interact with" is one fact about the game, and having autowalk
    stop somewhere the guide would still be calling out would be incoherent."""
    # "item"/"healing" reuse npc_beacons.py's verified, hand-curated
    # per-floor ITEMS/HEALING lookups (see entity_sources.
    # CategoryFilteredEntitySource) -- real names, but only covers the
    # floors already manually mapped there, not every floor generically.
    # "elevator"/"door" come from the authoritative common.rel interaction
    # table + CCD collision data instead (authoritative_warps.py's
    # AuthoritativeElevatorEntitySource/AuthoritativeDoorEntitySource),
    # covering every room in the game, same as "warp".
    # "door" was restored to the cycle at the project owner's request on
    # 2026-08-15. Doors also retain their passive beacon. A door sharing
    # its region with a warp is published silent, since the warp already
    # sounds from that exact point -- see AuthoritativeDoorEntitySource.)
    # The three tuples are positional and
    # must stay index-aligned; dropping an entry from one alone would
    # silently relabel every category after it.
    # "bridge" is its own category at the project owner's request
    # (2026-08-09): Gateon Port's piers rotate under the player with no
    # visual cue, so "which way can I cross right now" is a question of its
    # own, not a variety of warp. The source publishes only the connections
    # the LIVE alignment enables, so the category is empty -- and therefore
    # skipped by the cycle -- everywhere except on the pier.
    # "hazard" added 2026-08-09 (Phase 4): `hero_fall` regions are holes a
    # blind player has no way to perceive, and nothing in this project
    # warned about them. They are a WARNING category, not a destination --
    # see ENTITY_STATE_AND_BEACON_POLICY.md. Listed last so it never sits
    # between two categories the player cycles routinely.
    entity_nav_category_keys: tuple = (
        "npc", "item", "door", "interact", "exit", "bridge", "hazard")
    entity_nav_category_singular_labels: tuple = (
        "NPC", "Item", "Door", "Interactable", "Exit", "Bridge", "Hazard")
    entity_nav_category_plural_labels: tuple = (
        "NPCs", "Items", "Doors", "Interactables", "Exits", "Bridges", "Hazards")
    """Seven cycling categories, minus Pokemon until its actor distinction
    is established. Elevators and Warps remain grouped as **Exits**; Signs
    remain folded into **Interactables**; Doors and Gateon Bridges are
    separate categories.

    These are CYCLING groups, not entity types. `Entity.category` still
    says warp/elevator/bridge/sign, because the beacon sounds,
    `interaction_announcer`'s verbs and `interaction_ready`'s walk-into set
    all key on it. Regrouping what the player pages through must not
    rewrite what each entity is."""
    # Uncalibrated, documented game-unit thresholds (see entity_nav.py).
    entity_nav_same_position_threshold: float = 1.5
    entity_nav_vertical_threshold: float = 3.0
    entity_nav_auto_repeat_seconds: float = 1.0
    """How long the player must stand still before the current selection is
    re-announced without them pressing anything (see
    `EntityNavigator._poll_auto_repeat`). Requested value; not tuned by ear.
    Was 1.5 on first delivery, lowered to 1.0 at the project owner's request
    (2026-08-12) after using it.

    Fires ONCE per stop. Walking again re-arms it, so holding position never
    produces a repeating announcement."""
    entity_nav_auto_repeat_movement_epsilon: float = 0.5
    """Per-poll displacement, in game units, below which the player counts as
    standing still for the auto-repeat above.

    Reuses the value `navigation_service.STALL_MOVEMENT_EPSILON` already uses
    for the same physical question -- "is the player actually moving" --
    rather than introducing a second number for it. At the measured 17-35
    units/s of real walking, a moving player clears this in a single poll."""
    # Warp category -- UNVERIFIED/TENTATIVE, see ENTITY_NAVIGATION.md and
    # entity_sources.WarpEntitySource's docstring. Originally labeled
    # "treasures" by an unverified diagnostic script; live testing strongly
    # suggested these are actually elevator/floor-transition points.
    warp_count_root: int = 0x804E88F0
    warp_data_root: int = 0x804E88F4
    warp_record_stride: int = 0x1C
    warp_record_max: int = 512
    warp_position_offset: int = 0x10
    # The warp table has no floor-ID field (appears to be one global table
    # for the whole game -- confirmed live: 115 of 116 records were
    # offered regardless of the player's actual floor before this was
    # added). Distance is a practical stand-in for floor scoping.
    warp_max_distance: float = 120.0

    @property
    def label(self):
        return f"{self.title}, {self.region}, {self.game_id.decode()}, revision {self.revision}"


XD_US_REV0 = AddressProfile()











