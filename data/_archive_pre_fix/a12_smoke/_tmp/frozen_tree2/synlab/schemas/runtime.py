"""Runtime type contracts shared by every synlab module.

These are *in-memory* contracts (numpy payloads, callables).  Serialisable metadata
models live in ``synlab.schemas.spec`` (configuration) and ``synlab.schemas.packs``
(the six data packs).  Modules must import these types instead of redefining them;
changing a field here is an interface change that invalidates downstream caches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import numpy as np

# --------------------------------------------------------------------------------------
# Face origin semantics (plan 10.2)
# --------------------------------------------------------------------------------------
ORIGIN_MOTHER_SURFACE = 0
ORIGIN_INTERFACE = 1
ORIGIN_AMBIGUOUS = 2

ORIGIN_NAMES = {
    ORIGIN_MOTHER_SURFACE: "mother_surface",
    ORIGIN_INTERFACE: "interface",
    ORIGIN_AMBIGUOUS: "ambiguous",
}


# --------------------------------------------------------------------------------------
# Mothers, charts, materials, patterns
# --------------------------------------------------------------------------------------
SurfaceTag = Literal[
    "outer_wall", "inner_wall", "rim", "foot", "base", "attachment", "interface",
]


@dataclass
class Chart:
    """A parameterised drawing chart on the mother surface (plan 7.1 / 9.2).

    ``to_uv`` maps authoritative mother mm coordinates (N,3) to chart coordinates
    (N,2) = (x_mm or u in [0,1], s_mm).  Charts are frozen with the mother.
    """

    name: str
    surface_tags: tuple[int, ...]
    kind: Literal["revolve", "planar", "sweep", "triplanar"]
    u_periodic: bool
    x_period_mm: float | None
    area_mm2: float
    to_uv: Callable[[np.ndarray], np.ndarray]
    region_mask: Callable[[np.ndarray], np.ndarray] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def uv(self, points: np.ndarray) -> np.ndarray:
        uv = np.asarray(self.to_uv(np.asarray(points, dtype=np.float64)), dtype=np.float64)
        if uv.ndim != 2 or uv.shape[1] != 2:
            raise ValueError(f"chart {self.name}: to_uv must return (N,2), got {uv.shape}")
        return uv


@dataclass
class MotherGeometry:
    """Closed material body in millimetres plus face-level source bookkeeping."""

    mesh: Any  # trimesh.Trimesh, watertight, outward-oriented, mm
    face_surface_tag: np.ndarray  # (F,) int32 index into surface_tag_names
    surface_tag_names: dict[int, str]
    charts: list[Chart]
    vessel_id: str
    material_id: str
    params: dict[str, Any]
    mother_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_faces(self) -> int:
        return int(np.asarray(self.mesh.faces).shape[0])

    @property
    def volume_mm3(self) -> float:
        return float(abs(self.mesh.volume))

    @property
    def area_mm2(self) -> float:
        return float(self.mesh.area)

    def tags_for(self, faces: np.ndarray) -> np.ndarray:
        return self.face_surface_tag[np.asarray(faces, dtype=np.int64)]

    def tag_name(self, tag: int) -> str:
        return self.surface_tag_names.get(int(tag), f"tag_{int(tag)}")

    def chart_for_tag(self, tag: int) -> Chart | None:
        for chart in self.charts:
            if int(tag) in chart.surface_tags:
                return chart
        return None


@dataclass
class MaterialSample:
    """Per-point material field result (plan 8.1). Pure function of mother coordinates."""

    layer_id: np.ndarray          # (N,) int32, outermost layer wins
    albedo: np.ndarray            # (N,3) float32 linear
    roughness: np.ndarray         # (N,) float32
    direction: np.ndarray         # (N,3) float32 grain / bedding direction
    grain: np.ndarray             # (N,) float32 normalised grain intensity
    porosity: np.ndarray          # (N,) float32
    ior: np.ndarray               # (N,) float32
    layer_depth_mm: np.ndarray    # (N,) float32 depth below the outermost surface


@dataclass
class LayerSpec:
    layer_id: int
    name: str
    material_id: str
    mode: Literal["SHADING_LAYER", "GEOMETRIC_LAYER"]
    thickness_mm: float
    albedo: tuple[float, float, float]
    roughness: float
    ior: float = 1.5
    transmission: float = 0.0


@dataclass
class PatternRecipe:
    """Frozen pattern recipe; ``evaluate`` never draws randomness (plan 9.1)."""

    family_id: str
    seed_ref: str
    params: dict[str, Any]
    palette: list[tuple[float, float, float]]
    channels: tuple[str, ...]
    version: str = "1.0"
    resource_hash: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class PatternChannels:
    albedo: np.ndarray          # (N,3) float32 linear, in [0,1]
    roughness: np.ndarray       # (N,) float32
    height_mm: np.ndarray       # (N,) float32 real geometric displacement
    pattern_region: np.ndarray  # (N,) uint8 mask of the painted region
    meta: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------------------
# Fracture (plan 10)
# --------------------------------------------------------------------------------------
@dataclass
class CutBasis:
    """Local cut frame: w = h(u, v) with u/v in millimetres."""

    origin: np.ndarray       # (3,) float64
    e_u: np.ndarray          # (3,)
    e_v: np.ndarray          # (3,)
    normal: np.ndarray       # (3,) unit, +w direction (towards M_minus)
    u_range: tuple[float, float]
    v_range: tuple[float, float]
    h_scale_mm: float
    basis_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_local(self, points: np.ndarray) -> np.ndarray:
        p = np.asarray(points, dtype=np.float64) - self.origin
        return np.stack([p @ self.e_u, p @ self.e_v, p @ self.normal], axis=1)

    def to_world(self, uv_w: np.ndarray) -> np.ndarray:
        uv_w = np.asarray(uv_w, dtype=np.float64)
        return (self.origin[None, :] + uv_w[:, 0:1] * self.e_u[None, :]
                + uv_w[:, 1:2] * self.e_v[None, :] + uv_w[:, 2:3] * self.normal[None, :])


@dataclass
class CutterResult:
    """One closed cutter body shared by both sides of the cut."""

    mesh: Any  # trimesh.Trimesh, watertight
    basis: CutBasis
    h_fn: Callable[[np.ndarray, np.ndarray], np.ndarray]
    requested_error_mm: float
    realized_error_mm: float
    triangles: int
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Fragment:
    """One connected material body produced by a fracture event."""

    fragment_id: str
    mesh: Any
    volume_mm3: float
    area_mm2: float
    face_origin_kind: np.ndarray      # (F,) uint8: mother surface / interface / ambiguous
    face_source_tri: np.ndarray       # (F,) int32 original mother triangle id or -1
    face_interface_id: np.ndarray     # (F,) int32 interface id or -1
    face_side: np.ndarray             # (F,) int8  (+1 / -1 / 0)
    component_id: int
    is_tiny: bool = False
    parent_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_faces(self) -> int:
        return int(np.asarray(self.mesh.faces).shape[0])


@dataclass
class InterfacePatch:
    """Shared new-fracture surface between two fragments (plan 10.2 / 30.5)."""

    interface_id: int
    fragment_a: str
    fragment_b: str
    area_mm2: float
    sample_points_a: np.ndarray       # (N,3) world mm
    sample_points_b: np.ndarray       # (N,3) world mm
    normals_a: np.ndarray             # (N,3)
    normals_b: np.ndarray             # (N,3)
    gap_p95_mm: float
    normal_angle_p95_deg: float
    ambiguity_area_ratio: float
    ambiguous_area_mm2: float
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class FractureResult:
    fragments: list[Fragment]
    interfaces: list[InterfacePatch]
    event_tree: dict[str, Any]
    debris: list[Fragment]
    parent_id: str
    backend: str
    qa: dict[str, Any]
    cutter_ref: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def fragment(self, fragment_id: str) -> Fragment:
        for frag in self.fragments:
            if frag.fragment_id == fragment_id:
                return frag
        raise KeyError(fragment_id)


# --------------------------------------------------------------------------------------
# Truth (plan 11)
# --------------------------------------------------------------------------------------
RELATION_R2 = "R2"
RELATION_R1 = "R1"
RELATION_R0 = "R0"
RELATION_TINY = "TINY_CONTACT"
RELATION_UNKNOWN = "UNKNOWN"


@dataclass
class RelationEdge:
    fragment_a: str
    fragment_b: str
    kind: str
    interface_id: int | None
    area_mm2: float
    valid: bool = True
    reason: str = ""
    loss_mask: bool = True


@dataclass
class CorrespondenceSample:
    """One supervised correspondence in a shared scan frame (plan 11.3 / 30.6)."""

    fragment_a: str
    fragment_b: str
    point_a_mm: np.ndarray
    point_b_mm: np.ndarray
    normal_a: np.ndarray
    normal_b: np.ndarray
    face_a: int
    face_b: int
    bary_a: np.ndarray
    bary_b: np.ndarray
    association_kind: Literal["EXACT_SURVIVOR", "VERIFIED_RECESSION", "UNKNOWN_MAPPING"]
    weight: float = 1.0
    valid: bool = True
    residual_mm: float = 0.0


@dataclass
class CleanTruth:
    mother_id: str
    event_id: str
    version: int
    relations: dict[tuple[str, str], RelationEdge]
    interfaces: list[InterfacePatch]
    correspondence: list[CorrespondenceSample]
    event_tree: dict[str, Any]
    qa: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)

    def r2_neighbours(self, fragment_id: str) -> set[str]:
        out = set()
        for (a, b), edge in self.relations.items():
            if edge.kind == RELATION_R2:
                if a == fragment_id:
                    out.add(b)
                elif b == fragment_id:
                    out.add(a)
        return out


@dataclass
class PhysicalTruth:
    clean_truth_ref: str
    version: int
    residual: dict[str, Any]
    survivor_patches: dict[str, Any]
    association_counts: dict[str, int]
    current_fit_valid: dict[str, bool]
    qa: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class VisibleLabels:
    physical_truth_ref: str
    version: int
    per_view: dict[str, Any]
    qa: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------------------
# Physical damage (plan 12)
# --------------------------------------------------------------------------------------
@dataclass
class PhysicalComponent:
    component_id: str
    clean_fragment_id: str
    mesh: Any
    volume_mm3: float
    is_representative: bool
    status: Literal["CORE", "DEBRIS"] = "CORE"
    survivor_patch_ref: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class PhysicalResult:
    mother_id: str
    clean_ref: str
    event_id: str
    recipe_id: str
    version: int
    components: list[PhysicalComponent]
    lost_volume_mm3: float
    lost_volume_ratio: float
    representative_map: dict[str, str]          # clean fragment -> component id
    physical_truth: PhysicalTruth | None = None
    qa: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------------------
# Cameras and observation (plan 13 / 14)
# --------------------------------------------------------------------------------------
@dataclass
class CameraProfile:
    profile_id: str
    revision: int
    tier: Literal["GLOBAL", "MID", "LOCAL"]
    working_distance_mm: float
    u_position_mm: float
    K: np.ndarray                     # (3,3) OpenCV convention, pixel centre (0,0)
    dist: np.ndarray                  # (k,) OpenCV distortion coefficients
    image_size: tuple[int, int]       # (W, H)
    fov_mm: tuple[float, float]
    depth_of_field_mm: tuple[float, float]
    focus_setting: str
    calibration_refs: list[str]
    calibrated: bool
    action_cost_seconds: float
    f_number: float = 4.0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def mm_per_pixel(self) -> float:
        return float(self.working_distance_mm / self.K[0, 0])


@dataclass
class ViewFrame:
    view_id: str
    K: np.ndarray                 # (3,3) float64, OpenCV pixel centre convention
    T_WC: np.ndarray              # (4,4) camera-to-world
    image_size: tuple[int, int]
    profile_id: str
    tier: str
    u_position_mm: float
    working_distance_mm: float
    focus_setting: str
    source_kind: str
    camera_model: str = "PINHOLE"
    dist: np.ndarray | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def T_CW(self) -> np.ndarray:
        return np.linalg.inv(self.T_WC)


@dataclass
class RenderOutput:
    """One rendered view: linear scene RGB plus exact geometry channels."""

    rgb_linear: np.ndarray         # (H,W,3) float32 scene-linear
    depth_z: np.ndarray            # (H,W) float32 camera z in mm, NaN/inf where invalid
    id_map: np.ndarray             # (H,W) int32 integer label, -1 background (no interpolation)
    surface_tag: np.ndarray        # (H,W) int16
    visibility: np.ndarray         # (H,W) uint8: 1 visible, 0 background
    uncertain_mask: np.ndarray     # (H,W) bool: mixed/DOF/AA boundary pixels
    backend: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ObsView:
    view_id: str
    frame: ViewFrame
    rgb: np.ndarray                 # (H,W,3) uint8, encoded observation
    rgb_linear: np.ndarray          # (H,W,3) float32 post-sensor linear (pre-response)
    depth_z: np.ndarray             # (H,W) float32 mm, invalid NaN
    id_map: np.ndarray              # (H,W) int32 research label, -1 background
    surface_tag: np.ndarray         # (H,W) int16
    deployment_mask: np.ndarray     # (H,W) bool, obtainable/estimated mask
    roi: np.ndarray | None          # (H,W) bool fracture ROI estimate
    uncertain_mask: np.ndarray      # (H,W) bool
    quality: dict[str, float]
    source_kind: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ObservationResult:
    mother_id: str
    fragment_id: str
    component_id: str
    route: str
    input_profile: str
    observation_id: str
    views: list[ObsView]
    points: np.ndarray              # (N,3) float32 observation-frame points (mm if scale_valid)
    normals: np.ndarray             # (N,3) float32 estimated normals
    point_valid: np.ndarray         # (N,) bool
    normal_valid: np.ndarray        # (N,) bool
    scale_valid: bool
    frame_id: str
    quality: dict[str, float]
    fused_mesh: Any | None = None
    spurious_mask: np.ndarray | None = None
    backend_report: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------------------
# Degradation (plan 15)
# --------------------------------------------------------------------------------------
@dataclass
class DegradationBasis:
    """Frozen per-axis basis shared by all five levels of a paired experiment."""

    axis_id: str
    variant: str
    basis_id: str
    seed_ref: str
    payload: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Measurement:
    axis_id: str
    variant: str
    level: int
    factor_kind: str
    planned: dict[str, Any]
    measured: dict[str, float]
    units: dict[str, str]
    identity: bool
    realized: bool
    valid: bool = True
    na_reason: str | None = None
    failure_code: str | None = None
    source_hash: str = ""
    result_hash: str = ""
    calibration_status: str = "UNCALIBRATED"
    extra: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "axis_id": self.axis_id,
            "variant": self.variant,
            "level": self.level,
            "factor_kind": self.factor_kind,
            "identity": self.identity,
            "realized": self.realized,
            "valid": self.valid,
            "na_reason": self.na_reason,
            "failure_code": self.failure_code,
            "source_hash": self.source_hash,
            "result_hash": self.result_hash,
            "calibration_status": self.calibration_status,
        }
        for key, value in self.planned.items():
            row[f"planned_{key}"] = value
        for key, value in self.measured.items():
            row[f"measured_{key}"] = value
            row[f"unit_{key}"] = self.units.get(key, "")
        return row


# --------------------------------------------------------------------------------------
# Relations / pools / episodes (plan 16 / 17)
# --------------------------------------------------------------------------------------
@dataclass
class GallerySpec:
    pool_id: str
    gallery_version: str
    scope: Literal["FULL", "MATE_REMOVED", "NESTED", "DISTRACTOR_ONLY"]
    lineage_ids: list[str]
    fragment_ids: list[str]
    size_target: int
    split: str
    hash: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryRosterEntry:
    query_id: str
    lineage_cluster: str
    mother_id: str
    fragment_id: str
    split: str
    gallery_id: str
    historical_neighbours: list[str]
    mate_present: bool
    status: str = "PENDING"
    applicability: dict[str, Any] = field(default_factory=dict)


@dataclass
class EpisodeState:
    episode_id: str
    query_id: str
    step: int
    obs_version: int
    revealed_views: list[str]
    candidate_ids: list[str]
    cumulative_cost: dict[str, float]
    done: bool
    stop_reason: str | None = None
    available_actions: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
