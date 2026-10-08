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

# ---------------------------------------------------------------- units / frames
UNIT_MM = "mm"
UNIT_PX = "px"
UNIT_NONE = "1"
FRAME_WORLD = "W_mm"
FRAME_FRAGMENT = "F_mm"
FRAME_SCAN = "S_mm"
FRAME_CAMERA = "C_mm"
FRAME_PIXEL = "pixel_cv_center"

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
