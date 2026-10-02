"""Maximal ("full" flavour) export of an asset store, plus its ablation index.

Why a second exporter and not another flag on :mod:`synlab.storage.export`
------------------------------------------------------------------------
``export_training_package`` answers *"what may a training job consume?"*: it applies a view
channel policy, an opaque-name map, a token budget and a supervision split.  This module
answers a different question -- *"what does this store actually contain, modality by
modality, for every fragment?"* -- because the ablation programme needs to switch single
data sources on and off and measure whether they help or hurt.  Nothing here is trimmed:
every array of every asset of the scanned store is written, regrouped by
``(role, channel family)`` so a group can be ablated without touching the others.

Honesty rules this module implements
------------------------------------
* **No invented channel.**  A modality is *present* only when at least one real asset
  carries it; otherwise it is listed under ``missing`` with the concrete condition that
  would unlock it.  ``manifest["modalities"]`` is therefore a measurement, not a wish list.
* **No truth in the deployment view.**  Every modality carries
  ``deployment_view_allowed`` and the reason.  The permission is derived from the real
  policy document ``synlab/schemas/view_channels.json`` (read through
  :func:`synlab.storage.export.load_channel_policy`), whose path and byte hash are recorded
  in the manifest; truth/label roles are never allowed regardless of that document.
* **``synthetic_only`` is measured, not asserted.**  It is set from the asset's own
  metadata (``source_kind``/``data_scope``/``real_capture``); the manifest also reports how
  many assets claim a real capture, so a reader can see the basis of the flag.
* **Derived artefacts are labelled.**  The only derived geometry written here is the
  fracture-surface subset of an authoritative mesh; its exact formula is recorded in
  ``derivation`` and the standalone ``interface_mesh`` *asset* that does not exist anywhere
  is still reported as missing.

The package layout
------------------
``<out>/manifest.json``
    The modality registry (one row per ``(role, family)``), the per-fragment index, the
    file table with sizes and hashes, the permission block and the measured findings.
``<out>/ablation_index.json``
    Modalities regrouped into the dimensions an experiment can switch on and off.
``<out>/fragments/<fragment_id>/<scope>/<modality_id>__<asset_id>.npz``
    The payloads, one file per (asset, modality).  An array appears in exactly one file.
``<out>/mothers/<mother_id>/...`` and ``<out>/store/<role>/...``
    Assets that are scoped to a mother or to the whole store rather than to one fragment.
``<out>/assets/<asset_id>/meta.json`` and the verbatim non-array blobs (``glb.bin``, ...)
    The provenance/manifest bytes of the source asset, copied unchanged.
``<out>/README.md``
    The measured summary, generated from the manifest.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import struct
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import numpy as np

from ..canonical import hash_bytes, hash_file, hash_json
from ..errors import ErrorCode, SynLabError
from ..roles import (
    FORBIDDEN_FEATURE_FIELDS,
    ROLE_CONTEXT_PACK,
    ROLE_CLEAN_TRUTH,
    ROLE_CUTTER,
    ROLE_DEGRADE_MEASUREMENT,
    ROLE_DISPLAY_LOD,
    ROLE_EPISODE,
    ROLE_FEATURE_BUNDLE,
    ROLE_FRAGMENT_MESH,
    ROLE_LABEL_BUNDLE,
    ROLE_MOTHER_MESH,
    ROLE_MVS_RESULT,
    ROLE_OBS_FUSED,
    ROLE_OBS_RESULT,
    ROLE_OBS_VIEW,
    ROLE_PATTERN_CHANNELS,
    ROLE_PATTERN_RECIPE,
    ROLE_PHYSICAL_COMPONENT,
    ROLE_PHYSICAL_RESULT,
    ROLE_PHYSICAL_TRUTH,
    ROLE_POOL,
    ROLE_PROVENANCE,
    ROLE_QA_REPORT,
    ROLE_ROSTER,
    ROLE_VISIBLE_LABELS,
)
from .store import QA_PASS, AssetStore  # noqa: F401  (AssetStore is the writer; re-exported for callers)

__all__ = [
    "ABLATION_INDEX_SCHEMA",
    "ABLATION_GROUPS",
    "DEFAULT_OUT_ROOT",
    "FLAVOR_FULL",
    "FLAVORS",
    "FULL_MANIFEST_SCHEMA",
    "FULL_PACKAGE_SCHEMA",
    "MODALITY_CATALOGUE",
    "build_ablation_index",
    "check_full_package",
    "deployment_channel_policy",
    "export_full_package",
    "family_of",
    "load_full_manifest",
    "main",
    "render_readme",
]

# --------------------------------------------------------------------------------------
# flavour + schema identifiers
# --------------------------------------------------------------------------------------
#: The only flavour this module writes: every modality the store holds, nothing trimmed.
FLAVOR_FULL = "full"
FLAVORS: tuple[str, ...] = (FLAVOR_FULL,)

FULL_PACKAGE_SCHEMA = "synlab.full_package.v1"
FULL_MANIFEST_SCHEMA = "synlab.full_package_manifest.v1"
ABLATION_INDEX_SCHEMA = "synlab.ablation_index.v1"
FULL_CARD_SCHEMA = "synlab.full_package_card.v1"

#: Default output root named by the ablation plan (``data/a12_exports/full``).
DEFAULT_OUT_ROOT = Path("data") / "a12_exports" / "full"

#: Arrays larger than this many elements get their shape/dtype recorded but no
#: min/max/histogram pass (the pass is reported as skipped rather than faked).
STATS_MAX_ELEMENTS = 2_000_000
#: Integer arrays with more distinct values than this get a count, not a histogram.
HISTOGRAM_MAX_UNIQUE = 64
#: Arrays whose total size is below this are written compressed.
COMPRESS_BELOW_BYTES = 32 * 1024 * 1024

#: Observation-array names the deployment geometry view is documented to carry
#: (``synlab/storage/export.py`` writes ``deploy/geometry/index.json`` with exactly these).
GEOMETRY_DEPLOY_ARRAYS = frozenset({
    "points", "normals", "point_valid", "normal_valid", "scale_valid", "frame_id",
})

#: Roles whose payload *is* a truth layer (plan 30.12: never the deployment view).
TRUTH_ROLES = frozenset({ROLE_CLEAN_TRUTH, ROLE_PHYSICAL_TRUTH, ROLE_VISIBLE_LABELS})
#: Roles whose payload is a supervision label rather than an observation.
LABEL_ROLES = frozenset({ROLE_LABEL_BUNDLE, ROLE_POOL, ROLE_ROSTER})

SCOPE_FRAGMENT = "fragment"
SCOPE_MOTHER = "mother"
SCOPE_STORE = "store"

#: Directory inside the package for each scope.
SCOPE_DIRS = {SCOPE_FRAGMENT: "fragments", SCOPE_MOTHER: "mothers", SCOPE_STORE: "store"}

#: Roles that carry no arrays at all: their whole payload is the ``meta.json`` bytes.
METADATA_ONLY_ROLES = frozenset({ROLE_PROVENANCE, ROLE_PATTERN_RECIPE, ROLE_ROSTER})

#: ``source_kind`` values that would mean "not synthetic".  Anything else is synthetic.
REAL_SOURCE_KINDS = frozenset({"RAW_CAPTURE", "CALIBRATED", "MANUAL_OBS"})

_CLEAN_REF_RE = re.compile(r"^(?P<mother>[A-Za-z0-9_]+):(?P<event>[A-Za-z0-9_]+):v\d+$")
_EVENT_RE = re.compile(r"^(?P<mother>.+)_E\d+$")
#: A lineage label only counts as a *mother* when it really looks like one
#: (``LIN0000_V10_M11_PAT15``).  Free-form lineage tags such as ``audit_lineage`` or
#: ``a12_demo`` are bookkeeping labels, not mothers, and must not create a fake mother scope.
_MOTHER_RE = re.compile(r"^[A-Za-z0-9]+_V\d+_M\d+")
_VIEW_RE = re.compile(r"^(?P<view>v\d{3})\.(?P<channel>.+)$")
_FRAME_RE = re.compile(r"^(?P<prefix>payload\.)?frames\.(?P<index>\d+)\.(?P<channel>.+)$")


# --------------------------------------------------------------------------------------
# modality catalogue
# --------------------------------------------------------------------------------------
def _cat(modality_id: str, title: str, *, role: str, unit: str = "1", frame: str = "none",
         is_label: bool = False, is_truth: bool = False, derived: bool = False,
         unlock: str = "", note: str = "") -> dict[str, Any]:
    return {
        "modality_id": modality_id, "title": title, "role": role, "unit": unit, "frame": frame,
        "is_label": bool(is_label), "is_truth": bool(is_truth), "derived": bool(derived),
        "unlock_condition": unlock, "note": note,
    }


#: Every modality this exporter knows how to write.  A modality that has no data in the
#: scanned store is reported as ``missing`` with its declared ``unlock_condition``; a
#: family found in the store but absent from this table is still exported and marked
#: ``catalogue_known=false`` (nothing is dropped for being undocumented).
MODALITY_CATALOGUE: tuple[dict[str, Any], ...] = (
    # --- authoritative 3D geometry -----------------------------------------------------
    _cat("mother_mesh.vertices", "authoritative mother mesh vertices", role=ROLE_MOTHER_MESH,
         unit="mm", frame="W_mm",
         unlock="produce a mother_mesh asset (role mother_mesh) in this store"),
    _cat("mother_mesh.faces", "authoritative mother mesh faces", role=ROLE_MOTHER_MESH,
         unit="mm", frame="W_mm",
         unlock="produce a mother_mesh asset (role mother_mesh) in this store"),
    _cat("mother_mesh.face_attrs", "mother mesh per-face attributes (surface_tag/component_id)",
         role=ROLE_MOTHER_MESH, unit="mm", frame="W_mm",
         unlock="produce a mother_mesh asset carrying mesh.face__* arrays"),
    _cat("fragment_mesh.vertices", "authoritative fragment mesh vertices", role=ROLE_FRAGMENT_MESH,
         unit="mm", frame="W_mm", unlock="produce a fragment_mesh asset in this store"),
    _cat("fragment_mesh.faces", "authoritative fragment mesh faces", role=ROLE_FRAGMENT_MESH,
         unit="mm", frame="W_mm", unlock="produce a fragment_mesh asset in this store"),
    _cat("fragment_mesh.face_attrs",
         "fragment per-face fracture provenance (origin_kind/interface_id/side/ambiguous)",
         role=ROLE_FRAGMENT_MESH, unit="mm", frame="W_mm",
         unlock="produce a fragment_mesh asset carrying mesh.face__origin_kind"),
    _cat("fragment_mesh.interface_faces",
         "DERIVED fracture-surface subset of the fragment mesh",
         role=ROLE_FRAGMENT_MESH, unit="mm", frame="W_mm", derived=True,
         unlock="a fragment_mesh whose mesh.face__origin_kind has at least one INTERFACE(1) face",
         note="derived by np.flatnonzero(face__origin_kind == 1); no standalone interface mesh "
              "asset exists in any store, which is reported separately"),
    _cat("physical_component.mesh", "damaged physical component mesh (fragment frame)",
         role=ROLE_PHYSICAL_COMPONENT, unit="mm", frame="F_mm",
         unlock="produce a physical_component asset (P/I/G/X axis materialisation)"),
    _cat("physical_component.mesh_face_attrs", "physical component per-face attributes",
         role=ROLE_PHYSICAL_COMPONENT, unit="mm", frame="F_mm",
         unlock="produce a physical_component asset carrying payload.mesh.face__* arrays"),
    _cat("physical_component.appearance", "physical component texel appearance fields",
         role=ROLE_PHYSICAL_COMPONENT, unit="mm", frame="F_mm",
         unlock="produce a physical_component asset with a payload.appearance block"),
    _cat("physical_result.measurement", "physical (damage) operator measurement values",
         role=ROLE_PHYSICAL_RESULT, unit="mm", frame="F_mm",
         unlock="run a physical operator and commit its physical_result"),
    # --- fracture truth ----------------------------------------------------------------
    _cat("clean_truth.iface_geometry",
         "per-interface fracture geometry truth (iface_area_mm2 / gap / normal p95 / points)",
         role=ROLE_CLEAN_TRUTH, unit="mm", frame="W_mm", is_truth=True,
         unlock="produce a clean_truth asset with iface_* arrays (fracture event truth)"),
    _cat("clean_truth.corr_geometry",
         "per-sample fracture correspondence (corr_point_a/b, normals, bary, residual)",
         role=ROLE_CLEAN_TRUTH, unit="mm", frame="W_mm", is_truth=True,
         unlock="produce a clean_truth asset with corr_* arrays"),
    _cat("physical_truth.corr_geometry",
         "post-damage correspondence truth (corr_* carried by the physical layer)",
         role=ROLE_PHYSICAL_TRUTH, unit="mm", frame="W_mm", is_truth=True,
         unlock="produce a physical_truth asset with corr_* arrays"),
    _cat("visible_labels.visible_counts",
         "per-sample visibility counts of the correspondence in the delivered views",
         role=ROLE_VISIBLE_LABELS, unit="1", frame="W_mm", is_truth=True, is_label=True,
         unlock="produce a visible_labels asset (role visible_labels)"),
    # --- 2D observation channels -------------------------------------------------------
    _cat("obs_result.rgb", "delivered RGB view (ISP + optional JPEG round trip)",
         role=ROLE_OBS_RESULT, unit="count", frame="pixel_cv_center",
         unlock="produce an obs_result asset (synlab/observe routes) in this store"),
    _cat("obs_result.rgb_linear", "scene-linear radiance before the ISP",
         role=ROLE_OBS_RESULT, unit="1", frame="pixel_cv_center",
         unlock="produce an obs_result asset carrying rgb_linear"),
    _cat("obs_result.depth_z", "camera-z depth in millimetres", role=ROLE_OBS_RESULT,
         unit="mm", frame="pixel_cv_center",
         unlock="produce an obs_result asset carrying depth_z"),
    _cat("obs_result.id_map", "per-face integer label map (-1 background)", role=ROLE_OBS_RESULT,
         unit="1", frame="pixel_cv_center", unlock="produce an obs_result asset carrying id_map"),
    _cat("obs_result.surface_tag", "face-attribute tag map (0 outer_wall / 2 rim / 6 attachment)",
         role=ROLE_OBS_RESULT, unit="1", frame="pixel_cv_center",
         unlock="produce an obs_result asset carrying surface_tag"),
    _cat("obs_result.deployment_mask", "pixels a deployment profile may obtain",
         role=ROLE_OBS_RESULT, unit="1", frame="pixel_cv_center",
         unlock="produce an obs_result asset carrying deployment_mask"),
    _cat("obs_result.roi", "research region of interest", role=ROLE_OBS_RESULT, unit="1",
         frame="pixel_cv_center", unlock="produce an obs_result asset carrying roi"),
    _cat("obs_result.uncertain_mask", "pixels not attributable to one surface",
         role=ROLE_OBS_RESULT, unit="1", frame="pixel_cv_center",
         unlock="produce an obs_result asset carrying uncertain_mask"),
    _cat("obs_result.K", "camera intrinsics per view", role=ROLE_OBS_RESULT, unit="1",
         frame="C_mm", unlock="produce an obs_result asset carrying K"),
    _cat("obs_result.T_WC", "camera pose per view (T_AB maps B into A)", role=ROLE_OBS_RESULT,
         unit="mm", frame="W_mm", unlock="produce an obs_result asset carrying T_WC"),
    _cat("obs_result.dist", "OpenCV distortion coefficients per view", role=ROLE_OBS_RESULT,
         unit="1", frame="C_mm", unlock="produce an obs_result asset carrying dist"),
    _cat("obs_result.points", "fused observed point cloud", role=ROLE_OBS_RESULT, unit="mm",
         frame="S_mm", unlock="produce an obs_result asset carrying points"),
    _cat("obs_result.normals", "fused observed point normals", role=ROLE_OBS_RESULT, unit="1",
         frame="S_mm", unlock="produce an obs_result asset carrying normals"),
    _cat("obs_result.point_valid", "validity mask of the fused points", role=ROLE_OBS_RESULT,
         unit="1", frame="S_mm", unlock="produce an obs_result asset carrying point_valid"),
    _cat("obs_result.normal_valid", "validity mask of the fused normals", role=ROLE_OBS_RESULT,
         unit="1", frame="S_mm", unlock="produce an obs_result asset carrying normal_valid"),
    # --- degraded observation variants -------------------------------------------------
    _cat("obs_view.frames.rgb", "degraded delivered view (obs_view frame)",
         role=ROLE_OBS_VIEW, unit="count", frame="pixel_cv_center",
         unlock="materialise an obs_view asset (degrade axis run) in this store"),
    _cat("obs_view.frames.rgb_linear", "degraded linear radiance (obs_view frame)",
         role=ROLE_OBS_VIEW, unit="1", frame="pixel_cv_center",
         unlock="materialise an obs_view asset carrying rgb_linear"),
    _cat("obs_view.frames.depth_z", "degraded depth (obs_view frame)", role=ROLE_OBS_VIEW,
         unit="mm", frame="pixel_cv_center", unlock="materialise an obs_view asset carrying depth_z"),
    _cat("obs_view.frames.deployment_mask", "degraded deployment mask", role=ROLE_OBS_VIEW,
         unit="1", frame="pixel_cv_center",
         unlock="materialise an obs_view asset carrying deployment_mask"),
    _cat("obs_view.frames.research_mask", "research mask of the degraded frame",
         role=ROLE_OBS_VIEW, unit="1", frame="pixel_cv_center",
         unlock="materialise an obs_view asset carrying research_mask"),
    _cat("obs_view.frames.valid_mask", "validity mask of the degraded frame", role=ROLE_OBS_VIEW,
         unit="1", frame="pixel_cv_center",
         unlock="materialise an obs_view asset carrying valid_mask"),
    _cat("obs_view.frames.K", "camera intrinsics of the degraded frame", role=ROLE_OBS_VIEW,
         unit="1", frame="C_mm", unlock="materialise an obs_view asset carrying K"),
    _cat("obs_view.frames.T_WC", "camera pose of the degraded frame", role=ROLE_OBS_VIEW,
         unit="mm", frame="W_mm", unlock="materialise an obs_view asset carrying T_WC"),
    _cat("obs_view.frames.dist", "distortion of the degraded frame", role=ROLE_OBS_VIEW,
         unit="1", frame="C_mm", unlock="materialise an obs_view asset carrying dist"),
    # --- fused geometry -----------------------------------------------------------------
    _cat("obs_fused_geometry.points", "re-fused point cloud after a geometry-observation axis",
         role=ROLE_OBS_FUSED, unit="mm", frame="S_mm",
         unlock="materialise an obs_fused_geometry asset (G01..G08 axis run)"),
    _cat("obs_fused_geometry.normals", "normals of the re-fused cloud", role=ROLE_OBS_FUSED,
         unit="1", frame="S_mm", unlock="materialise an obs_fused_geometry asset"),
    _cat("obs_fused_geometry.point_valid", "validity of the re-fused cloud", role=ROLE_OBS_FUSED,
         unit="1", frame="S_mm", unlock="materialise an obs_fused_geometry asset"),
    _cat("obs_fused_geometry.point_view", "originating view index per fused point",
         role=ROLE_OBS_FUSED, unit="1", frame="S_mm",
         unlock="materialise an obs_fused_geometry asset"),
    _cat("obs_fused_geometry.roi", "fracture-ROI flag per fused point", role=ROLE_OBS_FUSED,
         unit="1", frame="S_mm", unlock="materialise an obs_fused_geometry asset"),
    _cat("obs_fused_geometry.priority_order", "frozen fusion priority order", role=ROLE_OBS_FUSED,
         unit="1", frame="S_mm", unlock="materialise an obs_fused_geometry asset"),
    _cat("obs_fused_geometry.reference_points", "clean reference points of the same cloud",
         role=ROLE_OBS_FUSED, unit="mm", frame="S_mm", is_truth=True,
         unlock="materialise an obs_fused_geometry asset carrying reference_points"),
    _cat("obs_fused_geometry.depth_error_field", "injected depth error field", role=ROLE_OBS_FUSED,
         unit="mm", frame="S_mm", unlock="materialise an obs_fused_geometry asset"),
    _cat("obs_fused_geometry.mesh", "fused mesh of the observed surface", role=ROLE_OBS_FUSED,
         unit="mm", frame="S_mm", unlock="materialise an obs_fused_geometry asset"),
    # --- feature bundle -----------------------------------------------------------------
    _cat("feature_bundle.point_cloud", "feature-bundle point cloud", role=ROLE_FEATURE_BUNDLE,
         unit="mm", frame="S_mm", unlock="produce a feature_bundle asset for this fragment"),
    _cat("feature_bundle.normal_field", "estimated normal field", role=ROLE_FEATURE_BUNDLE,
         unit="1", frame="S_mm", unlock="produce a feature_bundle asset"),
    _cat("feature_bundle.curvature_field", "estimated curvature field", role=ROLE_FEATURE_BUNDLE,
         unit="1/mm", frame="S_mm", unlock="produce a feature_bundle asset"),
    _cat("feature_bundle.density_field", "local point density field", role=ROLE_FEATURE_BUNDLE,
         unit="1/mm^2", frame="S_mm", unlock="produce a feature_bundle asset"),
    _cat("feature_bundle.quality", "per-fragment quality vector (names/values/valid)",
         role=ROLE_FEATURE_BUNDLE, unit="1", frame="S_mm",
         unlock="produce a feature_bundle asset carrying quality__values"),
    _cat("feature_bundle.token_index", "point -> token index assignment", role=ROLE_FEATURE_BUNDLE,
         unit="1", frame="S_mm", unlock="produce a feature_bundle asset carrying token_index"),
    _cat("feature_bundle.view_tokens", "per-view token summary", role=ROLE_FEATURE_BUNDLE,
         unit="1", frame="S_mm", unlock="produce a feature_bundle asset carrying view_tokens"),
    _cat("feature_bundle.roi_weight", "per-point ROI weight", role=ROLE_FEATURE_BUNDLE,
         unit="1", frame="S_mm", unlock="produce a feature_bundle asset carrying roi_weight"),
    # --- label bundles ------------------------------------------------------------------
    _cat("label_bundle.research_id_map", "per-view per-face id map (research label)",
         role=ROLE_LABEL_BUNDLE, unit="1", frame="pixel_cv_center", is_label=True,
         unlock="produce a label_bundle asset carrying label__research_id_map__*"),
    _cat("label_bundle.surface_tag_map", "per-view surface-tag map (research label)",
         role=ROLE_LABEL_BUNDLE, unit="1", frame="pixel_cv_center", is_label=True,
         unlock="produce a label_bundle asset carrying label__surface_tag_map__*"),
    # --- degradation measurements -------------------------------------------------------
    _cat("degrade_measurement.modalities", "modality presence after a degradation axis",
         role=ROLE_DEGRADE_MEASUREMENT, unit="1", frame="S_mm", is_label=True,
         unlock="run a degradation axis and commit its degrade_measurement"),
    _cat("degrade_measurement.mask", "mask state after a degradation axis",
         role=ROLE_DEGRADE_MEASUREMENT, unit="1", frame="pixel_cv_center", is_label=True,
         unlock="run a degradation axis and commit its degrade_measurement"),
    _cat("degrade_measurement.observed_est", "OBS_EST channel vector of the degraded payload",
         role=ROLE_DEGRADE_MEASUREMENT, unit="1", frame="S_mm",
         unlock="run a degradation axis and commit its degrade_measurement"),
    _cat("degrade_measurement.meta_arrays", "remaining measurement arrays",
         role=ROLE_DEGRADE_MEASUREMENT, unit="1", frame="S_mm",
         unlock="run a degradation axis and commit its degrade_measurement"),
    # --- display layer ------------------------------------------------------------------
    _cat("display_lod_glb.glb_scene", "display GLB (display-derived, metre / Y-up)",
         role=ROLE_DISPLAY_LOD, unit="m", frame="Y_up_m",
         unlock="materialise a display_lod_glb asset (today only data/a12_demo/store has them)"),
    _cat("display_lod_glb.lod_level_L1",
         "display LOD L1 as a scene node", role=ROLE_DISPLAY_LOD, unit="m", frame="Y_up_m",
         unlock="install fast_simplification and export L1 into the GLB scene graph; today "
                "lod_notes records 'L1 skipped: ModuleNotFoundError: No module named "
                "fast_simplification' or 'L1/L2 measured only (not exported as scene nodes)'"),
    _cat("display_lod_glb.lod_level_L2",
         "display LOD L2 as a scene node", role=ROLE_DISPLAY_LOD, unit="m", frame="Y_up_m",
         unlock="same as L1: the simplification dependency is absent and the levels are "
                "measured but not written as scene nodes"),
    # --- relations / roster -------------------------------------------------------------
    _cat("relation_pool.relations", "relation table of a frozen pool (rel_* arrays)",
         role=ROLE_POOL, unit="1", frame="W_mm", is_label=True,
         unlock="commit a relation_pool asset for this batch"),
    _cat("query_roster.queries", "frozen query roster", role=ROLE_ROSTER, unit="1", frame="W_mm",
         is_label=True, unlock="commit a query_roster asset for this pool"),
    # --- provenance / material / pattern ------------------------------------------------
    _cat("provenance.fingerprints", "code + backend fingerprints, seed and spec hashes",
         role=ROLE_PROVENANCE, unit="1", frame="none",
         unlock="commit a provenance asset for the run that produced these fragments"),
    _cat("qa_report.probe", "QA report payload", role=ROLE_QA_REPORT, unit="1", frame="none",
         unlock="commit a qa_report asset"),
    _cat("material_profile.profile", "material layer profile", role="material_profile",
         unit="mm", frame="W_mm", unlock="commit a material_profile asset"),
    _cat("pattern_channels.height_mm", "pattern relief height channel",
         role=ROLE_PATTERN_CHANNELS, unit="mm", frame="W_mm",
         unlock="commit a pattern_channels asset carrying the height_mm channel"),
    _cat("pattern_channels.albedo", "pattern albedo channel", role=ROLE_PATTERN_CHANNELS,
         unit="1", frame="W_mm",
         unlock="commit a pattern_channels asset carrying the albedo channel"),
    _cat("pattern_channels.roughness", "pattern roughness channel", role=ROLE_PATTERN_CHANNELS,
         unit="1", frame="W_mm",
         unlock="commit a pattern_channels asset carrying the roughness channel"),
    _cat("pattern_channels.pattern_region", "pattern region indicator", role=ROLE_PATTERN_CHANNELS,
         unit="1", frame="W_mm",
         unlock="commit a pattern_channels asset carrying the pattern_region channel"),
    _cat("pattern_recipe.recipe", "pattern recipe document", role=ROLE_PATTERN_RECIPE,
         unit="mm", frame="W_mm", unlock="commit a pattern_recipe asset"),
    _cat("clean_truth.relations", "relation table of the fracture event (relations.bin JSON)",
         role=ROLE_CLEAN_TRUTH, unit="1", frame="W_mm", is_label=True, is_truth=True,
         unlock="commit a clean_truth asset carrying a relations blob"),
    _cat("physical_truth.relations", "relation table carried by the physical truth layer",
         role=ROLE_PHYSICAL_TRUTH, unit="1", frame="W_mm", is_label=True, is_truth=True,
         unlock="commit a physical_truth asset carrying a relations blob"),
    _cat("visible_labels.relations", "relation table carried by the visible label layer",
         role=ROLE_VISIBLE_LABELS, unit="1", frame="W_mm", is_label=True, is_truth=True,
         unlock="commit a visible_labels asset carrying a relations blob"),
    # --- registrations that have no product anywhere yet --------------------------------
    _cat("context_pack.excavation",
         "simulated excavation context (site/trench/locus/stratum/batch)",
         role=ROLE_CONTEXT_PACK, unit="1", frame="none",
         unlock="materialise a context_pack asset (role context_pack, schema synlab.context.v1); "
                "0 such assets exist in any store of this checkout"),
    _cat("episode_trace.transitions", "active-observation episode transitions",
         role=ROLE_EPISODE, unit="1", frame="none", is_label=True,
         unlock="run at least one episode and commit an episode_trace asset; the role is "
                "registered but has 0 products in every store"),
    _cat("cutter_mesh.mesh", "cutter mesh of a fracture event", role=ROLE_CUTTER, unit="mm",
         frame="W_mm", is_truth=True,
         unlock="commit a cutter_mesh asset (role registered, 0 products in every store)"),
    _cat("mvs_result.sparse", "MVS/SfM reconstruction result", role=ROLE_MVS_RESULT, unit="mm",
         frame="S_mm",
         unlock="run the photo_mvs route to completion; the only recorded run failed with "
                "STOP_SFM (incremental_mapping returned no reconstruction)"),
)

_CATALOGUE_BY_ID = {item["modality_id"]: item for item in MODALITY_CATALOGUE}


# --------------------------------------------------------------------------------------
# ablation groups
# --------------------------------------------------------------------------------------
def _grp(group_id: str, title: str, question: str, modality_ids: Sequence[str], *,
         fields: Sequence[str], switch_on: str, switch_off: str, metrics: Sequence[str],
         measurements: Sequence[str] = (), permission: str = "research") -> dict[str, Any]:
    return {
        "group_id": group_id, "title": title, "question": question,
        "modality_ids": list(modality_ids), "field_patterns": list(fields),
        "switch": {"on": switch_on, "off": switch_off, "loader_flag": f"--groups {group_id}"},
        "dependent_metrics": list(metrics), "measurement_keys": list(measurements),
        "permission": permission,
    }


_METRICS_RETRIEVAL = ("any@50", "Hit@10", "CovRecall@10", "无邻片误导率", "有邻片接受覆盖")
_METRICS_GEOM = ("局部 surface repeat error", "normal repeatability", "coverage")
_METRICS_QUALITY = ("blur", "exposure", "coverage", "occlusion")

#: The dimensions an ablation can switch on and off.  ``field_patterns`` are matched by
#: :mod:`tools.load_full_package` against ``<modality_id>#<array key>`` so the same group
#: id is both a manifest row and a loader selector.
ABLATION_GROUPS: tuple[dict[str, Any], ...] = (
    _grp("G-GEOM-MOTHER", "母体权威网格",
         "母体全局几何是否是检索/配准的有效先验，还是只增加输入维度？",
         ["mother_mesh.vertices", "mother_mesh.faces", "mother_mesh.face_attrs"],
         fields=["mother_mesh.*#mesh.*"],
         switch_on="加载母体 mesh（母体全局形状先验）",
         switch_off="只给碎片 mesh，不给母体 mesh",
         metrics=_METRICS_RETRIEVAL, permission="research"),
    _grp("G-GEOM-FRAG", "碎片权威网格",
         "碎片 3D 几何（含顶点/面）是否比纯 2D 观测带来净增益？",
         ["fragment_mesh.vertices", "fragment_mesh.faces"],
         fields=["fragment_mesh.*#mesh.vertices", "fragment_mesh.*#mesh.faces"],
         switch_on="加载 fragment_mesh 几何",
         switch_off="去掉 fragment_mesh（只用观测派生的点云）",
         metrics=_METRICS_RETRIEVAL + _METRICS_GEOM, permission="research"),
    _grp("G-GEOM-PHYS", "物理损伤构件网格",
         "把退化后的 physical_component 几何当输入，是否抵消（负收益）或补偿 2D 退化？",
         ["physical_component.mesh", "physical_component.mesh_face_attrs",
          "physical_result.measurement"],
         fields=["physical_component.*#payload.mesh.*", "physical_result.*#*"],
         switch_on="用 physical_component 的受损几何",
         switch_off="用 fragment_mesh 的未受损几何",
         metrics=_METRICS_RETRIEVAL + ("退化敏感度曲线",), permission="research"),
    _grp("G-FRAC-ATTR", "断面面属性（origin_kind/interface_id/side）",
         "断面面属性是断面定位的最小充分信号吗？",
         ["fragment_mesh.face_attrs", "mother_mesh.face_attrs",
          "physical_component.mesh_face_attrs"],
         fields=["*#mesh.face__*", "*#payload.mesh.face__*"],
         switch_on="读入逐面 origin_kind/interface_id/side/ambiguous",
         switch_off="（必须同时把 2D surface_tag 一起关掉）只保留几何与 RGB",
         metrics=_METRICS_RETRIEVAL + _METRICS_GEOM, permission="research"),
    _grp("G-FRAC-IFACE-DERIVED", "断面几何子集（派生）",
         "从权威面属性派生的断面几何，能否单独支撑断面级监督（替代缺失的独立断面资产）？",
         ["fragment_mesh.interface_faces"],
         fields=["fragment_mesh.interface_faces#*"],
         switch_on="加载派生断面子集（iface_face_index/iface_faces/iface_area_mm2）",
         switch_off="去掉派生断面子集，只留逐面 origin_kind",
         metrics=_METRICS_GEOM + ("断面面积一致性",), permission="research"),
    _grp("G-FRAC-IFACE-TRUTH", "断面几何真值层 iface_*",
         "断面级真值（面积/间隙/法向）是否是配对断口监督的必要项？",
         ["clean_truth.iface_geometry"],
         fields=["clean_truth.iface_geometry#iface_*"],
         switch_on="加载 iface_area_mm2 / iface_gap_p95_mm / iface_normal_p95_deg / iface_points_*",
         switch_off="只留 corr_* 逐点对应，不留断面级聚合",
         metrics=("配对断口面积一致性", "R2 判定 AUROC", "Hit@10"), permission="research"),
    _grp("G-FRAC-CORR", "断面逐点对应 corr_*",
         "逐点对应监督（corr_point_a/b）对互补性学习的边际收益是多少？",
         ["clean_truth.corr_geometry", "physical_truth.corr_geometry"],
         fields=["*#corr_point_a", "*#corr_point_b", "*#corr_normal_a", "*#corr_normal_b",
                 "*#corr_bary_a", "*#corr_bary_b", "*#corr_index_a", "*#corr_index_b",
                 "*#corr_face_a", "*#corr_face_b", "*#corr_weight", "*#corr_valid",
                 "*#corr_residual_mm", "*#corr_interface_id", "*#corr_association_code",
                 "*#corr_ambiguous", "*#corr_fragment_ids", "*#corr_*"],
         switch_on="correspondence loss 打开（权重 0.1）",
         switch_off="correspondence loss 置零",
         metrics=("correspondence 误差", "Hit@10", "CovRecall@10"), permission="research"),
    _grp("G-IMG-RGB", "交付 RGB",
         "交付态 RGB 单独能把 Hit@10 做到多少（部署基线）？",
         ["obs_result.rgb", "obs_view.frames.rgb"],
         fields=["*#v*.rgb", "*#payload.frames.*.rgb"],
         switch_on="读入交付 RGB",
         switch_off="（该组是主输入，关闭仅用于定义地板）",
         metrics=_METRICS_RETRIEVAL, permission="deploy"),
    _grp("G-IMG-LINEAR", "场景线性辐射",
         "线性辐射通道（ISP 之前）是否比交付 RGB 有额外信息？",
         ["obs_result.rgb_linear", "obs_view.frames.rgb_linear"],
         fields=["*#v*.rgb_linear", "*#payload.frames.*.rgb_linear"],
         switch_on="加线性辐射通道",
         switch_off="只用交付 RGB",
         metrics=_METRICS_RETRIEVAL + ("色彩一致性",), permission="research"),
    _grp("G-IMG-DEPTH", "深度图 depth_z",
         "相机 z 深度是否带来正收益，还是只泄露渲染器构造？",
         ["obs_result.depth_z", "obs_view.frames.depth_z", "obs_fused_geometry.depth_error_field"],
         fields=["*#v*.depth_z", "*#payload.frames.*.depth_z",
                 "obs_fused_geometry.depth_error_field#payload.depth_error_field"],
         switch_on="加 depth_z 通道",
         switch_off="关闭 depth_z（部署白名单外的研究项）",
         metrics=_METRICS_RETRIEVAL, permission="deploy"),
    _grp("G-IMG-IDMAP", "逐面 id_map",
         "逐面 ID 是监督信号还是捷径（是否把答案直接喂给模型）？",
         ["obs_result.id_map"],
         fields=["*#v*.id_map"],
         switch_on="加 id_map",
         switch_off="关闭 id_map（检查指标是否崩塌：崩塌=捷径）",
         metrics=_METRICS_RETRIEVAL + ("捷径审计",), permission="research"),
    _grp("G-IMG-TAG", "面属性 tag 图 surface_tag",
         "surface_tag 图里 rim 像素为 0 时，该通道是否完全无信息？",
         ["obs_result.surface_tag"],
         fields=["*#v*.surface_tag"],
         switch_on="加 surface_tag 通道",
         switch_off="关闭 surface_tag",
         metrics=_METRICS_RETRIEVAL + ("断面可定位性",),
         measurements=["obs.surface_tag_histogram", "obs.surface_tag_total_pixels"],
         permission="research"),
    _grp("G-MASK-DEPLOY", "部署可获取掩码",
         "只保留部署可获取像素是否显著降低指标（部署代价的量化）？",
         ["obs_result.deployment_mask", "obs_view.frames.deployment_mask"],
         fields=["*#v*.deployment_mask", "*#payload.frames.*.deployment_mask"],
         switch_on="只算 deployment_mask 内像素",
         switch_off="全图参与（研究上界）",
         metrics=_METRICS_RETRIEVAL + ("部署代价",),
         measurements=["obs.deployment_mask_true", "obs.deployment_mask_total"],
         permission="deploy"),
    _grp("G-MASK-ROI", "研究 ROI",
         "限制到 ROI 是否提高精度（信噪比换召回）？",
         ["obs_result.roi", "obs_view.frames.research_mask", "obs_fused_geometry.roi"],
         fields=["*#v*.roi", "*#payload.frames.*.research_mask",
                 "obs_fused_geometry.roi#payload.roi"],
         switch_on="只在 ROI 内计算",
         switch_off="全渠道参与",
         metrics=_METRICS_RETRIEVAL + ("ROI 召回",), permission="research"),
    _grp("G-MASK-UNCERTAIN", "不确定像素掩码",
         "剔不确定像素（混合/景深/深度边）是否净收益？",
         ["obs_result.uncertain_mask"],
         fields=["*#v*.uncertain_mask"],
         switch_on="剔除 uncertain_mask 像素",
         switch_off="保留全部像素",
         metrics=_METRICS_RETRIEVAL,
         measurements=["obs.uncertain_mask_true", "obs.uncertain_mask_total"],
         permission="deploy"),
    _grp("G-CAM-K", "相机内参 K",
         "给真值内参是否比'未标定档'显著提高（标定价值上限）？",
         ["obs_result.K", "obs_view.frames.K"],
         fields=["*#v*.K", "*#payload.frames.*.K"],
         switch_on="用真值 K",
         switch_off="用档位标称 K（calibrated=false 的 STRESS_UNCALIBRATED）",
         metrics=_METRICS_RETRIEVAL + ("重投影误差",), permission="deploy"),
    _grp("G-CAM-POSE", "相机位姿 T_WC",
         "真值位姿是必要条件还是可被特征匹配替代？",
         ["obs_result.T_WC", "obs_view.frames.T_WC"],
         fields=["*#v*.T_WC", "*#payload.frames.*.T_WC"],
         switch_on="用真值位姿",
         switch_off="只用图像做位姿估计",
         metrics=_METRICS_RETRIEVAL + ("位姿误差",), permission="research"),
    _grp("G-CAM-DIST", "畸变系数 dist",
         "显式畸变是先验还是噪声源？",
         ["obs_result.dist", "obs_view.frames.dist"],
         fields=["*#v*.dist", "*#payload.frames.*.dist"],
         switch_on="按 dist 做去畸变",
         switch_off="不处理畸变（STRESS_UNCALIBRATED 现状）",
         metrics=_METRICS_RETRIEVAL + ("边缘重投影",), permission="research"),
    _grp("G-PC-FUSED", "融合点云与法向",
         "点云/法向是否是 2D 之外的互补证据？",
         ["obs_result.points", "obs_result.normals", "obs_result.point_valid",
          "obs_result.normal_valid", "obs_fused_geometry.points", "obs_fused_geometry.normals",
          "obs_fused_geometry.point_valid", "obs_fused_geometry.point_view",
          "obs_fused_geometry.priority_order", "obs_fused_geometry.mesh"],
         fields=["*#points", "*#normals", "*#point_valid", "*#normal_valid", "*#point_view",
                 "*#payload.points", "*#payload.normals", "*#payload.point_valid",
                 "*#payload.point_view", "*#payload.priority_order", "*#payload.mesh.*"],
         switch_on="加入融合点云/法向",
         switch_off="只用图像",
         metrics=_METRICS_RETRIEVAL + _METRICS_GEOM, permission="deploy"),
    _grp("G-PC-REFERENCE", "观测 vs 干净参考点云",
         "把干净参考点云当输入是否造成泄漏型虚高（预期负收益）？",
         ["obs_fused_geometry.reference_points"],
         fields=["obs_fused_geometry.reference_points#payload.reference_points"],
         switch_on="加入 reference_points（对照：应被判为泄漏）",
         switch_off="只用观测点云",
         metrics=_METRICS_RETRIEVAL + ("泄漏审计",), permission="research"),
    _grp("G-FEAT-FIELDS", "特征场（法向/曲率/密度）",
         "显式特征场是否比原始点云更有效？",
         ["feature_bundle.point_cloud", "feature_bundle.normal_field",
          "feature_bundle.curvature_field", "feature_bundle.density_field",
          "feature_bundle.roi_weight"],
         fields=["feature_bundle.*#point_cloud__*", "feature_bundle.*#normal_field__*",
                 "feature_bundle.*#curvature_field__*", "feature_bundle.*#density_field__*",
                 "feature_bundle.*#roi_weight"],
         switch_on="加载特征场",
         switch_off="只加载原始点云",
         metrics=_METRICS_RETRIEVAL + _METRICS_GEOM, permission="research"),
    _grp("G-QUALITY", "质量向量",
         "质量向量（11 通道）是否改善门控与拒识？",
         ["feature_bundle.quality"],
         fields=["feature_bundle.*#quality__*"],
         switch_on="把质量向量喂给质量头（权重 0.05）",
         switch_off="关闭质量任务",
         metrics=("质量头损失", "无邻片误导率", "有邻片接受覆盖"),
         measurements=["quality.channel_names"], permission="research"),
    _grp("G-TOKENS", "token 缓存",
         "token 缓存是否携带独立信息（已知有效秩=1 的疑问）？",
         ["feature_bundle.token_index", "feature_bundle.view_tokens"],
         fields=["feature_bundle.*#token_index", "feature_bundle.*#view_tokens"],
         switch_on="用 view_tokens/token_index",
         switch_off="用 token_input（真实 rank 内容）或原始像素",
         metrics=_METRICS_RETRIEVAL + ("token 有效秩",), permission="research"),
    _grp("G-LABEL-CLEAN", "clean 真值层",
         "干净层真值参与预训练是否正收益（还是只教合成捷径）？",
         ["clean_truth.iface_geometry", "clean_truth.corr_geometry"],
         fields=["clean_truth.*#iface_*", "clean_truth.*#corr_*"],
         switch_on="clean 层参与监督",
         switch_off="只用 physical 层",
         metrics=_METRICS_RETRIEVAL + ("迁移增益",), permission="research"),
    _grp("G-LABEL-PHYSICAL", "physical 真值层",
         "退化后的 physical 层监督是否比 clean 层更贴近部署？",
         ["physical_truth.corr_geometry", "physical_component.mesh"],
         fields=["physical_truth.*#corr_*", "physical_component.mesh#payload.mesh.*"],
         switch_on="physical 层参与监督",
         switch_off="只用 clean 层",
         metrics=_METRICS_RETRIEVAL + ("退化鲁棒性",), permission="research"),
    _grp("G-LABEL-VISIBLE", "visible 真值层",
         "可见性标签是否改善拒识与阈值选择？",
         ["visible_labels.visible_counts"],
         fields=["visible_labels.*#visible_*"],
         switch_on="visible 层参与（可见性加权）",
         switch_off="不做可见性加权",
         metrics=("无邻片误导率", "有邻片接受覆盖", "Hit@10"), permission="research"),
    _grp("G-LABEL-BUNDLE", "像素级标签包",
         "像素级 id/tag 标签图作为辅助监督是否正收益？",
         ["label_bundle.research_id_map", "label_bundle.surface_tag_map"],
         fields=["label_bundle.*#label__research_id_map__*",
                 "label_bundle.*#label__surface_tag_map__*"],
         switch_on="像素级分割辅助损失打开",
         switch_off="只用 pair 级监督",
         metrics=("seg F1", "Hit@10"), permission="research"),
    _grp("G-REL-POOL", "关系表与 query roster",
         "关系表（R1/R2/UNKNOWN）与冻结 roster 是否是可复算评测的前提？",
         ["relation_pool.relations", "query_roster.queries"],
         fields=["relation_pool.*#rel_*", "query_roster.queries#*"],
         switch_on="按 roster 的 query/库划分评测",
         switch_off="随机划分（仅作对照，结果不可引用）",
         metrics=_METRICS_RETRIEVAL, permission="research"),
    _grp("G-DEGRADE-PHYSICAL", "物理退化轴 P01–P08",
         "各物理磨损轴分别造成多大性能下降（敏感度曲线）？",
         ["physical_component.mesh", "physical_component.appearance"],
         fields=["physical_component.*#payload.*"],
         switch_on="选某个 axis_id/level 的 physical_component",
         switch_off="level 0（恒等档，实测与源字节相同）",
         metrics=("敏感度曲线", "临界质量", _METRICS_RETRIEVAL[1]), permission="research"),
    _grp("G-DEGRADE-IMAGING", "成像退化轴 I01–I10",
         "模糊/噪声/曝光/白平衡/JPEG 各轴的性能代价是多少？",
         ["obs_view.frames.rgb", "obs_view.frames.rgb_linear", "obs_view.frames.depth_z"],
         fields=["obs_view.*#payload.frames.*"],
         switch_on="选某个 axis_id/level 的 obs_view",
         switch_off="level 0 或 obs_result 基线",
         metrics=_METRICS_RETRIEVAL + _METRICS_QUALITY, permission="research"),
    _grp("G-DEGRADE-GEOMETRY", "几何观测退化轴 G01–G08",
         "深度误差/稀疏/空洞/位姿漂移/简化/尺度/标定/伪影各自的代价？",
         ["obs_fused_geometry.points", "obs_fused_geometry.normals",
          "obs_fused_geometry.depth_error_field"],
         fields=["obs_fused_geometry.*#payload.*"],
         switch_on="选某个 axis_id/level 的 obs_fused_geometry",
         switch_off="level 0（源几何）",
         metrics=_METRICS_GEOM + (_METRICS_RETRIEVAL[1],), permission="research"),
    _grp("G-DEGRADE-PROTOCOL", "特征协议退化轴 X01–X05",
         "分支缺失/边界误差/上下文缺失/估计偏差/留出工况的影响？",
         ["degrade_measurement.modalities", "degrade_measurement.observed_est",
          "degrade_measurement.mask", "degrade_measurement.meta_arrays"],
         fields=["degrade_measurement.*#payload.*"],
         switch_on="选某个 axis_id/level 的协议退化",
         switch_off="无退化的 OBS_EST 基线",
         metrics=_METRICS_RETRIEVAL + ("输入资格门",), permission="research"),
    _grp("G-CONTEXT", "采集/出土上下文",
         "受限的模拟出土上下文是否有正收益（文档要求不能等价母体 ID）？",
         ["context_pack.excavation"],
         fields=["context_pack.*#*"],
         switch_on="注入 context_pack 的模拟字段（含缺失/冲突扰动）",
         switch_off="不给任何上下文",
         metrics=_METRICS_RETRIEVAL + ("上下文冲突率",), permission="research"),
    _grp("G-DISPLAY-LOD", "展示 LOD",
         "L0 与 L1/L2 的差别是否影响几何侧实验（L1/L2 当前不可得）？",
         ["display_lod_glb.glb_scene", "display_lod_glb.lod_level_L1",
          "display_lod_glb.lod_level_L2"],
         fields=["display_lod_glb.*#*"],
         switch_on="用 L0+断面 primitive 的 GLB",
         switch_off="用权威 mesh（mm/Z-up）",
         metrics=_METRICS_GEOM, permission="deploy"),
    _grp("G-PROVENANCE", "provenance / 可复算性",
         "没有 provenance 的实验结果能否被复算（对照组必须失败）？",
         ["provenance.fingerprints", "qa_report.probe", "material_profile.profile",
          "pattern_channels.channels", "pattern_recipe.recipe"],
         fields=["provenance.*#*", "qa_report.*#*", "material_profile.*#*",
                 "pattern_channels.*#*", "pattern_recipe.*#*"],
         switch_on="记录并核对 code/backend 指纹",
         switch_off="丢弃指纹（结果不可复算，仅作反例）",
         metrics=("可复算率", "哈希一致性"), permission="research"),
)


# --------------------------------------------------------------------------------------
# channel family: which physical array belongs to which ablatable modality
# --------------------------------------------------------------------------------------
def family_of(role: str, key: str) -> str:
    """The ablatable modality family of one array ``key`` of an asset of ``role``.

    The partition is total: every key maps to exactly one family, so no array can be
    silently left out of the package (an unknown shape of key still returns its own
    first-segment family).
    """
    if role in (ROLE_MOTHER_MESH, ROLE_FRAGMENT_MESH):
        if key.startswith("mesh.face__"):
            return "face_attrs"
        if key == "mesh.vertices":
            return "vertices"
        if key == "mesh.faces":
            return "faces"
        return "mesh_arrays" if not key.startswith("mesh.") else key.split(".", 1)[1]

    if role in (ROLE_PHYSICAL_COMPONENT, ROLE_PHYSICAL_RESULT):
        if key.startswith("payload.mesh.face__"):
            return "mesh_face_attrs"
        if key.startswith("payload.mesh."):
            return "mesh"
        if key.startswith("payload.appearance."):
            return "appearance"
        if key.startswith("payload."):
            return "meta_arrays"
        return "measurement"

    if role == ROLE_OBS_RESULT:
        match = _VIEW_RE.match(key)
        if match:
            return match.group("channel")
        return key

    if role == ROLE_OBS_VIEW:
        match = _FRAME_RE.match(key)
        if match:
            return f"frames.{match.group('channel')}"
        if key.startswith("payload."):
            return key[len("payload."):].split(".", 1)[0]
        return key

    if role == ROLE_OBS_FUSED:
        match = _FRAME_RE.match(key)
        if match:
            return f"frames.{match.group('channel')}"
        if key.startswith("payload.mesh."):
            return "mesh"
        if key.startswith("payload."):
            return key[len("payload."):].split(".", 1)[0]
        return key

    if role == ROLE_FEATURE_BUNDLE:
        if "__" in key:
            return key.split("__", 1)[0]
        return key

    if role == ROLE_CLEAN_TRUTH:
        if key.startswith("iface_"):
            return "iface_geometry"
        if key.startswith("corr_"):
            return "corr_geometry"
        return "truth_arrays"

    if role == ROLE_PHYSICAL_TRUTH:
        if key.startswith("corr_"):
            return "corr_geometry"
        return "truth_arrays"

    if role == ROLE_VISIBLE_LABELS:
        return "visible_counts"

    if role == ROLE_LABEL_BUNDLE:
        match = re.match(r"^label__(?P<name>.+?)__\d+$", key)
        if match:
            return match.group("name")
        return "label_arrays"

    if role == ROLE_DEGRADE_MEASUREMENT:
        if key.startswith("payload.modalities."):
            return "modalities"
        if key.startswith("payload.mask"):
            return "mask"
        if key.startswith("payload.observed_est."):
            return "observed_est"
        if key.startswith("payload.roi"):
            return "roi"
        if key.startswith("payload.K"):
            return "K"
        if key.startswith("payload."):
            return key[len("payload."):].split(".", 1)[0]
        return "meta_arrays"

    if role == ROLE_POOL:
        return "relations" if key.startswith("rel_") else key
    return key


def modality_id_of(role: str, family: str) -> str:
    return f"{role}.{family}"


# --------------------------------------------------------------------------------------
# permission policy
# --------------------------------------------------------------------------------------
def deployment_channel_policy(path: str | Path | None = None) -> dict[str, Any]:
    """Resolve which observation arrays a deployment profile may obtain.

    The list is *read* from ``synlab/schemas/view_channels.json`` through the same loader
    the training exporter uses, so the two exporters can never disagree about a permission.
    A policy that cannot be read degrades to "nothing is deployable" rather than guessing.
    """
    try:
        from .export import load_channel_policy

        policy = load_channel_policy(path)
    except Exception as exc:                                   # pragma: no cover - defensive
        return {
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {exc}",
            "path": str(path) if path else "",
            "hash": "",
            "deploy_source_arrays": [],
            "research_source_arrays": [],
            "note": "no channel may be marked deployable while the policy is unreadable",
        }
    deploy = sorted({str(item.get("source_array", "")) for item in
                     policy["channels"].get("deploy", [])} - {""})
    research = sorted({str(item.get("source_array", "")) for item in
                       policy["channels"].get("research", [])} - {""})
    return {
        "status": "ok",
        "path": policy.get("path", ""),
        "hash": policy.get("hash", ""),
        "schema": policy.get("schema", ""),
        "deploy_source_arrays": deploy,
        "research_source_arrays": research,
        "truth_roles": sorted((policy.get("truth_roles") or {}).keys()),
        "note": "membership is a permission, not a claim: what the package contains is "
                "measured below",
    }


def _permission_for(modality_id: str, role: str, family: str,
                    policy: Mapping[str, Any]) -> tuple[bool, str, str]:
    array_name = family.split(".")[-1]
    if role in TRUTH_ROLES:
        return False, "truth_layer", (
            f"{role} is a ground-truth layer (plan 30.12); its channels are never shipped "
            "to a deployment consumer")
    if role in LABEL_ROLES:
        return False, "label_layer", (
            f"{role} carries supervision labels; a filename or field from it would be an "
            "answer channel")
    if role in (ROLE_OBS_RESULT, ROLE_OBS_VIEW, ROLE_OBS_FUSED):
        deploy_arrays = set(policy.get("deploy_source_arrays") or ())
        if array_name in deploy_arrays:
            return True, "policy_deploy_channel", (
                f"'{array_name}' is declared in the deploy view of {policy.get('path','')} "
                f"({policy.get('hash','')})")
        if array_name in GEOMETRY_DEPLOY_ARRAYS and role == ROLE_OBS_FUSED:
            return True, "policy_deploy_geometry", (
                f"'{array_name}' is declared in the deployment geometry index "
                "(synlab/storage/export.py deploy/geometry)")
    if role == ROLE_DISPLAY_LOD:
        return True, "display_layer", (
            "the display GLB is the product a user sees; it carries no truth channel")
    return False, "research_only", (
        f"'{array_name}' is not declared for the deploy view of "
        f"{policy.get('path','(policy unavailable)')}; it stays on the research side")


def _is_synthetic(record: Any) -> tuple[bool, str]:
    """``(synthetic_only, basis)`` measured from the asset's own metadata."""
    meta = dict(record.meta or {})
    nested = meta.get("meta") if isinstance(meta.get("meta"), Mapping) else {}
    for source in (meta, nested):
        kind = str(source.get("source_kind") or "").upper()
        scope = str(source.get("data_scope") or "").upper()
        real = source.get("real_capture")
        if kind in REAL_SOURCE_KINDS:
            return False, f"source_kind={kind}"
        if scope == "REAL":
            return False, f"data_scope={scope}"
        if real is True:
            return False, "real_capture=true"
        if kind or scope or real is not None:
            return True, (f"source_kind={kind or '<unset>'}"
                          f";data_scope={scope or '<unset>'};real_capture={real}")
    return True, "no real-capture declaration anywhere in the asset metadata"


