# A12 native bowl diagnostic bridge (2026-10-15)

`synlab.integrations.native_bowl` is a new, isolated reader for one VesselForge
`forge.asset.v1` bowl package and one PG-Frag `pgfrag.native_bowl_result.v1`
run. It verifies source bytes and native point-state consistency, copies both
sources into a new immutable A12 diagnostic package, and can export a research
point-snapshot view plus a separate offline physics-target payload.

This module is not wired into `run_generation`, the A12 fragment pipeline, the
release exporter, or PRETRAIN. It creates no shards, R2 relations, R0 labels,
negative labels, or deployment eligibility. Components remain active-graph
components; they are not certified fragments. Physical fragments, positive-area
crack surfaces, fracture validation, R2, and PRETRAIN all remain `UNKNOWN` or
false.

## Input contract and checks

The PG result uses the exact SHA-256 of the raw bytes of the source
`manifest.json` as `source_forge_manifest_sha256`. A12 recomputes that byte
digest and compares it with both the PG result and any caller-supplied digest.
It verifies the Forge file table, PG result JSON, the arrays NPZ descriptor, and
every path/size/SHA record in PG `outputs`. Source paths must be normalized
relative paths without symlinks or path traversal.

Forge and PG material values must match field by field for `rho_kg_m3`, `E_pa`,
`nu`, and `Gc_j_m2`; both must retain `UNVALIDATED_PROTOTYPE`. A12 checks every
`point_mass_kg[i] == material.rho_kg_m3 * volume_m3[i]`, including isolated
points, and checks the reported model mass against the complete sum. These are
model-input accounting checks: the bowl uses approximate centroid `h^3`
quadrature and its mass is not a measured specimen mass.

The reader requires SI values, original reference coordinates, a complete
contiguous trajectory from step zero, finite state arrays, strictly increasing
time, and canonical sorted `i < j` pairs. It checks that initial point centers
lie inside the lower hemispherical shell, retained bond rest lengths match the
original coordinates, and every retained bond segment stays outside the inner
spherical void. The little-bit-order `bond_active_packed` rows are checked for
zero padding, irreversible breakage, and exact agreement with the first-break
event table. Damage fractions and component labels are reconstructed from the
active graph. Event stretches and pair energies are checked against the saved
state and the native BB formula.

The validator enforces the frozen input bounds of 12,000 points, 1,000 steps,
2,000,000 pairs, and 256 MiB total bytes across the actual PG package files;
it checks the compressed arrays file and separately bounds NPZ uncompressed
members. The 256 MiB cap is the root-approved update for full-trajectory audit
I/O. A successful validation
means the source binding and these internal consistency checks passed. It does
not certify experimental or physical validity.

## Output separation

`run_manifest.json` records the exact source hashes, complete source file
inventories, counts, diagnostic-only qualification, and limitations. The ingest
command refuses an existing output path and revalidates the copied bytes before
committing the new directory.

`dataset_manifest.json` uses schema
`synlab.native_bowl_research_dataset.v1`. Its only data payloads are
`research_feature_view.npz` and `physics_target.npz`; the loader rejects extra
payload files. The feature NPZ has exactly one array:

- `position_m`: current positions in metres, independently rotated and
  permuted for each selected saved state.

The feature view is labeled `SIMULATION_POINT_SNAPSHOT`,
`rig_obtainable=false`, and `research_only=true`. It has no point IDs,
reference coordinates, simulation time, velocity, damage, events, graph,
components, or alignment map. Simulation time is available only in the
offline physics target. Sensor frames and point orders are independently
randomized per state, so these snapshots do not define point tracks or a
measured dynamic scan. This is not a physical scanner output or a deployment
feature view.

The physics-target NPZ is marked `OFFLINE_ONLY` and contains the source point
state, IDs, references, packed active graph, events, components, damage, mass,
and the feature-to-source alignment. Its raw velocities remain in the native
world frame. `NativeBowlDataset.aligned_targets()` applies the saved per-state
rotation and permutation, returning velocity in each snapshot's sensor frame;
damage is permuted as a scalar. The independent per-state frames mean this
alignment supports per-snapshot diagnostics, not temporal point tracking.

Qualification fields are fail-closed: physical validation, crack surface,
physical fragments, and R2 remain `UNKNOWN`; relation and negative labels are
`NOT_GENERATED`; production, deployment, and PRETRAIN flags are false. The
loader rejects attempts to promote `UNKNOWN` to `R0` or add answer-bearing fields
to the feature payload.

## CLI

Run from `relicweave-synlab` with the project Python environment:

```powershell
.venv/Scripts/python.exe -m synlab.integrations.native_bowl validate `
  --vf-dir <forge-package> --pg-dir <pg-result>

.venv/Scripts/python.exe -m synlab.integrations.native_bowl ingest `
  --vf-dir <forge-package> --pg-dir <pg-result> --out <new-run-directory>

.venv/Scripts/python.exe -m synlab.integrations.native_bowl export `
  --run <ingested-run-directory> --out <new-dataset-directory> --seed 20261015
```

The Python loader is `load_native_bowl_dataset(path)`. It verifies the dataset
manifest and both payload hashes, strict feature allowlist, array shapes and
dtypes, proper sensor rotations, per-state permutations, transform-to-feature
consistency, physics-target mass/graph/event consistency, and diagnostic-only
qualification before returning separate `research_features` and
`physics_targets` mappings.

## Tests

`tests/a12/integrations/test_native_bowl.py` uses a small synthetic source
package and three-state native result. It covers validate → ingest → export →
load, exact manifest-byte binding, full point-mass accounting with an isolated
point, event/graph/component rejection, material source binding, payload hash
tampering, feature identity leakage, `UNKNOWN` to `R0` promotion, and
sensor-frame vector target alignment.
