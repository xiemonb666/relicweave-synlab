# Fixed native CAD wall-resolution study

This is a bounded, local static-mesh study of the thin sidewall opposite the +X handle. It uses the canonical STEP with SHA-256 `4623bd373aeed0acfacfbf6cc0dda65952339561779b43429c59d61b8b5a1c30` and one native OpenCASCADE common with the fixed box `x=[-23,-14]`, `y=[-1.4,1.4]`, `z=[23.1,25.9] mm`. The exact OCC intersection volume is **31.5898009 mm³**. No solver, bonds, crack, or fracture surface was generated.

The preflight forecast was 961 tetrahedra for `h=1.0 mm` and 7,686 for `h=0.5 mm`, including a 15% margin from the preserved whole-vessel mesh densities. Both forecasts are below the fixed 10,000-tet cap. Each declared h was then meshed once, with a 180-second subprocess cap and Gmsh thread settings fixed to one. Neither ROI, h, cap, nor acceptance threshold changed.

| Target h | Tetrahedra | Mesh generation | End-to-end subprocess | Volume error | Signed orientation | Native centroid IN | Stratified samples IN | Result |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1.0 mm | 292 | 0.020 s | 5.58 s | 0.02332% | 292 positive, 0 negative | 292/292 | 291/292 | **Failed the point-IN check** |
| 0.5 mm | 1,506 | 0.021 s | 18.43 s | 0.00438% | 1,506 positive, 0 negative | 1,506/1,506 | 512/512 | **Passed local checks** |

Both meshes satisfy the unchanged 1% volume gate and stay under the tet cap. The h=1 mm exception is sample ordinal 226 in tetra cell 479. Its barycentric sample is `[-16.1936193, -0.9037109, 25.7285244] mm`, classified OUT by the canonical B-rep and 0.0004073 mm from the native solid. Its cell centroid is IN. The read-only repeat is in [pointin_exception_audit.json](h1mm/pointin_exception_audit.json); this finding is preserved as a failure, with no remesh or parameter adjustment.

## Native wall span and through-wall distribution

Forty-nine direct B-rep normal rays measured an outer-to-opposing-inner wall span of **4.000000 mm** at every sample (median 4.000000 mm). Same-z radial thickness was 4.025233 mm. For cell-centroid distributions, each native radial interval is projected along the local outer-cone normal and normalized by the nearest of those direct native normal-span samples. This gives candidate `t/h` ratios of **4.0** at h=1.0 mm and **8.0** at h=0.5 mm. The ratio of eight is a candidate sampling observation for this wall and setup, not a universal physics sufficiency rule.

The centroid histogram covers ten equal 10%-thickness bands; all ten bands are populated for both h values. It describes unstructured tetrahedral centroid locations, not structured element layers. The per-band counts are recorded in each trial report under `through_wall_normal_sampling.normal_fraction_10pct_band_counts`.

The δ=1.0 mm directional-fabric diagnostic uses the declared core `x < -14.5 mm`, `|y| <= 0.3 mm`, `z=24.2..24.8 mm`. Every selected center is at least 1.1 mm from all six box cut planes: minimum clearance is 1.1346 mm at h=1.0 and 1.1005 mm at h=0.5. There are 9 eligible centers at h=1.0 and 56 at h=0.5. δ remains an exploratory candidate, not a selected or calibrated material length.

For each core center, the discrete mesh fabric is compared with a same-radius ball sampled uniformly in volume and classified inside the untouched canonical STEP. The reference therefore includes physical CAD wall truncation. Median per-center mesh fabric anisotropy is 1.952 at h=1.0 and 1.133 at h=0.5; median native truncated-reference anisotropy is 1.338 and 1.073. Median Frobenius error against that reference is 0.1007 and 0.0290, respectively. These are local directional-support diagnostics with a small center count at h=1.0; they do not select δ or validate mechanics.

## Mesh quality and existing whole-vessel results

Per-cell maximum edge and pooled six-edge statistics are separate fields in the JSON reports. For the local ROI, the median/max per-cell maximum edge is 1.314/1.658 mm at h=1.0 and 0.758/1.000 mm at h=0.5. The median circumradius/inradius ratio is 3.798 and 3.802; the worst minimum dihedral angle is 15.67° and 11.49°. Neither local mesh has a cell below 10° minimum dihedral or above radius ratio 10.

The existing whole-CAD h=8 and h=6 results below are copied from [existing_whole_mesh_audit.json](../../../review_20261003/implementation/pg/wall_resolution/existing_whole_mesh_audit.json); they were not regenerated for this study. Those whole-vessel meshes were signed-tet positive, but supplied only 5 and 10 centroids in the previous wall ROI and contain poor cells:

| Existing whole-CAD h | Tetrahedra | Wall ROI centroids | Median/max per-cell max edge | Median/max radius ratio | Minimum dihedral | Cells below 10° | Radius ratio >100 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 mm | 1,313 | 5 | 7.789 / 10.666 mm | 4.219 / 113.108 | 4.35° | 9 | 2 |
| 6 mm | 2,030 | 10 | 6.106 / 8.478 mm | 3.662 / 112.614 | 5.92° | 10 | 2 |

The native wall span and ROI volume make the local wall sampling visible, while the local h=1 mm point-IN exception remains a real check failure. The h=0.5 mm mesh is the better of these two geometry candidates by the reported sampling and fabric measures, but this experiment proves neither spatial nor temporal convergence, crack support, a fracture law, nor a calibrated material horizon. A separate convergence study would hold the material and δ fixed while refining h, then hold the mesh fixed and refine time step; it would also need thin-wall response and remeshing-direction checks.

## Artifacts and provenance

- [run_index.json](run_index.json) records the exact argv, Python executable, exit codes, timeout, thread environment, source and output hashes, and both trial reports.
- [preflight.json](preflight.json) records the exact native OCC volume and fixed-h forecasts.
- [h=1.0 mm report](h1mm/report.json) and [h=0.5 mm report](h0.5mm/report.json) contain signed-tet, volume, point-IN, edge, radius-ratio, dihedral, boundary, wall-layer, and directional-fabric metrics.
- [h=1.0 mm section](h1mm/actual_section_y0_h1mm.png), [h=0.5 mm section](h0.5mm/actual_section_y0_h0.5mm.png), and [side-by-side sections](actual_sections_h1mm_vs_h0p5mm.png) show actual tetra intersections with the interior `y=0` plane. The dashed native inner wall and solid native outer wall are CAD references; red dotted lines mark artificial box cuts. The section is not a crack plane.
- The executable scripts are `pgfrag/experiments/wall_resolution/run_roi_trial.py`, `execute_predeclared_study.py`, and `audit_pointin_samples.py`; the experiment-local mesh metrics are in `mesh_audit.py`.