# --------------------------------------------------------------------------------------
# fragment association
# --------------------------------------------------------------------------------------
class _Association:
    """Resolve which fragment(s)/mother an asset belongs to, with a recorded reason."""

    def __init__(self, records: Sequence[Any]):
        self.by_asset = {record.asset_id: record for record in records}
        self.observation_map: dict[str, set[str]] = defaultdict(set)
        self.mother_fragments: dict[str, set[str]] = defaultdict(set)
        for record in records:
            meta = dict(record.meta or {})
            nested = meta.get("meta") if isinstance(meta.get("meta"), Mapping) else {}
            direct = self._direct_fragments(meta) | self._direct_fragments(nested)
            obs = meta.get("observation_id") or nested.get("observation_id")
            if isinstance(obs, str) and obs:
                self.observation_map[obs] |= direct
            if record.role == ROLE_FRAGMENT_MESH:
                mother = self._mother_hint(meta, record)
                if mother:
                    self.mother_fragments[mother] |= direct
        self._cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _direct_fragments(meta: Mapping[str, Any]) -> set[str]:
        found: set[str] = set()
        value = meta.get("fragment_id")
        if isinstance(value, str) and value:
            found.add(value)
        values = meta.get("fragment_ids")
        if isinstance(values, (list, tuple)):
            found |= {str(item) for item in values if item}
        return found

    @staticmethod
    def _mother_hint(meta: Mapping[str, Any], record: Any) -> str:
        for key in ("mother_id", "lineage_id"):
            value = meta.get(key)
            if isinstance(value, str) and value and _MOTHER_RE.match(value):
                return value
        event = meta.get("event_id")
        if isinstance(event, str):
            match = _EVENT_RE.match(event)
            if match:
                return match.group("mother")
        lineage = str(record.lineage_id or "")
        return lineage if _MOTHER_RE.match(lineage) else ""

    def resolve(self, record: Any) -> dict[str, Any]:
        if record.asset_id in self._cache:
            return self._cache[record.asset_id]
        meta = dict(record.meta or {})
        nested = meta.get("meta") if isinstance(meta.get("meta"), Mapping) else {}
        how: list[str] = []
        fragments = self._direct_fragments(meta) | self._direct_fragments(nested)
        if fragments:
            how.append("meta.fragment_id/fragment_ids")

        mother = str(meta.get("mother_id") or nested.get("mother_id") or "") or None
        event = str(meta.get("event_id") or nested.get("event_id") or "") or None
        if mother is None and event:
            match = _EVENT_RE.match(event)
            if match:
                mother = match.group("mother")

        # observation-id link (feature_bundle / label_bundle / visible_labels carry it)
        obs = meta.get("observation_id") or nested.get("observation_id")
        if isinstance(obs, str) and obs and not fragments:
            linked = self.observation_map.get(obs)
            if linked:
                fragments |= set(linked)
                how.append(f"observation_id={obs}")

        # explicit asset pointers
        for key in ("source_asset_id", "source_asset", "component_asset_id", "label_ref",
                    "obs_ref", "feature_ref", "mother_asset", "raster_asset"):
            value = meta.get(key) or nested.get(key)
            resolved = self._walk(value, depth=0)
            if resolved["fragments"]:
                fragments |= resolved["fragments"]
                how.append(f"meta.{key} -> {resolved['via']}")
            if mother is None and resolved["mother"]:
                mother = resolved["mother"]

        # ancestry chain
        for entry in list(record.ancestry or []):
            resolved = self._walk(entry, depth=0)
            if resolved["fragments"]:
                fragments |= resolved["fragments"]
                how.append(f"ancestry {entry} -> {resolved['via']}")
            if mother is None and resolved["mother"]:
                mother = resolved["mother"]

        if not fragments and mother:
            inherited = self.mother_fragments.get(mother)
            if inherited:
                fragments |= set(inherited)
                how.append(f"mother={mother} (all fragments of that mother)")
        if not mother:
            mother = self._mother_hint(meta, record) or None
        if not mother:
            lineage = str(record.lineage_id or "")
            if lineage and _MOTHER_RE.match(lineage):
                mother = lineage

        if fragments:
            scope = SCOPE_FRAGMENT
        elif mother:
            scope = SCOPE_MOTHER
        else:
            scope = SCOPE_STORE
        result = {
            "scope": scope,
            "fragment_ids": sorted(fragments),
            "mother_id": mother or "",
            "association": how or ["unassociated (no fragment, mother or pointer in metadata)"],
        }
        self._cache[record.asset_id] = result
        return result

    def _walk(self, ref: Any, *, depth: int) -> dict[str, Any]:
        """Follow an asset-id reference (bounded) and collect fragments/mother."""
        empty = {"fragments": set(), "mother": None, "via": ""}
        if depth > 3 or not isinstance(ref, str) or not ref:
            return empty
        record = self.by_asset.get(ref)
        if record is None:
            match = _CLEAN_REF_RE.match(ref)
            if match:
                mother = match.group("mother")
                return {"fragments": set(self.mother_fragments.get(mother, set())),
                        "mother": mother, "via": f"clean_ref:{mother}"}
            return empty
        meta = dict(record.meta or {})
        nested = meta.get("meta") if isinstance(meta.get("meta"), Mapping) else {}
        direct = self._direct_fragments(meta) | self._direct_fragments(nested)
        mother = str(meta.get("mother_id") or "") or None
        via = f"{record.role}:{record.asset_id}"
        if direct:
            return {"fragments": set(direct), "mother": mother, "via": via}
        if mother:
            return {"fragments": set(self.mother_fragments.get(mother, set())),
                    "mother": mother, "via": f"{via} (mother={mother})"}
        for key in ("source_asset_id", "source_asset", "component_asset_id"):
            value = meta.get(key) or nested.get(key)
            if isinstance(value, str) and value and value != ref:
                deeper = self._walk(value, depth=depth + 1)
                if deeper["fragments"] or deeper["mother"]:
                    return {"fragments": deeper["fragments"], "mother": deeper["mother"],
                            "via": f"{via} -> {deeper['via']}"}
        return {"fragments": set(), "mother": mother, "via": via}


