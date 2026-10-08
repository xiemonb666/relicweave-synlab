"""Antique wear / aging as a *spatially structured, physically driven* degradation model.

Why not global noise
--------------------
A pot does not age uniformly.  Every documented wear mechanism of archaeological ceramics acts on
a **specific region** and is driven by a **specific physical quantity**:

=========================  ==========================  ==========================================
mechanism (考古实际)         region                      physical driver
=========================  ==========================  ==========================================
口沿磨损 rim wear            the thin lip band at the    contact band area, handling intensity,
                            opening                     wall thickness of the lip, material
                                                        hardness
底部磨蚀 base abrasion       the footprint on the        contact pressure (mass / contact area),
                            placement plane (incl.      hardness ratio body:surface, porosity
                            the foot ring)              (abrasive embedment), glaze presence
釉面损失 glaze loss          convex / high spots and     wall thickness vs layer thickness
                            exposed ridges              (substrate support), local curvature,
                                                        porosity, layer:substrate toughness ratio
土沁/积垢/铁锈斑/盐析/根痕     crevices, undersides,       image domain only, separated from the
                            crack traces                geometry: a colour/level offset that is
                                                        measured on the delivered frame
风化与二次破损 崩口/微裂纹/   convex edges, near-edge     edge toughness, porosity, build-up depth
边缘钝化                     surface
=========================  ==========================  ==========================================

The model returns both a **material loss field** (mm, geometry) and a **soil/patina field**
(image domain, level per channel), and it never mixes the two: the geometry hash of a
soil-only change is unchanged, and the soil field is carried as its own channel (P06 already
takes this position for dirt: "appearance only" vs an explicit contamination body).

Physical drivers, measured on the real body
-------------------------------------------
* ``t_wall`` — local wall thickness, measured per vertex with a ray cast from just inside the
  surface to the opposite side (:func:`local_thickness`).  No nominal thickness is assumed.
* ``kappa`` — local mean curvature in 1/mm, from the area-weighted vertex normal divergence.
  Convex (``kappa > 0``) is where a glaze shell is unsupported and spalls.
* ``t_layer`` — the glaze / coating thickness.  It is **coupled** to the measured wall:
  ``t_layer = clip(fraction * t_wall, 0.469, 1.173) mm`` where the interval is the project's
  measured L01/L03 geometric-layer thickness range and ``fraction`` comes from the material
  trait table (flagged candidate — see :mod:`synlab.degrade.specs`).
* ``porosity`` / ``hardness`` / ``toughness`` — material traits from the catalogue, each with its
  provenance; used as *relative* resistances, never as measured values.

Legality (the A09 contract, unchanged)
--------------------------------------
The result is produced exactly like the shipped narrow-band P axes: per-vertex offset along the
area-weighted vertex normal with **compact support** (the band boundary is pinned to zero), so

* the body stays closed and positive-volume;
* ``damaged ⊆ clean`` holds in exact float64 signed distance (the shipped 1e-3 mm tolerance is
  *not* relaxed — it is re-measured here with :func:`synlab.physical.api.subset_outside_stats`);
* the depth is clamped by the measured wall thickness (``cap = margin * t_wall``) with a **factorial
  safety margin**, not an additive fudge, so a thin shell can never be punched through.

Only level 0 is the identity, and it is enforced by the framework, not here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping, Sequence

import numpy as np
import trimesh

from ..errors import ErrorCode, SynLabError
from ..seeds import make_rng
from . import narrowband as NB
from .specs import (
    GLAZE_THICKNESS_RANGE_MM,
    SpecValue,
    material_wear_traits,
)

__all__ = [
    "WearMechanism", "WearLevels", "WearModel", "WearField", "WearResult",
    "local_thickness", "vertex_mean_curvature", "geodesic_distance_mm", "band_weight",
    "SOIL_TYPES", "WEAR_LEVELS",
]

#: Material-loss mechanisms.  ``rim``/``base``/``glaze``/``chip``/``crack`` move material;
#: ``soil`` does not (it is the image-domain layer and is reported separately).
WearMechanism = str


class WearLevels:
    """The five-level ladder shared by every mechanism (index 0 is the identity).

    ``intensity`` is the *fraction of the mechanism's physically derived maximum* that is
    applied.  It is deliberately not a millimetre: a 0.4 mm rim loss on a 2 mm porcelain lip and
    on a 9 mm coarse-ware rim are both "heavy use", and the millimetre value is what the model
    **measures** afterwards, not what the caller declares.
    """

    INTENSITY: ClassVar[tuple[float, ...]] = (0.0, 0.25, 0.50, 0.75, 1.0)


#: The soil / patina layer types documented for archaeological ceramics, all image-domain.
SOIL_TYPES: tuple[str, ...] = ("soil_stain", "dirt_crust", "iron_rust", "salt_efflorescence",
                               "root_trace")

#: Per-mechanism level ladder, kept as a plain table so a recipe can reproduce it verbatim.
WEAR_LEVELS: dict[str, tuple[float, ...]] = {
    "rim_wear": WearLevels.INTENSITY,
    "base_abrasion": WearLevels.INTENSITY,
    "glaze_loss": WearLevels.INTENSITY,
    "edge_chip": WearLevels.INTENSITY,
    "microcrack": WearLevels.INTENSITY,
    "soil_layer": WearLevels.INTENSITY,
}


# ======================================================================================
# geometric drivers
# ======================================================================================
def _area_weighted_vertex_normals(mesh: Any) -> np.ndarray:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    out = np.zeros((len(mesh.vertices), 3), dtype=np.float64)
    for corner in range(3):
        np.add.at(out, faces[:, corner], normals * areas[:, None])
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1.0
    return out / norms


def local_thickness(mesh: Any, *, eps_mm: float = 1e-3) -> dict[str, Any]:
    """Wall thickness **per vertex**, measured by a ray cast inward from just under the surface.

    The ray starts at ``vertex - n*eps`` (already inside the material) and travels along the
    *inward* normal, so the hit distance is the distance to the opposite surface of the shell
    rather than to the neighbouring roughness.  That is the same instrument
    :func:`synlab.degrade.narrowband.paired_thickness` uses, applied per vertex.

    Returns ``{"values_mm", "method", "hits", "missing", "min_mm", "median_mm", "max_mm"}``.
    A vertex whose ray finds no second surface (open geometry, degenerate normal) gets ``NaN``
    and is counted in ``missing`` — it is never silently replaced by a nominal thickness.

    The ray cast goes through :func:`synlab.physical.sdf.scene_for` (the same Open3D
    ``RaycastingScene`` the frozen SDF pipeline uses), so this measures the *frozen* geometry and
    not a second, independently built acceleration structure.
    """
    from ..physical import sdf as S

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    normals = _area_weighted_vertex_normals(mesh)
    origins = vertices - normals * float(eps_mm)
    scene = S.scene_for(mesh)
    hit = np.asarray(scene.cast(origins, -normals), dtype=np.float64)
    values = np.where(np.isfinite(hit) & (hit > 0.0), hit + float(eps_mm), np.nan)
    finite = np.isfinite(values)
    return {
        "values_mm": values,
        "method": "per-vertex inward ray cast from vertex - n*eps (eps = %.1e mm)" % eps_mm,
        "hits": int(finite.sum()), "missing": int((~finite).sum()),
        "min_mm": float(values[finite].min()) if finite.any() else 0.0,
        "median_mm": float(np.median(values[finite])) if finite.any() else 0.0,
        "p05_mm": float(np.percentile(values[finite], 5)) if finite.any() else 0.0,
        "max_mm": float(values[finite].max()) if finite.any() else 0.0,
    }


def vertex_mean_curvature(mesh: Any, thickness_mm: np.ndarray | None = None) -> np.ndarray:
    """Signed mean curvature per vertex in 1/mm (positive = convex/outward).

    Uses the standard discrete estimator ``2 H n = -(1/A) sum_i (cot a + cot b)(v - v_i)`` on the
    one-ring, with the *angle-weighted* (cotangent) weights; the sign is taken so that a convex
    bump has ``H > 0``.  ``thickness_mm`` lets the caller cap the estimate on very thin shells
    where the one-ring spans both sides of the wall (there the discrete operator is meaningless).
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    normals = _area_weighted_vertex_normals(mesh)
    accum = np.zeros(len(vertices), dtype=np.float64)
    weight = np.zeros(len(vertices), dtype=np.float64)
    edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    if len(edges):
        # cotangent weight of an edge = sum of cot(opposite angle) over its two adjacent faces
        pairs = np.asarray(mesh.face_adjacency_edges, dtype=np.int64)
        adj = np.asarray(mesh.face_adjacency, dtype=np.int64)
        if len(pairs):
            for k in range(len(pairs)):
                i, j = int(pairs[k][0]), int(pairs[k][1])
                total = 0.0
                for f in (int(adj[k][0]), int(adj[k][1])):
                    tri = faces[f]
                    other = int(tri[0] + tri[1] + tri[2] - i - j)
                    a = vertices[i] - vertices[other]
                    b = vertices[j] - vertices[other]
                    cross = float(np.linalg.norm(np.cross(a, b)))
                    if cross < 1e-12:
                        continue
                    total += float(a @ b) / cross
                edge_vec = vertices[j] - vertices[i]
                length = float(np.linalg.norm(edge_vec))
                if length < 1e-12 or abs(total) < 1e-12:
                    continue
                # 2 H n = (1/(2 A_mixed)) sum (cot a + cot b)(v_i - v_j); A_mixed ~ length^2/6
                factor = total / max(length * length / 3.0, 1e-12)
                accum[i] += factor * float(edge_vec @ normals[i])
                accum[j] += factor * float((-edge_vec) @ normals[j])
                weight[i] += abs(factor)
                weight[j] += abs(factor)
    out = np.zeros(len(vertices), dtype=np.float64)
    present = weight > 0
    out[present] = 0.5 * accum[present] / weight[present]
    if thickness_mm is not None:
        # a one-ring wider than the wall measures the opposite side, not the curvature here
        reach = np.asarray(thickness_mm, dtype=np.float64)
        cap = np.where(np.isfinite(reach) & (reach > 0), 1.0 / np.maximum(reach, 1e-6), np.inf)
        out = np.clip(out, -cap, cap)
    out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
    return out


