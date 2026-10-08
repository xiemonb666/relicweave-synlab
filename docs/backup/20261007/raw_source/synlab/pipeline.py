"""Generation pipeline: one mother per lineage, exactly as plan 22.5 prescribes.

``build_one_mother`` runs the real chain mother 鈫?pattern (frozen before fracture) 鈫?
shared fracture 鈫?clean truth 鈫?physical damage 鈫?observation 鈫?visible truth 鈫?
features/labels/provenance 鈫?atomic commit.  A failure in one mother is isolated: the
other mothers continue, and the failure is recorded in the real denominator
(planned/attempted/accepted/quarantined/failed) instead of being hidden.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from .canonical import code_fingerprint, fingerprint_hash, hash_file, hash_json
from .config import CompiledSpec, compile_spec
from .errors import ErrorCode, SynLabError
from .jobs.scheduler import Scheduler
from .jobs.state import JobState
from .registry import REGISTRY, STATUS_IMPLEMENTED, STATUS_MISSING, load_all
from .roles import (
    FORBIDDEN_FEATURE_FIELDS,
    FRAME_NONE,
    FRAME_WORLD,
    ROLE_CLEAN_TRUTH,
    ROLE_CONTEXT_PACK,
    ROLE_COVERAGE,
    ROLE_FEATURE_BUNDLE,
    ROLE_FRAGMENT_MESH,
    ROLE_LABEL_BUNDLE,
    ROLE_MOTHER_MESH,
    ROLE_OBS_RESULT,
    ROLE_PATTERN_RECIPE,
    ROLE_PHYSICAL_RESULT,
    ROLE_PROVENANCE,
    SCHEMA_CONTEXT,
    SCHEMA_COVERAGE,
    SCHEMA_FEATURE,
    SCHEMA_FRAGMENT,
    SCHEMA_LABELS,
    SCHEMA_MOTHER,
    SCHEMA_OBS,
    SCHEMA_PHYSICAL,
    SCHEMA_PROVENANCE,
    SCHEMA_TRUTH_CLEAN,
    SOURCE_SENSOR_SIM,
    UNIT_MM,
    UNIT_NONE,
)
from .schemas.spec import GenerationSpec
from .schemas.runtime import ORIGIN_INTERFACE
from .seeds import derive_named_rngs, make_rng, seed_ref
from .storage.release import ReleaseManager
from .storage.store import QA_FAIL, QA_PASS, AssetStore


# --------------------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------------------
@dataclass


class LineagePlan:
    lineage_id: str
    split: str
    vessel_id: str
    material_id: str
    pattern_id: str
    layer_combo_id: str | None
    params: dict[str, Any]
    mother_index: int
    event_ids: list[str] = field(default_factory=list)
    #: Per-lineage drawn variables (``configs/a12/diversity.yaml``); ``None`` when the run did not
    #: ask for diversity, which is what keeps every legacy caller bit-for-bit unchanged.  Keys
    #: starting with ``_`` hold live objects (a ``FractureSpec``, an ``ObsSpec``, a rebuilt
    #: ``DiversityConfig``) and are stripped by :func:`_jsonable_variables` before serialisation.
    variables: dict[str, Any] | None = None


@dataclass
class GenerationPlan:
    spec: GenerationSpec
    compiled: CompiledSpec
    lineages: list[LineagePlan]
    spec_hash: str
    code_fingerprint: dict[str, Any]
    backend_fingerprints: dict[str, Any]

    @property
    def job_id(self) -> str:
        from .canonical import job_id_hash

        return "job_" + job_id_hash(
            stage="generate",
            canonical_spec=self.compiled.canonical,
            input_hashes=[self.spec_hash],
            code_fp=fingerprint_hash(self.code_fingerprint),
            backend_fps=self.backend_fingerprints,
            schema_versions={"synlab": "v3", "store": "v1"},
        ).split(":", 1)[-1][:24]

    def as_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for lineage in self.lineages:
            counts[lineage.split] = counts.get(lineage.split, 0) + 1
        return {
            "spec_hash": self.spec_hash,
            "job_id": self.job_id,
            "lineages": len(self.lineages),
            "per_split": counts,
            "code_fingerprint": self.code_fingerprint,
            "backend_fingerprints": self.backend_fingerprints,
        }


def backend_fingerprints() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for module_name in ("trimesh", "manifold3d", "gmsh", "pycolmap", "open3d", "torch", "cv2", "scipy"):
        try:
            module = __import__(module_name)
            version = getattr(module, "__version__", None)
            if version is None:
                try:
                    from importlib.metadata import version as md_version

                    version = md_version(module_name)
                except Exception:
                    version = "unknown"
            out[module_name] = str(version)
        except Exception as exc:  # pragma: no cover - recorded honestly
            out[module_name] = f"MISSING:{type(exc).__name__}"
    return out


def data_semantics() -> dict[str, str]:
    """Semantic versions of the render/damage products of this checkout (one definition).

    A change that alters *what the numbers mean* (the delivered mask channels, the legal
    physical-damage result) is a semantics change, not a bug fix a reader can infer: two batches
    produced under different versions look alike on disk.  The versions are therefore stamped
    into the run record, the coverage ledger and the observation metadata of everything this
    module writes, so the two batches can be separated programmatically
    (docs/a12/data_semantics_versions.md).  The assets produced before this marker exists carry
    no ``data_semantics`` key at all, which is itself the discriminator for the old batch.
    """
    from .observe.render import MASK_SEMANTICS
    from .physical.api import DAMAGE_SEMANTICS

    return {
        "mask_semantics": MASK_SEMANTICS,
        "damage_semantics": DAMAGE_SEMANTICS,
        "subset_instrument": "trimesh.proximity.signed_distance (exact, float64)",
        "defined_in": "docs/a12/data_semantics_versions.md",
    }


#: Semantics tag of the **two-endpoint** observation layer (``docs/a12/training_run.md``
#: section "R2 两端观测").  The declared damage recipe is applied to exactly one fragment of a
#: fracture event, so before this tag existed a lineage carried exactly one observation -- the
#: damaged target -- and the other end of every R2 interface was *modelled but unobserved*.
#: The encoder gates such a fragment out (``z_valid=False``), which made every R2 pair
#: unencodable and left the rank task (weight 1.0) with nothing to score.
#:
#: From this tag on, every non-tiny fragment of the event is observed **with its own
#: geometry**, so both ends of every R2 edge -- and every future confirmed negative candidate
#: -- can be encoded.  The tag is written into the observation metadata, the feature-bundle
#: metadata, the coverage ledger rows and the run record, so a batch produced by the old
#: single-endpoint path (no ``obs_semantics`` key at all) and a batch produced by this path are
#: distinguishable **programmatically** -- never by timestamp or run id.
OBS_SEMANTICS_V2 = "physical_side_v2"
#: ``obs_target_role`` of the endpoint the declared physical damage recipe was applied to.
OBS_ROLE_PHYSICAL_TARGET = "physical_damage_target"
#: ``obs_target_role`` of every other modelled endpoint of the same fracture event.
OBS_ROLE_EVENT_ENDPOINT = "fracture_event_endpoint"

#: Environment switch of the degradation-diversity step: a config path, or ``1``/``true``/``on``
#: for ``configs/a12/degrade_diversity.yaml``.  Unset means the step is skipped, so every
#: existing caller keeps its exact behaviour (the step writes assets, which is never implicit).
DEGRADE_DIVERSITY_ENV = "SYNLAB_DEGRADE_DIVERSITY"

#: Environment switch of the **variable-wiring** step (``configs/a12/diversity.yaml``): a config
#: path, or ``1``/``true``/``on`` for the default path.  Unset means not a single byte of that
#: config is read, so every existing caller keeps its exact behaviour (see
#: :func:`_resolve_diversity`).  Same opt-in discipline as :data:`DEGRADE_DIVERSITY_ENV`, for the
#: same reason: the step changes what the fracture event, the pattern recipe and the observation
#: spec are drawn *from*, and that must never happen behind a caller's back.
DIVERSITY_ENV = "SYNLAB_DIVERSITY"
DIVERSITY_DEFAULT_PATH = Path("configs/a12/diversity.yaml")


# --------------------------------------------------------------------------------------
# Variable wiring (configs/a12/diversity.yaml)
#
# Why this exists, in one paragraph: the reviewed stores drew every lineage's fracture plane
# from the *body hash* (``synlab.fracture.api._default_basis`` does not read the rng at all and
# says so in its own source), every pattern family's parameters from the pydantic field
# defaults (``_build_pattern_recipe`` passes ``params={}``), and every observation from the one
# hardcoded default camera profile (``observe(profile=None)`` -> ``camera_profiles()[1]``), one
# hardcoded light direction, a fixed 4xN view grid and an identity ``ImagingSpec``.  Measured on
# the 61 lineages of ``data/a12*`` that gave exactly **1** working distance, **1** camera
# profile, **1** light mode and **1** imaging setting, which is why this module now samples them
# per lineage from a frozen ``seed64`` sub-stream.
# --------------------------------------------------------------------------------------
def _resolve_diversity(override: bool | str | None) -> dict[str, Any] | None:
    """Resolve ``configs/a12/diversity.yaml``; ``None`` means "do not vary anything".

    ``False`` disables, ``True`` uses :data:`DIVERSITY_DEFAULT_PATH`, a string is a config path,
    and ``None`` falls back to :data:`DIVERSITY_ENV`.  Without an explicit request the config is
    never opened, so a lineage that does not ask for diversity cannot be changed by the file's
    presence.
    """
    if override is False:
        return None
    if override is None:
        raw = os.environ.get(DIVERSITY_ENV, "").strip()
        if not raw or raw.lower() in ("0", "false", "off", "no"):
            return None
        path = DIVERSITY_DEFAULT_PATH if raw.lower() in ("1", "true", "yes", "on") else Path(raw)
    elif override is True:
        path = DIVERSITY_DEFAULT_PATH
    else:
        path = Path(str(override))
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    if not path.exists():
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          f"diversity config not found: {path}",
                          stage="pipeline.diversity.config")
    try:
        import yaml
    except Exception as exc:  # pragma: no cover - pyyaml is a declared dependency
        raise SynLabError(ErrorCode.DEPENDENCY_CAPABILITY_MISSING,
                          f"pyyaml is required to read {path}: {exc}",
                          stage="pipeline.diversity.config") from exc
    raw_doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw_doc, dict):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"{path}: root is not a mapping",
                          stage="pipeline.diversity.config")
    schema = str(raw_doc.get("schema", ""))
    if schema != "synlab.diversity.v1":
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{path}: schema {schema!r} is not 'synlab.diversity.v1'",
                          stage="pipeline.diversity.config")
    if not bool(raw_doc.get("enabled", True)):
        return None
    document = dict(raw_doc)
    document["config_path"] = str(path)
    document["config_hash"] = hash_file(path)
    return document


def _div_block(config: dict[str, Any], *path: str, default: Any = None) -> Any:
    """Read a nested key of the diversity config, returning ``default`` when absent."""
    node: Any = config
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def _div_rng(config: dict[str, Any], lineage_id: str, group: str) -> np.random.Generator:
    """One generator per ``(lineage, group)`` from the config's own master seed."""
    from .seeds import make_rng

    master = int(_div_block(config, "master_seed", default=20261001))
    return make_rng(master, lineage_id, group)


def _div_uniform(rng: np.random.Generator, spec: Any, *, default: tuple[float, float]
                 ) -> float:
    """Draw one scalar from a ``{law: uniform, range: [lo, hi]}`` declaration."""
    lo, hi = default
    if isinstance(spec, dict) and spec.get("range"):
        lo, hi = (float(spec["range"][0]), float(spec["range"][1]))
    elif isinstance(spec, (list, tuple)) and len(spec) == 2:
        lo, hi = (float(spec[0]), float(spec[1]))
    return float(rng.uniform(lo, hi))


def _div_choice(rng: np.random.Generator, choices: Any, *, default: Any = None) -> Any:
    values = list(choices or [])
    if not values:
        return default
    return values[int(rng.integers(0, len(values)))]


def _div_weighted(rng: np.random.Generator, values: Any, weights: Any) -> Any:
    values = list(values or [])
    if not values:
        return None
    if not weights or len(weights) != len(values):
        return values[int(rng.integers(0, len(values)))]
    probs = np.asarray([float(w) for w in weights], dtype=np.float64)
    total = float(probs.sum())
    if total <= 0:
        return values[int(rng.integers(0, len(values)))]
    return values[int(rng.choice(len(values), p=probs / total))]


#: Light-control -> ``LightSpec`` mapping.  The five *modes* are the documented real
#: capture-rig vocabulary (``configs/a12/capture_contract.json`` ->
#: ``lighting.real_capture_light_modes``, count 5).  ``direction`` is the unit vector the light
#: **travels** (``LightSpec.direction``), in the same world frame the renderer uses.  The
#: contract fixes the modes and their physical setup ("left low angle", "left front and lens
#: front polarisers crossed", ...) but declares no numeric vector, so the vectors below are this
#: build's frozen realisation of those setups and are recorded in every observation's metadata
#: instead of being implied.  ``CROSS_POL`` also damps the specular path, which is what crossed
#: polarisers physically do; that is expressed as a lower colour and a higher ambient share.
LIGHT_MODE_SPECS: dict[str, dict[str, Any]] = {
    "WHITE_DIFFUSE": {
        "direction": (-0.35, -0.62, -0.70), "color": (2.35, 2.25, 2.10),
        "ambient": (0.30, 0.30, 0.33),
        "setup": "顶照均匀白光，略前偏，无遮挡",
    },
    "LEFT_GRAZE": {
        "direction": (0.82, -0.42, -0.39), "color": (2.15, 2.08, 1.98),
        "ambient": (0.14, 0.15, 0.17),
        "setup": "左侧低角度掠射，强化口沿与断口起伏",
    },
    "RIGHT_GRAZE": {
        "direction": (-0.82, -0.42, -0.39), "color": (2.15, 2.08, 1.98),
        "ambient": (0.14, 0.15, 0.17),
        "setup": "右侧低角度掠射，验证另一侧的起伏与阴影",
    },
    "CROSS_POL": {
        "direction": (-0.28, -0.50, -0.82), "color": (1.35, 1.30, 1.26),
        "ambient": (0.42, 0.42, 0.44),
        "setup": "灯前与镜头前偏振片正交，压低表面反光",
    },
    "NORMAL_REFLECT": {
        "direction": (0.0, -0.10, -0.995), "color": (1.95, 1.92, 1.88),
        "ambient": (0.22, 0.22, 0.24),
        "setup": "近法向普通白光观察，检查釉面反射",
    },
}


def _div_light(rng: np.random.Generator, config: dict[str, Any]) -> Any:
    """Sample one documented light control and build the real :class:`LightSpec`."""
    from .observe.render import LightSpec

    modes = list(_div_block(config, "observation", "light_modes", default=[])) \
        or list(LIGHT_MODE_SPECS)
    mode = str(_div_choice(rng, modes, default="WHITE_DIFFUSE"))
    spec = LIGHT_MODE_SPECS.get(mode) or LIGHT_MODE_SPECS["WHITE_DIFFUSE"]
    scale_range = _div_block(config, "observation", "light_intensity_jitter",
                             default=[1.0, 1.0])
    scale = float(rng.uniform(float(scale_range[0]), float(scale_range[1])))
    direction = np.asarray(spec["direction"], dtype=np.float64)
    direction /= max(float(np.linalg.norm(direction)), 1e-12)
    return mode, LightSpec(direction=direction,
                           color=np.asarray(spec["color"], dtype=np.float64) * scale,
                           ambient=np.asarray(spec["ambient"], dtype=np.float64) * scale)


