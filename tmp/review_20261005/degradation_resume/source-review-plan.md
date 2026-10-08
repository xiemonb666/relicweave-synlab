# A12 restricted height-graph certificate candidate — source review

**State: isolated source candidate only; the focused contract tests passed once, and there is no production connection.** The module can return PASS if called, but its successful fixtures do not qualify actual geometry; root review is still required before deciding on any frozen-array probe or production integration. Frozen P02/P03 qualification remains **UNKNOWN**. P03 wall guard, physical QA, observation capture, and labels remain blocked/UNKNOWN; `measurement.valid` is not physical QA.

## Owned files

- `synlab/degrade/heightgraph_certificate.py` — read-only diagnostic implementation. It does not import or call the narrowband, SDF, API, axes, G01, or geometry-operator paths.
- `tests/a12/degrade/test_heightgraph_certificate_20261005.py` — the original ten cases remain, with a source-invalid ordering case and bounded-input case appended; all twelve are authored and passed in the one root-authorized focused run below.
- `tmp/review_20261005/degradation_resume/source-review-plan.md` — this review and acceptance plan.
- `tmp/review_20261005/degradation_resume/source-freeze.sha256` — retained first-review source freeze.
- `tmp/review_20261005/degradation_resume/source-freeze-review2.sha256` — current source/test freeze; local snapshot identity only.
- `tmp/review_20261005/degradation_resume/source-review2.diff` — unified diff from exact first-review baseline copies listed below.
- `tmp/review_20261005/degradation_resume/heightgraph_certificate.pre_review2.py` and `test_heightgraph_certificate_20261005.pre_review2.py` — source/test copies whose hashes match the first-review freeze and form the diff baseline.

No existing production source or failure data was edited. There is no Boolean bypass, vertex snap, hole repair, or tolerance increase. No Git or CAD command was run. The only pytest command was the single authorized focused run recorded below.

## Proposed proof boundary

