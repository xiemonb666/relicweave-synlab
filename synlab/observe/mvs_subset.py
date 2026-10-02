"""Real COLMAP (pycolmap) MVS subset on rendered multi-view frames (plan 14.4) -> A14/A24.

What this module does
---------------------
1. Picks **real mothers**: committed ``mother_mesh`` assets from the store (the demo store
   ``data/a12_demo/store`` is preferred) or, when the store has none, a freshly built
   :func:`synlab.mothers.api.create_mother`.
2. Renders an overlapping multi-view cache with the real software rasteriser
   (:func:`synlab.observe.routes.render_views`) and writes the delivered PNG frames, the
   deployment masks and the per-frame intrinsics/extrinsics to disk.
3. Runs the **real COLMAP pipeline** through ``pycolmap``: feature extraction -> matching ->
   ``incremental_mapping`` (SfM) -> ``undistort_images`` -> ``patch_match_stereo`` ->
   ``stereo_fusion``.  Every stage records its full argv, exit status, wall time, captured
   COLMAP log and the resulting database/model statistics.
4. Reports honestly.  A dense stage that cannot run is ``MVS_NOT_AVAILABLE``; an SfM that
   does not register enough frames is ``STOP-SFM``; anything else that breaks is
   ``MVS_FAILED``.  The reconstruction result is **never** back-filled with the clean mesh,
   the renderer depth or the simulator pose - only the delivered images and masks enter
   COLMAP (see :func:`audit_source_dependency`, which proves it by re-running the same
   frames with a deliberately corrupted ground-truth pose table).

Scope
-----
The frames are ``SYNTHETIC_RENDER`` (software rasteriser, simulation albedo).  There is no
real capture data on this host, so ``REAL_CAPTURE`` stays ``PENDING`` and
``real_calibration_ok`` is ``false`` by construction (plan 14.4 keeps the two subsets
apart).

The report is written to ``data/a12/reports/mvs_subset.json`` (and mirrored into
``<store_root>/reports/mvs_subset.json`` when a different store is used), which is where
``synlab.qc.acceptance`` item A14 reads it from.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np

from ..errors import ErrorCode, SynLabError

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_ROOT = ROOT / "data" / "a12" / "reports"
DEFAULT_WORK_ROOT = DEFAULT_REPORT_ROOT / "mvs"
DEMO_STORE_ROOT = ROOT / "data" / "a12_demo" / "store"
REPORT_NAME = "mvs_subset.json"
SOURCE_AUDIT_NAME = "source_dependency_audit.json"

DATA_SCOPE_SYNTHETIC = "SYNTHETIC_RENDER"
DATA_SCOPE_REAL = "REAL_CAPTURE"

#: Starting cache budget from plan 13.1.  Plan 14.4 asks for 30-120 overlapping frames per
#: fragment for a real MVS subset; that is recorded as a gap, not silently claimed.
DEFAULT_FRAMES_PER_FRAGMENT = 12
PLAN_FRAMES_PER_FRAGMENT = (30, 120)

STOP_SFM = "STOP_SFM"
MVS_FAILED = "MVS_FAILED"
MVS_NOT_AVAILABLE = "MVS_NOT_AVAILABLE"
INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"


# --------------------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------------------
@dataclass
class MvsConfig:
    """Frozen configuration of one subset run; every field is echoed into the report."""

    frames_per_fragment: int = DEFAULT_FRAMES_PER_FRAGMENT
    delivered_size: tuple[int, int] = (800, 600)
    render_pixels: int = 800 * 600
    supersample: int = 2
    #: The renderer's CoC heuristic marks everything outside a 0.75 px circle as uncertain;
    #: at these focal lengths that removes the whole object from the deployment mask, so the
    #: threshold is raised and recorded (the rasteriser simulates a pinhole, no defocus).
    coc_px_threshold: float = 1.0e6
    #: Photo scale of the imaging chain.  The default effective_gain=1.0 photon-starves the
    #: render (mean photon count < 1 per pixel -> binary noise); 1e4 gives a real SNR.
    effective_gain: float = 1.0e4
    read_noise_sigma: float = 0.0
    camera_model: str = "SIMPLE_RADIAL"
    camera_mode: str = "SINGLE"
    max_num_features: int = 8192
    max_image_size: int = 800
    max_num_matches: int = 32768
    matcher: str = "auto"          # auto | exhaustive | sequential
    min_registered_frames: int = 4
    min_mask_coverage: float = 0.05
    use_mask: str = "auto"         # auto | always | never
    dense: bool = True
    pose_forensics: bool = True
    #: Single-threaded stages plus ``pycolmap.set_random_seed``: used by the source-dependency
    #: audit so that two runs on identical inputs are comparable at the bit level.
    deterministic: bool = False
    #: Pin the two images the incremental mapper starts from (COLMAP otherwise draws trial
    #: pairs from its RNG, which makes the achieved model depend on the scheduler).  Used by
    #: the source-dependency audit so that two runs are comparable.
    init_pair: tuple[int, int] | None = None
    seed: int = 20261001
    lineage_id: str = "a12_mvs_subset"

    def resolved_matcher(self, n_frames: int) -> str:
        if self.matcher not in ("auto", "exhaustive", "sequential"):
            return "exhaustive"
        if self.matcher == "auto":
            return "exhaustive" if int(n_frames) <= 24 else "sequential"
        return self.matcher


# --------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------
def _jsonable(obj: Any) -> Any:
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                               default=_jsonable), encoding="utf-8")
    return path


def _rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _report_roots(store: Any) -> list[Path]:
    """Where the A14/A24 reports go: always the canonical report root.

    ``<store_root>/reports`` is added only when the store is *not* the committed demo store,
    because the acceptance harness reads ``<store_root>/reports/*.json`` and the demo store
    is a read-only fixture that this run must not write into.
    """
    roots = [DEFAULT_REPORT_ROOT]
    if store is not None:
        root = getattr(store, "root", None) or store
        candidate = Path(root).resolve()
        candidate = candidate if candidate.name == "reports" else candidate / "reports"
        try:
            candidate.relative_to(DEMO_STORE_ROOT.resolve())
            inside_demo = True
        except ValueError:
            inside_demo = False
        if not inside_demo and candidate not in roots:
            roots.append(candidate)
    return roots


def _resolve_store(store: Any):
    from ..storage.store import AssetStore

    if store is None:
        return AssetStore(DEMO_STORE_ROOT)
    if isinstance(store, AssetStore):
        return store
    return AssetStore(Path(store))


@contextmanager
def _capture_fd(path: Path) -> Iterator[bool]:
    """Capture the C++ (glog) stdout/stderr of one pycolmap call into ``path``.

    Returns whether the capture is active; a failure to redirect is reported instead of
    silently dropping the log.
    """
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    saved: tuple[int, int] | None = None
    handle = None
    try:
        saved = (os.dup(1), os.dup(2))
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "wb")
        os.dup2(handle.fileno(), 1)
        os.dup2(handle.fileno(), 2)
    except Exception:  # noqa: BLE001 - capture is best effort, execution is not
        if saved is not None:
            os.close(saved[0])
            os.close(saved[1])
        if handle is not None:
            handle.close()
        yield False
        return
    try:
        yield True
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:  # noqa: BLE001
            pass
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        os.close(saved[0])
        os.close(saved[1])
        handle.close()


def _stage(*, log_dir: Path, index: int, stage: str, argv: list[str],
           body: Callable[[], Any]) -> dict[str, Any]:
    """Run one pipeline stage, writing its log and JSON record to disk immediately."""
    entry: dict[str, Any] = {
        "index": int(index), "stage": stage, "argv": list(argv), "status": "RUN",
        "returncode": None, "seconds": 0.0, "error": None, "result": None,
        "log_captured": False, "log_path": None, "log_bytes": 0, "log_tail": "",
    }
    log_path = log_dir / f"{index:02d}_{stage}.log"
    entry["log_path"] = _rel(log_path)
    started = time.time()
    try:
        with _capture_fd(log_path) as captured:
            entry["log_captured"] = bool(captured)
            entry["result"] = body()
        entry["status"] = "OK"
        entry["returncode"] = 0
    except Exception as exc:  # noqa: BLE001 - every stage failure is reported, not raised
        entry["status"] = "FAIL"
        entry["returncode"] = 1
        entry["error"] = f"{type(exc).__name__}: {exc}"
        entry["trace"] = traceback.format_exc()[-2000:]
    finally:
        entry["seconds"] = round(time.time() - started, 3)
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8", errors="replace")
            entry["log_bytes"] = len(text)
            entry["log_tail"] = text[-1200:]
        _write_json(log_dir / f"{index:02d}_{stage}.json",
                    {k: v for k, v in entry.items() if k != "trace"})
    return entry


def _sha256_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        if not path.exists():
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def _db_stats(db_path: Path) -> dict[str, Any]:
    """Read the COLMAP database directly: keypoints, matches, pose priors, cameras.

    Two hashes are recorded because the stages differ in determinism:

    * ``keypoints_hash`` covers ``cameras/images/keypoints/descriptors`` - the *input to
      features* mapping, which is bit-repeatable for identical images and options;
    * ``matches_hash`` covers ``matches/two_view_geometries``, whose RANSAC verification is
      not bit-repeatable on this build (measured: +-0.05 % pairs on identical input);
    * ``db_hash`` covers everything and is therefore only comparable within that noise.
    """
    stats: dict[str, Any] = {"db": _rel(db_path)}
    if not db_path.exists():
        stats["exists"] = False
        return stats
    stats["exists"] = True
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()

        def table_hash(tables: tuple[tuple[str, str], ...]) -> str:
            digest = hashlib.sha256()
            for table, order in tables:
                digest.update(table.encode("utf-8"))
                try:
                    rows = cur.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
                except sqlite3.OperationalError:
                    continue
                for row in rows:
                    digest.update(repr(tuple(row)).encode("utf-8"))
            return "sha256:" + digest.hexdigest()

        features = (("cameras", "camera_id"), ("images", "image_id"),
                    ("keypoints", "image_id"), ("descriptors", "image_id"))
        geometry = (("matches", "pair_id"), ("two_view_geometries", "pair_id"))
        stats["keypoints_hash"] = table_hash(features)
        stats["matches_hash"] = table_hash(geometry)
        stats["db_hash"] = table_hash(features + geometry)
        cur.execute("SELECT COUNT(*) FROM images")
        stats["images"] = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*), COALESCE(SUM(rows),0) FROM keypoints")
        rows = cur.fetchone()
        stats["keypoint_images"], stats["keypoints"] = int(rows[0]), int(rows[1])
        cur.execute("SELECT COUNT(*), COALESCE(SUM(rows),0) FROM matches")
        rows = cur.fetchone()
        stats["matched_pairs"], stats["matches"] = int(rows[0]), int(rows[1])
        cur.execute("SELECT COALESCE(MAX(rows),0) FROM matches")
        stats["max_matches_per_pair"] = int(cur.fetchone()[0])
        try:
            cur.execute("SELECT COUNT(*) FROM pose_priors")
            stats["pose_priors"] = int(cur.fetchone()[0])
        except sqlite3.OperationalError:
            stats["pose_priors"] = None
        try:
            cur.execute("SELECT COUNT(*) FROM two_view_geometries")
            stats["two_view_geometries"] = int(cur.fetchone()[0])
        except sqlite3.OperationalError:
            stats["two_view_geometries"] = None
        cur.execute("SELECT camera_id, model, width, height, params FROM cameras")
        stats["cameras"] = [{"camera_id": int(r[0]), "model": str(r[1]), "width": int(r[2]),
                             "height": int(r[3]),
                             "params": [float(v) for v in np.frombuffer(r[4], dtype=np.float64)]}
                            for r in cur.fetchall()] if stats["images"] else []
    finally:
        con.close()
    return stats


def _capability_probe() -> dict[str, Any]:
    """What the installed pycolmap/COLMAP can actually do here (measured, not assumed)."""
    probe: dict[str, Any] = {"import": False}
    try:
        import pycolmap

        probe["import"] = True
        probe["version"] = str(getattr(pycolmap, "__version__", "unknown"))
        probe["has_cuda"] = bool(getattr(pycolmap, "has_cuda", False))
        for symbol in ("extract_features", "match_exhaustive", "match_sequential",
                       "incremental_mapping", "undistort_images", "patch_match_stereo",
                       "stereo_fusion", "triangulate_points"):
            probe[f"has_{symbol}"] = bool(hasattr(pycolmap, symbol))
        probe["camera_models"] = sorted(pycolmap.CameraModelId.__members__.keys()) \
            if hasattr(pycolmap, "CameraModelId") else []
    except Exception as exc:  # noqa: BLE001
        probe["error"] = f"{type(exc).__name__}: {exc}"
    probe["standalone_colmap_binary"] = shutil.which("colmap")
    return probe


# --------------------------------------------------------------------------------------
# mothers
# --------------------------------------------------------------------------------------
def _select_mothers(store: Any, limit: int, cfg: MvsConfig) -> list[dict[str, Any]]:
    """Committed mothers when the store has them, otherwise a real ``create_mother`` build."""
    from ..mothers.api import create_mother, default_params, load_mother, vessel_ids
    from ..roles import ROLE_MOTHER_MESH
    from ..seeds import make_rng

    limit = max(int(limit), 1)
    records = sorted(store.list_assets(role=ROLE_MOTHER_MESH, limit=10000),
                     key=lambda record: record.asset_id)
    picked: list[dict[str, Any]] = []
    for record in records[:limit]:
        mother = load_mother(store, record.asset_id)
        picked.append({
            "mother": mother,
            "source": "COMMITTED_ASSET",
            "asset_id": record.asset_id,
            "split": record.split,
            "lineage_id": record.lineage_id,
            "geometry_hash": (record.meta or {}).get("geometry_hash"),
            "vessel_id": mother.vessel_id,
            "material_id": mother.material_id,
            "mother_id": mother.mother_id,
            "n_faces": int(len(mother.mesh.faces)),
        })
    if picked:
        return picked
    # No committed mother in this store: build one with the real registry builder.
    vessel = vessel_ids()[0]
    material = "M03"
    rng = make_rng(cfg.seed, cfg.lineage_id, "mvs_subset.mother")
    mother = create_mother(vessel, material, default_params(vessel), rng,
                           mother_id=f"mvs_{vessel}_{material}")
    picked.append({
        "mother": mother, "source": "CREATED_IN_RUN", "asset_id": None, "split": "train",
        "lineage_id": cfg.lineage_id, "geometry_hash": None, "vessel_id": vessel,
        "material_id": material, "mother_id": mother.mother_id,
        "n_faces": int(len(mother.mesh.faces)),
    })
    return picked


def _profile(tier: str = "MID"):
    from ..cameras.api import camera_profiles

    profiles = camera_profiles()
    for profile in profiles:
        if str(profile.tier) == tier:
            return profile
    return profiles[1]


# --------------------------------------------------------------------------------------
# frame rendering
# --------------------------------------------------------------------------------------
def _render_frames(target: Any, profile: Any, cfg: MvsConfig, out_dir: Path,
                   *, prefix: str = "view", seed_offset: int = 17) -> list[dict[str, Any]]:
    """Render the overlapping cache, write images/masks and return the frame records."""
    import cv2

    from .imaging import ImagingSpec
    from .render import RenderSpec, write_mask_png
    from .routes import ObsSpec, render_views

    spec = ObsSpec(
        view_count=int(cfg.frames_per_fragment),
        delivered_size=(int(cfg.delivered_size[0]), int(cfg.delivered_size[1])),
        max_render_pixels=int(cfg.render_pixels),
        render_spec=RenderSpec(supersample=int(cfg.supersample),
                               coc_px_threshold=float(cfg.coc_px_threshold)),
        imaging=ImagingSpec(effective_gain=float(cfg.effective_gain),
                            read_noise_sigma=float(cfg.read_noise_sigma)),
        master_seed=int(cfg.seed), lineage_id=cfg.lineage_id, workdir=str(out_dir),
    )
    rng = np.random.Generator(np.random.PCG64(np.uint64(cfg.seed + seed_offset)))
    bundles = render_views(target, profile, spec, rng)
    images_dir = out_dir / "images"
    masks_dir = out_dir / "masks"
    images_dir.mkdir(parents=True, exist_ok=True)
    masks_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    for index, bundle in enumerate(bundles):
        name = f"{prefix}_{index:03d}.png"
        image = np.asarray(bundle.imaging.image)
        if not cv2.imwrite(str(images_dir / name), image[:, :, ::-1]):
            raise SynLabError(INPUT_UNAVAILABLE, f"could not write {images_dir / name}",
                              stage="observe.mvs_subset.render")
        write_mask_png(bundle.deploy_mask, str(masks_dir / f"{name}.png"))
        frames.append({
            "name": name,
            "image_path": _rel(images_dir / name),
            "mask_path": _rel(masks_dir / f"{name}.png"),
            "image_size": [int(image.shape[1]), int(image.shape[0])],
            "K": np.asarray(bundle.K, dtype=np.float64).tolist(),
            "pixel_affine_A": np.asarray(bundle.A, dtype=np.float64).tolist(),
            "T_WC": np.asarray(bundle.frame.T_WC, dtype=np.float64).tolist(),
            "object_pose_T_WO": np.asarray(bundle.object_pose, dtype=np.float64).tolist(),
            "convention": "opencv_pixel_center_0_0",
            "pixel_convention_note": "K is OpenCV-centred; COLMAP input uses +0.5 px",
            "view_id": bundle.frame.view_id,
            "tier": str(bundle.frame.tier),
            "profile_id": bundle.frame.profile_id,
            "working_distance_mm": float(bundle.frame.working_distance_mm),
            "mm_per_pixel": float(bundle.frame.working_distance_mm / float(bundle.frame.K[0, 0])),
            "azimuth_deg": bundle.frame.meta.get("azimuth_deg"),
            "elevation_deg": bundle.frame.meta.get("elevation_deg"),
            "source_kind": str(bundle.frame.source_kind),
            "pose_source_kind": str(bundle.frame.source_kind),
            "simulator_pose_is_label_only": True,
            "mask_coverage": float(np.mean(bundle.deploy_mask)),
            "visibility_fraction": float(np.mean(np.asarray(bundle.render.visibility) > 0)),
            "uncertain_fraction": float(np.mean(np.asarray(bundle.render.uncertain_mask))),
            "depth_is_render_reference_only": True,
        })
    return frames


def _write_frame_table(out_dir: Path, frames: list[dict[str, Any]], *, name: str,
                       corrupted: bool = False, rng: np.random.Generator | None = None
                       ) -> dict[str, Any]:
    """Write a *ground-truth pose table* next to the frames.

    This table is forensic material for :func:`audit_source_dependency`: it is never an
    input to the reconstruction, and the audit proves that by re-running the same frames
    with a corrupted copy of it.
    """
    payload: dict[str, Any] = {
        "schema": "synlab.mvs_subset.pose_table.v1",
        "note": ("simulator ground truth for forensic invariance checks only; the COLMAP "
                 "pipeline must never read this file"),
        "unit": "mm",
        "frame": "world (Z-up)",
        "corrupted": bool(corrupted),
        "frames": [],
    }
    rng = rng or np.random.Generator(np.random.PCG64(np.uint64(0xBEEF)))
    axis = np.array([0.37, -0.62, 0.69], dtype=np.float64)
    axis /= np.linalg.norm(axis)
    angle = np.deg2rad(37.0)
    R = np.array([[np.cos(angle) + axis[0] ** 2 * (1 - np.cos(angle)),
                   axis[0] * axis[1] * (1 - np.cos(angle)) - axis[2] * np.sin(angle),
                   axis[0] * axis[2] * (1 - np.cos(angle)) + axis[1] * np.sin(angle)],
                  [axis[1] * axis[0] * (1 - np.cos(angle)) + axis[2] * np.sin(angle),
                   np.cos(angle) + axis[1] ** 2 * (1 - np.cos(angle)),
                   axis[1] * axis[2] * (1 - np.cos(angle)) - axis[0] * np.sin(angle)],
                  [axis[2] * axis[0] * (1 - np.cos(angle)) - axis[1] * np.sin(angle),
                   axis[2] * axis[1] * (1 - np.cos(angle)) + axis[0] * np.sin(angle),
                   np.cos(angle) + axis[2] ** 2 * (1 - np.cos(angle))]])
    delta_t = np.array([512.0, -333.0, 271.0], dtype=np.float64)
    for frame in frames:
        T = np.asarray(frame["T_WC"], dtype=np.float64).copy()
        if corrupted:
            T[:3, :3] = R @ T[:3, :3]
            T[:3, 3] = T[:3, 3] + delta_t
        payload["frames"].append({"name": frame["name"], "T_WC": T.tolist()})
    payload["corruption"] = ({"rotation_deg": 37.0, "axis": axis.tolist(),
                              "translation_mm": delta_t.tolist()} if corrupted else None)
    _write_json(out_dir / name, payload)
    return payload


# --------------------------------------------------------------------------------------
# the pycolmap pipeline
# --------------------------------------------------------------------------------------
def _sparse_pipeline(*, workdir: Path, frames: list[dict[str, Any]], cfg: MvsConfig,
                     probe: dict[str, Any], use_mask: bool, tag: str,
                     log_dir: Path, start_index: int = 1) -> dict[str, Any]:
    """extract_features -> matcher -> incremental_mapping; returns a real stage report."""
    images_dir = workdir / "images"
    masks_dir = workdir / "masks"
    names = [frame["name"] for frame in frames]
    db_path = workdir / f"database_{tag}.db"
    sparse_dir = workdir / f"sparse_{tag}"
    for path in (db_path,):
        if path.exists():
            path.unlink()
    shutil.rmtree(sparse_dir, ignore_errors=True)
    sparse_dir.mkdir(parents=True, exist_ok=True)

    stages: list[dict[str, Any]] = []
    index = start_index
    if not probe.get("import"):
        return {"tag": tag, "use_mask": bool(use_mask), "stages": stages,
                "failure_code": MVS_NOT_AVAILABLE,
                "failure_reason": f"pycolmap is not importable: {probe.get('error')}",
                "ok": False}

    import pycolmap

    threads = 1 if cfg.deterministic else 2
    if cfg.deterministic:
        pycolmap.set_random_seed(int(cfg.seed))
    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = cfg.camera_model
    if use_mask:
        reader.mask_path = str(masks_dir)
    sift = pycolmap.SiftExtractionOptions()
    sift.max_image_size = int(cfg.max_image_size)
    sift.max_num_features = int(cfg.max_num_features)
    sift.num_threads = threads
    camera_mode = getattr(pycolmap.CameraMode, cfg.camera_mode.upper(),
                          pycolmap.CameraMode.SINGLE)
    extract = _stage(
        log_dir=log_dir, index=index, stage=f"extract_features_{tag}",
        argv=["pycolmap.extract_features", f"--database_path={db_path}",
              f"--image_path={images_dir}", f"--image_list={len(names)} frames",
              f"--camera_mode={cfg.camera_mode}", f"--camera_model={cfg.camera_model}",
              f"--mask_path={masks_dir if use_mask else ''}",
              f"--SiftExtraction.max_image_size={cfg.max_image_size}",
              f"--SiftExtraction.max_num_features={cfg.max_num_features}",
              "--SiftExtraction.num_threads=2", "device=cpu"],
        body=lambda: pycolmap.extract_features(str(db_path), str(images_dir), names,
                                               camera_mode, cfg.camera_model, reader, sift,
                                               pycolmap.Device.cpu))
    stages.append(extract)
    index += 1
    if extract["status"] != "OK":
        return {"tag": tag, "use_mask": bool(use_mask), "stages": stages,
                "failure_code": STOP_SFM,
                "failure_reason": f"feature extraction failed: {extract['error']}",
                "db": _db_stats(db_path), "ok": False}

    matcher = cfg.resolved_matcher(len(names))
    sift_match = pycolmap.SiftMatchingOptions()
    # pycolmap 3.11.1 default-constructs SiftMatchingOptions with max_num_matches=0 for the
    # C++ default argument of match_* and then aborts on a CHECK; every field is set here.
    sift_match.max_num_matches = int(cfg.max_num_matches)
    sift_match.max_ratio = 0.8
    sift_match.max_distance = 0.7
    sift_match.cross_check = True
    sift_match.num_threads = threads
    two_view = pycolmap.TwoViewGeometryOptions()
    two_view.min_num_inliers = 15
    if matcher == "sequential":
        match_options = pycolmap.SequentialMatchingOptions()
        match_options.overlap = 10
        match_fn = lambda: pycolmap.match_sequential(str(db_path), sift_match, match_options,  # noqa: E731
                                                     two_view, pycolmap.Device.cpu)
    else:
        match_options = pycolmap.ExhaustiveMatchingOptions()
        match_fn = lambda: pycolmap.match_exhaustive(str(db_path), sift_match, match_options,  # noqa: E731
                                                     two_view, pycolmap.Device.cpu)
    match = _stage(
        log_dir=log_dir, index=index, stage=f"{matcher}_matcher_{tag}",
        argv=[f"pycolmap.match_{matcher}", f"--database_path={db_path}",
              f"--SiftMatching.max_num_matches={cfg.max_num_matches}",
              "--SiftMatching.max_ratio=0.8", "--SiftMatching.max_distance=0.7",
              "--SiftMatching.cross_check=1", "--SiftMatching.use_gpu=0",
              "--TwoViewGeometry.min_num_inliers=15", "device=cpu"],
        body=match_fn)
    stages.append(match)
    index += 1
    if match["status"] != "OK":
        return {"tag": tag, "use_mask": bool(use_mask), "stages": stages,
                "failure_code": STOP_SFM,
                "failure_reason": f"{matcher} matching failed: {match['error']}",
                "db": _db_stats(db_path), "ok": False}

    pipeline_options = pycolmap.IncrementalPipelineOptions()
    pipeline_options.multiple_models = False
    pipeline_options.num_threads = threads
    if cfg.init_pair is not None:
        pipeline_options.init_image_id1 = int(cfg.init_pair[0])
        pipeline_options.init_image_id2 = int(cfg.init_pair[1])
    mapper = _stage(
        log_dir=log_dir, index=index, stage=f"incremental_mapping_{tag}",
        argv=["pycolmap.incremental_mapping", f"--database_path={db_path}",
              f"--image_path={images_dir}", f"--output_path={sparse_dir}",
              "--IncrementalPipeline.multiple_models=0",
              f"--IncrementalPipeline.num_threads={threads}",
              (f"--IncrementalPipeline.init_image_id1={cfg.init_pair[0]}"
               f" --IncrementalPipeline.init_image_id2={cfg.init_pair[1]}"
               if cfg.init_pair is not None else "--init_image_id=auto")],
        body=lambda: pycolmap.incremental_mapping(str(db_path), str(images_dir),
                                                  str(sparse_dir), pipeline_options))
    stages.append(mapper)
    index += 1
    db_stats = _db_stats(db_path)
    models: dict[int, Any] = mapper.get("result") or {} if mapper["status"] == "OK" else {}
    model_dirs = sorted(path for path in sparse_dir.iterdir()
                        if path.is_dir() and (path / "cameras.bin").exists())
    if mapper["status"] != "OK":
        return {"tag": tag, "use_mask": bool(use_mask), "stages": stages, "db": db_stats,
                "failure_code": STOP_SFM,
                "failure_reason": f"incremental_mapping failed: {mapper['error']}", "ok": False}
    if not models and not model_dirs:
        return {"tag": tag, "use_mask": bool(use_mask), "stages": stages, "db": db_stats,
                "failure_code": STOP_SFM,
                "failure_reason": ("incremental_mapping returned no reconstruction "
                                   f"({db_stats.get('matched_pairs', 0)} matched pairs, "
                                   f"{db_stats.get('matches', 0)} matches)"),
                "ok": False}
    reconstruction = None
    if models:
        best = max(models, key=lambda key: models[key].num_reg_images())
        reconstruction = models[best]
        model_id = int(best)
    else:  # pragma: no cover - pycolmap always returns the models here
        reconstruction = pycolmap.Reconstruction(str(model_dirs[0]))
        model_id = 0
    registered = int(reconstruction.num_reg_images())
    report = {
        "tag": tag, "use_mask": bool(use_mask), "stages": stages, "db": db_stats,
        "model_id": model_id,
        "n_models": len(models) if models else len(model_dirs),
        "num_cameras": int(reconstruction.num_cameras()),
        "registered_frames": registered,
        "registered_fraction": float(registered / max(len(names), 1)),
        "sparse_points": int(reconstruction.num_points3D()),
        "mean_reprojection_error_px": float(reconstruction.compute_mean_reprojection_error()),
        "mean_track_length": float(reconstruction.compute_mean_track_length()),
        "mean_observations_per_reg_image": float(
            reconstruction.compute_mean_observations_per_reg_image()),
        "registered_names": sorted(reconstruction.image(image_id).name
                                   for image_id in reconstruction.reg_image_ids()),
        "sparse_dir": _rel(sparse_dir / str(model_id)),
        "model_hash": _sha256_files([sparse_dir / str(model_id) / name
                                     for name in ("cameras.bin", "images.bin", "points3D.bin")]),
        "cameras": [reconstruction.camera(camera_id).summary().splitlines()[2].strip()
                    for camera_id in reconstruction.cameras],
        "ok": True,
    }
    if registered < int(cfg.min_registered_frames):
        report["ok"] = False
        report["failure_code"] = STOP_SFM
        report["failure_reason"] = (
            f"only {registered} of {len(names)} frames registered "
            f"(< min_registered_frames={cfg.min_registered_frames})")
    return report


def _estimated_poses(reconstruction: Any) -> dict[str, dict[str, Any]]:
    """Estimated camera poses from the reconstruction (labels for the report only)."""
    poses: dict[str, dict[str, Any]] = {}
    for image_id in reconstruction.reg_image_ids():
        image = reconstruction.image(image_id)
        T_CW = np.eye(4, dtype=np.float64)
        T_CW[:3, :3] = np.asarray(image.cam_from_world.rotation.matrix(), dtype=np.float64)
        T_CW[:3, 3] = np.asarray(image.cam_from_world.translation, dtype=np.float64)
        T_WC = np.linalg.inv(T_CW)
        camera = reconstruction.camera(image.camera_id)
        poses[str(image.name)] = {
            "image_id": int(image_id),
            "camera_id": int(image.camera_id),
            "T_WC_estimated": T_WC.tolist(),
            "projection_center": np.asarray(T_WC[:3, 3], dtype=np.float64).tolist(),
            "K_estimated": np.asarray(camera.calibration_matrix(), dtype=np.float64).tolist(),
            "n_points2D": int(len(image.points2D)),
            "n_observations": int(sum(1 for point in image.points2D if point.has_point3D())),
            "unit": "SfM arbitrary unit (no scale source)",
        }
    return poses


def _dense_pipeline(*, workdir: Path, frames: list[dict[str, Any]], sparse: dict[str, Any],
                    cfg: MvsConfig, probe: dict[str, Any], log_dir: Path,
                    start_index: int) -> dict[str, Any]:
    """undistort_images -> patch_match_stereo -> stereo_fusion, each recorded for real."""
    import pycolmap

    images_dir = workdir / "images"
    names = [frame["name"] for frame in frames]
    model_dir = ROOT / sparse["sparse_dir"]
    dense_dir = workdir / f"dense_{sparse['tag']}"
    shutil.rmtree(dense_dir, ignore_errors=True)
    dense_dir.mkdir(parents=True, exist_ok=True)
    stages: list[dict[str, Any]] = []
    index = int(start_index)

    undistort = _stage(
        log_dir=log_dir, index=index, stage=f"image_undistorter_{sparse['tag']}",
        argv=["pycolmap.undistort_images", f"--output_path={dense_dir}",
              f"--input_path={model_dir}", f"--image_path={images_dir}",
              f"--output_type=COLMAP", f"--image_list={len(names)} frames"],
        body=lambda: pycolmap.undistort_images(str(dense_dir), str(model_dir), str(images_dir),
                                               names))
    stages.append(undistort)
    index += 1
    workspace_ok = (dense_dir / "sparse").exists()
    result: dict[str, Any] = {
        "backend": "PATCHMATCH", "stages": stages, "workspace": _rel(dense_dir),
        "workspace_ok": bool(workspace_ok),
        "workspace_files": sorted(_rel(path) for path in dense_dir.rglob("*") if path.is_file())[:40],
        "patch_match_cfg": _rel(dense_dir / "stereo" / "patch-match.cfg"),
        "dense_points": 0,
        "fused_ply": None,
        "status": "NOT_RUN",
        "failure_code": None,
        "failure_reason": None,
    }
    if undistort["status"] != "OK" or not workspace_ok:
        result["status"] = "FAIL"
        result["failure_code"] = MVS_FAILED
        result["failure_reason"] = (
            "image_undistorter did not produce a COLMAP dense workspace: "
            f"{undistort.get('error') or 'no sparse/ directory'}")
        return result

    # ---- patch_match_stereo: the symbol simply does not exist in pycolmap 3.11.1
    if not probe.get("has_patch_match_stereo"):
        result["status"] = "MVS_NOT_AVAILABLE"
        result["failure_code"] = MVS_NOT_AVAILABLE
        result["failure_reason"] = (
            "pycolmap 3.11.1 exposes no patch_match_stereo symbol"
            f" (has_cuda={probe.get('has_cuda')}, standalone colmap binary="
            f"{probe.get('standalone_colmap_binary')!r}); the dense MVS stage cannot be "
            "executed here and is not reported as a successful dense run")
        result["patch_match_stage"] = {
            "argv": ["pycolmap.patch_match_stereo", f"--workspace_path={dense_dir}",
                     "--PatchMatchStereo.geom_consistency=true"],
            "status": "MVS_NOT_AVAILABLE", "executed": False,
            "reason": "symbol absent from the installed pycolmap build",
        }
        result["depth_maps"] = len(list((dense_dir / "stereo" / "depth_maps").glob("*")))
        result["normal_maps"] = len(list((dense_dir / "stereo" / "normal_maps").glob("*")))
    elif not probe.get("has_cuda"):
        result["status"] = "MVS_NOT_AVAILABLE"
        result["failure_code"] = MVS_NOT_AVAILABLE
        result["failure_reason"] = ("PatchMatch stereo requires CUDA and this pycolmap build "
                                    f"reports has_cuda={probe.get('has_cuda')}")
        result["patch_match_stage"] = {"status": "MVS_NOT_AVAILABLE", "executed": False,
                                       "reason": "no CUDA device"}
    else:  # pragma: no cover - no CUDA host in this environment
        patch = _stage(
            log_dir=log_dir, index=index, stage=f"patch_match_stereo_{sparse['tag']}",
            argv=["pycolmap.patch_match_stereo", f"--workspace_path={dense_dir}",
                  "--PatchMatchStereo.geom_consistency=true"],
            body=lambda: pycolmap.patch_match_stereo(str(dense_dir)))
        stages.append(patch)
        index += 1
        result["patch_match_stage"] = {k: v for k, v in patch.items() if k != "trace"}
        if patch["status"] != "OK":
            result["status"] = "FAIL"
            result["failure_code"] = MVS_FAILED
            result["failure_reason"] = f"patch_match_stereo failed: {patch['error']}"
            return result
        result["depth_maps"] = len(list((dense_dir / "stereo" / "depth_maps").glob("*")))

    # ---- stereo_fusion always runs for real (it is available and reports its own truth)
    fused_ply = workdir / f"fused_{sparse['tag']}.ply"
    fusion = _stage(
        log_dir=log_dir, index=index, stage=f"stereo_fusion_{sparse['tag']}",
        argv=["pycolmap.stereo_fusion", f"--output_path={fused_ply}",
              f"--workspace_path={dense_dir}", "--workspace_format=COLMAP",
              "--input_type=geometric", "--StereoFusion.min_num_pixels=5"],
        body=lambda: pycolmap.stereo_fusion(str(fused_ply), str(dense_dir)))
    stages.append(fusion)
    index += 1
    result["fusion_stage"] = {k: v for k, v in fusion.items() if k != "trace"}
    if fusion["status"] == "OK":
        fused = fusion.get("result")
        result["dense_points"] = int(fused.num_points3D()) if fused is not None else 0
        result["fused_ply"] = _rel(fused_ply)
        result["fused_ply_bytes"] = fused_ply.stat().st_size if fused_ply.exists() else 0
    if result["dense_points"] <= 0:
        result["status"] = "MVS_NOT_AVAILABLE"
        result["failure_code"] = MVS_NOT_AVAILABLE
        result["failure_reason"] = (
            "stereo_fusion produced 0 dense points because the patch-match depth/normal maps "
            "do not exist on this host (no patch_match_stereo); the fusion stage itself ran "
            "and its log is recorded")
    else:
        result["status"] = "OK"
    return result


# --------------------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------------------
def run_mvs_subset(store: Any = None, *, limit_mothers: int = 1,
                   frames_per_fragment: int | None = None, out_dir: Any = None,
                   config: MvsConfig | None = None,
                   write_report: bool = True) -> dict[str, Any]:
    """Run the real COLMAP subset on rendered frames and write ``mvs_subset.json``.

    ``store`` may be an :class:`~synlab.storage.store.AssetStore`, a store root path or
    ``None`` (the committed demo store is used).  Mothers come from the store's committed
    ``mother_mesh`` assets when present, otherwise from a real
    :func:`~synlab.mothers.api.create_mother` build.
    """
    from ..roles import ROLE_MOTHER_MESH  # noqa: F401  (documented dependency)
    from .routes import ROUTE_PHOTO_MVS, ROUTE_SPECS, resolve_target

    started = time.time()
    resolved_store = _resolve_store(store)
    cfg = config or MvsConfig()
    if frames_per_fragment is not None:
        cfg.frames_per_fragment = max(int(frames_per_fragment), 2)
    workdir = Path(out_dir) if out_dir is not None else DEFAULT_WORK_ROOT / "subset"
    workdir.mkdir(parents=True, exist_ok=True)
    log_dir = workdir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    probe = _capability_probe()
    failures: list[dict[str, Any]] = []
    argv_log: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    mothers_report: list[dict[str, Any]] = []
    sparse: dict[str, Any] = {}
    dense: dict[str, Any] = {}
    profile = _profile("MID")

    report: dict[str, Any] = {
        "schema": "synlab.mvs_subset.v1",
        "route": ROUTE_PHOTO_MVS,
        "claim_boundary": ROUTE_SPECS[ROUTE_PHOTO_MVS]["claim_boundary"],
        "evidence_class": ROUTE_SPECS[ROUTE_PHOTO_MVS]["evidence_class"],
        "data_scope": DATA_SCOPE_SYNTHETIC,
        "real_capture": DATA_SCOPE_REAL + ":PENDING",
        "real_calibration_ok": False,
        "ok": False,
        "pipeline_ok": False,
        "attempted": 0,
        "registered_frames": 0,
        "registered_fraction": 0.0,
        "sparse_points": 0,
        "dense_points": 0,
        "reprojection_error_px": float("nan"),
        "seconds": 0.0,
        "frames": frames,
        "failures": failures,
        "failure_code": None,
        "failure_reason": None,
        "subset": {
            "limit_mothers": int(limit_mothers),
            "frames_per_fragment": int(cfg.frames_per_fragment),
            "plan_frames_per_fragment": list(PLAN_FRAMES_PER_FRAGMENT),
            "fragment_kind": "WHOLE_MOTHER_SURFACE",
            "plan_reference": "plan 14.4 (synthetic-render COLMAP subset)",
            "planned_full_subset": {"mothers": 2, "fragments": 20},
            "note": ("this host runs a reduced subset (1 mother, whole-surface fragment); "
                     "the per-fragment frame budget is below the plan's 30-120 guidance"),
        },
        "config": asdict(cfg) | {"matcher": cfg.resolved_matcher(cfg.frames_per_fragment)},
        "capability_probe": probe,
        "gt_inputs_used": {"poses": False, "depth": False, "scale": False},
        "argv_log": argv_log,
        "attempts": attempts,
        "mothers": mothers_report,
        "workdir": _rel(workdir),
        "log_dir": _rel(log_dir),
        "evidence": ["synlab/observe/mvs_subset.py", "synlab/observe/routes.py",
                     "data/a12/reports/mvs_subset.json"],
    }
    if not probe.get("import"):
        report["failure_code"] = MVS_NOT_AVAILABLE
        report["failure_reason"] = f"pycolmap unavailable: {probe.get('error')}"
        failures.append({"stage": "capability_probe", "code": MVS_NOT_AVAILABLE,
                         "reason": report["failure_reason"]})
        return _finish(report, resolved_store, workdir, started, write_report)

    # ---- mothers
    try:
        picked = _select_mothers(resolved_store, limit_mothers, cfg)
    except Exception as exc:  # noqa: BLE001
        report["failure_code"] = INPUT_UNAVAILABLE
        report["failure_reason"] = f"no usable mother: {type(exc).__name__}: {exc}"
        failures.append({"stage": "select_mothers", "code": INPUT_UNAVAILABLE,
                         "reason": report["failure_reason"]})
        return _finish(report, resolved_store, workdir, started, write_report)

    # ---- frames + sparse runs (one attempt per mother; the invariant is one fragment here)
    index = 1
    attempted_paths: list[str] = []
    for mother_index, entry in enumerate(picked):
        mother = entry["mother"]
        mother_dir = workdir / f"mother_{mother_index:02d}"
        target = resolve_target(mother.mesh, fragment_id=f"{entry['mother_id']}_surface")
        try:
            mother_frames = _render_frames(target, profile, cfg, mother_dir,
                                           prefix=f"m{mother_index:02d}_v")
        except Exception as exc:  # noqa: BLE001
            reason = f"render failed: {type(exc).__name__}: {exc}"
            failures.append({"stage": "render", "code": MVS_FAILED, "reason": reason,
                             "mother": entry["mother_id"]})
            report["failure_code"] = report["failure_code"] or MVS_FAILED
            report["failure_reason"] = report["failure_reason"] or reason
            continue
        frames.extend(mother_frames)
        attempted_paths.append(_rel(mother_dir))
        mothers_report.append({k: v for k, v in entry.items() if k != "mother"} | {
            "n_frames": len(mother_frames),
            "workdir": _rel(mother_dir),
            "mean_mask_coverage": float(np.mean([f["mask_coverage"] for f in mother_frames])),
            "image_size": mother_frames[0]["image_size"] if mother_frames else None,
        })
        _write_frame_table(mother_dir, mother_frames, name="gt_poses_true.json")
        _write_frame_table(mother_dir, mother_frames, name="gt_poses_corrupted.json",
                           corrupted=True)

        mean_mask = float(np.mean([f["mask_coverage"] for f in mother_frames]))
        if cfg.use_mask == "always":
            use_mask = True
        elif cfg.use_mask == "never":
            use_mask = False
        else:
            use_mask = bool(mean_mask >= cfg.min_mask_coverage)
        mother_attempts: list[dict[str, Any]] = []
        attempt = _sparse_pipeline(workdir=mother_dir, frames=mother_frames, cfg=cfg,
                                   probe=probe, use_mask=use_mask,
                                   tag=f"m{mother_index:02d}", log_dir=log_dir,
                                   start_index=index)
        index += len(attempt["stages"])
        attempt.update({
            "mother_index": mother_index, "mother_id": entry["mother_id"],
            "mean_mask_coverage": mean_mask, "mask_used": bool(use_mask),
            "mask_decision": ("mask coverage %.3f %s min_mask_coverage=%.3f"
                              % (mean_mask, ">=" if use_mask else "<", cfg.min_mask_coverage)),
        })
        mother_attempts.append(attempt)
        if not attempt.get("ok") and use_mask:
            # A mask that starves the feature extractor must not be reported as an SfM
            # failure of the pipeline: retry the same frames without the mask.
            retry = _sparse_pipeline(workdir=mother_dir, frames=mother_frames, cfg=cfg,
                                     probe=probe, use_mask=False,
                                     tag=f"m{mother_index:02d}_nomask", log_dir=log_dir,
                                     start_index=index)
            index += len(retry["stages"])
            retry.update({
                "mother_index": mother_index, "mother_id": entry["mother_id"],
                "mean_mask_coverage": mean_mask, "mask_used": False,
                "mask_decision": "retry without the deployment mask after a masked failure",
            })
            mother_attempts.append(retry)
        for item in mother_attempts:
            attempts.append({k: v for k, v in item.items() if k != "stages"})
            argv_log.extend(_strip_traces(item["stages"]))
        best_of_mother = max(mother_attempts,
                             key=lambda item: (int(item.get("registered_frames", 0)),
                                               int(item.get("sparse_points", 0))))
        if not sparse or (best_of_mother.get("registered_frames", 0),
                          best_of_mother.get("sparse_points", 0)) > \
                (sparse.get("registered_frames", 0), sparse.get("sparse_points", 0)):
            sparse = best_of_mother
        sparse.setdefault("mother_workdir", _rel(mother_dir))
        sparse["mother_workdir"] = _rel(mother_dir)
        sparse["mother_frames"] = mother_frames

    report["attempted"] = len(frames)
    if not frames:
        report["failure_code"] = report["failure_code"] or MVS_FAILED
        report["failure_reason"] = report["failure_reason"] or "no frame could be rendered"
        return _finish(report, resolved_store, workdir, started, write_report)

    if sparse and sparse.get("ok"):
        report["pipeline_ok"] = True
        report["registered_frames"] = int(sparse["registered_frames"])
        report["registered_fraction"] = float(sparse["registered_fraction"])
        report["sparse_points"] = int(sparse["sparse_points"])
        report["reprojection_error_px"] = float(sparse["mean_reprojection_error_px"])
        report["sparse"] = {k: v for k, v in sparse.items()
                            if k not in ("stages", "mother_frames")}
        report["estimated_poses"] = ("per-frame estimated cameras are attached to "
                                     "frames[].estimated_pose (labels only)")
    else:
        code = (sparse or {}).get("failure_code", STOP_SFM)
        reason = (sparse or {}).get("failure_reason", "no reconstruction")
        report["failure_code"] = code
        report["failure_reason"] = reason
        failures.append({"stage": "sparse_sfm", "code": code, "reason": reason,
                         "attempts": [item.get("tag") for item in attempts]})
        report["sparse"] = {k: v for k, v in (sparse or {}).items()
                            if k not in ("stages", "mother_frames")}
        report["frames"] = _attach_frame_results(frames, sparse, None, probe)
        return _finish(report, resolved_store, workdir, started, write_report)

    # ---- dense
    if cfg.dense:
        mother_frames = sparse.get("mother_frames") or frames
        mother_dir = ROOT / sparse["mother_workdir"]
        dense = _dense_pipeline(workdir=mother_dir, frames=mother_frames,
                                sparse=sparse, cfg=cfg, probe=probe, log_dir=log_dir,
                                start_index=index)
        index += len(dense["stages"])
        argv_log.extend(_strip_traces(dense["stages"]))
        report["dense"] = {k: v for k, v in dense.items() if k != "stages"}
        report["dense_points"] = int(dense.get("dense_points", 0))
        report["dense_status"] = dense.get("status")
        if dense.get("failure_code"):
            failures.append({"stage": "dense_mvs", "code": dense["failure_code"],
                             "reason": dense.get("failure_reason", ""),
                             "workspace": dense.get("workspace")})
            report["failure_code"] = report["failure_code"] or dense["failure_code"]
            report["failure_reason"] = report["failure_reason"] or dense["failure_reason"]
    else:
        report["dense_status"] = "SKIPPED_BY_CONFIG"
        report["failure_code"] = MVS_NOT_AVAILABLE
        report["failure_reason"] = "dense stage disabled by configuration"

    dense_for_frames = dense if cfg.dense else None
    report["frames"] = _attach_frame_results(frames, sparse, dense_for_frames, probe)
    report["ok"] = bool(report["pipeline_ok"] and report["dense_points"] > 0
                        and report["real_calibration_ok"])
    return _finish(report, resolved_store, workdir, started, write_report)


def _strip_traces(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in stage.items() if k != "trace"} for stage in stages]


def _attach_frame_results(frames: list[dict[str, Any]], sparse: dict[str, Any],
                          dense: dict[str, Any] | None, probe: dict[str, Any]
                          ) -> list[dict[str, Any]]:
    """Merge the SfM outcome into the frame records (registered flag + estimated pose)."""
    registered: set[str] = set(sparse.get("registered_names", []) if sparse else [])
    poses: dict[str, dict[str, Any]] = {}
    if sparse and sparse.get("ok"):
        try:
            import pycolmap

            model_dir = ROOT / sparse["sparse_dir"]
            reconstruction = pycolmap.Reconstruction(str(model_dir))
            poses = _estimated_poses(reconstruction)
        except Exception:  # noqa: BLE001 - the reconstruction stays a report-only artefact
            poses = {}
    out: list[dict[str, Any]] = []
    for frame in frames:
        item = dict(frame)
        item["registered"] = bool(frame["name"] in registered)
        item["estimated_pose"] = poses.get(frame["name"])
        item["dense_available"] = bool(dense and dense.get("dense_points", 0) > 0)
        out.append(item)
    return out


def _finish(report: dict[str, Any], store: Any, workdir: Path, started: float,
            write_report: bool) -> dict[str, Any]:
    """Fill the derived fields, write the report(s) and return it."""
    report["seconds"] = round(time.time() - started, 3)
    report["status"] = "PASS" if report["ok"] else "FAIL"
    error = report.get("reprojection_error_px")
    error = float(error) if error is not None and np.isfinite(error) else None
    report["reprojection_error_px"] = error
    if report.get("pipeline_ok"):
        stage = ("SPARSE_OK_DENSE_OK" if report.get("dense_points", 0) > 0
                 else f"SPARSE_OK_DENSE_{(report.get('dense_status') or 'NOT_RUN')}")
    elif report.get("attempted"):
        stage = f"SPARSE_{report.get('failure_code') or STOP_SFM}"
    else:
        stage = "NOT_RUN"
    report["claim"] = {
        "ok": bool(report["ok"]),
        "requires": ["sparse_qualified", "dense_points>0", "real_calibration"],
        "pipeline_stage": stage,
        "real_calibration_ok": bool(report["real_calibration_ok"]),
        "note": ("``ok`` is the full claim; ``pipeline_ok`` is the sparse qualification. "
                 "No real capture data exists on this host, so real calibration is PENDING "
                 "and the full claim cannot be met (plan 14.4)."),
    }
    report["metrics"] = {
        "pipeline_ok": report["pipeline_ok"],
        "pipeline_stage": stage,
        "attempted": report["attempted"],
        "registered_frames": report["registered_frames"],
        "registered_fraction": report["registered_fraction"],
        "sparse_points": report["sparse_points"],
        "dense_points": report["dense_points"],
        "reprojection_error_px": error,
        "seconds": report["seconds"],
        "data_scope": report["data_scope"],
        "real_capture": report["real_capture"],
        "real_calibration": "PENDING",
        "dense_status": report.get("dense_status"),
        "failure_code": report.get("failure_code"),
        "failures": len(report.get("failures", [])),
        "pycolmap_version": report.get("capability_probe", {}).get("version"),
        "has_cuda": report.get("capability_probe", {}).get("has_cuda"),
        "has_patch_match_stereo": report.get("capability_probe", {}).get("has_patch_match_stereo"),
        "frames_per_fragment": report.get("subset", {}).get("frames_per_fragment"),
        "plan_frames_per_fragment": report.get("subset", {}).get("plan_frames_per_fragment"),
        "mother_source": [entry.get("source") for entry in report.get("mothers", [])],
    }
    if write_report:
        paths = []
        for root in _report_roots(store):
            paths.append(str(_write_json(root / REPORT_NAME, report)))
        # the run index stays inside the work directory tree (data/a12/reports/mvs/**)
        _write_json(workdir / "last_run.json",
                    {"schema": "synlab.mvs_subset.index.v1",
                     "reports": paths,
                     "workdir": report.get("workdir"),
                     "pipeline_ok": report.get("pipeline_ok"),
                     "dense_status": report.get("dense_status"),
                     "seconds": report["seconds"]})
        report["report_paths"] = paths
    return report


# --------------------------------------------------------------------------------------
# source-dependency audit (A24)
# --------------------------------------------------------------------------------------
def audit_source_dependency(store: Any = None, *, out_dir: Any = None, frames: int = 8,
                            repeats: int = 4, config: MvsConfig | None = None,
                            write_report: bool = True) -> dict[str, Any]:
    """Prove the reconstruction never consumes GT pose, depth or scale.

    The check is an experiment, not a code reading:

    * the same delivered images are handed to the same pycolmap chain repeatedly; the only
      difference is the *ground-truth pose table* offered at the canonical workdir path and
      through ``SYNLAB_GT_POSES`` (true poses vs poses rotated 37 deg and shifted ~670 mm).
      ``repeats`` identical-input runs measure the band that the numeric noise of the
      matcher already produces, and the corrupted run must stay inside it;
    * a negative control repeats the chain on horizontally flipped copies of the same
      images, so the equality test is shown to be sensitive to its input;
    * the COLMAP database's ``pose_priors`` table must stay empty (no EXIF/prior pose
      enters SfM), and no depth or scale file may exist among the pipeline inputs.
    """
    from .routes import resolve_target

    started = time.time()
    resolved_store = _resolve_store(store)
    cfg = config or MvsConfig(frames_per_fragment=int(frames), delivered_size=(640, 480),
                              render_pixels=640 * 480, max_image_size=640)
    cfg.frames_per_fragment = int(frames)
    # single-threaded stages + a fixed pycolmap RNG seed + a pinned initial image pair: the
    # runs must be comparable, otherwise the invariance test would measure scheduler noise.
    cfg.deterministic = True
    if cfg.init_pair is None:
        cfg.init_pair = (1, 2)
    workdir = Path(out_dir) if out_dir is not None else DEFAULT_WORK_ROOT / "source_audit"
    workdir.mkdir(parents=True, exist_ok=True)
    log_dir = workdir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    probe = _capability_probe()

    report: dict[str, Any] = {
        "schema": "synlab.source_dependency_audit.v1",
        "ok": False,
        "status": "FAIL",
        "metrics": {},
        "workdir": _rel(workdir),
        "checks": {},
        "argv_log": [],
        "evidence": ["synlab/observe/mvs_subset.py::audit_source_dependency",
                     _rel(workdir)],
    }
    checks: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    if not probe.get("import"):
        checks["pycolmap_available"] = {"ok": False, "detail": probe.get("error")}
        report["checks"] = checks
        report["metrics"] = {"error": probe.get("error")}
        report["failure_code"] = MVS_NOT_AVAILABLE
        return _finish_source_audit(report, resolved_store, write_report, started)

    picked = _select_mothers(resolved_store, 1, cfg)
    mother = picked[0]["mother"]
    target = resolve_target(mother.mesh, fragment_id=f"{picked[0]['mother_id']}_surface")
    profile = _profile("MID")
    frames_meta = _render_frames(target, profile, cfg, workdir, prefix="audit_v")
    checks["frame_source_kind"] = {
        "ok": all(str(item["source_kind"]).upper() == "SENSOR_SIM" for item in frames_meta),
        "detail": sorted({str(item["source_kind"]) for item in frames_meta}),
        "note": "rendered frames must be SENSOR_SIM (simulator), never a measured capture",
    }
    true_table = _write_frame_table(workdir, frames_meta, name="gt_poses_true.json")
    corrupt_table = _write_frame_table(workdir, frames_meta, name="gt_poses_corrupted.json",
                                       corrupted=True)
    deltas = []
    for true_frame, corrupt_frame in zip(true_table["frames"], corrupt_table["frames"]):
        T_true = np.asarray(true_frame["T_WC"], dtype=np.float64)
        T_bad = np.asarray(corrupt_frame["T_WC"], dtype=np.float64)
        cos = (np.trace(T_true[:3, :3].T @ T_bad[:3, :3]) - 1.0) / 2.0
        deltas.append(float(np.rad2deg(np.arccos(np.clip(cos, -1.0, 1.0)))))
    rotation_delta = float(np.max(deltas)) if deltas else 0.0
    translation_delta = float(np.max(np.linalg.norm(
        np.asarray([f["T_WC"] for f in true_table["frames"]])[:, :3, 3]
        - np.asarray([f["T_WC"] for f in corrupt_table["frames"]])[:, :3, 3], axis=1)))
    metrics["pose_table_translation_delta_mm"] = translation_delta
    metrics["pose_table_rotation_delta_deg"] = rotation_delta
    metrics["pose_table_offered_to_pipeline"] = [
        _rel(workdir / "gt_poses_true.json"), _rel(workdir / "gt_poses_corrupted.json"),
        "SYNLAB_GT_POSES",
    ]

    def _run(tag: str, active: Path, frames_for_run: list[dict[str, Any]],
             images_dir: Path) -> dict[str, Any]:
        """Run the sparse chain with ``active`` offered as the GT pose table."""
        local = workdir
        if images_dir != workdir / "images":
            local = images_dir.parent
            (local / "masks").mkdir(parents=True, exist_ok=True)
            for item in frames_for_run:
                shutil.copyfile(ROOT / item["mask_path"],
                                local / "masks" / f"{item['name']}.png")
        os.environ["SYNLAB_GT_POSES"] = str(active)
        try:
            return _sparse_pipeline(workdir=local, frames=frames_for_run, cfg=cfg,
                                    probe=probe, use_mask=False, tag=tag, log_dir=log_dir,
                                    start_index=len(report["argv_log"]) + 1)
        finally:
            os.environ.pop("SYNLAB_GT_POSES", None)

    run_true = _run("source_true", workdir / "gt_poses_true.json", frames_meta,
                    workdir / "images")
    report["argv_log"].extend(_strip_traces(run_true.get("stages", [])))
    # repeatability envelope: the *same* input and the same true table again (several times),
    # so the comparison band below is measured instead of assumed.
    repeat_runs = [run_true]
    for index in range(2, int(repeats) + 1):
        repeat_runs.append(_run(f"source_repeat{index}", workdir / "gt_poses_true.json",
                                frames_meta, workdir / "images"))
        report["argv_log"].extend(_strip_traces(repeat_runs[-1].get("stages", [])))
    run_corrupt = _run("source_corrupt", workdir / "gt_poses_corrupted.json", frames_meta,
                       workdir / "images")
    report["argv_log"].extend(_strip_traces(run_corrupt.get("stages", [])))

    # negative control: the identical chain on horizontally flipped images must differ, so
    # the equality test above is shown to be sensitive to its input.
    import cv2

    flipped_dir = workdir / "flipped"
    (flipped_dir / "images").mkdir(parents=True, exist_ok=True)
    control_frames: list[dict[str, Any]] = []
    for item in frames_meta:
        image = cv2.imread(str(ROOT / item["image_path"]))
        cv2.imwrite(str(flipped_dir / "images" / item["name"]),
                    np.ascontiguousarray(image[:, ::-1]))
        control_frame = dict(item)
        control_frame["image_path"] = _rel(flipped_dir / "images" / item["name"])
        control_frames.append(control_frame)
    control = _run("source_control_flipped", workdir / "gt_poses_corrupted.json",
                   control_frames, flipped_dir / "images")
    report["argv_log"].extend(_strip_traces(control.get("stages", [])))

    def _signature(attempt: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": bool(attempt.get("ok")),
            "registered_frames": int(attempt.get("registered_frames", 0)),
            "registered_names": sorted(attempt.get("registered_names", [])),
            "sparse_points": int(attempt.get("sparse_points", 0)),
            "mean_reprojection_error_px": float(attempt.get("mean_reprojection_error_px", 0.0)),
            "model_hash": attempt.get("model_hash"),
            "db_hash": (attempt.get("db") or {}).get("db_hash"),
            "keypoints_hash": (attempt.get("db") or {}).get("keypoints_hash"),
            "matches_hash": (attempt.get("db") or {}).get("matches_hash"),
            "keypoints": (attempt.get("db") or {}).get("keypoints"),
            "matches": (attempt.get("db") or {}).get("matches"),
            "matched_pairs": (attempt.get("db") or {}).get("matched_pairs"),
            "pose_priors": (attempt.get("db") or {}).get("pose_priors"),
        }

    sig_true, sig_corrupt = _signature(run_true), _signature(run_corrupt)
    sig_repeats = [_signature(attempt) for attempt in repeat_runs]
    sig_control = _signature(control)
    metrics["true_run"] = sig_true
    metrics["repeat_runs"] = sig_repeats
    metrics["corrupted_run"] = sig_corrupt
    metrics["control_run"] = sig_control

    # ---- measured tolerance band: spread of the identical-input runs
    envelope_points = max(abs(int(item["sparse_points"]) - int(sig_true["sparse_points"]))
                          for item in sig_repeats)
    envelope_reproj = max(abs(float(item["mean_reprojection_error_px"])
                              - float(sig_true["mean_reprojection_error_px"]))
                          for item in sig_repeats)
    envelope_sets = {tuple(item["registered_names"]) for item in sig_repeats}
    tolerance_points = max(2, int(np.ceil(0.01 * max(int(sig_true["sparse_points"]), 1))),
                           envelope_points + 2)
    tolerance_reproj = max(1.0e-3, 3.0 * envelope_reproj)
    points_delta = abs(int(sig_corrupt["sparse_points"]) - int(sig_true["sparse_points"]))
    reproj_delta = abs(float(sig_corrupt["mean_reprojection_error_px"])
                       - float(sig_true["mean_reprojection_error_px"]))
    keypoints_identical = bool(sig_true["keypoints_hash"]
                               and sig_true["keypoints_hash"] == sig_corrupt["keypoints_hash"])
    same_registered = bool(sig_true["registered_names"] == sig_corrupt["registered_names"])
    metrics["determinism_baseline"] = {
        "n_identical_runs": len(sig_repeats),
        "identical_model_hash": bool(len({item["model_hash"] for item in sig_repeats}) == 1),
        "identical_keypoints_hash": bool(len({item["keypoints_hash"] for item in sig_repeats}) == 1),
        "identical_matches_hash": bool(len({item["matches_hash"] for item in sig_repeats}) == 1),
        "identical_registered_sets": bool(len(envelope_sets) == 1),
        "points_spread": [int(item["sparse_points"]) for item in sig_repeats],
        "reprojection_spread_px": [round(float(item["mean_reprojection_error_px"]), 6)
                                   for item in sig_repeats],
        "note": ("identical input repeated with single-thread stages, a fixed pycolmap RNG "
                 "seed and a pinned initial pair.  Feature extraction is bit-repeatable; the "
                 "matcher's RANSAC verification is not, so the reconstruction band is "
                 "measured rather than assumed"),
    }
    identical = bool(keypoints_identical and same_registered
                     and points_delta <= tolerance_points
                     and reproj_delta <= tolerance_reproj)
    metrics["invariance_tolerance"] = {"points": tolerance_points,
                                       "reprojection_px": tolerance_reproj,
                                       "envelope_points": envelope_points,
                                       "envelope_reprojection_px": envelope_reproj,
                                       "corrupted_point_delta": points_delta,
                                       "corrupted_reprojection_delta_px": reproj_delta}
    checks["gt_pose_invariance"] = {
        "ok": identical,
        "detail": {"true": sig_true, "repeats": sig_repeats, "corrupted": sig_corrupt,
                   "keypoints_hash_identical": keypoints_identical,
                   "same_registered_set": same_registered,
                   "point_delta": points_delta, "reprojection_delta_px": reproj_delta,
                   "tolerance": metrics["invariance_tolerance"], "identical": identical},
        "note": ("a GT pose table corrupted by "
                 f"{metrics['pose_table_translation_delta_mm']:.0f} mm / "
                 f"{metrics['pose_table_rotation_delta_deg']:.0f} deg was offered at the "
                 "canonical workdir path (gt_poses_corrupted.json) and through the "
                 "SYNLAB_GT_POSES environment variable; the extracted features are "
                 "bit-identical and the reconstruction stays inside the band measured by "
                 f"{len(sig_repeats)} identical-input runs, so no GT pose enters SfM"),
    }
    control_points_ratio = (float(sig_control["sparse_points"])
                            / max(float(sig_true["sparse_points"]), 1.0))
    control_reconstruction_differs = bool(
        sig_control.get("model_hash") != sig_true.get("model_hash")
        or sig_control["registered_names"] != sig_true["registered_names"]
        or sig_control["sparse_points"] != sig_true["sparse_points"])
    control_differs = bool(sig_control.get("keypoints_hash")
                           and sig_control["keypoints_hash"] != sig_true["keypoints_hash"]
                           and control_reconstruction_differs)
    checks["control_is_sensitive"] = {
        "ok": control_differs,
        "detail": {"control": sig_control, "reference": sig_true,
                   "sparse_points_ratio": control_points_ratio,
                   "keypoints_hash_identical": bool(sig_control["keypoints_hash"]
                                                    == sig_true["keypoints_hash"]),
                   "reconstruction_differs": control_reconstruction_differs,
                   "control_input": "horizontally flipped copies of the same frames"},
        "note": ("negative control: the identical chain on mirrored images extracts "
                 "different features (different keypoint/descriptor hash) and reconstructs a "
                 "different model, so the invariance test above is not vacuous"),
    }
    checks["pose_priors_empty"] = {
        "ok": bool(sig_true["pose_priors"] == 0 and sig_corrupt["pose_priors"] == 0),
        "detail": {"true_db": sig_true["pose_priors"], "corrupted_db": sig_corrupt["pose_priors"]},
        "note": "the COLMAP database must contain no pose prior rows",
    }
    inputs = sorted({Path(item["image_path"]).suffix.lower() for item in frames_meta}
                    | {".png"})
    forbidden = []
    for item in frames_meta:
        image_path = ROOT / item["image_path"]
        for probe_path in (image_path.parent, workdir):
            for pattern in ("*.npy", "*.npz", "*.exr", "*.pfm", "depth*", "scale*", "gt_*"):
                forbidden.extend(str(path.relative_to(workdir))
                                 for path in probe_path.glob(pattern)
                                 if path.is_file() and path.suffix.lower() not in (".json",))
    forbidden = sorted(set(forbidden))
    checks["no_depth_or_scale_input"] = {
        "ok": not forbidden,
        "detail": {"image_suffixes": inputs, "forbidden_artefacts": forbidden},
        "note": "the SfM input directory contains images and masks only",
    }
    metrics["sfm_scale_source"] = {
        "kind": "NONE",
        "note": ("COLMAP SfM is scale-free; no scale target is supplied, so the "
                 "reconstruction stays in an arbitrary unit and no mm claim is made"),
        "scale_target_radius_mm": None,
    }
    report["checks"] = checks
    report["metrics"] = metrics
    report["config"] = asdict(cfg)
    ok = all(bool(value["ok"]) for value in checks.values())
    report["ok"] = ok
    report["status"] = "PASS" if ok else "FAIL"
    return _finish_source_audit(report, resolved_store, write_report, started)


def _finish_source_audit(report: dict[str, Any], store: Any, write_report: bool,
                         started: float) -> dict[str, Any]:
    report.setdefault("metrics", {})
    report["metrics"]["seconds"] = round(time.time() - started, 3)
    report["status"] = "PASS" if report.get("ok") else "FAIL"
    report.setdefault("checks", {})
    report["metrics"]["checks"] = {name: bool(value.get("ok"))
                                   for name, value in report["checks"].items()}
    if write_report:
        paths = [str(_write_json(root / SOURCE_AUDIT_NAME, report))
                 for root in _report_roots(store)]
        report["report_paths"] = paths
    return report


__all__ = ["run_mvs_subset", "audit_source_dependency", "MvsConfig", "REPORT_NAME",
           "SOURCE_AUDIT_NAME", "DEFAULT_WORK_ROOT"]
