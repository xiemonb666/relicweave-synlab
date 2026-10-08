# Bounded CAD-volume candidate spike

**Status:** `FAIL_CANDIDATE_ACCEPTANCE`. This is a geometry representation candidate only; it is not a PG solver job or a fracture/fragment result.

## Canonical input

- STEP: `relicweave-synlab/tmp/review_20261003/implementation/vf/artifacts/four_bands_brep_semantics1_final/geometry/solid.step`
- SHA-256: `4623bd373aeed0acfacfbf6cc0dda65952339561779b43429c59d61b8b5a1c30` (matches manifest; 126052 bytes)
- Coordinate frame / length unit: `right_handed_z_up` / `mm`
- B-rep: 1 valid solid, 1 shell; volume 25946.947771 mm³; bbox 53.100×41.000×56.000 mm

## Mesh trials

| Target size (mm) | Status | Volume cells | Absolute volume error | Native OCC centroid states |
|---:|---|---:|---:|---|
| 8 | FAIL_CANDIDATE_ACCEPTANCE | 1313 | 2.03434% | {'IN': 1307, 'OUT': 6, 'UNKNOWN': 0} |
| 6 | SKIPPED_PREDICTED_CELL_BUDGET | — | — | — |

The proposed CAD volume error gate is 1.00%; it was not adjusted to force acceptance.

## Selected quadrature candidate

- NPZ: `cad_volume_candidate.npz`
- PNG: `cad_volume_candidate.png`
- Selected target size / cells: 8 mm / 1313
- Tetra volume sum: 25419.097420 mm³; signed relative error -2.034345%
- Cell-volume quadrature mass: 0.053380105 kg at rho=2100 kg/m³ (`UNVALIDATED_PROTOTYPE`)
- Point-mass conservation error against rho×tetra-volume sum: 0.000e+00
- Centroid OCC states: `{'IN': 1307, 'OUT': 6, 'UNKNOWN': 0}`; finite interior sample states: `{'IN': 491, 'OUT': 21, 'UNKNOWN': 0}`
- Empty cavity subset: `{'IN': 0, 'OUT': 119, 'UNKNOWN': 0}` for 119 finite OCC-classified probes; candidate centroids in that subset: 0

## Segment obstruction probe

Status: `PROBE_ONLY_NOT_NATIVE_BOND_GRAPH`; cross-wall examples: 3; same-wall controls: 3.
Each tested segment requires both endpoints to classify OCC IN. OCC face intersections partition the finite line, then native solid classification labels interval midpoints. This remains a small geometry probe with no horizon and no native PG bond graph.

## Scope and limitations

- Linear tetrahedral boundary facets approximate curved CAD faces. The cell-centroid checks and finite samples are evidence for this mesh, not a global boundary proof.
- The centroid set is an irregular discretization; directional bias, free-surface correction, and horizon selection remain pending.
- The reported 4 mm wall is the upstream analytic/profile check. This experiment does not prove a global minimum wall thickness over the fused solid.
- rho=2100 kg/m³ and the other mechanics values are unvalidated placeholders. Mass conservation here is only density times the candidate volume weights.
- No crack surfaces, R2 fragment geometry, supported PG asset/job schema, or solver output are created.

## Reproduction

```powershell
& 'third_party/vesselforge-runtime/venv/Scripts/python.exe' -u 'pgfrag/experiments/cad_volume_spike.py' --asset-dir 'relicweave-synlab/tmp/review_20261003/implementation/vf/artifacts/four_bands_brep_semantics1_final' --output-dir 'relicweave-synlab/tmp/review_20261003/implementation/pg/volume_candidate' 2>&1 | Tee-Object -FilePath 'relicweave-synlab/tmp/review_20261003/implementation/pg/volume_candidate/run.log'
```

The command uses the existing VesselForge Python environment read-only plus the isolated official Gmsh 4.15.2 SDK under `third_party/pgfrag-geometry-runtime`; it installs no packages and writes only this spike's output directory.
Official references: [Gmsh documentation](https://gmsh.info/doc/texinfo/) (OCC `importShapes`, STEP tutorial t20, 3D tetrahedral mesh API) and [CadQuery STEP import documentation](https://cadquery.readthedocs.io/en/latest/importexport.html).
