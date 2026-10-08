# Explicit crack visibility: source review plan

Status: source was reviewed and approved; one separately approved focused test run is complete with 17 passed, return code 0. Solver and renderer have not been run.

## Scope

Add an isolated, source-only 3D segment-versus-explicit-triangle visibility primitive under `pgfrag/experiments/explicit_visibility_20261005/`. Inputs are source points, query points, and the explicit triangular crack facets in SI meters. The result classifies each source-to-query segment as `VISIBLE`, `BLOCKED`, or `UNKNOWN`. Only `VISIBLE` permits local support; both `BLOCKED` and `UNKNOWN` are excluded, with `UNKNOWN` retained as a distinct reason-bearing outcome. No crack identity, tetrahedral adjacency, side selection, or segment direction is used. This is geometry only: it does not implement nucleation, growth, a fracture law, solver coupling, or ceramic physics.

## Frozen numerical contract

- Exact `numpy.ndarray` inputs; reject subclasses and array-like conversion hooks.
- Preflight shapes, row/pair caps, dtype, byte counts, and C-contiguity before scans, conversion, copies, or result allocation. This excludes non-contiguous/strided views from the public contract.
- Maximum 500 sources, 500 queries, 256 triangles, and 1,000,000 source-query-triangle classification pairs. Reject excess as `budgetRejected` before copying/converting.
- Default length tolerance: `1e-12 m + 1e-10 * L`, where `L` is the max of segment length and triangle maximum edge length; also floor it at `32 * machine_epsilon * coordinate_scale` to account for subtraction precision. All geometric boundary decisions use this length tolerance or its dimensionless segment parameter equivalent. Coordinate magnitudes above `1e150 m` are rejected to keep float64 products in range.
- Degenerate triangles, coplanar/near-coplanar finite-triangle proximity, endpoint contact/near-contact with the finite triangle, and edge grazing/near-grazing produce `UNKNOWN`. A point in the infinite triangle plane but far outside the finite triangle does not by itself produce `UNKNOWN`. A strict segment crossing of a triangle's relative interior produces `BLOCKED`; outside misses produce `VISIBLE` for that triangle.
- Aggregate a segment as `BLOCKED` if any strict interior hit is established; otherwise `UNKNOWN` if any facet is ambiguous; otherwise `VISIBLE`. This permits a proven blocker to reject support even if a different facet is ambiguous.
- Return immutable per-pair status and boolean masks where `visible` is true only for `VISIBLE`; expose local spatial stability as `NOT_ESTABLISHED` (a fixed pattern is not derivative or stability evidence).

## Derivation

For each nondegenerate triangle, form its unit normal from translated edge vectors and compute signed endpoint distances to its plane. Same-side segments cannot cross. Opposite-side segments define `t = d0 / (d0 - d1)` and an intersection point. Near-zero plane distances, near-parallel/coplanar cases, intersections within the length tolerance of either segment endpoint, and intersections within the length tolerance of any triangle edge are `UNKNOWN`. A hit with all three oriented edge distances strictly greater than tolerance is an interior crossing (`BLOCKED`); a hit strictly outside at least one edge is clear for that facet. Degenerate geometry is never repaired or silently ignored. The calculations use Euclidean lengths and dot/cross products only, giving rotation-covariant classifications away from the explicit UNKNOWN tolerance band.

## Test source inventory (not run)

The focused test source covers: (1) segment crossing a triangle interior is blocked; (2) segment missing the facet or crossing its plane outside the triangle is visible; (3) proper rigid rotations/translations preserve decisive classifications; (4) no crack identity or tetrahedral adjacency is accepted or consulted; (5) exact endpoint contact, edge contact, coplanarity, and degenerate facets return unknown; (6) input/output immutability; (7) fake array hooks and non-contiguous/oversized inputs fail before conversion/copy; (8) work-pair cap is enforced before private input copies; (9) a definite blocker dominates a different ambiguous facet; (10) no facets gives an all-visible identity map; and (11) a generic proper 90-degree rotation, reversed winding, and a `1e-3 m` fixture preserve decisive classifications. One focused pytest run passed all 17 cases (rc 0); solver and render were not run.

## Freeze and review sequence

The source freeze is limited to the two owned directories. Exact SHA-256 pins for source, test, and README match before and immediately after the one test run. Run receipt, JUnit, stdout, stderr, and pins are in `tmp/review_20261005/explicit_visibility_20261005/focused_test/run_20261005_01/`. Solver and render remain unrun.
