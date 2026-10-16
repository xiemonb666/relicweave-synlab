"""Realistic-library runner: capture-style observation on real lineages (A12 realism work).

Two modes, both writing into the *new* library ``data/a12_realistic`` and reporting to
``data/a12/reports/``.  Nothing here writes to ``data/a12`` except ``data/a12/reports/``.

``--mode run``    (heavy, one process per invocation)
    Builds the selected mothers through the **frozen pipeline**
    (``synlab.pipeline.build_one_mother``: mother -> fracture -> physical -> observe ->
    features/labels/provenance -> store) with the observation request taken from
    ``configs/a12/realistic.yaml`` through :mod:`synlab.observe.realism` instead of the
    frozen ``pipeline._resolve_observe_spec``.  The substitution is a *documented patch* of a
    frozen module: ``_resolve_observe_spec`` propagates only seven fields and cannot express
    ``renderer`` / route work dir / imaging chain / distortion policy (see the module
    docstring of ``synlab.observe.realism``).  Every other stage is the frozen code path.

    Two legs are supported on the *same* lineage index:

    ``--leg realistic``  photo_mvs + Blender Cycles + degraded imaging (level 1) + the
                         distorted CAM_MID_V3 profile handled by ``distortion_policy=undistort``
    ``--leg control``    ideal_visible + software rasteriser + identity imaging (level 0),
                         i.e. the "ideal observation" reference the realism gap is measured
                         against.  The control store is ``<root>/control_ideal`` so the
                         realistic library stays clean.

    The two legs share ``master_seed`` and the whole dataset/fracture block of the realistic
    config, so they must produce **bit-identical clean/fragment geometry**; the report records
    the measured geometry hashes of both legs as the proof that the comparison is same-scene.

``--mode probe``  (cheap, software rasteriser only)
    Re-renders the *committed* fragment of one lineage with three observation specs on the
    same target and measures the products directly (the software path exposes both
    ``scene_linear`` and the post-sensor ``linear``, so the sensor noise is measured against
    its own ground truth):

    ``identity``  identity imaging chain (level 0)
    ``degraded``  the realistic level-1 imaging chain
    ``pinhole``   the realistic chain with a pinhole camera (the Blender ``undistort`` path)
    ``distorted`` the realistic chain with the profile's own OpenCV distortion (software path)

    Measured: sensor noise sigma and SNR in dB, PSF sharpness drop, deployment-mask coverage,
    depth validity, and the distortion's pixel effect at the delivered grid.

Exit codes: ``0`` report written (a ``STOP_SFM``/``MVS_NOT_AVAILABLE`` verdict inside the
report is a measured result, not a crash), ``3`` a step raised, ``4`` the config failed to
compile.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

REPORT_SCHEMA = "synlab.realism.pilot.v1"


# --------------------------------------------------------------------------------------
# measurement helpers
# --------------------------------------------------------------------------------------
def _wall(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _wall(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_wall(v) for v in x]
    if isinstance(x, np.ndarray):
        return {"__ndarray__": {"dtype": str(x.dtype), "shape": list(x.shape)}}
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, Path):
        return str(x)
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)


def noise_sigma_estimate(linear: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    """Robust per-channel noise sigma of a linear image inside ``mask`` (measured).

    The estimator is the MAD of the difference to a 3x3 median filter, i.e. a local
    high-frequency residual: on a smooth surface it is the sensor noise, on an edge-rich
    surface it also contains texture.  The edge-contaminated pixels (top decile of the local
    gradient) are therefore reported separately instead of being silently averaged in.
    """
    import cv2

    arr = np.asarray(linear, dtype=np.float64)
    if arr.ndim == 2:
        arr = arr[:, :, None]
    sel = np.asarray(mask, dtype=bool)
    if sel.shape != arr.shape[:2]:
        sel = np.zeros(arr.shape[:2], dtype=bool)
    if not sel.any():
        return {"sigma": 0.0, "sigma_smooth": 0.0, "mean_level": 0.0, "pixels": 0.0}
    med = cv2.medianBlur(arr.astype(np.float32), 3).astype(np.float64)
    resid = arr - med
    gray = arr.mean(axis=2) if arr.shape[2] > 1 else arr[:, :, 0]
    grad = cv2.Laplacian(gray.astype(np.float32), cv2.CV_32F)
    thresh = float(np.percentile(np.abs(grad)[sel], 90))
    smooth = sel & (np.abs(grad) <= thresh)
    if not smooth.any():
        smooth = sel
    r = resid[smooth]
    sigma = float(1.4826 * np.median(np.abs(r)))
    return {
        "sigma": sigma,
        "sigma_smooth": sigma,
        "mean_level": float(np.mean(arr[sel])),
        "pixels": float(np.count_nonzero(sel)),
    }


def snr_db(mean_level: float, sigma: float) -> float | None:
    if not np.isfinite(sigma) or sigma <= 0 or not np.isfinite(mean_level) or mean_level <= 0:
        return None
    return float(20.0 * np.log10(mean_level / sigma))


def declared_noise_sigma(mean_level: float, *, gain: float, read: float) -> float:
    """Declared sensor model sigma for a given mean linear level: sqrt(L/g + r^2)."""
    shot = (mean_level / gain) if gain > 0 else 0.0
    return float(np.sqrt(max(shot, 0.0) + float(read) ** 2))


def mesh_geometry_hash(mesh: Any) -> str:
    """Content hash of a mesh's vertices/faces (same-scene proof across two legs)."""
    payload = b"".join([np.ascontiguousarray(mesh.vertices, dtype=np.float64).tobytes(),
                        np.ascontiguousarray(mesh.faces, dtype=np.int64).tobytes()])
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _per_view_products(obs: Any) -> dict[str, Any]:
    """Measured per-view products of a committed observation (no truth involved)."""
    views = list(obs.views)
    rows: list[dict[str, Any]] = []
    for view in views:
        rgb = np.asarray(view.rgb)
        depth = np.asarray(view.depth_z)
        valid = np.isfinite(depth) & (depth > 0)
        mask = np.asarray(view.deployment_mask, dtype=bool)
        uncertain = np.asarray(view.uncertain_mask, dtype=bool)
        roi = view.roi
        noise = noise_sigma_estimate(np.asarray(view.rgb_linear, dtype=np.float64), mask)
        stages = {str(s.get("op")): s for s in (view.meta or {}).get("imaging_stages", [])}
        sensor = stages.get("poisson_read_noise", {})
        encode = stages.get("quantise_encode", {})
        exposure = stages.get("exposure_gain_before_photons", {})
        psf = stages.get("psf_applied", {})
        declared = declared_noise_sigma(
            noise["mean_level"],
            gain=float(sensor.get("effective_gain", 1.0) or 1.0),
            read=float(sensor.get("read_noise_sigma", 0.0) or 0.0))
        rows.append({
            "view_id": str(view.view_id),
            "image_size": [int(rgb.shape[1]), int(rgb.shape[0])],
            "mask_coverage": float(np.mean(mask)) if mask.size else 0.0,
            "depth_valid_fraction": float(np.mean(valid)) if valid.size else 0.0,
            "depth_valid_in_mask": float(np.mean(valid[mask])) if mask.any() else 0.0,
            "uncertain_fraction": float(np.mean(uncertain)) if uncertain.size else 0.0,
            "roi_coverage": (float(np.mean(valid & np.asarray(roi, dtype=bool)))
                             if roi is not None and np.asarray(roi).size else None),
            "noise_sigma_measured": noise["sigma"],
            "noise_sigma_declared": declared,
            "mean_linear_in_mask": noise["mean_level"],
            "snr_measured_db": snr_db(noise["mean_level"], noise["sigma"]),
            "snr_declared_db": snr_db(noise["mean_level"], declared),
            "blur_laplacian": _laplacian(rgb),
            "declared": {
                "exposure_ev": exposure.get("exposure_ev"),
                "psf_sigma_px": psf.get("sigma_px"),
                "effective_gain": sensor.get("effective_gain"),
                "read_noise_sigma": sensor.get("read_noise_sigma"),
                "encode": encode.get("encode"),
                "jpeg_quality": encode.get("jpeg_quality"),
                "encode_bytes": encode.get("bytes"),
                "saturated_fraction": sensor.get("saturated_fraction"),
            },
            "render_backend": (view.meta or {}).get("render_backend"),
            "imaging_labels": list((view.meta or {}).get("imaging_labels") or []),
        })
    out: dict[str, Any] = {"views": rows, "n_views": len(rows)}
    if rows:
        for key in ("mask_coverage", "depth_valid_fraction", "depth_valid_in_mask",
                    "uncertain_fraction", "noise_sigma_measured", "noise_sigma_declared",
                    "snr_measured_db", "snr_declared_db", "mean_linear_in_mask"):
            values = [r[key] for r in rows if r.get(key) is not None]
            out[key + "_mean"] = float(np.mean(values)) if values else None
    return out


