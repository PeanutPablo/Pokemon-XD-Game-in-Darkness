# Shadow Pokémon controlled live-test plan

Read-only and one action at a time. Never automate movement, battles, saving, purification, item use, or confirmation. Make named states before irreversible events.

## Protocol

Record build/hash, Dolphin version, state, location, slot, and Shadow ID. Take two stable snapshots before/after. Capture screen text, message IDs, companion output, ordinary/static/persistent records. Stop on implausible pointers; never write.

## Tests

1. **Identity:** ordinary Pokémon expects ID 0/no Shadow narration; active Shadow expects valid nonzero ID and visible-state agreement.
2. **Gauge:** record initial/current/nature/flags, perform exactly one controlled activity, reread; repeat twice before deriving rate.
3. **Move unlock:** named pre-gate state, record ordinary IDs/overrides, trigger only progress, capture restoration message and immediate transition. Do not assume quarters from one sample.
4. **Reverse Mode:** sample flags before actions, capture exact entry message/state, Call once, capture exit and gauge delta. Use authoritative state/message, not probability.
5. **Purification:** before/after status, gauge, stored EXP/friendship, moves, level/EXP, ribbons, trainer data; manually capture every Relic/Chamber page. Pass requires status 4 and inactive predicate even if ID persists.
6. **Encounter lifecycle:** separate spectator, battle, failure/loss, Miror B rematch, snag states; confirm 0→1/2→3 and test flee/weight labels.
7. **XG deltas:** first identify installed patched bytes/data or authoritative build source, then paired retail/XG observations. Comments alone fail validation.

Each result needs named before/after states, timestamped logs, decoded fields, screen text, the single intervening action, and Confirmed/Rejected/Unknown verdict.

