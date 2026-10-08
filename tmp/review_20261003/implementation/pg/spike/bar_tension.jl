using Peridynamics
using TOML
using LinearAlgebra

const UPSTREAM_BACKEND = "peridynamics_jl_headless_0_5_4"

function graph_root!(parent::Vector{Int}, x::Int)
    while parent[x] != x
        parent[x] = parent[parent[x]]
        x = parent[x]
    end
    return x
end

function graph_union!(parent::Vector{Int}, i::Int, j::Int)
    ri = graph_root!(parent, i)
    rj = graph_root!(parent, j)
    ri == rj || (parent[max(ri, rj)] = min(ri, rj))
    return nothing
end

function run_bar(output_dir::String, scenario::String, nsteps::Int, speed::Float64,
                 dx::Float64, horizon::Float64, safety::Float64;
                 requested_duration_s::Float64=0.0,
                 requested_stepsize_s::Float64=0.0)
    scenario in ("zero", "loaded") || error("scenario must be zero or loaded")
    nsteps > 0 || error("nsteps must be positive")
    mkpath(output_dir)

    # A one-piece, homogeneous test body; no preset crack/cut or fragment target.
    lx, ly, lz = 0.006, 0.006, 0.016
    position, volume = uniform_box(lx, ly, lz, dx)
    body = Body(BBMaterial(), position, volume)
    zmin = minimum(@view position[3, :])
    zmax = maximum(@view position[3, :])
    tol = dx * 1e-8
    point_set!(body, :bottom, findall(abs.(@view(position[3, :]) .- zmin) .<= tol))
    point_set!(body, :top, findall(abs.(@view(position[3, :]) .- zmax) .<= tol))

    # These are deliberately toy values and are not calibrated to any real material.
    rho = 1000.0
    E = 1.0e6
    nu = 0.25
    Gc = 1.0
    material!(body; horizon=horizon, rho=rho, E=E, nu=nu, Gc=Gc)
    load_speed = scenario == "loaded" ? speed : 0.0
    velocity_bc!(t -> -load_speed, body, :bottom, 3)
    velocity_bc!(t -> load_speed, body, :top, 3)

    requested_duration_s > 0 && requested_stepsize_s > 0 &&
        error("choose at most one of requested_duration_s/requested_stepsize_s")
    solver = requested_stepsize_s > 0 ?
             VelocityVerlet(steps=nsteps, stepsize=requested_stepsize_s,
                            safety_factor=safety) :
             requested_duration_s > 0 ?
             VelocityVerlet(time=requested_duration_s, safety_factor=safety) :
             VelocityVerlet(steps=nsteps, safety_factor=safety)
    job = Job(body, solver)
    elapsed_s = @elapsed dh = submit(job; quiet=true)
    length(dh.chunks) == 1 || error("expected one CPU chunk for the bounded spike")
    chunk = dh.chunks[1]
    storage = chunk.storage
    now = storage.position
    damage = storage.damage
    n_active = storage.n_active_bonds
    velocity = storage.velocity
    sed = Peridynamics.export_field(Val(:strain_energy_density), chunk.mat, chunk.system,
                                    storage, chunk.paramsetup, solver.n_steps * solver.Δt)
    n = size(position, 2)
    length(damage) == n || error("unexpected damage field length")
    point_ids = chunk.system.chunk_handler.point_ids
    length(point_ids) == n || error("unexpected local point ID count")
    length(unique(point_ids)) == n || error("duplicate global point IDs in one-chunk fixture")
    Set(point_ids) == Set(1:n) || error("global point IDs are not a complete 1:n mapping")

    # Canonicalize the solver's directed bonds by their original global endpoint IDs.
    # Validate reciprocal state instead of treating per-point active counts as pair lineage.
    pair_state = Dict{Tuple{Int,Int},Vector{Bool}}()
    system = chunk.system
    for i_local in 1:system.chunk_handler.n_loc_points
        i_global = point_ids[i_local]
        for bond_id in Peridynamics.each_bond_idx(system, i_local)
            bond = system.bonds[bond_id]
            j_global = point_ids[bond.neighbor]
            i_global == j_global && error("self-bond in solver output")
            pair = i_global < j_global ? (i_global, j_global) : (j_global, i_global)
            push!(get!(pair_state, pair, Bool[]), storage.bond_active[bond_id])
        end
    end
    for (pair, states) in pair_state
        length(states) == 2 || error("expected two directed representations for bond $pair")
        states[1] == states[2] || error("reciprocal bond activity disagrees for $pair")
    end
    pairs = sort!(collect(keys(pair_state)))
    broken_pairs = [pair for pair in pairs if !pair_state[pair][1]]

    initial_parent = collect(1:n)
    for (i_global, j_global) in pairs
        graph_union!(initial_parent, i_global, j_global)
    end
    initial_component_count = length(Set(graph_root!(initial_parent, i) for i in 1:n))

    # Connected components of the actual intact-bond graph; this reports N=1 intact
    # honestly and does not request a fragment count from the solver.
    parent = collect(1:n)
    for (i_global, j_global) in pairs
        pair_state[(i_global, j_global)][1] || continue
        graph_union!(parent, i_global, j_global)
    end
    roots = [graph_root!(parent, global_id) for global_id in point_ids]
    root_order = sort!(unique(roots))
    component_id = Dict(root => id for (id, root) in enumerate(root_order))
    point_component_ids = [component_id[root] for root in roots]
    component_sizes = [count(==(id), point_component_ids) for id in eachindex(root_order)]
    component_masses = [rho * sum(volume[point_ids[i]] for i in 1:n if point_component_ids[i] == id)
                        for id in eachindex(root_order)]
    active_degree = zeros(Int, n)
    for (i_global, j_global) in pairs
        pair_state[(i_global, j_global)][1] || continue
        active_degree[i_global] += 1
        active_degree[j_global] += 1
    end
    isolated_point_ids = findall(==(0), active_degree)
    bottom_ids = Set(findall(abs.(@view(position[3, :]) .- zmin) .<= tol))
    top_ids = Set(findall(abs.(@view(position[3, :]) .- zmax) .<= tol))
    component_members = [Int[] for _ in eachindex(root_order)]
    for i in 1:n
        push!(component_members[point_component_ids[i]], point_ids[i])
    end
    component_bottom_only = [all(id -> id in bottom_ids, members) for members in component_members]
    component_top_only = [all(id -> id in top_ids, members) for members in component_members]

    local_volumes = [volume[point_ids[i]] for i in 1:n]
    mass_before = rho * sum(local_volumes)
    mass_after = rho * sum(local_volumes)
    kinetic_energy = 0.0
    for i in 1:n
        kinetic_energy += 0.5 * rho * local_volumes[i] * sum(abs2, @view velocity[:, i])
    end
    strain_energy = sum(sed .* local_volumes)

    open(joinpath(output_dir, "points.csv"), "w") do io
        println(io, "point_id,x_ref_m,y_ref_m,z_ref_m,x_current_m,y_current_m,z_current_m,vx_mps,vy_mps,vz_mps,damage,n_active_bonds,strain_energy_density_J_m3,volume_m3,mass_kg,intact_bond_component_id")
        for i in 1:n
            global_id = point_ids[i]
            println(io, join((global_id, position[1,global_id], position[2,global_id], position[3,global_id],
                              now[1,i], now[2,i], now[3,i],
                              velocity[1,i], velocity[2,i], velocity[3,i],
                              damage[i], n_active[i], sed[i], local_volumes[i], rho*local_volumes[i],
                              point_component_ids[i]), ","))
        end
    end
    open(joinpath(output_dir, "bond_states.csv"), "w") do io
        println(io, "point_i_global,point_j_global,active,reference_length_m,current_length_m")
        for (i_global, j_global) in pairs
            active = pair_state[(i_global, j_global)][1]
            i_local = chunk.system.chunk_handler.localizer[i_global]
            j_local = chunk.system.chunk_handler.localizer[j_global]
            ref_len = norm(system.position[:, i_local] - system.position[:, j_local])
            current_len = norm(now[:, i_local] - now[:, j_local])
            println(io, join((i_global, j_global, active, ref_len, current_len), ","))
        end
    end
    open(joinpath(output_dir, "broken_bonds.csv"), "w") do io
        println(io, "point_i_global,point_j_global,reference_length_m,current_length_m")
        for (i_global, j_global) in broken_pairs
            i_local = chunk.system.chunk_handler.localizer[i_global]
            j_local = chunk.system.chunk_handler.localizer[j_global]
            ref_len = norm(system.position[:, i_local] - system.position[:, j_local])
            current_len = norm(now[:, i_local] - now[:, j_local])
            println(io, join((i_global, j_global, ref_len, current_len), ","))
        end
    end
    open(joinpath(output_dir, "components.csv"), "w") do io
        println(io, "point_id,component_id,point_mass_kg,damage")
        for i in 1:n
            println(io, join((point_ids[i], point_component_ids[i], rho*local_volumes[i], damage[i]), ","))
        end
    end
    open(joinpath(output_dir, "component_summary.csv"), "w") do io
        println(io, "component_id,point_count,mass_kg,all_bottom_velocity_layer,all_top_velocity_layer")
        for id in eachindex(root_order)
            println(io, join((id, component_sizes[id], component_masses[id],
                              component_bottom_only[id], component_top_only[id]), ","))
        end
    end
    open(joinpath(output_dir, "isolated_points.csv"), "w") do io
        println(io, "point_id,reference_x_m,reference_y_m,reference_z_m,point_mass_kg")
        for global_id in isolated_point_ids
            i_local = chunk.system.chunk_handler.localizer[global_id]
            println(io, join((global_id, system.position[1,i_local], system.position[2,i_local],
                              system.position[3,i_local], rho*volume[global_id]), ","))
        end
    end

    summary = Dict{String,Any}(
        "status" => "COMPLETED",
        "backend_id" => UPSTREAM_BACKEND,
        "backend_version" => string(Base.pkgversion(Peridynamics)),
        "solver_model" => "bond-based Peridynamics.jl BBMaterial / CriticalStretch",
        "case" => "uniform tensile bar; emergent bond failure only",
        "scenario" => scenario,
        "calibration_status" => "UNVALIDATED_PROTOTYPE",
        "calibration_reason" => "toy E/rho/Gc values; no reference experiment or material calibration",
        "output_geometry_coordinates" => "m",
        "time_unit" => "s",
        "mass_unit" => "kg",
        "energy_unit" => "J",
        "n_points" => n,
        "n_steps" => solver.n_steps,
        "dt_s" => solver.Δt,
        "time_s" => solver.n_steps * solver.Δt,
        "requested_duration_s" => requested_duration_s > 0 ? requested_duration_s : solver.n_steps * solver.Δt,
        "requested_stepsize_s" => requested_stepsize_s > 0 ? requested_stepsize_s : "AUTO_STABLE_TIMESTEP",
        "wall_time_s" => elapsed_s,
        "dx_m" => dx,
        "horizon_m" => horizon,
        "rho_kg_m3" => rho,
        "E_pa" => E,
        "nu" => nu,
        "Gc_j_m2" => Gc,
        "critical_stretch" => body.point_params[1].εc,
        "load_speed_m_s" => load_speed,
        "max_damage" => maximum(damage),
        "mean_damage" => sum(damage) / n,
        "damaged_point_count" => count(>(0.0), damage),
        "global_point_ids_unique_complete" => true,
        "initial_directed_bond_count" => length(system.bonds),
        "initial_intact_bond_graph_component_count" => initial_component_count,
        "directed_bond_state_consistent" => true,
        "canonical_active_rule" => "two directed native BondSystem entries must agree; common storage.bond_active state is the canonical undirected edge state",
        "canonical_undirected_bond_count" => length(pairs),
        "broken_undirected_bond_count" => length(broken_pairs),
        "intact_undirected_bond_count" => length(pairs) - length(broken_pairs),
        "intact_bond_connected_component_count" => length(root_order),
        "isolated_point_count" => length(isolated_point_ids),
        "isolated_point_ids" => isolated_point_ids,
        "component_sizes_points" => component_sizes,
        "component_masses_kg" => component_masses,
        "component_all_bottom_velocity_layer" => component_bottom_only,
        "component_all_top_velocity_layer" => component_top_only,
        "bond_pair_lineage" => "SERIALIZED from native BondSystem and storage.bond_active; canonical undirected global point IDs",
        "total_point_mass_before_kg" => mass_before,
        "total_point_mass_after_kg" => mass_after,
        "point_mass_relative_change" => (mass_after-mass_before)/mass_before,
        "kinetic_energy_j" => kinetic_energy,
        "strain_energy_j" => strain_energy,
        "total_reported_energy_j" => kinetic_energy + strain_energy,
        "energy_conservation" => "UNKNOWN: prescribed velocity boundaries do external work; no full energy ledger audit in this spike",
        "contact" => "UNKNOWN: single body tension test has no contact",
        "broken_bond_pair_ids" => "SERIALIZED in broken_bonds.csv; includes all initial horizon bonds with active state",
        "surface_mapping" => "UNKNOWN: this fixture is a point cloud and has no crack surface reconstruction",
        "a12_relations" => "NOT_EMITTED: broken horizon interactions are not historical contact or R2"
    )
    open(joinpath(output_dir, "summary.toml"), "w") do io
        TOML.print(io, summary)
    end
    return summary
end

if abspath(PROGRAM_FILE) == abspath(String(@__FILE__))
    length(ARGS) == 7 || error("usage: bar_tension.jl OUTDIR SCENARIO NSTEPS SPEED_M_S DX_M HORIZON_M SAFETY_FACTOR")
    run_bar(ARGS[1], ARGS[2], parse(Int, ARGS[3]), parse(Float64, ARGS[4]),
            parse(Float64, ARGS[5]), parse(Float64, ARGS[6]), parse(Float64, ARGS[7]))
end