def _div_camera(rng: np.random.Generator, config: dict[str, Any]) -> dict[str, Any]:
    """Sample a camera profile at a sampled working distance, inside the declared travel.

    ``synlab.cameras.profiles.transform_profile_u`` is the rig's own definition of a slide
    move: it re-derives ``K`` from the focus group, scales the distortion with the nominal lens
    curve, recomputes the thin-lens depth of field and refuses a position outside the tier's
    declared ``u_travel_mm``.  Sampling a *working distance* therefore means inverting that
    relation (``u = u0 + w0 - w``) and **checking the travel**, not writing a new K: a distance
    no tier can reach is recorded as unreachable and the tier's own limit is used instead.
    """
    from .cameras.api import camera_profiles, transform_profile_u

    profiles = list(camera_profiles())
    if not profiles:
        raise SynLabError(ErrorCode.DEPENDENCY_CAPABILITY_MISSING,
                          "no camera profile is registered",
                          stage="pipeline.diversity.camera")
    source_weights = _div_block(config, "observation", "working_distance_source_weights",
                                default=[0.5, 0.5])
    source = _div_weighted(rng, ["registry_tier", "documented_envelope"], source_weights)
    target: float | None = None
    if source == "documented_envelope":
        envelope = [float(v) for v in _div_block(
            config, "observation", "documented_envelope_mm", default=[])]
        if envelope:
            target = float(_div_choice(rng, envelope))
    base_ids = [str(p.profile_id) for p in profiles]
    wanted_tiers = [str(t) for t in _div_block(config, "observation", "registry_tiers",
                                               default=[])]
    pool = [p for p in profiles if (not wanted_tiers or str(p.tier) in wanted_tiers)] or profiles
    order = [int(i) for i in rng.permutation(len(pool))]
    unreachable: list[dict[str, Any]] = []
    for index in order:
        profile = pool[index]
        u0, w0 = float(profile.u_position_mm), float(profile.working_distance_mm)
        if target is None:
            chosen = profile
            break
        u = u0 + w0 - float(target)
        try:
            chosen = transform_profile_u(profile, u)
        except SynLabError as exc:
            unreachable.append({"profile_id": profile.profile_id, "error": str(exc.code)})
            continue
        break
    else:
        chosen = pool[0]
        target = float(chosen.working_distance_mm)
    return {
        "profile": chosen,
        "source": "documented_envelope" if target is not None else "registry_tier",
        "requested_working_distance_mm": target,
        "realized_working_distance_mm": float(chosen.working_distance_mm),
        "profile_id": str(chosen.profile_id),
        "tier": str(chosen.tier),
        "u_position_mm": float(chosen.u_position_mm),
        "unreachable_tiers": unreachable,
        "registry_profile_ids": base_ids,
    }


def _div_fracture_spec(rng: np.random.Generator, config: dict[str, Any], lineage: Any,
                       mother: Any) -> tuple[Any, dict[str, Any]]:
    """Sample the event variables and build the :class:`FractureSpec` they describe.

    The plane is drawn **here**, not left to ``fracture.api._default_basis``: with
    ``plane_normal=None`` that function ignores the event rng entirely and derives the normal
    from a hash of the body's vertices and faces, so every lineage whose body geometry repeats
    gets the same cut orientation.  ``n_events`` selects the backend (2 -> ``secondary_fracture``,
    the only implemented genuine second break), and ``target_piece_range`` /
    ``secondary_probability`` are recorded as **declared** values: this build's fracture layer
    has no iterate-until-N-pieces implementation, so those two are never reported as realised.
    """
    from .fracture.spec import FractureSpec

    event_cfg = _div_block(config, "event", default={}) or {}
    backends = [str(b) for b in (event_cfg.get("backends")
                                 or ["plane_shared_cut", "rough_shared_cut"])]
    n_events = int(_div_weighted(rng, event_cfg.get("n_events_choices") or [1],
                                 event_cfg.get("n_events_weights")))
    if n_events >= 2:
        backend = "secondary_fracture"
    else:
        backend = str(_div_choice(rng, backends, default="plane_shared_cut"))

    plane_cfg = dict(event_cfg.get("plane") or {})
    z_law = str(plane_cfg.get("z_law", "bounded"))
    z_min = float(plane_cfg.get("z_min", -0.85))
    z_max = float(plane_cfg.get("z_max", 0.85))
    if z_law == "sine_uniform":
        # marginal of the uniform sphere measure over z: z ~ U(-1, 1) *is* that marginal
        z = float(rng.uniform(-1.0, 1.0))
    else:
        z = float(rng.uniform(z_min, z_max))
    azimuth = float(rng.uniform(0.0, 2.0 * np.pi))
    radial = float(np.sqrt(max(0.0, 1.0 - z * z)))
    normal = np.array([radial * np.cos(azimuth), radial * np.sin(azimuth), z], dtype=np.float64)
    normal /= max(float(np.linalg.norm(normal)), 1e-12)

    points = np.asarray(mother.mesh.vertices, dtype=np.float64)
    centroid = points.mean(axis=0)
    radius = float(np.linalg.norm(points - centroid, axis=1).mean())
    offset_cfg = plane_cfg.get("offset_range") or [-0.30, 0.30]
    offset = float(rng.uniform(float(offset_cfg[0]), float(offset_cfg[1])))
    anchor = centroid + normal * (offset * radius)

    rough_cfg = dict(event_cfg.get("rough") or {})
    rms = (float(rng.uniform(*[float(v) for v in rough_cfg.get("target_rms_mm_range",
                                                               [0.02, 0.30])]))
           if backend == "rough_shared_cut" else 0.0)
    n_bands = _div_choice(rng, rough_cfg.get("n_bands_choices") or [1, 2, 3], default=None)
    spec = FractureSpec(
        backend=backend,
        plane_normal=normal,
        plane_point=anchor,
        target_rms_mm=rms,
        n_bands=(int(n_bands) if n_bands is not None else None),
        error_budget_mm=float(rough_cfg.get("error_budget_mm", 0.01)),
    )
    sampled = {
        "backend": backend,
        "n_events": n_events,
        "plane_normal": [float(v) for v in normal],
        "plane_azimuth_deg": float(np.degrees(azimuth)),
        "plane_z": float(z),
        "plane_point": [float(v) for v in anchor],
        "offset_radius_units": offset,
        "body_radius_mm": radius,
        "target_rms_mm": rms,
        "n_bands": None if n_bands is None else int(n_bands),
        "declared_target_piece_range": list(event_cfg.get("target_piece_range") or []),
        "declared_secondary_probability": [
            float(v) for v in (event_cfg.get("secondary_probability_range") or [])],
        "secondary_realised": bool(n_events >= 2),
    }
    return spec, sampled


def _div_pattern_params(rng: np.random.Generator, config: dict[str, Any]) -> dict[str, Any]:
    """Sample the family parameters ``_build_pattern_recipe`` used to leave at their defaults."""
    pattern_cfg = dict(_div_block(config, "pattern", default={}) or {})
    params: dict[str, Any] = {}
    for name, declaration in (pattern_cfg.get("params") or {}).items():
        if not isinstance(declaration, dict):
            continue
        law = str(declaration.get("law", "uniform"))
        if law == "choice":
            params[name] = _div_choice(rng, declaration.get("choices"), default=None)
        else:
            params[name] = _div_uniform(rng, declaration, default=(0.0, 1.0))
    if isinstance(pattern_cfg.get("orientation_deg"), dict):
        params["orientation_deg"] = _div_uniform(
            rng, pattern_cfg["orientation_deg"], default=(0.0, 180.0))
        params.setdefault("tilt_deg", params["orientation_deg"])
    if isinstance(pattern_cfg.get("phase_s_mm"), dict):
        params["phase_s_mm"] = _div_uniform(rng, pattern_cfg["phase_s_mm"],
                                            default=(0.0, 360.0))
    return {k: v for k, v in params.items() if v is not None}


def _div_palette(rng: np.random.Generator, config: dict[str, Any]) -> str | None:
    """Sample a palette id from the pattern registry (never a hardcoded list)."""
    from .patterns.params import PALETTE_IDS

    declaration = _div_block(config, "pattern", "palette", default={}) or {}
    pool = list(PALETTE_IDS)
    if isinstance(declaration, dict) and declaration.get("choices"):
        pool = [str(c) for c in declaration["choices"] if str(c) in PALETTE_IDS] or pool
    return str(_div_choice(rng, pool, default=None)) if pool else None


def _div_observe_spec(rng: np.random.Generator, config: dict[str, Any], lineage: Any,
                      base_spec: Any, camera: dict[str, Any], light: Any
                      ) -> tuple[Any, dict[str, Any]]:
    """Sample the observation variables on top of the configured ``ObsSpec``.

    Everything sampled here is a knob ``ObsSpec``/``ImagingSpec`` already exposes: view count,
    delivered size, render budget, the light spec, and the imaging chain.  The defocus pair is
    derived, not guessed: a sampled focus offset inside the profile's own thin-lens depth of
    field is converted to a circle of confusion (``c = D * |d - d_f| / d_f``) and then to a
    Gaussian PSF sigma in **delivered** pixels through the delivered sampling density
    ``D = f_px / focal_length_mm`` -- the same conversion ``mask_semantics = coc_units_v2``
    documents in :func:`_resolve_observe_spec`.
    """
    import dataclasses

    from .observe.render import RenderSpec
    from .observe.routes import ObsSpec

    obs_cfg = dict(_div_block(config, "observation", default={}) or {})
    view_count = int(_div_choice(rng, obs_cfg.get("view_count_choices") or [base_spec.view_count],
                                 default=base_spec.view_count))
    long_edge = int(_div_choice(rng, obs_cfg.get("delivered_long_edge_choices")
                                or [base_spec.delivered_size[0]],
                                default=base_spec.delivered_size[0]))
    aspect = obs_cfg.get("delivered_aspect") or [4, 3]
    aspect = float(aspect[0]) / float(max(aspect[1], 1))
    delivered = (int(long_edge), max(int(round(long_edge / aspect)), 8))

    profile = camera["profile"]
    focal_px = float(profile.K[0, 0])
    focal_mm = float(profile.meta.get("focal_length_mm") or 0.0)
    f_number = float(profile.f_number)
    dof = tuple(profile.depth_of_field_mm or (0.0, 0.0))
    dof_half = abs(float(dof[1]) - float(dof[0])) / 2.0 if len(dof) == 2 else 0.0
    focus_cfg = dict(obs_cfg.get("focus_error") or {})
    offset_frac = _div_uniform(rng, focus_cfg.get("focus_offset_frac_of_dof"),
                               default=(-0.6, 0.6))
    focus_offset_mm = offset_frac * dof_half
    max_sigma = float(focus_cfg.get("max_defocus_sigma_px", 1.2))
    density = focal_px / focal_mm if focal_mm > 0 else 0.0
    coc_mm = abs(focus_offset_mm) / max(float(profile.working_distance_mm), 1e-9) * focal_mm \
        / max(f_number, 1e-9)
    sigma_px = min(coc_mm * density / 2.0, max_sigma) if density > 0 else 0.0

    exposure_ev = _div_uniform(rng, obs_cfg.get("exposure_ev"), default=(0.0, 0.0))
    read_noise = _div_uniform(rng, obs_cfg.get("read_noise_sigma"), default=(0.0, 0.0))
    gain = _div_uniform(rng, obs_cfg.get("effective_gain"), default=(1.0, 1.0))
    configured_noise = obs_cfg.get("sensor_noise_enabled")
    if configured_noise is not None:
        if type(configured_noise) is not bool:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              "sensor_noise_enabled must be bool or None",
                              stage="pipeline._resolve_observe_spec")
        noise_enabled = configured_noise
    elif base_spec.imaging.sensor_noise_enabled is not None:
        noise_enabled = base_spec.imaging.resolved_sensor_noise_enabled()
    else:
        # A numeric default gain of 1 is not a request to add Poisson noise. Only a
        # declared sensor parameter at this config boundary opts into the sensor model.
        declared_sensor_values = ("effective_gain" in obs_cfg or "read_noise_sigma" in obs_cfg)
        noise_enabled = (True if declared_sensor_values else
                         base_spec.imaging.resolved_sensor_noise_enabled())

    imaging = dataclasses.replace(base_spec.imaging, exposure_ev=float(exposure_ev),
                                  read_noise_sigma=float(read_noise),
                                  effective_gain=float(gain),
                                  sensor_noise_enabled=noise_enabled,
                                  defocus_sigma_px=float(sigma_px))
    declared = float(RenderSpec.coc_px_threshold)
    spec = dataclasses.replace(
        base_spec,
        view_count=view_count,
        delivered_size=delivered,
        max_render_pixels=max(int(delivered[0]) * int(delivered[1]), 1),
        render_spec=dataclasses.replace(base_spec.render_spec,
                                        coc_px_threshold=declared * f_number),
        imaging=imaging,
        light=light,
        master_seed=int(_div_block(config, "master_seed", default=base_spec.master_seed)),
        lineage_id=str(lineage.lineage_id),
    )
    sampled = {
        "view_count": view_count,
        "delivered_size": [int(delivered[0]), int(delivered[1])],
        "light_mode": None if light is None else str(light.__dict__.get("mode", "")) or None,
        "light_direction": None if light is None else [float(v) for v in light.direction],
        "light_color": None if light is None else [float(v) for v in light.color],
        "light_ambient": None if light is None else [float(v) for v in light.ambient],
        "focus_offset_frac_of_dof": offset_frac,
        "focus_offset_mm": focus_offset_mm,
        "profile_dof_mm": [float(dof[0]), float(dof[1])] if len(dof) == 2 else None,
        "defocus_sigma_px": sigma_px,
        "exposure_ev": exposure_ev,
        "read_noise_sigma": read_noise,
        "effective_gain": gain,
        "sensor_noise_enabled": bool(noise_enabled),
        "camera": {k: v for k, v in camera.items() if k != "profile"},
    }
    return spec, sampled


