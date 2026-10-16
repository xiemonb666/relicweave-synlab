"""Voxel/SDF, marching-cubes and mesh-measurement kernels for the only-remove-material operators.

Reuse policy (plan 12.1, 30.7) — nothing in this file re-implements a standard kernel:

* closed-solid signed distance: **Open3D** ``RaycastingScene.compute_signed_distance``
  (first choice for a qualified closed body);
* voxel-domain distance transform fallback: **SciPy** ``ndimage.distance_transform_edt``
  over a **trimesh** voxelisation (used when Open3D is unavailable, and as an
  independent backend cross-check);
* isosurface extraction: **scikit-image** ``measure.marching_cubes``;
* booleans (intersection with the clean source, cutter difference): **trimesh** with the
  **manifold3d** engine;
* rays/occupancy/unsigned-distance/thickness: **Open3D** ``RaycastingScene``;
* decimation: **Open3D** quadric edge collapse (see :mod:`synlab.physical.operators`).

The project-specific parts are the chunked evaluation with shared seam nodes, the
peak-memory accounting and the QA measurements; those are ours and are reported as such.
"""

from __future__ import annotations

import math
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import trimesh

from ..errors import ErrorCode, SynLabError

SDF_BACKENDS = ("open3d", "edt")
DEFAULT_SDF_BACKEND = "open3d"

#: absolute tolerance used for "damaged is inside clean" style comparisons, in mm
GEOM_TOL_MM = 1e-6


# ---------------------------------------------------------------------------- grid
@dataclass
class VoxelGrid:
    """Uniform node grid with one shared origin/spacing (plan 30.7)."""

    origin: np.ndarray
    spacing: float
    shape: tuple[int, int, int]
    backend: str = DEFAULT_SDF_BACKEND
    basis: str = "corner"

    def __post_init__(self) -> None:
        self.origin = np.asarray(self.origin, dtype=np.float64).reshape(3)
        self.shape = tuple(int(v) for v in self.shape)
        if self.spacing <= 0:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "voxel spacing must be > 0",
                              stage="physical.sdf")
        if any(v < 4 for v in self.shape):
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"voxel grid too small for marching cubes: {self.shape}",
                              stage="physical.sdf")

    @property
    def n_nodes(self) -> int:
        return int(np.prod(self.shape))

    @property
    def axis_coords(self) -> list[np.ndarray]:
        return [self.origin[a] + self.spacing * np.arange(self.shape[a]) for a in range(3)]

    def coords(self) -> np.ndarray:
        """(N,3) world coordinates of every node in C order."""
        xs, ys, zs = self.axis_coords
        grid = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), axis=-1)
        return grid.reshape(-1, 3)

    def node_bytes(self) -> int:
        return self.n_nodes * 8

    def value_at(self, field: np.ndarray, points: np.ndarray) -> np.ndarray:
        """Trilinear interpolation of a node field at world points (nearest outside)."""
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        idx = (pts - self.origin[None, :]) / self.spacing
        idx = np.clip(idx, 0.0, np.asarray(self.shape)[None, :] - 1.0)
        lo = np.floor(idx).astype(np.int64)
        hi = np.minimum(lo + 1, np.asarray(self.shape)[None, :] - 1)
        frac = idx - lo
        out = np.zeros(len(pts), dtype=np.float64)
        for di in (0, 1):
            for dj in (0, 1):
                for dk in (0, 1):
                    w = ((frac[:, 0] if di else 1 - frac[:, 0])
                         * (frac[:, 1] if dj else 1 - frac[:, 1])
                         * (frac[:, 2] if dk else 1 - frac[:, 2]))
                    i = hi[:, 0] if di else lo[:, 0]
                    j = hi[:, 1] if dj else lo[:, 1]
                    k = hi[:, 2] if dk else lo[:, 2]
                    out += w * field[i, j, k]
        return out

    def as_dict(self) -> dict[str, Any]:
        return {"origin_mm": [float(v) for v in self.origin], "spacing_mm": float(self.spacing),
                "shape": list(self.shape), "nodes": self.n_nodes,
                "node_bytes": self.node_bytes(), "backend": self.backend}


