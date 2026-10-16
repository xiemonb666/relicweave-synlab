"""``synlab.observe`` façade (frozen interface, ``docs/a12/interfaces.md`` section 2)::

    observe(physical_or_fragment, compiled, rngs, *, route, profile, renderer=None)
        -> ObservationResult
    commit_observation(store, obs, *, lineage_id, split, ancestry) -> AssetRecord
    load_observation(store, asset_id) -> ObservationResult
    adapt_observed_features(obs, contract) -> dict
    estimate_quality(obs) -> dict
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..roles import ROLE_OBS_RESULT, SCHEMA_OBS
from ..schemas.runtime import CameraProfile, ObservationResult
from .features import FEATURE_SCHEMA, adapt_observed_features, assert_no_leakage
from .quality import OBS_EST_VERSION
from .quality import estimate_quality as _estimate_quality
from .render import BACKEND_SOFTWARE, BLENDER_GAP, capability_probe
from .routes import (
    ROUTE_IDEAL_VISIBLE,
    ROUTE_PHOTO_MVS,
    ROUTE_PROXY_SCAN,
    ROUTE_SPECS,
    ObsSpec,
    observation_from_dict,
    observation_meta,
    observation_to_dict,
    render_backend_name,
    resolve_target,
    route_ideal_visible,
    route_photo_mvs,
    route_proxy_scan,
)

ROUTES: tuple[str, ...] = (ROUTE_IDEAL_VISIBLE, ROUTE_PROXY_SCAN, ROUTE_PHOTO_MVS)

__all__ = [
    "observe", "commit_observation", "load_observation", "adapt_observed_features",
    "estimate_quality", "ROUTES", "ROUTE_SPECS", "ObsSpec", "capability_probe",
    "BACKEND_SOFTWARE", "BLENDER_GAP", "assert_no_leakage", "FEATURE_SCHEMA",
    "OBS_EST_VERSION",
]


def _resolve_profile(profile: Any) -> CameraProfile:
    from ..cameras.api import camera_profiles, profile_by_id

    if profile is None:
        return camera_profiles()[1]
    if isinstance(profile, CameraProfile):
        return profile
    if isinstance(profile, str):
        if profile in ("GLOBAL", "MID", "LOCAL"):
            for candidate in camera_profiles():
                if candidate.tier == profile:
                    return candidate
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"tier {profile!r} unavailable",
                              stage="observe.observe")
        return profile_by_id(profile)
    raise SynLabError(ErrorCode.SCHEMA_INVALID,
                      f"profile must be a CameraProfile, a tier name or a profile id, "
                      f"got {type(profile)!r}",
                      stage="observe.observe")


def _resolve_rng(rngs: Any, module: str, *, master_seed: int, lineage_id: str):
    import numpy as _np

    from ..seeds import make_rng

    if rngs is None:
        return make_rng(master_seed, lineage_id, module)
    if isinstance(rngs, _np.random.Generator):
        return rngs
    if isinstance(rngs, Mapping):
        if module in rngs:
            return rngs[module]
        for key in ("camera", "sensor", "geometry", "sampler", "all"):
            if key in rngs:
                return rngs[key]
        if len(rngs) == 1:
            return next(iter(rngs.values()))
    raise SynLabError(
        ErrorCode.SCHEMA_INVALID,
        f"rngs must be a Generator or a mapping with a {module!r} substream "
        f"(see synlab.seeds.derive_named_rngs)",
        stage="observe.observe",
    )


def observe(physical_or_fragment: Any, compiled: Any, rngs: Any, *, route: str,
            profile: Any = None, renderer: Any = None,
            spec: ObsSpec | None = None) -> ObservationResult:
    """Run one observation route and return a real :class:`ObservationResult`.

    ``compiled`` is the compiled DAG produced by ``synlab.degrade``.  This module consumes
    only the parts that are observation-relevant (stage order, mask/crop/encoding
    decisions, the scene parameters it must re-render for).  When it is ``None`` the
    defaults of :class:`ObsSpec` are used; a compiled DAG that is present is validated
    rather than trusted blindly.
    """
    if route not in ROUTES:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown observation route {route!r}; expected one of {ROUTES}",
                          stage="observe.observe")
    spec = spec or ObsSpec()
    _apply_compiled(compiled, spec, route)
    if renderer is not None:
        name = str(getattr(renderer, "backend", renderer))
        if name.upper() not in ("SOFTWARE_RASTERIZER", "AUTO", "AUTO_SOFTWARE"):
            raise SynLabError(
                ErrorCode.ENV_CAPABILITY_MISSING,
                f"renderer {name!r} is not available here: Blender/bpy has no Windows "
                f"py3.12 wheel.  Use the software rasteriser or the Blender worker "
                f"adapter (blender_scripts/render_worker.py) on a host with bpy; the "
                f"request is not silently downgraded.",
                stage="observe.observe",
                evidence_refs=[BLENDER_GAP["detail"]],
            )
    camera = _resolve_profile(profile)
    cam_rng = _resolve_rng(rngs, "camera", master_seed=spec.master_seed,
                           lineage_id=spec.lineage_id)
    target = resolve_target(physical_or_fragment, None)

    if route == ROUTE_IDEAL_VISIBLE:
        result, _ = route_ideal_visible(target, camera, spec, cam_rng)
    elif route == ROUTE_PROXY_SCAN:
        result, _ = route_proxy_scan(target, camera, spec, cam_rng)
    else:
        result, _, _ = route_photo_mvs(target, camera, spec, cam_rng)
    result.meta.setdefault("seed_ref", f"{spec.master_seed}:{spec.lineage_id}")
    result.meta.setdefault("renderer", render_backend_name())
    result.meta.setdefault("route_boundary", ROUTE_SPECS[route]["claim_boundary"])
    result.quality = estimate_quality(result)
    return result


def _apply_compiled(compiled: Any, spec: ObsSpec, route: str) -> None:
    """Consume the observation-relevant part of a compiled DAG without trusting it."""
    if compiled is None:
        return
    nodes = getattr(compiled, "nodes", None)
    if nodes is None and isinstance(compiled, Mapping):
        nodes = compiled.get("nodes")
    if nodes is None:
        # A compiled recipe that cannot be inspected is not silently accepted.
        if isinstance(compiled, (str, bytes)):
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              "compiled recipe must be a typed DAG object, not a path string",
                              stage="observe.observe._apply_compiled")
        return
    allowed_routes = getattr(compiled, "allowed_profile", None)
    if isinstance(allowed_routes, Mapping) and "observation_route" in allowed_routes:
        declared = allowed_routes["observation_route"]
        if declared != route:
            raise SynLabError(
                ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION,
                f"compiled recipe declares observation_route={declared!r} but {route!r} "
                f"was requested",
                stage="observe.observe._apply_compiled",
            )
    for node in nodes if isinstance(nodes, (list, tuple)) else []:
        params = getattr(node, "parameters", None) or {}
        stage = str(getattr(node, "stage", "") or "").upper()
        if stage in ("SENSOR", "ISP"):
            if "effective_gain" in params:
                spec.imaging.effective_gain = float(params["effective_gain"])
            if "read_noise_sigma" in params:
                spec.imaging.read_noise_sigma = float(params["read_noise_sigma"])
            if "bit_depth" in params:
                spec.imaging.bit_depth = int(params["bit_depth"])
        elif stage == "OPTICS":
            if "exposure_ev" in params:
                spec.imaging.exposure_ev = float(params["exposure_ev"])
            if "psf_sigma_px" in params:
                spec.imaging.defocus_sigma_px = float(params["psf_sigma_px"])
        elif stage == "IMAGE_DERIVATION":
            if "resize_scale" in params:
                spec.delivered_size = _scaled_size(spec.delivered_size, params["resize_scale"])


def _scaled_size(size: tuple[int, int], scale: Any) -> tuple[int, int]:
    if isinstance(scale, (list, tuple)) and len(scale) == 2:
        sx, sy = float(scale[0]), float(scale[1])
    else:
        sx = sy = float(scale)
    return (max(int(round(size[0] * sx)), 8), max(int(round(size[1] * sy)), 8))


def estimate_quality(obs: ObservationResult, *, mask: np.ndarray | None = None
                     ) -> dict[str, Any]:
    """OBS_EST quality block (plan 14.2).  Ground-truth quality is never prefilled."""
    return _estimate_quality(obs, mask=mask)


def commit_observation(store: Any, obs: ObservationResult, *, lineage_id: str,
                       split: str, ancestry: Any = ()) -> Any:
    """Persist one observation under ``ROLE_OBS_RESULT`` (idempotent by interpretation)."""
    payload = observation_to_dict(obs)
    meta = observation_meta(obs)
    return store.commit_asset(
        role=ROLE_OBS_RESULT,
        schema=SCHEMA_OBS,
        unit="mm" if obs.scale_valid else "unknown",
        frame=obs.frame_id,
        payload=payload,
        meta=meta,
        qa={"obs_est_version": OBS_EST_VERSION,
            "route": obs.route,
            "route_status": obs.meta.get("route_status", "OK"),
            "scale_valid": bool(obs.scale_valid)},
        qa_status="QA_PASS",
        ancestry=list(ancestry),
        lineage_id=lineage_id,
        split=split,
    )


def load_observation(store: Any, asset_id: str) -> ObservationResult:
    """Rebuild an observation from its stored payload."""
    record = store.get_asset(asset_id)
    if record.role != ROLE_OBS_RESULT:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"asset {asset_id} has role {record.role!r}, expected "
                          f"{ROLE_OBS_RESULT!r}",
                          stage="observe.load_observation")
    arrays = store.load_arrays(asset_id)
    meta = dict(record.meta)
    for key in ("quality", "backend_report", "meta", "views"):
        if key in meta and not isinstance(meta[key], type(record.meta.get(key))):
            meta[key] = record.meta[key]
    missing = [k for k in ("points", "normals", "point_valid", "normal_valid")
               if k not in arrays]
    if "views" not in meta:
        missing.append("views")
    if missing:
        raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                          f"observation asset {asset_id} payload incomplete: {missing}",
                          stage="observe.load_observation")
    obs = observation_from_dict(meta, arrays)
    if not obs.quality:
        obs.quality = estimate_quality(obs)
    return obs


def scene_from_fragment(fragment: Any, *, surface_tag: np.ndarray | None = None,
                        albedo: np.ndarray | None = None) -> Any:
    """Convenience: build a renderable scene from a fragment (used by tests/tools)."""
    from .render import build_scene

    target = resolve_target(fragment)
    tags = target.surface_tag if surface_tag is None else surface_tag
    return build_scene(target.mesh, surface_tag=tags, face_id=target.face_id,
                       albedo=albedo, name=target.fragment_id)
