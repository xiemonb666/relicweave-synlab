"""Measured effects, nesting, NA handling and realized-effect honesty (plan 15.7 rows 3-4)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from synlab.degrade.api import apply_axis
from synlab.degrade.registry import AXIS_REGISTRY
from synlab.degrade.sources import mesh_geometry_hash
from synlab.errors import ErrorCode, SynLabError

from tests.a12.operators.operator_test_support import FAMILY_OF

#: axis -> a measured quantity that must be strictly positive at some non-zero level.
REQUIRED_EFFECTS = {
    "P01": "hf_rms_reduction",
    "P03": "lost_volume_mm3",
    "P04": "achieved_contact_loss",
    "I01": "sharpness_drop_ratio",
    "I03": "noise_sigma_increase",
    "I09": "long_edge_before",
    "I10": "encoding_error_rms",
    "G01": "applied_rms_mm",
    "G03": "removed_area_mm2",
    "G05": "face_reduction_ratio",
    "G08": "measured_max_displacement_mm",
    "X01": "removed_count",
    "G04": "mean_frame_translation_mm",
    "G07": "depth_deviation_mean_mm",
    "X02": "changed_px",
    "X03": "keys_touched",
    "X04": "mean_shift",
    "I06": "highlight_p99_after",
    "I07": "visible_loss",
}


def _code(exc: SynLabError) -> str:
    return exc.code.value if isinstance(exc.code, ErrorCode) else str(exc.code)


#: levels that the audit proved realizable first (deepest removed material first)
LEVEL_ORDER = {"P03": (4, 3, 2, 1), "P04": (2, 1, 4, 3)}


@pytest.mark.parametrize("axis_id", sorted(REQUIRED_EFFECTS))
def test_axes_measure_a_real_change(axis_id: str, probe: dict) -> None:
    """Every axis in the list measures its declared effect at a real non-zero level.

    Levels that the frozen SDF/IPF resolution cannot realise raise a structured error (and are
    reported as FAIL by the audit); this test requires at least one level to measure a strictly
    positive change, so a structurally broken axis cannot pass by luck.
    """
    key = REQUIRED_EFFECTS[axis_id]
    source = probe[FAMILY_OF[axis_id]]
    failures: list[str] = []
    for level in LEVEL_ORDER.get(axis_id, (1, 2, 3, 4)):
        try:
            ref, measurement = apply_axis(axis_id, level, source, None, lineage_id="audit_lineage")
        except SynLabError as exc:
            failures.append(f"L{level}:{_code(exc)}")
            continue
        assert measurement.identity is False
        assert measurement.measured, f"{axis_id}: no measured quantity at level {level}"
        assert measurement.result_hash != measurement.source_hash, axis_id
        assert ref.content_hash == measurement.result_hash, axis_id
        if key in measurement.measured and abs(float(measurement.measured[key])) > 0:
            assert measurement.realized, f"{axis_id} L{level}: {measurement.measured}"
            del ref, measurement
            return
        del ref, measurement
    raise AssertionError(f"{axis_id}: no non-zero level measured {key!r} (failures: {failures})")


def test_g08_variants_measure_and_keep_the_clean_hash(probe: dict) -> None:
    source = probe["G"]
    clean_before = source.get("clean_geometry_hash")
    seen: dict[str, dict[str, float]] = {}
    for variant in ("bump", "false_patch", "bridge"):
        _ref, measurement = apply_axis("G08", 2, source, None, variant=variant,
                                       lineage_id="audit_lineage")
        assert measurement.realized is True, variant
        measured = measurement.measured
        seen[variant] = measured
        assert (measured["measured_max_displacement_mm"] > 0
                or measured["measured_added_area_mm2"] > 0), variant
        assert measurement.extra["spurious_variant"] == variant
        assert measurement.extra["spurious_mask_role"] == "audit_and_supervision_only"
        invariants = measurement.extra["invariants"]
        assert invariants["clean_hash_unchanged"] in (True, None)
        assert clean_before == source.get("clean_geometry_hash")
    # bump displaces the observed support, the two face-adding variants add real faces
    assert seen["bump"]["measured_max_displacement_mm"] > 0
    assert seen["false_patch"]["n_added_faces"] > 0
    assert seen["false_patch"]["measured_added_area_mm2"] > 0
    assert seen["bridge"]["n_added_faces"] > 0
    assert seen["bridge"]["components_after"] != seen["bridge"]["components_before"]


def test_appearance_axes_do_not_change_the_geometry_hash(probe: dict) -> None:
    source = probe["P"]
    before = mesh_geometry_hash(source.get("mesh"))
    for axis_id, level in (("P05", 2), ("P06", 2)):
        ref, measurement = apply_axis(axis_id, level, source, None, lineage_id="lin_appearance")
        after = mesh_geometry_hash(ref if hasattr(ref, "get") else source.get("mesh"))
        assert after == before, f"{axis_id} changed the mesh geometry hash"
        invariants = measurement.extra.get("invariants", {})
        assert invariants.get("geometry_hash_unchanged") is True, invariants
        assert measurement.measured["mean_albedo_delta"] > 0


def test_nested_axes_are_nested(probe: dict) -> None:
    # P05 nested paint masks: removed area is non-decreasing in the level
    removed = []
    for level in (1, 2, 3, 4):
        _ref, measurement = apply_axis("P05", level, probe["P"], None, lineage_id="lin_nested")
        removed.append(measurement.measured["paint_removed_area_mm2"])
    assert removed == sorted(removed), removed
    assert removed[0] > 0

    # G02 nested point prefixes: strictly fewer points per level
    kept = []
    for level in (1, 2, 3, 4):
        _ref, measurement = apply_axis("G02", level, probe["G"], None, lineage_id="lin_nested")
        kept.append(measurement.measured["kept"])
    assert kept == sorted(kept, reverse=True) and len(set(kept)) == len(kept), kept

    # I08 fixed-priority frame deletion: never more views than the previous level
    views = []
    for level in (1, 2, 3, 4):
        _ref, measurement = apply_axis("I08", level, probe["I"], None, lineage_id="lin_nested")
        views.append(measurement.measured["views_after"])
    assert views == sorted(views, reverse=True), views
    assert views[-1] == 1

    # G03 connected holes: removed area grows, hole count stays positive
    areas = []
    for level in (1, 2, 3, 4):
        _ref, measurement = apply_axis("G03", level, probe["G"], None, lineage_id="lin_nested")
        areas.append(measurement.measured["removed_area_mm2"])
        assert measurement.measured["n_holes"] >= 1
    assert areas == sorted(areas), areas


def test_inapplicable_inputs_are_structured_na(probe: dict) -> None:
    # a glass body (M07) is not a supported material of the polish axis; the bundle copy must not
    # mutate the session fixture (with_payload shares the meta dict)
    glass = replace(probe["P"], meta={**probe["P"].meta, "material_id": "M07"})
    with pytest.raises(SynLabError) as excinfo:
        apply_axis("P01", 2, glass, None, lineage_id="lin_na")
    assert _code(excinfo.value) == ErrorCode.NA_NOT_APPLICABLE.value
    assert probe["P"].meta["material_id"] == "M03", "the probe fixture must stay untouched"

    # a probability temperature on a regression OBS_EST is undefined
    with pytest.raises(SynLabError) as excinfo:
        apply_axis("X04", 2, probe["X"], None, variant="probability_temperature",
                   lineage_id="lin_na")
    assert _code(excinfo.value) == ErrorCode.NA_NOT_APPLICABLE.value

    # a modality removal without modalities is NA, never a silent no-op
    bare = probe["X"].without("modalities")
    with pytest.raises(SynLabError) as excinfo:
        apply_axis("X01", 2, bare, None, lineage_id="lin_na")
    assert _code(excinfo.value) == ErrorCode.NA_NOT_APPLICABLE.value


def test_declared_change_not_measured_returns_operator_not_realized(probe: dict) -> None:
    """A declared effect that is not in the output must fail structurally, never pass silently.

    The contract is checked directly on ``AxisOperator.validate`` (deterministic, no SDF work)
    and then on the real P04 production path.  P04's declared target is now *realized* at every
    level on the probe (measured |achieved - target| <= 2.4e-4 against the frozen 0.02 budget),
    so the production part of this test asserts the contract in both directions: every level
    either reaches its target inside the frozen tolerance -- and then it must be ``realized``
    with a positive loss -- or it must come back as one of the structured failure codes.  A
    silent success with a missed target (what the axis did before the 1-D search was fixed:
    ``achieved 0.5708`` for a declared ``0.5``) fails this assertion.
    """
    from synlab.degrade.registry import AXIS_REGISTRY, measurement_from

    operator = AXIS_REGISTRY.get("P04")
    source = probe["P"]
    planned = operator.level_parameters(2)
    fake = measurement_from(operator, level=2, variant=operator.default_variant, planned=planned,
                            measured={"achieved_contact_loss": 0.0}, units={}, identity=False,
                            realized=False, source_hash=source.content_hash(),
                            result_hash=source.content_hash())
    with pytest.raises(SynLabError) as excinfo:
        operator.validate(source, source, fake)
    assert _code(excinfo.value) == ErrorCode.OPERATOR_NOT_REALIZED.value

    tolerance = float(operator.EXPECTED.get("tolerance", 0.02))
    realized_levels = 0
    codes = set()
    for level in (4, 3, 2, 1):
        try:
            _ref, measurement = apply_axis("P04", level, source, None,
                                           lineage_id="audit_lineage")
        except SynLabError as exc:
            codes.add(_code(exc))
            continue
        achieved = float(measurement.measured["achieved_contact_loss"])
        target = float(measurement.measured["contact_loss_target"])
        if abs(achieved - target) <= tolerance and measurement.measured["lost_volume_mm3"] > 0:
            assert measurement.realized, (level, measurement.measured)
            realized_levels += 1
        else:
            assert not measurement.realized, (level, measurement.measured)
            codes.add(ErrorCode.OPERATOR_NOT_REALIZED.value)
    assert codes <= {ErrorCode.OPERATOR_NOT_REALIZED.value, ErrorCode.TARGET_INFEASIBLE.value,
                     ErrorCode.PRECISION_NOT_REALIZED.value}, codes
    assert realized_levels == 0 or not codes, (realized_levels, codes)
    assert realized_levels > 0, "the probe must realize at least one declared P04 target"


def test_stage_reported_by_every_axis_matches_the_registry() -> None:
    for axis_id in sorted(AXIS_REGISTRY.ids()):
        operator = AXIS_REGISTRY.get(axis_id)
        params = operator.level_parameters(0)
        assert isinstance(params, dict)
        assert np.isfinite([v for v in params.values() if isinstance(v, float)] or [0.0]).all()