# --------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------
def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _write_json(path: Path, payload: Any) -> None:
    text = json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True)
    _atomic_write_bytes(path, text.encode("utf-8"))


def _write_npz(path: Path, arrays: Mapping[str, np.ndarray]) -> tuple[int, bool]:
    """Write one npz atomically; returns ``(bytes, compressed)``."""
    import io

    total = sum(int(np.asarray(a).nbytes) for a in arrays.values())
    compressed = total <= COMPRESS_BELOW_BYTES
    safe = {str(k): np.asarray(v) for k, v in arrays.items() if isinstance(v, np.ndarray)}
    buffer = io.BytesIO()
    if compressed:
        np.savez_compressed(buffer, **safe)
    else:
        np.savez(buffer, **safe)
    data = buffer.getvalue()
    _atomic_write_bytes(path, data)
    return len(data), compressed


def _glb_summary(data: bytes) -> dict[str, Any]:
    """Parse the JSON chunk of a GLB container (real counts, no rendering)."""
    out: dict[str, Any] = {"bytes": len(data)}
    try:
        if len(data) < 20 or data[0:4] != b"glTF":
            out["error"] = "not a GLB container"
            return out
        version, length = struct.unpack_from("<II", data, 4)
        out["version"] = int(version)
        out["declared_bytes"] = int(length)
        cursor = 12
        payload = None
        while cursor + 8 <= len(data):
            chunk_len, chunk_type = struct.unpack_from("<II", data, cursor)
            cursor += 8
            chunk = data[cursor:cursor + chunk_len]
            cursor += chunk_len
            if chunk_type == 0x4E4F534A:                    # 'JSON'
                payload = json.loads(chunk.decode("utf-8"))
                break
        if payload is None:
            out["error"] = "no JSON chunk"
            return out
        out["meshes"] = len(payload.get("meshes") or [])
        out["nodes"] = len(payload.get("nodes") or [])
        out["materials"] = len(payload.get("materials") or [])
        out["accessors"] = len(payload.get("accessors") or [])
        out["images"] = len(payload.get("images") or [])
        out["textures"] = len(payload.get("textures") or [])
        attributes: Counter = Counter()
        triangles = 0
        materials: Counter = Counter()
        for mesh in payload.get("meshes") or []:
            for primitive in mesh.get("primitives") or []:
                attributes.update((primitive.get("attributes") or {}).keys())
                if primitive.get("material") is not None:
                    materials[str(payload["materials"][primitive["material"]].get("name"))] += 1
                index = primitive.get("indices")
                if isinstance(index, int) and index < len(payload.get("accessors") or []):
                    triangles += int(payload["accessors"][index].get("count", 0)) // 3
        out["attributes"] = dict(attributes)
        out["triangles"] = int(triangles)
        out["material_names"] = dict(materials)
    except Exception as exc:                                # pragma: no cover - defensive
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _array_stats(array: np.ndarray) -> dict[str, Any]:
    size = int(array.size)
    stats: dict[str, Any] = {"elements": size, "nbytes": int(array.nbytes)}
    if size == 0:
        stats["stats_skipped"] = "empty array"
        return stats
    if size > STATS_MAX_ELEMENTS:
        stats["stats_skipped"] = f"array larger than STATS_MAX_ELEMENTS={STATS_MAX_ELEMENTS}"
        return stats
    stats["stats_skipped"] = ""
    if array.dtype.kind in ("U", "S", "O"):
        values = np.unique(array)
        stats["unique_count"] = int(values.size)
        stats["sample_values"] = [str(item) for item in values[:8].tolist()]
        return stats
    if array.dtype == bool:
        stats["true_count"] = int(np.count_nonzero(array))
        stats["true_fraction"] = float(np.count_nonzero(array) / size)
        return stats
    if np.issubdtype(array.dtype, np.integer):
        values, counts = np.unique(array, return_counts=True)
        stats["unique_count"] = int(values.size)
        if values.size <= HISTOGRAM_MAX_UNIQUE:
            stats["histogram"] = {str(int(v)): int(c) for v, c in zip(values, counts)}
        stats["min"] = int(values.min())
        stats["max"] = int(values.max())
        return stats
    finite = array[np.isfinite(array)] if np.issubdtype(array.dtype, np.floating) else array
    if finite.size == 0:
        stats["stats_skipped"] = "no finite value"
        return stats
    stats["min"] = float(np.min(finite))
    stats["max"] = float(np.max(finite))
    stats["mean"] = float(np.mean(finite.astype(np.float64)))
    return stats


