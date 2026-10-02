"""Gather the extra numbers the diversity report cites, from the stores and the contracts.

Writes ``data/a12/reports/diversity_context.json``:

* the three registered camera profiles and the exact working-distance window each tier can reach
  (from ``synlab.cameras.profiles``, by inverting ``transform_profile_u``);
* the documented capture envelope (``configs/a12/capture_contract.json``);
* the light-mode vocabulary and its mapping;
* the fracture backends that are implemented, and the cut-plane formula the pipeline used before
  the wiring (``synlab.fracture.api._default_basis``), measured on a real body;
* the pattern families' field defaults (``synlab.patterns.params``), which is what the reviewed
  stores actually got.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

OUT = REPO_ROOT / "data" / "a12" / "reports" / "diversity_context.json"


def camera_tiers() -> list[dict[str, Any]]:
    from synlab.cameras.api import camera_profiles, transform_profile_u

    out = []
    for profile in camera_profiles():
        reachable = {}
        for distance in (50.0, 70.0, 100.0, 140.0, 150.0, 190.0, 200.0, 220.0, 250.0, 340.0,
                         380.0, 460.0):
            u = float(profile.u_position_mm) + float(profile.working_distance_mm) - distance
            try:
                moved = transform_profile_u(profile, u)
                reachable[str(int(distance))] = {
                    "ok": True, "realized_mm": float(moved.working_distance_mm)}
            except Exception as exc:  # noqa: BLE001 - a refused position is a measurement
                reachable[str(int(distance))] = {"ok": False,
                                                 "reason": str(getattr(exc, "code", exc))}
        lo = hi = None
        for distance in np.arange(20.0, 500.5, 0.5):
            u = float(profile.u_position_mm) + float(profile.working_distance_mm) - float(distance)
            try:
                transform_profile_u(profile, u)
            except Exception:  # noqa: BLE001
                continue
            lo = float(distance) if lo is None else lo
            hi = float(distance)
        out.append({
            "profile_id": profile.profile_id, "tier": profile.tier,
            "u_position_mm": float(profile.u_position_mm),
            "working_distance_mm": float(profile.working_distance_mm),
            "f_number": float(profile.f_number),
            "focal_px_1024": float(profile.K[0, 0]) * 1024.0 / float(profile.image_size[0]),
            "image_size_native": list(profile.image_size),
            "focal_length_mm": profile.meta.get("focal_length_mm"),
            "px_per_mm": (float(profile.K[0, 0]) / float(profile.meta["focal_length_mm"])
                          if profile.meta.get("focal_length_mm") else None),
            "calibrated": bool(profile.calibrated),
            "reachable_working_distance_mm": [lo, hi],
            "probe": reachable,
        })
    return out


def capture_envelope() -> dict[str, Any]:
    path = REPO_ROOT / "configs" / "a12" / "capture_contract.json"
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    wd = doc.get("working_distance_and_resolution") or {}
    lighting = doc.get("lighting") or {}
    return {
        "acceptance_distances_cm": (wd.get("acceptance_distances_cm") or {}).get("spec"),
        "closeup_local_cm": (wd.get("closeup_local_cm") or {}).get("spec"),
        "resolution_table": (wd.get("resolution_table") or {}).get("rows"),
        "light_modes": (lighting.get("real_capture_light_modes") or {}).get("spec"),
        "light_mode_count": (lighting.get("real_capture_light_modes") or {}).get("count"),
        "camera_sensor": (((doc.get("camera") or {}).get("node_a_detail") or {})
                          .get("resolution_nominal_px") or {}).get("spec"),
        "camera_fov_h_deg": (((doc.get("camera") or {}).get("node_a_detail") or {})
                             .get("fov_h_deg") or {}).get("spec"),
        "lens": ((doc.get("camera") or {}).get("lens") or {}).get("spec"),
        "source": "configs/a12/capture_contract.json (generated from V1.44 ch.6)",
    }


def fracture_facts() -> dict[str, Any]:
    from synlab.fracture.api import BUILT_BACKENDS, PENDING_BACKENDS
    from synlab.fracture.spec import REQUIRED_BACKENDS
    from synlab.mothers.api import create_mother
    from synlab.seeds import make_rng

    params = {"base_mm": 5.0, "belly": 0.8, "depth_ratio": 0.26, "diameter_mm": 170.0,
              "foot_height_ratio": 0.041, "foot_ring_ratio": 0.89, "rim_flare": -0.03,
              "wall_mm": 9.3, "warp_amplitude": 0.028, "warp_eccentricity_mm": 2.39,
              "warp_lobes": 2}
    mother = create_mother("V01", "M01", params, make_rng(20261001, "ctx", "shape"),
                           mother_id="ctx_V01")
    points = np.asarray(mother.mesh.vertices, dtype=np.float64)
    # reproduce fracture.api._default_basis exactly for this body
    from synlab.canonical import hash_json

    digest = hash_json({"v": np.round(points, 9).tolist(),
                        "f": np.asarray(mother.mesh.faces, dtype=np.int64).tolist()}
                       ).split(":", 1)[-1]
    unit_a = int(digest[0:8], 16) / float(1 << 32)
    unit_b = int(digest[8:16], 16) / float(1 << 32)
    azimuth = 2.0 * np.pi * unit_a
    normal = np.array([np.cos(azimuth), np.sin(azimuth), -0.25 + 0.5 * unit_b])
    normal = normal / float(np.linalg.norm(normal))
    return {
        "built_backends": list(BUILT_BACKENDS),
        "pending_backends": list(PENDING_BACKENDS),
        "required_backends": list(REQUIRED_BACKENDS),
        "legacy_default_normal": {
            "body": "V01/M01 at the ctx parameters",
            "azimuth_deg": float(np.degrees(azimuth)),
            "normal": [float(v) for v in normal],
            "z_component_window": [-0.25, 0.25],
            "formula": ("azimuth = 2*pi*u1, normal = normalize([cos, sin, -0.25 + 0.5*u2]) with "
                        "(u1,u2) read from sha256 of the body's rounded vertices and faces; the "
                        "event rng is deliberately not used (`del rng` in "
                        "synlab/fracture/api.py::_default_basis)"),
        },
    }


def pattern_defaults() -> dict[str, Any]:
    from synlab.patterns.params import FAMILY_MODELS, PALETTE_IDS

    out: dict[str, Any] = {"palette_ids": list(PALETTE_IDS), "families": {}}
    for family, model in sorted(FAMILY_MODELS.items()):
        fields = getattr(model, "model_fields", {}) or {}
        out["families"][family] = {
            name: (field.default if not callable(field.default) else "<factory>")
            for name, field in sorted(fields.items())
            if field.default is not None and repr(field.default) != "PydanticUndefined"
        }
    return out


def material_stats() -> list[dict[str, Any]]:
    """Material profiles in the reviewed stores, with their own stats."""
    import sqlite3

    rows = []
    for rel in ("data/a12", "data/a12_trainable/store", "data/a12_smoke",
                "data/a12_exports/closed_loop/store"):
        db = REPO_ROOT / Path(*rel.split("/")) / "metadata.sqlite"
        if not db.exists():
            continue
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute("SELECT DISTINCT meta_json FROM assets "
                                    "WHERE role='material_profile'"):
                meta = json.loads(row["meta_json"] or "{}")
                rows.append({"store": rel, "material_id": meta.get("material_id"),
                             "stats": meta.get("stats"),
                             "mechanics_status": meta.get("mechanics_status")})
        finally:
            conn.close()
    keys: dict[str, set] = {}
    for row in rows:
        for key, value in (row.get("stats") or {}).items():
            if isinstance(value, (int, float, str)):
                keys.setdefault(key, set()).add(json.dumps(value))
    return [{"store": r["store"], "material_id": r["material_id"],
             "mechanics_status": r["mechanics_status"],
             "stats": r["stats"]} for r in rows[:40]] + [
        {"distinct_values_per_stat_key": {k: sorted(v) for k, v in sorted(keys.items())}}]


def main() -> int:
    document = {
        "schema": "synlab.diversity_context.v1",
        "camera_tiers": camera_tiers(),
        "capture_envelope": capture_envelope(),
        "fracture": fracture_facts(),
        "pattern_defaults": pattern_defaults(),
        "material_profiles_sample": material_stats(),
    }
    OUT.write_text(json.dumps(document, ensure_ascii=False, indent=1, default=str),
                   encoding="utf-8")
    print(json.dumps({k: (v if k != "material_profiles_sample" else f"{len(v)} rows")
                      for k, v in document.items()}, ensure_ascii=False, indent=1,
                     default=str)[:1500])
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
