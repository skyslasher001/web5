"""Pure pieces of the Phase 4 universe: the Semantic layout, wikilink parsing and agent probe targets."""

import numpy as np

from universe_core.agent_engine import step_target
from universe_vault.links import wikilink_targets
from universe_vault.semantic import RADIUS, layout


def test_related_vectors_land_together() -> None:
    rng = np.random.default_rng(1)
    centres = rng.standard_normal((3, 768))
    groups = np.repeat(np.arange(3), 40)
    vectors = centres[groups] + 0.15 * rng.standard_normal((120, 768))
    positions = layout(vectors)
    assert positions.shape == (120, 3) and np.abs(positions).max() <= RADIUS * 1.6
    within = np.mean(
        [np.linalg.norm(positions[groups == g] - positions[groups == g].mean(0), axis=1).mean() for g in range(3)]
    )
    means = np.stack([positions[groups == g].mean(0) for g in range(3)])
    between = np.mean([np.linalg.norm(means[a] - means[b]) for a in range(3) for b in range(a + 1, 3)])
    assert between > 3 * within
    # Deterministic: the same vectors give the same universe.
    assert np.array_equal(positions, layout(vectors))


def test_layout_handles_tiny_and_empty_inputs() -> None:
    assert layout(np.zeros((0, 8))).shape == (0, 3)
    assert layout(np.ones((1, 8))).shape == (1, 3)
    assert np.isfinite(layout(np.ones((3, 8)))).all()


def test_wikilink_targets() -> None:
    text = "See [[Seller call]], [[Parcel map|the map]], [[seller call#notes]] and [[ ]] and [not a link]."
    assert wikilink_targets(text) == ["Seller call", "Parcel map"]


def test_probe_targets_from_tool_arguments() -> None:
    assert step_target('{"item_id": "0190abcd-item"}') == {"kind": "item", "id": "0190abcd-item"}
    assert step_target('{"item_ids": ["a1", "b2"], "project": "DevMind"}') == {"kind": "item", "id": "a1"}
    assert step_target('{"project": "DevMind"}') == {"kind": "project", "id": "DevMind"}
    assert step_target('{"query": "land"}') is None
    assert step_target("not json") is None and step_target('{"item_ids": 7}') is None and step_target(None) is None