# --------------------------------------------------------------------------------------
# the export itself
# --------------------------------------------------------------------------------------
class _Recorder:
    """Accumulates the manifest while files are written."""

    def __init__(self) -> None:
        self.files: list[dict[str, Any]] = []
        self.modalities: dict[str, dict[str, Any]] = {}
        self.fragments: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"modalities": defaultdict(list), "missing": [], "mother_id": "",
                     "assets": defaultdict(list)})
        self.mothers: dict[str, dict[str, Any]] = defaultdict(lambda: {"assets": []})
        self.measurements: dict[str, Any] = {}
        self.degradation: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"levels": defaultdict(int), "variants": defaultdict(int), "roles": []})
        self.asset_rows: list[dict[str, Any]] = []
        self.bytes_written = 0

    # ---- modality rows ---------------------------------------------------------------
    def modality(self, modality_id: str, *, role: str, family: str,
                 permission: Mapping[str, Any]) -> dict[str, Any]:
        row = self.modalities.get(modality_id)
        if row is None:
            catalogued = _CATALOGUE_BY_ID.get(modality_id, {})
            allowed, code, reason = permission["allowed"], permission["code"], permission["reason"]
            row = {
                "modality_id": modality_id, "role": role, "family": family,
                "title": catalogued.get("title") or f"{role} / {family}",
                "status": "missing",
                "catalogue_known": modality_id in _CATALOGUE_BY_ID,
                "unit": catalogued.get("unit", "1"),
                "frame": catalogued.get("frame", "none"),
                "is_label": bool(catalogued.get("is_label")),
                "is_truth": bool(catalogued.get("is_truth", role in TRUTH_ROLES)),
                "derived": bool(catalogued.get("derived")),
                "derivation": catalogued.get("note", ""),
                "deployment_view_allowed": allowed,
                "permission_code": code,
                "permission_reason": reason,
                "synthetic_only": True,
                "synthetic_basis": "",
                "files": [], "arrays": {}, "assets": [],
                "fragments": [], "counts": {}, "measurements_keys": [],
                "unlock_condition": catalogued.get("unlock_condition", ""),
            }
            self.modalities[modality_id] = row
        return row

    def add_file(self, row: dict[str, Any], *, rel_path: str, out_root: Path, fragment: str,
                 asset_id: str, scope: str, fmt: str, arrays: Mapping[str, np.ndarray] | None,
                 bytes_written: int, note: str = "", derived: bool = False,
                 sha256: str | None = None) -> None:
        target = out_root / rel_path
        digest = sha256 if sha256 is not None else (
            hash_file(target) if target.exists() else "")
        entry = {
            "path": rel_path, "format": fmt, "bytes": int(bytes_written), "sha256": digest,
            "fragment": fragment, "asset_id": asset_id, "scope": scope,
            "arrays": sorted(arrays) if arrays else [], "derived": bool(derived),
        }
        if note:
            entry["note"] = note
        row["files"].append(entry)
        row["status"] = "present"
        if asset_id not in row["assets"]:
            row["assets"].append(asset_id)
        if fragment and fragment not in row["fragments"]:
            row["fragments"].append(fragment)
        if arrays:
            for key, array in arrays.items():
                info = row["arrays"].setdefault(str(key), {
                    "shape": list(np.asarray(array).shape), "dtype": str(np.asarray(array).dtype),
                    "nbytes": int(np.asarray(array).nbytes), "instances": 0, "stats": [],
                })
                info["instances"] += 1
                if len(info["stats"]) < 8:
                    info["stats"].append(_array_stats(np.asarray(array)))
        self.files.append(entry)
        self.bytes_written += int(bytes_written)

    def measurement(self, key: str, **values: Any) -> None:
        row = self.measurements.setdefault(key, {})
        for name, value in values.items():
            if isinstance(value, (int, float, str, bool)) or value is None:
                row[name] = value
            else:
                row[name] = _jsonable(value)


