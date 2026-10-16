"""Asset role and schema identifiers shared across modules (prevents semantic drift)."""

from __future__ import annotations

# ---------------------------------------------------------------- schema ids
SCHEMA_MOTHER = "synlab.mother.v1"
SCHEMA_MATERIAL = "synlab.material.v1"
SCHEMA_PATTERN = "synlab.pattern.v1"
SCHEMA_CUTTER = "synlab.cutter.v1"
SCHEMA_FRAGMENT = "synlab.fragment.v1"
SCHEMA_TRUTH_CLEAN = "synlab.truth.clean.v1"
SCHEMA_TRUTH_PHYSICAL = "synlab.truth.physical.v1"
SCHEMA_TRUTH_VISIBLE = "synlab.truth.visible.v1"
SCHEMA_PHYSICAL = "synlab.physical.v1"
SCHEMA_OBS = "synlab.obs.v1"
SCHEMA_FEATURE = "a12.obs.v1"
SCHEMA_CAMERA_PROFILE = "synlab.camera_profile.v1"
SCHEMA_MEASUREMENT = "synlab.measurement.v1"
SCHEMA_POOL = "synlab.pool.v1"
SCHEMA_ROSTER = "synlab.roster.v1"
SCHEMA_EPISODE = "synlab.episode.v1"
SCHEMA_CHECKPOINT = "synlab.checkpoint.v1"
SCHEMA_REPORT = "synlab.report.v1"
SCHEMA_QA = "synlab.qa.v1"
SCHEMA_COVERAGE = "synlab.coverage.v1"
#: The simulated excavation context of one batch (plan t088: "模拟出土区、层位、袋号/坑位等可控
#: 元数据").  Declared here, and every value it carries is marked ``simulated=true``.
SCHEMA_CONTEXT = "synlab.context.v1"
# --- contract-debt declarations: schema ids that real products already use but that were
# --- never declared here (docs/a12/modality_census.md §6.1b).  Declarations only: no existing
# --- asset is renamed, re-stamped or rewritten by adding these names.
SCHEMA_LABELS = "synlab.labels.v1"
SCHEMA_PROVENANCE = "synlab.provenance.v1"
SCHEMA_DISPLAY_GLB = "synlab.display_glb.v1"

# ---------------------------------------------------------------- roles
ROLE_MOTHER_MESH = "mother_mesh"
ROLE_MOTHER_META = "mother_meta"
ROLE_MATERIAL_PROFILE = "material_profile"
ROLE_PATTERN_RECIPE = "pattern_recipe"
ROLE_PATTERN_CHANNELS = "pattern_channels"
ROLE_PATTERN_AUDIT = "pattern_audit"
ROLE_CUTTER = "cutter_mesh"
ROLE_FRAGMENT_MESH = "fragment_mesh"
ROLE_CLEAN_TRUTH = "clean_truth"
ROLE_PHYSICAL_COMPONENT = "physical_component"
ROLE_PHYSICAL_RESULT = "physical_result"
ROLE_PHYSICAL_TRUTH = "physical_truth"
ROLE_VISIBLE_LABELS = "visible_labels"
ROLE_OBS_VIEW = "obs_view"
ROLE_OBS_RESULT = "obs_result"
ROLE_OBS_FUSED = "obs_fused_geometry"
ROLE_FEATURE_BUNDLE = "feature_bundle"
#: Degradation operator measurements (one asset per axis level).  A degraded bundle is the
#: *answer side* of a factor experiment: its metadata carries ``axis_id``/``level``/``variant``
#: by design, and ``FORBIDDEN_FEATURE_FIELDS`` lists exactly those keys, so it may never be
#: committed under :data:`ROLE_FEATURE_BUNDLE` (plan 4.4, 30.12).
ROLE_DEGRADE_MEASUREMENT = "degrade_measurement"
ROLE_LABEL_BUNDLE = "label_bundle"
ROLE_PROVENANCE = "provenance"
ROLE_POOL = "relation_pool"
ROLE_ROSTER = "query_roster"
ROLE_EPISODE = "episode_trace"
ROLE_CHECKPOINT = "train_checkpoint"
ROLE_TRAIN_METRICS = "train_metrics"
ROLE_DIAG_REPORT = "diagnostic_report"
ROLE_OPERATOR_AUDIT = "operator_audit"
ROLE_QA_REPORT = "qa_report"
ROLE_COVERAGE = "coverage"
ROLE_RUN_SPEC = "run_spec"
ROLE_DISPLAY_LOD = "display_lod_glb"
ROLE_MVS_RESULT = "mvs_result"
#: One simulated excavation context per batch (plan t088).  Carries no geometry payload: its
#: fields are the controlled metadata a real excavation would hand over with the sherds.
ROLE_CONTEXT_PACK = "context_pack"