def geodesic_distance_mm(mesh: Any, seeds: np.ndarray, *, cutoff_mm: float | None = None
                         ) -> np.ndarray:
    """Dijkstra distance (mm) along mesh edges from the seed vertices.

    Euclidean distance is wrong on a curved body: two points on opposite sides of a bowl can be
    2 mm apart in space and 60 mm apart along the surface.  A wear band is a *surface* band, so
    the band fields below use this distance, and the narrow-band support of the result is
    compact in the same metric.
    """
    import heapq

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    values = np.linalg.norm(vertices[edges[:, 1]] - vertices[edges[:, 0]], axis=1)
    n = len(vertices)
    adjacency: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for k in range(len(edges)):
        i, j = int(edges[k][0]), int(edges[k][1])
        w = float(values[k])
        adjacency[i].append((j, w))
        adjacency[j].append((i, w))
    limit = float(cutoff_mm) if cutoff_mm is not None else float("inf")
    dist = np.full(n, np.inf, dtype=np.float64)
    heap: list[tuple[float, int]] = []
    for seed in np.asarray(seeds, dtype=np.int64).reshape(-1):
        if 0 <= int(seed) < n:
            dist[int(seed)] = 0.0
            heap.append((0.0, int(seed)))
    heapq.heapify(heap)
    while heap:
        d, node = heapq.heappop(heap)
        if d > dist[node]:
            continue
        for neighbour, w in adjacency[node]:
            nd = d + w
            if nd < dist[neighbour] and nd <= limit:
                dist[neighbour] = nd
                heapq.heappush(heap, (nd, neighbour))
    return dist


def band_weight(distance_mm: np.ndarray, width_mm: float, *, falloff: str = "smoothstep"
                ) -> np.ndarray:
    """1 inside the band, 0 beyond ``width_mm``, with a finite-slope shoulder.

    ``smoothstep`` (default) has zero derivative at both ends, which is what keeps the offset
    field compact and the body closed.  ``linear`` is kept for the abrasive-contact profile,
    whose real cross-section is closer to a wedge.
    """
    d = np.asarray(distance_mm, dtype=np.float64)
    width = max(float(width_mm), 1e-9)
    ratio = np.clip(d / width, 0.0, 1.0)
    if falloff == "linear":
        return 1.0 - ratio
    if falloff != "smoothstep":
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown band falloff {falloff!r}", stage="degrade.wear.band_weight")
    return 1.0 - (3.0 * ratio ** 2 - 2.0 * ratio ** 3)


def _pin_ring(mesh: Any, mask: np.ndarray) -> np.ndarray:
    """Vertices just outside ``mask`` (the fixed rim of a band); the offset is pinned there."""
    faces = np.asarray(mesh.faces, dtype=np.int64)
    inside = np.zeros(len(mesh.vertices), dtype=bool)
    inside[np.asarray(mask, dtype=bool)] = True
    rim = np.zeros(len(mesh.vertices), dtype=bool)
    face_inside = inside[faces]
    for corner in range(3):
        # a vertex of a face that is not fully inside -> on the boundary ring
        not_full = ~np.all(face_inside, axis=1)
        rim[faces[not_full, corner]] = True
    return rim & ~inside


def _face_prism_violations(mesh: Any, normals: np.ndarray, offset: np.ndarray,
                           faces: np.ndarray) -> np.ndarray:
    """Faces whose moved corners leave the face's own prism, by a closed-form 2-D test.

    For one face with corners ``v_k`` and unit normal ``n``, the moved corners are
    ``v_k - n_k d_k``.  If the **projection** of every moved corner onto the face plane stays
    inside the original triangle, no point of the moved triangle can pierce the original face: the
    triangle only slides inward through its own prism.  That is a sufficient condition for
    ``damaged ⊆ clean`` restricted to that face, and it is evaluated here in closed form (a
    barycentric sign test) rather than by point sampling, so the verdict does not depend on a
    sampling seed.

    Returns the boolean per-face mask (``True`` = the face's prism is left).
    """
    if len(faces) == 0:
        return np.zeros(0, dtype=bool)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    triangles = vertices[faces]                                        # (F, 3, 3)
    edge1 = triangles[:, 1] - triangles[:, 0]
    edge2 = triangles[:, 2] - triangles[:, 0]
    raw = np.cross(edge1, edge2)
    norm = np.linalg.norm(raw, axis=1, keepdims=True)
    norm[norm < 1e-12] = 1.0
    unit = raw / norm
    moved = triangles - normals[faces] * offset[faces][:, :, None]     # (F, 3, 3)
    e1 = edge1 / np.maximum(np.linalg.norm(edge1, axis=1, keepdims=True), 1e-12)
    e2 = np.cross(unit, e1)
    rel = moved - triangles[:, 0][:, None, :]
    a = np.einsum("fkc,fc->fk", rel, e1)
    b = np.einsum("fkc,fc->fk", rel, e2)
    zero = np.zeros(len(faces))
    A = np.stack([zero, zero], axis=1)
    B = np.stack([np.linalg.norm(edge1, axis=1), zero], axis=1)
    C = np.stack([np.einsum("fc,fc->f", edge2, e1), np.einsum("fc,fc->f", edge2, e2)], axis=1)

    def sign(p: np.ndarray, q: np.ndarray, r: np.ndarray) -> np.ndarray:
        return ((q[:, 0] - p[:, 0]) * (r[:, 1] - p[:, 1])
                - (q[:, 1] - p[:, 1]) * (r[:, 0] - p[:, 0]))

    bad = np.zeros(len(faces), dtype=bool)
    for k in range(3):
        point = np.stack([a[:, k], b[:, k]], axis=1)
        d1 = sign(A, B, point)
        d2 = sign(B, C, point)
        d3 = sign(C, A, point)
        has_neg = (d1 < -1e-12) | (d2 < -1e-12) | (d3 < -1e-12)
        has_pos = (d1 > 1e-12) | (d2 > 1e-12) | (d3 > 1e-12)
        bad |= has_neg & has_pos
    return bad


