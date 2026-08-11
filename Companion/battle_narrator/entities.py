"""Generic, source-agnostic overworld entity representation for entity navigation.

Kept deliberately tiny: the navigator consumes this shape only, never any
category's own memory-source internals directly.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Entity:
    category: str
    identity: tuple
    label: object  # str or None -- never invented, only a verified name
    position: object  # duck-typed: exposes .x, .y, .z game-unit floats
    interaction_distance: object = None  # float game units, or None if not applicable
    subtype: object = None
    metadata: dict = field(default_factory=dict)
