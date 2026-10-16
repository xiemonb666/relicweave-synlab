# Extrinsic cohesive insertion: recorded work and local tangent

Root derivation following the read-only Astra review, 2026-10-16. This concerns
the existing 96-T4 coupon, not the new vessel or a calibrated ceramic material.
The runtime wheel is 5.0.7-post1; the inspected official source is tagged v5.0.7.
Their provenance distinction remains explicit.

## What the existing trajectory already shows

The first insertion is at step 650, with zero native dissipated energy. At 651
it is positive. At 652 it becomes negative after the native solve. Astra
reconstructed it from saved quadrature-point vectors and actual areas:

`dW = sum_q A_q * (t_old+t_new)/2 dot (delta_new-delta_old)`

`R = sum_q A_q * t_new dot delta_new/2`, `D = cumulative_W - R`.

At 651, dW is +3.6823662360605864e-7 J and D is
+1.7262621338279380e-7 J. At 652, dW is -5.609791800005645e-5 J and D is
-5.5729681376450394e-5 J. The differences from the native values are below
7e-21 J. Twenty-two of twenty-four quadrature points have negative work
increments at 652. One point reverses shear direction and jumps from sub-nm
opening beyond complete separation in one step.

Thus the first negative getter is explained by the signed work of the recorded
vector path. This is not evidence of a harmless sign convention, an immediate
insertion-energy offset, or permission to clamp the value. The leading cause is
unresolved near-zero-opening directional stiffness. Force continuity, operative
mass after reassembly and precise event timing still need an offline audit.

## Local derivative for the old beta=3, kappa=1 branch

For fixed unit normal n, set `B = n*n^T + beta^2*(I-n*n^T)` and
`q = sqrt(delta^T*B*delta)`. This derivation assumes positive q, no penetration,
fixed current normal, and the loading branch with history maximum m=q<delta_c.
The inspected native law gives

`t = sigma*(1/q-1/delta_c)*B*delta`.

Differentiation, with `v=B*delta`, yields the symmetric local Jacobian

`J = sigma*(1/q-1/delta_c)*B - (sigma/q^3)*v*v^T`.

On unloading with fixed m>q, the Jacobian is simply
`J = sigma*(1/m-1/delta_c)*B`. Complete failure has zero cohesive traction;
compression/contact is a separate active branch. The native stored opening can
exclude the penetration component, so contact opening must be inspected too.
For kappa other than one the metric and traction matrices differ; this symmetric
formula must not be reused without re-derivation.

Since `(x^T*B*delta)^2 <= (x^T*B*x)*q^2`, the loading tangent obeys

`-(sigma/delta_c)*B <= J <= sigma*(1/q-1/delta_c)*B`.

Consequently a local absolute spectral envelope is

`Kenv = lambda_max(B)*max(sigma/delta_c, sigma*(1/q-1/delta_c))`.

Its units are Pa/m. It grows without bound as q approaches zero. The native
fictitious q used in tangent evaluation does not itself regularize the traction
law's zero-opening insertion branch. A finite envelope at a recorded nonzero
state cannot certify onset or an entire trajectory.

For a recorded state, use actual QP shape maps Gq and positive QP areas:
`Kcoh = sum_q A_q*Gq^T*Jq*Gq`. Adding the bulk tangent and normalizing by the
actual post-reassembly lumped mass permits a small dense eigenvalue check and
an independently assembled row-sum bound. An absolute QP envelope also supplies
a conservative positive upper matrix. Current-normal/geometric derivatives,
branch switching and future states remain outside this frozen-state result.
Negative softening eigenvalues describe physical loss of stability; the usual
`2/sqrt(lambda_max)` concerns high-frequency explicit integration only.

## Next decision

The reproducible offline work/event/mass audit is now retained. It confirms that
new nodes at phase C have copied displacement/velocity but zero, unreassembled
mass; D has positive new-node mass and conserved total mass. The old capture lacks
acceleration, effective strengths/openings, native normals and contact history,
so it cannot independently reconstruct the force law or event force continuity.
Do not jump to a full vessel, substitute intrinsic
Kn for this tangent, change beta to hide the old failure, or add an undocumented
regularization. Native stress-driven insertion over eligible internal facets is
the intended bulk-crack route; the accepted preinserted seam remains a control.

Root and Astra selected a bounded fresh coupon replay at h, h/2 and h/4 with
common physical endpoint 666h. Instrumentation preparation precedes execution;
root reviews and authorizes the baseline first. The optional h/8 run confirms
only a plausible trend. Mandatory captures include acceleration, native forces,
effective QP parameters, normal, delta max, contact fields, shape maps and native
energies, without additional assemblies for observation. C and D update phases
must remain explicit. The wheel has no public getTime; step*dt is a derived time,
separate from the prescribed-boundary phase time.

## Why halving the step is an empirical question at onset

If the first nonzero effective opening behaves as q1 ~ C*h^p, the angular
stiffness behaves as lambda ~ Ck/q1. Thus h^2*lambda ~ (Ck/C)*h^(2-p).
For p=2 this diagnostic need not improve under step refinement; for p>2 it can
worsen. Copying velocity/acceleration makes a second-order first opening plausible,
but does not prove that scaling for this run. Measure q1 and q1/h^2 explicitly.

