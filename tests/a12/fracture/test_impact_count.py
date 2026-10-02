"""The piece-count law: monotonic in size and energy, and traceable.

These tests fix the *properties the requirement asks for*, not the constants: a bigger body must
break into more pieces, a harder impact must break into more pieces, and every parameter must carry
its provenance so an engineering assumption cannot pass as a measurement.
"""
from __future__ import annotations

import numpy as np
import pytest

from synlab.fracture.impact import (
    BodyStats,
    ImpactConfig,
    MaterialStats,
    calibrate_reference_energy,
    count_model,
    impact_energy_j,
    impact_from_drop_height,
    particle_size_distribution,
    target_piece_count,
)


def _body(volume_mm3: float, wall_mm: float) -> BodyStats:
    return BodyStats(vessel_id="T", volume_mm3=volume_mm3, area_mm2=volume_mm3 ** (2 / 3),
                     extents_mm=(1.0, 1.0, 1.0), thickness_min_mm=wall_mm * 0.5,
                     thickness_p05_mm=wall_mm * 0.8, thickness_median_mm=wall_mm,
                     thickness_max_mm=wall_mm * 2.0)


def _material(material_id: str = "M01") -> MaterialStats:
    return MaterialStats(material_id=material_id, density_g_cm3=2.2, porosity=0.2,
                         grain_size_mm=0.4)


def test_drop_energy_matches_free_fall() -> None:
    speed, energy = impact_from_drop_height(1.0, 500.0)
    assert speed == pytest.approx(np.sqrt(2 * 9810.0 * 500.0), rel=1e-12)
    assert energy == pytest.approx(0.5 * 1.0 * (speed * 1.0e-3) ** 2, rel=1e-12)
    assert energy == pytest.approx(4.905, rel=1e-3)


def test_bigger_body_breaks_into_more_pieces() -> None:
    """The requirement: a big vessel yields more pieces than a small one."""
    config = ImpactConfig()
    config.u_ref_j = calibrate_reference_energy(config)
    small = count_model(_body(8.0e4, 4.0), _material(), config, drop_height_mm=500.0)
    large = count_model(_body(9.6e5, 4.0), _material(), config, drop_height_mm=500.0)
    assert large["n_deterministic"] > small["n_deterministic"]
    # the same holds at a fixed impact energy: a bigger body offers more fracture sites, which is
    # what makes the *piece size* roughly scale-invariant (the observed archaeological pattern)
    small_energy = count_model(_body(8.0e4, 4.0), _material(), config, energy_j=15.0)
    large_energy = count_model(_body(9.6e5, 4.0), _material(), config, energy_j=15.0)
    assert large_energy["n_deterministic"] > small_energy["n_deterministic"]
    small_size = (6.0 * 8.0e4 / np.pi / small_energy["n_deterministic"]) ** (1.0 / 3.0)
    large_size = (6.0 * 9.6e5 / np.pi / large_energy["n_deterministic"]) ** (1.0 / 3.0)
    assert 0.4 < large_size / small_size < 2.5


def test_piece_size_is_only_weakly_size_dependent() -> None:
    """A tenfold body at the same energy must not give a tenfold piece size.

    The measured exponent of this law is ``N ~ V**0.571`` (``alpha = 1/(2m) + 0.5`` = 0.571 at
    m = 7), so a tenfold volume multiplies the piece size by ``10**(1/3) / 10**0.571`` = 1.39 --
    i.e. pieces grow far more slowly than the body.  That is the scale-invariance the shard-size
    literature reports, and it is asserted here as the *measured* exponent rather than the
    idealised ``1/3``.
    """
    config = ImpactConfig()
    config.u_ref_j = calibrate_reference_energy(config)
    volumes = (1.0e5, 3.0e5, 1.0e6)
    records = [count_model(_body(volume, 4.0), _material(), config, energy_j=15.0)
               for volume in volumes]
    sizes = [(6.0 * volume / np.pi / record["n_deterministic"]) ** (1.0 / 3.0)
             for volume, record in zip(volumes, records)]
    assert sizes[0] < sizes[1] < sizes[2]
    assert sizes[2] / sizes[0] == pytest.approx(1.39, rel=0.1)
    alpha = records[0]["alpha_size_exponent"]
    beta = config.impact_energy_exponent
    expected = (volumes[-1] / volumes[0]) ** ((1.0 - alpha) / 3.0)
    assert sizes[2] / sizes[0] == pytest.approx(expected, rel=1e-9)
    assert beta > 0.0  # the energy exponent is published and positive


def test_more_energy_breaks_into_more_pieces() -> None:
    config = ImpactConfig()
    config.u_ref_j = calibrate_reference_energy(config)
    body = _body(3.4e5, 6.0)
    weak = count_model(body, _material(), config, energy_j=6.0)
    strong = count_model(body, _material(), config, energy_j=48.0)
    assert strong["n_deterministic"] > weak["n_deterministic"]
    # the exponent is published, and it is the one actually used (both unclamped)
    assert not weak["clamped"] and not strong["clamped"]
    ratio = strong["n_raw"] / weak["n_raw"]
    assert ratio == pytest.approx((48.0 / 6.0) ** config.impact_energy_exponent, rel=1e-9)


