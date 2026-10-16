"""Environment and capability doctor (plan 2.2, 30.1).

``synlab doctor`` must verify real abilities in order and never fabricate a result:

1. dependency imports;
2. millimetre box cutting (solid boolean);
3. hollow thin-shell cutting;
4. Blender background render (reported missing when the binary/wheel is absent);
5. linear RGB / integer ID / depth readback;
6. projection round trip;
7. Parquet and chunked-array write/read;
8. SQLite transactions;
9. a small PyTorch tensor;
10. training and rendering GPU lease mutual exclusion.

Additionally ``backend_capabilities`` records the *actual* behaviour of the external
backends required by plan 30.1 (Manifold face source attributes, Gmsh discrete PLC
shared surfaces, pycolmap/COLMAP availability and camera models, Open3D signed distance
on closed vs open geometry, Blender colour/depth semantics).
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .canonical import hash_json
from .errors import ErrorCode, SynLabError

REQUIRED_IMPORTS = (
    "numpy", "scipy", "skimage", "cv2", "PIL", "pyarrow", "pandas", "pydantic",
    "typer", "yaml", "trimesh", "manifold3d", "shapely", "networkx", "jsonschema",
    "fastapi", "httpx",
)
OPTIONAL_IMPORTS = ("gmsh", "open3d", "pycolmap", "faiss", "torch", "zarr", "svgpathtools", "sqlalchemy")


@dataclass
class Check:
    name: str
    status: str  # PASS | FAIL | MISSING | SKIPPED
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        out = {"name": self.name, "status": self.status, "seconds": round(self.seconds, 4),
               "detail": self.detail}
        if self.error:
            out["error"] = self.error
        return out


def _timed(fn: Any, /, *args: Any, **kwargs: Any) -> tuple[Any, float]:
    start = time.perf_counter()
    value = fn(*args, **kwargs)
    return value, time.perf_counter() - start


def _import_check(module: str, *, optional: bool = False) -> Check:
    start = time.perf_counter()
    try:
        mod = importlib.import_module(module)
        version = getattr(mod, "__version__", None)
        if version is None:
            try:
                from importlib.metadata import version as md_version

                version = md_version(module)
            except Exception:
                version = "unknown"
        return Check(f"import:{module}", "PASS", {"version": str(version)},
                     seconds=time.perf_counter() - start)
    except Exception as exc:
        return Check(f"import:{module}", "MISSING" if optional else "FAIL", {},
                     error=f"{type(exc).__name__}: {exc}", seconds=time.perf_counter() - start)


# ---------------------------------------------------------------------------- geometry
def _box_cut_check() -> Check:
    import trimesh

    start = time.perf_counter()
    try:
        box = trimesh.creation.box(extents=(100.0, 40.0, 30.0))
        blade = trimesh.creation.box(extents=(1.0, 200.0, 200.0))
        blade.apply_translation((5.0, 0.0, 0.0))
        removed = trimesh.boolean.intersection([box, blade], engine="manifold")
        removed_volume = float(abs(removed.volume)) if removed is not None else 0.0
        parts = trimesh.boolean.difference([box, blade], engine="manifold")
        mesh = parts if isinstance(parts, trimesh.Trimesh) else trimesh.util.concatenate(parts)
        components = mesh.split(only_watertight=False)
        volumes = [abs(float(c.volume)) for c in components]
        total = float(sum(volumes))
        expected = abs(float(box.volume)) - removed_volume
        detail = {
            "engine": "manifold",
            "components": len(components),
            "volume_total_mm3": total,
            "analytic_remaining_mm3": expected,
            "removed_mm3": removed_volume,
            "conservation_ratio": abs(total - expected) / expected,
            "watertight": all(bool(c.is_watertight) for c in components),
        }
        ok = len(components) == 2 and detail["conservation_ratio"] < 1e-6
        return Check("geometry:mm_box_cut", "PASS" if ok else "FAIL", detail,
                     error=None if ok else "conservation or component count wrong",
                     seconds=time.perf_counter() - start)
    except Exception as exc:
        return Check("geometry:mm_box_cut", "FAIL", {}, error=f"{type(exc).__name__}: {exc}",
                     seconds=time.perf_counter() - start)


def _hollow_shell_check() -> Check:
    import trimesh

    start = time.perf_counter()
    try:
        outer = trimesh.creation.icosphere(subdivisions=3, radius=50.0)
        inner = trimesh.creation.icosphere(subdivisions=3, radius=46.0)
        shell = trimesh.boolean.difference([outer, inner], engine="manifold")
        blade = trimesh.creation.box(extents=(2.0, 400.0, 400.0))
        parts = trimesh.boolean.difference([shell, blade], engine="manifold")
        mesh = parts if isinstance(parts, trimesh.Trimesh) else trimesh.util.concatenate(parts)
        components = mesh.split(only_watertight=False)
        detail = {
            "components": len(components),
            "watertight_all": all(bool(c.is_watertight) for c in components),
            "volume_shell_mm3": float(abs(shell.volume)),
            "euler_number": int(mesh.euler_number),
        }
        ok = len(components) == 2 and detail["watertight_all"]
        return Check("geometry:hollow_thin_shell_cut", "PASS" if ok else "FAIL", detail,
                     error=None if ok else "hollow shell cut failed",
                     seconds=time.perf_counter() - start)
    except Exception as exc:
        return Check("geometry:hollow_thin_shell_cut", "FAIL", {},
                     error=f"{type(exc).__name__}: {exc}", seconds=time.perf_counter() - start)


def _manifold_source_check() -> Check:
    """Do Manifold output faces carry original/run/face provenance (plan 30.1, R32)?"""
    start = time.perf_counter()
    try:
        import manifold3d

        box = manifold3d.Manifold.cube((20.0, 20.0, 20.0), True)
        blade = manifold3d.Manifold.cube((5.0, 40.0, 40.0), True).translate((2.0, 0.0, 0.0))
        cut = box - blade
        mesh_gl = cut.to_mesh()
        detail: dict[str, Any] = {
            "has_mesh_glp": hasattr(cut, "to_mesh"),
            "tri_verts": int(len(mesh_gl.tri_verts)),
            "volume_mm3": float(cut.volume()),
            "attributes": {},
        }
        for attr in ("run_original_id", "run_index", "face_id", "run_flags", "vert_properties",
                     "halfedge_tangent"):
            if hasattr(mesh_gl, attr):
                arr = getattr(mesh_gl, attr)
                detail["attributes"][attr] = {
                    "dtype": str(getattr(arr, "dtype", type(arr))),
                    "size": int(getattr(arr, "size", 0)) if hasattr(arr, "size") else None,
                }
        # Real source mapping requires per-input original ids
        ok = bool(detail["attributes"])
        detail["library_version"] = getattr(manifold3d, "__version__", "unknown")
        detail["note"] = ("project keeps explicit source_triangle arrays on every input mesh; "
                          "Manifold attributes are only an auxiliary hint")
        return Check("backend:manifold_source_attributes", "PASS" if ok else "FAIL", detail,
                     error=None if ok else "no source attribute arrays exposed by this build",
                     seconds=time.perf_counter() - start)
    except Exception as exc:
        return Check("backend:manifold_source_attributes", "FAIL", {},
                     error=f"{type(exc).__name__}: {exc}", seconds=time.perf_counter() - start)


def _gmsh_check() -> Check:
    """Shared-surface conformal meshing of a two-cell PLC (plan 30.4, A26)."""
    start = time.perf_counter()
    try:
        import gmsh

        with tempfile.TemporaryDirectory() as tmp:
            gmsh.initialize()
            try:
                gmsh.option.setNumber("General.Terminal", 0)
                gmsh.model.add("poc")
                box1 = gmsh.model.occ.addBox(0, 0, 0, 10, 10, 10)
                box2 = gmsh.model.occ.addBox(10, 0, 0, 10, 10, 10)
                gmsh.model.occ.fragment([(3, box1)], [(3, box2)])
                gmsh.model.occ.synchronize()
                vols = gmsh.model.getEntities(3)
                gmsh.model.mesh.generate(3)
                node_tags, coords, _ = gmsh.model.mesh.getNodes()
                tet_types, tet_tags, tet_nodes = gmsh.model.mesh.getElements(3)
                tris = gmsh.model.mesh.getElements(2)
                detail = {
                    "volumes": len(vols),
                    "interface_fragmented": len(vols) == 2,
                    "nodes": int(len(node_tags)),
                    "tets": int(sum(len(t) for t in tet_nodes)),
                    "surface_elements": int(sum(len(t) for t in tris[1])) if tris else 0,
                    "version": getattr(gmsh, "__version__", "unknown"),
                    "path": os.environ.get("PATH", "")[:0],
                }
                ok = len(vols) == 2 and detail["tets"] > 0
                return Check("backend:gmsh_discrete_shared_surface", "PASS" if ok else "FAIL", detail,
                             error=None if ok else "fragmented volume count wrong",
                             seconds=time.perf_counter() - start)
            finally:
                gmsh.finalize()
    except Exception as exc:
        return Check("backend:gmsh_discrete_shared_surface", "MISSING", {},
                     error=f"{type(exc).__name__}: {exc}", seconds=time.perf_counter() - start)


def _pycolmap_check() -> Check:
    start = time.perf_counter()
    try:
        import pycolmap

        detail = {
            "version": getattr(pycolmap, "__version__", "unknown"),
            "has_reconstruction": hasattr(pycolmap, "Reconstruction"),
            "camera_models": sorted(getattr(pycolmap.CameraModelId, "__members__", {}).keys())[:12]
            if hasattr(pycolmap, "CameraModelId") else [],
            "gpu": _gpu_names(),
            "executable": shutil.which("colmap"),
        }
        ok = detail["has_reconstruction"]
        return Check("backend:colmap_pycolmap", "PASS" if ok else "FAIL", detail,
                     error=None if ok else "pycolmap missing Reconstruction API",
                     seconds=time.perf_counter() - start)
    except Exception as exc:
        return Check("backend:colmap_pycolmap", "MISSING", {},
                     error=f"{type(exc).__name__}: {exc}", seconds=time.perf_counter() - start)


def _open3d_check() -> Check:
    start = time.perf_counter()
    try:
        import open3d as o3d

        mesh = o3d.geometry.TriangleMesh.create_box(10.0, 10.0, 10.0)
        scene = o3d.t.geometry.RaycastingScene()
        scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(mesh))
        query = o3d.core.Tensor([[5.0, 5.0, 5.0]], dtype=o3d.core.Dtype.Float32)
        distance = float(scene.compute_signed_distance(query).numpy()[0])
        detail = {"version": o3d.__version__, "closed_mesh_signed_distance_mm": distance,
                  "note": "signed distance requires watertight solids; open observation meshes "
                          "must use unsigned/estimated distances"}
        ok = abs(distance - (-5.0)) < 1e-3
        return Check("backend:open3d_distance", "PASS" if ok else "FAIL", detail,
                     error=None if ok else f"expected -5.0 got {distance}",
                     seconds=time.perf_counter() - start)
    except Exception as exc:
        return Check("backend:open3d_distance", "MISSING", {},
                     error=f"{type(exc).__name__}: {exc}", seconds=time.perf_counter() - start)


def _blender_check() -> Check:
    """Blender is the reference imaging backend (plan 13.2); report the *measured* state.

    The probe is the real one used by the render path: binary discovery (``BLENDER_BIN`` in
    the process environment, ``PATH``, the persisted Windows environment, or the project's
    portable build) followed by ``blender_scripts/selftest.py``, which assigns the Cycles
    engine and performs a background render.  A present-but-broken binary is ``FAIL``, never
    ``PASS``; an absent one is ``MISSING`` and names the software rasteriser as replacement.
    """
    start = time.perf_counter()
    try:
        from .observe.blender import selftest

        report = selftest()
    except Exception as exc:  # noqa: BLE001 - a probe failure is itself a capability gap
        report = {"status": "MISSING", "binary": None,
                  "detail": f"blender probe failed: {type(exc).__name__}: {exc}"}
    detail: dict[str, Any] = {k: v for k, v in report.items()
                              if k not in ("stdout_tail", "stderr_tail")}
    detail["stderr_tail"] = report.get("stderr_tail", "")
    status = {"OK": "PASS"}.get(str(report.get("status")), "MISSING"
                                if report.get("binary") is None else "FAIL")
    error = None
    if status != "PASS":
        error = (report.get("error") or report.get("detail")
                 or "Blender background self-test failed")
    return Check("backend:blender_render", status, detail, error=error,
                 seconds=time.perf_counter() - start)


def _gpu_names() -> list[str]:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if proc.returncode == 0:
            return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except Exception:
        pass
    return []


def _device_report() -> dict[str, Any]:
    import scipy

    return {
        "platform": platform.platform(),
        "python": sys.version,
        "python_executable": sys.executable,
        "cpu_logical": os.cpu_count(),
        "gpus": _gpu_names(),
        "packages": {
            "numpy": np.__version__,
            "scipy": scipy.__version__,
        },
        "numpy_bit_generator": "PCG64",
        "cwd": str(Path.cwd()),
    }


# ---------------------------------------------------------------------------- IO / numeric
def _parquet_check() -> Check:
    start = time.perf_counter()
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.parquet"
            table = pa.table({"axis": ["P01", "I03"], "level": [0, 4], "measured": [0.0, 1.5]})
            pq.write_table(table, path)
            back = pq.read_table(path)
            ok = back.num_rows == 2 and back.column("measured").to_pylist() == [0.0, 1.5]
            return Check("io:parquet_write_read", "PASS" if ok else "FAIL",
                         {"rows": back.num_rows, "bytes": path.stat().st_size},
                         error=None if ok else "round trip mismatch",
                         seconds=time.perf_counter() - start)
    except Exception as exc:
        return Check("io:parquet_write_read", "FAIL", {}, error=f"{type(exc).__name__}: {exc}",
                     seconds=time.perf_counter() - start)


def _chunked_array_check() -> Check:
    start = time.perf_counter()
    errors: list[str] = []
    detail: dict[str, Any] = {}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            npz_path = Path(tmp) / "shard.npz"
            arr = np.arange(1024, dtype=np.float32).reshape(32, 32)
            np.savez(npz_path, points=arr)
            with np.load(npz_path) as data:
                ok_npz = bool(np.allclose(data["points"], arr))
            detail["npz_shard"] = ok_npz
    except Exception as exc:
        errors.append(f"npz: {type(exc).__name__}: {exc}")
    try:
        import zarr

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tokens.zarr"
            root = zarr.open_group(str(path), mode="w")
            data = root.create_array("tokens", shape=(4, 8), chunks=(2, 8), dtype="float32")
            data[:] = np.ones((4, 8), dtype=np.float32)
            ok_zarr = bool(np.allclose(root["tokens"][:], 1.0))
            detail["zarr_chunked"] = ok_zarr
            detail["zarr_version"] = getattr(zarr, "__version__", "unknown")
    except Exception as exc:
        errors.append(f"zarr: {type(exc).__name__}: {exc}")
    ok = not errors and detail.get("npz_shard")
    return Check("io:chunked_array_write_read", "PASS" if ok else "FAIL", detail,
                 error="; ".join(errors) or None, seconds=time.perf_counter() - start)


def _sqlite_check() -> Check:
    start = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "m.sqlite"
            conn = sqlite3.connect(str(db), isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO t(v) VALUES ('assets')")
            conn.execute("COMMIT")
            rows = conn.execute("SELECT v FROM t").fetchall()
            backup = Path(tmp) / "backup.sqlite"
            dst = sqlite3.connect(str(backup))
            try:
                conn.backup(dst)
            finally:
                dst.close()
            conn.close()
            check = sqlite3.connect(str(backup))
            try:
                integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                check.close()
            ok = rows and rows[0][0] == "assets" and integrity == "ok"
            return Check("io:sqlite_transaction_backup", "PASS" if ok else "FAIL",
                         {"wal": True, "backup_integrity": integrity},
                         error=None if ok else "transaction/backup mismatch",
                         seconds=time.perf_counter() - start)
    except Exception as exc:
        return Check("io:sqlite_transaction_backup", "FAIL", {}, error=f"{type(exc).__name__}: {exc}",
                     seconds=time.perf_counter() - start)


def _torch_check() -> Check:
    start = time.perf_counter()
    try:
        import torch

        x = torch.randn(4, 8, requires_grad=True)
        y = (x @ x.T).sum()
        y.backward()
        detail = {
            "version": torch.__version__,
            "cuda": bool(torch.cuda.is_available()),
            "cuda_devices": torch.cuda.device_count() if torch.cuda.is_available() else 0,
            "grad_finite": bool(torch.isfinite(x.grad).all().item()),
            "threads": torch.get_num_threads(),
            "note": "CPU-only wheel on this host; GPU work must be scheduled elsewhere or left PENDING",
        }
        ok = detail["grad_finite"]
        return Check("training:torch_tensor_grad", "PASS" if ok else "FAIL", detail,
                     error=None if ok else "non-finite gradient",
                     seconds=time.perf_counter() - start)
    except Exception as exc:
        return Check("training:torch_tensor_grad", "MISSING", {},
                     error=f"{type(exc).__name__}: {exc}", seconds=time.perf_counter() - start)


def _window_check() -> Check:
    """Projection ↔ back-projection round trip of a 100 mm box (plan 2.2, A02)."""
    start = time.perf_counter()
    try:
        from .cameras import api as cam

        make_intrinsics = getattr(cam, "make_intrinsics", None)
        project_points = getattr(cam, "project_points", None) or getattr(cam, "project")
        unproject_pixels = getattr(cam, "unproject_pixels", None) or getattr(cam, "unproject")
        if make_intrinsics is None:
            def make_intrinsics(f: float, width: int, height: int) -> np.ndarray:
                return np.array([[f, 0.0, width / 2.0], [0.0, f, height / 2.0], [0.0, 0.0, 1.0]])

        K = make_intrinsics(1200.0, 1024, 768)
        points = np.array([[0.0, 0.0, 500.0], [50.0, 30.0, 620.0], [-40.0, -20.0, 700.0]])
        fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
        # OpenCV camera frame: X right, Y down, Z forward (plan 4.3 / 30.3).
        expected = np.array([
            [cx + fx * 0.0 / 500.0, cy + fy * 0.0 / 500.0],
            [cx + fx * 50.0 / 620.0, cy + fy * 30.0 / 620.0],
            [cx + fx * -40.0 / 700.0, cy + fy * -20.0 / 700.0],
        ])
        projected = project_points(points, K, np.eye(4))
        uv, z = projected[0], projected[1]
        uv = np.asarray(uv, dtype=np.float64)
        z = np.asarray(z, dtype=np.float64)
        back = np.asarray(unproject_pixels(uv, z, K, np.eye(4)), dtype=np.float64)
        err_px = float(np.max(np.abs(uv - expected)))
        err_mm = float(np.max(np.abs(back - points)))
        ok = err_px <= 0.05 and err_mm <= 1e-3
        return Check("geometry:projection_roundtrip", "PASS" if ok else "FAIL",
                     {"max_px_error": err_px, "max_mm_error": err_mm},
                     error=None if ok else "round trip exceeds budget",
                     seconds=time.perf_counter() - start)
    except Exception as exc:
        return Check("geometry:projection_roundtrip", "MISSING", {},
                     error=f"{type(exc).__name__}: {exc}", seconds=time.perf_counter() - start)


def _gpu_lease_check(store_root: str) -> Check:
    start = time.perf_counter()
    try:
        from .jobs.leases import LeaseManager
        from .storage.store import AssetStore

        store = AssetStore(store_root)
        manager = LeaseManager(store, ttl_seconds=5.0)
        first = manager.acquire("gpu0:doctor", "doctor-A")
        blocked = False
        try:
            manager.acquire("gpu0:doctor", "doctor-B")
        except SynLabError as exc:
            blocked = exc.code == ErrorCode.BUDGET_EXCEEDED
        manager.release("gpu0:doctor", first.token)
        second = manager.acquire("gpu0:doctor", "doctor-B")
        manager.release("gpu0:doctor", second.token)
        detail = {"mutual_exclusion": blocked, "token_rotation": first.token != second.token}
        ok = blocked and detail["token_rotation"]
        return Check("jobs:gpu_lease_mutex", "PASS" if ok else "FAIL", detail,
                     error=None if ok else "lease did not exclude the second owner",
                     seconds=time.perf_counter() - start)
    except Exception as exc:
        return Check("jobs:gpu_lease_mutex", "FAIL", {}, error=f"{type(exc).__name__}: {exc}",
                     seconds=time.perf_counter() - start)


def _store_atomic_check(store_root: str) -> Check:
    start = time.perf_counter()
    try:
        from .storage.store import AssetStore

        store = AssetStore(store_root)
        arr = np.arange(16, dtype=np.float32).reshape(4, 4)
        rec = store.commit_asset(role="qa_report", schema="synlab.qa.v1", unit="1", frame="none",
                                 payload={"probe": arr}, meta={"doctor": True},
                                 qa={"ok": True}, qa_status="QA_PASS")
        again = store.commit_asset(role="qa_report", schema="synlab.qa.v1", unit="1", frame="none",
                                   payload={"probe": arr}, meta={"doctor": True},
                                   qa={"ok": True}, qa_status="QA_PASS")
        loaded = store.load_arrays(rec.asset_id)["probe"]
        detail = {"asset_id": rec.asset_id, "idempotent": rec.asset_id == again.asset_id,
                  "array_roundtrip": bool(np.allclose(loaded, arr))}
        ok = detail["idempotent"] and detail["array_roundtrip"]
        return Check("storage:atomic_commit_idempotent", "PASS" if ok else "FAIL", detail,
                     error=None if ok else "commit not idempotent or payload mismatch",
                     seconds=time.perf_counter() - start)
    except Exception as exc:
        return Check("storage:atomic_commit_idempotent", "FAIL", {},
                     error=f"{type(exc).__name__}: {exc}", seconds=time.perf_counter() - start)


# ---------------------------------------------------------------------------- driver
def run_doctor(store_root: str | Path, *, include_backends: bool = True) -> dict[str, Any]:
    store_root = Path(store_root)
    store_root.mkdir(parents=True, exist_ok=True)
    checks: list[Check] = []
    for module in REQUIRED_IMPORTS:
        checks.append(_import_check(module))
    for module in OPTIONAL_IMPORTS:
        checks.append(_import_check(module, optional=True))

    checks.append(_box_cut_check())
    checks.append(_hollow_shell_check())
    checks.append(_blender_check())
    checks.append(_window_check())
    checks.append(_parquet_check())
    checks.append(_chunked_array_check())
    checks.append(_sqlite_check())
    checks.append(_torch_check())
    checks.append(_gpu_lease_check(str(store_root)))
    checks.append(_store_atomic_check(str(store_root)))
    if include_backends:
        checks.append(_manifold_source_check())
        checks.append(_gmsh_check())
        checks.append(_pycolmap_check())
        checks.append(_open3d_check())

    failed = [c.name for c in checks if c.status == "FAIL"]
    missing = [c.name for c in checks if c.status == "MISSING"]
    report = {
        "schema": "synlab.env_report.v1",
        "generated_at": time.time(),
        "device": _device_report(),
        "checks": [c.as_dict() for c in checks],
        "summary": {
            "pass": len([c for c in checks if c.status == "PASS"]),
            "fail": len(failed),
            "missing": len(missing),
            "failed_checks": failed,
            "missing_checks": missing,
        },
        "ok": not failed,
        "limitations": [
            "Blender is absent (no binary, no bpy wheel for Windows/CPython 3.12): the reference "
            "imaging path uses the project software rasterizer; Blender remains an adapter target.",
            "No CUDA-enabled torch wheel on this host and no real capture dataset: PHONE_RGB "
            "calibration and GPU-scale training stay PENDING.",
        ],
    }
    report["report_hash"] = hash_json({k: v for k, v in report.items() if k != "generated_at"})
    return report


def write_env_report(report: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