def _div_degradation_config(rng: np.random.Generator, config: dict[str, Any], degrade_cfg: Any
                            ) -> tuple[Any, dict[str, Any]]:
    """Draw a per-lineage axis subset + level subset; level 0 (identity) is never dropped.

    ``configs/a12/degrade_diversity.yaml`` with ``selection: declared`` materialises the same
    nine axes for every lineage (measured: one distinct axis subset over the whole store).  This
    rebuilds a ``DiversityConfig`` whose ``axes`` tuple *is* the sampled subset and whose
    ``selection`` is ``declared``, so the existing, audited materialiser runs unchanged on a
    subset that really differs per lineage.  Sampling is clamped to the operator's own
    ``LEVEL_COUNT`` and refuses to drop level 0.
    """
    import dataclasses

    from .degrade.diversity import AxisSpec
    from .degrade.registry import get_operator

    deg_cfg = dict(_div_block(config, "degradation", default={}) or {})
    pool = [dict(item) for item in (deg_cfg.get("axis_pool") or [])]
    available = []
    for item in pool:
        axis_id = str(item.get("axis_id", ""))
        try:
            operator = get_operator(axis_id)
        except Exception:
            continue
        available.append((axis_id, operator, item))
    if not available or degrade_cfg is None:
        return degrade_cfg, {"axes": [], "levels": {}, "sampled": False}
    lo, hi = [int(v) for v in (deg_cfg.get("axes_per_lineage_range") or [3, 7])]
    want = int(rng.integers(min(lo, len(available)), min(hi, len(available)) + 1))
    order = [int(i) for i in rng.permutation(len(available))][:want]
    lv_lo, lv_hi = [int(v) for v in (deg_cfg.get("levels_per_axis_range") or [2, 5])]
    always_zero = bool(deg_cfg.get("always_include_level_zero", True))
    chosen_axes, levels = [], {}
    for index in sorted(order):
        axis_id, operator, item = available[index]
        count = int(getattr(operator, "LEVEL_COUNT", 5) or 5)
        n_levels = int(rng.integers(max(min(lv_lo, count), 1), min(lv_hi, count) + 1))
        candidates = [lvl for lvl in range(count) if not (always_zero and lvl == 0)]
        picked = [0] if always_zero else []
        extra = [int(i) for i in rng.permutation(len(candidates))][:max(n_levels - len(picked), 0)]
        picked.extend(candidates[i] for i in extra)
        levels[axis_id] = sorted({int(v) for v in picked})
        chosen_axes.append(AxisSpec(
            axis_id=axis_id,
            family=str(item.get("family") or axis_id[0]),
            variant=str(item.get("variant") or ""),
            levels=tuple(levels[axis_id]),
            stage=str(item.get("stage") or operator.STAGE),
            substage=str(getattr(operator, "SUBSTAGE", "") or ""),
            factor_kind=str(getattr(operator, "FACTOR_KIND", "") or ""),
            note=str(item.get("note", "")),
        ))
    per_axis = {axis_id: {"levels": levels[axis_id]} for axis_id in sorted(levels)}
    sampled = {
        "sampled": True,
        "declared_axes": [a.axis_id for a in chosen_axes],
        "levels": levels,
        "axis_count": len(chosen_axes),
        "level_combos": int(np.prod([len(v) for v in levels.values()])) if levels else 0,
        "materialised_axes": [a.axis_id for a in chosen_axes],
        "materialised_levels_total": int(sum(len(v) for v in levels.values())),
        "always_include_level_zero": always_zero,
    }
    rebuilt = dataclasses.replace(degrade_cfg, axes=tuple(chosen_axes), selection="declared",
                                  max_axes_per_lineage=max(len(chosen_axes), 1))
    return rebuilt, sampled


def _div_sample_static(config: dict[str, Any], lineage: Any, *, base_observe_spec: Any,
                       degrade_cfg: Any) -> dict[str, Any]:
    """The part of the variable table that does not need the mother geometry.

    Everything except the fracture plane can be drawn during planning: the pattern parameters,
    the camera/light choice, the observation spec and the degradation axis subset all depend on
    the *lineage* only.  The plane additionally needs the body's vertex cloud (its centroid and
    equivalent radius), so it is drawn in :func:`build_one_mother` from the same frozen
    ``event`` sub-stream -- see :func:`_div_fracture_spec`.
    """
    pattern_rng = _div_rng(config, lineage.lineage_id, "pattern")
    camera_rng = _div_rng(config, lineage.lineage_id, "camera")
    light_rng = _div_rng(config, lineage.lineage_id, "light")
    diversity_rng = _div_rng(config, lineage.lineage_id, "diversity")

    pattern_params = _div_pattern_params(pattern_rng, config)
    palette = _div_palette(pattern_rng, config)
    camera = _div_camera(camera_rng, config)
    light_mode, light = _div_light(light_rng, config)
    observe_spec, obs_vars = _div_observe_spec(camera_rng, config, lineage, base_observe_spec,
                                               camera, light)
    obs_vars["light_mode"] = light_mode
    rebuilt_degrade, degrade_vars = _div_degradation_config(diversity_rng, config, degrade_cfg)
    return {
        "schema": "synlab.diversity.variables.v1",
        "lineage_id": lineage.lineage_id,
        "master_seed": int(_div_block(config, "master_seed", default=0)),
        "config_hash": config.get("config_hash"),
        "event": None,
        "pattern": {"params": pattern_params, "palette_id": palette},
        "observation": obs_vars,
        "degradation": degrade_vars,
        "_observe_spec": observe_spec,
        "_degrade_config": rebuilt_degrade,
    }


def _div_sample_lineage(config: dict[str, Any], lineage: Any, mother: Any, *,
                        base_observe_spec: Any, degrade_cfg: Any) -> dict[str, Any]:
    """The full per-lineage variable table (one frozen sub-stream per group)."""
    table = _div_sample_static(config, lineage, base_observe_spec=base_observe_spec,
                              degrade_cfg=degrade_cfg)
    fracture_spec, event_vars = _div_fracture_spec(
        _div_rng(config, lineage.lineage_id, "event"), config, lineage, mother)
    table["event"] = event_vars
    table["_fracture_spec"] = fracture_spec
    return table


def _jsonable_variables(variables: dict[str, Any]) -> dict[str, Any]:
    """Strip the live objects: only the *drawn values* are serialisable and comparable."""
    return {key: value for key, value in variables.items() if not key.startswith("_")}


def _resolve_degrade_diversity(override: bool | str | None) -> Any:
    """Resolve the degradation-diversity config; ``None`` means "skip this step".

    Opt-in on purpose.  ``False`` disables, ``True`` uses the default config, a string is a
    config path, and ``None`` falls back to :data:`DEGRADE_DIVERSITY_ENV`.  Without an explicit
    request **no config is read at all**, so a lineage that does not ask for degradation
    diversity cannot be changed by the presence of the config file.
    """
    from .degrade.diversity import DEFAULT_CONFIG_PATH, load_diversity_config

    if override is False:
        return None
    if override is None:
        raw = os.environ.get(DEGRADE_DIVERSITY_ENV, "").strip()
        if not raw or raw.lower() in ("0", "false", "off", "no"):
            return None
        path: Any = DEFAULT_CONFIG_PATH if raw.lower() in ("1", "true", "yes", "on") else raw
    elif override is True:
        path = DEFAULT_CONFIG_PATH
    else:
        path = override
    config = load_diversity_config(path)
    return config if config.enabled else None


def _materialize_degrade_diversity(store: AssetStore, *, plan: GenerationPlan,
                                   lineage: "LineagePlan", degrade_cfg: Any, observation: Any,
                                   target_fragment: Any, fragment_asset_of: dict[str, Any],
                                   run_id: str | None = None,
                                   observation_asset_id: str = "") -> dict[str, Any]:
    """Step 9: materialise the configured degradation axes for *this* lineage's own assets.

    The sources are the lineage's own committed assets (the target fragment mesh for the
    physical family, the primary observation for the image/geometry/estimate families), so the
    variants are degradations of real lineage data rather than of a probe fixture.  The report
    is flushed to ``<store>/reports/degrade_diversity/<lineage>.json`` after every level.
    """
    from .degrade.diversity import (commit_observation_sources, load_p_family_source,
                                    materialize_lineage_diversity)

    fragment_id = str(getattr(target_fragment, "fragment_id", "") or "")
    sources: dict[str, Any] = {}
    fragment_asset = fragment_asset_of.get(fragment_id)
    if fragment_asset is not None:
        sources["P"] = load_p_family_source(
            store, fragment_asset.asset_id, fragment_id=fragment_id,
            material_id=lineage.material_id, mother_id=lineage.lineage_id,
            master_seed=plan.spec.master_seed, lineage_id=lineage.lineage_id)
    sources.update(commit_observation_sources(
        store, observation, lineage_id=lineage.lineage_id, split=lineage.split,
        material_id=lineage.material_id, mother_id=lineage.lineage_id,
        master_seed=plan.spec.master_seed, data_semantics=data_semantics(),
        observation_asset_id=observation_asset_id))
    report_path = store.root / "reports" / "degrade_diversity" / f"{lineage.lineage_id}.json"
    report = materialize_lineage_diversity(
        store, config=degrade_cfg, sources=sources, lineage_id=lineage.lineage_id,
        split=lineage.split, master_seed=plan.spec.master_seed,
        lineage_index=lineage.mother_index, run_id=run_id, data_semantics=data_semantics(),
        progress_path=report_path, mother_id=lineage.lineage_id, fragment_id=fragment_id)
    report["report_ref"] = str(report_path)
    return report


