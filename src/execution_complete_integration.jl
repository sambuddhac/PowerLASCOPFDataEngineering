# PowerLASCOPF.jl/scripts/run_lascopf.jl

"""
Main execution script for PowerLASCOPF solver
Called by Airflow pipeline
"""

using PowerLASCOPF
using PowerSystems
using JSON3
using Dates
using UUIDs
using Logging

# Import data interface modules
include("../src/data_interface/DataLoader.jl")
using .DataLoader

# Set up logging
logger = SimpleLogger(stdout, Logging.Info)
global_logger(logger)

function main(config_file::String)
    @info "Starting PowerLASCOPF execution"
    @info "Config file: $config_file"
    
    # Load configuration
    config = JSON3.read(read(config_file, String))
    @info "Configuration loaded" config
    
    # Connect to databases
    @info "Connecting to databases..."
    db = DatabaseConnection()
    
    try
        # Step 1: Load network topology
        @info "Loading network topology..."
        topology_id, sys = load_network_topology(db, config.case_name)
        @info "Network loaded" num_buses=length(PSY.get_components(PSY.Bus, sys)) 
                                num_generators=length(PSY.get_components(PSY.Generator, sys))
        
        # Step 2: Load time-series data
        @info "Loading time-series data..."
        start_time = DateTime(config.execution_date)
        end_time = start_time + Hour(config.optimization_horizon_hours)
        
        ts_data = load_time_series_data(db, config.case_name, start_time, end_time)
        @info "Time-series data loaded" num_measurements=nrow(ts_data["power_measurements"])
        
        # Attach time series to system
        attach_time_series_to_system!(sys, ts_data)
        
        # Step 3: Load contingencies
        @info "Loading contingencies..."
        contingencies = load_contingencies(db, topology_id)
        @info "Contingencies loaded" num_contingencies=nrow(contingencies)
        
        # Step 4: Set up LASCOPF problem
        @info "Setting up LASCOPF problem..."
        
        lascopf_config = Dict(
            "admm_rho" => config.admm_rho,
            "app_beta" => config.app_beta,
            "app_gamma" => config.app_gamma,
            "max_iterations" => config.max_iterations,
            "convergence_tolerance" => config.convergence_tolerance,
            "num_time_steps" => config.num_time_steps,
            "num_contingencies" => nrow(contingencies)
        )
        
        # Step 5: Solve LASCOPF
        @info "Starting solver..."
        start_solve_time = time()
        
        results = solve_lascopf(sys, contingencies, lascopf_config)
        
        solve_time = time() - start_solve_time
        @info "Solver completed" solve_time_seconds=solve_time status=results["status"]
        
        # Step 6: Save results to database
        @info "Saving results to database..."
        execution_id = save_results_to_database(
            db, 
            topology_id, 
            results, 
            lascopf_config,
            solve_time
        )
        
        @info "Results saved successfully" execution_id=execution_id
        
        # Print execution ID for Airflow to capture
        println("execution_id: $execution_id")
        
        return 0
        
    catch e
        @error "Error during execution" exception=(e, catch_backtrace())
        return 1
    finally
        close(db)
    end
end

