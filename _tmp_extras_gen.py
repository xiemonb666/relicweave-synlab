"""Scratch driver: one real lineage into the new synthetic-extras store.

Not a library module.  Writes the generation spec next to the new store so the run is
reproducible, then runs exactly one lineage (the host kills long heavy processes, so the
ledger is flushed to disk after the single mother).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SPEC_PATH = ROOT / "data" / "a12_extras" / "spec_extras.yaml"
STORE_ROOT = ROOT / "data" / "a12_extras" / "store"

SPEC = """schema: synlab.v3
data_scope: SYNTHETIC
release_profile: SANDBOX_CORE
experiment_purpose: SANDBOX
master_seed: 20261001
units: mm
integration:
  mode: standalone
  feature_schema: a12.obs.v1
  external_contract_ref: null
implementation:
  policy: open_source_first
  reuse_manifest_ref: docs/a12/reuse_manifest.json
  require_poc_before_custom: true
  require_gap_evidence: true
dataset:
  target_mothers: 1
  target_fragments_estimate: 10
  shape_lineage_split: {train: 1.0, dev: 0.0, confirm: 0.0}
  split_before_generation: true
  replacement_fractures_share_lineage: true
  include_all_components: true
  debris_policy: quarantine_and_record
  vessel_ids: [V01]
  material_ids: [M01]
  pattern_ids: [PAT01]
  layer_combo_ids: [L01]
  parameter_bounds_ref: configs/a12/registry_bounds.json
sampling:
  method: latin_hypercube
  quota_policy: registry_balanced
  seed_stride: 1
  sobol_power_of_two: true
pattern:
  coordinate_space: mother_surface_mm
  periodic_azimuth: true
  geometry_before_fracture: true
  antialias: analytic_or_mipmap
  height_policy: none
fracture:
  backend: plane_shared_cut
  target_piece_range: [8, 20]
  min_feature_wavelength_mm: 0.5
  shared_surface_max_error_mm: 0.01
  max_attempts: 3
  secondary_probability: 0.0
  keep_parent_history: true
  rough_amplitude_mm: [0.02, 0.15]
  seed_count_range: [8, 16]
physical:
  recipe_registry_ref: configs/a12/physical_recipes.json
  preserve_clean_assets: true
  recipes: [P03_depth_light]
observation:
  input_profile: SENSOR_PROXY
  routes: [proxy_scan]
  views_per_fragment: 4
  image_long_edge_px: 256
  point_count: 2048
  camera_profile_ref: configs/a12/camera_profiles.json
  persist_depth: selected_qa_only
  persist_view_geometry: false
  persist_fused_geometry: true
  truth_channels_role: research_label_only
  renderer: auto
resources:
  cpu_workers: 2
  threads_per_worker: 2
  cpu_rss_budget_gb: 30
  gpu_device: 0
  gpu_concurrency: 1
  gpu_budget_gb: 26
  disk_soft_fraction: 0.70
  disk_restrict_fraction: 0.80
  disk_stop_fraction: 0.90
  reserve_temp_peak: true
storage:
  root: data/a12_extras/store
  database: data/a12_extras/store/metadata.sqlite
  shard_target_mb: 512
  mutable_release: false
quality:
  protocol_ref: configs/a12/qa_protocol_v1.json
  fail_closed: true
  freeze_before_confirmation: true
degraded_recipe_refs:
  - configs/a12/degrade_recipes/paired_plane_levels.yaml
notes: "synthetic-extras lineage: one real lineage for the §8 extras walk-through."
"""


def main() -> int:
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(SPEC, encoding="utf-8")
    print(f"[spec] {SPEC_PATH}")

    from synlab.config import load_generation_spec
    from synlab.pipeline import plan_generation, run_generation

    spec = load_generation_spec(SPEC_PATH)
    plan = plan_generation(spec, max_mothers=1)
    print(f"[plan] lineages={len(plan.lineages)} job_id={plan.job_id} "
          f"spec_hash={plan.spec_hash[:12]}")
    print(f"[plan] lineage_ids={[l.lineage_id for l in plan.lineages]}")

    t0 = time.time()

    def progress(row: dict) -> None:
        print(f"[progress] {json.dumps(row)} t={time.time() - t0:.1f}s", flush=True)

    report = run_generation(spec, store_root=STORE_ROOT, max_mothers=1,
                            progress=progress)
    print(f"[report] {json.dumps({k: v for k, v in report.items() if k != 'rows'}, default=str)}")
    (ROOT / "_tmp_extras_gen_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[done] seconds={time.time() - t0:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
