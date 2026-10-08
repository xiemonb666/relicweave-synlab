# OCC-native clipped Cartesian volume-cell spike

Status: FAIL_STATIC_NATIVE_GEOMETRY_CANDIDATE

Static geometry candidate only. This is not an accepted PG job, solver input, native bond graph, realistic fragment result, or R2 result.

## Source and fixed policy

- Canonical STEP: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261003\implementation\vf\artifacts\four_bands_brep_semantics1_final\geometry\solid.step
- SHA-256: 4623bd373aeed0acfacfbf6cc0dda65952339561779b43429c59d61b8b5a1c30 (manifest verified)
- Frame and length unit: right_handed_z_up, mm
- Fixed grid: 8.0 mm; OCC Common single-thread; box cap 512
- Processed boxes: 1 / 294
- Exact null Common results: 0
- Positive connected native solids retained: 0
- Non-null Common without positive solids: 1
- Exceptions and geometry gate failures: 2
- Boolean time: 0.031 s (limit 300 s)

## Geometry and volume quadrature

- Exact CAD B-rep volume: 25946.947770950 mm3
- Sum of retained exact native volumes: 0.000000000 mm3
- Relative error: 100.000000% (gate 1.000%)
- CAD B-rep bbox in mm: [-20.5, 32.6000001, -20.5, 20.5, 0.0, 56.0]
- Finite positive components: 0 / 0
- Native COM classifications: {}
- Unique COMs at 1e-9 mm: 0 / 0
- Each retained connected solid contributes one native center of mass and its exact positive B-rep volume. Separate solids inside one box remain separate.

## Cavity and mass

- Cavity probes: {'OUT': 63} over axis-centered points at radii 0, 4, 8 mm (four azimuths for nonzero radii), z=8,16,24,32,40,48,52 mm
- Mass from manifest rho 2100.0 kg/m3: 0.000000000000 kg
- Relative mass difference from CAD volume: 100.000000%
- Material calibration: UNVALIDATED_PROTOTYPE

## Gates and limits

- canonical_manifest_and_step_hash_match: PASS
- canonical_one_valid_solid: PASS
- fixed_cartesian_grid_covers_exact_bbox: PASS
- candidate_box_count_at_most_512: PASS
- every_box_common_processed: FAIL
- native_boolean_single_thread: PASS
- boolean_wall_time_at_most_300_seconds: PASS
- only_exact_null_common_omitted: FAIL
- all_retained_components_valid_finite_positive: FAIL
- all_component_coms_natively_inside: FAIL
- cavity_probes_classify_out: PASS
- native_volume_error_at_most_1_percent: FAIL
- manifest_rho_mass_conservation_arithmetic: FAIL
- actual_occ_sections_png_created: FAIL
- physics_and_pg_acceptance: FAIL
- Exact OCC common partition addresses CAD geometric volume coverage only. An 8 mm cell spacing exceeds the nominal 4 mm wall and is not adequate evidence of physical-resolution quality.
- Cell size does not guarantee global minimum-wall resolution. One centroid per connected clipped solid is irregular quadrature and may bias directional fields; free-surface correction remains pending.
- Physical resolution, curvature-aware refinement, crack paths, fracture energy, bond calibration, mechanics, and R2 are NOT_VALIDATED or PENDING.
- Rho is an UNVALIDATED_PROTOTYPE placeholder; the mass result demonstrates only arithmetic conservation under that placeholder.

## Artifacts

- JSON report: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261003\implementation\pg\cad_clipped_cells\fixed8mm_singlethread_case02_bbox_order_fixed\report.json
- Per-box ledger: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261003\implementation\pg\cad_clipped_cells\fixed8mm_singlethread_case02_bbox_order_fixed\cell_records.json
- Append-only run log: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261003\implementation\pg\cad_clipped_cells\fixed8mm_singlethread_case02_bbox_order_fixed\run.log
- Candidate arrays: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261003\implementation\pg\cad_clipped_cells\fixed8mm_singlethread_case02_bbox_order_fixed\cad_clipped_cells_candidate.npz
- Every retained clipped solid: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261003\implementation\pg\cad_clipped_cells\fixed8mm_singlethread_case02_bbox_order_fixed\components
- Figure: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261003\implementation\pg\cad_clipped_cells\fixed8mm_singlethread_case02_bbox_order_fixed\cad_clipped_cells_y0.png

Reproduction from the repository root in PowerShell:

    & '.\third_party\vesselforge-runtime\venv\Scripts\python.exe' 'pgfrag\experiments\cad_clipped_cells_spike.py'