def choose_spacing(*, min_wall_thickness_mm: float | None = None,
                   shortest_structure_mm: float | None = None,
                   requested_mm: float | None = None, max_nodes: int = 4_000_000,
                   bbox_mm: tuple[float, float, float] | None = None) -> dict[str, Any]:
    """Initial spacing = min(wall/6, structure/4) with an explicit node budget (plan 12.1)."""
    candidates: list[tuple[str, float]] = []
    if min_wall_thickness_mm and min_wall_thickness_mm > 0:
        candidates.append(("min_wall_thickness/6", float(min_wall_thickness_mm) / 6.0))
    if shortest_structure_mm and shortest_structure_mm > 0:
        candidates.append(("shortest_structure/4", float(shortest_structure_mm) / 4.0))
    if requested_mm:
        candidates.append(("requested", float(requested_mm)))
    if not candidates:
        candidates.append(("default", 0.5))
    spacing = min(value for _, value in candidates)
    basis = min(candidates, key=lambda kv: kv[1])[0]
    budget_ok = True
    if bbox_mm is not None:
        extent = np.asarray(bbox_mm, dtype=np.float64)
        while float(np.prod(np.ceil(extent / spacing) + 3)) > max_nodes and spacing < 100.0:
            spacing *= 1.2
            budget_ok = False
            basis += "+node_budget_relaxation"
    return {"spacing_mm": float(spacing), "basis": basis, "budget_ok": budget_ok,
            "criteria": {name: float(value) for name, value in candidates},
            "max_nodes": int(max_nodes)}


def grid_for_mesh(mesh: trimesh.Trimesh, spacing: float, *, pad_mm: float = 2.0,
                  origin: np.ndarray | None = None,
                  shape: tuple[int, int, int] | None = None,
                  backend: str = DEFAULT_SDF_BACKEND) -> VoxelGrid:
    """Grid that fully covers the mesh plus ``pad_mm`` so extracted surfaces stay closed."""
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    if origin is None:
        origin = bounds[0] - float(pad_mm)
    if shape is None:
        extent = (bounds[1] + float(pad_mm)) - np.asarray(origin)
        shape = tuple(int(math.ceil(v / spacing)) + 1 for v in extent)
    return VoxelGrid(origin=np.asarray(origin, dtype=np.float64), spacing=float(spacing),
                     shape=tuple(int(v) for v in shape), backend=backend)


# ---------------------------------------------------------------------------- SDF backends
class _SceneCache:
    """One Open3D raycasting scene per mesh (exact SDF, occupancy, rays, distance)."""

    def __init__(self, mesh: trimesh.Trimesh) -> None:
        import open3d as o3d

        self._o3d = o3d
        legacy = o3d.geometry.TriangleMesh(
            o3d.utility.Vector3dVector(np.asarray(mesh.vertices, dtype=np.float64)),
            o3d.utility.Vector3iVector(np.asarray(mesh.faces, dtype=np.int32)),
        )
        self.scene = o3d.t.geometry.RaycastingScene()
        self.scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(legacy))

    def signed_distance(self, points: np.ndarray, chunk: int = 400_000) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float64)
        out = np.empty(len(pts), dtype=np.float64)
        for start in range(0, len(pts), chunk):
            block = pts[start:start + chunk].astype(np.float32)
            out[start:start + chunk] = self.scene.compute_signed_distance(
                self._o3d.core.Tensor(block)).numpy()
        return out

    def unsigned_distance(self, points: np.ndarray, chunk: int = 400_000) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float64)
        out = np.empty(len(pts), dtype=np.float64)
        for start in range(0, len(pts), chunk):
            block = pts[start:start + chunk].astype(np.float32)
            out[start:start + chunk] = self.scene.compute_distance(
                self._o3d.core.Tensor(block)).numpy()
        return out

    def occupancy(self, points: np.ndarray, chunk: int = 400_000) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float64)
        out = np.empty(len(pts), dtype=bool)
        for start in range(0, len(pts), chunk):
            block = pts[start:start + chunk].astype(np.float32)
            out[start:start + chunk] = self.scene.compute_occupancy(
                self._o3d.core.Tensor(block)).numpy().astype(bool)
        return out

    def cast(self, origins: np.ndarray, directions: np.ndarray) -> np.ndarray:
        rays = np.concatenate([np.asarray(origins, dtype=np.float32),
                               np.asarray(directions, dtype=np.float32)], axis=1)
        result = self.scene.cast_rays(self._o3d.core.Tensor(rays))
        return result["t_hit"].numpy()