def _laplacian(rgb: np.ndarray) -> float:
    import cv2

    arr = np.asarray(rgb)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY) if arr.ndim == 3 else arr
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


# --------------------------------------------------------------------------------------
# mode: run (heavy)
# --------------------------------------------------------------------------------------
def _install_bridge(spec: Any, *, store_root: Path, leg: str, levels: dict[str, int],
                    route: str, renderer: str, distortion_policy: str | None,
                    blender_samples: int, mask_policy: str,
                    photon_gain: float | None) -> dict[str, Any]:
    """Patch the frozen pipeline's observation projection with the realism bridge.

    Two patches are needed and both are recorded in the report:

    * ``pipeline._resolve_observe_spec`` -- the frozen projection propagates only seven fields
      and cannot express renderer / route work dir / imaging chain / distortion policy /
      mask policy.  The realism bridge replaces it.
    * ``observe.api.observe`` -- ``build_one_mother`` takes the *route* from
      ``spec.observation.routes[0]`` (``photo_mvs`` in ``configs/a12/realistic.yaml``), so the
      control leg (``ideal_visible``) has to force the route at the call boundary; without
      this the "control" leg silently ran the realistic route with ideal imaging.
    """
    import synlab.observe.api as observe_api
    import synlab.pipeline as pipeline
    from synlab.observe.realism import observe_spec_from_config

    state: dict[str, Any] = {"lineage": None, "plans": {}, "routes": []}

    def _resolve(spec_arg: Any, store: Any) -> Any:
        lineage = state["lineage"]
        if lineage is None:  # pragma: no cover - the wrapper always sets it first
            raise RuntimeError("pipeline._resolve_observe_spec called before a lineage was set")
        plan = observe_spec_from_config(
            spec_arg, store_root=store_root, lineage_id=lineage.lineage_id, route=route,
            renderer=renderer, levels=levels, distortion_policy=distortion_policy,
            mask_policy=mask_policy, photon_gain=photon_gain,
            blender_samples=blender_samples)
        state["plans"][lineage.lineage_id] = plan
        return plan.obs_spec

    original_observe = observe_api.observe
    route_forced = str(route)

    def _observe(target: Any, compiled: Any, rngs: Any, *, route: str, profile: Any = None,
                 renderer: Any = None, spec: Any = None) -> Any:
        # build_one_mother takes the route from ``spec.observation.routes[0]``; the leg's route
        # is *forced* here (the requested route is recorded so the substitution is visible)
        state["routes"].append({"requested": route, "forced": route_forced})
        return original_observe(target, compiled, rngs, route=route_forced, profile=profile,
                                renderer=renderer, spec=spec)

    original_build = pipeline.build_one_mother

    def _build(plan: Any, lineage: Any, store: Any, **kwargs: Any) -> Any:
        state["lineage"] = lineage
        return original_build(plan, lineage, store, **kwargs)

    pipeline._resolve_observe_spec = _resolve  # type: ignore[assignment]
    pipeline.build_one_mother = _build  # type: ignore[assignment]
    observe_api.observe = _observe  # type: ignore[assignment]
    return state