A plateau alone does not prove failure to converge over a fixed physical interval:
the numerical layer might shrink in time and integrated impulse/work. The decision
therefore also requires matched-physical-time opening, force, kinetic and fracture
histories and energy defects. Event-relative plots supplement rather than replace
physical-time comparisons. Provisional numerical screening scales are sigma*A =
280 N, Gc*A = 3.04e-5 J and nominal delta_c = 2.17142857e-7 m. Suggested 2% history
and 1% energy tolerances are numerical screening criteria, not ceramic calibration.
Prescribed-boundary work needs verified native force/kinematic phasing; the old
reaction-only trapezoid remains an estimate until that verification is established.

For a continuous approach to insertion traction under the stated nonpenetrating,
fixed-normal beta=3/kappa=1 assumptions, the opening direction must satisfy
d parallel B^-1*t_ins and t_ins^T*B^-1*t_ins = sigma_eff^2. A direction mismatch
can produce a finite traction jump while q tends to zero. Capture relative
acceleration and the first actual nonzero opening instead of assuming they occur
in the insertion solve.

Native implicit/Newmark is not selected as a fallback: the current official manual
documents cohesive elements as compatible with static and explicit dynamic
analyses. A base model enum is not proof of supported dynamic extrinsic insertion.
The tagged source's zero-opening fictitious tangent does not regularize traction;
its nominal-versus-effective-strength tangent detail requires a separate audit.

## Energy getters are not all observationally pure

Root inspected the cached tagged `SolidMechanicsModel::getKineticEnergy`: it calls
`assembleLumpedMatrix("M")`, which calls `assembleMassLumped()`. Native node
insertion marks mass for reassembly. The historical `save_phase` copies C arrays
first and then calls `energy_values`, including the kinetic getter. Its saved
zero new-node C mass therefore does **not** prove that mass remained zero until
the solve; the intervening getter may already have rebuilt it. Exact wheel/source
equivalence is still not established.

Root and Astra chose to preserve that original getter placement in the refinement
campaign, explicitly labeling it as a possible mass-assembly barrier and copying
pre/post-energy nodal mass, displacement, velocity, acceleration and forces at C.
This preserves the baseline's observation order and makes the effect measurable.
There are no extra explicit mass/force assemblies for observation, but claiming
all getters are read-only or that only one native mass assembly occurs would be
incorrect. The tagged potential-energy getter updates an energy cache from stored
stress/gradients; it does not refresh mechanical stress. The inspected cohesive
energy branches integrate stored fields without updating cohesive history.

A separate zero-step public-FE shape probe now retains actual raw `(696,3)` Tri3
shape/normal arrays for 232 native triangle slots and three QPs per slot. Proven
element-major grouping, the repeated symmetric three-point shape table, exact
candidate facet connectivity/FIDs and unit normals establish coupon-only area/3
weights. This is `VERIFIED_COUPON_AFFINE_TRI3`, not a general native Jacobian getter
or a cross-insertion QP ordinal identity.

## Boundary work and a local onset ledger

The tagged residual uses restoring internal force with sign convention
`M*a = F_int + F_ext + R`. For a constrained component with physical prescribed
motion g(t), its actuator force is `R_b = m_b*g'' - F_int_b - F_ext_b` and
actuator work is the integral of `R_b*g'`. Native blocked-DOF acceleration or
velocity is not automatically g'' or g'. Inside the frozen constant-velocity
ramp, g''=0; with zero top external nodal force, R_b=-F_int_b, conditional on
force/displacement/time phase consistency.

The D-to-D work trapezoid `0.5*(R_n+R_next) dot (g_next-g_n)` is an integration
estimate, not an exact discrete energy identity. Its refinement error and the
native force evaluation phase must be verified. The native `external work`
getter returns a per-step quantity using native velocity; it cannot validate
prescribed-boundary work if blocked velocity differs from g'. Do not add the
legacy `contact` alias to the canonical `cohesive contact` energy.

Keep native kinetic energy separate from a physical kinematic ledger:
`K_phys = 0.5*sum_free(m*v^2) + 0.5*sum_blocked(m*(g')^2)`.
The ramp starts with a velocity jump unless initialized consistently, so a
zero-time ledger needs its startup impulse. A smaller defensible diagnostic
anchors an additional local onset ledger at a verified pre-event D state already
inside the linear ramp, where the constrained kinetic contribution is constant.
This removes that startup ambiguity without concealing global history; both
records remain visible. It grants no automatic force-balance or energy PASS.

All-facet intrinsic insertion adds intact-body compliance on the scale
`E/(K*h)` and creates many interfaces immediately. Raising K reduces that
compliance but tightens the explicit step. It is not an automatic solution to
extrinsic onset or the current native closed-fragment gate.

Primary implementation: [Akantu v5.0.7 cohesive linear inline law](https://gitlab.com/akantu/akantu/-/raw/v5.0.7/src/model/solid_mechanics/solid_mechanics_model_cohesive/materials/constitutive_laws/material_cohesive_linear_inline_impl.hh).
