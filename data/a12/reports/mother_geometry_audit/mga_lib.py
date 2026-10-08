"""Shared measurement helpers for the mother-geometry audit (read-only).

Nothing here mutates repository geometry: the module only *builds* a mother through the
frozen public API and *measures* the result.
"""
from __future__ import annotations

import numpy as np
import trimesh

#: Declared z-extent of each vessel, expressed from the builder's own arithmetic.
#: ``source`` names the file/line the formula is read from, so a reviewer can re-derive it.
SHELL_TARGET_KEY = "z_rim_target_mm"


def declared_z_extent(vessel_id: str, params: dict) -> tuple[float | None, str]:
    """The z size the vessel's own parameters *declare* (not what it measures).

    Two semantics occur and the report keeps them apart:

    * the thirteen builders that call ``common.shell_profile`` declare a **top coordinate**
      (``z_rim_mm``), which that function records as ``profile_metrics.z_rim_target_mm``;
      their bodies are seated just above ``z = 0``, so the extent is within a few mm of it;
    * the slab / shell / superquadric builders declare a **size** (a thickness, a length, a
      half-height times two).

    This table only covers the builders that do not record a target themselves, and quotes
    their arithmetic so a reviewer can re-derive every number.
    """
    p = params
    if vessel_id == "V13":
        return float(p["height_mm"]), "group_extrude.V13: extrude_polygon_solid(height=p.height_mm)"
    if vessel_id == "V18":
        return float(p["thickness_mm"]), "group_extrude.V18: slab thickness along z"
    if vessel_id == "V19":
        return (float(p["thickness_mm"]) + float(p["side_lip_mm"]),
                "group_extrude.V19: thickness_mm + side_lip_mm (slope_mm raises one end further, "
                "so the realised extent can only be larger)")
    if vessel_id == "V22":
        return float(p["thickness_mm"]), "group_extrude.V22: slab thickness along z"
    if vessel_id == "V20":
        return (float(p["length_mm"]) + float(p["tail_lift_mm"]) + float(p["tail_drop_mm"]),
                "group_sheet.V20: length_mm + tail_lift_mm + tail_drop_mm (band + raised nose)")
    if vessel_id == "V21":
        # The panel lies in the x-y plane and its z extent is the *sag* (curvature_u + curvature_v
        # + warp) plus the thickness, not the thickness alone: a z-extent comparison against one
        # scalar parameter would be meaningless here, so it is reported as not comparable.
        return None, ("group_sheet.V21: thickness_mm is a normal thickness, not a z extent "
                      "(measured z extent = sag + thickness) - not comparable")
    if vessel_id == "V24":
        return 2.0 * float(p["c_mm"]), "group_sheet.V24: 2 x superquadric half-height c_mm"
    if vessel_id == "V23":
        return float(p["height_mm"]), "group_composite.V23: FigurineParams.height_mm (total height)"
    if vessel_id == "V14":
        thickness = float(p["thickness_mm"])
        z_top = max(float(p["rim_drop_mm"]), 0.0) + max(float(p["dome_height_mm"]), 0.5 * thickness)
        total = z_top + 0.35 * thickness + max(float(p["knob_height_mm"]), 0.0) + 0.5 * thickness
        return total, ("group_composite.V14: z_top + 0.35*t + knob_h + 0.5*t "
                       "(group_composite.py:391-423)")
    return None, "recorded by common.shell_profile as profile_metrics.z_rim_target_mm"


def silhouette(mesh: trimesh.Trimesh, *, bins: int = 12) -> dict:
    """Axisymmetric-ish outer radius by height, measured on the final vertices.

    For every z bin the maximum horizontal radius is taken, which is the outer silhouette of
    a body of revolution (attachments such as a spout or an ear can dominate a bin, which is
    why the raw table is stored next to the summary and the report never reads it alone).
    """
    return silhouette_points(np.asarray(mesh.vertices, dtype=np.float64), bins=bins)


