"""Blender render backend: binary probe, subprocess worker call and result assembly.

Why a subprocess and not ``import bpy``
--------------------------------------
``bpy`` has no wheel for Windows + CPython 3.12, so Blender cannot be imported into this
venv.  A **portable Blender 5.2.2 LTS** binary is driven as an external process with a
frozen JSON contract (``blender_scripts/render_worker.py``) and the raw pass files it
writes are assembled here into :class:`synlab.schemas.runtime.RenderOutput`.

Honesty rules implemented here
------------------------------
* A missing binary, a non-zero worker exit or an unreadable manifest raises a structured
  :class:`~synlab.errors.SynLabError` (``ENV_CAPABILITY_MISSING`` / ``OPERATOR_NOT_REALIZED``)
  carrying the full argv, the return code and the stderr tail.  The software rasteriser is
  **never** silently substituted while the result is labelled Blender.
* ``SENSOR_UPPER_BOUND``-style claims are not made from a wrapper: the caller gets the
  measured channels plus the worker manifest (samples actually used, Blender version,
  output hashes, self-check residuals).
* A camera model Blender cannot represent (OpenCV distortion with non-zero coefficients)
  is refused by default instead of being silently dropped; ``distortion_policy="ignore"``
  is available and records the ignored coefficients and their maximum pixel effect.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..roles import SOURCE_SENSOR_SIM
from ..schemas.runtime import RenderOutput, ViewFrame
from .render import (
    BACKEND_BLENDER,
    BACKEND_BLENDER_EEVEE,
    BACKEND_SOFTWARE,
    LightSpec,
    RenderSpec,
    Scene,
    circle_of_confusion_px,
)

CONFIG_SCHEMA = "rws.blender.render.config/1"
RESULT_PREFIX = "RWS_WORKER_RESULT "
ERROR_PREFIX = "RWS_WORKER_ERROR "

#: Repository root (…/relicweave-synlab) and the default scratch/output root.
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = REPO_ROOT / "blender_scripts" / "render_worker.py"
SELFTEST_PATH = REPO_ROOT / "blender_scripts" / "selftest.py"
DEFAULT_WORK_ROOT = REPO_ROOT / "data" / "a12" / "reports" / "blender" / "_work"

#: Search roots for the portable build.  MSIX/WindowsApps installs are deliberately not
#: searched: the packaged store build is not executable by path (plan 2.2 / doctor note).
PORTABLE_SEARCH_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "third_party",
    REPO_ROOT.parent / "third_party",
)


# --------------------------------------------------------------------------------------
# binary discovery and probe
# --------------------------------------------------------------------------------------
def _env_blender_bin() -> str | None:
    value = os.environ.get("BLENDER_BIN")
    return value if value and Path(value).is_file() else None


def _user_env_blender_bin() -> str | None:
    """Read ``BLENDER_BIN`` from the persisted Windows environment (new-process visibility).

    A user-level variable set after the parent process started is not in this process's
    environment block; the registry value is the honest way to see it.
    """
    if sys.platform != "win32":  # pragma: no cover - Windows-only path
        return None
    try:
        import winreg
    except Exception:  # noqa: BLE001 - non-Windows
        return None
    locations = (
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    )
    for root, sub in locations:
        try:
            with winreg.OpenKey(root, sub) as key:
                value, _kind = winreg.QueryValueEx(key, "BLENDER_BIN")
        except OSError:
            continue
        if value and Path(str(value)).is_file():
            return str(value)
    return None


def _portable_candidates() -> list[str]:
    out: list[str] = []
    for root in PORTABLE_SEARCH_ROOTS:
        try:
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if not child.is_dir() or "blender" not in child.name.lower():
                    continue
                for exe in ("blender.exe", "blender"):
                    candidate = child / exe
                    if candidate.is_file():
                        out.append(str(candidate))
        except OSError:
            continue
    return out


def find_blender_binary(explicit: str | None = None) -> str | None:
    """Locate a usable Blender executable; ``None`` when this host has none."""
    if explicit:
        return str(explicit) if Path(str(explicit)).is_file() else None
    for candidate in (_env_blender_bin(), shutil.which("blender"), _user_env_blender_bin()):
        if candidate:
            return str(candidate)
    portable = _portable_candidates()
    return portable[-1] if portable else None


_SELFTEST_CACHE: dict[str, dict[str, Any]] = {}


def _tail(text: str, n: int = 2000) -> str:
    text = (text or "").strip()
    return text[-n:]


def selftest(binary: str | None = None, *, refresh: bool = False,
             timeout_s: float = 300.0) -> dict[str, Any]:
    """Run ``blender_scripts/selftest.py`` in background mode and report what it measured."""
    exe = find_blender_binary(binary)
    if exe is None:
        return {
            "capability": "blender_render",
            "status": "MISSING",
            "binary": None,
            "detail": "no Blender binary found (BLENDER_BIN / PATH / persisted user env / "
                      "project third_party portable build)",
            "replacement": BACKEND_SOFTWARE,
            "replacement_class": "CUSTOM_GAP",
            "argv": None,
        }
    if not refresh and exe in _SELFTEST_CACHE:
        return dict(_SELFTEST_CACHE[exe])
    argv = [exe, "--background", "--factory-startup", "--python-exit-code", "1",
            "--python", str(SELFTEST_PATH)]
    started = time.perf_counter()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s,
                              check=False, cwd=str(REPO_ROOT))
    except Exception as exc:  # noqa: BLE001 - any failure is a capability failure
        report = {
            "capability": "blender_render", "status": "FAIL", "binary": exe,
            "argv": argv, "error": f"{type(exc).__name__}: {exc}",
            "seconds": time.perf_counter() - started,
        }
        _SELFTEST_CACHE[exe] = report
        return dict(report)
    parsed: dict[str, Any] = {}
    for line in (proc.stdout or "").splitlines():
        if line.startswith("RWS_SELFTEST "):
            try:
                parsed = json.loads(line[len("RWS_SELFTEST "):])
            except json.JSONDecodeError:
                parsed = {}
    status = "OK" if (proc.returncode == 0 and parsed.get("status") == "OK") else "FAIL"
    report = {
        "capability": "blender_render",
        "status": status,
        "binary": exe,
        "argv": argv,
        "returncode": int(proc.returncode),
        "seconds": time.perf_counter() - started,
        "version": parsed.get("version"),
        "python": parsed.get("python"),
        "cycles_engine": parsed.get("cycles_engine"),
        "cycles_samples_default": parsed.get("cycles_samples_default"),
        "denoiser": parsed.get("denoiser"),
        "replacement": None if status == "OK" else BACKEND_SOFTWARE,
        "replacement_class": None if status == "OK" else "CUSTOM_GAP",
        "stderr_tail": _tail(proc.stderr),
        "stdout_tail": _tail(proc.stdout, 600),
    }
    if status == "OK":
        report["detail"] = (
            f"portable Blender {report['version']} driven as a subprocess worker; bpy is "
            f"still not importable into this venv")
    else:
        report["detail"] = "the Blender binary exists but the background self-test failed"
        report["error"] = f"returncode {proc.returncode}"
    _SELFTEST_CACHE[exe] = report
    return dict(report)


def capability_probe(*, refresh: bool = False) -> dict[str, Any]:
    """Capability record for plan 30.1 (``backend:blender_render``)."""
    return selftest(refresh=refresh)


def probe_is_ok(report: dict[str, Any] | None = None) -> bool:
    return bool((report or selftest()).get("status") == "OK")


# --------------------------------------------------------------------------------------
# request configuration
# --------------------------------------------------------------------------------------
@dataclass
class BlenderBackendConfig:
    """Frozen knobs of one Blender worker call (every one is recorded in ``meta``)."""

    #: 32/64 are the plan's low-cost tiers (plan 13.2); 32 is the QA-frozen default here.
    samples: int = 32
    filter_width: float = 1.5
    denoise: bool = False
    denoiser: str = "OPENIMAGEDENOISE"
    max_bounces: int = 4
    device: str = "CPU"
    seed: int = 20261001
    #: exact geometry pass: one sample per pixel inside a 0.01 px filter (no interpolation)
    geometry_samples: int = 1
    geometry_filter_width: float = 0.01
    geometry_max_bounces: int = 0
    #: anti-aliased geometry pass used only as AA evidence / mixing detection
    aa_geometry_samples: int | None = None
    #: camera/geometry self-checks
    camera_uv_tol_px: float = 0.1
    face_order_tol_mm: float = 1e-2
    raycast_samples: int = 1500
    raycast_depth_tol_mm: float = 0.5
    #: uncertain-mask inputs
    coc_px_threshold: float = 0.75
    f_number: float = 4.0
    motion_amplitude_px: float = 0.0
    depth_edge_tol_mm: float = 0.25
    #: "error" refuses frames whose OpenCV distortion Blender cannot represent
    distortion_policy: str = "error"
    depth_pack_range_mm: float = 0.0
    #: process handling
    work_root: str | None = None
    workdir: str | None = None
    run_label: str = "render"
    keep_workdir: bool = True
    timeout_s: float = 3600.0
    previews: bool = True
    #: extra analytic objects (e.g. an occluder/support plate) placed in Blender world mm
    extra_objects: tuple[dict[str, Any], ...] = ()
    linearity_probes: tuple[dict[str, Any], ...] = ()

    def as_config(self, **overrides: Any) -> dict[str, Any]:
        data = dict(self.__dict__)
        data.update(overrides)
        return data


# --------------------------------------------------------------------------------------
# scene export
# --------------------------------------------------------------------------------------
def _subset_mesh(scene: Scene, face_mask: np.ndarray, name: str):
    """Reindexed trimesh for a face subset (vertex array kept identical to the scene)."""
    import trimesh

    faces = np.asarray(scene.faces, dtype=np.int64)[face_mask]
    used = np.unique(faces)
    remap = np.full(int(scene.vertices.shape[0]), -1, dtype=np.int64)
    remap[used] = np.arange(used.size, dtype=np.int64)
    verts = np.asarray(scene.vertices, dtype=np.float64)[used]
    mesh = trimesh.Trimesh(vertices=verts, faces=remap[faces], process=False)
    return mesh, {
        "name": name,
        "faces": remap[faces].astype(np.int32),
        "face_centroid_mm": verts[remap[faces]].mean(axis=1),
        "face_id": np.asarray(scene.face_id, dtype=np.int32)[face_mask],
        "surface_tag": np.asarray(scene.surface_tag, dtype=np.int16)[face_mask],
        "albedo": np.asarray(scene.material.albedo, dtype=np.float32)[face_mask],
        "roughness": np.asarray(scene.material.roughness, dtype=np.float32)[face_mask],
    }


def _export_object(scene: Scene, face_mask: np.ndarray, name: str, pass_index: int,
                   is_target: bool, workdir: Path, pose: np.ndarray | None,
                   axis: tuple[str, str]) -> dict[str, Any]:
    mesh, labels = _subset_mesh(scene, face_mask, name)
    ply = workdir / f"{name}.ply"
    with open(ply, "wb") as fh:
        fh.write(mesh.export(file_type="ply"))
    npz = workdir / f"{name}_labels.npz"
    np.savez(npz, **labels)
    return {
        "name": name,
        "mesh": str(ply),
        "mesh_format": "ply",
        "axis": {"forward": axis[0], "up": axis[1]},
        "labels": str(npz),
        "pass_index": int(pass_index),
        "is_target": bool(is_target),
        "object_pose_T_WO": None if pose is None else np.asarray(pose, dtype=np.float64).tolist(),
    }


def build_config(scene: Scene, frame: ViewFrame, *, light: LightSpec, spec: RenderSpec,
                 config: BlenderBackendConfig, workdir: Path,
                 object_pose: np.ndarray | None, focus_distance_mm: float) -> dict[str, Any]:
    """Translate the project's scene/frame into the worker's JSON contract."""
    dist = None if frame.dist is None else np.asarray(frame.dist, dtype=np.float64).ravel()
    if dist is not None and dist.size and float(np.abs(dist).max()) > 0.0:
        if config.distortion_policy != "ignore":
            raise SynLabError(
                ErrorCode.ENV_CAPABILITY_MISSING,
                "the Blender backend renders an ideal pinhole camera and cannot represent "
                "the OpenCV distortion coefficients of this frame "
                f"({dist.tolist()}); render a PINHOLE frame or use the software rasteriser. "
                "Set distortion_policy='ignore' to render anyway and record the ignored "
                "coefficients (the pixel error is then unreported-but-declared).",
                stage="observe.blender.build_config",
                measurements={"dist": dist.tolist(), "frame_model": frame.camera_model},
            )
    width, height = int(frame.image_size[0]), int(frame.image_size[1])
    K = np.asarray(frame.K, dtype=np.float64)
    if abs(K[0, 1]) > 1e-12 or abs(K[1, 0]) > 1e-12:
        raise SynLabError(ErrorCode.ENV_CAPABILITY_MISSING,
                          "the Blender backend needs an axis-aligned K (no skew)",
                          stage="observe.blender.build_config", measurements={"K": K.tolist()})

    is_target = np.asarray(scene.is_target, dtype=np.uint8).astype(bool)
    objects: list[dict[str, Any]] = []
    axis = ("NEGATIVE_Y", "Z")
    if is_target.any():
        objects.append(_export_object(scene, is_target, "target", 1, True, workdir,
                                      object_pose, axis))
    if (~is_target).any():
        objects.append(_export_object(scene, ~is_target, "support", 2, False, workdir,
                                      None, axis))
    for extra in config.extra_objects:
        objects.append(dict(extra))

    depth_range = float(config.depth_pack_range_mm) or float(spec.far_mm if spec.far_mm
                                                             < 1e6 else 1.0e5)
    aa_samples = int(config.aa_geometry_samples or config.samples)
    return {
        "schema": CONFIG_SCHEMA,
        "view_id": frame.view_id,
        "output_dir": str(workdir),
        "resolution": [width, height],
        "background_linear": list(spec.background_linear),
        "depth_pack_range_mm": depth_range,
        "camera": {
            "model": frame.camera_model or "PINHOLE",
            "K": K.tolist(),
            "T_WC": np.asarray(frame.T_WC, dtype=np.float64).tolist(),
            "dist": None if dist is None else dist.tolist(),
            "image_size": [width, height],
            "convention": "opencv_pixel_center_0_0",
            "near_mm": float(spec.near_mm),
            "far_mm": float(spec.far_mm),
            "focus_distance_mm": float(focus_distance_mm),
        },
        "light": {
            "direction": np.asarray(light.direction, dtype=np.float64).ravel().tolist(),
            "color": np.asarray(light.color, dtype=np.float64).ravel().tolist(),
            "ambient": np.asarray(light.ambient, dtype=np.float64).ravel().tolist(),
        },
        "render": {
            "samples": int(config.samples),
            "filter_width": float(config.filter_width),
            "denoise": bool(config.denoise),
            "denoiser": config.denoiser,
            "max_bounces": int(config.max_bounces),
            "device": config.device,
            "seed": int(config.seed),
            "geometry_samples": int(config.geometry_samples),
            "geometry_filter_width": float(config.geometry_filter_width),
            "geometry_max_bounces": int(config.geometry_max_bounces),
            "aa_geometry_samples": aa_samples,
        },
        "uncertain": {
            "coc_px_threshold": float(config.coc_px_threshold),
            "f_number": float(config.f_number),
            "focus_distance_mm": float(focus_distance_mm),
            "motion_amplitude_px": float(config.motion_amplitude_px),
            "depth_edge_tol_mm": float(config.depth_edge_tol_mm),
        },
        "checks": {
            "camera_uv_tol_px": float(config.camera_uv_tol_px),
            "face_order_tol_mm": float(config.face_order_tol_mm),
            "raycast_samples": int(config.raycast_samples),
            "raycast_depth_tol_mm": float(config.raycast_depth_tol_mm),
            "depth_pack_range_mm": depth_range,
        },
        "objects": objects,
        "linearity_probes": [dict(p) for p in config.linearity_probes],
        "write": {"previews": bool(config.previews), "npy": True, "exr": True},
        "provenance": {
            "source_kind": SOURCE_SENSOR_SIM,
            "albedo_source_kind": scene.material.source_kind,
            "requested_by": "synlab.observe.blender.render_view_blender",
        },
    }


# --------------------------------------------------------------------------------------
# worker call
# --------------------------------------------------------------------------------------
def _structured_worker_failure(proc: subprocess.CompletedProcess, argv: list[str],
                               config_path: Path, elapsed: float) -> SynLabError:
    """Turn a non-zero worker exit into a structured error that keeps the evidence."""
    payload: dict[str, Any] = {}
    for line in (proc.stderr or "").splitlines():
        if line.startswith(ERROR_PREFIX):
            try:
                payload = json.loads(line[len(ERROR_PREFIX):])
            except json.JSONDecodeError:
                payload = {}
    code = str(payload.get("error_code") or "")
    error_code = ErrorCode.OPERATOR_NOT_REALIZED
    if code in ("USAGE", "SCHEMA_INVALID", "MESH_IMPORT_FAILED"):
        error_code = ErrorCode.SCHEMA_INVALID
    if code in ("PASS_UNAVAILABLE", "EXR_READBACK_FAILED"):
        error_code = ErrorCode.ENV_CAPABILITY_MISSING
    message = payload.get("message") or (
        f"Blender worker exited with code {proc.returncode} without a structured error")
    return SynLabError(
        error_code,
        f"Blender worker failed: {message}",
        stage="observe.blender.render_view_blender",
        measurements={"returncode": int(proc.returncode),
                      "worker_error_code": code or None,
                      "elapsed_seconds": round(elapsed, 3)},
        evidence_refs=[json.dumps({"argv": argv, "config": str(config_path)}),
                       _tail(proc.stderr, 1200), _tail(proc.stdout, 600)],
    )


def run_worker(config: dict[str, Any], *, binary: str | None = None,
               timeout_s: float = 3600.0, workdir: Path | None = None
               ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the Blender worker once; returns ``(manifest, run_record)`` or raises."""
    exe = find_blender_binary(binary)
    if exe is None:
        probe = selftest()
        raise SynLabError(
            ErrorCode.ENV_CAPABILITY_MISSING,
            "no Blender binary is available for the 'blender' render backend; install the "
            "portable build and set BLENDER_BIN (the software rasteriser stays available "
            "as the declared replacement)",
            stage="observe.blender.run_worker",
            evidence_refs=[json.dumps(probe)],
        )
    out_dir = Path(config["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    config_path = Path(workdir or out_dir) / "render_config.json"
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
    argv = [exe, "--background", "--factory-startup", "--python-exit-code", "3",
            "--python", str(WORKER_PATH), "--", str(config_path)]
    started = time.perf_counter()
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s,
                          check=False, cwd=str(REPO_ROOT))
    elapsed = time.perf_counter() - started
    record = {"argv": argv, "returncode": int(proc.returncode), "seconds": elapsed,
              "config_path": str(config_path), "binary": exe}
    if proc.returncode != 0:
        raise _structured_worker_failure(proc, argv, config_path, elapsed)
    result_line = next((ln for ln in (proc.stdout or "").splitlines()
                        if ln.startswith(RESULT_PREFIX)), None)
    if result_line is None:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                          "the Blender worker exited 0 without a result line",
                          stage="observe.blender.run_worker",
                          evidence_refs=[_tail(proc.stdout, 800), _tail(proc.stderr, 800)])
    record["result"] = json.loads(result_line[len(RESULT_PREFIX):])
    manifest_path = Path(record["result"]["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record["manifest_path"] = str(manifest_path)
    return manifest, record


# --------------------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------------------
def _load(out_dir: Path, name: str) -> np.ndarray:
    path = out_dir / name
    if not path.is_file():
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                          f"the Blender worker did not write {name}",
                          stage="observe.blender.assemble",
                          evidence_refs=[str(out_dir)])
    return np.load(path)


def assemble_render_output(manifest: dict[str, Any], *, frame: ViewFrame,
                           config: BlenderBackendConfig, backend: str) -> RenderOutput:
    """Assemble the worker's channels into the frozen :class:`RenderOutput` contract."""
    out_dir = Path(manifest["output_dir"])
    rgb = np.asarray(_load(out_dir, "rgb_linear.npy"), dtype=np.float32)
    depth = np.asarray(_load(out_dir, "depth_z_mm.npy"), dtype=np.float32)
    depth_aa = np.asarray(_load(out_dir, "depth_z_aa_mm.npy"), dtype=np.float32)
    id_map = np.asarray(_load(out_dir, "id_face.npy"), dtype=np.int32)
    tag = np.asarray(_load(out_dir, "surface_tag.npy"), dtype=np.int16)
    obj_index = np.asarray(_load(out_dir, "object_index.npy"), dtype=np.int32)
    visibility = np.asarray(_load(out_dir, "visibility.npy"), dtype=np.uint8)
    target_visibility = np.asarray(_load(out_dir, "target_visibility.npy"), dtype=np.uint8)
    occlusion = np.asarray(_load(out_dir, "occlusion.npy"), dtype=np.uint8)
    uncertain = np.asarray(_load(out_dir, "uncertain_mask.npy"), dtype=bool)
    width, height = int(frame.image_size[0]), int(frame.image_size[1])
    for name, arr in (("rgb_linear", rgb), ("depth_z", depth), ("id_face", id_map),
                      ("surface_tag", tag), ("visibility", visibility),
                      ("uncertain_mask", uncertain)):
        if arr.shape[:2] != (height, width):
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"worker channel {name} has shape {arr.shape}, expected "
                              f"({height}, {width})",
                              stage="observe.blender.assemble")
    stat = dict(manifest.get("statistics", {}))
    checks = dict(manifest.get("checks", {}))
    meta: dict[str, Any] = {
        "backend": backend,
        "backend_class": "ADAPTER",
        "blender_version": manifest["blender"]["version"],
        "blender_binary": manifest["blender"]["binary"],
        "blender_python": manifest["blender"]["python"],
        "blender_build_hash": manifest["blender"]["build_hash"],
        "manifest_path": manifest.get("manifest_path"),
        "output_dir": str(out_dir),
        "argv": manifest["argv"],
        "worker_argv": [manifest["blender"]["binary"], "--background", "--factory-startup",
                        "--python-exit-code", "3", "--python",
                        "blender_scripts/render_worker.py", "--", "<config.json>"],
        "samples_requested": int(manifest["render"]["samples_requested"]),
        "samples_used": int(manifest["render"]["samples_used"]),
        "filter_width": float(manifest["render"]["filter_width"]),
        "denoise": bool(manifest["render"]["denoise"]),
        "denoise_applies_to": manifest["render"]["denoise_applies_to"],
        "max_bounces": int(manifest["render"]["max_bounces"]),
        "cycles_device": manifest["blender"]["cycles_device_setting"],
        "engine": manifest["render"]["engine"],
        "seed": int(manifest["render"]["seed"]),
        "elapsed_seconds": float(manifest["elapsed_seconds"]),
        "render_seconds": {r["tag"]: r["seconds"] for r in manifest["renders"]},
        "depth_semantics": "camera_frame_z_mm",
        "depth_source_pass": "Cycles Depth (Z), exact geometry pass",
        "depth_z_aa_available": True,
        "id_map_semantics": ("integer per-face label from a Shader AOV fed by a face-domain "
                             "FLOAT attribute; -1 = background; never interpolated"),
        "surface_tag_semantics": (f"Shader AOV fed by a face-domain FLOAT attribute; the "
                                  f"Cycles Material Index pass returns a constant in 5.2.2 "
                                  f"(measured) and is only an audit channel"),
        "visibility_semantics": ("1 = the primary hit is scene geometry and the pixel is not "
                                 "mixed (same meaning as the software rasteriser)"),
        "target_visibility_semantics": ("1 = the primary hit is the target object and the "
                                        "pixel is not mixed; exposed as the extra "
                                        "``target_visibility`` attribute"),
        "object_index_semantics": "Cycles Object Index pass (object pass_index)",
        "occlusion_semantics": "target visible with non-target objects hidden but not in the "
                               "full scene",
        "uncertain_semantics": ("anti-aliased geometry mixing | depth edge inside the pixel | "
                                "defocus CoC > threshold; motion boundary is an imaging-chain "
                                "stage (plan 13.3) and only dilates the mixed mask when a "
                                "motion amplitude is requested"),
        "mm_per_pixel": float(frame.working_distance_mm / float(frame.K[0, 0])),
        "object_pose_T_WO": (None if config.as_config().get("object_pose") is None
                             else np.asarray(config.as_config()["object_pose"]).tolist()),
        "focus_distance_mm": float(manifest["render"].get("focus_distance_mm")
                                   or manifest["camera"]["selfcheck"].get("focus")
                                   or 0.0),
        "coc_threshold_px": float(checks.get("aa_pass_fractional", {}).get("coc_threshold_px",
                                                                          config.coc_px_threshold)),
        "surface_visible_fraction": float(stat.get("visible_fraction", 0.0)),
        "target_visible_fraction": float(stat.get("target_visible_fraction", 0.0)),
        "uncertain_fraction": float(stat.get("uncertain_fraction", 0.0)),
        "occluded_fraction": float(stat.get("occluded_fraction", 0.0)),
        "id_classes_visible": int(stat.get("id_classes_visible", 0)),
        "albedo_source_kind": manifest.get("provenance", {}).get(
            "albedo_source_kind", SOURCE_SENSOR_SIM),
        "background_linear": list(manifest["light"]["background_linear"]),
        "bg_linear_present": True,
        "light_direction": list(manifest["light"]["direction_travel"]),
        "light_color": list(manifest["light"].get("sun_color_normalised", [])),
        "ambient": list(manifest["light"].get("ambient_linear", [])),
        "light_model": manifest["light"]["world_model"],
        "sun_irradiance": manifest["light"].get("sun_energy_irradiance"),
        "checks": checks,
        "rgb_background_linearity": checks.get("rgb_background_linearity"),
        "outputs": manifest["outputs"],
        "depth_z_aa_std_mm": float(np.nanstd(
            np.abs(depth_aa.astype(np.float64) - depth.astype(np.float64)))) if
        np.isfinite(depth).any() else 0.0,
        "backend_report_ref": "docs/a12/blender_backend.md",
        "not_equivalent_note": ("Blender pass anti-aliasing for Z/Object Index/Material Index "
                                "differs from the RGB pass; the delivered integer channels come "
                                "from a one-sample exact geometry pass, and the anti-aliased "
                                "behaviour is kept in depth_z_aa_mm and the checks block"),
    }
    if config.distortion_policy == "ignore":
        meta["distortion_ignored"] = True
        meta["distortion_note"] = ("frame distortion coefficients were dropped; the render is "
                                  "an ideal pinhole (declared, not silently corrected)")
    result = RenderOutput(
        rgb_linear=rgb[:, :, :3].astype(np.float32),
        depth_z=depth.astype(np.float32),
        id_map=id_map.astype(np.int32),
        surface_tag=tag.astype(np.int16),
        visibility=visibility.astype(np.uint8),
        uncertain_mask=uncertain.astype(bool),
        backend=backend,
        meta=meta,
    )
    #: Channels the Blender backend measures but :class:`RenderOutput` has no field for.
    #: They are attached as extra attributes (the dataclass is not slotted) and are also
    #: written to the work directory as ``.npy`` files; the frozen schema is not changed here.
    result.occlusion = occlusion.astype(np.uint8)
    result.target_visibility = target_visibility.astype(np.uint8)
    result.object_index = obj_index.astype(np.int32)
    result.depth_z_aa = depth_aa.astype(np.float32)
    meta["extra_channel_attributes"] = ["occlusion", "target_visibility", "object_index",
                                        "depth_z_aa"]
    return result