# ---------------------------------------------------------------- units / frames
UNIT_MM = "mm"
UNIT_PX = "px"
UNIT_NONE = "1"
# --- contract-debt declarations: ``m`` (118 ``display_lod_glb`` assets) was used by real
# --- products but never declared (docs/a12/modality_census.md §6.1b).
UNIT_M = "m"
FRAME_WORLD = "W_mm"
FRAME_FRAGMENT = "F_mm"
FRAME_SCAN = "S_mm"
FRAME_CAMERA = "C_mm"
FRAME_PIXEL = "pixel_cv_center"
#: Y-up metre frame of the display layer (``display_lod_glb``).
FRAME_Y_UP_M = "Y_up_m"
#: Explicit "this asset has no spatial frame" marker used by the provenance/qa roles.
FRAME_NONE = "none"

#: Every schema id this module declares.  A real product whose ``assets.schema`` is not in here
#: is contract drift, and ``tests/a12/storage`` asserts the set against the real stores.
DECLARED_SCHEMAS: frozenset[str] = frozenset({
    SCHEMA_MOTHER, SCHEMA_MATERIAL, SCHEMA_PATTERN, SCHEMA_CUTTER, SCHEMA_FRAGMENT,
    SCHEMA_TRUTH_CLEAN, SCHEMA_TRUTH_PHYSICAL, SCHEMA_TRUTH_VISIBLE, SCHEMA_PHYSICAL,
    SCHEMA_OBS, SCHEMA_FEATURE, SCHEMA_CAMERA_PROFILE, SCHEMA_MEASUREMENT, SCHEMA_POOL,
    SCHEMA_ROSTER, SCHEMA_EPISODE, SCHEMA_CHECKPOINT, SCHEMA_REPORT, SCHEMA_QA,
    SCHEMA_COVERAGE, SCHEMA_CONTEXT, SCHEMA_LABELS, SCHEMA_PROVENANCE, SCHEMA_DISPLAY_GLB,
})
#: Every unit value this module declares.
DECLARED_UNITS: frozenset[str] = frozenset({UNIT_MM, UNIT_PX, UNIT_NONE, UNIT_M})
#: Every frame value this module declares (``"none"`` included: it is a real written value).
DECLARED_FRAMES: frozenset[str] = frozenset({
    FRAME_WORLD, FRAME_FRAGMENT, FRAME_SCAN, FRAME_CAMERA, FRAME_PIXEL, FRAME_Y_UP_M, FRAME_NONE,
})

# ---------------------------------------------------------------- source kinds
SOURCE_RAW_CAPTURE = "RAW_CAPTURE"
SOURCE_CALIBRATED = "CALIBRATED"
SOURCE_OBS_EST = "OBS_EST"
SOURCE_MANUAL_OBS = "MANUAL_OBS"
SOURCE_SENSOR_SIM = "SENSOR_SIM"
SOURCE_GT_ORACLE = "GT_ORACLE"

# ---------------------------------------------------------------- quality profiles
QUALITY_PROFILES = ("SY-Q0_OBS", "Q1", "Q2", "Q3", "Q4", "Q5", "ORACLE_WORLD")

#: Fields that may never enter a model forward pass (plan 4.4, 30.12).
FORBIDDEN_FEATURE_FIELDS = frozenset({
    "parent_id", "object_id", "bag_id", "seed", "seed_ref", "generator_family_id",
    "interface_id", "relation", "historical_R2", "mate_present", "truth_pose", "T_WF",
    "clean_hidden_surface", "gt_thickness", "gt_normal", "gt_curvature",
    "damage_strength", "spurious_mask", "hard_case_tag", "lineage_id", "mother_id",
    "fragment_id", "event_id", "split", "variant", "axis_id", "level",
})
