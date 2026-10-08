# OCC-native clipped Cartesian volume-cell spike

Status: FAIL_STATIC_NATIVE_GEOMETRY_CANDIDATE
Run state: INCOMPLETE_COM_OUT

Static geometry candidate only. This is not an accepted PG job, solver input, native bond graph, realistic fragment result, or R2 result.

## Source and fixed policy

- Canonical STEP: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261003\implementation\vf\artifacts\four_bands_brep_semantics1_final\geometry\solid.step
- SHA-256: 4623bd373aeed0acfacfbf6cc0dda65952339561779b43429c59d61b8b5a1c30 (manifest verified)
- Frame and length unit: right_handed_z_up, mm
- Fixed grid: 8.0 mm; OCC Common single-thread; box cap 512
- Processed boxes: 58 / 294
- Exact null Common results: 0
- Total 3D-material empty cells (null or legal empty compound): 9
- Native valid empty-material compound results: 9
- Positive connected native solids retained: 49
- Non-null Common without positive solids: 0
- Exceptions and geometry gate failures: 1
- Boolean time: 0.656 s; whole run: 1.187 s (both limited to 300 s)

## Geometry and volume quadrature

- Exact CAD B-rep volume: 25946.947770950 mm3
- Processed clipped-component volume subtotal: 7699.598017564 mm3
- Retained subtotal / full CAD volume: 29.674388%
- Full-partition relative volume error: NOT_EVALUATED_INCOMPLETE_PARTITION
- CAD B-rep bbox in mm: [-20.5, 32.6000001, -20.5, 20.5, 0.0, 56.0]
- Finite positive components: 49 / 49
- Native COM classifications: {'IN': 48, 'OUT': 1}
- Unique COMs at 1e-9 mm: 49 / 49
- Each retained connected solid contributes one native center of mass and its exact positive B-rep volume. Separate solids inside one box remain separate.

## Cavity and mass

- Cavity probes: {'OUT': 63} over axis-centered points at radii 0, 4, 8 mm (four azimuths for nonzero radii), z=8,16,24,32,40,48,52 mm
- Manifest rho 2100.0 kg/m3; processed subtotal mass: 0.016169155837 kg
- Full-partition mass error: NOT_EVALUATED_INCOMPLETE_PARTITION
- Material calibration: UNVALIDATED_PROTOTYPE

## Gates and limits

- actual_occ_sections_png_created: PASS
- all_component_coms_natively_inside: FAIL
- all_retained_components_valid_finite_positive: PASS
- all_weights_and_units_finite_positive: PASS
- boolean_wall_time_at_most_300_seconds: PASS
- candidate_box_count_at_most_512: PASS
- canonical_manifest_and_step_hash_match: PASS
- canonical_one_valid_solid: PASS
- cavity_probes_classify_out: PASS
- corrected_section_covers_left_right_walls_and_full_z_bbox: PASS
- every_box_common_processed: FAIL
- fixed_cartesian_grid_covers_exact_bbox: PASS
- manifest_rho_mass_conservation_arithmetic: FAIL
- native_boolean_reports_no_errors_or_warnings: PASS
- native_boolean_single_thread: PASS
- native_volume_error_at_most_1_percent: FAIL
- only_exact_or_native_valid_empty_3d_material_omitted: PASS
- physics_and_pg_acceptance: FAIL
- whole_run_wall_time_at_most_300_seconds: PASS

## Exact section figure diagnostic

- Corrected PNG SHA-256: 7f0e26809153e7f495f5feef46b99daf41e312428f9ff2d6c377e2deb215168f
- Source OCC y=0 section curves: 49
- Sampled section bounds xmin,xmax,zmin,zmax (mm): [-20.500000000000103, 32.6, 0.0, 56.0]
- Both body walls sampled across z bands: {'8': {'negative_x_wall_sampled': True, 'positive_x_wall_sampled': True, 'sample_count': 53}, '16': {'negative_x_wall_sampled': True, 'positive_x_wall_sampled': True, 'sample_count': 63}, '24': {'negative_x_wall_sampled': True, 'positive_x_wall_sampled': True, 'sample_count': 40}, '32': {'negative_x_wall_sampled': True, 'positive_x_wall_sampled': True, 'sample_count': 38}, '40': {'negative_x_wall_sampled': True, 'positive_x_wall_sampled': True, 'sample_count': 62}, '48': {'negative_x_wall_sampled': True, 'positive_x_wall_sampled': True, 'sample_count': 48}, '52': {'negative_x_wall_sampled': True, 'positive_x_wall_sampled': True, 'sample_count': 40}}
- COM markers are XZ projections, not points constrained to y=0: True
- Superseded clipped figure retained at: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261004\implementation\cad_clipped_cells\fixed8mm_singlethread_case03_native_empty_compound_policy\cad_clipped_cells_y0_SUPERSEDED_wrong_plane_uv.png
- Exact OCC common partition addresses CAD geometric volume coverage only. An 8 mm cell spacing exceeds the nominal 4 mm wall and is not adequate evidence of physical-resolution quality.
- Cell size does not guarantee global minimum-wall resolution. One centroid per connected clipped solid is irregular quadrature and may bias directional fields; free-surface correction remains pending.
- Physical resolution, curvature-aware refinement, crack paths, fracture energy, bond calibration, mechanics, and R2 are NOT_VALIDATED or PENDING.
- Rho is an UNVALIDATED_PROTOTYPE placeholder; the mass result demonstrates only arithmetic conservation under that placeholder.
- A native COM outside the canonical source is a candidate FAIL. The exact native centroid is retained for evidence; it is not moved and no alternate interior point is substituted for the same quadrature rule.

## Artifacts

- JSON report: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261004\implementation\cad_clipped_cells\fixed8mm_singlethread_case03_native_empty_compound_policy\report.json
- Per-box ledger: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261004\implementation\cad_clipped_cells\fixed8mm_singlethread_case03_native_empty_compound_policy\cell_records.json
- Append-only run log: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261004\implementation\cad_clipped_cells\fixed8mm_singlethread_case03_native_empty_compound_policy\run.log
- Candidate arrays: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261004\implementation\cad_clipped_cells\fixed8mm_singlethread_case03_native_empty_compound_policy\cad_clipped_cells_candidate.npz
- Every retained clipped solid: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261004\implementation\cad_clipped_cells\fixed8mm_singlethread_case03_native_empty_compound_policy\components
- Figure: C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261004\implementation\cad_clipped_cells\fixed8mm_singlethread_case03_native_empty_compound_policy\cad_clipped_cells_y0_ax3_corrected.png

Reproduction from the repository root in PowerShell:

    & '.\third_party\vesselforge-runtime\venv\Scripts\python.exe' 'pgfrag\experiments\cad_clipped_cells_spike.py'

## Process execution

- Argv: `["C:\\Users\\xiemo\\Desktop\\ShardForge\\third_party\\vesselforge-runtime\\venv\\Scripts\\python.exe", "pgfrag\\experiments\\cad_clipped_cells_spike.py"]`
- Exit code: 1
- Runtime: 1.187 s
- Started: 2026-10-03T18:10:55+00:00; finished: 2026-10-03T18:10:56.187+00:00