_SCENES: dict[str, _SceneCache] = {}


def scene_for(mesh: trimesh.Trimesh) -> _SceneCache:
    key = f"{id(mesh)}:{len(mesh.faces)}"
    cache = _SCENES.get(key)
    if cache is None:
        cache = _SceneCache(mesh)
        _SCENES[key] = cache
        if len(_SCENES) > 32:  # bound the cache; scenes are cheap but not free
            _SCENES.pop(next(iter(_SCENES)))
    return cache


def _edt_field(mesh: trimesh.Trimesh, grid: VoxelGrid) -> tuple[np.ndarray, dict[str, Any]]:
    """SciPy distance-transform backend over a trimesh voxelisation."""
    from scipy import ndimage

    vox = mesh.voxelized(pitch=grid.spacing).fill()
    matrix = np.asarray(vox.matrix, dtype=bool)
    inside = ndimage.distance_transform_edt(matrix).astype(np.float64)
    outside = ndimage.distance_transform_edt(~matrix).astype(np.float64)
    field_vox = (outside - inside) * float(grid.spacing)
    # map our node grid into the voxel grid by nearest index
    transform = np.asarray(vox.transform, dtype=np.float64)
    vox_origin = transform[:3, :3] @ np.array([0.5, 0.5, 0.5]) + transform[:3, 3]
    nodes = grid.coords()
    idx = np.rint((nodes - vox_origin[None, :]) / float(grid.spacing)).astype(np.int64)
    idx = np.clip(idx, 0, np.asarray(field_vox.shape)[None, :] - 1)
    field = field_vox[idx[:, 0], idx[:, 1], idx[:, 2]].reshape(grid.shape)
    info = {"backend": "edt", "voxel_shape": list(matrix.shape),
            "voxel_inside_fraction": float(matrix.mean()),
            "note": "discrete distance transform; ~0.5 voxel systematic offset vs exact SDF"}
    return field, info


def signed_distance_field(mesh: trimesh.Trimesh, grid: VoxelGrid, *, backend: str | None = None,
                          surface_check_samples: int = 2000,
                          seed: int = 0) -> tuple[np.ndarray, dict[str, Any]]:
    """Signed distance ``d0`` at every node of ``grid`` (negative inside) + accuracy report."""
    backend = backend or grid.backend
    if backend not in SDF_BACKENDS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown SDF backend {backend!r}",
                          stage="physical.sdf")
    tracemalloc.start()
    started = time.perf_counter()
    if backend == "open3d":
        nodes = grid.coords()
        field = scene_for(mesh).signed_distance(nodes).reshape(grid.shape)
        info: dict[str, Any] = {"backend": "open3d",
                                "note": "Open3D RaycastingScene exact signed distance"}
    else:
        field, info = _edt_field(mesh, grid)
    elapsed = time.perf_counter() - started
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rng = np.random.default_rng(seed)
    samples, _ = trimesh.sample.sample_surface(mesh, int(surface_check_samples), seed=int(seed) % (2**31))
    interp = grid.value_at(field, np.asarray(samples, dtype=np.float64))
    info.update({
        "grid": grid.as_dict(), "seconds": float(elapsed),
        "tracemalloc_peak_bytes": int(peak), "tracemalloc_current_bytes": int(current),
        "surface_zero_level_rms_mm": float(np.sqrt(np.mean(interp ** 2))),
        "surface_zero_level_max_mm": float(np.max(np.abs(interp))),
        "surface_check_samples": int(len(samples)),
        "inside_fraction": float((field < 0).mean()),
        "field_min_mm": float(field.min()), "field_max_mm": float(field.max()),
        "rng_used": bool(rng is not None),
    })
    return field, info