`certify_heightgraph_subset` at [heightgraph_certificate.py:180](../../../synlab/degrade/heightgraph_certificate.py#L180) first establishes all source premises—upper/lower rectangular coverage, strict positive source thickness, complete source side curtains, and closed source topology. Only after those pass does it load and judge candidate geometry or candidate quality, so an invalid source cannot be reported as a candidate `FAIL`. It accepts typed axis, rectangle, face-role partitions, candidate quality limits, a shared coordinate contract, and a pair budget capped at 250,000. It supports one convex rectangular projection domain and coordinate-axis permutations/sign reversals. Other domains, malformed partitions, unsupported inputs, and exhausted work return `UNKNOWN`.

Mesh input arrays must be real NumPy `ndarray`s; array-like duck types are rejected before `.tolist()`. An ndarray subclass is converted to a base ndarray view before reading actual shape, dtype, and logical byte count. Before list conversion or Fraction creation, `_load_mesh` checks rank-2 `N×3` shapes, float64 vertex dtype, integer face dtype, exact logical `nbytes`, at most 5,000 vertices, and at most 10,000 faces. It also verifies converted row counts ([loader and array gates](../../../synlab/degrade/heightgraph_certificate.py#L445)); rejected inputs return `UNKNOWN`. External domain/quality ints, Fractions, and finite floats are checked against a 2,048-bit numerator/denominator cap. Face-role tuples are capped by the mesh face count before set/flatten work. The pair counter cannot be raised above 250,000. These are input-size and bounding-box candidate-pair limits only; there is no formal bound on intermediate Fraction bit growth or whole-call runtime. The exact mesh digest remains a normalized geometry-array semantic hash, not NPZ/source-file byte identity or physical provenance authentication ([encoding](../../../synlab/degrade/heightgraph_certificate.py#L44), [digest](../../../synlab/degrade/heightgraph_certificate.py#L594)).

The typed partition declares `coordinate_unit="mm"` and a non-empty `frame_id`; both mesh metadata objects must carry matching values. That verifies only the caller's coordinate contract and is not trusted-source verification ([partition fields](../../../synlab/degrade/heightgraph_certificate.py#L102), [coordinate contract](../../../synlab/degrade/heightgraph_certificate.py#L364), [mesh metadata checks](../../../synlab/degrade/heightgraph_certificate.py#L554)).

The overlay and triangle-contact decisions use exact `Fraction` orientation, clipping, area, and height predicates ([patch validation](../../../synlab/degrade/heightgraph_certificate.py#L646), [height overlay](../../../synlab/degrade/heightgraph_certificate.py#L815), [exact intersection](../../../synlab/degrade/heightgraph_certificate.py#L1289)); Shapely/Open3D are not used as proof.

The upper and lower face sets must each exactly tile the declared rectangle. Same-patch pair checks do not skip faces sharing only a vertex, and require any zero-area contact to match shared mesh topology ([lines 683–809](../../../synlab/degrade/heightgraph_certificate.py#L683)). Source/candidate overlays check all exact intersection polygon vertices, including vertices created where unlike triangulation edges cross. The conditions are `b_candidate == b_source`, `b_source < s_source`, `b_candidate < c_candidate`, and `c_candidate <= s_source` across the domain ([lines 822–861](../../../synlab/degrade/heightgraph_certificate.py#L822)). A proved candidate violation returns `FAIL` only after the independent source proof has completed.

Boundary traces are compared over the union of source/candidate breakpoints. Every side face must lie on exactly one declared rectangle side; its complete triangular area must be contained in and exactly cover the corresponding vertical curtain, with same-side overlap/T-junction checks ([side curtain checks](../../../synlab/degrade/heightgraph_certificate.py#L926)). Closed two-manifold edge incidence, vertex links, consistent winding, positive signed volume, role adjacency, and rectangle-rim pairing are checked separately ([closed-mesh checks](../../../synlab/degrade/heightgraph_certificate.py#L1069)). Candidate triangle `q`, minimum altitude, and aspect thresholds use exact squared rational comparisons ([quality checks](../../../synlab/degrade/heightgraph_certificate.py#L1193)).

The claimed implication is restricted to the representation checked here: two closed, oriented, rectangular height-graph solids with equal lower graph and rim traces, positive thickness, and exact side curtains. Within that representation, checking each affine height difference on every vertex of each convex overlay cell is a whole-cell test because extrema of an affine function over a convex polygon occur at its vertices. It does not establish minimum Euclidean wall thickness, process-physics validity, label validity, or general 3D mesh containment.

## Source review findings still requiring acceptance

- The module is intentionally not imported by `synlab/degrade/__init__.py` and no operator calls it. Preserve that separation through this review.
- Source geometry validity problems return `UNKNOWN`; proven candidate overlap, height violation, nonpositive thickness, topology failure, or candidate-quality failure can return `FAIL`.
- A failed structural precondition such as a nonrectangular domain is not converted into a guessed polygon proof. The U-hole case returns `UNKNOWN` at rectangular-domain coverage.
- Candidate quality is exact only relative to the supplied thresholds. The new inward-wear test uses contract-fixture thresholds and does not promote actual geometry quality; the module does not infer product thresholds from the old `q=0.00161`, `min-height=3.14e-5 mm`, or aspect `1074` observations.
- No frozen P03/P02 array probe is performed. `Mesh64` status, seven degenerate faces, the 21-edge/seven-loop post-clean failure, and the unrelated six-edge fixture remain as documented in `report.md`; this source candidate does not repair those failures.
- This is an engineering candidate, **not an established novelty claim**. Its 2D exact overlay method and strict domain restriction need independent review before any result is used as evidence.

## Focused acceptance tests — executed once

The test file contains twelve cases; the original ten remain in place:

1. Zero displacement and coplanar material with different upper and lower triangulations returns `PASS`.
2. A nonzero inward center-vertex displacement with unchanged rim and bottom is a geometry-only `PASS` fixture.
3. Axis permutation and projection sign changes pass under the correctly transformed typed rectangle.
4. Two upper faces with only one shared vertex but positive-area overlap return `FAIL` with face witness and both hashes.
5. A coarser candidate that fills an interior source depression returns `FAIL` at rational `(1/2,1/2)`.
6. An invalid source with upper center `-3` over bottom `-2` returns `UNKNOWN` before candidate comparison; candidate hash remains unset.
7. Opposite source/candidate diagonals create a new exact overlay crossing where all four original corner values agree but candidate height exceeds source height; expect `FAIL` at `(1/2,1/2)`.
8. A U-shaped projection domain whose candidate triangle has all vertices in material but spans the hole returns `UNKNOWN` under the rectangular-only contract.
9. Unsupported mesh type and zero pair-check budget each return `UNKNOWN` with explicit reason codes.
10. Source/candidate `coordinate_unit` or `frame_id` metadata mismatch returns `UNKNOWN`.
11. Oversized NumPy arrays (including an ndarray subclass that lies about its metadata), wrong shapes, and duck-typed array-likes return `UNKNOWN` before list conversion.
12. A caller budget above 250,000, oversized integer/Fraction domain or quality inputs, and oversized face-role tuples return `UNKNOWN`.

The focused verification command executed once was:

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab
.\.venv\Scripts\python.exe -m pytest -q tests\a12\degrade\test_heightgraph_certificate_20261005.py --junitxml=tmp\review_20261005\degradation_resume\focused_pytest_review2.junit.xml
```

The one root-authorized command covered all twelve isolated contract cases with a 60-second cap. It completed in 1.613 seconds with exit code 0; JUnit records 12 passed, 0 failed, 0 errors, and 0 skipped. Flat stdout, stderr, return-code, and JUnit receipts are saved in the review directory. The module, test, and review2 freeze hashes matched before and after execution. No full suite, CAD/backend run, frozen P02/P03 probe, production registration, wall-guard promotion, or label promotion was part of this verification step.

## Decision requested from root

The independent static review found that invalid source thickness could be reported as candidate FAIL before source qualification and that duck-typed arrays could lie about shape. The revised source fronts the complete source proof, restricts arrays to genuine NumPy ndarrays/base views, caps caller budgets and external rational bits, and rejects oversized role tuples before flattening. Root reviewed the restricted proof surface and authorized one focused twelve-test run; that run passed with exit code 0. The next decision is whether any read-only frozen-array probe is appropriate. Production wiring remains a separate decision. Keep the P03 wall guard, physical QA, observation labels, and measurement.valid interpretation at their current UNKNOWN/blocked states. The resource controls are not a formal whole-call runtime or intermediate-rational-growth proof.

## Source freeze

The first-review source freeze is retained in [source-freeze.sha256](source-freeze.sha256); the exact baseline copies are named above. The current source freeze is recorded in [source-freeze-review2.sha256](source-freeze-review2.sha256), and the changes from that exact baseline are in [source-review2.diff](source-review2.diff).

The second-review candidate module and authored test file are frozen at these SHA-256 values:

| File | SHA-256 |
|---|---|
| `synlab/degrade/heightgraph_certificate.py` | `c1a3468cae00b944bcb86c4186b04c5c7cd8e42af586bd27e9603bc6284523ec` |
| `tests/a12/degrade/test_heightgraph_certificate_20261005.py` | `ba9929534d71bb6d59489db6c69946282007112c956919829c6655df80487377` |
| `source-review2.diff` | `711d7e79e571116c685ea9ba7612316505dde16e843d258a11f8128e12cd43e4` |

The matching entries, including exact baseline copies, are in [source-freeze-review2.sha256](source-freeze-review2.sha256); the manifest SHA-256 is `ce7590ca661636322d0689126c13c4084ec63ec7f6d00d90f828eb184c3e6b43`. Hashes identify this local source snapshot only; they do not authenticate provenance. The one focused contract run passed; production and P03 probes remain separate decisions.



