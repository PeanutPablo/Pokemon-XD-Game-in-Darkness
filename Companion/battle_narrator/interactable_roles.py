"""Semantic classification of room-script interaction handlers.

Sibling of `npc_roles.py`, pointed at the 0x0100 interaction records
instead of NPC talk scripts. Same principle: the label is this project's,
the **membership test is entirely the game's**.

Why direct calls, not reachability
----------------------------------
`npc_roles` follows `call` edges transitively, which is right for a talk
script that delegates to a helper. It is wrong here: room scripts share
generic helpers, and transitive reachability made `center_elevator_open`
"reach" `Player::healParty` and half the room's furniture reach everything
else. Classification therefore uses the handler's OWN standard-library
calls. Every marker below was checked for exclusivity across all 89
handlers before being adopted.

Marker evidence (direct calls, 2026-08-09)
------------------------------------------
| Marker | Handlers that make it | Class |
|---|---|---|
| `Player::57` | `bed_de_kaihuku`, `bed_recovery`, `check_mana_bed`, `ev_bed` | bed |
| `Character::101` + `Player::countPartyPkm` | `recover`, `recovery_d5_factory_2f`, `recovery_m2_enter_1f`, `recovery_s2_building_1f_2`, `tako_machine` | healing machine |
| `UnknownClass38::50` | `watch_tv`, `watch_tv_l`, `watch_tv_r`, `watch_monitor_tv` | television |
| `UnknownClass60::16` | `esa_set` | PokéSpot plate |
| `Player::countPurfiedPkm` + `UnknownClass50::17` | `check_shrine` | Relic Stone |
| `Dialogs::openPokemartMenu` | `auto_sales` | vending machine |
| `Character::76` + `UnknownClass38::42` | `hero_fall` | fall hazard |

**Two markers had to be tightened, and the reason is worth recording.**
The first exclusivity pass was keyed on the handler NAME, taking one
representative record per name -- which is wrong, because the same name in
two rooms is two different functions with different bodies. Re-run
per-record, `Character::76` alone also matched a `check_bookshelf` variant
in `M5_apart_1F`, and `Player::countPurfiedPkm` alone also matched
`talk_131_beedy`, a fortune-teller's talk function. Both would have shipped
a confidently wrong label -- a bookshelf announced as a hole, and an NPC's
interaction region announced as the Relic Stone. Each marker is now a
conjunction verified against all 241 records, and
`test_interactables.RealTableTests` re-checks the counts against the
generated asset.

Two results worth stating because they were *not* guessable from the name:

- **`tako_machine` is a healing machine.** It calls `Character::101`
  (`useHealingMachine`) and `Player::countPartyPkm` directly, exactly as
  the Pokémon Centre `recovery_*` handlers do. Six records across the
  Cipher Lab, Citadark and the HQ Lab.
- **`UnknownClass38::50` picks out precisely the four television
  handlers** and nothing else, so "Television" is behaviour-derived rather
  than name-derived. `watch_tv_l` / `watch_tv_r` make no message call at
  all, only the transition -- they play something rather than print.

`Player::countPurfiedPkm` also appears in `talk_131_beedy`, an NPC talk
function. That is not a 0x0100 record and never reaches this table.
"""

BED = "bed"
HEALING = "healing"
TELEVISION = "television"
PLATE = "plate"
SHRINE = "shrine"
VENDING = "vending"
FALL = "fall"

LABELS = {
    BED: "Bed",
    HEALING: "Healing machine",
    TELEVISION: "Television",
    PLATE: "PokeSpot plate",
    SHRINE: "Relic Stone",
    VENDING: "Vending machine",
    FALL: "Hole",
}
GENERIC_LABEL = "Interactable"
"""For a press-A record whose handler matches no marker. This is the
ABSENCE of a label, not a guessed one: the record itself proves the engine
dispatches a room handler when the player interacts at that region, which
is a fact. What the handler then does is what remains unknown."""

MARKERS = (
    # (class, required direct calls). First match wins, so the more
    # specific pairs are listed before any single-call marker.
    (HEALING, ("Character::101", "Player::countPartyPkm")),
    (BED, ("Player::57",)),
    (TELEVISION, ("UnknownClass38::50",)),
    (PLATE, ("UnknownClass60::16",)),
    # Conjunctions, not single calls: `countPurfiedPkm` alone also hits a
    # fortune-teller's talk script, and `Character::76` alone also hits a
    # bookshelf. Verified per-record across all 241.
    (SHRINE, ("Player::countPurfiedPkm", "UnknownClass50::17")),
    (VENDING, ("Dialogs::openPokemartMenu",)),
    (FALL, ("Character::76", "UnknownClass38::42")),
)

HAZARD_CLASSES = frozenset({FALL})
"""Hazards are warnings, not destinations. See
ENTITY_STATE_AND_BEACON_POLICY.md."""

PRESS_A_METHOD = 3
"""`+0x00`. Method 3 is "stand inside and press A" across all 832
interaction records in both marker families; 1 and 2 fire on entry."""


def classify(direct_calls):
    """Semantic class for a handler, from its own direct calls. None when
    no marker matches -- which is a real answer, not a failure."""
    calls = set(direct_calls or ())
    for name, required in MARKERS:
        if all(call in calls for call in required):
            return name
    return None


def build_table(records):
    """`{record index: class}` for records whose handler is classified.

    `records` is an iterable of (index, direct_calls). Unclassified
    records are simply absent, and the source decides what to do with
    them by method."""
    table = {}
    for index, direct_calls in records:
        name = classify(direct_calls)
        if name is not None:
            table[index] = name
    return table
