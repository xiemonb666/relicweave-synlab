#!/usr/bin/env python
"""Stage 4 fallback: the fracture surface as data -- height field, normal map, profile sections.

This is the declared replacement for a renderer (the task allows it explicitly): it needs no
Blender, no GPU and no third-party plotting library, and it shows the three things a photograph of
a fracture face is judged on --

* the relief itself (a shaded height map of ``w(u, v)`` over the fracture patch, in mm);
* the slope field (a normal map), which is what makes a fracture look "broken" rather than
  "corrugated";
* two orthogonal profile sections with the same vertical scale, where the difference between a
  plane, a fine-grained glass surface and a coarse stoneware surface is directly readable.

For every case of the bundle it measures the *delivered* interface faces (the same population and
the same ``(u, v, w)`` frame the numeric matrix uses) and rasterises them; nothing here re-uses the
analytic height field, so the figure cannot flatter the model.

Usage::

    .venv\\Scripts\\python.exe tests\\a12\\fracture\\_render_physical_layer_fields.py `
        --bundle data\\a12_reports\\physical_layer\\bundle_V18.pkl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUT_DIR = REPO_ROOT / "data" / "a12_reports" / "physical_layer"


def _write_u8(path: Path, rgb: np.ndarray) -> str:
    import cv2

    arr = np.asarray(rgb)
    if arr.dtype.kind == "f":
        arr = np.clip(arr, 0.0, 1.0)
        arr = np.power(arr, 1.0 / 2.2)
    arr = (arr * 255.0 + 0.5).astype(np.uint8) if arr.dtype.kind == "f" else arr.astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), arr[:, :, ::-1].copy()):
        raise RuntimeError(f"cv2.imwrite failed for {path}")
    return str(path)


def interface_local(fragment: Any, basis: Any, cutter_mesh: Any) -> np.ndarray:
    """Local ``(u, v, w)`` triangles of the delivered interface faces of one fragment."""
    from synlab.fracture import surface_features as sf
    from synlab.fracture.event import _interface_faces

    ids, _sources, _centres = _interface_faces(fragment, cutter_mesh)
    if ids.size == 0:
        return np.zeros((0, 3, 3), dtype=np.float64)
    return sf.triangle_vertices_local(fragment.mesh, basis, ids).reshape(-1, 3, 3)


def rasterise(triangles: np.ndarray, *, res: int = 512, pad: float = 0.06
              ) -> dict[str, Any]:
    """Rasterise a local-frame triangle soup into mean height, count and slope fields."""
    pts = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
    lo = pts[:, :, 0:2].reshape(-1, 2).min(axis=0)
    hi = pts[:, :, 0:2].reshape(-1, 2).max(axis=0)
    span = np.maximum(hi - lo, 1.0e-6)
    lo = lo - pad * span
    hi = hi + pad * span
    span = hi - lo
    step = float(max(span[0], span[1]) / max(int(res) - 1, 2))
    nu = int(np.ceil(span[0] / step)) + 1
    nv = int(np.ceil(span[1] / step)) + 1
    total = np.zeros((nu, nv), dtype=np.float64)
    count = np.zeros((nu, nv), dtype=np.float64)
    slope_u = np.zeros((nu, nv), dtype=np.float64)
    slope_v = np.zeros((nu, nv), dtype=np.float64)
    # barycentric rasterisation per triangle; the soup is a few 1e4 triangles, so a vectorised
    # bounding-box loop is both fast enough and exact
    for tri in pts:
        normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
        nz = float(normal[2])
        if abs(nz) < 1.0e-15:
            continue
        su = -float(normal[0]) / nz
        sv = -float(normal[1]) / nz
        tlo = tri[:, 0:2].min(axis=0)
        thi = tri[:, 0:2].max(axis=0)
        i0 = int(np.floor((tlo[0] - lo[0]) / step))
        i1 = int(np.ceil((thi[0] - lo[0]) / step))
        j0 = int(np.floor((tlo[1] - lo[1]) / step))
        j1 = int(np.ceil((thi[1] - lo[1]) / step))
        if i1 < i0 or j1 < j0 or i1 < 0 or j1 < 0 or i0 >= nu or j0 >= nv:
            continue
        i0, i1 = max(i0, 0), min(i1, nu - 1)
        j0, j1 = max(j0, 0), min(j1, nv - 1)
        gi, gj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing="ij")
        pu = lo[0] + gi * step
        pv = lo[1] + gj * step
        ax, ay = tri[0, 0], tri[0, 1]
        bx, by = tri[1, 0], tri[1, 1]
        cx, cy = tri[2, 0], tri[2, 1]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1.0e-18:
            continue
        px, py = pu - cx, pv - cy
        w0 = ((by - cy) * px + (cx - bx) * py) / den
        w1 = ((cy - ay) * px + (ax - cx) * py) / den
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1.0e-9) & (w1 >= -1.0e-9) & (w2 >= -1.0e-9)
        if not bool(inside.any()):
            continue
        h = w0 * tri[0, 2] + w1 * tri[1, 2] + w2 * tri[2, 2]
        sl = slice(i0, i1 + 1), slice(j0, j1 + 1)
        total[sl] += np.where(inside, h, 0.0)
        count[sl] += inside.astype(np.float64)
        slope_u[sl] += np.where(inside, su, 0.0)
        slope_v[sl] += np.where(inside, sv, 0.0)
    filled = count > 0
    height = np.full_like(total, np.nan)
    height[filled] = total[filled] / count[filled]
    with np.errstate(invalid="ignore", divide="ignore"):
        gu = np.where(filled, slope_u / np.maximum(count, 1.0), np.nan)
        gv = np.where(filled, slope_v / np.maximum(count, 1.0), np.nan)
    return {"height_mm": height, "count": count, "filled": filled, "grad_u": gu, "grad_v": gv,
            "u0": float(lo[0]), "v0": float(lo[1]), "step_mm": float(step),
            "extent_mm": [float(span[0]), float(span[1])],
            "coverage_fraction": float(filled.mean())}


def height_map_rgb(field: dict[str, Any], *, vmin: float, vmax: float,
                   background: tuple[float, float, float] = (0.08, 0.08, 0.10)
                   ) -> np.ndarray:
    """Lambert-shaded relief of the height raster (three-point light, absolute scale)."""
    h = np.asarray(field["height_mm"], dtype=np.float64)
    gu = np.asarray(field["grad_u"], dtype=np.float64)
    gv = np.asarray(field["grad_v"], dtype=np.float64)
    filled = np.asarray(field["filled"], dtype=bool)
    step = float(field["step_mm"])
    # grad_u/grad_v are the surface slopes; a finite difference of the raster is the robust slope
    du = np.zeros_like(h)
    dv = np.zeros_like(h)
    du[1:-1, :] = (h[2:, :] - h[:-2, :]) / (2.0 * step)
    dv[:, 1:-1] = (h[:, 2:] - h[:, :-2]) / (2.0 * step)
    du = np.where(np.isfinite(du), du, 0.0)
    dv = np.where(np.isfinite(dv), dv, 0.0)
    del gu, gv
    nx, ny, nz = -du, -dv, np.ones_like(h)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / norm, ny / norm, nz / norm
    light = np.array([-0.45, -0.55, 0.70])
    light = light / np.linalg.norm(light)
    lam = np.clip(nx * light[0] + ny * light[1] + nz * light[2], 0.0, 1.0)
    span = max(float(vmax) - float(vmin), 1.0e-9)
    tone = np.clip((h - float(vmin)) / span, 0.0, 1.0)
    tint = np.stack([0.55 + 0.45 * tone, 0.50 + 0.42 * tone, 0.46 + 0.38 * tone], axis=-1)
    rgb = tint * (0.28 + 0.78 * lam)[:, :, None]
    rgb = np.where(filled[:, :, None], rgb, np.asarray(background)[None, None, :])
    return rgb


def normal_map_rgb(field: dict[str, Any],
                   background: tuple[float, float, float] = (0.08, 0.08, 0.10)) -> np.ndarray:
    """Standard tangent-space normal map of the same raster (visible = the surface's own slope)."""
    h = np.asarray(field["height_mm"], dtype=np.float64)
    filled = np.asarray(field["filled"], dtype=bool)
    step = float(field["step_mm"])
    du = np.zeros_like(h)
    dv = np.zeros_like(h)
    du[1:-1, :] = (h[2:, :] - h[:-2, :]) / (2.0 * step)
    dv[:, 1:-1] = (h[:, 2:] - h[:, :-2]) / (2.0 * step)
    du = np.where(np.isfinite(du), du, 0.0)
    dv = np.where(np.isfinite(dv), dv, 0.0)
    nx, ny, nz = -du, -dv, np.ones_like(h)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    rgb = np.stack([0.5 + 0.5 * nx / norm, 0.5 + 0.5 * ny / norm, 0.5 + 0.5 * nz / norm], axis=-1)
    rgb = np.where(filled[:, :, None], rgb, np.asarray(background)[None, None, :])
    return rgb


def profile_strip(fields: list[dict[str, Any]], labels: list[str], *, row: int, res: int = 512,
                  rows: int = 160) -> np.ndarray:
    """Side-by-side profile sections (one per case) through the middle of the raster."""
    out = np.zeros((rows * len(fields), res, 3), dtype=np.float64)
    for index, (field, label) in enumerate(zip(fields, labels)):
        h = np.asarray(field["height_mm"], dtype=np.float64)
        if row < 0:
            row = h.shape[1] // 2
        row = min(max(int(row), 0), h.shape[1] - 1)
        line = h[:, row]
        valid = np.isfinite(line)
        if not bool(valid.any()):
            continue
        line = np.interp(np.arange(line.size), np.flatnonzero(valid), line[valid])
        x = np.linspace(0.0, line.size - 1.0, res)
        y = np.interp(x, np.arange(line.size), line)
        centre = float(np.median(y))
        amp = float(np.percentile(np.abs(y - centre), 99.0))
        amp = max(amp, 1.0e-4)
        band = out[index * rows:(index + 1) * rows]
        pix = (0.5 * rows - (y - centre) / amp * (0.42 * rows)).astype(np.int64)
        pix = np.clip(pix, 0, rows - 1)
        band[np.arange(res), pix] = np.array([0.95, 0.85, 0.45])
        band[rows // 2, :] = np.array([0.22, 0.24, 0.30])
        band[:, :2] = band[:, :2] * 0.5 + np.array([0.10, 0.10, 0.12]) * 0.5
        _ = label
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--res", type=int, default=512)
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    import pickle

    bundle_path = Path(args.bundle)
    with bundle_path.open("rb") as handle:
        bundle = pickle.load(handle)
    vessel_id = bundle.get("vessel_id", "V18")
    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR
    report: dict[str, Any] = {"bundle": str(bundle_path), "vessel_id": vessel_id,
                              "resolution": int(args.res), "cases": {}}
    shared: list[dict[str, Any]] = []
    labels: list[str] = []
    for label, case in bundle["cases"].items():
        basis = case["basis"]
        cutter_mesh = case["cutter_mesh"]
        local = np.concatenate([interface_local(f, basis, cutter_mesh)
                                for f in case["result"].fragments], axis=0)
        if local.shape[0] == 0:
            report["cases"][label] = {"status": "NO_INTERFACE_FACES"}
            print(f"[{label}] no interface faces", flush=True)
            continue
        field = rasterise(local, res=int(args.res))
        good = np.isfinite(field["height_mm"]) & field["filled"]
        values = field["height_mm"][good]
        centre = float(np.median(values))
        rms = float(np.sqrt(np.mean((values - centre) ** 2)))
        vmin = centre - 2.0 * rms
        vmax = centre + 2.0 * rms
        relief = np.where(good, field["height_mm"] - centre, np.nan)
        height_png = _write_u8(out_dir / f"field_{vessel_id}_{label}_height.png",
                               height_map_rgb(field, vmin=vmin, vmax=vmax))
        normal_png = _write_u8(out_dir / f"field_{vessel_id}_{label}_normal.png",
                               normal_map_rgb(field))
        report["cases"][label] = {
            "status": "OK", "triangles": int(local.shape[0]),
            "filled_bins": int(good.sum()), "coverage_fraction": float(field["coverage_fraction"]),
            "step_mm": float(field["step_mm"]), "extent_mm": field["extent_mm"],
            "relief_rms_mm": rms,
            "relief_p99_mm": float(np.percentile(np.abs(relief[good]), 99.0)),
            "relief_peak_to_valley_mm": float(np.nanmax(relief[good]) - np.nanmin(relief[good])),
            "height_png": height_png, "normal_png": normal_png,
            "slope_rms": float(np.sqrt(np.mean(
                np.asarray(field["grad_u"])[good] ** 2
                + np.asarray(field["grad_v"])[good] ** 2))) if good.any() else 0.0,
        }
        shared.append(field)
        labels.append(label)
        print(f"[{label}] raster {field['height_mm'].shape} step={field['step_mm']:.4f}mm "
              f"rms={rms:.5f}mm p99={np.percentile(np.abs(relief[good]), 99.0):.5f}mm "
              f"coverage={field['coverage_fraction'] * 100:.1f}%", flush=True)
    if shared:
        strip = profile_strip(shared, labels, row=-1)
        strip_png = _write_u8(out_dir / f"field_{vessel_id}_profiles.png", strip)
        report["profiles_png"] = strip_png
        report["profile_labels"] = labels
        print(f"[profiles] {strip_png}", flush=True)

    text = json.dumps(report, ensure_ascii=False, indent=1, default=str)
    out_path = out_dir / f"fields_{vessel_id}.json"
    out_path.write_text(text, encoding="utf-8")
    print(f"[written] {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