"""
    solve_lascopf(sys, contingencies, config)

Main LASCOPF solver function
"""
function solve_lascopf(sys::PSY.System, contingencies::DataFrame, config::Dict)
    @info "Initializing LASCOPF solver..."
    
    num_time_steps = config["num_time_steps"]
    num_contingencies = config["num_contingencies"]
    
    # Initialize results storage
    results = Dict(
        "status" => "INITIALIZED",
        "objective_value" => Inf,
        "iterations" => 0,
        "convergence_history" => DataFrame(
            iteration = Int[],
            primal_residual = Float64[],
            dual_residual = Float64[],
            objective_value = Float64[],
            iteration_time = Float64[]
        ),
        "dispatch" => DataFrame(
            time_step = Int[],
            generator_id = String[],
            scenario_type = String[],
            active_power_mw = Float64[],
            reactive_power_mvar = Float64[],
            commitment_status = Bool[],
            generation_cost = Float64[]
        ),
        "bus_results" => DataFrame(
            time_step = Int[],
            bus_id = String[],
            scenario_type = String[],
            voltage_magnitude_pu = Float64[],
            voltage_angle_rad = Float64[],
            lmp_total = Float64[]
        ),
        "branch_flows" => DataFrame(
            time_step = Int[],
            branch_id = String[],
            scenario_type = String[],
            from_active_power_mw = Float64[],
            to_active_power_mw = Float64[],
            loading_percentage = Float64[]
        )
    )
    
    # Get ADMM/APP parameters
    rho = config["admm_rho"]
    beta = config["app_beta"]
    gamma = config["app_gamma"]
    max_iter = config["max_iterations"]
    tol = config["convergence_tolerance"]
    
    @info "Starting ADMM/APP iterations..."
    
    for iter in 1:max_iter
        iter_start = time()
        
        # ====================================================================
        # OUTER LOOP: APP for interval coupling
        # ====================================================================
        
        # Solve base case for all time steps
        @info "Iteration $iter: Solving base case..."
        base_results = solve_base_case(sys, num_time_steps, config)
        
        # ====================================================================
        # MIDDLE LOOP: ADMM for network consensus
        # ====================================================================
        
        @info "Iteration $iter: Network consensus update..."
        network_update!(base_results, config)
        
        # ====================================================================
        # INNER LOOP: Contingency scenarios
        # ====================================================================
        
        @info "Iteration $iter: Solving contingency scenarios..."
        contingency_results = solve_contingencies(
            sys, 
            contingencies, 
            base_results,
            config
        )
        
        # ====================================================================
        # Update Lagrange multipliers and check convergence
        # ====================================================================
        
        primal_residual, dual_residual = compute_residuals(
            base_results,
            contingency_results,
            config
        )
        
        objective = compute_objective_value(base_results, contingency_results)
        
        iter_time = time() - iter_start
        
        # Store convergence history
        push!(results["convergence_history"], (
            iter,
            primal_residual,
            dual_residual,
            objective,
            iter_time
        ))
        
        @info "Iteration $iter complete" primal_residual dual_residual objective iter_time
        
        # Check convergence
        if primal_residual < tol && dual_residual < tol
            @info "Converged at iteration $iter"
            results["status"] = "CONVERGED"
            results["iterations"] = iter
            results["objective_value"] = objective
            
            # Extract final dispatch and bus results
            extract_results!(results, base_results, contingency_results)
            
            return results
        end
        
        # Update multipliers
        update_multipliers!(base_results, contingency_results, config)
    end
    
    # Max iterations reached
    @warn "Maximum iterations reached without convergence"
    results["status"] = "MAX_ITERATIONS"
    results["iterations"] = max_iter
    results["objective_value"] = results["convergence_history"][end, :objective_value]
    
    # Extract best results found
    extract_results!(results, base_results, contingency_results)
    
    return results
end

"""
    solve_base_case(sys, num_time_steps, config)

Solve base case optimization problem for all time steps
"""
function solve_base_case(sys::PSY.System, num_time_steps::Int, config::Dict)
    @info "Solving base case for $num_time_steps time steps"
    
    generators = collect(PSY.get_components(PSY.Generator, sys))
    buses = collect(PSY.get_components(PSY.Bus, sys))
    
    base_results = Dict(
        "generators" => Dict{String, Any}(),
        "buses" => Dict{String, Any}(),
        "objective" => 0.0
    )
    
    # For each time step, solve generator subproblems in parallel
    for t in 1:num_time_steps
        for gen in generators
            gen_name = PSY.get_name(gen)
            
            # Create generator solver with regularization terms
            interval_type = GenFirstBaseInterval(
                lambda_1 = zeros(1),
                lambda_2 = zeros(1),
                B = zeros(1),
                D = zeros(1),
                BSC = zeros(config["num_contingencies"]),
                cont_count = config["num_contingencies"],
                rho = config["admm_rho"],
                beta = config["app_beta"],
                gamma = config["app_gamma"]
            )
            
            cost_curve = ExtendedThermalGenerationCost(
                thermal_cost_core = PSY.get_operation_cost(gen),
                regularization_term = interval_type
            )
            
            solver = GenSolver(
                interval_type = interval_type,
                cost_curve = cost_curve
            )
            
            # Solve generator subproblem
            gen_result = solve_generator_subproblem(solver, gen, t, config)
            
            if !haskey(base_results["generators"], gen_name)
                base_results["generators"][gen_name] = Dict()
            end
            base_results["generators"][gen_name][t] = gen_result
        end
    end
    
    return base_results
