import pathlib
p = pathlib.Path("synlab/fracture/implicit/field.py")
s = p.read_text(encoding="utf-8")
block = '''# ---------------------------------------------------------------------------- field
@dataclass
class ImplicitSheetField(MorphologyHeightField):
    """``w = dome_scale * dome + relief``, tapered to zero outside the material footprint.

    The conchoidal dome (which the frozen model caps at ``4 * sigma_r0`` but evaluates as an
    unbounded paraboloid) is scaled together with the relief by every slope-calibration step: it is
    a relief feature, and leaving it out of the scaling made the taper multiply a 1.6 mm bow, which
    is what produced the earliest curvature failures (measured 48 /mm on a 0.13 mm sheet).
    """

    envelope: Any = None
    #: scale applied to the conchoidal term (``MorphologyHeightField.apply_scale`` covers only
    #: bands / hackle / ribs / fibre / pits).
    dome_scale: float = 1.0

    def dome_term(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        return float(self.dome_scale) * np.asarray(self.dome(u, v), dtype=np.float64)

    def _parts(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``(dome, relief)`` of the frozen morphology field, without the glaze modulation."""
        modulation = self.modulation
        self.modulation = None
        try:
            dome = self.dome_term(u, v)
            relief = np.asarray(self._relief(u, v), dtype=np.float64)
        finally:
            self.modulation = modulation
        return dome, relief

    def unmasked(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``dome + relief`` before the footprint taper."""
        dome, relief = self._parts(u, v)
        if self.modulation is not None:
            return (dome + relief) * self.modulation.value(u, v)
        return dome + relief

    def raw(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        dome, relief = self._parts(u, v)
        if self.envelope is None:
            out = dome + relief
        else:
            out = self.envelope.apply(u, v, dome + relief)
        if self.modulation is not None:
            out = out * self.modulation.value(u, v)
        return out

    def apply_scale(self, ratio: float, *, core_uv: tuple[np.ndarray, np.ndarray] | None = None
                    ) -> None:
        """Scale every relief amplitude *including* the conchoidal term (see the class docstring)."""
        ratio = float(ratio)
        super().apply_scale(ratio, core_uv=core_uv)
        self.dome_scale = float(self.dome_scale) * ratio
        self.dome_amplitude_mm = float(self.dome_amplitude_mm) * ratio


# ---------------------------------------------------------------------------- spectrum
def band_limit_params(params: Any, *, delta_mm: float, samples_per_wavelength: float
                      ) -> tuple[Any, dict[str, Any]]:
    """Drop the Fourier bands the sheet triangulation cannot sample (>= 4-5 samples/lambda).

    Band-limiting is the honest alternative to aliasing: the removed bands are named with their
    amplitude and RMS contribution, and the shortest *retained* wavelength is what the sampling
    metric is evaluated against.  Nothing is coarsened silently.
    """
    lam_allowed = float(samples_per_wavelength) * float(delta_mm)
    kept: list[tuple[float, float, float, float, float]] = []
    dropped: list[dict[str, float]] = []
    for amplitude, wavelength, du, dv, phase in params.bands:
        if float(wavelength) + 1.0e-12 >= lam_allowed:
            kept.append((amplitude, wavelength, du, dv, phase))
        else:
            dropped.append({"amplitude_mm": float(amplitude), "wavelength_mm": float(wavelength),
                            "samples_at_delta": float(wavelength) / max(delta_mm, _EPS)})
    removed_rms = float(np.sqrt(np.sum([0.5 * d["amplitude_mm"] ** 2 for d in dropped])))
    kept_rms = float(np.sqrt(np.sum([0.5 * k[0] ** 2 for k in kept])))
    if not kept and params.bands:
        longest = max(params.bands, key=lambda b: float(b[1]))
        kept = [longest]
        dropped = [d for d in dropped if abs(d["wavelength_mm"] - float(longest[1])) > 1e-12]
        removed_rms = float(np.sqrt(np.sum([0.5 * d["amplitude_mm"] ** 2 for d in dropped])))
        kept_rms = float(np.sqrt(0.5 * float(longest[0]) ** 2))
    info = {
        "band_limit_mm": lam_allowed, "delta_mm": float(delta_mm),
        "samples_per_wavelength": float(samples_per_wavelength),
        "bands_requested": len(params.bands), "bands_kept": len(kept), "dropped": dropped,
        "removed_rms_mm": removed_rms, "kept_rms_mm": kept_rms,
        "requested_rms_mm": float(params.requested_rms_mm), "band_limited": bool(dropped),
        "lambda_min_realized_mm": float(min([float(k[1]) for k in kept], default=float("inf"))),
    }
    return replace(params, bands=tuple(kept)), info


def sheet_spectrum(params: Any) -> dict[str, Any]:
    """Shortest geometric scale of every active component of the field (mm)."""
    scales: dict[str, float] = {}
    for _amplitude, wavelength, _du, _dv, _phase in params.bands:
        scales[f"band_{float(wavelength):.4g}mm"] = float(wavelength)
    if params.hackle_amplitude_mm > 0.0 and params.hackle_count > 1:
        scales["hackle_arc_at_mirror"] = float(2.0 * np.pi * params.mirror_radius_mm
                                               / params.hackle_count)
    if params.rib_amplitude_mm > 0.0 and params.rib_spacing_at_mirror_mm > 0.0:
        scales["rib_spacing"] = float(params.rib_spacing_at_mirror_mm)
    if params.pit_depth_mm > 0.0:
        scales["pit_diameter"] = float(2.0 * params.pit_radius_mm)
    if params.fiber_amplitude_mm > 0.0 and params.fiber_period_mm > 0.0:
        scales["fiber_period"] = float(params.fiber_period_mm)
    if params.glaze_strip_width_mm > 0.0:
        scales["glaze_strip"] = float(params.glaze_strip_width_mm)
    shortest = min(scales.values()) if scales else float("inf")
    return {"scales_mm": scales, "shortest_mm": float(shortest)}


# ---------------------------------------------------------------------------- slope / curvature
def measure_field_slope(h_fn: Any, *, bounds: tuple[float, float, float, float],
                        mask_fn: Any, step_mm: float, max_points: int = 600_000
                        ) -> dict[str, Any]:
    """P50/P95/max slope and curvature of the realized surface over the footprint.

    The curvature is the mixed bound ``|h_uu| + 2|h_uv| + |h_vv|`` that the interpolation budget uses
    (``error <= C * cell^2 / 8``), measured on a raster finer than the sheet spacing so a cell-sized
    feature cannot hide between samples.
    """
    u0, u1, v0, v1 = (float(x) for x in bounds)
    step = float(step_mm)
    while ((u1 - u0) / step + 2.0) * ((v1 - v0) / step + 2.0) > float(max_points):
        step *= 1.25
    gu = np.arange(u0, u1 + 0.5 * step, step)
    gv = np.arange(v0, v1 + 0.5 * step, step)
    GU, GV = np.meshgrid(gu, gv, indexing="ij")
    inside = np.asarray(mask_fn(GU, GV), dtype=bool)
    if int(inside.sum()) < 64:
        return {"samples": int(inside.sum()), "note": "too few samples inside the footprint"}
    h = np.asarray(h_fn(GU, GV), dtype=np.float64)
    dv_axis, du_axis = np.gradient(h, step)
    slope = np.hypot(du_axis, dv_axis)[inside]
    angles = np.degrees(np.arctan(slope))
    ddu = np.gradient(du_axis, step, axis=0)
    ddv = np.gradient(dv_axis, step, axis=1)
    duv = np.gradient(du_axis, step, axis=1)
    curv = (np.abs(ddu) + 2.0 * np.abs(duv) + np.abs(ddv))[inside]
    return {
        "samples": int(slope.size), "step_mm": float(step),
        "slope_p50": float(np.percentile(slope, 50)),
        "slope_p95": float(np.percentile(slope, 95)),
        "slope_max": float(slope.max()),
        "angle_p50_deg": float(np.percentile(angles, 50)),
        "angle_p95_deg": float(np.percentile(angles, 95)),
        "angle_max_deg": float(angles.max()),
        "height_rms_mm": float(np.sqrt(np.mean((h[inside] - float(np.mean(h[inside]))) ** 2))),
        "height_peak_to_valley_mm": float(np.ptp(h[inside])),
        "curvature_p50_per_mm": float(np.percentile(curv, 50)),
        "curvature_p99_per_mm": float(np.percentile(curv, 99)),
        "curvature_max_per_mm": float(curv.max()),
    }


def calibrate_slope(field: ImplicitSheetField, h_fn: Any, *,
                    bounds: tuple[float, float, float, float], mask_fn: Any, step_mm: float,
                    target_p95_deg: float = SLOPE_P95_TARGET_DEG, max_iterations: int = 4,
                    on_scale: Any = None) -> dict[str, Any]:
    """Scale the relief amplitudes until the *measured* P95 slope enters the declared band.

    The step is ``tan(target) / tan(measured)`` on the realized surface (footprint taper included),
    the loop re-measures after every step, and it only ever scales the relief *down*.  The reported
    numbers are measurements, not predictions.
    """
    before = measure_field_slope(h_fn, bounds=bounds, mask_fn=mask_fn, step_mm=step_mm)
    history: list[dict[str, Any]] = [{"stage": "requested", **before}]
    target_tan = float(np.tan(np.radians(float(target_p95_deg))))
    scale_total = 1.0
    achieved = before
    for iteration in range(1, int(max_iterations) + 1):
        p95 = float(achieved.get("slope_p95", 0.0))
        if p95 <= target_tan or p95 <= 0.0:
            break
        ratio = target_tan / p95
        scale_total *= ratio
        field.apply_scale(ratio)
        if on_scale is not None:
            on_scale(ratio)
        field.mean_mm = 0.0
        achieved = measure_field_slope(h_fn, bounds=bounds, mask_fn=mask_fn, step_mm=step_mm)
        history.append({"stage": f"iteration_{iteration}", "ratio": float(ratio), **achieved})
    return {
        "target_p95_deg": float(target_p95_deg), "target_p95_tan": target_tan,
        "amplitude_scale_applied": float(scale_total),
        "before": before, "after": achieved, "history": history,
        "constraint": ("scale relief amplitudes (conchoidal term included) so that the measured P95 "
                       "of |grad h| over the footprint equals tan(target); re-measured after every "
                       "step, and only ever scaled down"),
        "achieved_within_band": bool(float(achieved.get("slope_p95", 0.0)) <= target_tan + 1e-9),
    }


'''
marker = "def build_implicit_field("
s = s.replace(marker, block + marker, 1)
p.write_text(s, encoding="utf-8")
print("restored helpers")
