import pathlib
p = pathlib.Path("synlab/fracture/implicit/field.py")
s = p.read_text(encoding="utf-8")
start = s.index("@dataclass\nclass FootprintEnvelope:")
end = s.index("def build_implicit_field(")
new = '''@dataclass
class FootprintEnvelope:
    """Outward taper of the fracture surface: 1 on the footprint, 0 far outside it.

    ``phi`` is built from the *signed distance* to the material cross-section outline:
    ``phi = smootherstep((d + width) / width)``, i.e. exactly 1 on the footprint and on its
    boundary, decaying to 0 over ``width`` outside it.  Both C^1 junctions (at ``d = 0`` and
    ``d = -width``) are smooth because ``smootherstep'`` vanishes at both ends.

    Why not force ``h = 0`` *on* the ring (the first two revisions did)
    ------------------------------------------------------------------
    Measured on the real bodies: any mask that rises from 0 at the ring to 1 in the interior has to
    interpolate between the ring and the interior, and on a thin wall strip (V18: mean cross-section
    width 1.6 mm) the medial axis of that strip is a ridge where the distance function itself has a
    slope kink.  The taper then carries a kink straight through the middle of the fracture face, and
    a sheet triangle cannot represent it (measured 0.024 mm of interpolation error versus the 0.01 mm
    budget, for every mask width between 0.5 mm and 2.7 mm).  A real fracture face does not return
    to the mean plane at the rim either, so the taper is the physically right shape: the surface
    keeps its relief to the edge and only the *outside* of the footprint is damped, which is what
    keeps the flat frame cheap.  ``boundary_height_*`` publishes where the sheet crosses the ring
    plane, and the interface patch it produces is measured like everything else.
    """

    u0: float
    v0: float
    step_mm: float
    sign_raster: np.ndarray
    signed_raster: np.ndarray
    inside_raster: np.ndarray
    boundary_cells: int
    width_mm: float
    raster_area_mm2: float
    exact_area_mm2: float
    footprint_touches_raster_edge: bool
    boundary_samples: int = 0
    boundary_source: str = ""
    blur_sigma_cells: float = 2.0
    #: kept for API stability with the earlier revisions (unused by the taper construction)
    offset_raster: np.ndarray | None = None
    dome_offset_raster: np.ndarray | None = None
    extra_raster: np.ndarray | None = None

    def mask(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``phi``: 1 on the footprint, decaying to 0 over ``width_mm`` outside it."""
        sd = raster_lookup(self.signed_raster, self.u0, self.v0, self.step_mm, u, v)
        return _smootherstep((sd + self.width_mm) / max(self.width_mm, _EPS))

    def smoothness(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``phi`` under the name ``MorphologyHeightField`` expects for its modulation slot."""
        return self.mask(u, v)

    def signed_distance(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        return raster_lookup(self.signed_raster, self.u0, self.v0, self.step_mm, u, v)

    def offset(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Unused by the taper construction (kept so the record's readers do not break)."""
        return np.zeros(np.broadcast(u, v).shape, dtype=np.float64)

    def dome_offset(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        return np.zeros(np.broadcast(u, v).shape, dtype=np.float64)

    def value(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``phi``: the object ``MorphologyHeightField`` expects in its modulation slot."""
        return self.mask(u, v)

    def apply(self, u: np.ndarray, v: np.ndarray, relief: np.ndarray) -> np.ndarray:
        """``phi * relief``: the masked surface (relief to the rim, flat far outside)."""
        uu = np.asarray(u, dtype=np.float64)
        vv = np.asarray(v, dtype=np.float64)
        out = self.mask(uu, vv) * np.asarray(relief, dtype=np.float64)
        if self.extra_raster is not None:
            out = out * raster_lookup(self.extra_raster, self.u0, self.v0, self.step_mm, uu, vv)
        return out

    def scale_offsets(self, ratio: float) -> None:
        """No-op (kept as the calibration hook; the taper has no ring offset to scale)."""
        return

    def glaze_raster_from(self, *, strip_mm: float, ratio: float) -> np.ndarray | None:
        """Relief damping inside the glaze strip (``ratio`` at the rim, 1 in the body)."""
        if strip_mm <= 0.0 or ratio >= 1.0:
            return None
        depth = np.maximum(self.signed_raster, 0.0)
        strip = max(float(strip_mm), 2.0 * float(self.step_mm))
        return float(ratio) + (1.0 - float(ratio)) * _smootherstep(depth / strip)

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_mm": float(self.step_mm), "width_mm": float(self.width_mm),
            "boundary_cells": int(self.boundary_cells),
            "raster_area_mm2": float(self.raster_area_mm2),
            "exact_area_mm2": float(self.exact_area_mm2),
            "raster_area_rel_error": float(
                abs(self.raster_area_mm2 - self.exact_area_mm2) / max(self.exact_area_mm2, _EPS)),
            "footprint_touches_raster_edge": bool(self.footprint_touches_raster_edge),
            "boundary_samples": int(self.boundary_samples),
            "boundary_source": str(self.boundary_source),
            "blur_sigma_cells": float(self.blur_sigma_cells),
            "glaze_raster": self.extra_raster is not None,
            "construction": "phi = smootherstep((signed_distance + width) / width): exactly 1 on "
                            "the footprint (relief reaches the rim, as a real fracture face does) "
                            "and 0 at 'width' outside it; the signed distance is blurred before it "
                            "is used so its raster quantisation cannot reach the surface",
        }


def _masked_blur(values: np.ndarray, mask: np.ndarray, *, sigma: float) -> np.ndarray:
    """Gaussian blur that only averages the cells where ``mask`` is true (normalised convolution)."""
    from scipy import ndimage

    num = ndimage.gaussian_filter(np.where(mask, values, 0.0), sigma=sigma, mode="nearest")
    den = ndimage.gaussian_filter(mask.astype(np.float64), sigma=sigma, mode="nearest")
    return np.where(den > 1.0e-6, num / np.maximum(den, 1.0e-12), 0.0)


def boundary_samples_uv(tris_uv: np.ndarray, *, max_step_mm: float
                        ) -> tuple[np.ndarray, dict[str, Any]]:
    """Sample the footprint boundary polyline (exterior + interior rings) in ``(u, v)``."""
    tris = np.asarray(tris_uv, dtype=np.float64).reshape(-1, 3, 2)
    try:
        import shapely

        union = shapely.union_all(shapely.polygons(tris))
        boundary = union.boundary
        parts = list(shapely.get_parts(boundary)) if boundary.geom_type != "LineString" \\
            else [boundary]
        points: list[np.ndarray] = []
        for part in parts:
            length = float(part.length)
            if length <= 0.0:
                continue
            count = int(max(8, np.ceil(length / max(float(max_step_mm), 1e-6))))
            distances = np.linspace(0.0, length, count, endpoint=False)
            sampled = shapely.line_interpolate_point(part, distances)
            points.append(np.column_stack([shapely.get_x(sampled), shapely.get_y(sampled)]))
        if points:
            return np.concatenate(points, axis=0), {
                "source": "shapely boundary of the union of the cross-section triangles",
                "parts": len(parts)}
    except Exception as exc:  # noqa: BLE001 - fall back to the triangle edges, and say so
        fallback = "shapely unavailable"
        error = f"{type(exc).__name__}: {exc}"
    else:
        fallback = "shapely produced no boundary"
        error = ""
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], axis=0)
    key = np.sort(edges, axis=1)
    flat = (key[:, 0, 0] * 1.0e6 + key[:, 0, 1] * 1.0e3
            + key[:, 1, 0] * 1.0e-3 + key[:, 1, 1])
    _uniq, inverse, counts = np.unique(np.round(flat, 6), return_inverse=True,
                                       return_counts=True)
    boundary_edges = edges[np.isin(inverse, np.nonzero(counts == 1)[0])]
    pts = boundary_edges.reshape(-1, 2)
    return np.unique(np.round(pts, 9), axis=0), {
        "source": f"triangle edges used once ({fallback} {error})".strip(), "parts": 0}


def build_footprint_envelope(tris_uv: np.ndarray, *, exact_area_mm2: float,
                             bbox: tuple[float, float, float, float],
                             step_mm: float, width_mm: float,
                             boundary_values_fn: Any = None,
                             dirichlet_step_mm: float | None = None,
                             extension_iterations: int = 0,
                             extension_tol_mm: float = 1.0e-5,
                             sigma_cells: float = 2.0
                             ) -> tuple["FootprintEnvelope", np.ndarray]:
    """Rasterise the footprint, blur its signed distance and build the outward taper."""
    from scipy import ndimage

    u0 = float(bbox[0])
    v0 = float(bbox[2])
    nu = int(np.ceil((bbox[1] - u0) / step_mm)) + 1
    nv = int(np.ceil((bbox[3] - v0) / step_mm)) + 1
    inside = rasterize_triangles(tris_uv, u0, v0, step_mm, (nu, nv))
    if not bool(inside.any()):
        raise ValueError("the material cross-section raster is empty")
    structure = ndimage.generate_binary_structure(2, 1)
    eroded = ndimage.binary_erosion(inside, structure=structure, border_value=0)
    boundary_cells = inside & ~eroded
    if not bool(boundary_cells.any()):
        boundary_cells = inside.copy()
    d_in = ndimage.distance_transform_edt(inside) * step_mm
    d_out = ndimage.distance_transform_edt(~inside) * step_mm
    signed = d_in - d_out
    #: blur the quantised EDT over a band that covers the taper plus a margin: the taper's *input*
    #: must be smooth, otherwise its one-cell staircase reaches the surface (measured: 0.04 mm).
    band = np.abs(signed) <= (2.0 * float(width_mm) + 8.0 * float(step_mm))
    signed_smooth = _masked_blur(signed, band, sigma=float(sigma_cells))
    edge = np.zeros_like(inside)
    edge[0, :] = edge[-1, :] = True
    edge[:, 0] = edge[:, -1] = True
    samples, sample_info = boundary_samples_uv(
        tris_uv, max_step_mm=float(dirichlet_step_mm if dirichlet_step_mm is not None
                                   else 0.05 * step_mm))
    del boundary_values_fn, extension_iterations, extension_tol_mm
    return FootprintEnvelope(
        u0=u0, v0=v0, step_mm=float(step_mm), sign_raster=signed_smooth,
        signed_raster=signed_smooth, inside_raster=inside,
        boundary_cells=int(boundary_cells.sum()), width_mm=float(width_mm),
        raster_area_mm2=float(inside.sum() * step_mm ** 2), exact_area_mm2=float(exact_area_mm2),
        footprint_touches_raster_edge=bool(np.any(inside & edge)),
        boundary_samples=int(samples.shape[0]),
        boundary_source=str(sample_info.get("source", "")),
        blur_sigma_cells=float(sigma_cells),
        offset_raster=None, dome_offset_raster=None,
    ), samples


'''
p.write_text(s[:start] + new + s[end:], encoding="utf-8")
print("rewrote envelope section")
