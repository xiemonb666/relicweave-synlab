# P03 wall-interval integration design (read-only snapshot)

## Conclusion

At the inspected snapshot, P03 has both the source fragment mesh and the final clipped result mesh, so the interval helper can measure continuous material intervals **if** it is given a trusted station and wall direction. Current P03 inputs do not provide that wall mapping. The interface ROI face normal is a fracture/interface normal, not evidence of an inner-to-outer or through-wall direction. Consequently there is no defensible way to construct the helper's station/direction pair from the current P03 fields alone. Until an explicit, source-bound wall map is present, P03 must retain structured `UNKNOWN` and reject physical success.

The local helper's all-hit sample result is not a global minimum-wall proof. Even with a complete map and all requested samples passing, report `sampled_status=SAMPLED_PASS`, `global_wall_status=UNVERIFIED`, and `physical_qualification_status=UNKNOWN`. Do not rename a sampled pass to generic `PASS` to satisfy the current QA gate.

## Snapshot identity

The dynamic files were read at **2026-10-04 07:51:35 UTC**. The `physical_narrowband.py` hash was checked immediately with the P03 block and `_assemble` gate shown below. These are snapshot hashes, not statements about a later working-tree state; no diff-based inference was used.

| File | SHA-256 |
|---|---|
| `synlab/degrade/physical_narrowband.py` | `47D1DC5308AEE795D49F05CB28165BBE4A940DBD27E3E3A59579BB9EB6A976EA` |
| `synlab/degrade/axes.py` | `1255550FE50741C81C2C57CF1EA5B4701496E8B1E933949279E4F54D41CF0E87` |
| `synlab/degrade/narrowband.py` | `31E5E44F198F357991768C2AC1EC08DF4115A5E5E5C9BADCF903F82B1F9C5A8A` |
| `synlab/physical/fields.py` | `EEFAB692A109DDF027C91796D8B8AC771FAB49F99A07B51E11686E88EEAF9FD1` |
| `synlab/physical/sdf.py` | `FD433876FA4DF84D2316C93DBBE521E1094241829D5FCCF93CEDEEAC02467B1D` |
| `synlab/schemas/runtime.py` | `080B6E9C5ABED88873786F5DCE4D654E78072CB71E3E04106CEDA17640352609` |
| `synlab/fracture/fragment.py` | `53A581C5964D7B350A6C938BB188E908ADB06E87E4114CBC5914BF6EE1E079FD` |
| `synlab/degrade/wall_intervals.py` | `02799E54CD1567405B43BFBBDFD1044FED609CCFC5BE6DE88764F3544CE16693` |

## Current P03 data and call chain

1. `synlab/degrade/axes.py:567-590` declares P03's interface ROI, `MIN_WALL_MM = 0.6`, and narrow-band backend. `_PhysicalAxis._apply` resolves a fragment/source mesh and recipe at `axes.py:384-392`, then calls `physical_result`; the P03 narrow-band route is selected at `axes.py:366-379`.
2. `synlab/degrade/physical_narrowband.py:248-305` validates the mesh and reads `min_wall_thickness_mm` from `recipe.qa`; the P03 recipe currently supplies 0.6 mm. `_erode_interface` selects only interface face IDs through `F.roi_faces` at `physical_narrowband.py:308-315` and creates a recession field at `:315-332`.
3. `synlab/physical/fields.py:59-82` uses `face_interface_id` or `face_origin_kind == ORIGIN_INTERFACE` to choose that ROI. Those labels identify which triangles are fracture/interface faces; they do not name a wall surface or a direction across wall material.
4. At `physical_narrowband.py:334-336`, the legacy probe is explicitly diagnostic-only. `synlab/degrade/narrowband.py:368-419` samples source points under the ROI face mask, takes `source.face_normals`, starts at `point + normal * eps`, casts inward, filters to paired hits, and returns aggregate counts/statistics without preserving station IDs/points or per-row UNKNOWN reasons. Its only threshold statistic is a >50% relative drop; it does not enforce the 0.6 mm absolute minimum. Filtering after the 400-point draw explains why requested and paired counts can differ. This data cannot be promoted to trusted wall stations.
5. The final output geometry is `accepted = S.intersect_with_source(body, mesh)` at `physical_narrowband.py:338`; `synlab/physical/sdf.py:604-618` defines that result as `candidate ∩ source`. This is the correct result mesh to compare to the source; do not measure the pre-clip `body` as if it were the delivered subset. The intersection is a usable basis for `ResultSubsetEvidence` when its source/result hashes and operation provenance are recorded.
6. The current P03 `wall_guard` is `UNKNOWN` at `physical_narrowband.py:379-383`. `_assemble` accepts only a missing guard or literal `PASS` at `physical_narrowband.py:106-127`; an `UNKNOWN` guard therefore sets `realized=false`, `physical_acceptance=false`, clears physical truth, and reports `WALL_GUARD_UNKNOWN`. This is the required fail-closed fallback at this snapshot.
7. `axes.py:401-405` copies only `origin_kind` and `interface_id` to an output fragment when their array length happens to equal the representative output face count. This is not a source-to-result face correspondence map. `axes.py:417-425` also currently requires generic result `qa.status == "PASS"` plus boolean `physical_acceptance` before declaring realized, so a future `SAMPLED_PASS` contract needs explicit QA propagation rather than status renaming.

## Fields present and missing

