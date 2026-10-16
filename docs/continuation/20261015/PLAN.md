# 2026-10-15 continuation: first reproducible vessel experiment

User authorization: continue A12, VesselForge and PG-Frag development and run the short experimental/data path. This is a new development scope, not a replay of the 2026-10-07 single-attempt authorization. Preserve old source, results, failures and receipts. No service, periodic commit loop, publishing or bulk training is needed.

## Root decisions

1. Use the existing CadQuery/OpenCascade and source-pinned Peridynamics.jl backend. First asset: an analytic concentric hemispherical bowl, outer radius 12 mm, inner radius 8 mm, sphere center (0,0,12) mm, material below z=12 mm. Two rest-coordinate painted band recipes. This is an experimental geometry, with unvalidated material and historical style.
2. Preserve `forge.asset.v1` and its existing validator. Add a separate reusable bowl builder; do not modify the handled-vessel prototype or rewrite older experiments.
3. Start with native BB, Poisson ratio 0.25, NoCorrection, CriticalStretch and VelocityVerlet. Use a type-specific geometry-filter adapter, with no changes to vendor physics or time integration. Filter bonds whose reference segment enters the inner sphere before native system/storage initialization. These are INITIAL_GEOMETRIC_EXCLUSION, never fracture events.
4. Start with free evolution from prescribed initial velocity. It is not a drop/contact experiment. A symmetric anisotropic strain-rate tensor and a zero control avoid grip-boundary fracture. Freeze amplitudes before results; do not tune for a target shard count.
5. Keep point state/graph identity, experimental observations, offline physics targets, and public observation-only features separate. PD connectivity alone cannot establish positive-area physical crack surfaces, rigid fragments, R2 or negative relations. Existing PRETRAIN/physical qualification gates stay in force.
6. In parallel, implement one bounded native cohesive patch with free interior DOFs, as the next candidate for traceable paired faces. Do not tile the prior all-DOF intrinsic toy across a vessel. Its interface compliance/process-zone conflict was reviewed with the user-authorized Astra advisor.

## Root formulas and acceptance

For radii in SI, V=2*pi/3*(Ro^3-Ri^3). For the reference segment a+t*d and sphere center o, t*=clip(-(a-o).d/(d.d),0,1); retain only if |a+t*d-o|>=Ri. Outer sphere and lower half-space are convex, so valid endpoints already establish their segment containment.

For uniform native BB, K=E/[3(1-2*nu)], c=18*K/(pi*delta^4), epsilon_c=sqrt(5*Gc/(9*K*delta)). The undirected pair potential is Uij=0.5*c*Vi*Vj*Lij*sij^2. A first-break event removes that potential at its actual integration state. Accumulate this discrete removed energy D separately from any continuum Gc*A claim. Confirm reciprocal states, parameters and correction factors before using the undirected formula.

Check complete mass coverage (including isolated points), irreversible events, original reference coordinates, finite native states, native stable dt, zero-load behavior, and independently reconstructed P/L/K/U/D. Fixed-mesh dt comparison and fixed-delta spatial comparison have separate meanings; a two-level comparison is a sensitivity study, not established asymptotic convergence. Point-center h^3 quadrature is explicitly approximate and is compared with CAD/analytic volume without uniform mass rescaling.

First-run bounds: one thread, at most 12,000 points, 1,000 steps and 2,000,000 undirected pairs, 120 seconds wall time and 256 MiB output per run. The initial 128 MiB plan was increased before the first native solve because preserving every state for the same-duration 800-step half-dt comparison doubles the audit history. This is an I/O resource allocation change, not a change to physical, numerical or data-qualification thresholds. Report raw/final peak and persistent bytes separately. New output directories only. Save exact source bytes, case, argv, size/SHA and execution receipt. Root reviews initial source before the first solver run.

## Ownership

- Luna VF: new spherical_bowl module, its tests and geometry experiment/documentation.
- Luna PG: new bowl_dynamics wrapper/native runner, their tests and runtime receipts.
- Luna A12: new experimental ingestion/export module and tests, after its interface review.
- Luna cohesive: only experiments/free_cohesive_patch_20261015 and its report.
- Root: scope, formulas, case amplitudes, integration, independent acceptance and final status.

Starting evidence: handover 2026-10-07 and A12 contract alignment 2026-10-09. Qualified complete physical packages at the starting point: 0. This plan is not evidence that any new implementation or run has passed.

## Full goal remains open

The point-state milestone does not replace the requested vessel-fracture and training-data outcome. Remaining required work includes actual vessel separation, traceable positive-area paired crack surfaces, closed fragment geometry and dynamics, observation generation from those fragments, and an audited experimental/training export. Material, numerical and data qualification must be reported separately; an uncalibrated synthetic experiment must not be described as measured ceramic behavior. Existing A12 and infrastructure gaps are retained rather than declared complete after this first milestone.

## Environment and source-review updates

