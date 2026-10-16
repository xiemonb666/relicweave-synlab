# Blue-white underglaze spread prototype

This experiment adds a scalar pigment-loading field to a surface-of-revolution chart. It
uses true meridian arclength, a variable radius profile, positive annular cell areas, a
periodic azimuth, and no-flux ends on the selected physical band. The sparse finite-volume
graph shares one positive conductance per face; SciPy `expm_multiply` advances the
conservative mass system. Callers may provide profile-integrated cell areas; the demo
computes them from an 80,001-sample meridian evaluator. The library default remains
explicitly labeled midpoint quadrature.

The motif seed comes from Met object 50899, *Vase with dragon*. The comparison includes
the continuous cobalt-chroma projection and a binary strong-support mask. Both are
derived from an already-fired O2 photograph. They preserve its projection and photo/glaze
effects; neither describes recovered pre-firing brush placement or pigment density.
Additional spread is therefore a stylized post-firing appearance transformation, with a
known double-diffusion risk.

The output compares a zero-spread control with two fixed effective diffusion settings:
`(K_s, K_theta) = (0.4, 2.0) mm²` and `(1.6, 8.0) mm²`. The settings show sensitivity;
they are not fitted to a measured bleed width or mapped to kiln temperature or time.
Because angular conductance includes the local radius, the same azimuthal coefficient
acts over a changing physical distance around the illustrative bulb-and-neck profile.
The image shows the whole dragon projection and a local density crop around the dragon
head. A 22 mm blank meridian halo separates the motif from each reflecting physical band
end. The azimuth is periodic.

The appearance map returns linear RGB using a dimensionless Beer-like attenuation proxy.
Its cobalt coefficients roughly align full density with the project's existing
cobalt-white palette as an art-direction anchor, not optical calibration. Display pixels
receive only the standard linear-RGB to sRGB transfer conversion. Geometry, height,
thickness, roughness, and mechanics are not changed.

`receipt.json` contains source hashes, effective diffusion values, profile and cell-area
details, solver receipts, weighted mass drift, and claim limits. `motif_spread_fields.npz`
stores every initial/spread density and linear-RGB array. Recreate these files from the
workspace root with:

```powershell
& '.\relicweave-synlab\.venv\Scripts\python.exe' '.\experiments\continuation_20261015\underglaze\run_underglaze_demo.py'
```