def _observation_summary(store: Any, asset_id: str) -> dict[str, Any]:
    from synlab.observe.api import load_observation
    from synlab.observe.realism import is_realistic_capture, realism_tags

    obs = load_observation(store, asset_id)
    verdict, reasons = is_realistic_capture(obs)
    report = dict(getattr(obs, "backend_report", {}) or {})
    products = _per_view_products(obs)
    quality = {k: (v.get("value") if isinstance(v, dict) else v)
               for k, v in dict(getattr(obs, "quality", {}) or {}).items()
               if isinstance(v, (dict, int, float, str))}
    return {
        "asset_id": asset_id,
        "fragment_id": str(obs.fragment_id),
        "route": str(obs.route),
        "route_status": str((obs.meta or {}).get("route_status", "")),
        "input_profile": str(obs.input_profile),
        "scale_valid": bool(obs.scale_valid),
        "n_points": int(np.asarray(obs.points).shape[0]),
        "renderer": str((obs.meta or {}).get("renderer", "")),
        "distortion_policy": str((obs.meta or {}).get("distortion_policy", "")),
        "obs_semantics": (obs.meta or {}).get("obs_semantics"),
        "data_semantics": (obs.meta or {}).get("data_semantics"),
        "tags": _wall(realism_tags(obs)),
        "is_realistic_capture": bool(verdict),
        "is_realistic_capture_failures": reasons,
        "quality": _wall(quality),
        "products": _wall(products),
        "backend_report": _wall(report),
    }


