# A finite sourced pigment panel on a curved bowl

Root derivation, 2026-10-16. This specifies an appearance design, not an original
historical layout or an inverse reconstruction of pigment before firing.

Let the outer meridian have arclength `s`, radius `r(s)>0`, and azimuth `theta`.
Its metric is `dell^2 = ds^2 + r(s)^2 dtheta^2`. The implementation currently
uses the recorded finite-polyline arclength of the actual CAD-derived chart.

For a panel centered at `(s0,theta0)`, define

`X = r(s) * wrap_to_minus_pi_pi(theta-theta0)` and `Y = s-s0`.

Map a retained image crop into `|X| <= W/2, |Y| <= H/2`; set loading to zero
outside this finite panel. Require `W < 2*pi*min_panel_radius`, a positive-radius
domain, a meridian halo around its support, and explicit crop orientation. A
partial photographed motif is a partial panel, never an automatically repeated
complete circumferential historical motif.

Rows have the stated physical arc width `W`. Differentiating gives

`r dtheta = dX - (X r'(s)/r(s)) dY`.

Consequently the panel-coordinate metric is

`dell^2 = (dX-a dY)^2 + dY^2`, where `a=X*r'/r`.

Its determinant is one, so `dA=dX*dY` within a smooth unwrap branch: the mapping
preserves area but shears the image. It is not an isometry. Report a sampled
`max(abs(a))` over the actual panel, with the finite-polyline derivative convention.
This distinguishes controlled design distortion from an unmeasured source UV.

Evolve the sampled scalar loading on the original `(s,theta)` surface using the
metric finite-volume operator in `SURFACE_PIGMENT_MATH.md`. Do not diffuse on the
flat source bitmap and then claim curvature-aware spreading. With bound/mobile
fraction `m`, use `(1-m)*c0 + exp(t*A^-1*L)*(m*c0)`. Both fractions retain the
same area-weighted total apart from recorded numerical error.

The source mask measures blue chroma in an already-fired photograph. It preserves
tonal variation but also carries illumination, glaze, projection and photographic
effects. Any added spread and linear-RGB attenuation are effective appearance
controls. They do not identify kiln conditions, chemical species or material
fracture properties. The new bowl plus vase-derived panel is a synthetic design.

Keep panel scale, placement, crop/mask hashes, curve/chart hashes, grid, diffusion,
fraction, mass residuals and approximation limits in the generated receipt. The
mother geometry and original/rest coordinates stay unchanged.
