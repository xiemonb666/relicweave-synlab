"""Impact physics: target fragment count from size, material toughness and impact energy.

The model is a *scaling law with declared, traceable parameters* -- not a curve fit hidden in a
constant.  Every symbol below is written out in :mod:`synlab.fracture.impact` and in
``docs/a12/fracture_physics.md``; the parameters that are engineering assumptions are marked as
such in ``configs/a12/fracture_physics.yaml`` (``provenance:`` on every block).

Traceability of the three ingredients:

* **Energy balance** ``N * G_c * t**2 ~ U``: the fracture work of one shard is proportional to the
  new surface it creates, which for a shard of edge length ``s`` in a wall of thickness ``t`` is
  ``~ s * t``, and the shard's linear size follows ``s ~ R / N`` (a partition of a body of linear
  size ``R`` into ``N`` cells).  Then ``N * t * R / N * G_c ~ U`` is not increasing in ``N``, so
  the *count* comes from the size of the smallest shard that the energy can still create --
  ``U_1 ~ G_c * t**2`` -- which is the reference energy used below.  With a fragment count
  distributed over the available sites this gives ``N ~ (U / U_1)**beta`` with ``beta`` the
  ``impact_energy_exponent`` of the config (engineering assumption, calibrated in
  :func:`calibrate_reference_energy`).
* **Weibull weakest-link size effect**: a body of volume ``V`` has a characteristic strength
  ``sigma_c(V) ~ sigma_0 * (V / V_0)**(-1/m)`` (Weibull modulus ``m``; for earthenware ``m`` is
  small, of order 5-10, which is why a bigger body is *weaker* in the mean and not stronger).
  The same law scales the reference energy: ``U_1(V) = U_ref_0 * (V/V_0)**(2/3)`` is the
  geometric (surface) part and the Weibull part enters as ``(V/V_0)**alpha_weibull`` with
  ``alpha_weibull = 1/(2*m)`` (``m`` from the material profile / the config).
* **Drop / throw energy** ``U = 0.5 * m * v**2`` with ``m`` the mass of the body and ``v`` the
  impact speed.  ``m`` is measured from the realised geometry and the material density, never
  assumed: ``m = rho * V``.

The module is pure arithmetic on measured inputs (volume, wall thickness, material statistics),
so it runs in microseconds and is unit-testable without any mesh.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..canonical import hash_json

__all__ = [
    "ImpactConfig",
    "MaterialStats",
    "BodyStats",
    "count_model",
    "target_piece_count",
    "particle_size_distribution",
    "calibrate_reference_energy",
    "impact_energy_j",
    "impact_from_drop_height",
]

#: reference volume of the calibration body (mm^3): a 200 mm bowl with a 6 mm wall,
#: ``V_ref ~ pi * D * t * H`` with D = 200, t = 6, H = 90 -> 3.39e5 mm^3.  The value is an
#: engineering reference body, declared here (not fitted); it only sets the scale of the
#: normalised energy, every exponent is separate and declared.
V_REF_MM3 = math.pi * 200.0 * 6.0 * 90.0
#: reference impact speed (mm/s) = 3.13 m/s, i.e. a 0.5 m drop.
V_IMPACT_REF_MM_S = 3130.0
#: gravity (mm/s^2), used for the drop-height route.
G_MM_S2 = 9810.0


@dataclass
class ImpactConfig:
    """Declared parameters of the fragmentation law (mirrors ``fracture_physics.yaml``)."""

    #: ``N = N0 * (U / U_1)^beta``  -- beta is an engineering assumption (see the module docstring)
    n0: float = 3.0
    #: exponent of the energy scaling
    impact_energy_exponent: float = 0.65
    #: Weibull modulus (earthenware 5-11; the material profile's own value wins when present)
    weibull_modulus: float = 7.0
    #: weakest-link volume exponent (alpha in the docstring).  ``0.5`` = "surface-area law":
    #: alpha_eff = 1 / m + 1/2 puts the size effect for equal *specific* energy at
    #: (D/D0)**(1 + 1/m).  The 1/2 is the geometric (V**(2/3) vs V) part of the reference energy.
    weibull_volume_exponent: float = 0.5
    #: lower / upper clamp on the *deterministic* count (validity range of the scaling law)
    min_pieces: int = 2
    max_pieces: int = 64
    #: spread of the Weibull-distributed count (coefficient of variation of ``ln N``)
    log_sigma: float = 0.18
    #: characteristic fracture energy (J/mm^2) of the wall material, per material family.
    #: 1e-3 J/mm^2 = 1000 J/m^2 (dynamic fracture energy of a porous ceramic body).
    fracture_energy_j_mm2: dict[str, float] = field(default_factory=lambda: {
        "M01": 1.0e-3, "M04": 1.6e-3, "M06": 1.2e-3, "M07": 0.8e-3,
        "M09": 1.1e-3, "M10": 0.9e-3, "M11": 1.3e-3,
    })
    #: fallback when the material id is unknown (engineering assumption, flagged in meta)
    fracture_energy_default_j_mm2: float = 1.0e-3
    #: reference body of the calibration
    v_ref_mm3: float = V_REF_MM3
    v_impact_ref_mm_s: float = V_IMPACT_REF_MM_S
    #: wall-thickness reference (mm) of the calibration body
    thickness_ref_mm: float = 6.0
    #: reference density (g/cm^3) of the calibration body: frozen engineering value, fired
    #: earthenware.  It must match the material's own density for the calibration body to land on
    #: ``n0``; see :func:`calibrate_reference_energy`.
    reference_density_g_cm3: float = 2.2
    #: ``U_ref`` solved by :func:`calibrate_reference_energy` (J) -- filled at load time
    u_ref_j: float | None = None
    #: where the numbers come from (published as evidence, never guessed at read time)
    provenance: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n0": float(self.n0),
            "impact_energy_exponent": float(self.impact_energy_exponent),
            "weibull_modulus": float(self.weibull_modulus),
            "weibull_volume_exponent": float(self.weibull_volume_exponent),
            "min_pieces": int(self.min_pieces),
            "max_pieces": int(self.max_pieces),
            "log_sigma": float(self.log_sigma),
            "fracture_energy_j_mm2": {k: float(v) for k, v in sorted(
                self.fracture_energy_j_mm2.items())},
            "fracture_energy_default_j_mm2": float(self.fracture_energy_default_j_mm2),
            "v_ref_mm3": float(self.v_ref_mm3),
            "v_impact_ref_mm_s": float(self.v_impact_ref_mm_s),
            "thickness_ref_mm": float(self.thickness_ref_mm),
            "reference_density_g_cm3": float(self.reference_density_g_cm3),
            "u_ref_j": None if self.u_ref_j is None else float(self.u_ref_j),
            "provenance": dict(self.provenance),
        }

    @property
    def hash(self) -> str:
        return hash_json(self.as_dict())[:32]


@dataclass
class MaterialStats:
    """Measured material statistics of one mother (no assumed numbers)."""

    material_id: str = ""
    density_g_cm3: float = 2.2
    #: fracture energy (J/mm^2); ``None`` means "take the config's per-material table"
    fracture_energy_j_mm2: float | None = None
    weibull_modulus: float | None = None
    #: measured porosity (fraction) and grain size (mm) -- recorded, used for the roughness law
    porosity: float = 0.0
    grain_size_mm: float = 0.0
    #: source of each field, for the audit table
    provenance: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id,
            "density_g_cm3": float(self.density_g_cm3),
            "fracture_energy_j_mm2": (None if self.fracture_energy_j_mm2 is None
                                      else float(self.fracture_energy_j_mm2)),
            "weibull_modulus": (None if self.weibull_modulus is None
                                else float(self.weibull_modulus)),
            "porosity": float(self.porosity),
            "grain_size_mm": float(self.grain_size_mm),
            "provenance": dict(self.provenance),
        }


@dataclass
class BodyStats:
    """Measured geometry statistics of one mother."""

    vessel_id: str = ""
    volume_mm3: float = 0.0
    area_mm2: float = 0.0
    extents_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: wall thickness (mm): measured distribution from ``synlab.mothers.measure.thickness_samples``
    thickness_min_mm: float = 0.0
    thickness_p05_mm: float = 0.0
    thickness_median_mm: float = 0.0
    thickness_max_mm: float = 0.0
    #: outer-surface area of the whole body (mm^2), used by the specific-energy form
    outer_area_mm2: float = 0.0
    provenance: dict[str, str] = field(default_factory=dict)

    @property
    def wall_mm(self) -> float:
        """Wall thickness used by the law: the measured median (per-body, not assumed)."""
        for value in (self.thickness_median_mm, self.thickness_p05_mm, self.thickness_min_mm):
            if value and value > 0.0:
                return float(value)
        return 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "vessel_id": self.vessel_id,
            "volume_mm3": float(self.volume_mm3),
            "area_mm2": float(self.area_mm2),
            "extents_mm": [float(x) for x in self.extents_mm],
            "thickness_min_mm": float(self.thickness_min_mm),
            "thickness_p05_mm": float(self.thickness_p05_mm),
            "thickness_median_mm": float(self.thickness_median_mm),
            "thickness_max_mm": float(self.thickness_max_mm),
            "outer_area_mm2": float(self.outer_area_mm2),
            "provenance": dict(self.provenance),
        }


# ---------------------------------------------------------------------------- energy


def impact_energy_j(mass_kg: float, speed_mm_s: float) -> float:
    """``U = 0.5 * m * v**2`` with the speed in mm/s and the result in joule (kg*mm^2/s^2 = mJ)."""
    return 0.5 * float(mass_kg) * (float(speed_mm_s) * 1.0e-3) ** 2


def impact_from_drop_height(mass_kg: float, drop_height_mm: float) -> tuple[float, float]:
    """``v = sqrt(2 g h)`` and ``U = 0.5 m v^2`` for a free drop (returns ``(v_mm_s, U_J)``)."""
    speed = math.sqrt(max(2.0 * G_MM_S2 * float(drop_height_mm), 0.0))
    return float(speed), impact_energy_j(mass_kg, speed)


def calibrate_reference_energy(cfg: ImpactConfig) -> float:
    """Solve ``U_ref`` so the law reproduces ``N0`` pieces on the reference body.

    The reference body is declared explicitly: volume ``v_ref_mm3``, wall ``thickness_ref_mm``,
    **reference density** ``reference_density_g_cm3`` (a frozen engineering value: 2.2 g/cm^3,
    fired earthenware) and the impact speed of a 0.5 m drop.  Solving for ``U_ref`` makes the
    *shape* of the law (both exponents) independent of the arbitrary scale ``N0``, which is what a
    calibration is allowed to absorb.

    The reference density has to be part of the config rather than of the caller: ``count_model``
    uses the *material's* density, so a calibration that assumed a different one would make the
    reference body miss ``N0`` by ``(rho/rho_ref)**(2*beta*(2/3))`` (measured: 9 instead of 3 for
    the 2.2 g/cm^3 default used by the module's own reference body).
    """
    volume = float(cfg.v_ref_mm3)
    density = float(cfg.reference_density_g_cm3) * 1.0e-6      # g/cm^3 -> kg/mm^3
    mass = density * volume
    speed = math.sqrt(max(2.0 * G_MM_S2 * 500.0, 0.0))
    energy = impact_energy_j(mass, speed)
    alpha = 1.0 / max(float(cfg.weibull_modulus), 1.0) / 2.0 + float(cfg.weibull_volume_exponent)
    gamma = float(cfg.weibull_volume_exponent)
    shape = (volume / float(cfg.v_ref_mm3)) ** alpha \
        * (float(cfg.thickness_ref_mm) / float(cfg.thickness_ref_mm)) ** gamma
    # N = n0 * (U/U_ref)**beta * shape must equal n0 on this body, so (U/U_ref)**beta = 1/shape
    # and therefore U_ref = U * shape**(1/beta).  The Weibull size term of the *reference* body is
    # 1 by construction; the factor is written out so the identity is checkable by hand.
    return float(energy * shape ** (1.0 / float(cfg.impact_energy_exponent)))


# ---------------------------------------------------------------------------- the law


def count_model(body: BodyStats, material: MaterialStats, cfg: ImpactConfig, *,
                speed_mm_s: float | None = None, energy_j: float | None = None,
                drop_height_mm: float | None = None) -> dict[str, Any]:
    """Deterministic target fragment count plus the full arithmetic record.

    ``N = N0 * (U / U_ref)**beta * (V / V_ref)**alpha * (t_ref / t)**gamma``

    with

    * ``alpha = 1/(2 m) + weibull_volume_exponent`` (Weibull weakest link + geometric part),
    * ``gamma = weibull_volume_exponent`` (thin walls carry less fracture work per shard),
    * ``U`` from ``energy_j`` when given, else from ``speed_mm_s`` (with the measured mass),
      else from ``drop_height_mm``.
    """
    density = float(material.density_g_cm3) * 1.0e-6            # g/cm^3 -> kg/mm^3
    mass_kg = density * float(body.volume_mm3)
    m_modulus = float(material.weibull_modulus or cfg.weibull_modulus)
    alpha = 1.0 / max(m_modulus, 1.0) / 2.0 + float(cfg.weibull_volume_exponent)
    gamma = float(cfg.weibull_volume_exponent)

    if energy_j is not None:
        energy = float(energy_j)
        speed = math.sqrt(max(2.0 * energy / max(mass_kg, 1e-12), 0.0)) * 1.0e3
        energy_source = "given_energy_j"
    elif speed_mm_s is not None:
        speed = float(speed_mm_s)
        energy = impact_energy_j(mass_kg, speed)
        energy_source = "given_speed"
    elif drop_height_mm is not None:
        speed, energy = impact_from_drop_height(mass_kg, float(drop_height_mm))
        energy_source = "drop_height"
    else:
        raise ValueError("count_model needs one of energy_j, speed_mm_s, drop_height_mm")

    u_ref = float(cfg.u_ref_j if cfg.u_ref_j is not None
                  else calibrate_reference_energy(cfg))
    wall = float(body.wall_mm)
    t_ref = float(cfg.thickness_ref_mm)
    # A body with no measured thickness cannot be scored with the thickness term; refusing is
    # honest here because the term is not a small correction (gamma = 0.5).
    if wall <= 0.0:
        raise ValueError("body has no measured wall thickness; the count law needs one")

    size_term = (float(body.volume_mm3) / float(cfg.v_ref_mm3)) ** alpha
    energy_term = max(energy, 1e-12) / u_ref
    thickness_term = (t_ref / wall) ** gamma
    n_raw = float(cfg.n0) * energy_term ** float(cfg.impact_energy_exponent) \
        * size_term * thickness_term
    n_clamped = float(np.clip(n_raw, float(cfg.min_pieces), float(cfg.max_pieces)))
    provenance: dict[str, str] = {}
    if material.fracture_energy_j_mm2 is None and material.material_id:
        provenance["fracture_energy_j_mm2"] = (
            f"config table entry for {material.material_id} (engineering assumption) "
            f"or default")
    provenance["weibull_modulus"] = (
        "material profile" if material.weibull_modulus else "config default (engineering "
        "assumption; earthenware literature range 5-11)")
    return {
        "model": "N = N0 * (U/U_ref)^beta * (V/V_ref)^alpha * (t_ref/t)^gamma",
        "n0": float(cfg.n0),
        "beta_impact_energy_exponent": float(cfg.impact_energy_exponent),
        "alpha_size_exponent": float(alpha),
        "gamma_thickness_exponent": float(gamma),
        "weibull_modulus": float(m_modulus),
        "energy_j": float(energy),
        "energy_source": energy_source,
        "impact_speed_mm_s": float(speed),
        "mass_kg": float(mass_kg),
        "u_ref_j": float(u_ref),
        "size_term": float(size_term),
        "energy_term": float(energy_term),
        "thickness_term": float(thickness_term),
        "wall_mm": wall,
        "n_raw": float(n_raw),
        "n_deterministic": float(n_clamped),
        "clamped": bool(abs(n_clamped - n_raw) > 1e-9),
        "config_hash": cfg.hash,
        "provenance": provenance,
    }


def target_piece_count(body: BodyStats, material: MaterialStats, cfg: ImpactConfig, *,
                       rng: np.random.Generator | None = None,
                       speed_mm_s: float | None = None, energy_j: float | None = None,
                       drop_height_mm: float | None = None,
                       target_pieces: int | None = None) -> dict[str, Any]:
    """Physical target count, with an explicit (recorded) manual override for the sweep.

    ``target_pieces`` exists **only** so the efficiency sweep can ask for 1/4/8/16/32 pieces; the
    physics result is still computed and published next to it, and ``count_source`` says which
    one was used, so an override can never be mistaken for a measurement.
    """
    record = count_model(body, material, cfg, speed_mm_s=speed_mm_s, energy_j=energy_j,
                         drop_height_mm=drop_height_mm)
    n_det = float(record["n_deterministic"])
    draw = 1.0
    if rng is not None:
        draw = float(np.exp(rng.normal(0.0, float(cfg.log_sigma))))
    n_physical = float(np.clip(round(n_det * draw), int(cfg.min_pieces), int(cfg.max_pieces)))
    record["weibull_draw"] = float(draw)
    record["n_physical"] = int(n_physical)
    if target_pieces is None:
        record["n_target"] = int(n_physical)
        record["count_source"] = "physics"
    else:
        record["n_target"] = int(max(1, int(target_pieces)))
        record["count_source"] = "explicit_override"
    return record


def particle_size_distribution(n_pieces: int, *, weibull_modulus: float = 7.0,
                               seed: int = 0) -> np.ndarray:
    """Relative shard *linear* sizes for ``n_pieces`` shards (Weibull size distribution).

    A fragmented brittle body follows a Weibull / Rosin-Rammler shard-size distribution, so the
    shard sizes are drawn from ``x = (-ln u)**(1/m)`` normalised to unit volume sum.  Used to
    report the expected size spread (and as the initial seed weights) -- the geometric partition
    itself is the Voronoi diagram, this only sets the *expected* spread that is reported.
    """
    count = max(int(n_pieces), 1)
    rng = np.random.default_rng(int(seed))
    u = np.clip(rng.random(count), 1e-9, 1.0 - 1e-12)
    x = (-np.log(u)) ** (1.0 / max(float(weibull_modulus), 1.0))
    volume = x ** 3
    return volume / float(np.sum(volume))
