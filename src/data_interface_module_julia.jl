# PowerLASCOPF.jl/src/data_interface/DataLoader.jl

"""
Data loading and database interface module for PowerLASCOPF
"""
module DataLoader

using DataFrames
using CSV
using LibPQ
using JSON3
using Dates
using UUIDs
using PowerSystems
using InfrastructureSystems

const PSY = PowerSystems
const IS = InfrastructureSystems

export DatabaseConnection, 
       load_network_topology,
       load_time_series_data,
       load_contingencies,
       save_execution_metadata,
       save_dispatch_results,
       save_bus_results,
       save_convergence_history

# ============================================================================
# Database Connection Management
# ============================================================================

"""
    DatabaseConnection

Manages connections to PostgreSQL and TimescaleDB
"""
mutable struct DatabaseConnection
    metadata_conn::LibPQ.Connection  # PostgreSQL for metadata
    timeseries_conn::LibPQ.Connection  # TimescaleDB for time-series
end

"""
    DatabaseConnection(metadata_url::String, timeseries_url::String)

Create database connections
"""
function DatabaseConnection(metadata_url::String, timeseries_url::String)
    metadata_conn = LibPQ.Connection(metadata_url)
    timeseries_conn = LibPQ.Connection(timeseries_url)
    return DatabaseConnection(metadata_conn, timeseries_conn)
end

"""
    DatabaseConnection()

Create database connections from environment variables
"""
function DatabaseConnection()
    metadata_url = get(ENV, "DATABASE_URL", "postgresql://lascopf:lascopf_pass_2024@localhost:5433/lascopf_metadata")
    timeseries_url = get(ENV, "TIMESCALE_URL", "postgresql://lascopf:lascopf_pass_2024@localhost:5432/lascopf_timeseries")
    return DatabaseConnection(metadata_url, timeseries_url)
end

function Base.close(db::DatabaseConnection)
    LibPQ.close(db.metadata_conn)
    LibPQ.close(db.timeseries_conn)
end

# ============================================================================
# Network Topology Loading
# ============================================================================

"""
    load_network_topology(db::DatabaseConnection, case_name::String)

Load network topology and create PowerSystems.System object
"""
function load_network_topology(db::DatabaseConnection, case_name::String)
    query = """
        SELECT topology_id, system_data, powersystems_file_path, base_mva
        FROM network_topology 
        WHERE case_name = \$1 
        AND (valid_until IS NULL OR valid_until > NOW())
        ORDER BY valid_from DESC
        LIMIT 1
    """
    
    result = execute(db.metadata_conn, query, [case_name])
    
    if LibPQ.num_rows(result) == 0
        error("Network topology not found for case: $case_name")
    end
    
    row = first(result)
    topology_id = row[:topology_id]
    
    # If PowerSystems file path exists, load directly
    if !ismissing(row[:powersystems_file_path]) && isfile(row[:powersystems_file_path])
        @info "Loading system from file: $(row[:powersystems_file_path])"
        sys = PSY.System(row[:powersystems_file_path])
        return topology_id, sys
    end
    
    # Otherwise, build from JSON data
    @info "Building system from JSON data"
    system_json = JSON3.read(row[:system_data])
    sys = build_system_from_json(system_json, row[:base_mva])
    
    return topology_id, sys
end