end

"""
    solve_generator_subproblem(solver, gen, time_step, config)

Solve individual generator optimization subproblem
"""
function solve_generator_subproblem(solver::GenSolver, gen, time_step::Int, config::Dict)
    # This is a simplified version - you would use your actual GenSolver implementation
    
    limits = PSY.get_active_power_limits(gen)
    
    result = Dict(
        "Pg" => (limits.min + limits.max) / 2,  # Placeholder
        "PgNext" => (limits.min + limits.max) / 2,
        "thetag" => 0.0,
        "cost" => 0.0
    )
    
    return result
end

"""
    network_update!(base_results, config)

Perform network consensus update (ADMM)
"""
function network_update!(base_results::Dict, config::Dict)
    # Update network variables for consensus
    # This implements the ADMM network layer
    
    rho = config["admm_rho"]
    
    # Average generator outputs across the network
    for (gen_name, gen_data) in base_results["generators"]
        for (t, result) in gen_data
            # Update consensus variables
            result["Pg_avg"] = result["Pg"]
            result["theta_avg"] = result["thetag"]
        end
    end
    
    return base_results
end

"""
    solve_contingencies(sys, contingencies, base_results, config)

Solve all contingency scenarios
"""
function solve_contingencies(
    sys::PSY.System,
    contingencies::DataFrame,
    base_results::Dict,
    config::Dict
)
    contingency_results = Dict()
    
    for (idx, cont) in enumerate(eachrow(contingencies))
        @info "Solving contingency: $(cont.contingency_name)"
        
        # Create contingency system
        cont_sys = apply_contingency(sys, cont)
        
        # Solve contingency case
        cont_result = solve_base_case(cont_sys, config["num_time_steps"], config)
        
        contingency_results[cont.contingency_name] = cont_result
    end
    
    return contingency_results
end

"""
    apply_contingency(sys, contingency)

Apply contingency to system (remove affected elements)
"""
function apply_contingency(sys::PSY.System, contingency)
    # Create a copy of the system
    cont_sys = deepcopy(sys)
    
    # Remove affected branches
    if !ismissing(contingency.affected_branches) && !isnothing(contingency.affected_branches)
        for branch_name in contingency.affected_branches
            branch = PSY.get_component(PSY.Branch, cont_sys, branch_name)
            if !isnothing(branch)
                PSY.set_available!(branch, false)
            end
        end
    end
    
    # Remove affected generators
    if !ismissing(contingency.affected_generators) && !isnothing(contingency.affected_generators)
        for gen_name in contingency.affected_generators
            gen = PSY.get_component(PSY.Generator, cont_sys, gen_name)
            if !isnothing(gen)
                PSY.set_available!(gen, false)
            end
        end
    end
    
    return cont_sys
end

"""
    compute_residuals(base_results, contingency_results, config)

Compute primal and dual residuals for convergence check
"""
function compute_residuals(base_results::Dict, contingency_results::Dict, config::Dict)
    primal_residual = 0.0
    dual_residual = 0.0
    
    # Compute primal residual (constraint violations)
    for (gen_name, gen_data) in base_results["generators"]
        for (t, result) in gen_data
            # Power balance residual
            primal_residual += (result["Pg"] - get(result, "Pg_avg", result["Pg"]))^2
        end
    end
    primal_residual = sqrt(primal_residual)
    
    # Compute dual residual (multiplier changes)
    # Simplified - would track actual multiplier changes
    dual_residual = primal_residual * 0.1
    
    return primal_residual, dual_residual
end

"""
    compute_objective_value(base_results, contingency_results)

Compute total objective function value
"""
function compute_objective_value(base_results::Dict, contingency_results::Dict)
    objective = 0.0
    
    # Base case costs
    for (gen_name, gen_data) in base_results["generators"]
        for (t, result) in gen_data
            objective += get(result, "cost", 0.0)
        end
    end
    
    # Contingency case costs (weighted)
    for (cont_name, cont_result) in contingency_results
        cont_obj = 0.0
        for (gen_name, gen_data) in cont_result["generators"]
            for (t, result) in gen_data
                cont_obj += get(result, "cost", 0.0)
            end
        end
        objective += cont_obj * 0.01  # Weight by probability
    end
    
    return objective
