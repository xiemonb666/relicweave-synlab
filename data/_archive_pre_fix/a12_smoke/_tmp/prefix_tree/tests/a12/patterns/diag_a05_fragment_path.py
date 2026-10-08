"""Locate the fragment-path vs field-path albedo difference for one family (A05 evidence)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "tests" / "a12" / "patterns"))
from probe_a05_cut_continuity import build_family  # noqa: E402


def main() -> int:
    from synlab.patterns.api import _composite, evaluate
    from synlab.patterns.charts import (region_weight, tag_index, to_chart_mm,
                                        vertex_surface_tags)

    family = sys.argv[1] if len(sys.argv) > 1 else "PAT07"
    built = build_family(family)
    mother, region, frame, recipe = (built["mother"], built["region"], built["frame"],
                                     built["recipe"])
    verts = np.asarray(mother.mesh.vertices, dtype=np.float64)
    tags = np.asarray(vertex_surface_tags(mother), dtype=np.int64)
    tag = int(tag_index(mother, str(region["surface_tag"])))
    ang = np.arctan2(verts[:, 1], verts[:, 0])
    radius = np.hypot(verts[:, 0], verts[:, 1])
    arc = np.abs(ang) * np.maximum(radius, 1e-9)
    band = (tags == tag) & (arc <= 8.0)
    pts = verts[band]
    x_mm, s_mm = to_chart_mm(frame, pts)
    weight = region_weight(frame, pts, x_mm, s_mm, region)
    sel = weight >= 1.0 - 1e-12
    print("candidates", pts.shape[0], "interior", int(sel.sum()),
          "weight range", float(weight.min()), float(weight.max()))
    pts_sel = pts[sel]
    x_sel, s_sel = x_mm[sel], s_mm[sel]
    ch = evaluate(recipe, mother, pts_sel, tag)
    frag = np.asarray(ch.albedo, dtype=np.float64)
    moth = built["albedo_at"](x_sel, s_sel)

    # rebuild the same composites explicitly to find the source of the difference
    ctx_a = built["meta"]
    from synlab.patterns.api import _context
    from synlab.patterns.fields import WarpField
    from synlab.patterns.builders import field_context
    from synlab.patterns.layers import build_field

    ctx_audit = _context(recipe)
    ctx_eval = field_context(ctx_a, dict(ctx_a.get("palette") or {}),
                             WarpField.from_dict(ctx_a.get("warp")))
    same_ctx = all(
        (np.array_equal(getattr(ctx_audit, f), getattr(ctx_eval, f))
         if isinstance(getattr(ctx_audit, f), np.ndarray) else getattr(ctx_audit, f) == getattr(ctx_eval, f))
        for f in ("x_period_mm", "s_min_mm", "s_max_mm", "s_periodic", "footprint_mm",
                  "body", "body_roughness", "paints", "paint_roughness"))
    print("ctx identical:", same_ctx)
    field = build_field(recipe.family_id, recipe.params)
    out, _ = _composite(field, list((recipe.meta or {}).get("aux_layers") or []), x_sel, s_sel, ctx_audit)
    cov = np.clip(out.coverage, 0.0, 1.0)
    body = np.asarray((ctx_a.get("palette") or {}).get("body"), dtype=np.float64)
    manual = body[None, :] * (1.0 - cov[:, None]) + out.paint * cov[:, None]
    print("frag vs manual max|d| =", float(np.abs(frag - manual).max()))
    print("moth vs manual max|d| =", float(np.abs(moth - manual).max()))
    print("frag vs moth   max|d| =", float(np.abs(frag - moth).max()))
    cov_eval = np.clip(out.coverage * np.ones_like(cov), 0.0, 1.0)
    print("coverage path equal:", bool(np.array_equal(cov, cov_eval)))
    print("evaluate meta keys:", sorted((ch.meta or {}).keys()))
    print("unpatterned_reason:", (ch.meta or {}).get("unpatterned_reason"))
    d = np.abs(frag - moth).max(axis=1)
    i = int(np.argmax(d))
    print("worst point idx", i, "diff", float(d[i]))
    print("  x,s =", x_sel[i], s_sel[i], "weight", float(weight[sel][i]))
    print("  frag", frag[i], "moth", moth[i])
    single_frag = np.asarray(evaluate(recipe, mother, pts_sel[i:i + 1], tag).albedo)[0]
    single_moth = built["albedo_at"](x_sel[i:i + 1], s_sel[i:i + 1])[0]
    print("  single-point frag", single_frag, "moth", single_moth)
    print("  frag value stable under batching:", bool(np.allclose(single_frag, frag[i])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
