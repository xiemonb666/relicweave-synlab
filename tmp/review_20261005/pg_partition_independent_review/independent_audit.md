# Independent PG-Frag endpoint partition audit

This report analyzes only the copied toy endpoint fixture. It independently rebuilds the graph with union-find over all active canonical bonds, initializes every point (so isolates remain singleton components), and compares partitions as sets of point IDs. Label numbers are allowed to differ.

## Finding

Independent reconstruction found **2 intact-bond graph components** from 576 points and 15544 active edges. `components.csv` partition match: **True**; `points.csv` partition match: **True**; both declared partitions agree with each other allowing label renumbering: **True**.

The graph contains 20780 canonical pairs total: 15544 active and 5236 inactive. `broken_bonds.csv` independently matches the inactive pair set and lengths: **True**. Recomputed active degrees match all point declarations: **True**. Zero-degree points: 0; isolated roster check: **True**.

Point mass sums to 0.00057600000000000012 kg (components table 0.00057600000000000012 kg; delta 0 kg), and point volume sums to 5.7600000000000008e-07 m³. Point mass equals job density × volume at every point: **True**.

The copied job hash matches the result declaration: **True**. All copied table/dictionary bytes match `result.json` output manifest: **True**. Full byte counts and SHA-256 digests for all eight inputs are in `independent_audit.json`.

## Independently reconstructed components

Component rows below are graph partitions ordered by minimum point ID; bounds are in the dictionary's right-handed z-up frame. These are endpoint graph components, not physical fragments.

| Graph component | Points | Point IDs | Mass (kg) | Reference bbox (mm) | Current bbox (mm) | Declared point labels | Declared component labels |
|---:|---:|---|---:|---|---|---|---|
| 1 | 432 | 1–432 | 0.000432 | x -2.5…2.5; y -2.5…2.5; z -7.5…3.5 | x -2.52238…2.52238; y -2.52238…2.52238; z -8.06024…3.67216 | [1] | [1] |
| 2 | 144 | 433–576 | 0.000144 | x -2.5…2.5; y -2.5…2.5; z 4.5…7.5 | x -2.50695…2.50695; y -2.50695…2.50695; z 5.01121…8.06024 | [2] | [2] |

## Coordinate extents and independent checks

Coordinates are reported in meters in the JSON; table values above use millimeters only for readability. Point columns state `x/y/z_ref_m` and `x/y/z_current_m` in `right_handed_z_up` frame.

Active degree histogram: `{"12":4,"20":4,"24":16,"25":4,"26":16,"28":4,"29":12,"30":4,"31":16,"32":8,"33":8,"34":16,"35":8,"36":8,"37":16,"40":16,"42":4,"43":32,"44":16,"46":24,"47":24,"48":8,"50":8,"51":4,"54":12,"55":8,"56":32,"57":20,"58":24,"59":4,"60":12,"61":4,"62":16,"63":12,"66":8,"69":4,"70":16,"71":8,"73":12,"76":8,"77":24,"78":12,"82":8,"84":8,"88":8,"91":4,"94":12,"95":4,"96":4,"98":4,"106":4,"107":4}`; inactive incident-pair histogram: `{"1":16,"2":8,"3":8,"4":36,"5":24,"6":24,"7":16,"8":28,"9":4,"10":32,"11":28,"12":16,"13":16,"14":40,"15":16,"16":24,"17":16,"18":4,"19":12,"20":12,"21":4,"22":20,"23":8,"24":8,"25":16,"26":16,"27":16,"29":4,"30":8,"31":8,"34":12,"35":12,"37":16,"41":8,"42":4,"43":8,"50":8,"51":8,"62":8,"74":4}`.

The independent inactive-incidence fraction equals the emitted damage at every point: **True**. The dictionary describes damage as upstream material-model point damage; this is an observed consistency check, not a claim that the dictionary specifies this exact formula.

The dictionary's actual selected fields and units are: `points.csv` uses point IDs/component IDs and bond counts as unit `1`, reference/current xyz in `m`, xyz velocity in `m/s`, damage in `1`, strain-energy density in `J/m³`, volume in `m³`, and mass in `kg`; its coordinate and velocity frame is `right_handed_z_up`. `components.csv` has `component_id` in `1`, point mass in `kg`, damage in `1`. `bond_states.csv` and `broken_bonds.csv` use endpoint IDs in `1` and reference/current lengths in `m`; the active flag is boolean in `1`. `isolated_points.csv` uses point ID in `1`, reference xyz in `m`, and mass in `kg`.

Checks failing: none. Output manifest mismatches: none.

## Reader gap and scope

The current production reader [`pgfrag_result.py`](../../../synlab/qa/source_readers/pgfrag_result.py#L573) validates source-file hashes, typed rows, degree declarations, inactive/broken-pair equality, and isolated-point membership, but it does not recompute graph connectivity or validate the intact graph component count. Its report initializes `source_binding.component_partition_validation.status` to `UNKNOWN` because connectivity is not recomputed (lines 573–575), and that field remains UNKNOWN after successful source parsing. It also requires literal per-row equality between the integer labels in `components.csv` and `points.csv` ([line 431](../../../synlab/qa/source_readers/pgfrag_result.py#L431)); this fixture happens to use the same labels, while this independent audit compares partition membership and would allow renumbering. The union-find comparison fills that bounded source-correctness check for this copied fixture only.

The producer's `result.json` says validation PASS for bounded endpoint serialization, while separately labeling physical calibration pending and contact/surface/event history outside scope. This audit does not upgrade endpoint graph components into fragments, nor establish crack geometry, R2 lineage, energy completeness, calibrated physics, or forge-ready assets.

## Input byte binding

See `independent_audit.json` → `source_files` for all eight input byte counts and SHA-256 digests, and `result_manifest_checks` for independent output-manifest comparisons.
