"""The neck-joint resolver, against a synthetic JObj hierarchy.

Every case here corresponds to a divergence from the engine found by
re-tracing `HSD_JObjWalkTree` / `GSpartGetTransform` on 2026-08-09, after
live samples produced neck offsets of 11.32 and 40.92 units against a 4.0
collision ball.
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from battle_narrator.memory import MemoryReader
from battle_narrator.model_parts import (
    JOBJ_MATRIX_DIRTY_FLAG, JOBJ_MATRIX_TRUSTED_FLAG, JOBJ_NO_DESCEND_FLAG,
    MODEL_BLENDING_FLAG, MODEL_PART_INDEX_BIAS_FLAG, NeckPositionResolver,
)
from battle_narrator.npc_beacons import Position
from battle_narrator.profile import XD_US_REV0


BASE = 0x80600000
MODEL = BASE
JOBJ = BASE + 0x1000
JOBJ_STRIDE = 0x100

# A joint whose matrix the engine would trust as-is: the "needs rebuild"
# combination is (trusted clear AND dirty set), so setting trusted is the
# simplest way to say "this one is current".
CLEAN = JOBJ_MATRIX_TRUSTED_FLAG


class Backend:
    def __init__(self):
        self.data = {}

    def write(self, address, payload):
        for offset, value in enumerate(payload):
            self.data[address + offset] = value

    def read_bytes(self, address, size):
        return bytes(self.data.get(address + i, 0) for i in range(size))


def u32(value):
    return struct.pack(">I", value & 0xFFFFFFFF)


def f32(value):
    return struct.pack(">f", value)


class Tree:
    """Builds a JObj hierarchy. Node n lives at JOBJ + n * JOBJ_STRIDE and
    its matrix translation is (n * 10, 0, 0), so the node a walk lands on
    is readable straight off the resolved X."""

    def __init__(self, model_flags=0):
        self.backend = Backend()
        self.backend.write(MODEL, u32(model_flags))
        self.backend.write(MODEL + 0x0C, u32(self.node(0)))
        self.backend.write(MODEL + 0x14, u32(self.node(0)))
        self.model_flags = model_flags

    @staticmethod
    def node(index):
        return JOBJ + index * JOBJ_STRIDE

    def add(self, index, child=None, following=None, flags=CLEAN,
            position=None, blend=None):
        address = self.node(index)
        if child is not None:
            self.backend.write(address + 0x10, u32(self.node(child)))
        if following is not None:
            self.backend.write(address + 0x08, u32(self.node(following)))
        self.backend.write(address + 0x14, u32(flags))
        x, y, z = position or (index * 10.0, 0.0, 0.0)
        self.backend.write(address + 0x50, f32(x))
        self.backend.write(address + 0x60, f32(y))
        self.backend.write(address + 0x70, f32(z))
        if blend is not None:
            self.backend.write(address + 0x38, f32(blend[0]))
            self.backend.write(address + 0x3C, f32(blend[1]))
            self.backend.write(address + 0x40, f32(blend[2]))
        return self

    def resolver(self):
        return NeckPositionResolver(
            MemoryReader(self.backend, XD_US_REV0), XD_US_REV0)


def landed_on(resolution):
    """Which node index the walk reached, decoded from its X."""
    if resolution.position is None:
        return None
    return round(resolution.position.x / 10.0)


class WalkOrderTests(unittest.TestCase):
    """`GSpartGetJObjPtr` -> `HSD_JObjWalkTree`: pre-order over the root's
    subtree, counting every visited node from zero."""

    def build(self):
        # root(0)
        #   +-- 1
        #   |    +-- 2
        #   |    +-- 3
        #   +-- 4
        return (Tree()
                .add(0, child=1)
                .add(1, child=2, following=4)
                .add(2, following=3)
                .add(3)
                .add(4))

    def test_index_zero_is_the_root(self):
        tree = self.build()
        self.assertEqual(
            landed_on(tree.resolver().resolve(MODEL, 0, Position(0, 0, 0))), 0)

    def test_pre_order_visits_a_subtree_before_the_next_sibling(self):
        tree = self.build()
        resolver = tree.resolver()
        order = [
            landed_on(resolver.resolve(MODEL, index, Position(0, 0, 0)))
            for index in range(5)
        ]
        self.assertEqual(order, [0, 1, 2, 3, 4])

    def test_a_no_descend_node_hides_its_children(self):
        tree = (Tree()
                .add(0, child=1)
                .add(1, child=2, following=4, flags=CLEAN | JOBJ_NO_DESCEND_FLAG)
                .add(2, following=3)
                .add(3)
                .add(4))
        resolver = tree.resolver()
        order = [
            landed_on(resolver.resolve(MODEL, index, Position(0, 0, 0)))
            for index in range(3)
        ]
        self.assertEqual(order, [0, 1, 4])


class RootSiblingTests(unittest.TestCase):
    """The 40.92-unit defect.

    `HSD_JObjWalkTree` reads `root->child` and never `root->next`. Following
    the root's sibling chain turned an out-of-range part index from a clean
    miss into a joint belonging to whatever model sat next in the
    hierarchy -- which is exactly what a neck tens of units from its own
    body looks like.
    """

    def build(self):
        # This model is root(0) with one child(1). Node 9 is a NEIGHBOURING
        # model's root, reachable only through root->next, and parked far
        # away so landing on it is unmistakable.
        return (Tree()
                .add(0, child=1, following=9)
                .add(1)
                .add(9, position=(4000.0, 0.0, 0.0)))

    def test_an_index_past_this_model_resolves_to_nothing(self):
        resolution = self.build().resolver().resolve(
            MODEL, 2, Position(0.0, 0.0, 0.0))
        self.assertIsNone(resolution.position)
        self.assertIn("past the end", resolution.reason)

    def test_the_neighbouring_model_is_never_returned(self):
        resolver = self.build().resolver()
        for index in range(2, 8):
            resolution = resolver.resolve(MODEL, index, Position(0, 0, 0))
            self.assertIsNone(
                resolution.position,
                f"part {index} escaped this model's subtree")

    def test_indices_inside_the_subtree_still_resolve(self):
        resolver = self.build().resolver()
        self.assertEqual(
            landed_on(resolver.resolve(MODEL, 1, Position(0, 0, 0))), 1)


class MatrixSourceTests(unittest.TestCase):
    """`GSpartGetTransform` picks its source by the MODEL's blending flag,
    not by the joint's bits alone."""

    def test_a_non_blending_model_ignores_the_joint_blend_bits(self):
        tree = (Tree(model_flags=0)
                .add(0, child=1)
                .add(1, flags=CLEAN | 0x00600000, position=(50.0, 0.0, 0.0),
                     blend=(999.0, 0.0, 0.0)))
        resolution = tree.resolver().resolve(MODEL, 1, Position(0, 0, 0))
        self.assertEqual(resolution.source, "matrix")
        self.assertAlmostEqual(resolution.position.x, 50.0, places=3)

    def test_a_blending_model_with_blend_bits_uses_the_blend_position(self):
        tree = (Tree(model_flags=MODEL_BLENDING_FLAG)
                .add(0, child=1)
                .add(1, flags=CLEAN | 0x00600000, position=(50.0, 0.0, 0.0),
                     blend=(77.0, 0.0, 0.0)))
        resolution = tree.resolver().resolve(MODEL, 1, Position(0, 0, 0))
        self.assertEqual(resolution.source, "blend")
        self.assertAlmostEqual(resolution.position.x, 77.0, places=3)

    def test_a_blending_model_without_blend_bits_uses_the_matrix(self):
        tree = (Tree(model_flags=MODEL_BLENDING_FLAG)
                .add(0, child=1)
                .add(1, flags=CLEAN, position=(50.0, 0.0, 0.0),
                     blend=(77.0, 0.0, 0.0)))
        resolution = tree.resolver().resolve(MODEL, 1, Position(0, 0, 0))
        self.assertEqual(resolution.source, "matrix")
        self.assertAlmostEqual(resolution.position.x, 50.0, places=3)