# ---------------------------------------------------------------------------- field evaluation
def evaluate_field(grid: VoxelGrid, fn: Callable[[np.ndarray], np.ndarray], *,
                   chunk: int = 32, halo: int = 1,
                   base: np.ndarray | None = None) -> tuple[np.ndarray, dict[str, Any]]:
    """Evaluate ``base + fn(points)`` chunk-wise and verify the halo seams share nodes.

    Blocks overlap by ``halo`` nodes; the overlapping values must be bit-identical because
    every chunk evaluates the same pointwise function.  ``seam_max_abs_diff`` reports the
    measured agreement (0.0 means the chunks share nodes exactly).
    """
    nx, ny, nz = grid.shape
    out = np.zeros(grid.shape, dtype=np.float64) if base is None else np.array(base, dtype=np.float64,
                                                                              copy=True)
    written = np.zeros(grid.shape, dtype=bool)
    seam_diff = 0.0
    overlap_nodes = 0
    xs, ys, zs = grid.axis_coords
    step = max(1, int(chunk) - 2 * int(halo))
    for i0 in range(0, nx - 1, step):
        i1 = min(nx, i0 + chunk)
        for j0 in range(0, ny - 1, step):
            j1 = min(ny, j0 + chunk)
            for k0 in range(0, nz - 1, step):
                k1 = min(nz, k0 + chunk)
                block = np.stack(np.meshgrid(xs[i0:i1], ys[j0:j1], zs[k0:k1], indexing="ij"),
                                 axis=-1).reshape(-1, 3)
                values = np.asarray(fn(block), dtype=np.float64).reshape(i1 - i0, j1 - j0, k1 - k0)
                target = out[i0:i1, j0:j1, k0:k1]
                mask = written[i0:i1, j0:j1, k0:k1]
                # The operator contract is field = base + t*alpha*b (plan 12.1).  Writing the
                # raw fn() values here silently dropped the base field, so the extracted level
                # set was the perturbation itself instead of base+perturbation.
                base_block = (None if base is None
                              else np.asarray(base[i0:i1, j0:j1, k0:k1], dtype=np.float64))
                contribution = values if base_block is None else base_block + values
                if mask.any():
                    diff = float(np.max(np.abs(target[mask] - contribution[mask]))) if mask.any() else 0.0
                    seam_diff = max(seam_diff, diff)
                    overlap_nodes += int(mask.sum())
                target[~mask] = contribution[~mask]
                written[i0:i1, j0:j1, k0:k1] = True
    if not written.all():
        raise SynLabError(ErrorCode.PRECISION_NOT_REALIZED,
                          f"chunked evaluation left {int((~written).sum())} nodes unwritten",
                          stage="physical.sdf")
    return out, {"seam_max_abs_diff": float(seam_diff), "overlap_nodes": int(overlap_nodes),
                 "chunk": int(chunk), "halo": int(halo)}


