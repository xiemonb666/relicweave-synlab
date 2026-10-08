# Isolated wall-interval helper: source freeze and review notes

This phase adds an isolated sampled-interval helper and tiny analytic acceptance sources. It does
not connect the helper to P03, `narrowband.py`, `physical_narrowband.py`, `axes.py`, or `sdf.py`.
`global_wall_status` is permanently `UNVERIFIED`; `physical_qualification_status` is permanently
`UNKNOWN`. Nothing in this package labels sampled chords as global wall quality or physical-data
qualification.

## Source and intended API

- `synlab/degrade/wall_intervals.py`: `measure_material_intervals(source_mesh, result_mesh,
  stations_mm, wall_directions, *, direction_evidence, result_evidence, ...)`.
- `tests/a12/operators/test_wall_intervals_20261004.py`: small analytic fixtures and explicit
  UNKNOWN / FAIL assertions. This test module is source-only until the parent approves the
  focused run.
- `fixtures.json`: the expected geometry, analytic interval ranges, and statuses. These are
  expectations, not executed measurements.

All coordinates and reported distances use mm. The caller must provide a fixed source surface
station and a trusted outward direction with explicit provenance. An interface/fracture normal
does not qualify as a wall direction by itself. The caller must also attest that the result mesh
contains only retained source material; without that evidence, a missing result interval cannot
be called a perforation.

The helper recenters both meshes around the source bounds center before the float32 ray scene is
built. It uses Open3D `RaycastingScene.list_intersections` once per source/result scene for the
requested rays, reads all native triangle hits, groups coincident events by distance, classifies
their direction using oriented face normals, and samples occupancy in the gaps between events.
Redundant same-direction hits at a coplanar triangulation seam become one event. Before occupancy
is trusted, one batched `compute_distance` call checks every initial, inter-event, and tail gap
probe midpoint against the same mesh. Any nonfinite distance, bad response shape, or distance at
or below `2 * merge_tolerance_mm` returns UNKNOWN for the affected ray. This rejects points that
lie on a parallel/coplanar boundary even when `list_intersections` omits that boundary face. The
occupancy response is checked for exact shape and finite values before thresholding; NaN is never
interpreted as outside. A normal-sign conflict, occupancy/event conflict, unresolved gap,
event-cap overflow, or bad mesh also returns UNKNOWN. No nearest-hit stepping loop is used.

Only the unique source material interval whose entry is within station tolerance of the requested
probe offset is selected. At most one result material interval may overlap and remain inside that
source interval. The algorithm never sums through air gaps or across opposite walls. A closed,
non-self-intersecting, trusted result with no interval in that selected source segment is a
sampled perforation FAIL. Multiple retained segments are a sampled split FAIL; their list is
returned, while singular remaining thickness, loss, and relative loss remain null. A unique result
segment below the absolute guard is a sampled FAIL.

## Precision and status semantics

The default merge tolerance is
`max(1e-5 mm, 8 * float32_epsilon * max(source/result bounds diagonal, 1 mm))`. The reported
measurement uncertainty is twice this tolerance. The meshes and rays are recentered before their
float32 query conversion. A probe offset not resolved above `8 * merge_tolerance`, a merge
tolerance too coarse for the guard, a gap at or below `4 * merge_tolerance`, or a wall/relative
guard value within its uncertainty is UNKNOWN. The event cap is 256 per ray; hitting it is UNKNOWN.
These conservative bounds do not promise detection below Open3D float32 resolution.

Both meshes must have finite nondegenerate triangles, be watertight, have consistent winding and
positive volume, and pass Open3D legacy `TriangleMesh.is_self_intersecting() == False`. The helper
does not repair or orient input geometry. If the self-intersection API is missing or errors, the
result is UNKNOWN because occupancy's watertight/nonintersecting assumptions are not established.

`stations_classified` and `coverage_fraction` are recomputed from terminal row states. UNKNOWN
rows are not coverage. `stations_measured` / `measurement_coverage_fraction` count only a unique
numeric source/result interval pair; a threshold-uncertain row can be measured but not classified.
Split rows are classified FAIL but are not measured as a single wall thickness. Relative-loss
count/fraction are null when any requested station has no numeric relative-loss classification;
when every requested sample is numerically classified and there are zero relative violations,
the fraction is `0.0`. There is no implicit 95% threshold: this phase requires every requested
station to be classifiable for `SAMPLED_PASS`. Known FAIL takes precedence over UNKNOWN in the
top-level sampled status, while counts and per-station reasons preserve both.

## Static Open3D API evidence

The inspection used the repository's `.venv` Python with one `-c` invocation and no mesh, scene,
ray, operator, solver, or test execution. It exited 0.

```text
open3d_version= 0.19.0
sys.argv= ['-c']
legacy_class= <class 'open3d.cpu.pybind.geometry.TriangleMesh'>
has_is_self_intersecting= True
docstring= is_self_intersecting(self: open3d.cpu.pybind.geometry.TriangleMesh) -> bool
Tests if the triangle mesh is self-intersecting.
Returns: bool
```

The earlier permitted static `RaycastingScene` symbol/docstring inspection in this environment
found `list_intersections`, `compute_occupancy`, and `compute_signed_distance` in Open3D 0.19.0.
`list_intersections` exposes `ray_splits`, `ray_ids`, `t_hit`, `geometry_ids`, `primitive_ids`,
and `primitive_uvs`. The occupancy / signed-distance docs state their assumptions about
watertight, nonintersecting meshes; this implementation therefore preflights self-intersection
instead of silently assuming it away. A follow-up static method inspection found:

```text
open3d_version= 0.19.0
sys.argv= ['-c']
raycasting_scene_class= <class 'open3d.cpu.pybind.t.geometry.RaycastingScene'>
has_compute_distance= True
compute_distance(self, query_points: Float32 Tensor, nthreads=0) -> Float32 Tensor
Computes the distance to the surface of the scene.
```

This invocation exited 0 and did not instantiate a scene.

For each valid nonempty source/result mesh, the planned bounded native calls are one legacy
`is_self_intersecting`, one `list_intersections`, and at most one batched `compute_distance` plus
one batched `compute_occupancy` for all gap probes. Occupancy includes only rays whose every gap
probe passed the distance check. Both distance and occupancy calls are skipped when the scene has
no hit events to disambiguate; occupancy is also skipped when every gap probe was rejected. There
are no per-hit retries or nearest-cast loops. The result report records this per-mesh call plan.

## Deferred verification and PNG plan

Only Python source compilation is authorized before review. No scene is instantiated, no
ray/occupancy query is run, no Boolean fixture is built, and no pytest is run in this freeze.
After the parent reviews the exact source and fixture hashes and approves one focused run, run
only `tests/a12/operators/test_wall_intervals_20261004.py`. The one perforation test makes one
small explicit Manifold Boolean at runtime; all other fixtures use composed box meshes.

The requested PNG must be generated after that run from actual returned native interval reports
and their corresponding real source/result mesh vertices and fixed stations. The image may overlay
the analytic oracle (`1.0 mm` source, `0.8 mm` eroded result) with a separate label, but must show
the actual returned endpoints and must not depict an analytic-only diagram as a successful query.
The report and image should be kept under this owned implementation directory. No PNG is claimed
or included in this pre-query freeze.