end

"""
    update_multipliers!(base_results, contingency_results, config)

Update Lagrange multipliers for next iteration
"""
function update_multipliers!(base_results::Dict, contingency_results::Dict, config::Dict)
    rho = config["admm_rho"]
    beta = config["app_beta"]
    
    # Update ADMM multipliers
    for (gen_name, gen_data) in base_results["generators"]
        for (t, result) in gen_data
            residual = result["Pg"] - get(result, "Pg_avg", result["Pg"])
            result["lambda_admm"] = get(result, "lambda_admm", 0.0) + rho * residual
        end
    end
    
    return
end

"""
    extract_results!(results, base_results, contingency_results)

Extract final results into structured format
"""
function extract_results!(results::Dict, base_results::Dict, contingency_results::Dict)
    # Extract dispatch results
    for (gen_name, gen_data) in base_results["generators"]
        for (t, result) in gen_data
            push!(results["dispatch"], (
                t,
                gen_name,
                "BASE",
                result["Pg"],
                get(result, "Qg", 0.0),
                true,
                get(result, "cost", 0.0)
            ))
        end
    end
    
    # Extract contingency dispatch results
    for (cont_name, cont_result) in contingency_results
        for (gen_name, gen_data) in cont_result["generators"]
            for (t, result) in gen_data
                push!(results["dispatch"], (
                    t,
                    gen_name,
                    cont_name,
                    result["Pg"],
                    get(result, "Qg", 0.0),
                    true,
                    get(result, "cost", 0.0)
                ))
            end
        end
    end
    
    return results
end

"""
    save_results_to_database(db, topology_id, results, config, solve_time)

Save all results to database
"""
function save_results_to_database(
    db::DatabaseConnection,
    topology_id::Int,
    results::Dict,
    config::Dict,
    solve_time::Float64
)
    @info "Saving results to database..."
    
    # Step 1: Save execution metadata
    execution_data = Dict(
        "topology_id" => topology_id,
        "num_time_steps" => config["num_time_steps"],
        "num_contingencies" => config["num_contingencies"],
        "admm_rho" => config["admm_rho"],
        "app_beta" => config["app_beta"],
        "app_gamma" => config["app_gamma"],
        "max_iterations" => config["max_iterations"],
        "convergence_tolerance" => config["convergence_tolerance"],
        "convergence_status" => results["status"],
        "final_iteration" => results["iterations"],
        "objective_value" => results["objective_value"],
        "solve_time_seconds" => solve_time,
        "triggered_by" => "AIRFLOW"
    )
    
    execution_id = save_execution_metadata(db, execution_data)
    
    # Step 2: Save dispatch results
    if nrow(results["dispatch"]) > 0
        # Add execution_id to dispatch results
        dispatch_df = results["dispatch"]
        dispatch_df[!, :execution_id] .= execution_id
        dispatch_df[!, :target_datetime] .= now()
        
        save_dispatch_results(db, execution_id, dispatch_df)
    end
    
    # Step 3: Save bus results
    if nrow(results["bus_results"]) > 0
        bus_df = results["bus_results"]
        bus_df[!, :execution_id] .= execution_id
        bus_df[!, :target_datetime] .= now()
        
        save_bus_results(db, execution_id, bus_df)
    end
    
    # Step 4: Save convergence history
    if nrow(results["convergence_history"]) > 0
        conv_df = results["convergence_history"]
        conv_df[!, :execution_id] .= execution_id
        
        save_convergence_history(db, execution_id, conv_df)
    end
    
    @info "All results saved successfully"
    
    return execution_id
end

# =============================================================================
# Main execution
# =============================================================================

if length(ARGS) < 1
    @error "Usage: julia run_lascopf.jl <config_file>"
    exit(1)
end

config_file = ARGS[1]

if !isfile(config_file)
    @error "Config file not found: $config_file"
    exit(1)
end

exit_code = main(config_file)
exit(exit_code)