def _inplane_cap_mm(mesh: Any, normals: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Largest offset a face's corners may take before the face can pierce its own plane.

    For one face with unit normal ``n`` and moved corners ``v_k - n_k d_k``, the *perpendicular*
    part of every offset moves the corner strictly inward (never out of the solid), while the
    *in-plane* part ``p_k = -(n_k - (n_k·n) n) d_k`` slides the corner sideways.  A corner whose
    in-plane displacement is shorter than the inradius ``r`` of the face cannot leave the triangle
    around it, so the face cannot pierce the original surface anywhere.  Requiring

        ``|p_k| < r``   for every corner   ⇔   ``d_k * sqrt(1 - (n_k·n)^2) < r``

    gives the per-corner cap reported here (``inf`` where the vertex normal is parallel to the face
    normal, which is the common case and costs nothing).

    This is the *sufficient* form of the prism test.  The exact projection test (does the projected
    corner stay inside the triangle?) was implemented first and measured to be unusable: a sliver
    triangle's real inradius is far smaller than its circumradius, so the exact test is dominated by
    near-degenerate faces and drove the accepted wear factor to 0 on the real mother body.
    """
    if len(faces) == 0:
        return np.zeros(0, dtype=np.float64)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    triangles = vertices[faces]
    edge1 = triangles[:, 1] - triangles[:, 0]
    edge2 = triangles[:, 2] - triangles[:, 0]
    edge3 = triangles[:, 2] - triangles[:, 1]
    raw = np.cross(edge1, edge2)
    double_area = np.linalg.norm(raw, axis=1)
    norm = np.where(double_area[:, None] < 1e-12, 1.0, double_area[:, None])
    unit = raw / norm
    perimeter = (np.linalg.norm(edge1, axis=1) + np.linalg.norm(edge2, axis=1)
                 + np.linalg.norm(edge3, axis=1))
    inradius = np.where(perimeter > 1e-12, double_area / np.maximum(perimeter, 1e-12), 0.0)
    # cosine between each corner's vertex normal and the face normal
    cos = np.einsum("fkc,fc->fk", normals[faces], unit)
    tangent = np.sqrt(np.clip(1.0 - cos ** 2, 0.0, 1.0))
    return np.where(tangent > 1e-9, inradius[:, None] / np.maximum(tangent, 1e-12), np.inf)


def inward_offset_guard(mesh: Any, offset_mm: np.ndarray, *,
                        safety: float = 0.90) -> tuple[np.ndarray, dict[str, Any]]:
    """Shrink the offset of any vertex whose **faces** would leave their own prism.

    Why the guard has to look at faces, not only vertices
    ----------------------------------------------------
    The offset moves *vertices* along their own normals, but ``damaged ⊆ clean`` is a statement
    about the *surface between* them.  A vertex can be strictly inside while being a corner of a
    triangle that still reaches the original surface: measured on the real mother body
    ``LIN0000_V10_M11_PAT15`` (7936 faces, 3973 vertices, median wall 10.0 mm) at wear level 4,
    the violating triangles of the shipped ``subset_outside_stats`` sample (8-12 of 1200 samples,
    up to 0.456 mm outside) all had three very different vertex offsets — measured example
    ``1.5998 / 0.1084 / 1.5998`` mm on a 311 mm² sliver.  The interior of such a triangle stays
    where the original face was while the moved corners cut across it in plane, so a vertex-only
    guard reports zero violations while the subset check still fails.

    The instrument
    --------------
    :func:`_inplane_cap_mm`: a closed-form per-face cap derived from the *in-plane* component of
    each corner offset against the face's inradius.  For every vertex the applied offset becomes
    the smallest cap over its incident faces, so no face can pierce its own plane anywhere.  A
    per-face exact projection test and a global bisection on one factor were both implemented first
    and are rejected on measured grounds: the exact test is dominated by near-degenerate slivers
    (it drove the accepted factor to 0 on the real mother body, i.e. no wear at all), and the global
    bisection then has to follow it to the same 0.  The inradius form is the *sufficient* condition,
    it keeps the depth field's shape, and it costs one pass — the truncation it produces is reported
    per level instead of being hidden.

    Two other instruments were tried and are rejected on measured grounds:

    * ``trimesh.proximity.signed_distance`` on moved face centroids: every centroid of a
      vertex-offset body sits within ~1e-6 mm of the source surface by construction (measured: 667
      of 2645 moved centroids reported ``sd <= 0`` while the *sampled* surface had only 8 real
      violations), so it fires on numerical noise instead of on protrusion;
    * an Open3D ray test along the face normal: casting from any point of a closed mesh hits the
      body (measured: 19/19 known-outside centroids returned a finite ``t_hit`` along both ``+n``
      and ``-n``), so it carries no inside/outside information.

    The A09 tolerance is untouched: the verdict is re-measured afterwards by
    :func:`synlab.physical.api.subset_outside_stats` at 1e-3 mm.
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    normals = _area_weighted_vertex_normals(mesh)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    offset = np.clip(np.asarray(offset_mm, dtype=np.float64).reshape(-1), 0.0, None)
    caps = _inplane_cap_mm(mesh, normals, faces)
    per_vertex_cap = np.full(len(vertices), np.inf, dtype=np.float64)
    if caps.size:
        for corner in range(3):
            np.minimum.at(per_vertex_cap, faces[:, corner], caps[:, corner])
    finite_cap = np.isfinite(per_vertex_cap)
    applied = np.where(offset > 0, np.minimum(offset, float(safety) * per_vertex_cap), 0.0)
    applied = np.clip(np.nan_to_num(applied, nan=0.0, posinf=0.0), 0.0, None)
    truncated = (offset > 0) & (applied < offset - 1e-15)
    report: dict[str, Any] = {
        "instrument": "closed-form in-plane cap per face corner: "
                      "d * sqrt(1 - (n_vertex . n_face)^2) < safety * inradius(face)",
        "method": "per-vertex minimum over the caps of its incident faces",
        "safety_factor": float(safety),
        "vertices_moved": int(np.count_nonzero(offset > 0)),
        "faces_checked": int(len(faces)),
        "vertices_with_finite_cap": int(np.count_nonzero(finite_cap)),
        "vertices_truncated": int(np.count_nonzero(truncated)),
        "declared_max_mm": float(offset.max()) if offset.size else 0.0,
        "applied_max_mm": float(applied.max()) if applied.size else 0.0,
        "max_truncation_mm": float(np.max(offset - applied)) if offset.size else 0.0,
        "median_cap_mm": float(np.median(per_vertex_cap[finite_cap])) if bool(
            np.any(finite_cap)) else 0.0,
        "min_cap_mm": float(np.min(per_vertex_cap[finite_cap])) if bool(
            np.any(finite_cap)) else 0.0,
    }
    return applied, report


# ======================================================================================
# the model
# ======================================================================================
@dataclass(frozen=True)
class WearModel:
    """Physically driven wear/aging parameters (all defaults are *candidate* unless noted).

    ``handling_contacts``
        number of handling/transport contacts the object is assumed to have survived.  Documented
        archaeology gives no number; :data:`DEFAULT_HANDLING_CONTACTS` is a candidate.
    ``mass_kg`` / ``contact_pressure_kpa``
        base abrasion is driven by contact pressure, not by a depth: the depth follows from
        ``pressure / hardness`` scaled by the abrasive embedment (porosity).
    ``support_plane`` / ``opening_axis``
        *measured* from the body when ``None`` (the base is the tangent plane of the support, the
        opening is the axis of the thinnest-wall ring).
    ``layer_thickness_range_mm``
        the measured L01/L03 geometric-layer interval; the per-body layer thickness is clipped
        into it, so the model can never claim a glaze thicker *or* thinner than the project has
        actually built.
    ``margin``
        factorial wall-thickness guard: the applied depth never exceeds ``margin * t_wall``.
    """

    material_id: str = "M03"
    handling_contacts: float = 40.0
    mass_kg: float = 0.35
    contact_pressure_kpa: float = 12.0
    burial_years: float = 300.0
    p_h_cycles: float = 300.0
    soluble_salt_ppm: float = 800.0
    layer_thickness_range_mm: tuple[float, float] = GLAZE_THICKNESS_RANGE_MM
    support_plane: Sequence[float] | None = None      # (3,) normal, measured when None
    opening_axis: Sequence[float] | None = None       # (3,) direction, measured when None
    opening_side: str = "auto"                        # auto | + | -
    margin: float = 0.30
    #: fraction of the layer thickness that must remain under an intact glaze cap
    glaze_loss_fraction: float = 0.75
    #: candidate constants; each one documented as CANDIDATE in :meth:`provenance`
    contact_band_width_mm: float = 2.5
    base_band_mm: float = 4.0
    chip_radius_mm: float = 1.6
    microcrack_depth_mm: float = 0.18
    soil_thickness_um: float = 60.0
    #: below this measured wall thickness the body is treated as a *sheet* rather than a solid
    #: (it changes the wear mechanism, not the tolerance)
    thin_sheet_mm: float = 1.0
    #: grid/limit decisions, not physical knobs
    max_band_width_mm: float = 12.0
    seed: int = 20261001

    # ------------------------------------------------------------------ provenance
    def provenance(self) -> dict[str, Any]:
        """Which field is a documented value, a derivation or a candidate (no silent numbers)."""
        traits = material_wear_traits(self.material_id)
        candidate = lambda note: SpecValue(None, "CANDIDATE", note=note)  # noqa: E731
        return {
            "material_id": {"value": self.material_id, "provenance": "DOCUMENTED",
                            "ref": "synlab/schemas/spec.py MATERIAL_IDS M01..M12"},
            "material_traits": traits.as_dict(),
            "handling_contacts": {**candidate(
                "无考古实测次数；把手/搬运次数按'传世+出土搬运'量级取候选值。"
                "模型只用它做线性缩放，实测替换后不改结构").__dict__, "value": self.handling_contacts},
            "mass_kg": {**candidate("器物质量未实测；0.35 kg 为中等碗/罐量级候选值").__dict__,
                        "value": self.mass_kg},
            "contact_pressure_kpa": {**candidate(
                "放置面接触压强未实测；由 mass/contact_area 反解，未标定前为候选").__dict__,
                "value": self.contact_pressure_kpa},
            "burial_years": {**candidate("埋藏年限未逐件定年；300 年为出土陶器量级候选").__dict__,
                             "value": self.burial_years},
            "p_h_cycles": {**candidate("干湿/冻融循环次数未实测；用于盐析与风化速率").__dict__,
                           "value": self.p_h_cycles},
            "soluble_salt_ppm": {**candidate("可溶盐含量未实测（需离子色谱/电导率）").__dict__,
                                 "value": self.soluble_salt_ppm},
            "layer_thickness_range_mm": {
                "value": list(self.layer_thickness_range_mm), "provenance": "MEASURED",
                "ref": "L01/L03 GEOMETRIC_LAYER 釉层/涂层厚度实测区间 0.469-1.173 mm",
                "note": "实测依据；每件实体的层厚由实测壁厚 * 材料分数耦合后再夹到该区间"},
            "support_plane": {"value": None if self.support_plane is None
                              else list(self.support_plane),
                              "provenance": "MEASURED" if self.support_plane is None
                              else "CALLER", "note": "None = measured from the body"},
            "opening_axis": {"value": None if self.opening_axis is None
                             else list(self.opening_axis),
                             "provenance": "MEASURED" if self.opening_axis is None else "CALLER"},
            "margin": {"value": self.margin, "provenance": "CANDIDATE",
                       "ref": "A09 subset_v2 合法性判据",
                       "note": ("乘性壁厚守卫；0.30 是候选（待实测：用真实薄壁片做穿透试验）。"
                                "判据本身未被放宽——受损体仍须水密、正体积、1e-3 mm 子集")},
            "glaze_loss_fraction": {**candidate("釉层剥离判据（剥落处剩余层厚分数）未实测").__dict__,
                                    "value": self.glaze_loss_fraction},
            "contact_band_width_mm": {**candidate("口沿接触带宽度未实测；2.5 mm 为手工搬运量级").__dict__,
                                      "value": self.contact_band_width_mm},
            "base_band_mm": {**candidate("底面接触带宽度未实测；4.0 mm 为放置面量级").__dict__,
                             "value": self.base_band_mm},
            "chip_radius_mm": {**candidate(
                "崩口影响半径未实测；1.6 mm 为口沿崩口量级候选（可由崩口面积反解）").__dict__,
                "value": self.chip_radius_mm},
            "microcrack_depth_mm": {**candidate("微裂纹深度未实测；0.18 mm 为釉面龟裂量级").__dict__,
                                    "value": self.microcrack_depth_mm},
            "soil_thickness_um": {**candidate("土沁/积垢层厚未实测；60 µm 为薄层积垢量级").__dict__,
                                  "value": self.soil_thickness_um},
            "thin_sheet_mm": {**candidate("薄片判据未实测；1.0 mm 以下按薄片机制（两面同时磨损）").__dict__,
                              "value": self.thin_sheet_mm},
        }

    # ------------------------------------------------------------------ context
    def effective_layer_mm(self, wall_mm: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        """Glaze/coating thickness coupled to the *measured* wall, clamped to the measured range."""
        traits = material_wear_traits(self.material_id)
        fraction = float(traits.glaze_fraction_of_wall.value)
        lo, hi = (float(self.layer_thickness_range_mm[0]), float(self.layer_thickness_range_mm[1]))
        raw = fraction * np.asarray(wall_mm, dtype=np.float64)
        layer = np.clip(np.nan_to_num(raw, nan=0.0), lo, hi)
        return layer, {
            "fraction_of_wall": fraction,
            "fraction_provenance": traits.glaze_fraction_of_wall.provenance,
            "clamp_mm": [lo, hi],
            "clamp_provenance": "MEASURED (L01/L03 geometric-layer thickness interval)",
            "raw_median_mm": float(np.median(raw[np.isfinite(raw)])) if np.isfinite(raw).any()
            else 0.0,
            "median_mm": float(np.median(layer)), "min_mm": float(layer.min()),
            "max_mm": float(layer.max()),
        }

    def opening_direction(self, mesh: Any, wall_mm: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        """The opening axis: the direction in which the *thin* wall sits at the extreme.

        Measured, not assumed: the opening of a vessel is where the shell is thinnest and the
        surface ends, so the axis is the principal direction of the vertices whose measured wall
        thickness is in the lowest quartile.  ``opening_side`` selects which end (+/-) carries the
        rim; ``auto`` takes the end whose thin-wall density is higher.
        """
        if self.opening_axis is not None:
            axis = np.asarray(self.opening_axis, dtype=np.float64)
            axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
            return axis, {"source": "CALLER", "axis": axis.tolist()}
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        finite = np.isfinite(wall_mm)
        if not bool(np.any(finite)):
            raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                              "opening_direction needs a measured wall thickness",
                              stage="degrade.wear.opening_direction")
        threshold = float(np.percentile(wall_mm[finite], 25))
        thin = finite & (wall_mm <= threshold)
        if int(thin.sum()) < 6:
            thin = finite
        points = vertices[thin]
        centre = points.mean(axis=0)
        centred = points - centre
        # principal axis of the thin-wall vertex cloud
        _u, _s, vt = np.linalg.svd(centred, full_matrices=False)
        axis = np.asarray(vt[0], dtype=np.float64)
        axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
        limits = vertices @ axis
        density_pos = float(np.mean((points @ axis) > np.median(limits)))
        density_neg = 1.0 - density_pos
        if self.opening_side == "+":
            sign = 1.0
        elif self.opening_side == "-":
            sign = -1.0
        else:
            sign = 1.0 if density_pos >= density_neg else -1.0
        axis = axis * sign
        return axis, {
            "source": "MEASURED (principal axis of the thinnest-wall quartile)",
            "axis": axis.tolist(), "threshold_mm": threshold,
            "thin_vertices": int(thin.sum()), "sign_rule": self.opening_side,
            "density_positive_end": density_pos, "density_negative_end": density_neg,
        }

    def support_plane_of(self, mesh: Any, opening: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        """The placement plane: the support tangent at the end *opposite* the opening."""
        if self.support_plane is not None:
            normal = np.asarray(self.support_plane, dtype=np.float64)
            normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
            return normal, {"source": "CALLER", "normal": normal.tolist()}
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        down = -np.asarray(opening, dtype=np.float64)
        height = vertices @ down
        top = float(np.percentile(height, 98.0))
        band = vertices[height >= top - 1e-9]
        if len(band) < 3:
            band = vertices[height >= float(np.max(height)) - 1e-6]
        centre = band.mean(axis=0)
        _u, _s, vt = np.linalg.svd(band - centre, full_matrices=False)
        normal = np.asarray(vt[2], dtype=np.float64)
        if float(normal @ down) < 0:
            normal = -normal
        return normal, {
            "source": "MEASURED (least-squares plane of the 2 % lowest ring opposite the opening)",
            "normal": normal.tolist(), "support_vertices": int(len(band)),
            "opposite_opening": True,
        }


@dataclass
class WearField:
    """The applied material-loss field plus every measurement taken on it."""

    depth_mm: np.ndarray                      # per vertex, >= 0
    applied_mm: np.ndarray                    # after the wall-thickness clamp
    clamped_mm: np.ndarray                    # how much the guard removed
    per_mechanism: dict[str, np.ndarray]      # raw (unclamped) depth per mechanism
    glaze_loss: np.ndarray                    # bool per vertex: layer gone, substrate exposed
    soil: dict[str, np.ndarray]               # image-domain level per soil type, in [0,1]
    measured: dict[str, float]
    units: dict[str, str]
    info: dict[str, Any]
    face_depth_mm: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))

    @property
    def nonzero_fraction(self) -> float:
        return float(np.mean(self.applied_mm > 0)) if self.applied_mm.size else 0.0


@dataclass
class WearResult:
    """A legal worn body plus its field, measurements and the legality evidence."""

    mesh: Any
    field: WearField
    level: int
    intensity: float
    mechanisms: tuple[str, ...]
    wall: dict[str, Any]
    curvature: dict[str, Any]
    layer: dict[str, Any]
    opening: dict[str, Any]
    support: dict[str, Any]
    info: dict[str, Any]


# ======================================================================================
# apply
# ======================================================================================
def _mechanism_fields(mesh: Any, model: WearModel, wall_mm: np.ndarray, kappa: np.ndarray,
                      layer_mm: np.ndarray, *, opening: np.ndarray, support: np.ndarray,
                      intensity: float, base_seed: int) -> tuple[
        dict[str, np.ndarray], np.ndarray, dict[str, Any], dict[str, Any]]:
    """Raw (unclamped) depth per mechanism, the glaze-loss mask and the two band geometries."""
    from ..physical.fields import FourierField
    from ..seeds import make_rng

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    traits = material_wear_traits(model.material_id)
    porosity = float(traits.porosity.value)
    hardness = max(float(traits.hardness_mohs.value), 0.1)
    toughness = max(float(traits.toughness.value), 0.05)
    n = len(vertices)
    wall_filled = np.where(np.isfinite(wall_mm), wall_mm, np.nanmax(wall_mm) if np.isfinite(
        wall_mm).any() else 1.0)
    seed = int(base_seed)
    jitter_rng = make_rng(seed, "wear", "glaze_edge_jitter")
    chip_rng = make_rng(seed, "wear", "edge_chip")
    crack_rng = make_rng(seed, "wear", "microcrack")

    # -- rim band: thin wall at the opening end -----------------------------------------
    # The *lip* is where the shell ends at the opening: a narrow ring at the extreme of the
    # measured opening axis whose wall is thin.  Both conditions are needed — a body can be thin
    # all over (a sheet) or blunt at the top (a closed form), and only their intersection is a
    # rim.  The height gate is 5 % of the extent along that axis (the measured lip band of a
    # 270 mm body is therefore <= 13.5 mm, i.e. the documented 2-5 mm contact band plus its
    # shoulder), and within that ring the *thinnest* vertices are the lip.
    height = vertices @ opening
    span = float(np.ptp(height))
    top = float(np.max(height))
    gate = max(0.05 * span, 3.0 * model.contact_band_width_mm)
    near_opening = height >= top - gate
    if int(np.count_nonzero(near_opening)) < 6:
        near_opening = height >= top - max(0.10 * span, gate)
    candidates = np.flatnonzero(near_opening)
    ring_wall = wall_filled[candidates]
    # blade/rim rule: thin relative to the body's own wall distribution (never an absolute mm)
    cutoff = min(float(np.percentile(wall_filled, 25.0)),
                 float(np.percentile(ring_wall, 50.0)))
    lip_vertices = candidates[ring_wall <= cutoff]
    if lip_vertices.size < 6:
        lip_vertices = candidates[np.argsort(ring_wall)[:max(6, len(candidates) // 4)]]
    rim_distance = geodesic_distance_mm(mesh, lip_vertices)
    rim_width = float(np.clip(model.contact_band_width_mm, 0.5, model.max_band_width_mm))
    rim_profile = band_weight(rim_distance, rim_width, falloff="smoothstep")
    pin = _pin_ring(mesh, rim_distance <= rim_width)
    rim_profile[pin] = 0.0
    rim_band = {
        "seed_vertices": int(lip_vertices.size),
        "opening_gate_mm": float(gate),
        "opening_gate_rule": "5 % of the extent along the measured opening axis, floored at "
                             "3 x contact_band_width_mm",
        "thin_wall_cutoff_mm": float(cutoff),
        "thin_wall_rule": "min(p25 of the body wall, p50 of the ring wall) - a blade/rim rule, "
                          "never an absolute thickness",
        "band_width_mm": rim_width,
        "contact_band_width_mm": model.contact_band_width_mm,
        "pinned_boundary_vertices": int(pin.sum()),
        "distance_metric": "Dijkstra geodesic along mesh edges (mm)",
        "seed_rule": "thin-wall ring at the opening extreme of the measured opening axis",
    }

    # -- base band: footprint on the placement plane ------------------------------------
    support_height = vertices @ support
    depth_above_support = support_height - float(np.min(support_height))
    footprint = depth_above_support <= 0.02 * max(float(np.ptp(support_height)), 1e-6)
    footprint_vertices = np.flatnonzero(footprint)
    if footprint_vertices.size == 0:
        footprint_vertices = np.flatnonzero(
            depth_above_support <= float(np.percentile(depth_above_support, 5.0)))
    base_distance = geodesic_distance_mm(mesh, footprint_vertices)
    base_width = float(np.clip(model.base_band_mm, 1.0, model.max_band_width_mm))
    base_profile = band_weight(base_distance, base_width, falloff="linear")
    base_pin = _pin_ring(mesh, base_distance <= base_width)
    base_profile[base_pin] = 0.0
    base_band = {
        "seed_vertices": int(footprint_vertices.size),
        "band_width_mm": base_width,
        "pinned_boundary_vertices": int(base_pin.sum()),
        "support_contact_fraction": float(footprint.mean()),
        "seed_rule": "within 2 % of the body extent above the measured support plane",
    }

    # -- physically derived maxima ------------------------------------------------------
    glaze_present = bool(np.median(layer_mm) > 0)
    # rim: each contact abrades a Hertzian-class band; the loss is depth-per-contact scaled by
    # hardness and by how unsupported the lip is (thin wall = less material to lose before the
    # profile changes, so the *relative* loss is larger).
    gaussian_profile = np.exp(-0.5 * (rim_distance / max(rim_width * 0.5, 1e-6)) ** 2)
    gaussian_profile[pin] = 0.0
    rim_profile_total = np.clip(rim_profile + 0.6 * gaussian_profile, 0.0, 1.0)
    lip_thickness = float(np.median(wall_filled[lip_vertices])) if lip_vertices.size else float(
        np.median(wall_filled))
    per_contact_mm = 0.004 * (3.0 / hardness) * (0.6 + 0.8 * porosity)
    rim_max = per_contact_mm * float(model.handling_contacts) * (
        1.0 + 0.5 * (1.0 - min(lip_thickness / max(model.thin_sheet_mm * 3.0, 1e-6), 1.0)))
    rim_field = rim_profile_total * rim_max

    # base: abrasive wear scales with contact pressure / surface hardness and with the
    # embedment of grit (porosity); a glazed base loses the glaze first and then the body.
    pressure_term = float(model.contact_pressure_kpa) / max(hardness, 1e-6)
    grit = 1.0 + 0.8 * porosity
    base_max = 0.0016 * pressure_term * grit * math.sqrt(max(float(model.burial_years), 0.0) / 100.0)
    base_field = base_profile * base_max

    # glaze loss: a shell spalls where it is unsupported on a convex high spot and where the
    # substrate is thick enough to have pushed the layer off (thermal expansion mismatch).
    kappa_scale = max(float(np.percentile(np.abs(kappa), 90.0)), 1e-6)
    convexity = np.clip(kappa / kappa_scale, 0.0, 1.0)
    support_term = np.clip(wall_filled / max(np.median(wall_filled), 1e-6), 0.0, 3.0) / 3.0
    spall_rank = np.clip(0.55 * convexity + 0.30 * support_term + 0.15 * porosity / 0.35,
                         0.0, 1.0)
    spall_rank = np.clip(spall_rank + 0.12 * (FourierField.sample_frozen(
        jitter_rng, scale_mm=max(6.0 * float(np.mean(layer_mm))
                                 / max(np.median(layer_mm), 1e-6), 2.0),
        n_components=6, field_id="wear_glaze_edge_jitter").raw(vertices) * 0.5), 0.0, 1.0)
    if glaze_present:
        glaze_threshold = float(np.quantile(spall_rank, 1.0 - 0.55 * intensity))
        glaze_map = spall_rank >= glaze_threshold
    else:
        glaze_map = np.zeros(n, dtype=bool)
    glaze_depth = np.where(glaze_map, np.clip(layer_mm, 0.0, None)
                           * float(model.glaze_loss_fraction), 0.0)

    # edge chip: at convex edges the loss is a spherical-cap profile; where the wall is thin the
    # chip is limited by the wall (that is the wall guard's job, not this field's).
    chip_profile, chip_info = _chip_profile(mesh, chip_rng, model)
    chip_max = 0.35 * model.chip_radius_mm * (1.0 / max(toughness, 0.05)) * (
        0.5 + 1.5 * porosity)
    chip_field = chip_profile * min(chip_max, 0.45 * model.chip_radius_mm)

    # microcracks: a thin trace network; depth is bounded by the coating thickness wherever the
    # surface carries one, so a crack never opens the body.
    crack_profile, crack_info = _crack_profile(mesh, crack_rng, model)
    crack_cap = np.clip(layer_mm, 0.0, None) if glaze_present else np.full(n, 0.5)
    crack_field = np.minimum(crack_profile * float(model.microcrack_depth_mm), crack_cap)

    fields = {"rim_wear": rim_field, "base_abrasion": base_field, "glaze_loss": glaze_depth,
              "edge_chip": chip_field, "microcrack": crack_field}
    drivers = {
        "per_contact_mm": per_contact_mm, "rim_max_mm": rim_max,
        "lip_thickness_mm": lip_thickness, "base_max_mm": base_max,
        "pressure_term_kpa_per_mohs": pressure_term, "grit_embedment_factor": grit,
        "chip_max_mm": float(min(chip_max, 0.45 * model.chip_radius_mm)),
        "crack_cap_mm_median": float(np.median(crack_cap)),
        "glaze_threshold_rank": float(glaze_threshold) if glaze_present else None,
        "glaze_area_fraction": float(np.mean(glaze_map)),
        "hardness_mohs": hardness, "toughness": toughness, "porosity": porosity,
        "chip": chip_info, "crack": crack_info, "layer_present": glaze_present,
    }
    return fields, glaze_map, {"rim": rim_band, "base": base_band}, drivers


def _chip_profile(mesh: Any, rng: np.random.Generator, model: WearModel) -> tuple[
        np.ndarray, dict[str, Any]]:
    """Spherical-cap chip field centred on a frozen subset of convex edges."""
    from ..physical.fields import convex_edges, edge_sample_points

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    edges = convex_edges(mesh, min_angle_deg=45.0)
    if len(edges) == 0:
        return np.zeros(len(vertices), dtype=np.float64), {"convex_edges": 0,
                                                           "note": "no convex edge population"}
    points = edge_sample_points(mesh, edges, density_mm=0.3)
    if len(points) == 0:
        return np.zeros(len(vertices), dtype=np.float64), {"convex_edges": int(len(edges)),
                                                           "note": "no edge sample points"}
    # frozen choice: the *rank* of every edge anchor, so increasing intensity reveals a nested
    # subset of the same chips instead of re-rolling their positions
    order = np.argsort(rng.random(len(points)), kind="stable")
    rank = np.empty(len(points), dtype=np.float64)
    rank[order] = np.linspace(0.0, 1.0, len(points))
    radius = float(model.chip_radius_mm)
    field = np.zeros(len(vertices), dtype=np.float64)
    for index in range(len(points)):
        d = np.linalg.norm(vertices - points[index][None, :], axis=1)
        field = np.maximum(field, np.clip(1.0 - (d / radius) ** 2, 0.0, 1.0))
    return field, {"convex_edges": int(len(edges)), "anchors": int(len(points)),
                   "radius_mm": radius, "nested_by": "frozen random rank per anchor",
                   "rank_field": rank}


def _crack_profile(mesh: Any, rng: np.random.Generator, model: WearModel) -> tuple[
        np.ndarray, dict[str, Any]]:
    """Micro-crack trace field: a frozen 3-D Fourier ridge network, normalised to [0,1]."""
    from ..physical.fields import FourierField

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    scale = max(float(np.ptp(vertices, axis=0).max()) / 6.0, 0.5)
    field = FourierField.sample_frozen(rng, scale_mm=scale, n_components=10,
                                       field_id="wear_microcrack_network")
    raw = np.abs(field.raw(vertices))
    top = float(np.percentile(raw, 92.0))
    span = max(float(raw.max()) - top, 1e-9)
    profile = np.clip((raw - top) / span, 0.0, 1.0)
    return profile, {"scale_mm": scale, "n_components": 10, "ridge_percentile": 92.0,
                     "covered_fraction": float(np.mean(profile > 0)),
                     "field_id": "wear_microcrack_network"}


def _soil_fields(mesh: Any, stream_rng: Any, model: WearModel, *,
                 opening: np.ndarray, support: np.ndarray, intensity: float,
                 wall_mm: np.ndarray) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Image-domain soil/patina levels per vertex, in [0,1] (never mixed into the geometry)."""
    from ..physical.fields import FourierField

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    traits = material_wear_traits(model.material_id)
    porosity = float(traits.porosity.value)
    # crevice proxy: the measured wall thickness is a usable local "how enclosed is this surface"
    # proxy, and the underside term uses the measured support normal.  Both are measured here.
    wall = np.asarray(wall_mm, dtype=np.float64)
    wall_filled = np.where(np.isfinite(wall), wall,
                           np.nanmedian(wall) if np.isfinite(wall).any() else 1.0)
    enclose = 1.0 - np.clip(wall_filled / max(np.percentile(wall_filled, 90.0), 1e-6), 0.0, 1.0)
    underside = np.clip(-(vertices @ support), 0.0, None)
    underside = 1.0 - np.clip(underside / max(float(np.ptp(vertices @ support)), 1e-6), 0.0, 1.0)
    upturned = np.clip(vertices @ opening, 0.0, None)
    upturned = np.clip(upturned / max(float(np.ptp(vertices @ opening)), 1e-6), 0.0, 1.0)

    def patch(scale_mm: float, name: str) -> np.ndarray:
        field = FourierField.sample_frozen(stream_rng(name), scale_mm=scale_mm, n_components=8,
                                           field_id=name)
        return np.clip(0.5 * (field.raw(vertices) + 1.0), 0.0, 1.0)

    body = max(float(np.ptp(vertices, axis=0).max()), 1.0)
    base = {
        "soil_stain": 0.35 * enclose + 0.30 * underside + 0.35 * patch(body / 3.0, "soil_stain"),
        "dirt_crust": 0.30 * enclose + 0.15 * underside + 0.55 * patch(body / 5.0, "dirt_crust"),
        "iron_rust": 0.55 * patch(body / 2.0, "iron_rust") + 0.45 * enclose,
        "salt_efflorescence": 0.60 * patch(body / 8.0, "salt_efflorescence") + 0.25 * porosity / 0.35
                              + 0.15 * upturned,
        "root_trace": 0.70 * patch(body / 4.0, "root_trace") + 0.30 * enclose,
    }
    out = {k: np.clip(v, 0.0, 1.0) * float(intensity) for k, v in base.items()}
    return out, {
        "domain": "IMAGE_ONLY",
        "separated_from_geometry": True,
        "drivers": {"enclosure_proxy": "1 - measured wall thickness / p90 wall thickness",
                    "underside_proxy": "support-plane normal component",
                    "upturned_proxy": "opening-axis component (salt efflorescence)",
                    "porosity": porosity},
        "types": list(SOIL_TYPES),
        "thickness_um": float(model.soil_thickness_um),
    }


def _glaze_face_attribute(mesh: Any, glaze_map: np.ndarray) -> np.ndarray:
    """Face-level glaze-loss mask (a face is lost when all three corners are)."""
    faces = np.asarray(mesh.faces, dtype=np.int64)
    return np.all(np.asarray(glaze_map, dtype=bool)[faces], axis=1)


def apply_wear(mesh: Any, level: int, *, model: WearModel | None = None,
               mechanisms: Sequence[str] = ("rim_wear", "base_abrasion", "glaze_loss",
                                            "edge_chip", "microcrack", "soil_layer"),
               rng: np.random.Generator | None = None) -> WearResult:
    """Apply one wear level to ``mesh`` and return a legally closed worn body.

    ``level`` is 0..4; **level 0 returns the source mesh object unchanged** so the caller can
    prove identity by object identity *and* by content hash.  Randomness is fully frozen in
    ``model.seed`` (the rng argument is accepted only so a caller can reproduce a model that was
    sampled elsewhere).
    """
    level = int(level)
    if level not in range(5):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"wear level {level} outside 0..4", stage="degrade.wear.apply_wear")
    resolved = model or WearModel()
    if level == 0:
        wall = local_thickness(mesh)
        return WearResult(
            mesh=mesh, level=0, intensity=0.0, mechanisms=tuple(mechanisms),
            field=WearField(
                depth_mm=np.zeros(len(mesh.vertices), dtype=np.float64),
                applied_mm=np.zeros(len(mesh.vertices), dtype=np.float64),
                clamped_mm=np.zeros(len(mesh.vertices), dtype=np.float64),
                per_mechanism={}, glaze_loss=np.zeros(len(mesh.vertices), dtype=bool),
                soil={k: np.zeros(len(mesh.vertices), dtype=np.float64) for k in SOIL_TYPES},
                measured={}, units={},
                info={"identity": True,
                      "note": "level 0 returns the source mesh object unchanged; nothing is "
                              "offset, re-meshed or re-encoded"}),
            wall=wall, curvature={"values_per_mm": None, "identity": True}, layer={},
            opening={"identity": True}, support={"identity": True},
            info={"identity": True, "level": 0, "intensity": 0.0,
                  "model": resolved.provenance()})

    # The base seed is the model's frozen seed.  An explicit ``rng`` may *replace* it with one
    # draw from the caller's stream; every field below then comes from a **named** stream derived
    # from that seed, so two calls with the same effective seed are bit-identical and no field
    # can shift because another field drew first.
    base_seed = int(resolved.seed)
    if rng is not None:
        base_seed = int(np.asarray(rng.integers(0, 2 ** 31 - 1)).reshape(-1)[0])
    intensity = WearLevels.INTENSITY[level]
    wall_info = local_thickness(mesh)
    wall_mm = np.asarray(wall_info["values_mm"], dtype=np.float64)
    kappa = vertex_mean_curvature(mesh, wall_mm)
    layer_mm, layer_info = resolved.effective_layer_mm(wall_mm)
    opening, opening_info = resolved.opening_direction(mesh, wall_mm)
    support, support_info = resolved.support_plane_of(mesh, opening)

    fields, glaze_map, bands, drivers = _mechanism_fields(
        mesh, resolved, wall_mm, kappa, layer_mm, opening=opening, support=support,
        intensity=intensity, base_seed=base_seed)

    active = [m for m in mechanisms if m in fields]
    unknown = [m for m in mechanisms if m not in fields and m != "soil_layer"]
    if unknown:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown wear mechanisms {unknown}; known: {sorted(fields)} + soil_layer",
                          stage="degrade.wear.apply_wear")
    total = np.zeros(len(mesh.vertices), dtype=np.float64)
    for name in active:
        total = total + np.asarray(fields[name], dtype=np.float64) * float(intensity)
    soil, soil_info = (_soil_fields(
        mesh,
        lambda name: make_rng(int(base_seed), "wear", "soil", name),
        resolved, opening=opening, support=support, intensity=intensity, wall_mm=wall_mm)
        if "soil_layer" in mechanisms
        else ({k: np.zeros(len(mesh.vertices), dtype=np.float64)
               for k in SOIL_TYPES}, {"applied": False}))

    # ---- wall-thickness guard (multiplicative) and the applied field
    wall_filled = np.where(np.isfinite(wall_mm), wall_mm, 0.0)
    cap = float(resolved.margin) * np.clip(wall_filled, 0.0, None)
    applied = np.minimum(total, cap)
    clamped = np.clip(total - applied, 0.0, None)
    if not bool(np.any(applied > 0)):
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING,
                          f"wear level {level} moves no vertex: the measured wall thickness "
                          f"({np.median(wall_filled):.4f} mm median) caps every mechanism at 0",
                          stage="degrade.wear.apply_wear",
                          measurements={"level": level, "intensity": intensity,
                                        "wall_median_mm": float(np.median(wall_filled)),
                                        "cap_median_mm": float(np.median(cap))})

    # ---- inward offset guard: shrink the (rare) vertices whose normal offset would poke out
    guarded, guard_report = inward_offset_guard(mesh, applied)
    guard_shrunk = np.clip(applied - guarded, 0.0, None)
    applied = guarded
    clamped = clamped + guard_shrunk

    body = NB._offset_body(mesh, applied)
    report = _measure_wear(mesh, body, applied, clamped, fields, glaze_map, kappa, wall_mm,
                           layer_mm, active, intensity, resolved)
    face_depth = _face_depth(mesh, applied)
    field_out = WearField(
        depth_mm=total, applied_mm=applied, clamped_mm=clamped, per_mechanism=fields,
        glaze_loss=np.asarray(glaze_map, dtype=bool), soil=soil,
        measured=report["measured"], units=report["units"],
        info={"level": level, "intensity": intensity, "active_mechanisms": active,
              "drivers": drivers, "bands": bands, "soil": soil_info,
              "guard": {"rule": "applied = min(sum(mechanisms) * intensity, margin * t_wall)",
                        "margin": float(resolved.margin),
                        "clamped_vertices": int(np.count_nonzero(clamped > 0)),
                        "max_clamped_mm": float(clamped.max()) if clamped.size else 0.0,
                        "inward_offset_guard": guard_report},
              "level_ladder": list(WearLevels.INTENSITY)},
        face_depth_mm=face_depth)
    info = {
        "level": level, "intensity": intensity, "active_mechanisms": active,
        "offset_method": ("per-vertex inward offset along the area-weighted vertex normal "
                          "(synlab.degrade.narrowband._offset_body); compact support, band "
                          "boundary pinned to zero"),
        "wall_guard": field_out.info["guard"], "drivers": drivers, "bands": bands,
        "inward_offset_guard": guard_report,
        "model": resolved.provenance(),
    }
    return WearResult(mesh=body, field=field_out, level=level, intensity=intensity,
                      mechanisms=tuple(mechanisms), wall=wall_info,
                      curvature={"values_per_mm": kappa,
                                 "p90_abs_per_mm": float(np.percentile(np.abs(kappa), 90.0)),
                                 "positive_fraction": float(np.mean(kappa > 0))},
                      layer=layer_info, opening=opening_info, support=support_info, info=info)


def _face_depth(mesh: Any, per_vertex: np.ndarray) -> np.ndarray:
    """Area-weighted mean of the applied vertex depth, per face (the audit channel)."""
    faces = np.asarray(mesh.faces, dtype=np.int64)
    values = np.asarray(per_vertex, dtype=np.float64)
    return values[faces].mean(axis=1)


def _measure_wear(mesh: Any, body: Any, applied: np.ndarray, clamped: np.ndarray,
                  fields: Mapping[str, np.ndarray], glaze_map: np.ndarray, kappa: np.ndarray,
                  wall_mm: np.ndarray, layer_mm: np.ndarray, active: Sequence[str],
                  intensity: float, model: WearModel) -> dict[str, Any]:
    """Every reported number is measured on the produced geometry, not read off a parameter."""
    from ..physical import sdf as S

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)          # per face
    areas = areas / 3.0                                            # per face-corner
    vertex_area = np.zeros(len(vertices), dtype=np.float64)
    for corner in range(3):
        np.add.at(vertex_area, faces[:, corner], areas)
    nonzero = applied > 0
    contact_area = float(vertex_area[nonzero].sum())
    lost_volume = float((applied[nonzero] * vertex_area[nonzero]).sum())
    glaze_face = _glaze_face_attribute(mesh, glaze_map)
    face_area_total = float(np.asarray(mesh.area_faces, dtype=np.float64).sum())
    glaze_area = float(np.asarray(mesh.area_faces, dtype=np.float64)[glaze_face].sum())
    exposed_volume = float((np.clip(layer_mm, 0.0, None)[glaze_map] * vertex_area[glaze_map]).sum())
    watertight = S.watertight_report(body)
    measured: dict[str, float] = {
        "wear_intensity": float(intensity),
        "max_applied_depth_mm": float(applied.max()) if applied.size else 0.0,
        "mean_applied_depth_mm": float(applied[nonzero].mean()) if bool(np.any(nonzero)) else 0.0,
        "p95_applied_depth_mm": float(np.percentile(applied, 95.0)) if applied.size else 0.0,
        "clamped_max_mm": float(clamped.max()) if clamped.size else 0.0,
        "clamped_vertex_fraction": float(np.mean(clamped > 0)) if clamped.size else 0.0,
        "contact_area_mm2": contact_area,
        "contact_area_fraction": float(contact_area / max(float(vertex_area.sum()), 1e-9)),
        "lost_volume_mm3": lost_volume,
        "lost_volume_fraction": float(lost_volume / max(float(abs(mesh.volume)), 1e-9)),
        "glaze_lost_area_mm2": glaze_area,
        "glaze_lost_area_ratio": float(glaze_area / max(face_area_total, 1e-9)),
        "glaze_exposed_volume_mm3": exposed_volume,
        "wall_min_mm": float(np.nanmin(wall_mm)) if np.isfinite(wall_mm).any() else 0.0,
        "wall_median_mm": float(np.nanmedian(wall_mm)) if np.isfinite(wall_mm).any() else 0.0,
        "layer_median_mm": float(np.median(layer_mm)),
        "curvature_p90_abs_per_mm": float(np.percentile(np.abs(kappa), 90.0)),
        "volume_before_mm3": float(abs(mesh.volume)), "volume_after_mm3": float(abs(body.volume)),
        "volume_lost_mm3": float(abs(mesh.volume) - abs(body.volume)),
        "watertight": 1.0 if watertight["watertight"] else 0.0,
        "positive_volume": 1.0 if watertight["positive_volume"] else 0.0,
        "face_count_before": float(len(faces)), "face_count_after": float(len(body.faces)),
    }
    for name in active:
        values = np.asarray(fields[name], dtype=np.float64) * float(intensity)
        measured[f"depth_{name}_max_mm"] = float(values.max()) if values.size else 0.0
        measured[f"depth_{name}_mean_mm"] = float(values[values > 0].mean()) \
            if bool(np.any(values > 0)) else 0.0
    measured["mechanism_sum_max_mm"] = float(
        sum(float(np.asarray(fields[name]).max()) for name in active) * float(intensity)
        if active else 0.0)
    units = {key: ("mm3" if key.endswith("_mm3") else "mm2" if key.endswith("_mm2")
                   else "mm" if key.endswith("_mm") else "1")
             for key in measured}
    units["wall_median_mm"] = "mm"
    return {"measured": measured, "units": units, "watertight": watertight}


# ======================================================================================
# legality helpers used by the measurement report and the tests
# ======================================================================================
def legality_report(clean: Any, body: Any, *, tol_mm: float = 1e-3, n_samples: int = 1200,
                    seed: int = 0) -> dict[str, Any]:
    """The shipped A09 legality verdict, re-measured for the wear result (no relaxed tolerance)."""
    from ..physical import sdf as S
    from ..physical.api import subset_outside_stats

    watertight = S.watertight_report(body)
    subset = subset_outside_stats(body, clean, n_samples=int(n_samples), tol_mm=float(tol_mm),
                                  seed=int(seed))
    return {
        "tolerance_mm": float(tol_mm),
        "watertight": bool(watertight["watertight"]),
        "positive_volume": bool(watertight["positive_volume"]),
        "volume_mm3": float(watertight["volume_mm3"]),
        "damaged_subset_clean": bool(subset["outside_points"] == 0),
        "subset_outside_points": int(subset["outside_points"]),
        "subset_outside_fraction": float(subset["outside_fraction"]),
        "subset_max_outside_mm": float(subset["max_outside_mm"]),
        "subset_instrument": subset["instrument"],
        "clean_volume_mm3": float(abs(clean.volume)),
        "subset_of_clean_by_volume": bool(float(abs(body.volume)) <= float(abs(clean.volume)) + 1e-9),
    }