#: Roles whose quality vector / label arrays may carry forbidden feature fields.
def _record_degradation(recorder: _Recorder, record: Any, assoc: Mapping[str, Any]) -> None:
    meta = dict(record.meta or {})
    axis = meta.get("axis_id")
    if not axis:
        return
    entry = recorder.degradation[str(axis)]
    level = meta.get("level")
    if level is not None:
        entry["levels"][str(int(level)) if isinstance(level, (int, np.integer)) else str(level)] += 1
    variant = meta.get("variant")
    if variant:
        entry["variants"][str(variant)] += 1
    if record.role not in entry["roles"]:
        entry["roles"].append(record.role)
    entry.setdefault("factor_kind", meta.get("factor_kind"))
    if assoc["fragment_ids"] and "fragments" not in entry:
        entry["fragments"] = list(assoc["fragment_ids"])


def _degrade_axes_registry() -> dict[str, Any]:
    """Introspect the registered degradation axes (never fatal if the module moved)."""
    try:
        from ..degrade import axes as axes_module

        rows = []
        for cls in getattr(axes_module, "AXES", ()):  # pragma: no branch - data driven
            levels = getattr(cls, "LEVELS", ()) or ()
            rows.append({
                "axis_id": getattr(cls, "AXIS_ID", cls.__name__),
                "stage": str(getattr(cls, "STAGE", "")),
                "levels_declared": len(levels),
                "variants_declared": sorted((getattr(cls, "VARIANT_KINDS", {}) or {}).keys()),
                "class": cls.__name__,
            })
        return {"status": "ok", "source": "synlab.degrade.axes.AXES", "axes": rows,
                "axes_total": len(rows)}
    except Exception as exc:                                # pragma: no cover - defensive
        return {"status": "unavailable", "source": "synlab.degrade.axes.AXES",
                "error": f"{type(exc).__name__}: {exc}", "axes": [], "axes_total": 0}


def _select_fragments(records: Sequence[Any], assoc: _Association, *,
                      fragments: Sequence[str] | None, limit: int | None) -> tuple[list[str], dict]:
    mothers_of: dict[str, str] = {}
    for record in records:
        if record.role != ROLE_FRAGMENT_MESH:
            continue
        info = assoc.resolve(record)
        for fragment in info["fragment_ids"]:
            mothers_of.setdefault(fragment, info["mother_id"])
    all_fragments = sorted(mothers_of)
    if fragments:
        wanted = [str(item) for item in fragments]
        unknown = sorted(set(wanted) - set(all_fragments))
        chosen = [item for item in all_fragments if item in set(wanted)]
        selection = {"mode": "explicit", "requested": wanted, "unknown_fragments": unknown}
    elif limit is not None:
        chosen = all_fragments[: max(int(limit), 0)]
        selection = {"mode": "limit", "limit": int(limit), "available": len(all_fragments)}
    else:
        chosen = all_fragments
        selection = {"mode": "all", "available": len(all_fragments)}
    selection["fragments_exported"] = len(chosen)
    selection["fragments_available"] = len(all_fragments)
    return chosen, selection


