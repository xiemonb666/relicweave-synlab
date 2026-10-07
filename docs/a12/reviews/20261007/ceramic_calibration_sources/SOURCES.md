# Fired ceramic calibration source notes

Accessed 2026-10-07. These are research comparators and test-method references. They do not calibrate a ShardForge, PG-Frag, VesselForge, or RelicWeave material card.

## S1 — Experimental low-calcareous pottery clay (primary study)

N. S. Müller, G. Vekinis, P. M. Day, and V. Kilikoglou, “The influence of microstructure and texture on the mechanical properties of rock tempered archaeological ceramics,” *Journal of the European Ceramic Society* 35 (2015), 831–843. [DOI](https://doi.org/10.1016/j.jeurceramsoc.2014.09.025) · [Author PDF](https://ltt.arizona.edu/sites/ltt.lab.arizona.edu/files/2015%20Mueller%20et%20al%20Mechanical%20of%20rock%20tempered_J%20Eur%20Cer%20Soc.pdf).

The closest controlled earthenware analogue is the untempered, low-calcareous Kalami clay briquette fired at 1050 °C. It is an experimental body, not an excavated vessel shard. The raw clay has `<0.5% CaO`; the `<30 μm` clay fraction was moulded at about `0.02 MPa`, ambient-dried for more than ten days, and fired in air at `200 °C/h` with a one-hour soak. Fired bars were about `10 × 10 × 70 mm` (paper pp. 832–834).

| Field | Published evidence for that condition | Test / spread / limit |
|---|---|---|
| Porosity | Total porosity about `11%`, mainly closed | Water immersion on companion pieces; porosity uncertainty about `±2%`. This is not a fired bulk-density value (pp. 834–835). |
| Density, ρ | Fired bulk density: **not numerically reported** | `2.77 ± 0.05 g/mL` is an estimated true density of the *raw* Kalami clay from mineral phases, not fired bulk density. Do not substitute it. |
| Young’s modulus, E | `68.4 ± 7.5 GPa` | Mean of five compliance-corrected bending load–displacement determinations, calibrated against a known-E bar; SD reported (Table 1, p. 839). This is a static bending modulus. |
| Poisson ratio, ν | **Not reported** | No value or method. |
| Flexural strength | TRS about `70 MPa` | Three-point bend, approximately `10 × 10 × 70 mm`, crosshead `109 μm/min`, `n=5`; visible macroscopic flaw failures were excluded. Support span and numerical dispersion are not reported (pp. 834–837). This is flaw-sensitive flexural strength, not direct tensile strength `f_t`. |
| Mode-I toughness | `K_Ic,eff ≈ 1.2 MPa·m^1/2` | Four-point bending of pre-notched bars, notch depth `1 ± 0.1 mm`, `0.15 mm` diamond blade, `54 μm/min`, `n=3`; finite-notch correction at peak load. It is the authors’ effective toughness, not an ASTM C1421 result. Scatter is not numerically tabulated (pp. 834–838). |
| Fracture energy | `G_Ic,eff ≈ 21 J/m²`, **derived here** as `K²/E` from the rounded `1.2 MPa·m^1/2` and `68.4 GPa` values | The paper links `K_Ic = √(E G_Ic)` and says high-fired `G_Ic,eff` scatter is very high, but gives no numerical SD for this condition. This is not an independent direct `G_c` measurement. Stable-tail `G_t` is not reported for this brittle untempered condition. |
| Moisture / test state | Briquettes ambient-dried before firing; tests follow firing | Ambient temperature/humidity were not quantified; residual moisture at test was not measured or reported. |

This paper demonstrates why clay type, firing, and temper must be material-state fields: the same untempered Kalami clay has `E = 5.5 ± 0.8 GPa` and about `32 ± 2%` total porosity at 850 °C, versus `68.4 ± 7.5 GPa` and about `11%` porosity at 1050 °C. Its 1050 °C toughness must not be assigned to the 850 °C condition.

## S2 — Fast-fired porcelain stoneware (primary study)

J. Martín-Márquez, J. M. Rincón, and M. Romero, “Effect of microstructure on mechanical properties of porcelain stoneware,” *Journal of the European Ceramic Society* 30 (2010), 3063–3069. [DOI](https://doi.org/10.1016/j.jeurceramsoc.2010.07.015) · [Repository full text](https://files.core.ac.uk/download/pdf/45451165.pdf).

The reference industrial tile body is `50 wt%` kaolinitic clay, `40 wt%` feldspar, and `10 wt%` quartz; the powder was pressed with forming water, then oven-dried at `110 °C`. Fast firing spans `1200–1300 °C` with about 30 minutes to peak, 15-minute soak, and furnace cooling at `50 °C/min`. The firing and production history is unlike an unknown archaeological vessel body.

| Field | Published evidence | Test / spread / limit |
|---|---|---|
| Porosity / density | Open and closed porosity, bulk density `B`, and absolute density `AD` were measured; exact values are plotted against firing temperature, not tabulated in the article text | `B` and open porosity per ASTM C373-88; `AD` per ASTM C329-88; total porosity computed as `1 − B/AD`. Do not copy a plot estimate into a card without a documented digitization. |
| Young’s modulus, E | At `1200, 1230, 1250, 1260, 1270, 1280, 1300 °C`: `48, 49, 61, 61, 61, 57, 65 GPa` | Resonance-frequency method (Grindosonic). Table gives no SD or replicate count. These are dynamic values. |
| Poisson ratio, ν | **Not reported** | No value or method. |
| Flexural strength | Variation with firing temperature is shown in Fig. 1; numerical per-temperature values and dispersion are not tabulated in the retrieved article text | UNE-EN 843-1; 3-point bend; `50 × 10 × 8 mm`, span `36 mm`, crosshead `3 mm/min`, `n=10`. This is flexural strength, not direct `f_t`. |
| Toughness | Authors’ indentation-derived `K_Ic` at the same firing temperatures: `1.3, 1.2, 1.3, 1.2, 1.4, 1.3, 1.4 MPa·m^1/2` | Vickers indentation, `1000 gf`, 15 s; polished surface; average 10 measurements. No SD is tabulated. This is not a sharp precracked-beam mode-I result and does not supply a calibrated `G_c`. |
| Moisture / test state | Forming water was used; bodies were oven-dried at `110 °C` before firing and cooled after firing | Residual moisture, relative humidity, equilibration, and test moisture content are not specified. |

Do not combine this paper’s indentation toughness with a separately sourced modulus, porosity, or strength to form a synthetic “porcelain” card. Its tile body and test methods are useful method comparators only.

## S3 — Official ceramic fracture-toughness test method

ASTM C1421-18(2025), *Standard Test Methods for Determination of Fracture Toughness of Advanced Ceramics at Ambient Temperature*. [ASTM official page](https://store.astm.org/standards/c1421), active edition shown as `C1421-18(2025)` (ASTM DOI `10.1520/C1421-18R25`). It covers precracked beam, surface-crack-in-flexure, and chevron-notched beam methods using sharp cracks and SI units. Results can vary with crack-size method, environment, rate, and temperature. It does not provide pottery material values and its advanced-ceramic scope must be checked before applying to porous or tempered traditional ceramics.

## S4 — Official elastic-modulus / Poisson-ratio test method

ASTM C1259-21(2026), *Standard Test Method for Dynamic Young’s Modulus, Shear Modulus, and Poisson’s Ratio for Advanced Ceramics by Impulse Excitation of Vibration*. [ASTM official page](https://store.astm.org/c1259-21r26.html), active version shown as `C1259-21(2026)`. It determines dynamic `E` and shear modulus from resonant flexural/torsional modes and computes `ν`. This yields dynamic elastic properties; compare against a static modulus from the loading curve before selecting solver inputs. It supplies no values for an earthenware, stoneware, or porcelain body.

## Evidence boundary

The local earlier note [CERAMIC_FRACTURE_BENCHMARK_20261004.md](../../../pgfrag/docs/references/CERAMIC_FRACTURE_BENCHMARK_20261004.md) already covers Müller et al. and Kilikoglou et al. fracture-surface context; this pass adds no new claim from Kilikoglou. The two papers above show how different preparation and measurement methods change the meaning of each number. Neither supplies a complete, lot-matched `E, ρ, ν, f_t, G_c` card for the project’s actual fragments. Literature values remain prior context, never production parameters or online inference inputs.
