"""Typed configuration schemas: ``synlab.v3``, ``synlab.train.v1``, ``synlab.diagnose.v1``.

Unknown fields are rejected (``extra="forbid"``), units and stage order are validated, and
``data_scope`` / ``input_profile`` / ``observation_route`` / ``experiment_purpose`` /
``release_profile`` are five independent fields that may never be conflated (plan 30.1).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_GENERATION = "synlab.v3"
SCHEMA_TRAIN = "synlab.train.v1"
SCHEMA_DIAGNOSE = "synlab.diagnose.v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=False)


class DataScope(str, Enum):
    SYNTHETIC = "SYNTHETIC"
    REAL = "REAL"


class InputProfile(str, Enum):
    PHONE_RGB = "PHONE_RGB"
    SENSOR_PROXY = "SENSOR_PROXY"
    SENSOR_UPPER_BOUND = "SENSOR_UPPER_BOUND"


class ObservationRoute(str, Enum):
    PHOTO_MVS = "photo_mvs"
    PROXY_SCAN = "proxy_scan"
    IDEAL_VISIBLE = "ideal_visible"


class ExperimentPurpose(str, Enum):
    SANDBOX = "SANDBOX"
    DEVELOPMENT = "DEVELOPMENT"
    CONFIRMATION = "CONFIRMATION"


class ReleaseProfile(str, Enum):
    SANDBOX_CORE = "SANDBOX_CORE"
    PILOT = "PILOT"
    CORE_COVERAGE = "CORE_COVERAGE"
    SCALE_10K = "SCALE_10K"
    SCALE_50K = "SCALE_50K"
    SCALE_100K = "SCALE_100K"
    CALIBRATED_PHONE = "CALIBRATED_PHONE"
    RESEARCH_EVIDENCE = "RESEARCH_EVIDENCE"


class Stage(str, Enum):
    PHYSICAL = "PHYSICAL"
    SCENE = "SCENE"
    OPTICS = "OPTICS"
    SENSOR = "SENSOR"
    ISP = "ISP"
    GEOMETRY_OBS = "GEOMETRY_OBS"
    FEATURE_PROTOCOL = "FEATURE_PROTOCOL"


#: Canonical stage order for the compiler's dependency DAG (plan 30.2).
STAGE_ORDER: dict[str, int] = {
    "MATERIAL": 0, "PHYSICAL": 0, "SCENE": 1, "OPTICS": 2, "SENSOR": 3, "ISP": 3,
    "IMAGE_DERIVATION": 4, "MASK_ESTIMATION": 5, "PHOTO_MVS": 6, "DEPTH_PROXY": 6,
    "GEOMETRY_OBS": 7, "FEATURE_PROTOCOL": 8, "SUPERVISION": 9,
}

SUBSTAGE_ORDER: dict[str, int] = {
    "exposure": 2, "frame_selection": 4, "mask_estimation": 5, "sfm": 6,
    "per_view_geometry": 7, "fusion": 7, "surface": 7, "quality": 8, "feature": 8,
}


class SplitFractions(StrictModel):
    train: float = 0.8
    dev: float = 0.1
    confirm: float = 0.1

    def normalized(self) -> tuple[float, float, float]:
        total = self.train + self.dev + self.confirm
        if total <= 0:
            raise ValueError("split fractions must be positive")
        return self.train / total, self.dev / total, self.confirm / total

    @model_validator(mode="after")
    def _positive(self) -> "SplitFractions":
        for name in ("train", "dev", "confirm"):
            if getattr(self, name) < 0:
                raise ValueError(f"split.{name} must be >= 0")
        if abs(self.train + self.dev + self.confirm - 1.0) > 1e-6:
            raise ValueError("split fractions must sum to 1")
        return self


class IntegrationConfig(StrictModel):
    mode: Literal["standalone", "main_repo_adapter"] = "standalone"
    feature_schema: str = "a12.obs.v1"
    external_contract_ref: str | None = None
    contract_diff_ref: str | None = None


class ImplementationConfig(StrictModel):
    policy: Literal["open_source_first"] = "open_source_first"
    reuse_manifest_ref: str = "docs/a12/reuse_manifest.json"
    require_poc_before_custom: bool = True
    require_gap_evidence: bool = True


class DatasetConfig(StrictModel):
    target_mothers: int = Field(1, ge=1)
    target_fragments_estimate: int = Field(8, ge=1)
    shape_lineage_split: SplitFractions = SplitFractions()
    split_before_generation: bool = True
    replacement_fractures_share_lineage: bool = True
    include_all_components: bool = True
    debris_policy: Literal["quarantine_and_record", "keep"] = "quarantine_and_record"
    # ids are resolved through the registry; unregistered strings are rejected by the compiler
    vessel_ids: list[str] = Field(default_factory=lambda: ["V01"])
    material_ids: list[str] = Field(default_factory=lambda: ["M01"])
    pattern_ids: list[str] = Field(default_factory=lambda: ["PAT01"])
    layer_combo_ids: list[str] = Field(default_factory=list)
    parameter_bounds_ref: str | None = None


class SamplingConfig(StrictModel):
    method: Literal["latin_hypercube", "sobol", "quota_uniform"] = "latin_hypercube"
    quota_policy: Literal["registry_balanced", "uniform", "explicit"] = "registry_balanced"
    seed_stride: int = Field(1, ge=1)
    sobol_power_of_two: bool = True


class PatternConfig(StrictModel):
    coordinate_space: Literal["mother_surface_mm"] = "mother_surface_mm"
    periodic_azimuth: bool = True
    geometry_before_fracture: bool = True
    antialias: Literal["analytic_or_mipmap", "analytic", "mipmap"] = "analytic_or_mipmap"
    height_policy: Literal["relief", "engrave", "none"] = "none"


class FractureConfig(StrictModel):
    backend: Literal["plane_shared_cut", "rough_shared_cut", "warped_partition", "secondary_fracture",
                     "fracture_modes", "warp_voronoi_cut"] = "rough_shared_cut"
    target_piece_range: tuple[int, int] = (8, 20)
    min_feature_wavelength_mm: float = Field(0.24, gt=0)
    shared_surface_max_error_mm: float = Field(0.01, gt=0)
    max_attempts: int = Field(3, ge=1)
    secondary_probability: float = Field(0.0, ge=0, le=1)
    keep_parent_history: bool = True
    rough_amplitude_mm: tuple[float, float] = (0.02, 0.3)
    seed_count_range: tuple[int, int] = (8, 30)

    @model_validator(mode="after")
    def _range(self) -> "FractureConfig":
        lo, hi = self.target_piece_range
        if lo < 2 or hi < lo:
            raise ValueError("target_piece_range must satisfy 2 <= lo <= hi")
        if self.min_feature_wavelength_mm > 3.0:
            raise ValueError("min_feature_wavelength_mm outside supported band (<= 3 mm)")
        return self


class PhysicalConfig(StrictModel):
    recipe_registry_ref: str | None = None
    preserve_clean_assets: bool = True
    recipes: list[str] = Field(default_factory=list)


class ObservationConfig(StrictModel):
    input_profile: InputProfile = InputProfile.SENSOR_PROXY
    routes: list[ObservationRoute] = Field(default_factory=lambda: [ObservationRoute.PROXY_SCAN])
    views_per_fragment: int = Field(12, ge=1)
    image_long_edge_px: int = Field(1024, ge=32)
    point_count: int = Field(8192, ge=0)
    camera_profile_ref: str | None = None
    persist_depth: Literal["selected_qa_only", "all", "none"] = "selected_qa_only"
    persist_view_geometry: bool = False
    persist_fused_geometry: bool = True
    truth_channels_role: Literal["research_label_only"] = "research_label_only"
    renderer: Literal["auto", "software_rasterizer", "blender"] = "auto"


class ResourcesConfig(StrictModel):
    cpu_workers: int = Field(2, ge=1)
    threads_per_worker: int = Field(2, ge=1)
    cpu_rss_budget_gb: float = Field(30.0, gt=0)
    gpu_device: int = 0
    gpu_concurrency: int = Field(1, ge=1)
    gpu_budget_gb: float = Field(26.0, gt=0)
    disk_soft_fraction: float = 0.70
    disk_restrict_fraction: float = 0.80
    disk_stop_fraction: float = 0.90
    reserve_temp_peak: bool = True

    @model_validator(mode="after")
    def _ordered(self) -> "ResourcesConfig":
        if not (self.disk_soft_fraction < self.disk_restrict_fraction < self.disk_stop_fraction <= 1.0):
            raise ValueError("disk fractions must satisfy soft < restrict < stop <= 1")
        return self


class StorageConfig(StrictModel):
    root: str = "data/a12"
    database: str | None = None
    shard_target_mb: int = Field(512, ge=1)
    mutable_release: Literal[False] = False


class QualityConfig(StrictModel):
    protocol_ref: str | None = None
    fail_closed: bool = True
    freeze_before_confirmation: bool = True


class GenerationSpec(StrictModel):
    """``synlab.v3`` generation configuration (plan 22.1)."""

    schema_id: Literal["synlab.v3"] = Field(default=SCHEMA_GENERATION, alias="schema")
    data_scope: DataScope = DataScope.SYNTHETIC
    release_profile: ReleaseProfile = ReleaseProfile.SANDBOX_CORE
    experiment_purpose: ExperimentPurpose = ExperimentPurpose.DEVELOPMENT
    input_profile: InputProfile | None = None
    observation_route: ObservationRoute | None = None
    master_seed: int = 20261001
    units: Literal["mm"] = "mm"
    integration: IntegrationConfig = IntegrationConfig()
    implementation: ImplementationConfig = ImplementationConfig()
    dataset: DatasetConfig = DatasetConfig()
    sampling: SamplingConfig = SamplingConfig()
    pattern: PatternConfig = PatternConfig()
    fracture: FractureConfig = FractureConfig()
    physical: PhysicalConfig = PhysicalConfig()
    observation: ObservationConfig = ObservationConfig()
    resources: ResourcesConfig = ResourcesConfig()
    storage: StorageConfig = StorageConfig()
    quality: QualityConfig = QualityConfig()
    degraded_recipe_refs: list[str] = Field(default_factory=list)
    notes: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _cross_checks(self) -> "GenerationSpec":
        if self.units != "mm":
            raise ValueError("authoritative geometry must be in mm")
        if self.integration.mode == "standalone" and self.integration.external_contract_ref is not None:
            raise ValueError("standalone integration cannot reference an external contract")
        if self.integration.mode == "main_repo_adapter" and not self.integration.external_contract_ref:
            raise ValueError("main_repo_adapter requires external_contract_ref (verified schema)")
        if self.input_profile is not None and self.observation.input_profile != self.input_profile:
            raise ValueError("top-level input_profile conflicts with observation.input_profile")
        if self.observation_route is not None and self.observation_route not in self.observation.routes:
            raise ValueError("observation_route must be one of observation.routes")
        if self.release_profile is ReleaseProfile.CALIBRATED_PHONE and self.data_scope is not DataScope.REAL:
            raise ValueError("CALIBRATED_PHONE requires data_scope=REAL")
        return self


class RetreivalConfig(StrictModel):
    first_stage: Literal["normalized_dual_encoder", "classical_descriptor"] = "normalized_dual_encoder"
    refinement: Literal["observed_local_pair_head", "none", "classical_local"] = "observed_local_pair_head"
    candidate_pool_size: int = Field(200, ge=1)
    score_sources_separate: bool = True


class InitializationConfig(StrictModel):
    kind: Literal["existing_public_or_project_backbone", "random", "classical"] = "random"
    checkpoint_ref: str | None = None
    require_sha256: bool = True
    allow_random_fallback: bool = False

    @model_validator(mode="after")
    def _ckpt(self) -> "InitializationConfig":
        if self.kind == "existing_public_or_project_backbone" and not self.checkpoint_ref:
            raise ValueError("approved initializer requires checkpoint_ref; do not fall back silently")
        return self


class TrainInputs(StrictModel):
    feature_schema: str = "a12.obs.v1"
    feature_schema_requires_verified_adapter: bool = True
    input_profile: InputProfile = InputProfile.SENSOR_PROXY
    observation_route: ObservationRoute = ObservationRoute.PROXY_SCAN
    quality_source: Literal["OBS_EST", "GT_ORACLE"] = "OBS_EST"
    roi_source: Literal["observed_estimator", "MANUAL_OBS", "HEURISTIC_OBS", "ORACLE_ROI"] = "observed_estimator"
    local_token_budget: int = Field(256, ge=1)
    oracle_features: Literal[False] = False


class TrainSampling(StrictModel):
    queries_per_microbatch: int = Field(2, ge=1)
    positive_limit: int = Field(2, ge=1)
    legal_negative_limit: int = Field(8, ge=0)
    negative_mix: dict[str, float] = Field(default_factory=lambda: {"R1": 0.5, "R0": 0.5})
    exclude_all_R2_and_unknown: Literal[True] = True
    deduplicate_fragment_encoding: bool = True

    @model_validator(mode="after")
    def _mix(self) -> "TrainSampling":
        unknown = set(self.negative_mix) - {"R1", "R0"}
        if unknown:
            raise ValueError(f"negative_mix may only use R1/R0, got {sorted(unknown)}")
        return self


class OptimizationConfig(StrictModel):
    optimizer: Literal["AdamW", "SGD"] = "AdamW"
    head_lr: float = Field(1e-4, gt=0)
    backbone_lr: float = Field(1e-5, gt=0)
    weight_decay: float = Field(0.01, ge=0)
    warmup_fraction: float = Field(0.05, ge=0, le=0.5)
    gradient_clip_norm: float = Field(1.0, gt=0)
    accumulation_steps: int = Field(1, ge=1)
    max_steps: int = Field(5000, ge=1)
    precision: Literal["fp32", "bf16_if_verified"] = "fp32"


class LossWeights(StrictModel):
    rank: float = 1.0
    view: float = 0.1
    correspondence: float = 0.0
    quality: float = 0.0
    contradiction: float = 0.0


class CurriculumConfig(StrictModel):
    enabled: bool = False
    comparison_ref: str | None = None
    clean_minimum_fraction: float = Field(0.2, ge=0, le=1)


class EvaluationConfig(StrictModel):
    split: Literal["train", "dev", "confirm"] = "dev"
    interval_steps: int = Field(500, ge=1)
    candidate_pool_ref: str | None = None
    top_k: list[int] = Field(default_factory=lambda: [1, 5, 10, 20, 50])


class CheckpointConfig(StrictModel):
    interval_steps: int = Field(500, ge=1)
    save_rng_sampler_and_data_hash: Literal[True] = True


class TrainingSpec(StrictModel):
    schema_id: Literal["synlab.train.v1"] = Field(default=SCHEMA_TRAIN, alias="schema")
    run_name: str
    train_seed: int = 11
    release_ref: str
    split: Literal["train"] = "train"
    release_profile_required: ReleaseProfile = ReleaseProfile.PILOT
    stage: Literal["P0", "P1", "P2", "P3", "P4"] = "P0"
    migration_group: Literal["T0_SCRATCH_REAL", "T1_PUBLIC_REAL", "T2_PUBLIC_SYN_REAL",
                             "T3_PUBLIC_MIXED_REAL"] | None = None
    retrieval: RetreivalConfig = RetreivalConfig()
    initialization: InitializationConfig = InitializationConfig()
    inputs: TrainInputs = TrainInputs()
    sampling: TrainSampling = TrainSampling()
    optimization: OptimizationConfig = OptimizationConfig()
    losses: LossWeights = LossWeights()
    curriculum: CurriculumConfig = CurriculumConfig()
    evaluation: EvaluationConfig = EvaluationConfig()
    checkpoint: CheckpointConfig = CheckpointConfig()
    device: Literal["cpu", "cuda", "auto"] = "auto"

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DiagnosticStatistics(StrictModel):
    unit: Literal["shape_lineage"] = "shape_lineage"
    bootstrap_replicates: int = Field(10000, ge=100)
    confidence: float = Field(0.95, gt=0, lt=1)
    multiple_testing: Literal["holm_for_registered_comparisons", "none"] = "holm_for_registered_comparisons"
    report_all_attempts: Literal[True] = True


class ConfirmationConfig(StrictModel):
    open: bool = False
    require_frozen_protocol: Literal[True] = True


class DiagnosticSpec(StrictModel):
    schema_id: Literal["synlab.diagnose.v1"] = Field(default=SCHEMA_DIAGNOSE, alias="schema")
    protocol_id: str
    checkpoint_ref: str | None = None
    release_ref: str | None = None
    evaluation_split: Literal["train", "dev", "confirm"] = "dev"
    candidate_pool_ref: str | None = None
    axes: list[str] = Field(default_factory=list)
    levels: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    paired_basis: bool = True
    input_profile: InputProfile = InputProfile.SENSOR_PROXY
    observation_route: ObservationRoute = ObservationRoute.PROXY_SCAN
    perturbation_side: Literal["QUERY_ONLY", "QUERY_AND_CANDIDATE", "CANDIDATE_ONLY"] = "QUERY_ONLY"
    variant_map_ref: str | None = None
    query_roster_ref: str | None = None
    include_pipeline_failures_in_primary_denominator: Literal[True] = True
    fixed_query_ids: Literal[True] = True
    seed_kind: Literal["observation_basis"] = "observation_basis"
    seeds: list[int] = Field(default_factory=lambda: [11])
    training_replicates_ref: str | None = None
    metrics: list[str] = Field(default_factory=lambda: ["HitAtK", "CovRecallAtK", "PoolCovAtM"])
    statistics: DiagnosticStatistics = DiagnosticStatistics()
    confirmation: ConfirmationConfig = ConfirmationConfig()

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("axes")
    @classmethod
    def _axes(cls, value: list[str]) -> list[str]:
        for axis in value:
            if axis not in AXIS_IDS:
                raise ValueError(f"unregistered axis id {axis}")
        return value


class DegradationOperatorSpec(StrictModel):
    axis_id: str
    stage: Stage
    level: int = Field(0, ge=0, le=4)
    variant: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("axis_id")
    @classmethod
    def _axis(cls, value: str) -> str:
        if value not in AXIS_IDS:
            raise ValueError(f"unregistered axis id {value}")
        return value


class DegradationRecipeSpec(StrictModel):
    schema_id: Literal["synlab.v3"] = Field(default=SCHEMA_GENERATION, alias="schema")
    recipe_id: str
    basis_policy: Literal["paired_across_levels", "independent"] = "paired_across_levels"
    source_role: Literal["clean", "physical", "observed"] = "clean"
    operators: list[DegradationOperatorSpec] = Field(default_factory=list)
    measurement: dict[str, Any] = Field(default_factory=lambda: {
        "save_baseline": True, "save_effect_statistics": True,
        "save_label_versions": True, "save_spurious_mask": "research_label_only",
    })

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


VESSEL_IDS = [f"V{i:02d}" for i in range(1, 25)]
MATERIAL_IDS = [f"M{i:02d}" for i in range(1, 13)]
PATTERN_IDS = [f"PAT{i:02d}" for i in range(1, 17)]
LAYER_COMBO_IDS = ["L01", "L02", "L03", "L04"]
FRACTURE_BACKEND_IDS = ["plane_shared_cut", "rough_shared_cut", "warped_partition",
                        "secondary_fracture", "fracture_modes", "warp_voronoi_cut"]
AXIS_IDS = (
    [f"P{i:02d}" for i in range(1, 9)]
    + [f"I{i:02d}" for i in range(1, 11)]
    + [f"G{i:02d}" for i in range(1, 9)]
    + [f"X{i:02d}" for i in range(1, 6)]
)