| Data item | Current field/source | What it establishes | Wall-interval use |
|---|---|---|---|
| Source geometry | `fragment.mesh` / source payload mesh | The closed source body P03 erodes | Available as the source all-hit scene |
| P03 affected ROI | `face_interface_id`, `face_origin_kind`, `roi_info` | Which interface faces receive recession | Not a wall-direction or inner/outer label |
| Fragment ancestry | `Fragment.face_source_tri`, `parent_id`, `meta` (`runtime.py:192-207`, `fragment.py:137-195`) | Source triangle IDs for mother-surface provenance; `-1` for non-mother faces | No inner/outer face pair, station correspondence, or local through-wall vector |
| Fracture side | `face_side` (+1/-1/0) | Fragment side of an interface event | Sign of fracture side, not outward material wall direction |
| Interface correspondence | `InterfacePatch.sample_points_a/b`, `normals_a/b` (`runtime.py:214-230`); `CleanTruth.correspondence` (`:294-305`) | Paired fracture faces / supervised point correspondence | Does not state that either normal traverses vessel wall material or identify opposite wall surfaces |
| Result mesh | `accepted` from source intersection | Final clipped P03 geometry, material subset by construction | Available as the result scene; cite intersection and geometry hashes as subset provenance |
| Fixed station IDs/coordinates | None in P03 recipe/result | No stable requested station population | Missing; old probe discards station identities/coordinates |
| Trusted wall direction / wall-surface class | None in P03 ROI/recipe/Fragment schema | No proof of the local wall axis | Missing; cannot use `mesh.face_normals` of historical fracture faces by default |
| Inner/outer or source-material ancestry map | None in `Fragment`, `CleanTruth`, or P03 payload passed here | No paired source-wall material lane at each affected station | Missing; must come from upstream trusted geometry semantics, not an inferred fracture normal |

`Fragment.face_source_tri` refers to an original mother triangle or `-1`; it is not an inner/outer pair. `parent_id`, interface IDs, opposing interface normals, and historical fracture-surface samples likewise cannot be repurposed as wall ancestry. If the needed mother/inner/outer geometry is absent from the current input assets, the mapping is unavailable and the answer remains `UNKNOWN`.

## Minimal gated call if a real map is supplied

The earliest correct insertion point is in `_erode_interface`, immediately after `accepted, clip_info = S.intersect_with_source(body, mesh)` (`physical_narrowband.py:338`) and before constructing `wall_guard` (`:379`). At that point both compared meshes are known. Do not call the helper on `body` before clipping.

Before calling `measure_material_intervals`, require a versioned wall map bound to the exact source geometry hash and units, with a complete requested station list. Each station must identify (a) world-mm point on a semantically classified source wall face, (b) stable station ID and its affected P03 ROI/interface association, (c) outward-from-material wall direction, and (d) mapping provenance. The map must be generated from an actual inner/outer wall correspondence, validated material wall-direction field, or a semantically classified outer-wall face normal. A raw `ORIGIN_INTERFACE` normal is not an allowed fallback.

Then query `measure_material_intervals(mesh, accepted, stations_mm, wall_directions, ...)` with:

- `direction_evidence`: trusted source from the helper's explicit vocabulary (`inner_outer_wall_map`, `material_wall_direction`, or `classified_outer_wall_face_normal`), convention `outward_from_source`, units `mm`, non-empty source provenance;
- `result_evidence`: `relation="material_subset_of_source"`, trusted only because this exact P03 candidate was intersected with `mesh`; include operation, source/result geometry hashes, and `clip_info` provenance;
- `station_ids`: every requested station ID; do not drop unpaired stations or reduce the denominator;
- `min_remaining_wall_mm=guard_mm`, requiring the P03 policy's declared 0.6 mm; preserve `relative_loss_threshold=0.5` and the helper's explicit 0.01 sampled violation budget unless the root freezes a different budget;
- no retry loop, normal inference, or interval-length summation across air cavities or separated material segments.

The helper already reports each selected source interval and unique retained result interval on the same ray, handles all native triangle hits, and returns terminal row reasons. A real split is FAIL with per-segment values and no fictitious single remaining-thickness value; a trusted closed result with no retained interval can be a sampled perforation FAIL. Missing map, stale geometry hash, any UNKNOWN station, grazing/near-surface ambiguity, non-unique result mapping, or incomplete requested denominator remains UNKNOWN and cannot qualify P03 physical success.

## QA/rollback semantics

- Keep the 0.6 mm minimum as an explicit guard input, not just a recipe label or a post-hoc filter. Enforce the sampled 50% loss policy separately from the absolute minimum.
- A missing/invalid wall map produces a structured wall report with `stations_requested` preserved, `stations_measured=0`, per-request UNKNOWN reasons (or an explicit no-map summary), no zero-valued thickness, `sampled_status=UNKNOWN`, `global_wall_status=UNVERIFIED`, and `physical_qualification_status=UNKNOWN`.
- Only an all-requested-stations result can be `SAMPLED_PASS`; any unknown requested station prevents that top-level sampled status. This is a finite station-set decision, never a global minimum-wall result.
- Current `_assemble` only accepts literal `PASS`; passing `SAMPLED_PASS` into it currently fails closed. Do not work around that by converting `SAMPLED_PASS` to `PASS`. If the root later chooses to allow local P03 realization on a trusted all-station sample pass, the QA layer must carry `operator/sample acceptance`, `global_wall_status=UNVERIFIED`, and `physical_qualification_status=UNKNOWN` as distinct fields. Until that contract is reviewed, preserve current rejection on UNKNOWN and do not claim physical success.
- Safe fallback when map extraction or provenance validation fails: do not invoke interval classification with fabricated points/directions; leave wall guard UNKNOWN and let the current fail-closed path reject realization.

No production files were edited. This was a source review only; no Boolean, ray/occupancy query, solver, tests, or Git operation was run.