"""
    build_system_from_json(json_data, base_mva)

Build PowerSystems.System from JSON representation
"""
function build_system_from_json(json_data, base_mva)
    # Create empty system
    sys = PSY.System(base_mva)
    
    # Add buses
    for bus_data in json_data[:buses]
        bus = PSY.Bus(
            number = bus_data[:number],
            name = bus_data[:name],
            bustype = PSY.BusTypes.PQ,  # Will be updated
            angle = get(bus_data, :angle, 0.0),
            magnitude = get(bus_data, :voltage_magnitude, 1.0),
            voltage_limits = (
                min = get(bus_data, :voltage_min, 0.9),
                max = get(bus_data, :voltage_max, 1.1)
            ),
            base_voltage = bus_data[:base_voltage],
            area = PSY.Area(get(bus_data, :area, "Area1")),
            load_zone = PSY.LoadZone(get(bus_data, :zone, "Zone1"))
        )
        PSY.add_component!(sys, bus)
    end
    
    # Add branches
    for branch_data in json_data[:branches]
        from_bus = PSY.get_component(PSY.Bus, sys, branch_data[:from_bus_name])
        to_bus = PSY.get_component(PSY.Bus, sys, branch_data[:to_bus_name])
        
        branch = PSY.Line(
            name = branch_data[:name],
            available = get(branch_data, :available, true),
            active_power_flow = 0.0,
            reactive_power_flow = 0.0,
            arc = PSY.Arc(from_bus, to_bus),
            r = branch_data[:resistance],
            x = branch_data[:reactance],
            b = (from = get(branch_data, :shunt_susceptance, 0.0) / 2,
                 to = get(branch_data, :shunt_susceptance, 0.0) / 2),
            rate = branch_data[:rating],
            angle_limits = (
                min = get(branch_data, :angle_min, -π/2),
                max = get(branch_data, :angle_max, π/2)
            )
        )
        PSY.add_component!(sys, branch)
    end
    
    # Add generators
    for gen_data in json_data[:generators]
        bus = PSY.get_component(PSY.Bus, sys, gen_data[:bus_name])
        
        if gen_data[:type] == "THERMAL"
            # Create thermal generation cost
            cost = PSY.ThermalGenerationCost(
                variable = PSY.CostCurve(PSY.LinearCurve(gen_data[:cost_linear])),
                fixed = get(gen_data, :cost_fixed, 0.0),
                start_up = get(gen_data, :startup_cost, 0.0),
                shut_down = get(gen_data, :shutdown_cost, 0.0)
            )
            
            gen = PSY.ThermalStandard(
                name = gen_data[:name],
                available = get(gen_data, :available, true),
                status = get(gen_data, :status, true),
                bus = bus,
                active_power = get(gen_data, :active_power, 0.0),
                reactive_power = get(gen_data, :reactive_power, 0.0),
                rating = gen_data[:rating],
                prime_mover = PSY.PrimeMovers.ST,
                fuel = PSY.ThermalFuels.COAL,
                active_power_limits = (
                    min = gen_data[:pmin],
                    max = gen_data[:pmax]
                ),
                reactive_power_limits = (
                    min = get(gen_data, :qmin, -gen_data[:rating]),
                    max = get(gen_data, :qmax, gen_data[:rating])
                ),
                ramp_limits = (
                    up = get(gen_data, :ramp_up, gen_data[:pmax]),
                    down = get(gen_data, :ramp_down, gen_data[:pmax])
                ),
                time_limits = nothing,
                operation_cost = cost,
                base_power = base_mva
            )
            PSY.add_component!(sys, gen)
        end
    end
    
    # Add loads
    for load_data in json_data[:loads]
        bus = PSY.get_component(PSY.Bus, sys, load_data[:bus_name])
        
        load = PSY.PowerLoad(
            name = load_data[:name],
            available = get(load_data, :available, true),
            bus = bus,
            active_power = load_data[:active_power],
            reactive_power = load_data[:reactive_power],
            base_power = base_mva,
            max_active_power = load_data[:active_power] * 1.2,
            max_reactive_power = load_data[:reactive_power] * 1.2
        )
        PSY.add_component!(sys, load)
    end
    
    return sys
end

# ============================================================================
# Time Series Data Loading
# ============================================================================

"""
    load_time_series_data(db::DatabaseConnection, case_name::String, 
                         start_time::DateTime, end_time::DateTime)

Load time-series measurements for a case
"""
function load_time_series_data(
    db::DatabaseConnection, 
    case_name::String,
    start_time::DateTime,
    end_time::DateTime
)
    # Load power measurements
    power_query = """
        SELECT time, bus_id, voltage_magnitude, voltage_angle_rad,
               active_power_mw, reactive_power_mvar, frequency_hz
        FROM power_measurements
        WHERE case_name = \$1 
        AND time >= \$2 
        AND time <= \$3
        ORDER BY time, bus_id
    """
    
    power_data = DataFrame(execute(
        db.timeseries_conn, 
        power_query, 
        [case_name, start_time, end_time]
    ))
    
    # Load generator measurements
    gen_query = """
        SELECT time, generator_id, active_power_mw, reactive_power_mvar,
               commitment_status, marginal_cost
        FROM generator_measurements
        WHERE case_name = \$1 
        AND time >= \$2 
        AND time <= \$3
        ORDER BY time, generator_id
    """
    
    gen_data = DataFrame(execute(
        db.timeseries_conn,
        gen_query,
        [case_name, start_time, end_time]
    ))
    
    # Load load measurements
    load_query = """
        SELECT time, load_id, active_power_mw, reactive_power_mvar,
               forecasted_active_power_mw
        FROM load_measurements
        WHERE case_name = \$1 
        AND time >= \$2 
        AND time <= \$3
        ORDER BY time, load_id
    """
    
    load_data = DataFrame(execute(
        db.timeseries_conn,
        load_query,
        [case_name, start_time, end_time]
    ))
    
    return Dict(
        "power_measurements" => power_data,
        "generator_measurements" => gen_data,
        "load_measurements" => load_data
    )
end

"""
    attach_time_series_to_system!(sys::PSY.System, time_series_data::Dict)

Attach time-series data to PowerSystems components
"""
function attach_time_series_to_system!(sys::PSY.System, time_series_data::Dict)
    # Attach load time series
    load_data = time_series_data["load_measurements"]
    
    for load_id in unique(load_data.load_id)
        load_component = PSY.get_component(PSY.PowerLoad, sys, load_id)
        if isnothing(load_component)
            @warn "Load $load_id not found in system"
            continue
        end
        
        load_subset = filter(row -> row.load_id == load_id, load_data)
        times = load_subset.time
        values = load_subset.active_power_mw
        
        ts = PSY.SingleTimeSeries(
            name = "active_power",
            data = IS.TimeArray(times, values),
            scaling_factor_multiplier = PSY.get_active_power
        )
        
        PSY.add_time_series!(sys, load_component, ts)
    end
    
    return sys
