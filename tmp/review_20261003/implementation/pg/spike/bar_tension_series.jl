include("bar_tension.jl")

if length(ARGS) != 1
    error("usage: bar_tension_series.jl OUTPUT_ROOT")
end
root = ARGS[1]
mkpath(root)

h = 0.001
horizon = 3h
safety = 0.7
zero = run_bar(joinpath(root, "zero_h1"), "zero", 50, 0.0, h, horizon, safety)
duration = zero["time_s"]
low = run_bar(joinpath(root, "low_load_h1"), "loaded", 50, 0.1, h, horizon, safety)

for nsteps in (5, 10, 20, 35, 50)
    run_bar(joinpath(root, "high_load_h1", "steps_$(nsteps)"), "loaded", nsteps,
            0.5, h, horizon, safety)
end

# Same physical body, load speed and requested end-time; halve auto dt by halving safety.
dt_fine = run_bar(joinpath(root, "high_load_h1_dt_half"), "loaded", 100, 0.5,
                  h, horizon, 0.35)
isapprox(dt_fine["dt_s"], zero["dt_s"] / 2; rtol=1e-12, atol=0.0) ||
    error("fine timestep is not half the baseline timestep")
isapprox(dt_fine["time_s"], duration; rtol=1e-12, atol=0.0) ||
    error("fine run did not end at the baseline physical time")

# Fixed geometry and physical horizon; this is a resolution sensitivity check,
# not a calibrated convergence study.
dx_coarse = 0.0015
coarse_probe = run_bar(joinpath(root, "h1p5_auto_dt_probe"), "loaded", 1, 0.5,
                       dx_coarse, horizon, safety)
coarse_steps = ceil(Int, duration / coarse_probe["dt_s"])
coarse_dt = duration / coarse_steps
coarse_dt <= coarse_probe["dt_s"] || error("matched coarse timestep exceeds measured stable step")
dx_compare = run_bar(joinpath(root, "high_load_h1p5_same_time"), "loaded", coarse_steps, 0.5,
                     dx_coarse, horizon, safety; requested_stepsize_s=coarse_dt)
isapprox(dx_compare["time_s"], duration; rtol=1e-12, atol=0.0) ||
    error("spacing comparison did not end at the baseline physical time")

println("BAR_SERIES_COMPLETE baseline_time_s=", duration,
        " low_damage=", low["max_damage"],
        " fine_dt_s=", dt_fine["dt_s"],
        " fine_steps=", dt_fine["n_steps"],
        " fine_time_s=", dt_fine["time_s"],
        " coarse_dt_probe_s=", coarse_probe["dt_s"],
        " coarse_matched_dt_s=", dx_compare["dt_s"],
        " coarse_matched_steps=", dx_compare["n_steps"],
        " coarse_time_s=", dx_compare["time_s"],
        " coarse_n=", dx_compare["n_points"],
        " coarse_steps=", dx_compare["n_steps"])