def run_leg(args: argparse.Namespace, *, leg: str) -> dict[str, Any]:
    from synlab.canonical import hash_file
    from synlab.config import load_generation_spec
    from synlab.observe.realism import (LEVEL_IDENTITY, LEVEL_REALISTIC, MASK_POLICY_PIPELINE_COC,
                                        degradation_report, observe_spec_from_config, run_tag)
    from synlab.pipeline import plan_generation
    from synlab.registry import load_all
    from synlab.roles import ROLE_FRAGMENT_MESH
    from synlab.storage.store import QA_PASS, AssetStore

    load_all()
    spec = load_generation_spec(args.config)
    plan = plan_generation(spec)
    root = Path(args.root) if leg == "realistic" else Path(args.control_root)
    store = AssetStore(root)
    wanted = {int(x) for x in str(args.only).split(",") if str(x).strip()}
    lineages = [l for l in plan.lineages if l.mother_index in wanted]
    if not lineages:
        raise SystemExit(f"no lineage matches --only {args.only} (planned {len(plan.lineages)})")

    levels = ({axis: LEVEL_IDENTITY for axis in
               ("I01", "I03", "I04", "I05", "I10")} if leg == "control"
              else {axis: LEVEL_REALISTIC for axis in ("I01", "I03", "I04", "I05", "I10")})
    route = "ideal_visible" if leg == "control" else "photo_mvs"
    renderer = "software_rasterizer" if leg == "control" else "blender"
    policy = None if leg == "control" else args.distortion_policy
    # The control leg is the *frozen* reference: identity imaging and the pipeline's own CoC
    # mark-out.  The realistic leg declares the foreground-silhouette mask (measured reason in
    # synlab/observe/realism.py: the CoC mark-out leaves the SfM mask without the object).
    mask_policy = (MASK_POLICY_PIPELINE_COC if leg == "control" else args.mask_policy)
    photon_gain = None if leg == "control" else args.photon_gain
    state = _install_bridge(spec, store_root=root, leg=leg, levels=levels, route=route,
                            renderer=renderer, distortion_policy=policy,
                            blender_samples=int(args.blender_samples),
                            mask_policy=mask_policy, photon_gain=photon_gain)
    run_id = f"run_realistic_{leg}_{plan.job_id.split('_', 1)[-1][:10]}"
    sample_plan = observe_spec_from_config(spec, store_root=root,
                                           lineage_id=lineages[0].lineage_id, route=route,
                                           renderer=renderer, levels=levels,
                                           distortion_policy=policy, mask_policy=mask_policy,
                                           photon_gain=photon_gain,
                                           blender_samples=int(args.blender_samples))
    tag = run_tag(spec, sample_plan, root=str(root), run_id=run_id)
    store.create_run(run_id, plan.spec_hash, scope=spec.data_scope.value,
                     profile=spec.release_profile.value,
                     meta={"plan": plan.as_dict(), "spec": plan.compiled.expanded,
                           "batch_driver": "tests/a12/observe/run_realistic_lineage.py",
                           "leg": leg,
                           "realism": tag})

    out: dict[str, Any] = {
        "leg": leg, "root": str(root), "run_id": run_id, "route": route,
        "renderer": renderer, "distortion_policy": policy,
        "mask_policy": mask_policy, "photon_gain_override": photon_gain,
        "levels": dict(levels),
        "degradation": degradation_report(levels, mask_policy=mask_policy,
                                          photon_gain=photon_gain),
        "plan": _wall(sample_plan.as_dict()),
        "lineages": {}, "started_at": time.time(),
        "patched": {
            "pipeline._resolve_observe_spec": "synlab.observe.realism.observe_spec_from_config",
            "pipeline.build_one_mother": "lineage-tracking wrapper (unchanged behaviour)",
            "observe.api.observe": "route forced to the leg's route at the call boundary",
            "routes_requested": state["routes"],
        },
    }
    for lineage in lineages:
        entry: dict[str, Any] = {"lineage_id": lineage.lineage_id,
                                 "mother_index": int(lineage.mother_index),
                                 "split": lineage.split, "vessel_id": lineage.vessel_id,
                                 "material_id": lineage.material_id,
                                 "pattern_id": lineage.pattern_id}
        t0 = time.time()
        try:
            outcome = __import__("synlab.pipeline", fromlist=["build_one_mother"]).build_one_mother(
                plan, lineage, store, run_id=run_id)
        except Exception as exc:  # noqa: BLE001 - one mother's failure is a measured outcome
            entry.update({"ok": False, "seconds": time.time() - t0,
                          "error": f"{type(exc).__name__}: {exc}",
                          "traceback": traceback.format_exc()[-1500:]})
            out["lineages"][lineage.lineage_id] = entry
            _write_report(args, out)
            continue
        row = dict(outcome["coverage_row"])
        entry.update({
            "ok": bool(outcome["ok"]),
            "seconds": time.time() - t0,
            "stages": _wall(row.get("stages") or {}),
            "fragments": row.get("fragments"),
            "observations": row.get("observations"),
            "r2_pairs": row.get("r2_pairs"),
            "obs_endpoint_failures": _wall(row.get("obs_endpoint_failures") or {}),
            "physical_audit_status": row.get("physical_audit_status"),
            "fracture_audit": _wall(row.get("fracture_audit") or {}),
            "error": (outcome.get("error") or {}).get("code"),
            "error_message": (outcome.get("error") or {}).get("message"),
            "bridge_plan": _wall(state["plans"].get(lineage.lineage_id).as_dict()
                                 if state["plans"].get(lineage.lineage_id) else None),
            "obs_semantics": row.get("obs_semantics"),
            "data_semantics": _wall(row.get("data_semantics")),
        })
        # per-observation measured products
        obs_assets = dict(row.get("obs_assets") or {})
        entry["observation_assets"] = obs_assets
        entry["observations_detail"] = {}
        for fragment_id, asset_id in obs_assets.items():
            try:
                detail = _observation_summary(store, asset_id)
            except Exception as exc:  # noqa: BLE001
                detail = {"asset_id": asset_id, "error": f"{type(exc).__name__}: {exc}"}
            if len(entry["observations_detail"]) == 0:
                detail["obs_target_role"] = "physical_damage_target"
            else:
                detail["obs_target_role"] = "fracture_event_endpoint"
            entry["observations_detail"][fragment_id] = detail
        # same-scene proof: the committed fragment meshes of both legs
        geometry: dict[str, str] = {}
        for record in store.list_assets(role=ROLE_FRAGMENT_MESH, lineage_id=lineage.lineage_id):
            try:
                mesh = store.load_mesh(record.asset_id)
                geometry[str(record.meta.get("fragment_id", record.asset_id))] = \
                    mesh_geometry_hash(mesh)
            except Exception:  # noqa: BLE001
                continue
        entry["fragment_geometry_hashes"] = geometry
        entry["config_hash"] = hash_file(args.config)
        out["lineages"][lineage.lineage_id] = entry
        _write_report(args, out)
        print(f"[{leg}] {lineage.lineage_id} ok={entry['ok']} "
              f"frag={entry.get('fragments')} obs={entry.get('observations')} "
              f"{entry['seconds']:.1f}s", flush=True)
    # ``set_run_status`` *replaces* meta_json, so the realism tag is written again here: a
    # run record that lost its capture-style declaration would be indistinguishable from the
    # frozen batch (the pipeline stamps data_semantics/obs_semantics on every batch alike).
    store.set_run_status(run_id, "QA_PASSED" if any(
        v.get("ok") for v in out["lineages"].values()) else "FAILED",
        meta={"plan": plan.as_dict(), "leg": leg,
              "batch_driver": "tests/a12/observe/run_realistic_lineage.py",
              "realism": tag,
              "lineages": {k: {"ok": v.get("ok"), "seconds": v.get("seconds")}
                           for k, v in out["lineages"].items()}})
    out["finished_at"] = time.time()
    return out


