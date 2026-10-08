"""Integration with the real parametric mother generator (``synlab.mothers.api``).

``synlab.mothers.api`` is delivered by a different workstream and is still changing in this
workspace, so this file *tries* to obtain a real mother first: if the generator cannot
produce a body for any of the sampled parameter sets, the tests skip with the exact
structured reasons instead of inventing a result.  When a real mother is available the whole
frozen contract is exercised on it (chart resolution, freeze, evaluate, audit, geometry
guard) - the documented analytic fixture is then not used at all.
"""

from __future__ import annotations

import numpy as np
import pytest

from synlab import seeds
from synlab.errors import SynLabError
from synlab.patterns import api

VESSELS = ("V01", "V02", "V06")
_REAL: dict[str, object] = {}


def _try_real_mother():
    """First working (vessel, params, mother) from the real generator, else the errors."""
    if "mother" in _REAL:
        return _REAL
    from synlab.mothers import api as mapi

    errors: list[str] = []
    for vessel in VESSELS:
        for attempt in range(2):
            rng = seeds.make_rng(20261001, "patterns-int", vessel, attempt)
            try:
                sampled = mapi.sample_parameters(vessel, 4, rng)
                if not sampled:
                    errors.append(f"{vessel}: sample_parameters returned no candidate")
                    continue
                mother = mapi.create_mother(vessel, "M01", sampled[0], rng,
                                            mother_id=f"int_{vessel}_{attempt}")
            except SynLabError as exc:
                errors.append(f"{vessel}: {exc.code} {exc.message[:120]}")
                continue
            except Exception as exc:  # pragma: no cover - reported honestly
                errors.append(f"{vessel}: {type(exc).__name__} {str(exc)[:120]}")
                continue
            _REAL["mother"] = mother
            _REAL["vessel"] = vessel
            _REAL["errors"] = errors
            return _REAL
    _REAL["mother"] = None
    _REAL["errors"] = errors
    return _REAL


def _require_real_mother():
    info = _try_real_mother()
    if info["mother"] is None:
        pytest.skip("synlab.mothers.api could not produce a mother in this workspace: "
                    + " | ".join(info["errors"][:4]))
    return info["mother"]


def _outer_points(mother, n: int = 300) -> np.ndarray:
    return np.asarray(mother.mesh.sample(n, seed=np.random.default_rng(11)), dtype=np.float64)


def test_real_mother_has_a_periodic_chart():
    mother = _require_real_mother()
    charts = list(mother.charts or [])
    assert charts, "a real mother must publish at least one chart"
    periodic = [c for c in charts if c.u_periodic and c.x_period_mm]
    assert periodic, "at least one chart must be a periodic revolve chart"
    assert mother.mesh.is_watertight
    assert float(abs(mother.mesh.volume)) > 0.0


def test_build_evaluate_on_a_real_mother():
    mother = _require_real_mother()
    points = _outer_points(mother)
    for family_id in ("PAT01", "PAT03", "PAT06", "PAT13"):
        recipe = api.build_pattern(mother,
                                   {"family": family_id, "complexity": 1,
                                    "allow_aux_layers": False},
                                   seeds.make_rng(20261001, "real", family_id))
        assert recipe.family_id == family_id
        assert recipe.meta["recipe_hash"] == api.recipe_hash(recipe)
        region = recipe.meta["regions"][0]
        assert region["surface_tag"] in set(mother.surface_tag_names.values())
        assert recipe.meta["chart"]["x_period_mm"] > 0
        channels = api.evaluate(recipe, mother, points, region["surface_tag"])
        assert np.all(np.isfinite(channels.albedo))
        assert channels.albedo.min() >= 0.0 and channels.albedo.max() <= 1.0
        assert np.all(np.isfinite(channels.height_mm))


def test_seam_and_scale_audit_on_a_real_mother():
    mother = _require_real_mother()
    recipe = api.build_pattern(mother,
                               {"family": "PAT03", "complexity": 2,
                                "allow_aux_layers": False},
                               seeds.make_rng(20261001, "real-seam", "pattern"))
    audit = api.audit_pattern(recipe, mother, n_pairs=1000, geometry_probe=False,
                              scale_samples=32)
    chart = audit["seam"]["chart_space"]
    assert chart["max_abs_color_error"] <= 1e-5
    assert chart["pass"] is True
    assert chart["derivative_pass"] is True
    assert audit["determinism"]["pass"] is True
    assert audit["inheritance"]["pass"] is True
    assert audit["scale"]["spectrum"]["status"] in ("OK", "FLAT_FIELD")


def test_geometry_policy_on_a_real_mother():
    """Relief/engraving must be applied or refused with a structured reason - never faked."""
    mother = _require_real_mother()
    applied = 0
    refused = 0
    for family_id in ("PAT14", "PAT15"):
        recipe = api.build_pattern(mother,
                                   {"family": family_id, "complexity": 1,
                                    "allow_aux_layers": False},
                                   seeds.make_rng(20261001, "real-geom", family_id))
        audit = api.audit_pattern(recipe, mother, n_pairs=16, geometry_probe=True,
                                  scale_samples=0)
        geometry = audit["geometry"]
        # either the displacement really happened on the real body, or the guard refused it
        # with a structured reason and measurements - never a silent normal map
        assert geometry["pass"] is True, geometry.get("reason")
        assert geometry["mode"] in ("relief", "engrave")
        if geometry["status"] == "GUARD_REJECTED":
            refused += 1
            # a structured refusal is the compliant outcome: unknown wall thickness,
            # unrepresentable waveforms or a depth beyond the wall fraction
            assert geometry["guard_code"] in ("TARGET_INFEASIBLE", "PRECISION_BUDGET_EXCEEDED",
                                             "PRECISION_NOT_REALIZED", "INTEGRATION_PENDING")
            assert geometry["guard_measurements"] is not None
        else:
            applied += 1
            assert geometry["hash_changed"] is True
            assert geometry["vertex_displacement_max_mm"] > 0
            assert geometry["flipped_faces"] == 0
            assert geometry["watertight_after"] is True
            assert geometry["appearance_only_normal_map"] is False
    assert applied + refused == 2


def test_appearance_only_families_leave_a_real_mother_untouched():
    mother = _require_real_mother()
    from synlab.patterns.serialize import geometry_hash

    before = geometry_hash(np.asarray(mother.mesh.vertices), np.asarray(mother.mesh.faces))
    for family_id in ("PAT03", "PAT13"):
        recipe = api.build_pattern(mother,
                                   {"family": family_id, "allow_aux_layers": False},
                                   seeds.make_rng(20261001, "real-identity", family_id))
        out = api.apply_pattern_geometry(mother, recipe, np.random.default_rng(2))
        assert out is mother
    after = geometry_hash(np.asarray(mother.mesh.vertices), np.asarray(mother.mesh.faces))
    assert before == after