end

# ============================================================================
# Contingency Loading
# ============================================================================

"""
    load_contingencies(db::DatabaseConnection, topology_id::Int)

Load contingency definitions for a topology
"""
function load_contingencies(db::DatabaseConnection, topology_id::Int)
    query = """
        SELECT contingency_id, contingency_name, contingency_type,
               affected_branches, affected_generators, probability
        FROM contingencies
        WHERE topology_id = \$1
        ORDER BY severity_level DESC, probability DESC
    """
    
    result = execute(db.metadata_conn, query, [topology_id])
    return DataFrame(result)
end

# ============================================================================
# Results Writing
# ============================================================================

"""
    save_execution_metadata(db::DatabaseConnection, execution_data::Dict)

Save LASCOPF execution metadata and return execution_id
"""
function save_execution_metadata(db::DatabaseConnection, execution_data::Dict)
    execution_id = uuid4()
    
    query = """
        INSERT INTO lascopf_executions (
            execution_id, execution_time, topology_id,
            optimization_horizon_hours, num_time_steps, num_contingencies,
            admm_rho, app_beta, app_gamma,
            max_iterations, convergence_tolerance,
            convergence_status, final_iteration, objective_value, solve_time_seconds,
            julia_version, triggered_by
        ) VALUES (
            \$1, \$2, \$3, \$4, \$5, \$6, \$7, \$8, \$9, \$10, \$11, 
            \$12, \$13, \$14, \$15, \$16, \$17
        )
    """
    
    execute(db.metadata_conn, query, [
        execution_id,
        get(execution_data, "execution_time", now()),
        execution_data["topology_id"],
        get(execution_data, "optimization_horizon_hours", 24),
        execution_data["num_time_steps"],
        execution_data["num_contingencies"],
        execution_data["admm_rho"],
        execution_data["app_beta"],
        execution_data["app_gamma"],
        execution_data["max_iterations"],
        execution_data["convergence_tolerance"],
        execution_data["convergence_status"],
        execution_data["final_iteration"],
        execution_data["objective_value"],
        execution_data["solve_time_seconds"],
        string(VERSION),
        get(execution_data, "triggered_by", "MANUAL")
    ])
    
    return execution_id
end

"""
    save_dispatch_results(db::DatabaseConnection, execution_id::UUID, 
                         dispatch_results::DataFrame)

Save generator dispatch results
"""
function save_dispatch_results(
    db::DatabaseConnection, 
    execution_id::UUID,
    dispatch_results::DataFrame
)
    # Batch insert for efficiency
    query = """
        INSERT INTO generator_dispatch_results (
            execution_id, time_step, target_datetime, generator_id,
            scenario_type, active_power_mw, reactive_power_mvar,
            commitment_status, generation_cost
        ) VALUES (
            \$1, \$2, \$3, \$4, \$5, \$6, \$7, \$8, \$9
        )
    """
    
    LibPQ.load!(
        dispatch_results,
        db.metadata_conn,
        "INSERT INTO generator_dispatch_results (
            execution_id, time_step, target_datetime, generator_id,
            scenario_type, active_power_mw, reactive_power_mvar,
            commitment_status, generation_cost
        ) VALUES (\$1, \$2, \$3, \$4, \$5, \$6, \$7, \$8, \$9)"
    )
    
    @info "Saved $(nrow(dispatch_results)) dispatch results"
end

"""
    save_bus_results(db::DatabaseConnection, execution_id::UUID, 
                    bus_results::DataFrame)

Save bus voltage and LMP results
"""
function save_bus_results(
    db::DatabaseConnection,
    execution_id::UUID,
    bus_results::DataFrame
)
    LibPQ.load!(
        bus_results,
        db.metadata_conn,
        "INSERT INTO bus_results (
            execution_id, time_step, target_datetime, bus_id,
            scenario_type, voltage_magnitude_pu, voltage_angle_rad,
            lmp_total
        ) VALUES (\$1, \$2, \$3, \$4, \$5, \$6, \$7, \$8)"
    )
    
    @info "Saved $(nrow(bus_results)) bus results"
end

"""
    save_convergence_history(db::DatabaseConnection, execution_id::UUID,
                            convergence_data::DataFrame)

Save convergence history for analysis
"""
function save_convergence_history(
    db::DatabaseConnection,
    execution_id::UUID,
    convergence_data::DataFrame
)
    LibPQ.load!(
        convergence_data,
        db.metadata_conn,
        "INSERT INTO convergence_history (
            execution_id, iteration, primal_residual, dual_residual,
            objective_value, iteration_time_seconds
        ) VALUES (\$1, \$2, \$3, \$4, \$5, \$6)"
    )
    
    @info "Saved convergence history for $(nrow(convergence_data)) iterations"
end

end # module DataLoader