# --------------------------------------------------------------------------------------
# mode: probe (cheap, software rasteriser, same committed target)
# --------------------------------------------------------------------------------------
def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    """Same-scene product comparison at the delivered grid (software rasteriser)."""
    from synlab.cameras.api import camera_profiles
    from synlab.config import load_generation_spec
    from synlab.observe.api import load_observation
    from synlab.observe.realism import (IDEAL_REFERENCE_GAIN, LEVEL_IDENTITY, LEVEL_REALISTIC,
                                        MASK_POLICY_FOREGROUND, MASK_POLICY_PIPELINE_COC,
                                        observe_spec_from_config)
    from synlab.observe.routes import (ObsSpec, _frame_for_delivered,
                                       distortion_pixel_effect_px, render_views,
                                       resolve_target)
    from synlab.pipeline import plan_generation
    from synlab.registry import load_all
    from synlab.roles import ROLE_FRAGMENT_MESH, ROLE_OBS_RESULT
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    load_all()
    spec = load_generation_spec(args.config)
    plan = plan_generation(spec)
    wanted = [int(x) for x in str(args.only).split(",") if str(x).strip()]
    lineage = next((l for l in plan.lineages if l.mother_index == wanted[0]), None)
    if lineage is None:
        raise SystemExit(f"no lineage with index {wanted[0]}")
    store = AssetStore(Path(args.root))
    records = store.list_assets(role=ROLE_FRAGMENT_MESH, lineage_id=lineage.lineage_id)
    if not records:
        raise SystemExit(f"lineage {lineage.lineage_id} has no committed fragment in {args.root}; "
                         f"run --mode run first")
    record = records[0]
    mesh = store.load_mesh(record.asset_id)
    attrs = dict((mesh.metadata or {}).get("face_attr_arrays") or {})
    target = resolve_target({"mesh": mesh, "fragment_id": record.meta.get("fragment_id", ""),
                             "face_origin_kind": attrs.get("origin_kind"),
                             "face_interface_id": attrs.get("interface_id")})
    # The camera profile carries OpenCV distortion.  The software rasteriser projects through
    # it (the delivered image is distorted); the Blender backend cannot, so the realistic leg
    # delivers the *undistorted pinhole* image of the same K.  Both cases are measured here
    # with the same profile by handing the pinhole variant a dist-free copy of it.
    profile = camera_profiles()[1]
    pinhole_profile = dataclasses.replace(profile, dist=None,
                                          profile_id=f"{profile.profile_id}_PINHOLE")
    realistic_levels = {axis: LEVEL_REALISTIC for axis in ("I01", "I03", "I04", "I05", "I10")}
    identity_levels = {axis: LEVEL_IDENTITY for axis in ("I01", "I03", "I04", "I05", "I10")}

    def _spec_for(levels: dict[str, int], chosen_profile: Any, *,
                  mask_policy: str = MASK_POLICY_FOREGROUND,
                  photon_gain: float | None = None) -> ObsSpec:
        return observe_spec_from_config(
            spec, store_root=Path(args.root), lineage_id=lineage.lineage_id,
            route="photo_mvs", renderer="software_rasterizer", levels=levels,
            distortion_policy=None, profile=chosen_profile, mask_policy=mask_policy,
            photon_gain=photon_gain, view_count=int(args.probe_views)).obs_spec

    variants: dict[str, tuple[ObsSpec, Any, str]] = {
        # what the *control* leg delivers today: frozen identity imaging (photon scale 1.0),
        # the profile's own distortion and the pipeline's CoC mark-out
        "control_frozen_identity": (
            _spec_for(identity_levels, profile, mask_policy=MASK_POLICY_PIPELINE_COC), profile,
            "frozen identity chain (gain 1.0), profile distortion, pipeline CoC mark-out"),
        # the same ideal chain at a photon scale that is not shot-noise limited: separates the
        # simulator's photon starvation from the route's own degradation
        "ideal_photon_scaled": (
            _spec_for(identity_levels, profile, photon_gain=IDEAL_REFERENCE_GAIN), profile,
            f"identity chain with effective_gain={IDEAL_REFERENCE_GAIN:g} (MvsConfig's value)"),
        # what the realistic leg's imaging chain does, still on the distorted camera
        "realistic_imaging_distorted_camera": (
            _spec_for(realistic_levels, profile), profile,
            "level-1 imaging chain + profile distortion + foreground mask"),
        # what the realistic leg actually delivers through Blender+undistort
        "realistic_imaging_pinhole_camera": (
            _spec_for(realistic_levels, pinhole_profile), pinhole_profile,
            "level-1 imaging chain + undistorted pinhole (the Blender "
            "distortion_policy=undistort deliverable)"),
    }

    out: dict[str, Any] = {
        "mode": "probe", "root": str(args.root), "lineage_id": lineage.lineage_id,
        "fragment_asset": record.asset_id,
        "fragment_geometry_hash": mesh_geometry_hash(mesh),
        "delivered_size": list(next(iter(variants.values()))[0].delivered_size),
        "views": int(args.probe_views),
        "profile_id": profile.profile_id,
        "profile_distortion": np.asarray(profile.dist, dtype=np.float64).ravel().tolist(),
        "renderer": "software_rasterizer",
        "variants": {},
    }
    for name, (obs_spec, chosen_profile, description) in variants.items():
        sensor_rng = make_rng(20261001, f"probe_{name}", "sensor")
        bundles = render_views(target, chosen_profile, obs_spec, sensor_rng,
                               backend="software_rasterizer")
        rows = []
        effects: list[float] = []
        for bundle in bundles:
            delivered_frame = _frame_for_delivered(bundle, obs_spec)
            effect = distortion_pixel_effect_px(delivered_frame)
            if effect is not None:
                effects.append(float(effect))
            visible = np.asarray(bundle.deploy_mask, dtype=bool)
            scene = np.asarray(bundle.imaging.scene_linear, dtype=np.float64)
            linear = np.asarray(bundle.imaging.linear, dtype=np.float64)
            inner = visible.copy()
            if inner.any():
                import cv2

                inner = cv2.erode(inner.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
            residual = linear - scene
            true_sigma = float(np.std(residual[inner])) if inner.any() else None
            mean_scene = float(np.mean(scene[visible])) if visible.any() else 0.0
            rows.append({
                "view_id": str(bundle.frame.view_id),
                "mask_coverage": float(np.mean(visible)) if visible.size else 0.0,
                "depth_valid_fraction": float(np.mean(np.isfinite(bundle.render.depth_z))),
                "uncertain_fraction": float(np.mean(bundle.imaging.uncertain_mask)),
                "mean_scene_linear": mean_scene,
                "unique_levels_gray": int(len(np.unique(
                    np.asarray(bundle.imaging.image).mean(axis=2).astype(np.uint8)))),
                "delivered_uint8_mean": float(np.mean(bundle.imaging.image)),
                "delivered_uint8_std": float(np.std(bundle.imaging.image)),
                "noise_from_ground_truth_sigma": true_sigma,
                "snr_from_ground_truth_db": snr_db(mean_scene, true_sigma or 0.0),
                "noise_from_delivered_linear_sigma":
                    noise_sigma_estimate(linear, visible)["sigma"],
                "blur_laplacian_rgb": _laplacian(bundle.imaging.image),
                "blur_laplacian_linear": _laplacian(np.asarray(bundle.imaging.linear)),
                "delivered_distortion_none": delivered_frame.dist is None,
                "delivered_camera_model": delivered_frame.camera_model,
                "distortion_provenance": dict(bundle.distortion),
                "delivered_mm_per_px": float(delivered_frame.working_distance_mm
                                             / float(bundle.K[0, 0])),
                "delivered_size": list(bundle.imaging.image.shape[:2][::-1]),
            })
        agg: dict[str, Any] = {"description": description, "per_view": rows}
        for key in ("mask_coverage", "depth_valid_fraction", "uncertain_fraction",
                    "noise_from_ground_truth_sigma", "snr_from_ground_truth_db",
                    "noise_from_delivered_linear_sigma", "blur_laplacian_rgb",
                    "blur_laplacian_linear", "mean_scene_linear", "unique_levels_gray",
                    "delivered_uint8_mean", "delivered_uint8_std"):
            values = [r[key] for r in rows if r.get(key) is not None]
            agg[key + "_mean"] = float(np.mean(values)) if values else None
        agg["distortion_max_pixel_effect_px_delivered"] = (float(max(effects))
                                                           if effects else None)
        agg["imaging_identity"] = bool(obs_spec.imaging.is_identity())
        agg["imaging_spec"] = {
            "defocus_sigma_px": obs_spec.imaging.defocus_sigma_px,
            "effective_gain": obs_spec.imaging.effective_gain,
            "read_noise_sigma": obs_spec.imaging.read_noise_sigma,
            "exposure_ev": obs_spec.imaging.exposure_ev,
            "white_balance": list(obs_spec.imaging.white_balance),
            "encode": obs_spec.imaging.encode,
            "jpeg_quality": obs_spec.imaging.jpeg_quality,
        }
        out["variants"][name] = agg
    # the SfM numbers of the committed realistic observation (if the leg has run)
    try:
        obs_assets = list(store.list_assets(role=ROLE_OBS_RESULT,
                                            lineage_id=lineage.lineage_id))
        out["committed_observations"] = [
            {"asset_id": r.asset_id,
             "renderer": (r.meta.get("meta") or {}).get("renderer"),
             "route": r.meta.get("route"),
             "route_status": (r.meta.get("meta") or {}).get("route_status")}
            for r in obs_assets]
        if obs_assets:
            obs = load_observation(store, obs_assets[0].asset_id)
            report = dict(obs.backend_report or {})
            out["committed_sfm"] = {
                "route": report.get("route"),
                "failure_code": report.get("failure_code"),
                "failure_reason": report.get("failure_reason"),
                "capability_probe": _wall(report.get("capability_probe")),
                "reconstruction": _wall(report.get("reconstruction")),
                "dense": _wall(report.get("dense")),
                "dense_backend": report.get("dense_backend"),
                "argv_seconds": {str(e.get("argv", [""])[0]): e.get("seconds")
                                 for e in (report.get("argv_log") or [])},
                "scale_valid": bool(obs.scale_valid),
                "n_points": int(np.asarray(obs.points).shape[0]),
                "quality": _wall({k: (v.get("value") if isinstance(v, dict) else v)
                                  for k, v in dict(obs.quality).items()
                                  if isinstance(v, (dict, int, float, str))}),
                "products": _wall(_per_view_products(obs)),
            }
    except Exception as exc:  # noqa: BLE001
        out["committed_sfm_error"] = f"{type(exc).__name__}: {exc}"
    return out


# --------------------------------------------------------------------------------------
# report plumbing
# --------------------------------------------------------------------------------------
def _load_report(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"schema": REPORT_SCHEMA, "legs": {}, "probes": {}}


def _write_report(args: argparse.Namespace, leg_payload: dict[str, Any]) -> None:
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = _load_report(path)
    document["schema"] = REPORT_SCHEMA
    document.setdefault("legs", {})
    document.setdefault("probes", {})
    document["config"] = str(args.config)
    document["root"] = str(args.root)
    document["control_root"] = str(args.control_root)
    document["legs"][leg_payload["leg"]] = leg_payload
    _compare(document)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(_wall(document), ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    tmp.replace(path)


def _write_probe(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = _load_report(path)
    document["schema"] = REPORT_SCHEMA
    document.setdefault("legs", {})
    document.setdefault("probes", {})
    document["config"] = str(args.config)
    document["probes"][str(payload.get("lineage_id"))] = payload
    _compare(document)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(_wall(document), ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    tmp.replace(path)


def _agg_view_key(entry: dict[str, Any], key: str) -> float | None:
    """Mean of one per-view product over every observation of one leg."""
    values: list[float] = []
    for detail in (entry.get("observations_detail") or {}).values():
        for view in ((detail.get("products") or {}).get("views") or []):
            value = view.get(key)
            if value is not None:
                values.append(float(value))
    return float(np.mean(values)) if values else None


def _quality_key(entry: dict[str, Any], key: str) -> float | None:
    values: list[float] = []
    for detail in (entry.get("observations_detail") or {}).values():
        value = (detail.get("quality") or {}).get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return float(np.mean(values)) if values else None


def _compare(document: dict[str, Any]) -> None:
    """Same-scene comparison between the two legs (only what the measurements support)."""
    real = (document.get("legs") or {}).get("realistic") or {}
    control = (document.get("legs") or {}).get("control") or {}
    rows: dict[str, Any] = {}
    for lineage_id, real_entry in (real.get("lineages") or {}).items():
        control_entry = (control.get("lineages") or {}).get(lineage_id)
        if not control_entry:
            continue
        same_scene = (real_entry.get("fragment_geometry_hashes")
                      == control_entry.get("fragment_geometry_hashes"))
        rows[lineage_id] = {
            "same_scene_geometry_hashes_equal": bool(same_scene),
            "realistic_stages": real_entry.get("stages"),
            "control_stages": control_entry.get("stages"),
            "realistic_seconds": real_entry.get("seconds"),
            "control_seconds": control_entry.get("seconds"),
            "route": {"realistic": real.get("route"), "control": control.get("route")},
            "renderer": {"realistic": real.get("renderer"), "control": control.get("renderer")},
            "mask_coverage": {"realistic": _agg_view_key(real_entry, "mask_coverage"),
                              "control": _agg_view_key(control_entry, "mask_coverage")},
            "depth_valid_in_mask": {
                "realistic": _agg_view_key(real_entry, "depth_valid_in_mask"),
                "control": _agg_view_key(control_entry, "depth_valid_in_mask")},
            "uncertain_fraction": {
                "realistic": _agg_view_key(real_entry, "uncertain_fraction"),
                "control": _agg_view_key(control_entry, "uncertain_fraction")},
            "noise_sigma_measured": {
                "realistic": _agg_view_key(real_entry, "noise_sigma_measured"),
                "control": _agg_view_key(control_entry, "noise_sigma_measured")},
            "snr_measured_db": {"realistic": _agg_view_key(real_entry, "snr_measured_db"),
                                "control": _agg_view_key(control_entry, "snr_measured_db")},
            "snr_declared_db": {"realistic": _agg_view_key(real_entry, "snr_declared_db"),
                                "control": _agg_view_key(control_entry, "snr_declared_db")},
            "blur_laplacian_p95": {"realistic": _quality_key(real_entry, "blur_laplacian_p95"),
                                   "control": _quality_key(control_entry, "blur_laplacian_p95")},
            "hole_ratio_max": {"realistic": _quality_key(real_entry, "hole_ratio_max"),
                               "control": _quality_key(control_entry, "hole_ratio_max")},
            "point_count": {"realistic": _quality_key(real_entry, "point_count"),
                            "control": _quality_key(control_entry, "point_count")},
            "points": {"realistic": _points(real_entry), "control": _points(control_entry)},
        }
    if rows:
        document["comparison"] = rows


def _points(entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for fragment_id, detail in (entry.get("observations_detail") or {}).items():
        report = detail.get("backend_report") or {}
        recon = report.get("reconstruction") or {}
        out[fragment_id] = {
            "n_points": detail.get("n_points"),
            "scale_valid": detail.get("scale_valid"),
            "route_status": detail.get("route_status"),
            "num_reg_images": recon.get("num_reg_images"),
            "num_points3D": recon.get("num_points3D"),
            "mean_reproj_error_px": recon.get("mean_reproj_error_px"),
            "registered_fraction": recon.get("registered_fraction"),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(ROOT / "configs" / "a12" / "realistic.yaml"))
    parser.add_argument("--root", default=str(ROOT / "data" / "a12_realistic"))
    parser.add_argument("--control-root",
                        default=str(ROOT / "data" / "a12_realistic" / "control_ideal"))
    parser.add_argument("--report", default=str(ROOT / "data" / "a12" / "reports"
                                                / "realistic_pilot.json"))
    parser.add_argument("--mode", choices=("run", "probe"), default="run")
    parser.add_argument("--leg", choices=("realistic", "control"), default="realistic")
    parser.add_argument("--only", default="0", help="comma-separated mother indices")
    parser.add_argument("--distortion-policy", default="undistort",
                        choices=("undistort", "ignore", "error"))
    parser.add_argument("--mask-policy", default="foreground_silhouette",
                        choices=("foreground_silhouette", "pipeline_coc_markout"))
    parser.add_argument("--photon-gain", type=float, default=None,
                        help="override the ladder's I03 photon scale (default: the ladder)")
    parser.add_argument("--blender-samples", type=int, default=32)
    parser.add_argument("--probe-views", type=int, default=4)
    args = parser.parse_args(argv)
    try:
        if args.mode == "run":
            payload = run_leg(args, leg=args.leg)
            _write_report(args, payload)
            print(json.dumps({k: v for k, v in payload.items() if k != "lineages"},
                             ensure_ascii=False, default=str)[:2000], flush=True)
        else:
            payload = run_probe(args)
            _write_probe(args, payload)
            print(json.dumps(payload, ensure_ascii=False, default=str)[:2000], flush=True)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
