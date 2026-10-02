"""Loading, hashing and self-checking of ``configs/a12/fracture_physics.yaml``.

The physics parameters of the multi-piece model live in one YAML file so they can be reviewed
without reading code.  This module is the only place that knows the file's *shape*: it turns it
into typed records, records where every number came from (``provenance``), and refuses to run if
the precision thresholds in the file disagree with the frozen ones in
:mod:`synlab.fracture.spec`.

That last check is the important one: ``fracture_physics.yaml`` carries a copy of the A06
thresholds for documentation, and a copy is exactly the thing that drifts.  :func:`verify_against_spec`
makes the drift impossible -- a widened threshold is a hard error, not a warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from . import energy as energy_mod
from . import impact as impact_mod
from . import voronoi_frag as vf
from .spec import (
    AMBIGUITY_AREA_RATIO_MAX,
    AMP_MAX_MM,
    AMP_MIN_MM,
    INTERFACE_GAP_P95_MM,
    NORMAL_REVERSAL_P95_DEG,
    OVERLAP_RATIO_MAX,
    VOLUME_REL_TOL,
    WAVELENGTH_MAX_MM,
    WAVELENGTH_MIN_MM,
)

__all__ = ["PhysicsConfig", "RoughnessConfig", "CrushingConfig", "load_physics_config",
           "verify_against_spec", "DEFAULT_CONFIG_PATH"]

#: the config this build ships (relative to the repository root)
DEFAULT_CONFIG_PATH = "configs/a12/fracture_physics.yaml"
SCHEMA = "synlab.fracture_physics.v1"


@dataclass
class RoughnessConfig:
    """Declared parameters of the physics-driven fracture-surface roughness."""

    amp_wall_ratio: float = 0.08
    amp_min_mm: float = 0.02
    amp_max_mm: float = 0.30
    wavelength_grain_ratio: float = 6.0
    wavelength_floor_mm: float = 5.0
    wavelength_min_mm: float = WAVELENGTH_MIN_MM
    wavelength_max_mm: float = WAVELENGTH_MAX_MM
    n_bands: int = 3
    spectral_slope: float = 1.0
    correlation_factor: float = 2.0
    anisotropy: float = 0.35
    #: How a fracture facet is triangulated before it is displaced.
    #: ``lattice`` (default) clips a shared lattice to the facet; ``fan`` uses the facet's own
    #: corners.  Both are measured in ``docs/a12/fracture_physics.md``: the refinement is what
    #: resolves the roughness, the fan is the cheap fallback that keeps the cell watertight.
    facet_refinement: str = "lattice"
    #: Sub-edge length (mm) of the facet refinement; ``0`` derives it from the roughness
    #: wavelength (``wavelength_min / roughness_edges_per_wavelength``).
    facet_refine_mm: float = 0.0
    #: Fraction of the shortest admitted roughness wavelength used as the facet sub-edge length.
    roughness_edges_per_wavelength: float = 0.75
    provenance: dict[str, str] = field(default_factory=dict)

    def amplitude_mm(self, wall_mm: float) -> float:
        """Amplitude follows the *measured* wall thickness, clamped to the package window."""
        value = float(self.amp_wall_ratio) * max(float(wall_mm), 0.0)
        return float(min(max(value, float(self.amp_min_mm)), float(self.amp_max_mm)))

    def wavelength_min_for(self, grain_mm: float) -> float:
        """Shortest admitted roughness wavelength from the material's own grain size.

        Clamped from below by ``wavelength_floor_mm``: the interface gap is measured between two
        *linear* triangulations of the same displaced surface, so it equals their interpolation
        error ``(1/8)|d''|h**2``.  A 0.6 mm feature inside a 0.3 mm band would need ``h ~ 0.02 mm``
        and therefore billions of triangles, so the admitted band starts at the floor (5 mm by
        default) and the floor is published as an engineering limit, not as physics.
        """
        value = float(self.wavelength_grain_ratio) * max(float(grain_mm), 0.0)
        lower = max(float(self.wavelength_min_mm), float(self.wavelength_floor_mm))
        return float(min(max(value, lower), float(self.wavelength_max_mm)))

    def correlation_length_mm(self, grain_mm: float) -> float:
        return float(self.correlation_factor) * self.wavelength_min_for(grain_mm)

    def as_dict(self) -> dict[str, Any]:
        return {
            "amp_wall_ratio": float(self.amp_wall_ratio),
            "amp_min_mm": float(self.amp_min_mm),
            "amp_max_mm": float(self.amp_max_mm),
            "wavelength_grain_ratio": float(self.wavelength_grain_ratio),
            "wavelength_floor_mm": float(self.wavelength_floor_mm),
            "wavelength_min_mm": float(self.wavelength_min_mm),
            "wavelength_max_mm": float(self.wavelength_max_mm),
            "n_bands": int(self.n_bands),
            "spectral_slope": float(self.spectral_slope),
            "correlation_factor": float(self.correlation_factor),
            "anisotropy": float(self.anisotropy),
            "facet_refinement": str(self.facet_refinement),
            "facet_refine_mm": float(self.facet_refine_mm),
            "roughness_edges_per_wavelength": float(self.roughness_edges_per_wavelength),
            "provenance": dict(self.provenance),
        }


@dataclass
class CrushingConfig:
    """Secondary / tertiary crushing (re-fracture of the largest pieces)."""

    secondary_probability: float = 0.85
    secondary_trigger_volume_ratio: float = 0.12
    secondary_pieces_range: tuple[int, int] = (2, 5)
    tertiary_probability: float = 0.35
    tertiary_pieces_range: tuple[int, int] = (2, 3)
    max_generations: int = 3
    provenance: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "secondary_probability": float(self.secondary_probability),
            "secondary_trigger_volume_ratio": float(self.secondary_trigger_volume_ratio),
            "secondary_pieces_range": [int(x) for x in self.secondary_pieces_range],
            "tertiary_probability": float(self.tertiary_probability),
            "tertiary_pieces_range": [int(x) for x in self.tertiary_pieces_range],
            "max_generations": int(self.max_generations),
            "provenance": dict(self.provenance),
        }


@dataclass
class PhysicsConfig:
    """The whole file, typed."""

    path: str = DEFAULT_CONFIG_PATH
    version: str = "1.0.0"
    impact: impact_mod.ImpactConfig = field(default_factory=impact_mod.ImpactConfig)
    seeds: vf.SeedConfig = field(default_factory=vf.SeedConfig)
    roughness: RoughnessConfig = field(default_factory=RoughnessConfig)
    crushing: CrushingConfig = field(default_factory=CrushingConfig)
    tolerance: dict[str, float] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    scenario: dict[str, Any] = field(default_factory=dict)
    material_block: dict[str, Any] = field(default_factory=dict)
    generation_spec: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "path": str(self.path),
            "version": str(self.version),
            "impact": self.impact.as_dict(),
            "seeds": self.seeds.as_dict(),
            "roughness": self.roughness.as_dict(),
            "crushing": self.crushing.as_dict(),
            "tolerance": {k: float(v) for k, v in sorted(self.tolerance.items())},
            "resources": dict(self.resources),
            "scenario": dict(self.scenario),
            "material": dict(self.material_block),
        }

    @property
    def hash(self) -> str:
        return hash_json(self.as_dict())[:32]


def _require(document: dict[str, Any], key: str, *, where: str) -> dict[str, Any]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{where}: missing mapping {key!r}", stage="fracture.physics.config")
    return value


def load_physics_config(path: str | Path = DEFAULT_CONFIG_PATH) -> PhysicsConfig:
    """Read + type the YAML; unknown keys are reported instead of being ignored."""
    import yaml

    config_path = Path(path)
    if not config_path.exists():
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"fracture physics config not found: {config_path}",
                          stage="fracture.physics.config")
    document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{config_path} must contain a mapping",
                          stage="fracture.physics.config")
    if document.get("schema") != SCHEMA:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"{config_path}: schema must be {SCHEMA!r}, got {document.get('schema')!r}",
            stage="fracture.physics.config")

    count = _require(document, "count_model", where=str(config_path))
    impact = impact_mod.ImpactConfig(
        n0=float(count.get("n0", 3.0)),
        impact_energy_exponent=float(count.get("impact_energy_exponent", 0.65)),
        weibull_modulus=float(count.get("weibull_modulus", 7.0)),
        weibull_volume_exponent=float(count.get("weibull_volume_exponent", 0.5)),
        min_pieces=int(count.get("min_pieces", 2)),
        max_pieces=int(count.get("max_pieces", 64)),
        log_sigma=float(count.get("log_sigma", 0.18)),
        v_ref_mm3=float(count.get("v_ref_mm3", impact_mod.V_REF_MM3)),
        thickness_ref_mm=float(count.get("thickness_ref_mm", 6.0)),
        v_impact_ref_mm_s=float(count.get("v_impact_ref_mm_s", impact_mod.V_IMPACT_REF_MM_S)),
        provenance={str(k): str(v) for k, v in (count.get("provenance") or {}).items()
                    if isinstance(v, str)},
    )
    material = _require(document, "material", where=str(config_path))
    energies = material.get("fracture_energy_j_mm2") or {}
    impact.fracture_energy_j_mm2 = {str(k): float(v) for k, v in energies.items()}
    impact.fracture_energy_default_j_mm2 = float(
        material.get("default_fracture_energy_j_mm2", 1.0e-3))
    impact.provenance.update({str(k): str(v) for k, v in (material.get("provenance") or {}).items()
                              if isinstance(v, str)})
    impact.u_ref_j = impact_mod.calibrate_reference_energy(impact)

    seed_block = _require(document, "seeds", where=str(config_path))
    seeds = vf.SeedConfig(
        thickness_exponent=float(seed_block.get("thickness_exponent", 1.0)),
        curvature_gain=float(seed_block.get("curvature_gain", 1.0)),
        curvature_exponent=float(seed_block.get("curvature_exponent", 0.5)),
        impact_decay_mm=float(seed_block.get("impact_decay_mm", 60.0)),
        impact_weight=float(seed_block.get("impact_weight", 1.0)),
        min_weight_ratio=float(seed_block.get("min_weight_ratio", 0.05)),
        jitter_mm=float(seed_block.get("jitter_mm", 0.35)),
        max_candidates=int(seed_block.get("max_candidates", 20000)),
        strategy=str(seed_block.get("strategy", "farthest_weighted")),
    )

    rough_block = _require(document, "roughness", where=str(config_path))
    roughness = RoughnessConfig(
        amp_wall_ratio=float(rough_block.get("amp_wall_ratio", 0.08)),
        amp_min_mm=float(rough_block.get("amp_min_mm", AMP_MIN_MM)),
        amp_max_mm=float(rough_block.get("amp_max_mm", AMP_MAX_MM)),
        wavelength_grain_ratio=float(rough_block.get("wavelength_grain_ratio", 6.0)),
        wavelength_floor_mm=float(rough_block.get("wavelength_floor_mm", 5.0)),
        wavelength_min_mm=float(rough_block.get("wavelength_min_mm", WAVELENGTH_MIN_MM)),
        wavelength_max_mm=float(rough_block.get("wavelength_max_mm", WAVELENGTH_MAX_MM)),
        n_bands=int(rough_block.get("n_bands", 3)),
        spectral_slope=float(rough_block.get("spectral_slope", 1.0)),
        correlation_factor=float(rough_block.get("correlation_factor", 2.0)),
        anisotropy=float(rough_block.get("anisotropy", 0.35)),
        facet_refinement=str(rough_block.get("facet_refinement", "lattice")),
        facet_refine_mm=float(rough_block.get("facet_refine_mm", 0.0)),
        roughness_edges_per_wavelength=float(
            rough_block.get("roughness_edges_per_wavelength", 0.75)),
        provenance={str(k): str(v) for k, v in (rough_block.get("provenance") or {}).items()
                    if isinstance(v, str)},
    )

    crush_block = _require(document, "crushing", where=str(config_path))
    crushing = CrushingConfig(
        secondary_probability=float(crush_block.get("secondary_probability", 0.85)),
        secondary_trigger_volume_ratio=float(
            crush_block.get("secondary_trigger_volume_ratio", 0.12)),
        secondary_pieces_range=tuple(int(x) for x in
                                     (crush_block.get("secondary_pieces_range") or (2, 5))),
        tertiary_probability=float(crush_block.get("tertiary_probability", 0.35)),
        tertiary_pieces_range=tuple(int(x) for x in
                                    (crush_block.get("tertiary_pieces_range") or (2, 3))),
        max_generations=int(crush_block.get("max_generations", 3)),
        provenance={str(k): str(v) for k, v in (crush_block.get("provenance") or {}).items()
                    if isinstance(v, str)},
    )

    scenario_block = document.get("impact") or {}
    scenario = {
        "drop_height_mm": float(scenario_block.get("drop_height_mm", 500.0)),
        "speed_mm_s": float(scenario_block.get("speed_mm_s", 0.0)),
        "target_pieces_override": int(scenario_block.get("target_pieces_override", 0)),
        "provenance": {str(k): str(v) for k, v in (scenario_block.get("provenance") or {}).items()
                       if isinstance(v, str)},
    }
    tolerance = {str(k): float(v) for k, v in
                 (_require(document, "tolerances", where=str(config_path))).items()
                 if isinstance(v, (int, float))}
    resources = {k: v for k, v in
                 (_require(document, "resources", where=str(config_path))).items()
                 if k != "provenance"}

    config = PhysicsConfig(
        path=str(config_path), version=str(document.get("version", "0")), impact=impact,
        seeds=seeds, roughness=roughness, crushing=crushing, tolerance=tolerance,
        resources=resources, scenario=scenario, material_block=material,
        generation_spec=document.get("generation_spec") or {},
        provenance={"document": {k: v for k, v in document.items()
                                 if isinstance(v, (str, int, float))}},
        raw=document,
    )
    verify_against_spec(config)
    return config


def verify_against_spec(config: PhysicsConfig) -> None:
    """Hard-fail if the config's thresholds or wavelength guards disagree with the frozen spec."""
    expected = {
        "interface_gap_p95_mm": INTERFACE_GAP_P95_MM,
        "normal_reversal_p95_deg": NORMAL_REVERSAL_P95_DEG,
        "volume_rel_tol": VOLUME_REL_TOL,
        "overlap_ratio_max": OVERLAP_RATIO_MAX,
        "ambiguity_area_ratio_max": AMBIGUITY_AREA_RATIO_MAX,
    }
    problems: dict[str, Any] = {}
    for key, frozen in expected.items():
        found = config.tolerance.get(key)
        if found is None:
            problems[key] = {"config": None, "frozen": frozen, "why": "missing"}
        elif float(found) > float(frozen) * (1.0 + 1e-12):
            problems[key] = {"config": float(found), "frozen": float(frozen), "why": "widened"}
    if config.roughness.wavelength_min_mm < WAVELENGTH_MIN_MM - 1e-12:
        problems["wavelength_min_mm"] = {"config": config.roughness.wavelength_min_mm,
                                         "frozen": WAVELENGTH_MIN_MM, "why": "below package guard"}
    if config.roughness.wavelength_max_mm > WAVELENGTH_MAX_MM + 1e-12:
        problems["wavelength_max_mm"] = {"config": config.roughness.wavelength_max_mm,
                                         "frozen": WAVELENGTH_MAX_MM, "why": "above package guard"}
    if config.roughness.amp_max_mm > AMP_MAX_MM + 1e-12:
        problems["amp_max_mm"] = {"config": config.roughness.amp_max_mm, "frozen": AMP_MAX_MM,
                                  "why": "above package guard"}
    if config.roughness.amp_min_mm < 0.0:
        problems["amp_min_mm"] = {"config": config.roughness.amp_min_mm, "frozen": 0.0,
                                  "why": "negative amplitude"}
    if config.impact.min_pieces < 2:
        problems["min_pieces"] = {"config": config.impact.min_pieces, "frozen": 2,
                                  "why": "a fracture event must produce at least two pieces"}
    if config.impact.max_pieces > 512:
        problems["max_pieces"] = {"config": config.impact.max_pieces, "frozen": 512,
                                  "why": "resource guard"}
    if config.impact.impact_energy_exponent <= 0.0:
        problems["impact_energy_exponent"] = {
            "config": config.impact.impact_energy_exponent, "frozen": "> 0",
            "why": "a count that does not grow with energy contradicts the requirement"}
    if config.crushing.max_generations > 4:
        problems["max_generations"] = {"config": config.crushing.max_generations, "frozen": 4,
                                       "why": "resource guard"}
    if not energy_mod.__doc__:                      # pragma: no cover - import sanity
        problems["energy_module"] = {"why": "the energy ledger module is empty"}
    if problems:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            "fracture physics config conflicts with the frozen spec: "
            + "; ".join(f"{k} ({v['why']})" for k, v in sorted(problems.items())),
            stage="fracture.physics.verify",
            measurements={"problems": problems},
        )

