from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synlab.errors import SynLabError
from synlab.mothers.design_space import (
    build_designed_mother,
    parameter_space,
    probe_parameter_effect,
)
from synlab.mothers.api import geometry_hash


def test_space_uses_registered_fields_and_marks_evidence_boundary():
    space = parameter_space("V01")
    fields = {item["name"]: item for item in space["parameters"]}

    assert fields["diameter_mm"]["unit"] == "mm"
    assert fields["diameter_mm"]["bounds"] == {"minimum": 60.0, "maximum": 320.0}
    assert fields["diameter_mm"]["default"] == 190.0
    assert fields["rim_flare"]["scope"] == "type_specific"
    assert fields["wall_mm"]["scope"] == "common"
    assert fields["rim_flare"]["shape_effect"]["registry_declared_shape_driver"] is True
    assert space["evidence_status"]["source_class"] == "SYNTHETIC_CONTROL"
    assert space["evidence_status"]["validation_status"] == "PARAMETRIC_CANDIDATE"
    assert space["evidence_status"]["source_dimensions"] is None
    assert space["evidence_status"]["visual_style"] is None
    assert space["evidence_status"]["real_world_validation"] == "NOT_ESTABLISHED"


def test_type_specific_field_is_rejected_for_wrong_vessel():
    with pytest.raises(SynLabError, match="spout_length_mm") as caught:
        build_designed_mother("V06", overrides={"spout_length_mm": 90.0})

    assert caught.value.measurements["unknown_fields"] == ["spout_length_mm"]


def test_type_specific_parameter_changes_actual_mesh_and_bounds():
    probe = probe_parameter_effect("V01", "rim_flare", 0.35, seed=41)

    assert probe["changes_mesh"] is True
    assert probe["baseline_geometry_hash"] != probe["variant_geometry_hash"]
    assert probe["baseline_bounds_mm"] != probe["variant_bounds_mm"]


def test_style_recipe_does_not_override_explicit_user_values():
    result = build_designed_mother(
        "V06", style_preset="narrow_mouth",
        base_params={"shoulder_position": 0.61},
        overrides={"mouth_ratio": 0.72}, seed=12,
    )

    assert result.resolved_canonical_values["mouth_ratio"] == 0.72
    assert result.resolved_canonical_values["shoulder_position"] == 0.61
    assert result.requested_values["style_recipe"]["mouth_ratio"] == 0.34
    assert result.mother.meta["design_space"]["requested_values"] == result.requested_values


def test_deterministic_replay_has_same_mesh_and_resolved_values():
    first = build_designed_mother(
        "V04", style_preset="tall_cup", overrides={"handle_thickness_mm": 9.0}, seed=901,
    )
    replay = build_designed_mother(
        "V04", style_preset="tall_cup", overrides={"handle_thickness_mm": 9.0}, seed=901,
    )

    assert geometry_hash(first.mother.mesh) == geometry_hash(replay.mother.mesh)
    assert first.resolved_canonical_values == replay.resolved_canonical_values
    assert first.realized_values == replay.realized_values


def test_invalid_joint_geometry_reports_implicated_parameters():
    with pytest.raises(SynLabError, match="mouth_ratio") as caught:
        build_designed_mother("V06", overrides={"wall_mm": 60.0}, seed=6)

    assert "mouth_ratio" in caught.value.measurements["parameter_fields"]
    assert "wall_mm" in caught.value.measurements["parameter_fields"]
    assert caught.value.measurements["requested_values"]["wall_mm"] == 60.0