class StaleMatrixTests(unittest.TestCase):
    """The engine rebuilds a joint's matrix before reading it when
    `!(flags & 0x00800000) && (flags & 0x40)`. A read-only companion cannot
    rebuild, so that state is unresolved rather than reported stale."""

    def test_a_matrix_awaiting_rebuild_is_not_reported(self):
        tree = (Tree()
                .add(0, child=1)
                .add(1, flags=JOBJ_MATRIX_DIRTY_FLAG, position=(50.0, 0, 0)))
        resolution = tree.resolver().resolve(MODEL, 1, Position(0, 0, 0))
        self.assertIsNone(resolution.position)
        self.assertIn("rebuild", resolution.reason)

    def test_a_trusted_matrix_is_read_even_when_dirty(self):
        tree = (Tree()
                .add(0, child=1)
                .add(1, flags=JOBJ_MATRIX_TRUSTED_FLAG | JOBJ_MATRIX_DIRTY_FLAG,
                     position=(50.0, 0, 0)))
        resolution = tree.resolver().resolve(MODEL, 1, Position(0, 0, 0))
        self.assertAlmostEqual(resolution.position.x, 50.0, places=3)

    def test_a_clean_matrix_is_read(self):
        tree = Tree().add(0, child=1).add(1, flags=0, position=(50.0, 0, 0))
        resolution = tree.resolver().resolve(MODEL, 1, Position(0, 0, 0))
        self.assertAlmostEqual(resolution.position.x, 50.0, places=3)


