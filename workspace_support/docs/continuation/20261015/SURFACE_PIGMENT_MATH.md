# Effective pigment spread on a revolved surface

Root derivation with an independent Astra mathematical review, 2026-10-15.

This is an appearance surrogate for pigment spreading, not a calibrated chemical
or thermal reconstruction of porcelain firing. Cobalt/glaze interaction and
diffusion-related migration have experimental support, but this source does not
supply the coefficients of our surface model:
[Sun et al., 2026](https://pmc.ncbi.nlm.nih.gov/articles/PMC13257541/).

For a surface parameterized by azimuth theta and true meridian arc length s,
the metric is `ds^2 + r(s)^2 dtheta^2`. With diagonal diffusivity in those
directions the scalar diffusion equation is

`dc/dt = (1/r) d_s(r D_s d_s c) + (D_theta/r^2) d_theta_theta c`.

For uniform cell spacing, use positive cell areas
`A_i = delta_theta * integral_cell r(s) ds`; midpoint
`r_i * delta_s * delta_theta` is a declared quadrature approximation.
Each neighboring cell pair shares one symmetric nonnegative conductance:

`g_s = D_s_face * r_face * delta_theta / delta_s`

`g_theta = D_theta_face * delta_s / (r_i * delta_theta)`.

Use harmonic face diffusivity for heterogeneous coefficients, explicitly treating
zero diffusivity as zero conductance. Off-diagonal `L_ij = g_ij`, diagonal
`L_ii = -sum_j g_ij`. Therefore `L 1 = 0` and

`x^T L x = -sum_unordered_edges g_ij (x_i-x_j)^2 <= 0`.

Writing `A dc/dt = L c`, the symmetric operator
`H = A^(-1/2) L A^(-1/2)` gives

`c(t) = A^(-1/2) exp(t H) A^(1/2) c(0)`.

Reuse SciPy sparse exponential action. This conserves the discrete weighted
pigment total, preserves constant concentration and preserves nonnegativity
mathematically. Report numerical negative values and mass residuals before any
roundoff clipping; do not renormalize errors away. Use exactly N angular cells,
periodic angular adjacency and no-flux meridian ends. Leave blank halo around
motifs; the motif footprint itself is not a reflecting boundary. The initial
implementation excludes axis-touching bands explicitly.

With `D` in mm^2/time, `H` is 1/time. Alternatively expose integrated effective
diffusion `K = D*t` in mm^2 and exponentiate once, without another time factor.
A spatial K field is a fixed effective model, not arbitrary firing chronology.
For a cylindrical angular mode k, the discrete attenuation exponent is
`-4 K_theta sin(pi*k/N)^2 / (r^2 delta_theta^2)`.

Use normalized dimensionless pigment density and an explicitly effective
dimensionless absorption parameter for the first color mapping:

`linear_rgb = glaze_white_linear_rgb * exp(-tau_rgb * c)`.

Stronger red/green than blue absorption yields blue. This does not model complete
glaze scattering, spectral reflectance, pigment chemistry or measured optical
constants. A fired-photo-derived pigment proxy already includes original spread;
additional diffusion is a stylized variation, not recovered pre-firing deposition.

Required checks include zero/constant fields, discrete mass, nonnegativity,
cylinder Fourier attenuation, angular-roll equivariance, two half exposures vs
one full exposure, spread into blank cells, periodic seams and spatial refinement.
Original/rest-coordinate identity is retained through fragmentation.