def _default_workdir(config: BlenderBackendConfig, view_id: str) -> Path:
    if config.workdir:
        return Path(config.workdir)
    root = Path(config.work_root) if config.work_root else DEFAULT_WORK_ROOT
    stamp = time.strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha256(f"{view_id}|{stamp}|{os.getpid()}".encode()).hexdigest()[:8]
    return root / f"{config.run_label}_{view_id}_{stamp}_{digest}"


def render_view_blender(scene: Scene, frame: ViewFrame, *, light: LightSpec,
                        spec: RenderSpec | None = None,
                        object_pose: np.ndarray | None = None,
                        focus_distance_mm: float | None = None,
                        config: BlenderBackendConfig | None = None,
                        backend: str = BACKEND_BLENDER) -> RenderOutput:
    """Render one view with the real Blender worker and assemble a :class:`RenderOutput`."""
    config = config or BlenderBackendConfig()
    spec = spec or RenderSpec()
    if backend not in (BACKEND_BLENDER, BACKEND_BLENDER_EEVEE):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"render_view_blender got backend {backend!r}",
                          stage="observe.blender.render_view_blender")
    if backend == BACKEND_BLENDER_EEVEE:
        raise SynLabError(
            ErrorCode.ENV_CAPABILITY_MISSING,
            "the EEVEE backend is not wired: the worker renders Cycles passes (Z / Object "
            "Index / Material Index / Shader AOV) and EEVEE Next does not provide the same "
            "pass set in 5.2; use backend='BLENDER_CYCLES' or the software rasteriser",
            stage="observe.blender.render_view_blender")
    focus = float(frame.working_distance_mm if focus_distance_mm is None
                  else focus_distance_mm)
    workdir = _default_workdir(config, frame.view_id)
    workdir.mkdir(parents=True, exist_ok=True)
    overrides = config.as_config()
    overrides["object_pose"] = None if object_pose is None else np.asarray(object_pose).tolist()
    cfg = build_config(scene, frame, light=light, spec=spec, config=config,
                       workdir=workdir, object_pose=object_pose, focus_distance_mm=focus)
    manifest, record = run_worker(cfg, timeout_s=config.timeout_s, workdir=workdir)
    result = assemble_render_output(manifest, frame=frame, config=config, backend=backend)
    result.meta["manifest_path"] = record.get("manifest_path")
    result.meta["worker_returncode"] = record.get("returncode")
    result.meta["worker_wall_seconds"] = record.get("seconds")
    if not config.keep_workdir:  # pragma: no cover - opt-in cleanup
        shutil.rmtree(workdir, ignore_errors=True)
    return result


__all__ = [
    "BACKEND_BLENDER", "BACKEND_SOFTWARE", "BlenderBackendConfig", "CONFIG_SCHEMA",
    "DEFAULT_WORK_ROOT", "REPO_ROOT", "ERROR_PREFIX", "RESULT_PREFIX", "SELFTEST_PATH",
    "WORKER_PATH", "assemble_render_output", "build_config", "capability_probe",
    "circle_of_confusion_px", "find_blender_binary", "probe_is_ok", "render_view_blender",
    "run_worker", "selftest",
]