class PartIndexBiasTests(unittest.TestCase):
    def test_the_model_flag_adds_one_to_the_requested_index(self):
        tree = (Tree(model_flags=MODEL_PART_INDEX_BIAS_FLAG)
                .add(0, child=1).add(1, following=2).add(2))
        resolution = tree.resolver().resolve(MODEL, 1, Position(0, 0, 0))
        self.assertEqual(resolution.requested_index, 1)
        self.assertEqual(resolution.part_index, 2)
        self.assertEqual(landed_on(resolution), 2)

    def test_without_the_flag_the_index_is_used_as_given(self):
        tree = Tree().add(0, child=1).add(1, following=2).add(2)
        resolution = tree.resolver().resolve(MODEL, 1, Position(0, 0, 0))
        self.assertEqual(resolution.part_index, 1)
        self.assertEqual(landed_on(resolution), 1)


class ContractTests(unittest.TestCase):
    def test_y_always_comes_from_the_actor_base(self):
        # peopleGetNeckPos overwrites out.y with the actor's own Y.
        tree = Tree().add(0, child=1).add(1, position=(50.0, 900.0, 60.0))
        resolution = tree.resolver().resolve(
            MODEL, 1, Position(0.0, 12.5, 0.0))
        self.assertAlmostEqual(resolution.position.y, 12.5, places=3)
        self.assertAlmostEqual(resolution.position.x, 50.0, places=3)
        self.assertAlmostEqual(resolution.position.z, 60.0, places=3)

    def test_a_negative_index_is_the_actor_base_not_a_failure(self):
        resolution = Tree().add(0).resolver().resolve(
            MODEL, -1, Position(3.0, 4.0, 5.0))
        self.assertEqual(resolution.position, Position(3.0, 4.0, 5.0))
        self.assertEqual(resolution.source, "actor base")

    def test_a_model_outside_mem1_resolves_to_nothing(self):
        resolution = Tree().add(0).resolver().resolve(
            0x1234, 0, Position(0, 0, 0))
        self.assertIsNone(resolution.position)

    def test_the_resolution_reports_the_jobj_it_used(self):
        tree = Tree().add(0, child=1).add(1)
        resolution = tree.resolver().resolve(MODEL, 1, Position(0, 0, 0))
        self.assertEqual(resolution.jobj, Tree.node(1))
        self.assertEqual(resolution.root, Tree.node(0))

    def test_offset_is_horizontal_only(self):
        tree = Tree().add(0, child=1).add(1, position=(3.0, 500.0, 4.0))
        resolution = tree.resolver().resolve(MODEL, 1, Position(0, 0, 0))
        self.assertAlmostEqual(resolution.offset, 5.0, places=3)

    def test_neck_position_is_the_thin_wrapper(self):
        tree = Tree().add(0, child=1).add(1, position=(50.0, 0, 0))
        resolver = tree.resolver()
        self.assertEqual(
            resolver.neck_position(MODEL, 1, Position(0, 0, 0)),
            resolver.resolve(MODEL, 1, Position(0, 0, 0)).position)

    def test_a_cyclic_hierarchy_is_bounded_not_hung(self):
        tree = Tree().add(0, child=1).add(1, child=1)
        resolution = tree.resolver().resolve(MODEL, 900, Position(0, 0, 0))
        self.assertIsNone(resolution.position)


if __name__ == "__main__":
    unittest.main()