# ---------------------------------------------------------------------------- isosurface
def marching_cubes_mesh(field: np.ndarray, grid: VoxelGrid, *, level: float = 0.0) -> trimesh.Trimesh:
    """Extract the zero level set with scikit-image and return a cleaned trimesh mesh."""
    from skimage import measure

    if not (field.min() <= level <= field.max()):
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING,
                          f"level {level} outside field range [{field.min()}, {field.max()}]",
                          stage="physical.sdf")
    verts, faces, _normals, _values = measure.marching_cubes(
        np.ascontiguousarray(field, dtype=np.float32), level=float(level),
        spacing=(grid.spacing, grid.spacing, grid.spacing),
    )
    world = np.asarray(verts, dtype=np.float64) + grid.origin[None, :]
    mesh = trimesh.Trimesh(vertices=world, faces=np.asarray(faces, dtype=np.int64), process=True)
    mesh = clean_mesh(mesh)
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def clean_mesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Merge vertices, drop degenerate faces, remove unreferenced vertices, fix winding."""
    out = mesh.copy()
    out.merge_vertices()
    # trimesh 5.x: nondegenerate_faces() is the mask-based replacement for the removed
    # remove_degenerate_faces(); calling both is unnecessary and the old name no longer exists.
    out.update_faces(out.nondegenerate_faces(height=1e-12))
    out.remove_unreferenced_vertices()
    trimesh.repair.fix_winding(out)
    trimesh.repair.fix_inversion(out)
    out.metadata = dict(out.metadata or {})
    return out


def boolean_op(operation: str, meshes: list[trimesh.Trimesh], *,
               engine: str = "manifold") -> trimesh.Trimesh:
    """trimesh/manifold3d boolean; structured failure instead of a silent empty mesh."""
    dispatch = {
        "difference": trimesh.boolean.difference,
        "union": trimesh.boolean.union,
        "intersection": trimesh.boolean.intersection,
    }
    if operation not in dispatch:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unsupported boolean operation {operation!r}", stage="physical.sdf")
    try:
        # trimesh 5.x removed boolean_automatic(); the explicit module functions are the
        # supported entry points and keep the same engine selection.
        result = dispatch[operation](meshes, engine=engine)
    except Exception as exc:  # pragma: no cover - backend specific
        raise SynLabError(ErrorCode.PRECISION_NOT_REALIZED,
                          f"boolean {operation} failed with engine {engine}: {type(exc).__name__}: {exc}",
                          stage="physical.sdf") from exc
    if result is None or len(result.faces) == 0:
        raise SynLabError(ErrorCode.TARGET_INFEASIBLE,
                          f"boolean {operation} produced an empty mesh (engine {engine})",
                          stage="physical.sdf")
    return clean_mesh(result)


def intersect_with_source(candidate: trimesh.Trimesh, source: trimesh.Trimesh,
                          *, engine: str = "manifold") -> tuple[trimesh.Trimesh, dict[str, Any]]:
    """`candidate ∩ source`: the only-remove-material guard (plan 12.1)."""
    before_volume = float(abs(candidate.volume))
    before_area = float(candidate.area)
    out = boolean_op("intersection", [candidate, source], engine=engine)
    after_volume = float(abs(out.volume))
    info = {
        "engine": engine,
        "candidate_volume_mm3": before_volume, "accepted_volume_mm3": after_volume,
        "clipped_volume_mm3": max(0.0, before_volume - after_volume),
        "candidate_area_mm2": before_area, "accepted_area_mm2": float(out.area),
        "clipped_area_mm2": max(0.0, before_area - float(out.area)),
    }
    return out, info


# ---------------------------------------------------------------------------- measurements
def watertight_report(mesh: trimesh.Trimesh) -> dict[str, Any]:
    return {
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "volume_mm3": float(abs(mesh.volume)),
        "signed_volume_mm3": float(mesh.volume),
        "area_mm2": float(mesh.area),
        "euler_number": int(mesh.euler_number),
        "n_faces": int(len(mesh.faces)), "n_vertices": int(len(mesh.vertices)),
        "degenerate_faces": int((~mesh.nondegenerate_faces(height=1e-12)).sum()),
        "positive_volume": bool(abs(mesh.volume) > 0),
    }


def outside_fraction(damaged: trimesh.Trimesh, reference: trimesh.Trimesh, *,
                     n_samples: int = 2000, tol_mm: float = 1e-6,
                     seed: int = 0) -> dict[str, Any]:
    """How much of ``damaged``'s surface lies outside ``reference`` (plan 12.4 `damaged ⊆ clean`)."""
    points, _fid = trimesh.sample.sample_surface(damaged, int(n_samples), seed=int(seed) % (2**31))
    pts = np.asarray(points, dtype=np.float64)
    signed = scene_for(reference).signed_distance(pts)
    outside = signed > float(tol_mm)
    stats = {
        "samples": int(len(pts)), "outside_points": int(outside.sum()),
        "outside_fraction": float(outside.mean()),
        "max_outside_mm": float(signed.max()) if len(pts) else 0.0,
        "p99_outside_mm": float(np.percentile(signed, 99)) if len(pts) else 0.0,
        "tol_mm": float(tol_mm), "signed_max_mm": float(signed.max()) if len(pts) else 0.0,
    }
    if outside.any():
        stats["max_outside_distance_mm"] = float(scene_for(reference).unsigned_distance(
            pts[outside]).max())
    else:
        stats["max_outside_distance_mm"] = 0.0
    return stats