def silhouette_points(verts: np.ndarray, *, bins: int = 12) -> dict:
    """Outer radius by height for a raw vertex array (see :func:`silhouette`)."""
    verts = np.asarray(verts, dtype=np.float64)
    if verts.size == 0:
        return {"z_table": [], "r_table": [], "note": "empty mesh"}
    z = verts[:, 2]
    r = np.hypot(verts[:, 0], verts[:, 1])
    lo, hi = float(z.min()), float(z.max())
    span = max(hi - lo, 1e-9)
    edges = np.linspace(lo, hi, int(bins) + 1)
    idx = np.clip(np.digitize(z, edges) - 1, 0, int(bins) - 1)
    z_tab, r_tab, n_tab = [], [], []
    for k in range(int(bins)):
        mask = idx == k
        n_tab.append(int(mask.sum()))
        z_tab.append(float(0.5 * (edges[k] + edges[k + 1])))
        r_tab.append(float(r[mask].max()) if np.any(mask) else 0.0)
    return {
        "z_table": z_tab,
        "r_table": r_tab,
        "n_vertices": n_tab,
        "r_global_max": float(r.max()),
        "normalised": {"z": [round((zz - lo) / span, 4) for zz in z_tab],
                       "r": [round(rr / max(float(r.max()), 1e-9), 4) for rr in r_tab]},
    }


def wall_taper(sil: dict) -> dict:
    """Ratio between the outer radius high up and low down on a silhouette table.

    Bins without vertices are skipped (a warped or multi-lobe body can leave an empty bin).
    The bottom quarter of the height is excluded because the base plate / foot ring turns the
    profile there; what is left is the wall.
    """
    z = np.asarray(sil.get("z_table") or [], dtype=np.float64)
    r = np.asarray(sil.get("r_table") or [], dtype=np.float64)
    if z.size == 0:
        return {"taper": None, "n_bins_used": 0}
    good = r > 1e-9
    if not np.any(good):
        return {"taper": None, "n_bins_used": 0}
    z_lo, z_hi = float(z[good].min()), float(z[good].max())
    span = max(z_hi - z_lo, 1e-9)
    keep = good & (z >= z_lo + 0.25 * span)
    if int(keep.sum()) < 2:
        keep = good
    zz, rr = z[keep], r[keep]
    order = np.argsort(zz)
    zz, rr = zz[order], rr[order]
    r_low = float(np.median(rr[:max(1, len(rr) // 3)]))
    r_high = float(np.median(rr[-max(1, len(rr) // 3):]))
    return {"taper": r_high / max(r_low, 1e-9), "r_low": r_low, "r_high": r_high,
            "n_bins_used": int(keep.sum())}


def component_report(mesh: trimesh.Trimesh) -> list[dict]:
    """Per connected body: face count, volume, z range, extents and axis occupancy."""
    parts = mesh.split(only_watertight=False)
    out: list[dict] = []
    for index, part in enumerate(parts):
        try:
            volume = float(part.volume)
        except Exception:
            volume = float("nan")
        bounds = np.asarray(part.bounds, dtype=np.float64)
        verts = np.asarray(part.vertices, dtype=np.float64)
        radius = np.hypot(verts[:, 0], verts[:, 1]) if verts.size else np.zeros(0)
        # the *body* of a vessel is the piece that owns the revolution axis; a leg, a lid dome
        # or an ear may sit lower or be bulkier, so neither z_min nor volume identifies it.
        axis_tol = max(1e-6, 0.02 * float(radius.max()) if radius.size else 1e-6)
        out.append({
            "index": int(index),
            "faces": int(len(part.faces)),
            "volume_mm3": volume,
            "z_min": float(bounds[0][2]),
            "z_max": float(bounds[1][2]),
            "z_extent_mm": float(bounds[1][2] - bounds[0][2]),
            "x_extent_mm": float(bounds[1][0] - bounds[0][0]),
            "y_extent_mm": float(bounds[1][1] - bounds[0][1]),
            "contains_axis": bool(radius.size and float(radius.min()) <= axis_tol),
            "r_max_mm": float(radius.max()) if radius.size else 0.0,
            "watertight": bool(part.is_watertight),
        })
    return out


def gaps_between_components(components: list[dict]) -> list[dict]:
    """Vertical gaps between the bodies, ordered by z: a positive gap means a floating part."""
    ordered = sorted(components, key=lambda c: c["z_min"])
    out: list[dict] = []
    for lower, upper in zip(ordered, ordered[1:]):
        out.append({
            "lower": lower["index"],
            "upper": upper["index"],
            "gap_mm": float(upper["z_min"] - lower["z_max"]),
            "overlap_mm": float(lower["z_max"] - upper["z_min"]),
            "lower_z_max": float(lower["z_max"]),
            "upper_z_min": float(upper["z_min"]),
        })
    return out


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [jsonable(v) for v in value.tolist()]
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value