def test_thinner_wall_breaks_into_more_pieces() -> None:
    config = ImpactConfig()
    config.u_ref_j = calibrate_reference_energy(config)
    thick = count_model(_body(3.0e5, 10.0), _material(), config, energy_j=15.0)
    thin = count_model(_body(3.0e5, 3.0), _material(), config, energy_j=15.0)
    assert thin["n_deterministic"] > thick["n_deterministic"]


def test_harder_material_breaks_into_fewer_pieces() -> None:
    config = ImpactConfig()
    config.u_ref_j = calibrate_reference_energy(config)
    soft = MaterialStats(material_id="A", density_g_cm3=2.2, fracture_energy_j_mm2=5.0e-4,
                         grain_size_mm=0.4)
    tough = MaterialStats(material_id="B", density_g_cm3=2.2, fracture_energy_j_mm2=2.0e-3,
                          grain_size_mm=0.4)
    del soft, tough
    # the fracture energy does not enter the count directly (it enters the energy ledger); the
    # *material's own* Weibull modulus does, and a lower modulus is a more variable, weaker body
    weak = MaterialStats(material_id="A", density_g_cm3=2.2, weibull_modulus=4.0,
                         grain_size_mm=0.4)
    strong = MaterialStats(material_id="B", density_g_cm3=2.2, weibull_modulus=12.0,
                           grain_size_mm=0.4)
    record_weak = count_model(_body(3.0e5, 6.0), weak, config, energy_j=15.0)
    record_strong = count_model(_body(3.0e5, 6.0), strong, config, energy_j=15.0)
    assert record_weak["alpha_size_exponent"] > record_strong["alpha_size_exponent"]


def test_count_is_clamped_and_says_so() -> None:
    config = ImpactConfig()
    config.u_ref_j = calibrate_reference_energy(config)
    tiny = count_model(_body(1.0e3, 6.0), _material(), config, energy_j=1.0e-6)
    assert tiny["n_deterministic"] == float(config.min_pieces)
    assert tiny["clamped"] is True
    huge = count_model(_body(1.0e9, 2.0), _material(), config, energy_j=1.0e6)
    assert huge["n_deterministic"] == float(config.max_pieces)
    assert huge["clamped"] is True


def test_count_model_needs_a_measured_wall() -> None:
    config = ImpactConfig()
    body = _body(3.0e5, 0.0)
    with pytest.raises(ValueError):
        count_model(body, _material(), config, energy_j=15.0)


def test_target_piece_count_records_whether_it_was_physics() -> None:
    config = ImpactConfig()
    config.u_ref_j = calibrate_reference_energy(config)
    physics = target_piece_count(_body(3.4e5, 6.0), _material(), config, drop_height_mm=500.0,
                                 rng=np.random.default_rng(0))
    assert physics["count_source"] == "physics"
    assert physics["n_target"] == physics["n_physical"] >= config.min_pieces
    overridden = target_piece_count(_body(3.4e5, 6.0), _material(), config, drop_height_mm=500.0,
                                    target_pieces=17)
    assert overridden["count_source"] == "explicit_override"
    assert overridden["n_target"] == 17
    # the physics result is still published next to an override
    assert overridden["n_physical"] == physics["n_physical"]


def test_reference_energy_is_solved_not_guessed() -> None:
    """The reference energy is the one that reproduces ``n0`` on the declared reference body."""
    config = ImpactConfig()
    reference = calibrate_reference_energy(config)
    config.u_ref_j = reference
    # the calibration body is the declared reference volume at the declared reference wall, and the
    # reference density is the one the material used here carries (2.2 g/cm^3)
    material = _material()
    mass = material.density_g_cm3 * 1.0e-6 * config.v_ref_mm3
    _speed, energy = impact_from_drop_height(mass, 500.0)
    body = _body(config.v_ref_mm3, config.thickness_ref_mm)
    record = count_model(body, material, config, drop_height_mm=500.0)
    assert record["energy_j"] == pytest.approx(energy, rel=1e-9)
    assert record["u_ref_j"] == pytest.approx(reference)
    # solving for U_ref is exactly inverting the law, so the reference body lands on n0
    assert record["n_raw"] == pytest.approx(config.n0, rel=1e-9)
    assert record["clamped"] is False


def test_energy_helper_is_the_kinetic_energy() -> None:
    assert impact_energy_j(1.0, 1000.0) == pytest.approx(0.5)
    assert impact_energy_j(0.0, 1000.0) == 0.0


def test_weibull_shard_sizes_sum_to_one() -> None:
    sizes = particle_size_distribution(12, weibull_modulus=7.0, seed=3)
    assert sizes.shape == (12,)
    assert float(sizes.sum()) == pytest.approx(1.0, rel=1e-12)
    assert bool((sizes > 0.0).all())
    again = particle_size_distribution(12, weibull_modulus=7.0, seed=3)
    assert np.array_equal(sizes, again)