def export_full_package(store_root: str | Path, out_dir: str | Path | None = None, *,
                        flavor: str = FLAVOR_FULL,
                        fragments: Sequence[str] | None = None,
                        limit: int | None = None,
                        derived: bool = True,
                        dry_run: bool = False,
                        policy_path: str | Path | None = None,
                        progress: Any = None) -> dict[str, Any]:
    """Write the maximal export of ``store_root`` and return its manifest.

    Parameters
    ----------
    flavor
        Only ``"full"`` is registered.  The parameter exists so a caller cannot silently
        get a trimmed package: an unknown flavour is a hard error.
    fragments / limit
        Optional *scope* selectors.  They limit which fragments are exported (a scoped
        run); they never limit which modalities of a selected fragment are exported.  The
        choice is recorded in ``manifest["selection"]`` so a scoped run cannot be mistaken
        for a whole-store export.
    derived
        Write the documented derived artefacts (the fracture-surface subset).  The
        derivation formula is recorded either way.
    """
    if flavor not in FLAVORS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown flavour {flavor!r} (registered: {FLAVORS})",
                          stage="storage.export_full")
    started = time.time()
    store = _StoreReader(store_root)
    out = Path(out_dir) if out_dir else store.root / "exports_full"
    out = out.resolve()

    total = store.count_assets()
    records = store.list_assets(limit=max(total, 1) + 1) if total else []
    assoc = _Association(records)
    selected, selection = _select_fragments(records, assoc,
                                            fragments=fragments, limit=limit)
    selected_set = set(selected)
    policy = deployment_channel_policy(policy_path)
    recorder = _Recorder()

    # ---- fragments / mothers skeleton -------------------------------------------------
    for fragment in selected:
        recorder.fragments[fragment]["mother_id"] = ""
    for record in records:
        if record.role != ROLE_FRAGMENT_MESH:
            continue
        info = assoc.resolve(record)
        for fragment in info["fragment_ids"]:
            if fragment in selected_set:
                recorder.fragments[fragment]["mother_id"] = info["mother_id"]

    synthetic_claims: Counter = Counter()
    written_meta: set[str] = set()
    skipped_assets: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        info = assoc.resolve(record)
        scope = info["scope"]
        frags = [f for f in info["fragment_ids"] if f in selected_set]
        if scope == SCOPE_FRAGMENT and not frags:
            skipped_assets.append({"asset_id": record.asset_id, "role": record.role,
                                   "reason": "fragment(s) outside the selected scope",
                                   "fragment_ids": info["fragment_ids"]})
            continue
        if scope == SCOPE_MOTHER:
            mother = info["mother_id"]
            attached = sorted(f for f in selected_set
                              if recorder.fragments[f]["mother_id"] == mother)
            # A mother with no fragment in the store is still exported (nothing is trimmed):
            # it lands under ``mothers/<mother_id>/`` and its asset row records that no
            # selected fragment inherits from it.
            frags = attached
        if scope == SCOPE_STORE and not selected:
            skipped_assets.append({"asset_id": record.asset_id, "role": record.role,
                                   "reason": "store-scoped asset but no fragment selected",
                                   "mother_id": info["mother_id"]})
            continue

        synthetic, basis = _is_synthetic(record)
        synthetic_claims["synthetic" if synthetic else "declared_real"] += 1
        primary = (frags[0] if frags else (info["mother_id"] or "_store"))
        if scope == SCOPE_STORE:
            dir_key, scope_dir = record.role, f"store/{record.role}"
        elif scope == SCOPE_MOTHER:
            dir_key = info["mother_id"] or primary
            scope_dir = f"mothers/{dir_key}"
        else:
            dir_key, scope_dir = primary, f"fragments/{primary}"

        row = {
            "asset_id": record.asset_id, "role": record.role, "schema": record.schema,
            "unit": record.unit, "frame": record.frame, "qa_status": record.qa_status,
            "lineage_id": record.lineage_id or "", "split": record.split or "",
            "scope": scope, "fragment_ids": info["fragment_ids"],
            "primary": primary, "mother_id": info["mother_id"],
            "attached_fragments": list(frags),
            "association": info["association"], "synthetic_only": synthetic,
            "synthetic_basis": basis,
            "axis_id": record.meta.get("axis_id") if isinstance(record.meta, Mapping) else None,
            "level": record.meta.get("level") if isinstance(record.meta, Mapping) else None,
            "variant": record.meta.get("variant") if isinstance(record.meta, Mapping) else None,
            "files": [],
        }
        _record_degradation(recorder, record, info)

        # ---- meta.json verbatim ------------------------------------------------------
        meta_path = store.meta_path(record.asset_id)
        meta_rel = f"assets/{record.asset_id}/meta.json"
        if meta_path.exists():
            data = meta_path.read_bytes()
            source = "verbatim from the store"
        else:
            data = json.dumps(_jsonable({"meta": record.meta, "qa": record.qa,
                                         "files": record.files}),
                              ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            source = "reconstructed from the assets table (no meta.json on disk)"
        if not dry_run:
            _atomic_write_bytes(out / meta_rel, data)
        if record.asset_id not in written_meta:
            recorder.files.append({"path": meta_rel, "format": "json", "bytes": len(data),
                                   "sha256": hash_bytes(data), "fragment": primary,
                                   "asset_id": record.asset_id, "scope": scope,
                                   "arrays": [], "derived": False,
                                   "note": f"asset manifest bytes ({source})"})
            recorder.bytes_written += len(data)
            written_meta.add(record.asset_id)
            row["files"].append(meta_rel)

        # ---- non-array blobs (glb.bin, relations.bin, ...) ---------------------------
        blobs: dict[str, bytes] = {}
        for name in sorted(record.files or {}):
            if name in ("meta", "arrays"):
                continue
            try:
                blobs[name] = store.load_bytes(record.asset_id, name)
            except Exception as exc:                        # pragma: no cover - defensive
                row.setdefault("blob_errors", []).append(f"{name}: {type(exc).__name__}: {exc}")

        # ---- arrays ------------------------------------------------------------------
        arrays: dict[str, np.ndarray] = {}
        if record.files and record.files.get("arrays"):
            arrays = store.load_arrays(record.asset_id)

        buckets: dict[str, dict[str, np.ndarray]] = defaultdict(dict)
        for key, array in arrays.items():
            buckets[family_of(record.role, key)][key] = array
        if derived and record.role == ROLE_FRAGMENT_MESH:
            subset = _interface_subset(arrays)
            if subset:
                buckets["interface_faces"] = subset

        if not arrays and not blobs and record.role not in METADATA_ONLY_ROLES:
            row["no_payload"] = True

        for family in sorted(buckets):
            subset = buckets[family]
            if not subset:
                continue
            modality_id = modality_id_of(record.role, family)
            allowed, code, reason = _permission_for(modality_id, record.role, family, policy)
            mrow = recorder.modality(modality_id, role=record.role, family=family,
                                     permission={"allowed": allowed, "code": code,
                                                 "reason": reason})
            _apply_synthetic(mrow, synthetic, basis)
            rel = f"{scope_dir}/{modality_id}__{record.asset_id}.npz"
            ok = not dry_run
            if ok:
                nbytes, compressed = _write_npz(out / rel, subset)
            else:
                nbytes, compressed = (int(sum(a.nbytes for a in subset.values())), False)
            recorder.add_file(mrow, rel_path=rel, out_root=out, fragment=primary,
                              asset_id=record.asset_id, scope=scope, fmt="npz",
                              arrays=subset, bytes_written=nbytes,
                              note="npz" + (" (compressed)" if compressed else ""),
                              derived=family == "interface_faces",
                              sha256="" if dry_run else None)
            row["files"].append(rel)
            for fragment in frags:
                entry = {"modality_id": modality_id, "path": rel, "asset_id": record.asset_id,
                         "scope": scope, "arrays": sorted(subset),
                         "primary_fragment": primary,
                         "inherited": fragment != primary}
                recorder.fragments[fragment]["modalities"][modality_id].append(entry)
                recorder.fragments[fragment]["assets"][record.role].append(record.asset_id)
            if scope == SCOPE_MOTHER:
                recorder.mothers[dir_key]["assets"].append(record.asset_id)
            _accumulate_measurements(recorder, modality_id, record, subset)

        # ---- metadata-only roles: the meta.json *is* the modality payload ------------
        if record.role in METADATA_ONLY_ROLES or (not arrays and not blobs):
            family = _metadata_family(record)
            modality_id = modality_id_of(record.role, family)
            allowed, code, reason = _permission_for(modality_id, record.role, family, policy)
            mrow = recorder.modality(modality_id, role=record.role, family=family,
                                     permission={"allowed": allowed, "code": code,
                                                 "reason": reason})
            _apply_synthetic(mrow, synthetic, basis)
            mrow["status"] = "present"
            mrow["files"].append({"path": meta_rel, "format": "json", "bytes": len(data),
                                  "sha256": hash_bytes(data), "fragment": primary,
                                  "asset_id": record.asset_id, "scope": scope, "arrays": [],
                                  "note": "payload is the asset metadata itself"})
            if record.asset_id not in mrow["assets"]:
                mrow["assets"].append(record.asset_id)
            if primary not in mrow["fragments"]:
                mrow["fragments"].append(primary)
            mrow.setdefault("metadata_only", True)
            for fragment in frags:
                recorder.fragments[fragment]["modalities"][modality_id].append(
                    {"modality_id": modality_id, "path": meta_rel, "asset_id": record.asset_id,
                     "scope": scope, "arrays": [], "primary_fragment": primary,
                     "inherited": fragment != primary})

        # ---- blobs as their own modalities -------------------------------------------
        for name, blob in sorted(blobs.items()):
            family = _blob_family(record, name)
            modality_id = modality_id_of(record.role, family)
            allowed, code, reason = _permission_for(modality_id, record.role, family, policy)
            mrow = recorder.modality(modality_id, role=record.role, family=family,
                                     permission={"allowed": allowed, "code": code,
                                                 "reason": reason})
            _apply_synthetic(mrow, synthetic, basis)
            extension = ".glb" if name == "glb" else ".bin"
            rel = f"{scope_dir}/{modality_id}__{record.asset_id}{extension}"
            if not dry_run:
                _atomic_write_bytes(out / rel, blob)
            digest = hash_bytes(blob)
            entry = {"path": rel, "format": extension.lstrip("."), "bytes": len(blob),
                     "sha256": digest, "fragment": primary, "asset_id": record.asset_id,
                     "scope": scope, "arrays": [], "derived": bool(
                         record.meta.get("derived")) if isinstance(record.meta, Mapping) else False}
            mrow["files"].append(entry)
            mrow["status"] = "present"
            if record.asset_id not in mrow["assets"]:
                mrow["assets"].append(record.asset_id)
            if primary not in mrow["fragments"]:
                mrow["fragments"].append(primary)
            recorder.files.append(entry)
            recorder.bytes_written += len(blob)
            row["files"].append(rel)
            for fragment in frags:
                recorder.fragments[fragment]["modalities"][modality_id].append(
                    {"modality_id": modality_id, "path": rel, "asset_id": record.asset_id,
                     "scope": scope, "arrays": [], "primary_fragment": primary,
                     "inherited": fragment != primary})
            if name == "glb":
                summary = _glb_summary(blob)
                mrow.setdefault("glb", {})
                mrow["glb"] = summary
                mrow["format"] = "glb"
                meta = record.meta if isinstance(record.meta, Mapping) else {}
                levels = meta.get("lod_levels") or {}
                exported = sorted(
                    str(level) for level, block in levels.items()
                    if isinstance(block, Mapping) and block.get("exported_as_scene_node"))
                mrow["lod_levels_declared"] = sorted(str(k) for k in levels)
                mrow["lod_levels_exported_as_scene_node"] = exported
                mrow["lod_notes"] = _jsonable(meta.get("lod_notes") or [])
                for level in ("L1", "L2"):
                    sub_id = f"{ROLE_DISPLAY_LOD}.lod_level_{level}"
                    sub = recorder.modality(
                        sub_id, role=ROLE_DISPLAY_LOD, family=f"lod_level_{level}",
                        permission={"allowed": True, "code": "display_layer",
                                    "reason": "display LOD level (scene node)"})
                    if level in exported:
                        sub["status"] = "present"
                        sub["files"].append({**entry, "note": f"{level} scene node inside {rel}"})
                        sub["assets"].append(record.asset_id)
                        sub["fragments"].append(primary)
                    else:
                        sub["status"] = "missing"
                        sub["evidence"] = _jsonable(meta.get("lod_notes") or [])

        recorder.asset_rows.append(row)
        if progress is not None and (index % 25 == 0 or index == len(records)):
            progress(index, len(records), record.role)

    # ---- missing modalities ------------------------------------------------------------
    missing = _missing_modalities(recorder)
    for modality_id, unlock in missing:
        entry = _CATALOGUE_BY_ID.get(modality_id, {})
        recorder.modality(
            modality_id, role=entry.get("role", ""), family=modality_id.split(".", 1)[-1],
            permission={"allowed": False, "code": "missing",
                        "reason": "no asset carries this modality in the scanned store"})
        recorder.modalities[modality_id]["status"] = "missing"
        recorder.modalities[modality_id]["unlock_condition"] = (
            unlock or recorder.modalities[modality_id]["unlock_condition"])

    # ---- assemble ----------------------------------------------------------------------
    modalities = [recorder.modalities[key] for key in sorted(recorder.modalities)]
    for row in modalities:
        row["counts"] = {
            "files": len(row["files"]),
            "bytes": int(sum(entry["bytes"] for entry in row["files"])),
            "assets": len(row["assets"]),
            "fragments": len(row["fragments"]),
            "arrays": len(row["arrays"]),
            "instances": int(sum(info["instances"] for info in row["arrays"].values())),
            "elements": int(sum(info["nbytes"] for info in row["arrays"].values())),
        }
        if row["status"] == "missing" and not row["unlock_condition"]:
            row["unlock_condition"] = ("materialise an asset of role "
                                       f"'{row['role']}' carrying family '{row['family']}'")
        row["files"] = sorted(row["files"], key=lambda item: (item["path"], item["asset_id"]))
        row["synthetic_only"] = bool(row["synthetic_only"])

    missing_rows = [{"modality_id": row["modality_id"], "unlock_condition": row["unlock_condition"]}
                    for row in modalities if row["status"] != "present"]

    fragments_block: dict[str, Any] = {}
    for fragment in selected:
        block = recorder.fragments[fragment]
        fragments_block[fragment] = {
            "mother_id": block["mother_id"],
            "modalities": {key: sorted(value, key=lambda item: (item["modality_id"],
                                                                item["asset_id"]))
                           for key, value in sorted(block["modalities"].items())},
            "assets": {role: sorted(set(ids)) for role, ids in sorted(block["assets"].items())},
            "modalities_present": len(block["modalities"]),
            "files": sum(len(value) for value in block["modalities"].values()),
            "missing": missing_rows,
        }

    recorder.measurement("store.declared_real_assets", n=synthetic_claims["declared_real"])
    recorder.measurement("store.assets_exported", n=len(recorder.asset_rows))
    mothers_of_selected = sorted({block["mother_id"] for block in recorder.fragments.values()
                                  if block["mother_id"]})
    findings = _findings(recorder)
    manifest: dict[str, Any] = {
        "schema": FULL_MANIFEST_SCHEMA,
        "package_schema": FULL_PACKAGE_SCHEMA,
        "flavor": flavor,
        "ablation_index": "ablation_index.json",
        "generated_from": {
            "store": str(store.root),
            "store_db": str(store.db_path),
            "store_read_mode": store.read_mode or "unopened",
            "assets_in_store": total,
            "assets_exported": len(recorder.asset_rows),
            "assets_skipped": len(skipped_assets),
        },
        "selection": selection,
        "store_snapshot": {
            "assets": total,
            "roles": _role_counts(records),
            "lineages": _lineage_counts(records),
        },
        "permission_policy": policy,
        "role_counts": _role_counts(records),
        "synthetic_evidence": {
            "assets_synthetic": synthetic_claims["synthetic"],
            "assets_declaring_real_capture": synthetic_claims["declared_real"],
            "note": "synthetic_only is derived per asset from source_kind/data_scope/"
                    "real_capture; a store with no real capture declares 0",
        },
        "counts": {
            "modalities_present": sum(1 for row in modalities if row["status"] == "present"),
            "modalities_missing": sum(1 for row in modalities if row["status"] == "missing"),
            "files": len(recorder.files),
            "bytes": int(sum(entry["bytes"] for entry in recorder.files)),
            "fragments": len(selected),
            "mothers": len(mothers_of_selected),
        },
        "modalities": modalities,
        "fragments": fragments_block,
        "mothers": {key: {"assets": sorted(set(value["assets"]))}
                    for key, value in sorted(recorder.mothers.items())},
        "assets": recorder.asset_rows,
        "assets_skipped": skipped_assets,
        "files": sorted(recorder.files, key=lambda item: item["path"]),
        "measurements": recorder.measurements,
        "degradation": {
            "axes_registry": _degrade_axes_registry(),
            "materialised": {axis: {"levels": dict(sorted(value["levels"].items())),
                                    "variants": dict(sorted(value["variants"].items())),
                                    "roles": sorted(value["roles"]),
                                    "factor_kind": value.get("factor_kind")}
                             for axis, value in sorted(recorder.degradation.items())},
        },
        "findings": findings,
        "truth_permission": {
            "truth_roles": sorted(TRUTH_ROLES),
            "label_roles": sorted(LABEL_ROLES),
            "forbidden_feature_fields": sorted(FORBIDDEN_FEATURE_FIELDS),
            "note": "no modality of a truth/label role is ever marked deployable; "
                    "the flag is recomputed per modality below",
            "deployable_modalities": sorted(
                row["modality_id"] for row in modalities if row["deployment_view_allowed"]),
            "deployable_fields": sorted(
                f"{row['modality_id']}#{key}" for row in modalities
                if row["deployment_view_allowed"] for key in row["arrays"]),
        },
        "write_scope": "read_only (the scanned store is opened without DDL and never written; "
                       "see generated_from.store_read_mode)",
        "wall_seconds": round(time.time() - started, 4),
    }

    index = build_ablation_index(manifest)
    manifest["ablation_summary"] = {
        "groups": len(index["groups"]),
        "available": sum(1 for group in index["groups"] if group["availability"] == "present"),
        "partial": sum(1 for group in index["groups"] if group["availability"] == "partial"),
        "missing": sum(1 for group in index["groups"] if group["availability"] == "missing"),
    }
    if not dry_run:
        _write_json(out / "ablation_index.json", index)
        _write_json(out / "manifest.json", manifest)
        (out / "README.md").write_text(render_readme(manifest, index), encoding="utf-8")
    return manifest


class _StoreReader:
    """Read-only view of an asset store.

    The exporter must not disturb the store it scans -- other writers may be committing to it
    while this runs -- so it deliberately does **not** build an :class:`~synlab.storage.store.AssetStore`
    (whose constructor creates directories and writes ``schema_meta``).  This reader opens the
    metadata database with ``mode=ro`` where the platform allows it, never runs DDL, and reads
    payload bytes straight from the recorded relative paths.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.db_path = self.root / "metadata.sqlite"
        if not self.db_path.is_file():
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                              f"no metadata.sqlite under {self.root}",
                              stage="storage.export_full")
        self.read_mode = ""

    def connect(self) -> Any:
        import sqlite3

        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=60.0)
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            self.read_mode = "sqlite-uri-mode=ro"
        except sqlite3.Error:
            # A WAL database without its -shm cannot always be opened read-only; fall back to
            # a plain handle.  No DDL and no INSERT is ever issued on it.
            conn = sqlite3.connect(str(self.db_path), timeout=60.0)
            self.read_mode = "sqlite-rw-handle-no-writes"
        conn.execute("PRAGMA busy_timeout=60000")
        conn.row_factory = sqlite3.Row
        return conn

    def count_assets(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM assets").fetchone()["n"])

    def list_assets(self, *, limit: int = 500, offset: int = 0) -> list[Any]:
        from .store import AssetRecord

        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM assets ORDER BY created_at ASC, asset_id ASC LIMIT ? OFFSET ?",
                (int(limit), int(offset)),
            ).fetchall()
        return [self._record(row, AssetRecord) for row in rows]

    def get_asset(self, asset_id: str) -> Any:
        from .store import AssetRecord

        with self.connect() as conn:
            row = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        if row is None:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH, f"unknown asset {asset_id}",
                              stage="storage.export_full")
        return self._record(row, AssetRecord)

    def _record(self, row: Any, cls: Any) -> Any:
        import json as _json

        return cls(
            asset_id=row["asset_id"], blob_hash=row["blob_hash"], role=row["role"],
            schema=row["schema"], unit=row["unit"], frame=row["frame"],
            interpretation_hash=row["interpretation_hash"], qa_status=row["qa_status"],
            qa=_json.loads(row["qa_json"] or "{}"), files=_json.loads(row["files_json"] or "{}"),
            meta=_json.loads(row["meta_json"] or "{}"),
            ancestry=_json.loads(row["ancestry_json"] or "[]"),
            lineage_id=row["lineage_id"], split=row["split"], revision=row["revision"],
            created_at=row["created_at"], path=self.root / "assets" / row["asset_id"],
        )

    def arrays_path(self, record: Any) -> Path | None:
        rel = (record.files or {}).get("arrays")
        return self.root / Path(*str(rel).split("/")) if rel else None

    def load_arrays(self, asset_id: str) -> dict[str, np.ndarray]:
        record = self.get_asset(asset_id)
        path = self.arrays_path(record)
        if path is None or not path.exists():
            return {}
        with np.load(path, allow_pickle=False) as data:
            return {key: data[key] for key in data.files}

    def load_bytes(self, asset_id: str, key: str) -> bytes:
        record = self.get_asset(asset_id)
        rel = (record.files or {}).get(key)
        if not rel:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              f"asset {asset_id} has no file {key}",
                              stage="storage.export_full")
        return (self.root / Path(*str(rel).split("/"))).read_bytes()

    def meta_path(self, asset_id: str) -> Path:
        return self.root / "assets" / asset_id / "meta.json"


def _apply_synthetic(row: dict[str, Any], synthetic: bool, basis: str) -> None:
    """Record the measured ``synthetic_only`` flag *and* its basis on a modality row.

    A modality stays synthetic only while **every** contributing asset is: one real-capture
    asset makes the whole modality non-synthetic, and the basis string says which asset
    metadata produced the verdict.
    """
    if not synthetic:
        row["synthetic_only"] = False
        row["synthetic_basis"] = basis
    elif not row["synthetic_basis"]:
        row["synthetic_basis"] = basis


def _metadata_family(record: Any) -> str:
    if record.role == ROLE_PROVENANCE:
        return "fingerprints"
    if record.role == ROLE_PATTERN_RECIPE:
        return "recipe"
    if record.role == ROLE_ROSTER:
        return "queries"
    if record.role == ROLE_CONTEXT_PACK:
        return "excavation"
    if record.role == ROLE_EPISODE:
        return "transitions"
    return "metadata"


def _blob_family(record: Any, name: str) -> str:
    if record.role == ROLE_DISPLAY_LOD and name == "glb":
        return "glb_scene"
    return name


def _interface_subset(arrays: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    """The documented fracture-surface subset of an authoritative fragment mesh.

    Formula (recorded verbatim in the manifest):
    ``idx = np.flatnonzero(mesh.face__origin_kind == 1)`` with ``1 == INTERFACE``
    (``synlab/observe/routes.py`` ORIGIN_TO_TAG); faces/vertices and the triangle areas are
    recomputed from ``mesh.vertices``/``mesh.faces``.  Nothing is inferred: a mesh without
    ``mesh.face__origin_kind`` yields an empty subset and the modality stays ``missing``.
    """
    origin = arrays.get("mesh.face__origin_kind")
    faces = arrays.get("mesh.faces")
    vertices = arrays.get("mesh.vertices")
    if origin is None or faces is None or vertices is None:
        return {}
    idx = np.flatnonzero(np.asarray(origin).astype(np.int64) == 1)
    if idx.size == 0:
        return {}
    subset_faces = np.asarray(faces)[idx]
    v = np.asarray(vertices, dtype=np.float64)
    tri = v[subset_faces]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = 0.5 * np.linalg.norm(cross, axis=1)
    used, inverse = np.unique(subset_faces.reshape(-1), return_inverse=True)
    return {
        "iface_face_index": idx.astype(np.int64),
        "iface_faces": subset_faces.astype(np.int32),
        "iface_area_mm2": area,
        "iface_centroid": tri.mean(axis=1),
        "iface_normal": cross / np.maximum(np.linalg.norm(cross, axis=1, keepdims=True), 1e-30),
        "iface_vertices": v[used],
        "iface_vertex_index": inverse.reshape(-1).astype(np.int64),
    }


def _accumulate_measurements(recorder: _Recorder, modality_id: str, record: Any,
                             arrays: Mapping[str, np.ndarray]) -> None:
    for key, array in arrays.items():
        name = key.split(".")[-1]
        if name == "surface_tag" or name.startswith("label__surface_tag_map__"):
            is_label = name.startswith("label__surface_tag_map__")
            target = "labels.surface_tag_histogram" if is_label else "obs.surface_tag_histogram"
            values, counts = np.unique(np.asarray(array), return_counts=True)
            row = recorder.measurements.setdefault(target, {})
            for value, count in zip(values, counts):
                row[str(int(value))] = int(row.get(str(int(value)), 0)) + int(count)
            total_key = ("labels.surface_tag_total_pixels" if is_label
                         else "obs.surface_tag_total_pixels")
            recorder.measurement(
                total_key,
                pixels=int((recorder.measurements.get(total_key) or {}).get("pixels", 0))
                + int(array.size))
        elif name.endswith("face__surface_tag"):
            values, counts = np.unique(np.asarray(array), return_counts=True)
            row = recorder.measurements.setdefault("geometry.surface_tag_histogram", {})
            for value, count in zip(values, counts):
                row[str(int(value))] = int(row.get(str(int(value)), 0)) + int(count)
        elif name in ("deployment_mask", "uncertain_mask", "roi", "research_mask", "valid_mask"):
            key_name = f"obs.{name}_true"
            recorder.measurement(key_name,
                                 true=int(recorder.measurements.get(key_name, {}).get("true", 0))
                                 + int(np.count_nonzero(array)))
            total_key = f"obs.{name}_total"
            recorder.measurement(total_key,
                                 pixels=int(recorder.measurements.get(total_key, {}).get("pixels", 0))
                                 + int(array.size))
        elif name.endswith("origin_kind"):
            values, counts = np.unique(np.asarray(array), return_counts=True)
            row = recorder.measurements.setdefault("geometry.origin_kind_histogram", {})
            for value, count in zip(values, counts):
                row[str(int(value))] = int(row.get(str(int(value)), 0)) + int(count)
        elif name == "id_map":
            values = np.unique(np.asarray(array))
            seen = recorder.measurements.setdefault("obs.id_map_distinct", {"values": []})
            distinct = set(int(v) for v in values.tolist()) | set(seen.get("values") or [])
            seen["values"] = sorted(distinct)[:4096]
            seen["distinct_seen"] = len(distinct)
            recorder.measurement("obs.id_map_background",
                                 pixels=int(recorder.measurements
                                            .get("obs.id_map_background", {})
                                            .get("pixels", 0))
                                 + int(np.count_nonzero(np.asarray(array) == -1)))
        elif name == "quality__names":
            recorder.measurement("quality.channel_names",
                                 names=[str(item) for item in np.asarray(array).tolist()])


def _findings(recorder: _Recorder) -> dict[str, Any]:
    histogram = recorder.measurements.get("obs.surface_tag_histogram", {}) or {}
    total = int(recorder.measurements.get("obs.surface_tag_total_pixels", {}).get("pixels", 0))
    rim = int(histogram.get("2", 0))
    label_histogram = recorder.measurements.get("labels.surface_tag_histogram", {}) or {}
    label_total = int(recorder.measurements.get("labels.surface_tag_total_pixels",
                                                {}).get("pixels", 0))
    label_rim = int(label_histogram.get("2", 0))
    origin = recorder.measurements.get("geometry.origin_kind_histogram", {}) or {}
    face_tag = recorder.measurements.get("geometry.surface_tag_histogram", {}) or {}
    interface_faces = int(origin.get("1", 0))
    return {
        "fracture_visible_in_2d": {
            "rim_tag_pixels": rim,
            "surface_tag_pixels": total,
            "rim_fraction": (rim / total) if total else None,
            "label_bundle_rim_tag_pixels": label_rim,
            "label_bundle_surface_tag_pixels": label_total,
            "tag_histogram": histogram,
            "label_tag_histogram": label_histogram,
            "authoritative_face_surface_tag_histogram": face_tag,
            "status": "present" if (rim or label_rim) else (
                "absent" if (total or label_total) else "no_tag_map"),
            "unlock_condition": "the 2D rim channel is empty while the authoritative face "
                                "attributes still carry INTERFACE faces; it becomes usable when "
                                "the render target keeps mesh.face__origin_kind "
                                "(synlab/physical/api.py writes ORIGIN_AMBIGUOUS for every face)",
        },
        "fracture_faces_authoritative": {
            "interface_faces": interface_faces,
            "origin_kind_histogram": origin,
            "status": "present" if interface_faces else "absent",
            "unlock_condition": "produce a fragment_mesh whose mesh.face__origin_kind has "
                                "INTERFACE(1) faces",
        },
        "standalone_interface_asset": {
            "assets": 0,
            "status": "absent",
            "unlock_condition": "no store of this checkout holds a role whose payload is a "
                                "standalone fracture-surface mesh; the derived subset in "
                                "fragment_mesh.interface_faces is what exists instead",
        },
        "real_capture": {
            "assets_declaring_real_capture": int(
                recorder.measurements.get("store.declared_real_assets", {}).get("n", 0)),
            "status": "absent",
            "unlock_condition": "scan a store produced from real photographs "
                                "(real_capture=REAL_CAPTURE:PENDING today)",
        },
    }


def _missing_modalities(recorder: _Recorder) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in MODALITY_CATALOGUE:
        modality_id = item["modality_id"]
        row = recorder.modalities.get(modality_id)
        if row is None or row["status"] != "present":
            out.append((modality_id, item.get("unlock_condition", "")))
    return out


def _role_counts(records: Sequence[Any]) -> dict[str, int]:
    return dict(sorted(Counter(record.role for record in records).items()))


def _lineage_counts(records: Sequence[Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(record.lineage_id or "<none>") for record in records).items()))


# --------------------------------------------------------------------------------------
# ablation index
# --------------------------------------------------------------------------------------
def build_ablation_index(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Regroup the manifest's modalities into the dimensions an experiment can switch."""
    modalities = {row["modality_id"]: row for row in manifest.get("modalities", [])}
    groups: list[dict[str, Any]] = []
    for spec in ABLATION_GROUPS:
        members = _members_of(spec, modalities)
        present = [row for row in members if row["status"] == "present"]
        missing = [row for row in members if row["status"] != "present"]
        if present and not missing:
            availability = "present"
        elif present:
            availability = "partial"
        else:
            availability = "missing"
        measurements: dict[str, Any] = {}
        for row in members:
            for key in spec["measurement_keys"]:
                if key in (manifest.get("measurements") or {}):
                    measurements[key] = manifest["measurements"][key]
        groups.append({
            "group_id": spec["group_id"],
            "title": spec["title"],
            "question": spec["question"],
            "modality_ids": [row["modality_id"] for row in members],
            "fields": sorted({f"{row['modality_id']}#{key}"
                              for row in members for key in row["arrays"]}),
            "field_patterns": spec["field_patterns"],
            "counts": {
                "modalities_present": len(present),
                "modalities_missing": len(missing),
                "files": int(sum(row["counts"]["files"] for row in present)),
                "bytes": int(sum(row["counts"]["bytes"] for row in present)),
                "fragments": int(max([row["counts"]["fragments"] for row in present] or [0])),
                "assets": int(sum(row["counts"]["assets"] for row in present)),
                "arrays": int(sum(row["counts"]["arrays"] for row in present)),
                "instances": int(sum(row["counts"]["instances"] for row in present)),
            },
            "availability": availability,
            "missing": [{"modality_id": row["modality_id"],
                         "unlock_condition": row["unlock_condition"]} for row in missing],
            "switch": dict(spec["switch"]),
            "dependent_metrics": list(spec["dependent_metrics"]),
            "measurements": measurements,
            "permission": spec["permission"],
            "is_truth": any(row["is_truth"] for row in members),
            "is_label": any(row["is_label"] for row in members),
            "synthetic_only": all(row["synthetic_only"] for row in members) if members else True,
            "deployable_fields": sorted({f"{row['modality_id']}#{key}" for row in members
                                         if row["deployment_view_allowed"]
                                         for key in row["arrays"]}),
        })
    by_availability = Counter(group["availability"] for group in groups)
    return {
        "schema": ABLATION_INDEX_SCHEMA,
        "package_schema": manifest.get("package_schema", FULL_PACKAGE_SCHEMA),
        "flavor": manifest.get("flavor", FLAVOR_FULL),
        "generated_from": manifest.get("generated_from", {}),
        "selection": manifest.get("selection", {}),
        "how_to_use": {
            "load_one_group": "python tools/load_full_package.py --package <dir> --groups "
                              "<group_id>",
            "load_several": "--groups G-IMG-RGB,G-MASK-DEPLOY",
            "list_groups": "python tools/load_full_package.py --package <dir> --list-groups",
            "verify": "python tools/load_full_package.py --package <dir> --check  # exit 0 / 3",
            "note": "switching a group on means loading its fields; switching it off means "
                    "not loading them. Nothing is deleted from the package.",
        },
        "summary": {
            "groups": len(groups),
            "present": by_availability["present"],
            "partial": by_availability["partial"],
            "missing": by_availability["missing"],
            "fragments": manifest.get("counts", {}).get("fragments", 0),
            "files": manifest.get("counts", {}).get("files", 0),
            "bytes": manifest.get("counts", {}).get("bytes", 0),
        },
        "groups": groups,
        "permission_policy": manifest.get("permission_policy", {}),
    }


def _members_of(spec: Mapping[str, Any], modalities: Mapping[str, Any]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for pattern in spec["modality_ids"]:
        if pattern in modalities:
            members.append(modalities[pattern])
            continue
        matched = [row for key, row in sorted(modalities.items())
                   if fnmatch.fnmatchcase(key, pattern)]
        members.extend(matched)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in members:
        if row["modality_id"] in seen:
            continue
        seen.add(row["modality_id"])
        unique.append(row)
    return unique


# --------------------------------------------------------------------------------------
# reader helpers (used by tools/load_full_package.py and the tests)
# --------------------------------------------------------------------------------------
def load_full_manifest(package: str | Path) -> dict[str, Any]:
    path = Path(package) / "manifest.json"
    if not path.is_file():
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          f"no manifest.json under {package}", stage="storage.export_full")
    return json.loads(path.read_text(encoding="utf-8"))


def check_full_package(package: str | Path) -> dict[str, Any]:
    """Verify that the file set on disk is exactly the manifest's file set.

    Returns ``{"ok": bool, "problems": [...], "exit_code": 0|3, ...}``.  Exit code 3 is the
    "inconsistent" verdict used by the other checkers of this repository.
    """
    root = Path(package)
    problems: list[str] = []
    manifest_path = root / "manifest.json"
    index_path = root / "ablation_index.json"
    if not manifest_path.is_file():
        return {"ok": False, "problems": [f"missing {manifest_path}"], "exit_code": 3,
                "files_declared": 0, "files_on_disk": 0, "bytes_on_disk": 0}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = {entry["path"]: entry for entry in manifest.get("files", [])}
    declared["manifest.json"] = {"bytes": manifest_path.stat().st_size}
    if index_path.is_file():
        declared["ablation_index.json"] = {"bytes": index_path.stat().st_size}
    readme = root / "README.md"
    if readme.is_file():
        declared["README.md"] = {"bytes": readme.stat().st_size}
    on_disk = {str(path.relative_to(root)).replace("\\", "/")
               for path in root.rglob("*") if path.is_file()}
    on_disk = {path for path in on_disk if not path.endswith(".part")}
    for path in sorted(set(declared) - on_disk):
        problems.append(f"declared but absent: {path}")
    for path in sorted(on_disk - set(declared)):
        problems.append(f"present but undeclared: {path}")
    bytes_on_disk = 0
    checked = 0
    for path in sorted(set(declared) & on_disk):
        file = root / path
        size = file.stat().st_size
        bytes_on_disk += size
        expected = declared[path].get("bytes")
        if expected is not None and int(expected) != size:
            problems.append(f"size mismatch: {path} declared={expected} on_disk={size}")
        digest = declared[path].get("sha256")
        if digest and path not in ("manifest.json", "ablation_index.json", "README.md"):
            actual = hash_file(file)
            if actual != digest:
                problems.append(f"sha256 mismatch: {path} declared={digest} on_disk={actual}")
        checked += 1
    return {
        "ok": not problems,
        "problems": problems,
        "exit_code": 0 if not problems else 3,
        "package": str(root),
        "flavor": manifest.get("flavor"),
        "files_declared": len(declared),
        "files_on_disk": len(on_disk),
        "files_checked": checked,
        "bytes_on_disk": int(bytes_on_disk),
        "modalities_present": manifest.get("counts", {}).get("modalities_present", 0),
        "modalities_missing": manifest.get("counts", {}).get("modalities_missing", 0),
        "fragments": manifest.get("counts", {}).get("fragments", 0),
    }


def render_readme(manifest: Mapping[str, Any], index: Mapping[str, Any]) -> str:
    """Generate the package README from the manifest (no hand-written numbers)."""
    counts = manifest.get("counts", {})
    lines: list[str] = []
    lines.append("# full 导出包（flavor=`full`，最大视图）")
    lines.append("")
    lines.append(f"* 来源库：`{manifest.get('generated_from', {}).get('store','')}`")
    lines.append(f"* schema：`{manifest.get('schema','')}` / 消融索引 `{index.get('schema','')}`")
    lines.append(f"* 选择：{json.dumps(manifest.get('selection', {}), ensure_ascii=False)}")
    lines.append(f"* 文件 **{counts.get('files', 0)}** 个 / **{counts.get('bytes', 0)}** 字节；"
                 f"碎片 **{counts.get('fragments', 0)}**；模态 present "
                 f"**{counts.get('modalities_present', 0)}** / missing "
                 f"**{counts.get('modalities_missing', 0)}**")
    lines.append(f"* 消融组 **{index.get('summary', {}).get('groups', 0)}**：present "
                 f"{index.get('summary', {}).get('present', 0)} / partial "
                 f"{index.get('summary', {}).get('partial', 0)} / missing "
                 f"{index.get('summary', {}).get('missing', 0)}")
    lines.append("")
    lines.append("## 加载方式")
    lines.append("")
    lines.append("```powershell")
    lines.append("& .venv\\Scripts\\python.exe tools\\load_full_package.py --package <本目录> "
                 "--list-groups")
    lines.append("& .venv\\Scripts\\python.exe tools\\load_full_package.py --package <本目录> "
                 "--groups G-IMG-RGB,G-FRAC-ATTR")
    lines.append("& .venv\\Scripts\\python.exe tools\\load_full_package.py --package <本目录> "
                 "--check          # exit 0 = 一致 / 3 = 不一致")
    lines.append("```")
    lines.append("")
    lines.append("## 逐模态（present）")
    lines.append("")
    lines.append("| modality_id | files | bytes | fragments | arrays | deploy | truth | derived |")
    lines.append("|---|---:|---:|---:|---:|:--:|:--:|:--:|")
    for row in manifest.get("modalities", []):
        if row["status"] != "present":
            continue
        lines.append(f"| `{row['modality_id']}` | {row['counts']['files']} | "
                     f"{row['counts']['bytes']} | {row['counts']['fragments']} | "
                     f"{row['counts']['arrays']} | "
                     f"{'是' if row['deployment_view_allowed'] else '否'} | "
                     f"{'是' if row['is_truth'] else '否'} | "
                     f"{'是' if row['derived'] else '否'} |")
    lines.append("")
    lines.append("## 缺失模态与解锁条件")
    lines.append("")
    lines.append("| modality_id | 缺什么才能有 |")
    lines.append("|---|---|")
    for row in manifest.get("modalities", []):
        if row["status"] == "present":
            continue
        lines.append(f"| `{row['modality_id']}` | {row['unlock_condition']} |")
    lines.append("")
    lines.append("## 消融组")
    lines.append("")
    lines.append("| group_id | 可用性 | 模态数(有/缺) | 字段数 | 权限 | 问题 |")
    lines.append("|---|---|---:|---:|:--:|---|")
    for group in index.get("groups", []):
        row_counts = group["counts"]
        lines.append(f"| `{group['group_id']}` | {group['availability']} | "
                     f"{row_counts['modalities_present']}/{row_counts['modalities_missing']} | "
                     f"{len(group['fields'])} | {group['permission']} | {group['question']} |")
    lines.append("")
    lines.append("> 本文件由 `synlab/storage/export_full.py` 从 manifest 自动生成；每个数字都可在 "
                 "`manifest.json` 中复算。")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m synlab.storage.export_full",
        description="Maximal (flavour=full) export of an asset store plus its ablation index.")
    parser.add_argument("--store", required=True, help="store root holding metadata.sqlite")
    parser.add_argument("--out", default=None, help=f"output directory (default {DEFAULT_OUT_ROOT})")
    parser.add_argument("--flavor", default=FLAVOR_FULL, choices=list(FLAVORS))
    parser.add_argument("--limit", type=int, default=None,
                        help="export only the first N fragments (recorded in the manifest)")
    parser.add_argument("--fragments", default=None,
                        help="comma-separated fragment ids to export")
    parser.add_argument("--no-derived", action="store_true",
                        help="skip the derived fracture-surface subset")
    parser.add_argument("--dry-run", action="store_true", help="plan only; write nothing")
    parser.add_argument("--check", action="store_true", help="check an existing package instead")
    args = parser.parse_args(argv)

    if args.check:
        verdict = check_full_package(args.out or args.store)
        print(json.dumps(_jsonable(verdict), ensure_ascii=False, indent=2))
        return int(verdict["exit_code"])

    fragments = [item.strip() for item in args.fragments.split(",") if item.strip()] \
        if args.fragments else None
    manifest = export_full_package(
        args.store, args.out or DEFAULT_OUT_ROOT, flavor=args.flavor, fragments=fragments,
        limit=args.limit, derived=not args.no_derived, dry_run=args.dry_run,
        progress=lambda i, n, role: print(f"  [{i}/{n}] {role}", flush=True))
    summary = {
        "flavor": manifest["flavor"],
        "store": manifest["generated_from"]["store"],
        "assets_exported": manifest["generated_from"]["assets_exported"],
        "fragments": manifest["counts"]["fragments"],
        "files": manifest["counts"]["files"],
        "bytes": manifest["counts"]["bytes"],
        "modalities_present": manifest["counts"]["modalities_present"],
        "modalities_missing": manifest["counts"]["modalities_missing"],
        "ablation": manifest["ablation_summary"],
        "wall_seconds": manifest["wall_seconds"],
    }
    print(json.dumps(_jsonable(summary), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