- Windows Smart App Control initially blocked the OCP extension. The user changed the setting; a normal import subsequently succeeded (`OCP`, CadQuery 2.8.0). Continue the original CAD/STEP route. No policy workaround or analytic-only replacement was used.
- Root review corrected a segment test that clipped away an invalid endpoint instead of requiring the entire segment to lie in material.
- The new bowl asset and solver must share the same explicitly unvalidated mechanics: rho=2300 kg/m3, E=70 GPa, nu=0.25, Gc=7.6 J/m2. Reject a silent material override.
- Solver source snapshots must be the bytes actually executed; prepared and actual argv records are separate. Keep the exact source manifest bytes with their receipt.
- Vector supervision is transformed into the same sensor frame as anonymous feature positions when an aligned training view is requested. Raw native vectors remain in the offline target's original frame.
- Local Akantu `MaterialCohesive::updateEnergies` integrates positive conjugate `traction dot d(opening)` and uses `reversible=0.5 traction dot opening`; do not negate the work merely because traction is called a resisting force. Preserve raw signed histories and verify the solver update order.
- A second Astra review accepted an actual-bowl, preinserted weak-seam case as the next bounded route to solver-driven separation and closed tet-derived fragments. It retains an explicit prescribed crack-path limitation. Do not promote it to homogeneous-ceramic free fracture. Proposed separate weak seam: sigma=10 MPa, Gc=7.6 J/m2, E=70 GPa, nu=0.25, delta0=1e-8 m, beta=kappa=1; root must freeze and validate stiffness, bonded compliance, native quadrature histories and physical-time comparisons before use.
- Akantu's checked local `getStableTimeStep()` implementation covers regular bulk elements, not intrinsic cohesive stiffness. An independent mass-normalized bulk-plus-interface bound is required before the free-coupling run; a fraction of bulk CFL alone is insufficient.

## Actual-vessel cohesive stage: decisions before execution

The displacement-driven coupon established native free-interior coupling and signed interface work. For the actual vessel, root and Astra selected fully free DOFs with reference-direction nodal patch forces, avoiding an unverified prescribed-boundary velocity/acceleration convention. The native source mesh has 1,212 nodes, 4,342 linear tetrahedra and 158 conformal x=0 triangles; native cohesive insertion yields 1,317 nodes and 474 quadrature points. The original geometry partition is never a fragment label.

The new weak-seam case uses the original bowl bulk card (rho=2300, E=70 GPa, nu=0.25, Gc=7.6) and an explicitly separate uncalibrated interface sigma=10 MPa, delta0=1e-8 m, beta=kappa=1, penalty=0. Its Kn=1e15 Pa/m and delta_f=1.52 micrometres. No contact, drop or homogeneous crack-path claim is made.

The declared external load is +/-x on finite original-exterior node patches |x|>8.5 mm. Positive area weights are projected by a relative-entropy method to a common reference bulk-COM y,z force line. This avoids the large initial eccentricity of a small equatorial patch. Each side receives 1600*sin(pi*t/25 us)^2 N for 0<t<25 us, then zero, with free evolution to 50 us. Initial net force and torque are zero; actual current torque is measured, not assumed to remain zero. The load and weak-seam law were fixed before the native solve, not selected for two fragments.

The initial mass-normalized T4+Tri3 row-sum stiffness bound is 2.5705200214639015e15 /s^2. Native bulk-only critical dt is 3.854377218288659e-8 s; independent total critical dt is 3.944750139695518e-8 s. The step is T/ceil(T/min(0.4*dt_total,0.4*dt_bulk)), giving 3244 steps and dt=1.5413070283600494e-8 s; the paired comparison uses exactly 6488 steps at half dt and the same physical duration. This is an initial/fixed-normal high-frequency bound, not a full softening convergence proof.

This stage has its own predeclared resource allocation: at most 40,000 steps, 300 seconds and 2 GiB per run. Full native-double quadrature histories and full nodal u/v/a/internal-force histories are retained in the accepted v4 baseline and v2 half-dt runs. Batched flushes preserve every value without forcing a filesystem sync per field per step. The limits do not change the scientific criteria. Small-strain applicability checks use each saved native T4: principal infinitesimal strain <=1%, polar rotation <=0.05 rad and detF>=0.8. These are numerical-model windows, not calibrated ceramic limits.

Whole-node histories enable independent central-difference recurrence, Ma=F+I, nodal K/P/L, bulk energy, external work and material-work audits. K_alg=K-dt^2*a^T*M*a/8 distinguishes the discrete integration identity from ordinary physical energy. Report residuals relative to both total work and Gc times the actual one-sided discrete interface area; final large translation energy must not hide fracture-energy errors.

Only actual all-QP failure with near-zero traction can remove a cohesive graph connection. Closed fragments must cover all native tets and mass, have actual native boundary closure and source-exterior ancestry, and share no remaining native DOF across components. No artificial caps, virtual node welding or input-volume tags can establish fragment eligibility. Observations derive from their current boundary geometry; rest coordinates, ancestry, damage and simulation transforms remain offline truth. All views of this one mother vessel/event belong to one research source group.