def _degrade_diversity_totals(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Run-level denominator of step 9 (planned vs realised axes/levels; nothing dropped)."""
    summaries = [dict(row.get("degrade_diversity") or {}) for row in rows]
    summaries = [item for item in summaries if item]
    keys = ("axes_planned", "axes_ok", "axes_na", "axes_failed", "levels_planned", "levels_ok",
            "levels_identity", "levels_na", "levels_failed", "variant_assets",
            "identity_reference_ok", "identity_bytes_unchanged", "bytes")
    totals: dict[str, Any] = {f"lineages": len(summaries)}
    for key in keys:
        totals[key] = int(sum(int(item.get(key, 0) or 0) for item in summaries))
    totals["basis_shared_per_axis"] = all(bool(item.get("basis_shared_per_axis"))
                                          for item in summaries) if summaries else None
    return totals


def plan_generation(spec: GenerationSpec, *, max_mothers: int | None = None,
                    diversity: dict[str, Any] | None = None,
                    store_root: str | Path | None = None) -> GenerationPlan:
    """Split lineages *before* generation, then sample feasible parameter combinations.

    ``diversity`` is the resolved ``configs/a12/diversity.yaml`` mapping (see
    :func:`_resolve_diversity`).  When it is ``None`` -- the default for every legacy caller --
    not one variable is drawn, ``LineagePlan.variables`` stays ``None``, and the plan is
    bit-for-bit what it was before this parameter existed.
    """
    load_all()
    compiled = compile_spec(spec)
    if compiled.errors:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "; ".join(compiled.errors), stage="pipeline.plan")
    missing = [e.id for e in REGISTRY.list() if e.status == STATUS_MISSING]
    target = int(spec.dataset.target_mothers)
    if max_mothers is not None:
        target = min(target, int(max_mothers))
    rng = derive_named_rngs(spec.master_seed, "planning")["sampler"]
    fractions = spec.dataset.shape_lineage_split.normalized()
    splits = ("train", "dev", "confirm")
    cumulative = np.cumsum(fractions)
    vessels = [v for v in spec.dataset.vessel_ids if REGISTRY.has("vessel", v)] or list(spec.dataset.vessel_ids)
    materials = list(spec.dataset.material_ids)
    patterns = list(spec.dataset.pattern_ids)
    layers = list(spec.dataset.layer_combo_ids)

    # Balanced coverage: enumerate every (vessel, material, pattern[, layer]) combination and
    # walk it in a deterministic frozen order, so ANY prefix of N mothers covers N distinct
    # combinations. The previous index//stride scheme only changed the pattern every
    # |vessels|*|materials| mothers (288), which made pattern coverage unreachable in a 100-200
    # mother batch (plan 1.2 requires 16 pattern families and >=12 vessels in the pilot).
    #
    # The order is drawn ONCE (a per-mother re-draw made the prefix property false and could
    # repeat one combination), and the parameter sampler is handed the *picked* vessel sequence:
    # ``_sample_parameter_sets`` hands out ``vessels[index % len(vessels)]``, so passing the
    # catalog order while the lineages walk the permuted order gave each mother another vessel's
    # parameters (measured: 3/4 lineages, e.g. V02 receiving V01's ``depth_ratio``/``rim_flare``
    # -> MOTHER_INVALID).  See data/a12/reports/plan_param_mapping_probe.json.
    combos = [
        (v, m, pt, ly)
        for v in vessels
        for m in materials
        for pt in patterns
        for ly in (layers if layers else [None])
    ]
    order = [int(i) for i in rng.permutation(len(combos))]
    picked = [combos[order[index % len(combos)]] for index in range(target)]

    param_samples = _sample_parameter_sets([combo[0] for combo in picked], target, rng, compiled)
    # The variable table is drawn per lineage from that lineage's own frozen sub-streams, so the
    # order in which lineages are generated can never change what a given lineage draws.
    div_degrade_cfg = None
    div_base_observe = None
    if diversity is not None:
        # ``_resolve_observe_spec`` is a pure projection of the generation config onto an
        # ``ObsSpec``: it never touches ``store``.  It is handed ``None`` so that planning a
        # diverse run cannot create a store as a side effect of *planning* one.
        div_degrade_cfg = _resolve_degrade_diversity(
            diversity.get("_degrade_diversity") if isinstance(diversity, dict) else None)
        div_base_observe = _resolve_observe_spec(spec, None)
    lineages: list[LineagePlan] = []
    for index in range(target):
        draw = float(rng.random())
        split = splits[int(np.searchsorted(cumulative, draw, side="right"))] if draw < 1.0 else "confirm"
        vessel, material, pattern, layer = picked[index]
        lineage_id = f"LIN{index:04d}_{vessel}_{material}_{pattern}"
        variables = None
        if diversity is not None:
            placeholder = LineagePlan(lineage_id=lineage_id, split=split, vessel_id=vessel,
                                      material_id=material, pattern_id=pattern,
                                      layer_combo_id=layer, params={}, mother_index=index)
            variables = _div_sample_static(diversity, placeholder,
                                           base_observe_spec=div_base_observe,
                                           degrade_cfg=div_degrade_cfg)
        lineages.append(LineagePlan(
            lineage_id=lineage_id,
            split=split,
            vessel_id=vessel,
            material_id=material,
            pattern_id=pattern,
            layer_combo_id=layer,
            params=param_samples[index] if index < len(param_samples) else {},
            mother_index=index,
            event_ids=[f"{lineage_id}_E01"],
            variables=variables,
        ))
    return GenerationPlan(
        spec=spec, compiled=compiled, lineages=lineages, spec_hash=compiled.spec_hash,
        code_fingerprint=code_fingerprint(Path(__file__).resolve().parents[1]),
        backend_fingerprints=backend_fingerprints(),
    )


def _sample_parameter_sets(vessels: list[str], count: int, rng: np.random.Generator,
                           compiled: CompiledSpec) -> list[dict[str, Any]]:
    """Sample one parameter set per lineage with **each lineage's own vessel schema**.

    The sampler is called per vessel id (``synlab.mothers.api.sample_parameters`` draws from
    the registered pydantic model of *that* vessel and returns only the fields that model
    declares), and the handout walks the same ``vessels`` sequence the lineages use, so
    lineage *i* always receives parameters that belong to the vessel lineage *i* builds.
    Passing the catalogue order while the lineages walk a permuted order is exactly the
    cross-vessel defect that produced ``MOTHER_INVALID`` (V12 received ``depth_ratio`` /
    ``rim_flare``, V07 received ``with_handle`` - see
    ``data/a12/reports/plan_param_mapping_probe.json``), so the picked sequence must stay the
    only source of the vessel order here.

    Every handed-out dictionary is then verified against its vessel's own model
    (:func:`synlab.mothers.api.params_model_ok`); a failure raises ``MOTHER_INVALID`` with the
    offending fields instead of being replaced by a default dictionary, and the vessel
    announcement is never silently dropped (no ``try/except`` around the sampler).
    """
    from .mothers.api import declared_fields, declared_only, params_model_ok, sample_parameters

    counts: dict[str, int] = {}
    for index in range(count):
        vessel = vessels[index % len(vessels)]
        counts[vessel] = counts.get(vessel, 0) + 1
    per_vessel: dict[str, list[dict[str, Any]]] = {
        vessel: list(sample_parameters(vessel, n, rng)) for vessel, n in counts.items()
    }
    out: list[dict[str, Any]] = []
    cursors = {vessel: 0 for vessel in per_vessel}
    for index in range(count):
        vessel = vessels[index % len(vessels)]
        items = per_vessel.get(vessel) or []
        if not items:  # pragma: no cover - sample_parameters raises instead of returning none
            raise SynLabError(
                ErrorCode.MOTHER_INVALID,
                f"{vessel}: the parameter sampler returned no set for a planned mother",
                stage="pipeline.plan",
                measurements={"lineage_index": index, "planned_for_vessel": counts.get(vessel)},
            )
        cursor = cursors.get(vessel, 0)
        params = declared_only(vessel, items[cursor % len(items)])
        ok, why = params_model_ok(vessel, params)
        if not ok:
            raise SynLabError(
                ErrorCode.MOTHER_INVALID,
                f"{vessel}: sampled parameters do not validate against the vessel's own model: "
                f"{why}",
                stage="pipeline.plan",
                measurements={"lineage_index": index, "vessel_id": vessel,
                              "params": params,
                              "declared_fields": sorted(declared_fields(vessel)),
                              "note": "the field list of another vessel is never substituted "
                                      "here; the draw is rejected with its model error"},
            )
        out.append(params)
        cursors[vessel] = cursor + 1
    return out


# --------------------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------------------
def run_generation(spec: GenerationSpec, *, store_root: str | Path = "data/a12",
                   resume: bool = False, max_mothers: int | None = None,
                   progress: Callable[[dict[str, Any]], None] | None = None,
                   degrade_diversity: bool | str | None = None) -> dict[str, Any]:
    store = AssetStore(store_root)
    plan = plan_generation(spec, max_mothers=max_mothers)
    degrade_cfg = _resolve_degrade_diversity(degrade_diversity)
    scheduler = Scheduler(store)
    run_id = f"run_{plan.job_id.split('_', 1)[-1][:16]}"
    store.create_run(run_id, plan.spec_hash, scope=spec.data_scope.value, profile=spec.release_profile.value,
                     meta={"plan": plan.as_dict(), "spec": plan.compiled.expanded,
                           "data_semantics": data_semantics(),
                           "obs_semantics": OBS_SEMANTICS_V2})
    plan_path = store.root / "reports" / f"run_spec_{run_id}.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps({**plan.as_dict(), "plan": [vars(l) for l in plan.lineages]},
                                    ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    accepted = 0
    attempted = 0
    start = time.time()

    def _ledger(seconds: float, *, complete: bool) -> dict[str, Any]:
        return {
            "schema": SCHEMA_COVERAGE,
            "run_id": run_id,
            "spec_hash": plan.spec_hash,
            "planned": len(plan.lineages),
            "attempted": attempted,
            "accepted": accepted,
            "quarantined": len([r for r in rows if r.get("quarantined")]),
            "failed": len(failures),
            "per_split": _counts(l.split for l in plan.lineages),
            "vessels": sorted({l.vessel_id for l in plan.lineages}),
            "materials": sorted({l.material_id for l in plan.lineages}),
            "patterns": sorted({l.pattern_id for l in plan.lineages}),
            "layer_combos": sorted({l.layer_combo_id for l in plan.lineages
                                    if l.layer_combo_id}),
            "fracture_backend": spec.fracture.backend,
            "data_semantics": data_semantics(),
            "obs_semantics": OBS_SEMANTICS_V2,
            "degrade_diversity": _degrade_diversity_totals(rows),
            "seconds": seconds,
            "complete": bool(complete),
            "rows": rows,
            "failures": failures,
        }

    for lineage in plan.lineages:
        attempted += 1
        outcome = build_one_mother(plan, lineage, store, run_id=run_id,
                                   degrade_cfg=degrade_cfg)
        rows.append(outcome["coverage_row"])
        if outcome["ok"]:
            accepted += 1
        else:
            failures.append({"lineage_id": lineage.lineage_id, "error": outcome["error"]})
        if progress:
            progress({"lineage_id": lineage.lineage_id, "ok": outcome["ok"],
                      "accepted": accepted, "attempted": attempted})
        # flush the honest denominator to disk after *every* mother: on this host a long
        # generation can be killed without a traceback, and a lost ledger would hide which
        # lineage was in flight.
        _write_coverage(store, _ledger(time.time() - start, complete=False))
    duration = time.time() - start

    coverage = _ledger(duration, complete=True)
    _write_coverage(store, coverage)
    store.set_run_status(run_id, "QA_PASSED" if accepted else "FAILED",
                         meta={"accepted": accepted, "attempted": attempted})
    report = {
        "run_id": run_id,
        "job_id": plan.job_id,
        "spec_hash": plan.spec_hash,
        "planned": len(plan.lineages),
        "attempted": attempted,
        "accepted": accepted,
        "failed": len(failures),
        "seconds": duration,
        "failures": failures[:20],
        "coverage_ref": str(store.root / "reports" / "coverage.json"),
        "run_spec_ref": str(plan_path),
        "errors": [f["error"] for f in failures[:20]],
        "degrade_diversity": coverage.get("degrade_diversity"),
        "code_fingerprint": plan.code_fingerprint,
    }
    (store.root / "reports" / f"generation_{run_id}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    coverage_summary = {k: v for k, v in coverage.items() if k not in ("rows", "failures")}
    (store.root / "reports" / "coverage.json").write_text(
        json.dumps(coverage_summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report


def _counts(items: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out


def _write_coverage(store: AssetStore, coverage: dict[str, Any]) -> None:
    rows = coverage.get("rows") or []
    if not rows:
        return
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.Table.from_pylist([_flatten(row) for row in rows])
        pq.write_table(table, store.root / "reports" / "coverage.parquet")
    except Exception:
        pass
    (store.root / "reports" / "coverage_rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _flatten(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                out[f"{key}_{sub_key}"] = sub_value if not isinstance(sub_value, (dict, list)) else json.dumps(sub_value, ensure_ascii=False)
        elif isinstance(value, (list, tuple)):
            out[key] = json.dumps(list(value), ensure_ascii=False)
        else:
            out[key] = value
    return out


# --------------------------------------------------------------------------------------
# Simulated excavation context (plan t088 / D3 / D5)
# --------------------------------------------------------------------------------------
#: ``t088`` gives exactly one sentence for this modality: "模拟出土区、层位、袋号/坑位等可控元数据".
#: It also fixes the two boundaries this module obeys:
#:
#: * the document says **模拟** (simulated).  Every pack therefore carries ``simulated: true``
#:   at the top level and ``simulated_*`` operator/session fields, so no consumer can mistake
#:   these strings for a real archaeological record (p1146: "坑位/层位只有真实可信字段时才使用").
#: * the synthetic side's D23 form ("有缺失冲突和噪声的字段；**不能等价母体 ID**", t101) is
#:   honoured negatively: the context ids are generated *downstream* of the lineage id, and no
#:   context id may be derived from, or reconstruct, a lineage/mother id.  ``rng`` is seeded from
#:   ``master_seed`` + the lineage id but the emitted values only pick vocabulary entries, and
#:   ``assert_context_is_not_answer_bearing`` refuses a pack that names a lineage, an R2
#:   neighbour or a lineage-derived hash.
#:
#: Grid references are dated archaeological grid labels, not a claim about a real site.
CONTEXT_VOCABULARY: dict[str, Any] = {
    "excavation_areas": (
        # area id -> (grid ref, pit ref, institution code, unit code)
        ("EXA-A", "T0505", "PIT-3", "SYN", "U2"),
        ("EXA-B", "T0607", "PIT-1", "SYN", "U2"),
        ("EXA-C", "T0711", "PIT-4", "SYN", "U1"),
    ),
    "strata": (
        # stratum id -> depth below the site datum, in mm (a simulated reading)
        ("STR-02", 180),
        ("STR-03", 320),
        ("STR-04", 450),
        ("STR-05", 610),
    ),
    "scale_references": (
        # kind, size in mm, how it appears in the image
        ("steel_ruler", 150.0, "in_frame_left_edge_vertical"),
        ("apriltag_36h11", 36.0, "flat_on_tray_beside_sherd"),
        ("reference_sphere", 12.0, "on_tray_upper_right"),
        ("calibration_board_chessboard", 60.0, "under_sample_corner_visible"),
    ),
    "sites": (("SYN-SITE-01", "simulated_reference_site"),),
    "operators": (("OP-SIM-01",), ("OP-SIM-02",), ("OP-SIM-03",)),
    "note_template": (
        "SIMULATED context, not an archaeological record: synthetic sherd set "
        "{lineage_kind} registered under a generated bag id; no excavation took place."
    ),
}

#: Field names a context pack may never carry (they are answer-side or identity-side).
_CONTEXT_FORBIDDEN_FIELDS: frozenset[str] = frozenset({
    "lineage_id", "mother_id", "fragment_id", "event_id", "split", "seed", "seed_ref",
    "historical_R2", "mate_present", "relation", "relations", "interface_id", "kind",
})


def assert_context_is_not_answer_bearing(context: Mapping[str, Any]) -> None:
    """Refuse a context pack that carries an answer-side or identity-side field.

    The check walks the whole nested document, so a field cannot be hidden one level down.  It
    is called on every pack this module emits; a violation raises instead of being committed.
    """
    offenders: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if str(key) in _CONTEXT_FORBIDDEN_FIELDS:
                    offenders.append(str(key))
                walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(context)
    if context.get("simulated") is not True:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            "a context pack must be marked simulated=true: the fields are generated, not "
            "observed at a real excavation (plan t088)",
            stage="pipeline.context",
        )
    if offenders:
        raise SynLabError(
            ErrorCode.LEAKAGE_DETECTED,
            f"simulated context pack carries answer-side fields: {sorted(set(offenders))}",
            stage="pipeline.context",
            evidence_refs=sorted(set(offenders)),
        )


@dataclass
class ContextPlan:
    """The simulated excavation context of one batch (all values deterministic from the seed)."""

    pack_id: str
    context_id: str
    batch_id: str
    bag_id: str
    pit_id: str
    site_id: str
    institution_id: str
    excavation_area_id: str
    grid_ref: str
    unit_code: str
    stratum_id: str
    stratum_depth_mm: int
    session_id: str
    operator_id: str
    captured_at: str
    site_notes: str
    scale_reference: dict[str, Any]
    batch_size_target: int
    batch_rule: str
    batch_index: int = 0
    simulator: str = "synlab.pipeline.simulated_excavation_context"
    seed_path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_CONTEXT,
            "simulated": True,
            "pack_id": self.pack_id,
            "context_id": self.context_id,
            "batch_id": self.batch_id,
            "batch_index": int(self.batch_index),
            "bag_id": self.bag_id,
            "pit_id": self.pit_id,
            "site_id": self.site_id,
            "institution_id": self.institution_id,
            "excavation_area_id": self.excavation_area_id,
            "grid_ref": self.grid_ref,
            "unit_code": self.unit_code,
            "stratum_id": self.stratum_id,
            "stratum_depth_mm": int(self.stratum_depth_mm),
            "session_id": self.session_id,
            "operator_id": self.operator_id,
            "captured_at": self.captured_at,
            "site_notes": self.site_notes,
            "scale_reference": dict(self.scale_reference),
        }


def plan_context(master_seed: int, lineage: LineagePlan, *, divisor: int = 0,
                 batch_slot: int | None = None) -> ContextPlan:
    """Deterministically plan one batch's simulated excavation context.

    Every choice is a pure function of ``master_seed`` and the lineage's plan row (its index and
    id), so the same spec replays to the same context.  ``divisor`` is the *declared* target
    batch size: ``0`` puts a whole lineage in one batch (the default), a positive value splits a
    lineage into consecutive batches of that size so that "same batch" is a real, non-trivial
    grouping for the retrieval scope.  ``batch_slot`` names which of those batches this plan is
    for (``None`` derives it from the lineage's plan index).  Nothing here reads a fracture, an
    interface or a relation.
    """
    rng = make_rng(int(master_seed), lineage.lineage_id, "context")
    area = CONTEXT_VOCABULARY["excavation_areas"][
        int(rng.integers(0, len(CONTEXT_VOCABULARY["excavation_areas"])))]
    stratum = CONTEXT_VOCABULARY["strata"][
        int(rng.integers(0, len(CONTEXT_VOCABULARY["strata"])))]
    scale = CONTEXT_VOCABULARY["scale_references"][
        int(rng.integers(0, len(CONTEXT_VOCABULARY["scale_references"])))]
    site_id, site_kind = CONTEXT_VOCABULARY["sites"][0]
    operator_id = CONTEXT_VOCABULARY["operators"][
        int(rng.integers(0, len(CONTEXT_VOCABULARY["operators"])))][0]

    index = int(lineage.mother_index)
    batch_index = (index // int(divisor)) if divisor > 0 else 0
    if batch_slot is not None:
        batch_index = int(batch_slot)
    bag_id = f"BAG-{lineage.lineage_id}"
    # the batch name: ``BAG-<lineage>`` when the whole lineage is one bag (divisor 0), and
    # ``BAG-<lineage>#b<slot>`` when the lineage is split -- so ``context_id`` (pit|stratum|batch)
    # identifies exactly one pack, and a fragment's context_id resolves to a single pack.
    batch_id = bag_id if divisor <= 0 else f"{bag_id}#b{batch_index + 1:02d}"
    pit_id, grid_ref, institution_id, unit_code = area[2], area[1], area[3], area[4]
    context_id = f"{pit_id}|{stratum[0]}|{batch_id}"
    session_id = f"SES-{lineage.lineage_id}"
    # A simulated capture timestamp: a deterministic date in the near past, never "now" (a real
    # timestamp would be indistinguishable from a real record's own clock).
    day = 1 + int(rng.integers(0, 27))
    hour = 8 + int(rng.integers(0, 9))
    captured_at = f"2026-03-{day:02d}T{hour:02d}:{int(rng.integers(0, 60)):02d}:00+00:00"
    target = max(int(divisor), 0)
    return ContextPlan(
        pack_id=f"ctx_{lineage.lineage_id}"
                 + ("" if divisor <= 0 else f"#b{batch_index + 1:02d}"),
        context_id=context_id,
        batch_id=batch_id,
        bag_id=bag_id,
        pit_id=pit_id,
        site_id=site_id,
        institution_id=institution_id,
        excavation_area_id=area[0],
        grid_ref=grid_ref,
        unit_code=unit_code,
        stratum_id=stratum[0],
        stratum_depth_mm=int(stratum[1]),
        session_id=session_id,
        operator_id=operator_id,
        captured_at=captured_at,
        site_notes=CONTEXT_VOCABULARY["note_template"].format(lineage_kind=site_kind),
        scale_reference={
            # named explicitly: the leakage gate forbids a bare "kind" key anywhere in the pack
            "scale_reference_kind": scale[0],
            "size_mm": float(scale[1]),
            "appearance": scale[2],
            "simulated": True,
            "placed_by": "simulator",
        },
        batch_size_target=target,
        batch_index=int(batch_index),
        batch_rule=("whole lineage is one bag when batch_size_target == 0, otherwise "
                    "consecutive batches of batch_size_target fragments"),
        seed_path=seed_ref(int(master_seed), lineage.lineage_id, "context"),
    )


def batch_slot_layout(master_seed: int, lineage: LineagePlan, fragment_ids: Sequence[str],
                      *, divisor: int) -> dict[str, ContextPlan]:
    """Map every fragment id of one event to the context pack of its batch.

    The layout is fixed *before* any of those assets is committed: the fragment ids are sorted
    (a stable key, not insertion order) and sliced into consecutive batches of ``divisor``
    fragments -- or one batch when ``divisor <= 0``.  The same layout decides
    ``meta.context_id`` on every asset of a fragment and the batch membership of the pack, so the
    two can never disagree.
    """
    ordered = sorted(str(fid) for fid in fragment_ids)
    layout: dict[str, ContextPlan] = {}
    if divisor <= 0:
        single = plan_context(master_seed, lineage, divisor=0)
        for fragment_id in ordered:
            layout[fragment_id] = single
        return layout
    for position, fragment_id in enumerate(ordered):
        layout[fragment_id] = plan_context(master_seed, lineage, divisor=int(divisor),
                                           batch_slot=position // int(divisor))
    return layout


def context_identity_fields(context: ContextPlan) -> dict[str, str]:
    """The identity written into the metadata of the fragments/observations/labels of a batch."""

    return {
        "context_id": context.context_id,
        "batch_id": context.batch_id,
        "context": {
            "schema": SCHEMA_CONTEXT,
            "simulated": True,
            "bag_id": context.bag_id,
            "pit_id": context.pit_id,
            "stratum_id": context.stratum_id,
            "grid_ref": context.grid_ref,
            "excavation_area_id": context.excavation_area_id,
        },
    }


def _with_context(context: ContextPlan, meta: dict[str, Any]) -> dict[str, Any]:
    """Merge the batch identity into one asset's metadata and return it."""
    return {**meta, **context_identity_fields(context)}


def stamp_context(target: Any, context: ContextPlan) -> Any:
    """Write the batch identity into a truth/observation object's own ``meta`` and return it.

    ``truth.commit_truth`` / ``observe.commit_observation`` build the committed metadata from the
    object they are given (``truth.api._payload_of`` copies selected ``obj.meta`` keys), so the
    batch identity is attached at the object, before the commit, instead of through a second
    write path.  The object's ``meta`` mapping is a plain dict on every layer this pipeline
    produces (``CleanTruth``/``PhysicalTruth``/``VisibleLabels``/``ObservationResult``); an object
    whose metadata is not a mutable mapping is returned untouched rather than raising mid-chain.
    """
    meta = getattr(target, "meta", None)
    if isinstance(meta, dict):
        meta.update(context_identity_fields(context))
    return target


def build_context_pack(store: AssetStore, plan: GenerationPlan, lineage: LineagePlan,
                       context: ContextPlan, *, batches: Sequence[Mapping[str, Any]],
                       run_id: str | None = None) -> tuple[Any, dict[str, Any]]:
    """Commit one simulated context pack for a batch and return (record, pack document).

    ``batches`` is the measured membership of the batch: one row per fragment of this lineage's
    event with its fragmentation role, its fragment id, a one-line provenance note and whether
    the fragment carries a delivered observation.  The rows are read back from the *committed*
    assets, so the pack describes what the store really holds.
    """
    fragments = [dict(row) for row in batches]
    coexistents = [
        {
            "context_object_kind": "fragment",
            "id": str(row["fragment_id"]),
            "role": str(row.get("role", "event_endpoint")),
            "count": 1,
            "has_observation": bool(row.get("has_observation", False)),
            "geometry_asset": str(row.get("geometry_asset", "")),
            "observation_asset": str(row.get("observation_asset", "")),
            "note": str(row.get("note", "")),
        }
        for row in fragments
    ]
    document = {
        **context.as_dict(),
        "role_note": ("this asset is the *simulated* excavation context of one batch; it is "
                      "generated, not recorded"),
        "batch_size": len(fragments),
        "batch_rule": context.batch_rule,
        "batch_size_target": context.batch_size_target,
        "coexistents": coexistents,
        "coexistent_counts": {
            "fragments": len(fragments),
            "with_observation": sum(1 for row in fragments if row.get("has_observation")),
            "vessels": 1,          # one mother per lineage: the batch holds one vessel's sherds
            "others": 0,
        },
        "coexistence_scope": ("every fragment of this lineage's fracture event that the store "
                              "holds: the same-batch candidate scope of a query"),
        "lineage_scope": ("one batch = one lineage's event (see batch_rule); a cross-lineage "
                          "batch is not produced at this scale"),
        "site_id_kind": CONTEXT_VOCABULARY["sites"][0][1],
        "institution_note": ("SYN is this repository's own synthetic institution code, not a real "
                             "excavation institution"),
        "simulator_revision": {"pipeline": "synlab.pipeline", "role": ROLE_CONTEXT_PACK,
                               "schema": SCHEMA_CONTEXT},
        "master_seed_path": context.seed_path,
        "source_kind": SOURCE_SENSOR_SIM,
        "data_semantics": data_semantics(),
        "run_id": run_id,
    }
    assert_context_is_not_answer_bearing(document)
    record = store.commit_asset(
        role=ROLE_CONTEXT_PACK,
        schema=SCHEMA_CONTEXT,
        unit=UNIT_NONE,
        frame=FRAME_NONE,
        payload={},
        meta=document,
        qa={"ok": True, "schema": SCHEMA_CONTEXT, "simulated": True,
            "relational_fields": False,
            "checked_by": "pipeline.assert_context_is_not_answer_bearing"},
        qa_status=QA_PASS,
        lineage_id=lineage.lineage_id,
        split=lineage.split,
    )
    return record, document


def context_query(store: AssetStore, fragment_id: str) -> dict[str, Any]:
    """Given a fragment id, return the same-batch candidate scope it belongs to.

    Resolution order, all of it read from committed metadata: the fragment asset's
    ``meta.context_id`` -> the ``context_pack`` asset carrying that ``context_id`` -> that pack's
    ``batch_id`` and ``coexistents``.  A fragment that carries no context is reported as such
    (``found: false``) instead of falling back to a guess.
    """
    matches: list[Any] = []
    for record in store.list_assets(limit=1000000):
        if str((record.meta or {}).get("fragment_id", "")) == str(fragment_id):
            matches.append(record)
    if not matches:
        return {"fragment_id": str(fragment_id), "found": False,
                "reason": "no asset in this store carries this fragment_id"}
    fragment = matches[0]
    context_id = str((fragment.meta or {}).get("context_id", "") or "")
    if not context_id:
        return {"fragment_id": str(fragment_id), "found": False,
                "reason": (f"fragment asset {fragment.asset_id} carries no context_id; the batch "
                           f"scope cannot be resolved and is not guessed"),
                "fragment_asset": fragment.asset_id, "role": fragment.role}
    for record in store.list_assets(role=ROLE_CONTEXT_PACK, limit=1000000):
        meta = dict(record.meta or {})
        if str(meta.get("context_id", "")) != context_id:
            continue
        candidates = [str(row.get("id", "")) for row in (meta.get("coexistents") or [])
                      if str(row.get("id", "")) != str(fragment_id)]
        return {
            "fragment_id": str(fragment_id), "found": True, "simulated": bool(meta["simulated"]),
            "fragment_asset": fragment.asset_id,
            "context_asset": record.asset_id,
            "context_id": context_id,
            "batch_id": str(meta.get("batch_id", "")),
            "bag_id": str(meta.get("bag_id", "")),
            "pit_id": str(meta.get("pit_id", "")),
            "stratum_id": str(meta.get("stratum_id", "")),
            "same_batch_candidates": sorted(candidates),
            "same_batch_size": int(meta.get("batch_size", 0) or 0),
            "scale_reference_kind": str(
                (meta.get("scale_reference") or {}).get("scale_reference_kind", "")),
        }
    return {"fragment_id": str(fragment_id), "found": False,
            "reason": (f"fragment carries context_id {context_id!r} but this store holds no "
                       f"context_pack with it"),
            "fragment_asset": fragment.asset_id, "context_id": context_id}


def _batch_membership(fragment_assets: Sequence[Any], obs_by_fragment: Mapping[str, str],
                      *, primary_id: str, divisor: int) -> dict[int, list[dict[str, Any]]]:
    """Group the committed fragments of one event into batches (index -> member rows).

    Read back from the committed ``fragment_mesh`` metadata, so the grouping describes the store
    rather than the in-memory fracture object.  ``divisor <= 0`` puts the whole event in batch 0.
    """
    out: dict[int, list[dict[str, Any]]] = {}
    ordered = sorted(fragment_assets, key=lambda record: str(record.meta.get("fragment_id", "")))
    for position, record in enumerate(ordered):
        meta = dict(record.meta or {})
        fragment_id = str(meta.get("fragment_id", ""))
        batch_index = 0 if divisor <= 0 else position // int(divisor)
        role = "target_observed" if fragment_id == primary_id else "event_endpoint"
        if bool(meta.get("is_tiny", False)):
            role = "debris_tiny"
        out.setdefault(batch_index, []).append({
            "fragment_id": fragment_id,
            "role": role,
            "is_tiny": bool(meta.get("is_tiny", False)),
            "geometry_asset": record.asset_id,
            "observation_asset": obs_by_fragment.get(fragment_id, ""),
            "has_observation": fragment_id in obs_by_fragment,
            "note": ("primary damaged endpoint rendered by the observation route"
                     if fragment_id == primary_id else
                     "modelled endpoint of the same fracture event"),
        })
    return out


def build_one_mother(plan: GenerationPlan, lineage: LineagePlan, store: AssetStore,
                     *, run_id: str | None = None, degrade_cfg: Any = None,
                     total_lineages: int = 1) -> dict[str, Any]:
    """Run the full asset chain for one lineage. Never raises: returns a real outcome.

    ``degrade_cfg`` (step 9) is a :class:`synlab.degrade.diversity.DiversityConfig` or ``None``.
    ``None`` -- the default for every legacy caller -- skips the step entirely.

    Step 10 commits the **simulated excavation context** of this lineage's batch (plan t088): the
    ``context_pack`` asset plus the ``context_id``/``batch_id`` identity stamped into the
    metadata of the fragments, observations, truths and labels of the batch.  ``total_lineages``
    only sizes the batch: a one- or two-lineage corpus keeps a whole lineage in one bag (so the
    "same batch" scope is not trivially the whole store), a larger corpus is split by the
    declared ``target_fragments_estimate``.
    """
    spec = plan.spec
    row: dict[str, Any] = {
        "lineage_id": lineage.lineage_id, "split": lineage.split, "vessel_id": lineage.vessel_id,
        "material_id": lineage.material_id, "pattern_id": lineage.pattern_id,
        "layer_combo_id": lineage.layer_combo_id, "params": lineage.params,
        "planned": 1, "attempted": 1, "accepted": 0, "quarantined": False,
        "quarantine_reason": None, "fragments": 0, "observations": 0,
        "stages": {}, "backend": spec.fracture.backend,
    }
    # the declared per-batch fragment target, never smaller than 1 fragment.  At the current
    # corpus scale (one or two lineages) a whole lineage is one bag: a batch would otherwise be
    # either a single sherd or the entire store, and neither makes "same batch" a useful scope.
    divisor = max(int(getattr(spec.dataset, "target_fragments_estimate", 0) or 0) // 10, 1)
    if int(total_lineages) <= 2:
        divisor = 0
    # The mother is not a sherd, so it carries no bag; every asset a sherd owns (its fragment
    # mesh, its observation, the truth layers and the labels) carries the batch identity of its
    # own batch, planned below from the fragment ids before any of them is committed.
    mother_context: ContextPlan | None = None
    rngs = derive_named_rngs(spec.master_seed, lineage.lineage_id)
    stage_times: dict[str, float] = {}
    try:
        # 1. mother ---------------------------------------------------------------
        t0 = time.perf_counter()
        from .mothers.api import audit_mother, create_mother

        mother = create_mother(lineage.vessel_id, lineage.material_id, lineage.params,
                               rngs["shape"], mother_id=lineage.lineage_id)
        mother_audit = audit_mother(mother)
        stage_times["mother"] = time.perf_counter() - t0
        if not mother_audit.get("ok", True):
            raise SynLabError(ErrorCode.MOTHER_INVALID, f"mother audit failed: {mother_audit}",
                              stage="mother")
        mother_asset = _commit_mother(store, mother, lineage, mother_audit, run_id=run_id,
                                      context=mother_context)

        # 2. material -------------------------------------------------------------
        t0 = time.perf_counter()
        material_asset = None
        try:
            from .materials.api import build_material_profile, commit_material

            # material profiles own their parameter schema; vessel shape parameters must not be
            # pushed into it (the catalogue validates unknown fields and refuses them).
            material_params = _material_params(lineage.material_id, lineage.params)
            profile = build_material_profile(lineage.material_id, material_params, rngs["material"])
            material_asset = commit_material(store, profile, lineage_id=lineage.lineage_id,
                                             split=lineage.split, ancestry=[mother_asset.asset_id],
                                             run_id=run_id)
        except SynLabError:
            raise
        except Exception as exc:
            raise SynLabError(ErrorCode.DEPENDENCY_CAPABILITY_MISSING,
                              f"material stage failed: {type(exc).__name__}: {exc}",
                              stage="material") from exc
        stage_times["material"] = time.perf_counter() - t0

        # 3. pattern (frozen before fracture) -------------------------------------
        t0 = time.perf_counter()
        from .patterns.api import apply_pattern_geometry, build_pattern, commit_pattern, evaluate

        recipe = _build_pattern_recipe(mother, spec, rngs["pattern"], lineage.pattern_id)
        sample_points = np.asarray(mother.mesh.vertices, dtype=np.float64)
        sample_tags = np.zeros(len(sample_points), dtype=np.int32)
        channels = evaluate(recipe, mother, sample_points, sample_tags)
        pattern_asset = commit_pattern(store, recipe, lineage_id=lineage.lineage_id,
                                       split=lineage.split, ancestry=[mother_asset.asset_id],
                                       channels=channels, run_id=run_id)
        if spec.pattern.height_policy != "none" or getattr(recipe, "params", {}).get("height_mm", 0):
            mother = apply_pattern_geometry(mother, recipe, rngs["pattern"])
            mother_asset = _commit_mother(store, mother, lineage, mother_audit, suffix="patterned",
                                          run_id=run_id)
        stage_times["pattern"] = time.perf_counter() - t0

        # 4. fracture -------------------------------------------------------------
        t0 = time.perf_counter()
        from .fracture.api import audit_fracture, fracture_event

        event_id = lineage.event_ids[0] if lineage.event_ids else f"{lineage.lineage_id}_E01"
        fracture = fracture_event(mother, spec.fracture, rngs["cut"], event_id=event_id)
        fracture_audit = audit_fracture(fracture, mother)
        # the fracture auditor reports `passed` while this pipeline reads `ok`: accept either, and
        # never treat a missing flag as success when other evidence says the event failed.
        #
        # ``ambiguous_area_ratio_max`` is deliberately NOT a rejection criterion here.  The
        # auditor does not list it as a conservation failure, and an ambiguous interface is a
        # *legitimate* outcome: ``truth.finalize_clean_truth`` classifies such a patch as
        # UNKNOWN with valid=false / loss_mask=false, so it never becomes an R2 positive.
        # Rejecting the whole mother on it deleted the real mother, its fragments and its
        # observation from the dataset instead of letting the relation classification degrade.
        audit_ok = fracture_audit.get("ok", fracture_audit.get("passed", True))
        if audit_ok is False:
            raise SynLabError(ErrorCode.FRACTURE_CONSERVATION_FAIL,
                              f"fracture audit failed: {fracture_audit}", stage="fracture",
                              measurements=fracture_audit)
        # The batch layout of this event is fixed here, from the fragment ids, *before* the first
        # of those assets is committed: the same mapping decides each fragment's
        # ``meta.context_id`` and the membership of the context pack, so they cannot disagree.
        context_layout = batch_slot_layout(
            spec.master_seed, lineage,
            [str(getattr(fragment, "fragment_id", "")) for fragment in fracture.fragments],
            divisor=divisor)
        context_for_fragment = context_layout
        lineage_context = next(iter(context_layout.values())) if context_layout else None
        if lineage_context is None:
            raise SynLabError(ErrorCode.MOTHER_INVALID, "the fracture event produced no fragment",
                              stage="fracture")
        row["context"] = lineage_context.as_dict()
        fragment_assets = _commit_fragments(store, fracture, lineage, mother_asset.asset_id,
                                            run_id=run_id,
                                            context_for=context_for_fragment)
        row["fragments"] = len(fracture.fragments)
        stage_times["fracture"] = time.perf_counter() - t0

        # 5. clean truth ----------------------------------------------------------
        t0 = time.perf_counter()
        from .truth.api import commit_truth, finalize_clean_truth

        clean = finalize_clean_truth(mother, fracture)
        clean_ref = commit_truth(store, stamp_context(clean, lineage_context),
                                 role=ROLE_CLEAN_TRUTH,
                                 lineage_id=lineage.lineage_id,
                                 split=lineage.split,
                                 ancestry=[a.asset_id for a in fragment_assets] + [mother_asset.asset_id],
                                 run_id=run_id)
        r2_pairs = sum(1 for edge in clean.relations.values() if edge.kind == "R2")
        stage_times["clean_truth"] = time.perf_counter() - t0

        # 6. physical damage ------------------------------------------------------
        t0 = time.perf_counter()
        physical_ref = None
        physical_result_ref = None
        physical_truth_ref = None
        from .physical.api import apply_damage, audit_physical, commit_physical, commit_physical_result
        from .truth.api import update_residual_truth

        target_fragment = _pick_fragment(fracture)
        recipe_id = (spec.physical.recipes[0] if spec.physical.recipes else "P03_depth_light")
        # the choice is a real measurement, not a hidden heuristic: the coverage row says which
        # piece was damaged, how much new surface it carries and how many pieces were eligible
        target_ids, target_origin = _fragment_interface_faces(target_fragment)
        row["physical_target"] = {
            "fragment_id": str(getattr(target_fragment, "fragment_id", "")),
            "volume_mm3": float(getattr(target_fragment, "volume_mm3", 0.0)),
            "faces": int(len(np.asarray(getattr(target_fragment, "face_side", np.zeros(0))))),
            "interface_faces_by_id": int(target_ids),
            "interface_faces_by_origin": int(target_origin),
            "fragments_carrying_an_interface": int(sum(
                1 for f in fracture.fragments
                if any(count > 0 for count in _fragment_interface_faces(f)))),
            "fragments_total": int(len(fracture.fragments)),
            "rule": "largest non-tiny fragment that carries an interface face (declared ROI)",
        }
        damage_recipe = _load_damage_recipe(recipe_id, spec, fragment=target_fragment,
                                            master_seed=spec.master_seed,
                                            lineage_id=lineage.lineage_id)
        physical = apply_damage(clean, target_fragment, damage_recipe, rngs["damage"])
        physical_audit = audit_physical(physical, clean)
        physical_ref = commit_physical(store, physical, lineage_id=lineage.lineage_id,
                                       split=lineage.split, run_id=run_id)
        # Plan 4.1: the PhysicalPack carries the damaged component *and* the result record
        # (recipe, survivor map, lost volume, revision/hash, clean reference).  The record is a
        # real measurement from `audit_physical`; its verdict is that audit's own status, so a
        # level the auditor did not confirm enters the store as QA_FAIL instead of silently
        # passing as an unjudged asset.
        physical_result_ref = commit_physical_result(
            store, physical, audit=physical_audit, clean_asset_id=clean_ref.asset_id,
            clean_asset_hash=clean_ref.blob_hash,
            component_asset_id=physical_ref.asset_id, lineage_id=lineage.lineage_id,
            split=lineage.split, run_id=run_id)
        physical_truth = update_residual_truth(clean, physical)
        physical_truth_ref = commit_truth(store, stamp_context(physical_truth, lineage_context),
                                          role="physical_truth",
                                          lineage_id=lineage.lineage_id, split=lineage.split,
                                          ancestry=[physical_ref.asset_id], run_id=run_id)
        stage_times["physical"] = time.perf_counter() - t0

        # 7. observation ----------------------------------------------------------
        t0 = time.perf_counter()
        from .observe.api import adapt_observed_features, commit_observation, observe, estimate_quality
        from .truth.api import update_visibility_truth

        route = spec.observation.routes[0].value
        observe_spec = _resolve_observe_spec(spec, store)
        # The first request is the historical one and is unchanged: the declared damage recipe
        # was applied to exactly one fragment, and ``resolve_target`` resolves the physical pack
        # to that fragment's *damaged* geometry.
        observation = observe(physical, None, rngs, route=route, spec=observe_spec)
        # the semantics this observation was rendered under travel with it, so a batch produced
        # before/after a render-semantics change is distinguishable programmatically
        # (docs/a12/data_semantics_versions.md) instead of by timestamp
        observation.meta["data_semantics"] = data_semantics()
        _stamp_obs_semantics(observation, role=OBS_ROLE_PHYSICAL_TARGET, damage_state="DAMAGED",
                             geometry_asset_id=physical_ref.asset_id)
        # the context stamp needs the owning fragment id, which the loop below also uses
        primary_fragment_id = str(getattr(observation, "fragment_id", "") or "")
        stamp_context(observation, context_for_fragment.get(primary_fragment_id,
                                                            lineage_context))
        observation_quality = estimate_quality(observation)
        obs_ref = commit_observation(store, observation, lineage_id=lineage.lineage_id,
                                     split=lineage.split,
                                     ancestry=[physical_ref.asset_id], run_id=run_id)
        # Every *other* modelled endpoint of the same event is observed with **its own**
        # geometry.  No observation is ever copied from the clean side onto another endpoint:
        # a fragment that the declared recipe did not touch has, as its physical geometry, its
        # own fracture mesh -- which is exactly what this route renders -- and the metadata says
        # so (``damage_state="UNDAMAGED"``, ``observed_geometry_asset`` = that fragment's asset).
        # Without this, the mate of every R2 interface stayed modelled-but-unobserved, the
        # encoder gated it out (``z_valid=False``) and the rank task (weight 1.0) could not start.
        fragment_asset_of = {str(record.meta.get("fragment_id", "")): record
                             for record in fragment_assets}
        endpoint_observations: list[dict[str, Any]] = []
        endpoint_failures: dict[str, str] = {}
        for fragment in fracture.fragments:
            fragment_id = str(getattr(fragment, "fragment_id", "") or "")
            if not fragment_id or fragment_id == primary_fragment_id:
                continue
            if bool(getattr(fragment, "is_tiny", False)):
                # a TINY body has no supportable surface and is excluded from every negative and
                # positive set downstream; rendering it would buy nothing
                continue
            try:
                endpoint = observe(fragment, None, rngs, route=route, spec=observe_spec)
            except SynLabError as exc:
                endpoint_failures[fragment_id] = f"{exc.code}: {exc.message}"[:300]
                continue
            except Exception as exc:  # noqa: BLE001 - an unobserved endpoint is an outcome
                endpoint_failures[fragment_id] = f"{type(exc).__name__}: {exc}"[:300]
                continue
            endpoint.meta["data_semantics"] = data_semantics()
            source_asset = fragment_asset_of.get(fragment_id)
            _stamp_obs_semantics(
                endpoint, role=OBS_ROLE_EVENT_ENDPOINT, damage_state="UNDAMAGED",
                geometry_asset_id=(source_asset.asset_id if source_asset is not None else ""))
            stamp_context(endpoint, context_for_fragment.get(fragment_id, lineage_context))
            endpoint_ref = commit_observation(
                store, endpoint, lineage_id=lineage.lineage_id, split=lineage.split,
                ancestry=([source_asset.asset_id] if source_asset is not None else []),
                run_id=run_id)
            endpoint_observations.append({"fragment_id": fragment_id, "observation": endpoint,
                                          "observation_asset": endpoint_ref.asset_id})
        visible = update_visibility_truth(physical_truth, observation)
        # S5: stamp the semantic version on the *visible* layer too.  This layer is derived from
        # the delivered mask channels (uncertain_mask / deployment_mask / id_map), so which
        # `coc_units` generation produced them decides what its counts mean -- but it used to be
        # committed with no marker at all (measured on data/a12_trainable/store: visible_labels
        # n=9, with mask_semantics=0; the other five data_semantics roles carried it).  The stamp
        # is applied here, at the commit boundary, so every producer of this layer gets it.
        _stamp_data_semantics(visible)
        visible_ref = commit_truth(store, stamp_context(visible, lineage_context),
                                   role="visible_labels",
                                   lineage_id=lineage.lineage_id, split=lineage.split,
                                   ancestry=[obs_ref.asset_id, physical_truth_ref.asset_id],
                                   run_id=run_id)
        row["observations"] = (len(observation.views)
                               + sum(len(entry["observation"].views)
                                     for entry in endpoint_observations))
        stage_times["observe"] = time.perf_counter() - t0

        # 8. features / labels / provenance (separate objects) --------------------
        t0 = time.perf_counter()
        contract = {"schema": spec.integration.feature_schema, "token_budget": 256}
        bundles = adapt_observed_features(observation, contract)
        feature_ref = _commit_features(store, bundles, lineage, obs_ref.asset_id, run_id=run_id,
                                       obs_semantics=OBS_SEMANTICS_V2)
        endpoint_feature_assets: dict[str, str] = {}
        for entry in endpoint_observations:
            endpoint_bundles = adapt_observed_features(entry["observation"], contract)
            endpoint_feature = _commit_features(store, endpoint_bundles, lineage,
                                                entry["observation_asset"], run_id=run_id,
                                                obs_semantics=OBS_SEMANTICS_V2)
            endpoint_feature_assets[entry["fragment_id"]] = endpoint_feature.asset_id
        label_ref = _commit_labels(store, bundles, clean, visible, lineage, clean_ref.asset_id,
                                   run_id=run_id, context=lineage_context)
        provenance_ref = _commit_provenance(store, plan, lineage, feature_ref.asset_id,
                                            label_ref.asset_id, run_id=run_id,
                                            context=lineage_context)
        stage_times["features"] = time.perf_counter() - t0

        # 8b. simulated excavation context (plan t088) -----------------------------
        # The grouping is read back from the *committed* fragment assets (not from the in-memory
        # fracture object), so "same batch" describes what the store holds.  Every fragment must
        # already carry this batch's context_id: a mismatch is a real contract violation and is
        # raised instead of being papered over by a second write.
        t0 = time.perf_counter()
        obs_asset_of = {primary_fragment_id: obs_ref.asset_id,
                        **{entry["fragment_id"]: entry["observation_asset"]
                           for entry in endpoint_observations}}
        mismatched = [
            f"{record.asset_id}:{record.meta.get('context_id')!r}"
            for record in fragment_assets
            if str(record.meta.get("context_id", ""))
            != context_for_fragment.get(str(record.meta.get("fragment_id", "")),
                                        lineage_context).context_id]
        if mismatched:
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                f"{len(mismatched)} fragment asset(s) carry a context_id that the batch layout of "
                f"this event did not plan: {mismatched[:5]}",
                stage="pipeline.context")
        batches = _batch_membership(fragment_assets, obs_asset_of,
                                    primary_id=primary_fragment_id, divisor=divisor)
        context_refs: list[dict[str, Any]] = []
        for batch_index in sorted(batches):
            members = batches[batch_index]
            pack_context = context_for_fragment.get(str(members[0]["fragment_id"]),
                                                    lineage_context)
            if int(pack_context.batch_index) != int(batch_index):
                raise SynLabError(
                    ErrorCode.SCHEMA_INVALID,
                    f"batch slot {batch_index} does not match the planned batch slot "
                    f"{pack_context.batch_index} of context {pack_context.context_id!r}",
                    stage="pipeline.context")
            record, document = build_context_pack(
                store, plan, lineage, pack_context, batches=members, run_id=run_id)
            context_refs.append({"asset_id": record.asset_id, "pack_id": pack_context.pack_id,
                                 "batch_id": pack_context.batch_id,
                                 "batch_size": int(document["batch_size"]),
                                 "coexistents": len(document["coexistents"])})
        row["context_assets"] = context_refs
        row["context_batches"] = len(batches)
        stage_times["context"] = time.perf_counter() - t0

        # 9. degradation diversity (opt-in: see configs/a12/degrade_diversity.yaml) ---------
        # One asset per (axis, level) of *this* lineage's own geometry/observation, level 0
        # referencing the source asset, all five levels sharing one frozen basis.  The role is
        # `degrade_variant` (never `feature_bundle`): the metadata carries axis_id/level/variant,
        # which are exactly the answer-side keys the leakage audit forbids in a feature bundle.
        if degrade_cfg is not None:
            t0 = time.perf_counter()
            diversity = _materialize_degrade_diversity(
                store, plan=plan, lineage=lineage, degrade_cfg=degrade_cfg,
                observation=observation, target_fragment=target_fragment,
                fragment_asset_of=fragment_asset_of, run_id=run_id,
                observation_asset_id=obs_ref.asset_id)
            row["degrade_diversity"] = diversity["summary"]
            row["degrade_variant_assets"] = list(diversity["variant_asset_ids"])
            row["degrade_source_assets"] = {key: entry.get("asset_id")
                                            for key, entry in diversity["sources"].items()}
            row["degrade_diversity_report_ref"] = diversity.get("report_ref")
            stage_times["degrade_diversity"] = time.perf_counter() - t0

        row.update({
            "accepted": 1,
            "r2_pairs": r2_pairs,
            "interfaces": len(clean.interfaces),
            "physical_components": len(physical.components),
            "lost_volume_ratio": physical.lost_volume_ratio,
            "mother_asset": mother_asset.asset_id,
            "material_asset": material_asset.asset_id if material_asset else None,
            "pattern_asset": pattern_asset.asset_id,
            "clean_truth": clean_ref.asset_id,
            "physical_asset": physical_ref.asset_id,
            "physical_result_asset": physical_result_ref.asset_id,
            "physical_result_qa": physical_result_ref.qa_status,
            "physical_audit_status": physical_audit.get("status"),
            "obs_asset": obs_ref.asset_id,
            "obs_assets": {primary_fragment_id: obs_ref.asset_id,
                           **{entry["fragment_id"]: entry["observation_asset"]
                              for entry in endpoint_observations}},
            "obs_semantics": OBS_SEMANTICS_V2,
            "observed_fragments": sorted({primary_fragment_id}
                                         | {entry["fragment_id"]
                                            for entry in endpoint_observations} - {""}),
            "observation_assets": 1 + len(endpoint_observations),
            # an endpoint that could not be rendered is reported with its real reason instead of
            # being silently absent from the observed set
            "obs_endpoint_failures": dict(endpoint_failures),
            "visible_labels_from": primary_fragment_id,
            "visible_asset": visible_ref.asset_id,
            "feature_asset": feature_ref.asset_id,
            "feature_assets": {primary_fragment_id: feature_ref.asset_id,
                               **endpoint_feature_assets},
            "label_asset": label_ref.asset_id,
            "provenance_asset": provenance_ref.asset_id,
            "stages": stage_times,
            "quality": observation_quality,
            "fracture_audit": fracture_audit,
            "physical_audit": physical_audit,
        })
        return {"ok": True, "coverage_row": row, "error": None}
    except SynLabError as exc:
        row["quarantined"] = True
        row["quarantine_reason"] = f"{exc.code}: {exc.message}"[:400]
        row["stages"] = stage_times
        return {"ok": False, "coverage_row": row,
                "error": {"code": str(exc.code), "stage": exc.stage, "message": exc.message[:400]}}
    except Exception as exc:  # noqa: BLE001 - isolate one mother, keep the run honest
        row["quarantined"] = True
        row["quarantine_reason"] = f"{type(exc).__name__}: {exc}"[:400]
        row["stages"] = stage_times
        return {"ok": False, "coverage_row": row,
                "error": {"code": "UNEXPECTED", "stage": "pipeline",
                          "message": f"{type(exc).__name__}: {exc}"[:400],
                          "traceback": traceback.format_exc()[-1200:]}}


def _resolve_observe_spec(spec: GenerationSpec, store: AssetStore | None) -> Any:
    """Project the generation config + camera profile onto a real ``ObsSpec``.

    Three mismatches are fixed here, all of them against a *declared* value:

    ``observation.views_per_fragment`` / ``image_long_edge_px``
        Ignored entirely when the observation runs with the default ``ObsSpec`` (12 views at
        512 px regardless of the config).  The delivered product of a run follows its config.

    the defocus mark-out of the software rasteriser
        ``render_view`` marks a pixel uncertain when the delivered circle of confusion exceeds
        ``RenderSpec.coc_px_threshold``.  Under ``mask_semantics = coc_units_v2`` the CoC is
        evaluated with the *declared* optics (focal length and f-number from ``ViewFrame.meta``
        or the camera-profile registry) and converted into pixels with the delivered sampling
        density ``D = f_px / focal_length_mm``; the superseded pixel-unit expression -- which fed
        a pixel focal length into the millimetre formula, dropped ``D`` and always used f/1 --
        inflated the CoC by ``D * f_number`` (measured 74.105 on the delivered L0 views,
        data/a12/reports/visible_labels_coc_units.json) and eroded the deployable mask to
        0.26-7.2 % of the object.  The threshold handed to the renderer stays scaled by the
        declared f-number: that is the conservative mark-out this loop has always applied
        (0.75 px x 2.2 = 1.65 px on CAM_MID_V3, i.e. *stricter* than the profile's own 2.0 px
        ``coC_px``), so the renderer/config contract does not change with the unit fix.  Measured
        consequence: every object pixel of the L0 loop is now inside the mark-out
        (data/a12/reports/coc_units_v2_verification_l0.json).

    the supersample block-disagreement channel
        ``deployment_mask_from_render`` requires every supersample of a block to hit the same
        face id.  At the delivered resolution of this loop that rejects ~90 % of the object
        (and at the profile-native 1024 px still ~67 %), which empties the deployable
        foreground mask and fails the visibility truth with "no correspondence sample is
        visible in any view".  The loop renders at ``supersample=1``, which makes the pixel
        classification exact (a pixel is object or background, never a blend of two faces);
        the choice is recorded in the observation metadata through the render spec.
    """
    from .observe.render import RenderSpec
    from .observe.routes import ObsSpec

    frames = _profile_frames(spec)
    view_count = int(spec.observation.views_per_fragment)
    long_edge = int(spec.observation.image_long_edge_px)
    aspect = 4.0 / 3.0
    if frames:
        width, height = frames[0]
        aspect = float(width) / float(max(height, 1))
    if aspect >= 1.0:
        delivered = (int(long_edge), max(int(round(long_edge / aspect)), 8))
    else:
        delivered = (max(int(round(long_edge * aspect)), 8), int(long_edge))
    max_render_pixels = max(int(delivered[0]) * int(delivered[1]), 1)
    declared = float(RenderSpec.coc_px_threshold)
    aperture = float(_declared_f_number(spec))
    return ObsSpec(
        view_count=view_count,
        delivered_size=delivered,
        max_render_pixels=max_render_pixels,
        render_spec=RenderSpec(supersample=1, coc_px_threshold=declared * aperture),
        master_seed=int(spec.master_seed),
        lineage_id="generate",
    )


def _declared_f_number(spec: GenerationSpec) -> float:
    """Aperture declared by the camera profiles; f/8 when the registry is unavailable."""
    ref = getattr(spec.observation, "camera_profile_ref", None)
    path = Path(ref) if ref else None
    if not path or not path.exists():
        return 8.0
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 8.0
    values = [float(p["f_number"]) for p in (document.get("profiles") or [])
              if p.get("f_number")]
    return values[0] if values else 8.0


def _declared_coc_px(spec: GenerationSpec) -> float:
    """CoC mark-out threshold; the renderer default (0.75 px) when nothing is declared."""
    from .observe.render import RenderSpec

    value = getattr(spec.observation, "coc_px_threshold", None)
    return float(value) if value else float(RenderSpec.coc_px_threshold)


def _profile_frames(spec: GenerationSpec) -> list[tuple[int, int]]:
    ref = getattr(spec.observation, "camera_profile_ref", None)
    path = Path(ref) if ref else None
    if not path or not path.exists():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[tuple[int, int]] = []
    for profile in document.get("profiles") or []:
        edge = int(profile.get("image_long_edge_px", 0) or 0)
        if edge > 0:
            out.append((edge, int(round(edge * 3.0 / 4.0))))
    return out


def _material_params(material_id: str, vessel_params: dict[str, Any]) -> dict[str, Any]:
    """Keep only the keys the material catalogue declares; never leak vessel fields into it."""
    try:
        from .materials.api import material_param_model

        model = material_param_model(material_id)
        allowed = set(getattr(model, "model_fields", {}) or {})
        return {k: v for k, v in vessel_params.items() if k in allowed}
    except Exception:
        return {}


def _fragment_interface_faces(fragment: Any) -> tuple[int, int]:
    """``(faces with an interface id, faces whose origin is the fracture interface)``.

    Mirrors the acceptance rule of :func:`synlab.physical.fields.roi_faces` for
    ``{"kind": "interface"}``: a fragment can host an interface operator when **either**
    channel is non-empty, because the ROI falls back from ``face_interface_id`` to
    ``face_origin_kind`` when no face was paired into a patch.
    """
    ids = np.asarray(getattr(fragment, "face_interface_id", np.zeros(0, dtype=np.int32)))
    origin = np.asarray(getattr(fragment, "face_origin_kind", np.zeros(0, dtype=np.uint8)))
    n_ids = int(np.count_nonzero(ids >= 0)) if ids.size else 0
    n_origin = int(np.count_nonzero(origin == ORIGIN_INTERFACE)) if origin.size else 0
    return n_ids, n_origin


def _pick_fragment(fracture: Any) -> Any:
    """The fragment the declared damage recipe is applied to.

    Every physical recipe of this plan addresses the *fracture interface* as its ROI (P01,
    P02 and P03 all declare ``{"kind": "interface"}`` in :mod:`synlab.degrade.axes`), and a
    fracture event can return bodies the cutter never touched.  Two cases are real in this
    store: a composite mother whose separate pre-break body (the V10 lid) is entirely on one
    side of the cut, and a stray body created by the vessel builder.  Such a body keeps every
    face tagged ``mother_surface``, so it carries no interface attribute *because it has no
    new surface* - the attribute is not lost, the surface does not exist.

    Selecting the largest fragment by volume alone therefore picks an untouched body whenever
    it is the biggest piece: measured on ``LIN0004_V10_M06_PAT03`` the untouched lid is
    394 820 mm^3 against 168 026 mm^3 for the largest cut piece, and the interface ROI then
    answers ``NA_NOT_APPLICABLE`` for the whole lineage although the event *does* have a new
    surface.  The target is the largest fragment that really carries an interface face; when
    no fragment carries one (a genuinely interface-free event) the previous largest-volume
    choice is kept, so the honest ``NA`` answer is still produced instead of being hidden.
    """
    fragments = [f for f in fracture.fragments if not getattr(f, "is_tiny", False)]
    if not fragments:
        fragments = list(fracture.fragments)
    capable = [f for f in fragments
               if any(count > 0 for count in _fragment_interface_faces(f))]
    pool = capable or fragments
    return max(pool, key=lambda f: float(getattr(f, "volume_mm3", 0.0)))


def _load_damage_recipe(recipe_id: str, spec: GenerationSpec, *, fragment: Any = None,
                        master_seed: int | None = None, lineage_id: str = "") -> Any:
    """Resolve one physical recipe into the typed ``DamageRecipe`` the operators expect.

    The P operators do not only read ``params``: several of them (P03/P07 ``FourierField``,
    P04 cutter pose, P06 contamination field) read *frozen* decisions out of ``recipe.basis``.
    A recipe built from the level table alone therefore has no ``basis`` and the operator fails
    with ``KeyError`` -- the declared effect is never applied.  This resolver builds the recipe
    through the degrade registry entry for the declared axis, so ``params``, ``roi``, ``grid``
    and the whole ``basis`` payload come from the same code path the axis audit uses.
    """
    import json as _json

    from .physical.recipe import DamageRecipe

    declared: dict[str, Any] = {}
    path = Path(spec.physical.recipe_registry_ref) if spec.physical.recipe_registry_ref else None
    if path and path.exists():
        data = _json.loads(path.read_text(encoding="utf-8"))
        for recipe in data.get("recipes", []):
            if recipe.get("recipe_id") == recipe_id:
                declared = recipe
                break
    operators = declared.get("operators") or [{"axis_id": "P03", "level": 1, "variant": "depth_mm"}]
    first = operators[0]
    axis_id = str(first.get("axis_id", "P03"))
    level = int(first.get("level", 1))
    variant = str(first.get("variant", "") or "")
    try:
        return _recipe_from_degrade_registry(
            axis_id, level, variant, recipe_id, fragment=fragment,
            master_seed=spec.master_seed if master_seed is None else master_seed,
            lineage_id=lineage_id)
    except SynLabError:
        raise
    except Exception:
        # The registry is present in this checkout; reaching the fallback means the declared
        # axis could not build its basis.  Record that instead of silently running a recipe
        # with an empty basis, and keep the documented level table as the declared effect.
        params = _fallback_level_parameters(axis_id, level)
        return DamageRecipe(axis_id=axis_id, variant=variant, level=level, recipe_id=recipe_id,
                            params=params, meta={"basis_source": "FALLBACK_LEVEL_TABLE"})


def _recipe_from_degrade_registry(axis_id: str, level: int, variant: str, recipe_id: str, *,
                                  fragment: Any, master_seed: int, lineage_id: str) -> Any:
    """Freeze one axis basis through the degrade registry and project it onto a recipe."""
    from .degrade.axes import physical_fragment
    from .degrade.sources import SourceBundle
    from .degrade.registry import get_operator
    from .seeds import make_rng

    operator = get_operator(axis_id)
    variant_name = operator.resolve_variant(variant or None)
    fragment_id = str(getattr(fragment, "fragment_id", "") or "fragment")
    payload: dict[str, Any] = {}
    mesh = getattr(fragment, "mesh", None)
    if mesh is not None:
        payload["mesh"] = mesh
        payload["fragment"] = fragment
    source = SourceBundle(source_kind="CLEAN", payload=payload, lineage_id=lineage_id or None,
                          fragment_id=fragment_id,
                          meta={"master_seed": int(master_seed), "fragment_id": fragment_id,
                                "material_id": str(getattr(fragment, "meta", {}).get("material_id", "")
                                                   or "")})
    rng = make_rng(int(master_seed), lineage_id or "lineage", "physical", axis_id, variant_name)
    context = {"axis_id": axis_id, "lineage_id": lineage_id or "lineage",
               "fragment_id": fragment_id, "master_seed": int(master_seed),
               "variant": variant_name, "source": source, "source_kind": source.source_kind}
    basis = operator.sample_basis(context, rng, variant_name)
    params = operator.params_for(level, variant_name)
    resolved_fragment = physical_fragment(source)
    recipe = operator.recipe(level=level, variant=variant_name, params=params, basis=basis,
                             fragment=resolved_fragment, source=source)
    recipe.recipe_id = recipe_id
    recipe.meta["basis_source"] = "degrade.registry"
    recipe.meta["basis_id"] = basis.basis_id
    return recipe


def _fallback_level_parameters(axis_id: str, level: int) -> dict[str, Any]:
    """Documented level tables from plan section 15.2 (used only when degrade is absent)."""
    table: dict[str, list[dict[str, Any]]] = {
        "P01": [{"recession_strength": v} for v in (0.0, 0.25, 0.5, 0.75, 1.0)],
        "P02": [{"recession_strength": v} for v in (0.0, 0.25, 0.5, 0.75, 1.0)],
        "P03": [{"depth_mm": v} for v in (0.0, 0.05, 0.1, 0.25, 0.5)],
        "P04": [{"contact_loss_target": v} for v in (0.0, 0.1, 0.25, 0.5, 0.8)],
        "P05": [{"retained_fraction": v} for v in (1.0, 0.75, 0.5, 0.25, 0.0)],
        "P06": [{"coverage": v} for v in (0.0, 0.2, 0.4, 0.6, 0.8)],
        "P07": [{"depth_mm": v} for v in (0.0, 0.025, 0.05, 0.1, 0.2)],
        "P08": [{"affected_area": v} for v in (0.0, 0.05, 0.1, 0.2, 0.3)],
    }
    levels = table.get(axis_id, [{}] * 5)
    return dict(levels[max(0, min(len(levels) - 1, level))])


def _build_pattern_recipe(mother: Any, spec: GenerationSpec, rng: Any, pattern_id: str) -> Any:
    """Build a frozen pattern recipe for one lineage.

    ``synlab.patterns.api.build_pattern`` accepts its own typed ``PatternSpec`` or a plain
    mapping, so the generation config is projected onto it explicitly instead of being passed
    through as an unrelated model.
    """
    from .patterns.api import build_pattern

    seed = seed_ref(spec.master_seed, pattern_id, "pattern")
    payload: dict[str, Any] = {
        "family": pattern_id,
        "seed_ref": seed,
        "params": {},
        "quota_class": "PLAIN" if pattern_id == "PAT01" else "FREE",
        "allow_aux_layers": True,
        "max_aux_layers": 2,
    }
    if spec.pattern.height_policy in ("relief", "engrave"):
        payload["height"] = {"mode": spec.pattern.height_policy}
    try:
        return build_pattern(mother, payload, rng)
    except SynLabError:
        return build_pattern(mother, {"family": pattern_id, "seed_ref": seed}, rng)


def _commit_mother(store: AssetStore, mother: Any, lineage: LineagePlan, audit: dict[str, Any],
                   *, suffix: str = "", run_id: str | None = None,
                   context: ContextPlan | None = None) -> Any:
    from .storage.mesh_io import with_face_attrs

    tag_names = getattr(mother, "surface_tag_names", {}) or {}
    with_face_attrs(mother.mesh, surface_tag=np.asarray(mother.face_surface_tag, dtype=np.int32))
    meta = {
        "registry_version": str(getattr(mother, "meta", {}).get("registry_version", "")),
        "profile_metrics": getattr(mother, "meta", {}).get("profile_metrics", {}),"vessel_id": mother.vessel_id, "material_id": mother.material_id,
              "mother_id": mother.mother_id or lineage.lineage_id,
              "params": _jsonable(mother.params), "surface_tag_names": _jsonable(tag_names),
              "charts": [{"name": c.name, "kind": c.kind, "u_periodic": bool(c.u_periodic),
                          "area_mm2": float(c.area_mm2), "x_period_mm": c.x_period_mm}
                         for c in getattr(mother, "charts", [])],
              "variant": suffix or "base",
              "data_semantics": data_semantics(),
              "run_id": run_id}
    if context is not None:
        meta = _with_context(context, meta)
    return store.commit_asset(
        role=ROLE_MOTHER_MESH,
        schema=SCHEMA_MOTHER,
        unit=UNIT_MM,
        frame=FRAME_WORLD,
        payload={"mesh": mother.mesh},
        meta=meta,
        qa=audit, qa_status=QA_PASS if audit.get("ok", True) else QA_FAIL,
        lineage_id=lineage.lineage_id, split=lineage.split,
    )


def _commit_fragments(store: AssetStore, fracture: Any, lineage: LineagePlan,
                      mother_asset_id: str, *, run_id: str | None = None,
                      context_for: Mapping[str, ContextPlan] | None = None) -> list[Any]:
    from .storage.mesh_io import with_face_attrs

    out = []
    for fragment in fracture.fragments:
        with_face_attrs(fragment.mesh,
                        origin_kind=np.asarray(fragment.face_origin_kind, dtype=np.uint8),
                        source_triangle=np.asarray(fragment.face_source_tri, dtype=np.int32),
                        interface_id=np.asarray(fragment.face_interface_id, dtype=np.int32),
                        side=np.asarray(fragment.face_side, dtype=np.int8))
        meta = {"fragment_id": fragment.fragment_id, "volume_mm3": float(fragment.volume_mm3),
                "area_mm2": float(fragment.area_mm2), "is_tiny": bool(fragment.is_tiny),
                "component_id": int(fragment.component_id), "event_id": fracture.event_tree.get("event_id")
                if isinstance(fracture.event_tree, dict) else None,
                "backend": fracture.backend, "data_semantics": data_semantics(),
                "run_id": run_id}
        fragment_context = (context_for or {}).get(str(fragment.fragment_id))
        if fragment_context is not None:
            meta = _with_context(fragment_context, meta)
        record = store.commit_asset(
            role=ROLE_FRAGMENT_MESH,
            schema=SCHEMA_FRAGMENT,
            unit=UNIT_MM,
            frame=FRAME_WORLD,
            payload={"mesh": fragment.mesh},
            meta=meta,
            qa={"ok": True, "parent_qa": _jsonable(fracture.qa)},
            qa_status=QA_PASS,
            ancestry=[mother_asset_id], lineage_id=lineage.lineage_id, split=lineage.split,
        )
        out.append(record)
    return out


#: Nested feature groups produced by ``observe.features.adapt_observed_features`` and the flat
#: array names they are serialised under.  Committing the nested dictionaries as JSON metadata
#: would bury the numeric payload in ``meta.json`` (a full float list per point), leaving the
#: asset with no readable feature tensors at all.
_FEATURE_ARRAY_KEYS: dict[str, tuple[str, ...]] = {
    "point_cloud": ("xyz", "valid", "scale_valid", "n_points", "unit", "order"),
    "normal_field": ("normals", "valid", "estimator"),
    "curvature_field": ("curvature_per_mm", "valid", "estimator"),
    "density_field": ("density_per_mm2", "valid", "unit"),
    "quality": ("values", "valid", "names"),
}

#: Objects that are not scalars, arrays or short lists of scalars stay in the metadata as a
#: *description* (shape/dtype/length) rather than being inlined value by value.
_MAX_INLINE_META = 8


def _flatten_features(features: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split one feature bundle into (arrays, scalar metadata)."""
    arrays: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for key, value in features.items():
        if isinstance(value, np.ndarray):
            arrays[key] = value
            continue
        group = _FEATURE_ARRAY_KEYS.get(key)
        if isinstance(value, dict) and group:
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, np.ndarray):
                    arrays[f"{key}__{sub_key}"] = sub_value
                    continue
                if isinstance(sub_value, (list, tuple)):
                    arr = np.asarray(sub_value)
                    if arr.dtype != object and arr.size > _MAX_INLINE_META:
                        arrays[f"{key}__{sub_key}"] = arr
                        continue
                meta[f"{key}__{sub_key}"] = _jsonable(sub_value)
            continue
        if isinstance(value, dict):
            meta[key] = {str(k): _describe_value(v) for k, v in value.items()}
            continue
        if isinstance(value, (list, tuple)) and len(value) > _MAX_INLINE_META:
            arr = np.asarray(value)
            if arr.dtype != object:
                arrays[key] = arr
                continue
        meta[key] = _jsonable(value)
    return arrays, meta


def _describe_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return {"__ndarray__": list(value.shape), "dtype": str(value.dtype)}
    if isinstance(value, (list, tuple)):
        return {"__list__": len(value)}
    if isinstance(value, dict):
        return {str(k): _describe_value(v) for k, v in value.items()}
    return _jsonable(value)


def _commit_features(store: AssetStore, bundles: dict[str, Any], lineage: LineagePlan,
                     obs_asset_id: str, *, run_id: str | None = None,
    obs_semantics: str | None = None,
    **_extra: Any,
) -> Any:
    features = bundles.get("features", bundles)
    arrays, meta = _flatten_features(dict(features))
    # The legal deployment input itself: the ObsPack RGB tiles and the deployable foreground
    # mask, taken from the committed observation.  ``observe.features.adapt_observed_features``
    # returns grouped *estimates* (point cloud, normals, tokens) but not the delivered images,
    # and ``relations.attach_features`` requires ``global_rgb`` beside ``points`` to rebuild an
    # ``a12.obs.v1`` payload.  Both are observation-only quantities -- no truth channel, no
    # identifier -- so they belong on the feature side.  They are stored as uint8 so the
    # duplicate costs one byte per delivered pixel per channel.
    encoded = _observation_feature_block(store, obs_asset_id)
    if encoded:
        arrays.update(encoded["arrays"])
        meta.update(encoded["meta"])
    # Identity/answer fields are provenance, not features (plan 4.4 / 30.12): drop them here
    # instead of weakening the leakage audit later. They stay in the provenance asset.
    dropped = sorted(set(meta) & FORBIDDEN_FEATURE_FIELDS)
    for key in dropped:
        meta.pop(key, None)
    meta["feature_fields"] = sorted(meta.keys()) + sorted(arrays.keys())
    if obs_semantics:
        meta["obs_semantics"] = obs_semantics
    meta["dropped_forbidden_fields"] = dropped
    # the delivered pixel validity of this bundle comes from the observation's deployment mask,
    # so the bundle is only comparable to another batch under the same mask semantics
    meta["data_semantics"] = data_semantics()
    meta["run_id"] = run_id
    return store.commit_asset(
        role=ROLE_FEATURE_BUNDLE, schema=SCHEMA_FEATURE, unit=UNIT_MM, frame="S_mm",
        payload={**arrays}, meta=_jsonable(meta), qa={"ok": True, "whitelist_checked": True},
        qa_status=QA_PASS, ancestry=[obs_asset_id], lineage_id=lineage.lineage_id, split=lineage.split,
    )


def _observation_feature_block(store: AssetStore, obs_asset_id: str) -> dict[str, Any]:
    """Pack the delivered RGB/validity of one observation into an ``a12.obs.v1`` payload."""
    try:
        record = store.get_asset(obs_asset_id)
    except SynLabError:
        return {}
    meta = dict(record.meta or {})
    views = list(meta.get("views") or [])
    if not views:
        return {}
    arrays = store.load_arrays(obs_asset_id)
    rgb_views: list[Any] = []
    valid_views: list[Any] = []
    for index in range(len(views)):
        key = f"v{index:03d}.rgb"
        if key not in arrays:
            continue
        rgb = np.asarray(arrays[key])
        if rgb.dtype != np.uint8:
            rgb = np.clip(rgb, 0.0, 255.0).astype(np.uint8) if rgb.max(initial=0) > 2.0 \
                else np.clip(rgb * 255.0, 0.0, 255.0).astype(np.uint8)
        rgb_views.append(rgb)
        mask = arrays.get(f"v{index:03d}.deployment_mask")
        valid_views.append(np.asarray(mask, dtype=bool) if mask is not None
                           else np.ones(rgb.shape[:2], dtype=bool))
    if not rgb_views:
        return {}
    shapes = {tuple(rgb.shape[:2]) for rgb in rgb_views}
    if len(shapes) != 1:
        return {}
    height, width = shapes.pop()
    block: dict[str, Any] = {
        "global_rgb": np.stack([np.asarray(rgb, dtype=np.uint8) for rgb in rgb_views], axis=0)
        if all(rgb.shape[:2] == (height, width) for rgb in rgb_views) else None,
    }
    if block["global_rgb"] is None:
        return {}
    block["pixel_valid"] = np.stack([np.asarray(mask, dtype=bool) for mask in valid_views], axis=0)
    block["global_valid"] = np.asarray([bool(np.asarray(m).any()) for m in valid_views], bool)
    tokens_total = int(sum(int(np.count_nonzero(m)) for m in valid_views))
    return {
        "arrays": block,
        "meta": {"fragment_id": str(meta.get("fragment_id", "") or ""),
                 "component_id": str(meta.get("component_id", "") or ""),
                 "mother_id": str(meta.get("mother_id", "") or ""),
                 "n_views": len(block["global_rgb"]),
                 "image_size": [int(width), int(height)],
                 "tokens_total": tokens_total,
                 "scale_valid": bool(meta.get("scale_valid", False)),
                 "observation_id": str(meta.get("observation_id", "") or "")},
        "fragment_id": str(meta.get("fragment_id", "") or ""),
    }


def _commit_labels(store: AssetStore, bundles: dict[str, Any], clean: Any, visible: Any,
                   lineage: LineagePlan, clean_asset_id: str, *,
                   run_id: str | None = None, context: ContextPlan | None = None) -> Any:
    labels = bundles.get("labels", {}) or {}
    relations = []
    for (a, b), edge in getattr(clean, "relations", {}).items():
        relations.append({"a": a, "b": b, "kind": edge.kind, "area_mm2": float(edge.area_mm2),
                          "valid": bool(edge.valid), "loss_mask": bool(edge.loss_mask)})
    payload: dict[str, Any] = {
        "relations_json": json.dumps(relations, ensure_ascii=False),
        "visible_json": json.dumps(_jsonable(getattr(visible, "per_view", {})), ensure_ascii=False),
    }
    meta: dict[str, Any] = {}
    for key, value in labels.items():
        if isinstance(value, np.ndarray):
            payload[f"label__{key}"] = value
        elif isinstance(value, (list, tuple)) and value and isinstance(value[0], np.ndarray):
            for index, item in enumerate(value):
                payload[f"label__{key}__{index}"] = np.asarray(item)
        else:
            meta[key] = _jsonable(value)
    meta["relation_count"] = len(relations)
    meta["r2_count"] = sum(1 for r in relations if r["kind"] == "R2")
    meta["data_semantics"] = data_semantics()
    meta["run_id"] = run_id
    if context is not None:
        meta = _with_context(context, meta)
    return store.commit_asset(
        role=ROLE_LABEL_BUNDLE, schema=SCHEMA_LABELS, unit=UNIT_NONE, frame=FRAME_WORLD,
        payload=payload, meta=meta, qa={"ok": True, "layer": "visible"},
        qa_status=QA_PASS, ancestry=[clean_asset_id], lineage_id=lineage.lineage_id,
        split=lineage.split,
    )


def _commit_provenance(store: AssetStore, plan: GenerationPlan, lineage: LineagePlan,
                       feature_asset_id: str, label_asset_id: str, *,
                       run_id: str | None = None,
                       context: ContextPlan | None = None) -> Any:
    meta = {"seed_ref": seed_ref(plan.spec.master_seed, lineage.lineage_id),
            "spec_hash": plan.spec_hash,
            "code_fingerprint": _jsonable(plan.code_fingerprint),
            "backend_fingerprints": _jsonable(plan.backend_fingerprints),
            "data_semantics": data_semantics(),
            "run_id": run_id,
            "params": _jsonable(lineage.params)}
    if context is not None:
        meta = _with_context(context, meta)
    return store.commit_asset(
        role=ROLE_PROVENANCE, schema=SCHEMA_PROVENANCE, unit=UNIT_NONE, frame=FRAME_NONE,
        payload={},
        meta=meta,
        qa={"ok": True}, qa_status=QA_PASS,
        ancestry=[feature_asset_id, label_asset_id], lineage_id=lineage.lineage_id,
        split=lineage.split,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
# --- observation semantics stamping -------------------------------------------------------
OBS_SEMANTICS = "physical_side_v2"
"""Tag for observation assets produced after the two-endpoint fix.

The observation stage renders the damaged/physical variant as well, so every R2 relation can
be encoded on both sides. Assets produced before this change carry no tag, which is how the
two eras stay separable (never by timestamp or run id).
"""


def _stamp_data_semantics(obj, semantics=None):
    """Stamp a truth/label object's ``meta`` with the render/damage semantic versions (S5).

    ``data_semantics()`` already travels with the run record and the observation metadata of
    everything :func:`run_pipeline` writes; the *derived truth* layers were the exception.  A
    ``visible_labels`` layer is computed **from** the delivered mask channels, so a reader cannot
    tell which ``mask_semantics`` generation its counts came from unless the asset says so -- and
    the two generations disagree by a measured factor of ``D * N`` (74.105 on the L0 views).

    Tolerant by design, like :func:`_stamp_obs_semantics`: a non-mapping argument passes through
    untouched, and an object that already declares its versions keeps them.
    """
    target = obj if isinstance(obj, dict) else getattr(obj, "meta", None)
    if isinstance(target, dict):
        declared = dict(semantics or data_semantics())
        for key, value in declared.items():
            target.setdefault(key, value)
    return obj


def _stamp_obs_semantics(meta, semantics=None, **facts):
    """Stamp an observation meta mapping with the observation-semantics version.

    Tolerant by design: the mapping is mutated and returned, and non-mapping arguments pass
    through untouched so an unexpected call shape cannot corrupt a run.
    """
    target = meta if isinstance(meta, dict) else getattr(meta, "meta", None)
    if isinstance(target, dict):
        target["obs_semantics"] = semantics or OBS_SEMANTICS
        # the call sites describe which endpoint this observation belongs to; keep those facts
        # with the asset (namespaced so no existing key is clobbered)
        recorded = {k: v for k, v in facts.items() if v is not None and v != ""}
        if recorded:
            facts_box = target.setdefault("observation_facts", {})
            if isinstance(facts_box, dict):
                facts_box.update(recorded)
    return meta