def surface_deviation(points: np.ndarray, reference: trimesh.Trimesh) -> dict[str, float]:
    """Unsigned distance statistics of points to a reference surface (Open3D distance query)."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) == 0:
        return {"n": 0, "max_mm": 0.0, "mean_mm": 0.0, "rms_mm": 0.0, "p95_mm": 0.0}
    dist = scene_for(reference).unsigned_distance(pts)
    return {"n": int(len(pts)), "max_mm": float(dist.max()), "mean_mm": float(dist.mean()),
            "rms_mm": float(np.sqrt(np.mean(dist ** 2))), "p95_mm": float(np.percentile(dist, 95))}


def sampled_hausdorff(mesh_a: trimesh.Trimesh, mesh_b: trimesh.Trimesh, *,
                      n_samples: int = 1500, seed: int = 0,
                      tol_mm: float = 1e-6) -> dict[str, Any]:
    """Independently measured symmetric Hausdorff distance (sampled, disclosed as such)."""
    pa, _ = trimesh.sample.sample_surface(mesh_a, int(n_samples), seed=int(seed) % (2**31))
    pb, _ = trimesh.sample.sample_surface(mesh_b, int(n_samples), seed=(int(seed) + 1) % (2**31))
    da = scene_for(mesh_b).unsigned_distance(pa)
    db = scene_for(mesh_a).unsigned_distance(pb)
    return {
        "method": "surface_sampled_symmetric_unsigned_distance",
        "samples_per_mesh": int(n_samples),
        "hausdorff_mm": float(max(da.max() if len(da) else 0.0, db.max() if len(db) else 0.0)),
        "hausdorff_p95_mm": float(max(np.percentile(da, 95) if len(da) else 0.0,
                                      np.percentile(db, 95) if len(db) else 0.0)),
        "mean_mm": float(0.5 * ((da.mean() if len(da) else 0.0) + (db.mean() if len(db) else 0.0))),
        "outside_tol_fraction_a": float((da > tol_mm).mean()) if len(da) else 0.0,
        "tol_mm": float(tol_mm),
    }


def ray_thickness(mesh: trimesh.Trimesh, *, n_samples: int = 400, eps_mm: float = 1e-3,
                  seed: int = 0) -> dict[str, Any]:
    """Local wall thickness by inward ray casting from sampled surface points."""
    points, face_ids = trimesh.sample.sample_surface(mesh, int(n_samples), seed=int(seed) % (2**31))
    normals = np.asarray(mesh.face_normals, dtype=np.float64)[np.asarray(face_ids)]
    origins = np.asarray(points, dtype=np.float64) - normals * float(eps_mm)
    t_hit = scene_for(mesh).cast(origins, -normals)
    valid = np.isfinite(t_hit) & (t_hit > 0)
    thickness = (t_hit[valid] + float(eps_mm)) if valid.any() else np.zeros(0)
    out = {
        "samples": int(len(points)), "valid_rays": int(valid.sum()),
        "valid_fraction": float(valid.mean()) if len(points) else 0.0,
        "min_mm": float(thickness.min()) if thickness.size else 0.0,
        "p05_mm": float(np.percentile(thickness, 5)) if thickness.size else 0.0,
        "median_mm": float(np.median(thickness)) if thickness.size else 0.0,
        "max_mm": float(thickness.max()) if thickness.size else 0.0,
    }
    return out


def component_split(mesh: trimesh.Trimesh) -> list[trimesh.Trimesh]:
    """Connected components of a (possibly split) damaged body."""
    parts = mesh.split(only_watertight=False)
    out = [clean_mesh(p) for p in parts if len(p.faces) > 0]
    return out


def mesh_summary(mesh: trimesh.Trimesh) -> dict[str, Any]:
    return {"n_faces": int(len(mesh.faces)), "n_vertices": int(len(mesh.vertices)),
            "area_mm2": float(mesh.area), "volume_mm3": float(abs(mesh.volume)),
            "watertight": bool(mesh.is_watertight),
            "bounds_mm": [[float(v) for v in mesh.bounds[0]], [float(v) for v in mesh.bounds[1]]]}


def geometry_key(mesh: trimesh.Trimesh) -> str:
    """Frozen tie-break key for representative selection (plan 30.8)."""
    from ..canonical import hash_json

    centroid = [round(float(v), 6) for v in mesh.centroid]
    return hash_json({"centroid": centroid, "n_faces": int(len(mesh.faces)),
                      "area": round(float(mesh.area), 6)})


@dataclass
class DamageMeshResult:
    """One damaged body plus the measurements that justify it."""

    mesh: trimesh.Trimesh
    measurements: dict[str, Any] = field(default_factory=dict)
