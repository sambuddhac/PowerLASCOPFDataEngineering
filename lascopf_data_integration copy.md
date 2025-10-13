# PowerLASCOPF.jl Data Engineering Implementation Guide

## Project Structure Overview

```
PowerLASCOPF.jl/
├── src/
│   ├── PowerLASCOPF.jl          # Main module
│   ├── models/
│   │   └── solver_models/        # Your existing solver code
│   ├── data_interface/           # NEW: Data layer
│   │   ├── DataLoader.jl
│   │   ├── DataValidator.jl
│   │   └── ResultsWriter.jl
│   └── api/                      # NEW: API layer
│       └── Server.jl
├── example_cases/                # Your test cases
│   ├── RTS_GMLC/
│   ├── case5/
│   └── case118/
├── data_engineering/             # NEW: Python data engineering
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── load_examples.py
│   │   ├── scada_simulator.py
│   │   └── weather_api.py
│   ├── validation/
│   │   ├── expectations.py
│   │   └── schemas.py
│   ├── transformation/
│   │   ├── converters.py
│   │   └── powersystems_builder.py
│   └── orchestration/
│       └── airflow_dags/
│           ├── daily_pipeline.py
│           └── realtime_pipeline.py
├── database/                     # NEW: Database schemas
│   ├── migrations/
│   ├── init_timescale.sql
│   └── init_postgres.sql
├── docker/                       # NEW: Docker setup
│   ├── docker-compose.yml
│   ├── Dockerfile.julia
│   └── Dockerfile.airflow
├── config/                       # NEW: Configuration
│   ├── database.yml
│   └── pipeline_config.yml
└── tests/
    ├── data_pipeline/
    └── integration/
```

---

# STEP 1: Docker Compose Setup for Local Development

## 1.1 Create Database Infrastructure

Create `docker/docker-compose.yml`:

```yaml
version: '3.8'

services:
  # TimescaleDB for time-series power system measurements
  timescaledb:
    image: timescale/timescaledb:latest-pg15
    container_name: lascopf_timescale
    environment:
      POSTGRES_DB: lascopf_timeseries
      POSTGRES_USER: lascopf
      POSTGRES_PASSWORD: lascopf_pass_2024
    ports:
      - "5432:5432"
    volumes:
      - timescale_data:/var/lib/postgresql/data
      - ./database/init_timescale.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - lascopf_network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U lascopf"]
      interval: 10s
      timeout: 5s
      retries: 5

  # PostgreSQL for metadata and results
  postgres:
    image: postgres:15-alpine
    container_name: lascopf_postgres
    environment:
      POSTGRES_DB: lascopf_metadata
      POSTGRES_USER: lascopf
      POSTGRES_PASSWORD: lascopf_pass_2024
    ports:
      - "5433:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./database/init_postgres.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - lascopf_network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U lascopf"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Redis for caching and Airflow broker
  redis:
    image: redis:7-alpine
    container_name: lascopf_redis
    ports:
      - "6379:6379"
    networks:
      - lascopf_network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  # MinIO for data lake storage
  minio:
    image: minio/minio:latest
    container_name: lascopf_minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: lascopf
      MINIO_ROOT_PASSWORD: lascopf_minio_2024
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data
    networks:
      - lascopf_network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3

  # Airflow PostgreSQL backend
  airflow-db:
    image: postgres:15-alpine
    container_name: lascopf_airflow_db
    environment:
      POSTGRES_DB: airflow
      POSTGRES_USER: airflow
      POSTGRES_PASSWORD: airflow
    volumes:
      - airflow_db_data:/var/lib/postgresql/data
    networks:
      - lascopf_network

  # Airflow Webserver
  airflow-webserver:
    build:
      context: .
      dockerfile: Dockerfile.airflow
    container_name: lascopf_airflow_webserver
    command: webserver
    environment:
      AIRFLOW__CORE__EXECUTOR: CeleryExecutor
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@airflow-db/airflow
      AIRFLOW__CELERY__RESULT_BACKEND: db+postgresql://airflow:airflow@airflow-db/airflow
      AIRFLOW__CELERY__BROKER_URL: redis://redis:6379/0
      AIRFLOW__CORE__FERNET_KEY: ''
      AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: 'true'
      AIRFLOW__CORE__LOAD_EXAMPLES: 'false'
      AIRFLOW__API__AUTH_BACKENDS: 'airflow.api.auth.backend.basic_auth'
      _AIRFLOW_DB_UPGRADE: 'true'
      _AIRFLOW_WWW_USER_CREATE: 'true'
      _AIRFLOW_WWW_USER_USERNAME: airflow
      _AIRFLOW_WWW_USER_PASSWORD: airflow
    volumes:
      - ./data_engineering/orchestration/airflow_dags:/opt/airflow/dags
      - ./data_engineering:/opt/airflow/plugins/data_engineering
      - ./example_cases:/opt/airflow/example_cases
      - airflow_logs:/opt/airflow/logs
    ports:
      - "8080:8080"
    networks:
      - lascopf_network
    depends_on:
      airflow-db:
        condition: service_started
      redis:
        condition: service_healthy

  # Airflow Scheduler
  airflow-scheduler:
    build:
      context: .
      dockerfile: Dockerfile.airflow
    container_name: lascopf_airflow_scheduler
    command: scheduler
    environment:
      AIRFLOW__CORE__EXECUTOR: CeleryExecutor
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@airflow-db/airflow
      AIRFLOW__CELERY__RESULT_BACKEND: db+postgresql://airflow:airflow@airflow-db/airflow
      AIRFLOW__CELERY__BROKER_URL: redis://redis:6379/0
    volumes:
      - ./data_engineering/orchestration/airflow_dags:/opt/airflow/dags
      - ./data_engineering:/opt/airflow/plugins/data_engineering
      - ./example_cases:/opt/airflow/example_cases
      - airflow_logs:/opt/airflow/logs
    networks:
      - lascopf_network
    depends_on:
      airflow-webserver:
        condition: service_started

  # Airflow Worker
  airflow-worker:
    build:
      context: .
      dockerfile: Dockerfile.airflow
    container_name: lascopf_airflow_worker
    command: celery worker
    environment:
      AIRFLOW__CORE__EXECUTOR: CeleryExecutor
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@airflow-db/airflow
      AIRFLOW__CELERY__RESULT_BACKEND: db+postgresql://airflow:airflow@airflow-db/airflow
      AIRFLOW__CELERY__BROKER_URL: redis://redis:6379/0
    volumes:
      - ./data_engineering/orchestration/airflow_dags:/opt/airflow/dags
      - ./data_engineering:/opt/airflow/plugins/data_engineering
      - ./example_cases:/opt/airflow/example_cases
      - airflow_logs:/opt/airflow/logs
    networks:
      - lascopf_network
    depends_on:
      airflow-scheduler:
        condition: service_started

  # Julia Solver Container
  julia-solver:
    build:
      context: .
      dockerfile: Dockerfile.julia
    container_name: lascopf_julia_solver
    environment:
      JULIA_NUM_THREADS: 8
      DATABASE_URL: postgresql://lascopf:lascopf_pass_2024@postgres:5432/lascopf_metadata
      TIMESCALE_URL: postgresql://lascopf:lascopf_pass_2024@timescaledb:5432/lascopf_timeseries
    volumes:
      - ./:/app
      - julia_depot:/root/.julia
    networks:
      - lascopf_network
    depends_on:
      postgres:
        condition: service_healthy
      timescaledb:
        condition: service_healthy
    command: julia --project=/app -e "using Pkg; Pkg.instantiate(); using PowerLASCOPF"

  # Grafana for monitoring
  grafana:
    image: grafana/grafana:latest
    container_name: lascopf_grafana
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_INSTALL_PLUGINS: grafana-clock-panel
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards
      - ./monitoring/grafana/datasources:/etc/grafana/provisioning/datasources
    networks:
      - lascopf_network
    depends_on:
      - postgres
      - timescaledb

volumes:
  timescale_data:
  postgres_data:
  minio_data:
  airflow_db_data:
  airflow_logs:
  julia_depot:
  grafana_data:

networks:
  lascopf_network:
    driver: bridge
```

## 1.2 Create Dockerfiles

Create `docker/Dockerfile.airflow`:

```dockerfile
FROM apache/airflow:2.8.0-python3.10

USER root

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Install Python packages
COPY data_engineering/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Install Julia (for calling Julia from Python)
RUN pip install --no-cache-dir julia

WORKDIR /opt/airflow
```

Create `docker/Dockerfile.julia`:

```dockerfile
FROM julia:1.10

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    postgresql-client \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY Project.toml Manifest.toml ./

# Instantiate Julia environment
RUN julia --project=. -e 'using Pkg; Pkg.instantiate()'

# Pre-compile packages
RUN julia --project=. -e 'using Pkg; Pkg.precompile()'

COPY . .

# Set Julia to use multiple threads
ENV JULIA_NUM_THREADS=8

CMD ["julia", "--project=.", "-e", "using PowerLASCOPF"]
```

Create `data_engineering/requirements.txt`:

```
apache-airflow==2.8.0
apache-airflow-providers-postgres==5.9.0
psycopg2-binary==2.9.9
pandas==2.1.4
numpy==1.26.2
sqlalchemy==2.0.23
great-expectations==0.18.8
pydantic==2.5.3
fastapi==0.108.0
uvicorn==0.25.0
python-dotenv==1.0.0
boto3==1.34.19
minio==7.2.0
redis==5.0.1
pyarrow==14.0.2
```

---

# STEP 2: Database Schema Design

## 2.1 TimescaleDB Schema for Time-Series Data

Create `database/init_timescale.sql`:

```sql
-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ============================================================================
-- POWER MEASUREMENTS TABLE (Real-time and historical measurements)
-- ============================================================================
CREATE TABLE power_measurements (
    time TIMESTAMPTZ NOT NULL,
    measurement_id UUID DEFAULT gen_random_uuid(),
    bus_id TEXT NOT NULL,
    bus_name TEXT,
    -- Voltage measurements
    voltage_magnitude DOUBLE PRECISION,
    voltage_angle_rad DOUBLE PRECISION,
    -- Active and reactive power
    active_power_mw DOUBLE PRECISION,
    reactive_power_mvar DOUBLE PRECISION,
    -- Frequency
    frequency_hz DOUBLE PRECISION DEFAULT 60.0,
    -- Data quality
    measurement_quality INTEGER DEFAULT 100, -- 0-100 quality indicator
    source TEXT, -- 'SCADA', 'PMU', 'SIMULATED'
    -- Metadata
    scenario_id TEXT,
    case_name TEXT,
    PRIMARY KEY (time, bus_id)
);

-- Convert to hypertable with 1-day chunks
SELECT create_hypertable('power_measurements', 'time', chunk_time_interval => INTERVAL '1 day');

-- Create indexes for faster queries
CREATE INDEX idx_power_meas_bus ON power_measurements (bus_id, time DESC);
CREATE INDEX idx_power_meas_scenario ON power_measurements (scenario_id, time DESC);
CREATE INDEX idx_power_meas_case ON power_measurements (case_name, time DESC);

-- ============================================================================
-- GENERATOR MEASUREMENTS TABLE
-- ============================================================================
CREATE TABLE generator_measurements (
    time TIMESTAMPTZ NOT NULL,
    measurement_id UUID DEFAULT gen_random_uuid(),
    generator_id TEXT NOT NULL,
    generator_name TEXT,
    bus_id TEXT NOT NULL,
    -- Power output
    active_power_mw DOUBLE PRECISION,
    reactive_power_mvar DOUBLE PRECISION,
    -- Status
    commitment_status BOOLEAN,
    available_capacity_mw DOUBLE PRECISION,
    -- Fuel and costs
    fuel_consumption DOUBLE PRECISION,
    marginal_cost DOUBLE PRECISION,
    -- Constraints
    ramp_rate_actual DOUBLE PRECISION,
    -- Metadata
    generator_type TEXT, -- 'THERMAL', 'HYDRO', 'WIND', 'SOLAR', 'STORAGE'
    source TEXT,
    scenario_id TEXT,
    case_name TEXT,
    PRIMARY KEY (time, generator_id)
);

SELECT create_hypertable('generator_measurements', 'time', chunk_time_interval => INTERVAL '1 day');

CREATE INDEX idx_gen_meas_gen ON generator_measurements (generator_id, time DESC);
CREATE INDEX idx_gen_meas_bus ON generator_measurements (bus_id, time DESC);
CREATE INDEX idx_gen_meas_type ON generator_measurements (generator_type, time DESC);

-- ============================================================================
-- BRANCH/LINE MEASUREMENTS TABLE
-- ============================================================================
CREATE TABLE branch_measurements (
    time TIMESTAMPTZ NOT NULL,
    measurement_id UUID DEFAULT gen_random_uuid(),
    branch_id TEXT NOT NULL,
    branch_name TEXT,
    from_bus_id TEXT NOT NULL,
    to_bus_id TEXT NOT NULL,
    -- Power flows
    from_bus_active_power_mw DOUBLE PRECISION,
    from_bus_reactive_power_mvar DOUBLE PRECISION,
    to_bus_active_power_mw DOUBLE PRECISION,
    to_bus_reactive_power_mvar DOUBLE PRECISION,
    -- Current and loading
    current_magnitude_pu DOUBLE PRECISION,
    loading_percentage DOUBLE PRECISION,
    -- Status
    in_service BOOLEAN DEFAULT TRUE,
    -- Metadata
    source TEXT,
    scenario_id TEXT,
    case_name TEXT,
    PRIMARY KEY (time, branch_id)
);

SELECT create_hypertable('branch_measurements', 'time', chunk_time_interval => INTERVAL '1 day');

CREATE INDEX idx_branch_meas_branch ON branch_measurements (branch_id, time DESC);
CREATE INDEX idx_branch_meas_buses ON branch_measurements (from_bus_id, to_bus_id, time DESC);

-- ============================================================================
-- LOAD MEASUREMENTS TABLE
-- ============================================================================
CREATE TABLE load_measurements (
    time TIMESTAMPTZ NOT NULL,
    measurement_id UUID DEFAULT gen_random_uuid(),
    load_id TEXT NOT NULL,
    load_name TEXT,
    bus_id TEXT NOT NULL,
    -- Load values
    active_power_mw DOUBLE PRECISION,
    reactive_power_mvar DOUBLE PRECISION,
    -- Forecast vs actual
    forecasted_active_power_mw DOUBLE PRECISION,
    forecast_error_mw DOUBLE PRECISION,
    -- Metadata
    load_type TEXT, -- 'RESIDENTIAL', 'COMMERCIAL', 'INDUSTRIAL'
    source TEXT,
    scenario_id TEXT,
    case_name TEXT,
    PRIMARY KEY (time, load_id)
);

SELECT create_hypertable('load_measurements', 'time', chunk_time_interval => INTERVAL '1 day');

CREATE INDEX idx_load_meas_load ON load_measurements (load_id, time DESC);
CREATE INDEX idx_load_meas_bus ON load_measurements (bus_id, time DESC);

-- ============================================================================
-- RENEWABLE FORECAST TABLE
-- ============================================================================
CREATE TABLE renewable_forecasts (
    forecast_time TIMESTAMPTZ NOT NULL,
    target_time TIMESTAMPTZ NOT NULL,
    generator_id TEXT NOT NULL,
    -- Forecasted values
    forecasted_power_mw DOUBLE PRECISION,
    confidence_lower_mw DOUBLE PRECISION,
    confidence_upper_mw DOUBLE PRECISION,
    -- Forecast metadata
    forecast_horizon_hours INTEGER,
    forecast_model TEXT,
    scenario_id TEXT,
    PRIMARY KEY (forecast_time, target_time, generator_id)
);

SELECT create_hypertable('renewable_forecasts', 'forecast_time', chunk_time_interval => INTERVAL '1 day');

CREATE INDEX idx_renewable_fc_gen ON renewable_forecasts (generator_id, target_time DESC);

-- ============================================================================
-- CONTINUOUS AGGREGATES FOR ANALYTICS
-- ============================================================================

-- Hourly average power measurements
CREATE MATERIALIZED VIEW power_measurements_hourly
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 hour', time) AS bucket,
    bus_id,
    case_name,
    AVG(voltage_magnitude) as avg_voltage,
    AVG(active_power_mw) as avg_active_power,
    AVG(reactive_power_mvar) as avg_reactive_power,
    MIN(voltage_magnitude) as min_voltage,
    MAX(voltage_magnitude) as max_voltage,
    COUNT(*) as measurement_count
FROM power_measurements
GROUP BY bucket, bus_id, case_name;

-- Refresh policy: update every hour
SELECT add_continuous_aggregate_policy('power_measurements_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');

-- Daily generator statistics
CREATE MATERIALIZED VIEW generator_daily_stats
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 day', time) AS day,
    generator_id,
    generator_type,
    case_name,
    AVG(active_power_mw) as avg_generation,
    MAX(active_power_mw) as peak_generation,
    SUM(active_power_mw) as total_generation_mwh, -- Assuming hourly data
    AVG(marginal_cost) as avg_marginal_cost
FROM generator_measurements
GROUP BY day, generator_id, generator_type, case_name;

SELECT add_continuous_aggregate_policy('generator_daily_stats',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day');

-- ============================================================================
-- DATA QUALITY METRICS TABLE
-- ============================================================================
CREATE TABLE data_quality_metrics (
    metric_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    check_time TIMESTAMP DEFAULT NOW(),
    table_name TEXT NOT NULL,
    metric_type TEXT NOT NULL, -- 'COMPLETENESS', 'VALIDITY', 'CONSISTENCY'
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION,
    pass_fail TEXT, -- 'PASS', 'FAIL', 'WARNING'
    details JSONB,
    affected_records INTEGER
);

CREATE INDEX idx_quality_time ON data_quality_metrics (check_time DESC);
CREATE INDEX idx_quality_table ON data_quality_metrics (table_name, metric_type);

-- ============================================================================
-- PIPELINE EXECUTION LOGS TABLE
-- ============================================================================
CREATE TABLE pipeline_execution_logs (
    log_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    pipeline_name TEXT NOT NULL,
    dag_run_id TEXT,
    task_id TEXT,
    execution_date TIMESTAMP NOT NULL,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    status TEXT, -- 'RUNNING', 'SUCCESS', 'FAILED'
    error_message TEXT,
    records_processed INTEGER,
    metadata JSONB
);

CREATE INDEX idx_pipeline_logs_name ON pipeline_execution_logs (pipeline_name, execution_date DESC);
CREATE INDEX idx_pipeline_logs_status ON pipeline_execution_logs (status);

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- Latest execution results summary
CREATE VIEW v_latest_executions AS
SELECT 
    e.execution_id,
    e.execution_time,
    t.case_name,
    e.convergence_status,
    e.objective_value,
    e.solve_time_seconds,
    e.num_time_steps,
    e.num_contingencies,
    COUNT(DISTINCT gd.generator_id) as num_generators_dispatched
FROM lascopf_executions e
LEFT JOIN network_topology t ON e.topology_id = t.topology_id
LEFT JOIN generator_dispatch_results gd ON e.execution_id = gd.execution_id
GROUP BY e.execution_id, e.execution_time, t.case_name, e.convergence_status, 
         e.objective_value, e.solve_time_seconds, e.num_time_steps, e.num_contingencies
ORDER BY e.execution_time DESC
LIMIT 100;

-- Generator dispatch summary
CREATE VIEW v_generator_dispatch_summary AS
SELECT 
    gd.execution_id,
    gd.time_step,
    gd.target_datetime,
    gd.scenario_type,
    COUNT(*) as num_generators,
    SUM(gd.active_power_mw) as total_generation_mw,
    SUM(gd.generation_cost) as total_generation_cost,
    AVG(gd.active_power_mw) as avg_generation_per_unit
FROM generator_dispatch_results gd
GROUP BY gd.execution_id, gd.time_step, gd.target_datetime, gd.scenario_type;

-- System-wide LMP statistics
CREATE VIEW v_lmp_statistics AS
SELECT 
    br.execution_id,
    br.time_step,
    br.target_datetime,
    br.scenario_type,
    AVG(br.lmp_total) as avg_lmp,
    MIN(br.lmp_total) as min_lmp,
    MAX(br.lmp_total) as max_lmp,
    STDDEV(br.lmp_total) as lmp_std_dev,
    MAX(br.lmp_total) - MIN(br.lmp_total) as lmp_spread
FROM bus_results br
GROUP BY br.execution_id, br.time_step, br.target_datetime, br.scenario_type; RETENTION POLICIES
-- ============================================================================

-- Keep raw measurements for 90 days, then compress
SELECT add_compression_policy('power_measurements', INTERVAL '7 days');
SELECT add_retention_policy('power_measurements', INTERVAL '90 days');

SELECT add_compression_policy('generator_measurements', INTERVAL '7 days');
SELECT add_retention_policy('generator_measurements', INTERVAL '90 days');

SELECT add_compression_policy('branch_measurements', INTERVAL '7 days');
SELECT add_retention_policy('branch_measurements', INTERVAL '90 days');

-- Keep forecasts for 30 days
SELECT add_compression_policy('renewable_forecasts', INTERVAL '3 days');
SELECT add_retention_policy('renewable_forecasts', INTERVAL '30 days');
```

## 2.2 PostgreSQL Schema for Metadata and Results

Create `database/init_postgres.sql`:

```sql
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- NETWORK TOPOLOGY TABLE
-- ============================================================================
CREATE TABLE network_topology (
    topology_id SERIAL PRIMARY KEY,
    case_name TEXT NOT NULL UNIQUE,
    version INTEGER DEFAULT 1,
    -- Topology characteristics
    num_buses INTEGER,
    num_generators INTEGER,
    num_branches INTEGER,
    num_loads INTEGER,
    base_mva DOUBLE PRECISION DEFAULT 100.0,
    -- System data (JSON representation of PowerSystems.System)
    system_data JSONB NOT NULL,
    -- PowerSystems.jl serialized data
    powersystems_file_path TEXT,
    -- Validity period
    valid_from TIMESTAMP DEFAULT NOW(),
    valid_until TIMESTAMP,
    -- Metadata
    description TEXT,
    source TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by TEXT
);

CREATE INDEX idx_topology_case ON network_topology (case_name);
CREATE INDEX idx_topology_valid ON network_topology (valid_from, valid_until);

-- ============================================================================
-- CONTINGENCY DEFINITIONS TABLE
-- ============================================================================
CREATE TABLE contingencies (
    contingency_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    topology_id INTEGER REFERENCES network_topology(topology_id),
    contingency_name TEXT NOT NULL,
    contingency_type TEXT NOT NULL, -- 'N-1', 'N-1-1', 'N-2'
    -- Affected elements
    affected_branches TEXT[], -- Array of branch IDs
    affected_generators TEXT[], -- Array of generator IDs
    -- Probability and severity
    probability DOUBLE PRECISION DEFAULT 0.01,
    severity_level INTEGER DEFAULT 1, -- 1-5 scale
    -- Metadata
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_contingency_topology ON contingencies (topology_id);
CREATE INDEX idx_contingency_type ON contingencies (contingency_type);

-- ============================================================================
-- LASCOPF EXECUTION RECORDS TABLE
-- ============================================================================
CREATE TABLE lascopf_executions (
    execution_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    execution_time TIMESTAMP NOT NULL DEFAULT NOW(),
    topology_id INTEGER REFERENCES network_topology(topology_id),
    -- Execution parameters
    optimization_horizon_hours INTEGER,
    num_time_steps INTEGER,
    num_contingencies INTEGER,
    -- Algorithm parameters
    admm_rho DOUBLE PRECISION,
    app_beta DOUBLE PRECISION,
    app_gamma DOUBLE PRECISION,
    max_iterations INTEGER,
    convergence_tolerance DOUBLE PRECISION,
    -- Execution results
    convergence_status TEXT, -- 'CONVERGED', 'MAX_ITERATIONS', 'INFEASIBLE'
    final_iteration INTEGER,
    objective_value DOUBLE PRECISION,
    solve_time_seconds DOUBLE PRECISION,
    -- Performance metrics
    avg_iteration_time_seconds DOUBLE PRECISION,
    peak_memory_mb DOUBLE PRECISION,
    num_parallel_workers INTEGER,
    -- File paths
    results_file_path TEXT,
    log_file_path TEXT,
    -- Metadata
    triggered_by TEXT, -- 'SCHEDULED', 'MANUAL', 'EVENT'
    airflow_dag_run_id TEXT,
    git_commit_hash TEXT,
    julia_version TEXT,
    notes TEXT
);

CREATE INDEX idx_exec_time ON lascopf_executions (execution_time DESC);
CREATE INDEX idx_exec_topology ON lascopf_executions (topology_id);
CREATE INDEX idx_exec_status ON lascopf_executions (convergence_status);

-- ============================================================================
-- GENERATOR DISPATCH RESULTS TABLE
-- ============================================================================
CREATE TABLE generator_dispatch_results (
    result_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    execution_id UUID REFERENCES lascopf_executions(execution_id) ON DELETE CASCADE,
    time_step INTEGER NOT NULL,
    target_datetime TIMESTAMP,
    generator_id TEXT NOT NULL,
    scenario_type TEXT DEFAULT 'BASE', -- 'BASE', 'CONTINGENCY_1', etc.
    -- Dispatch values
    active_power_mw DOUBLE PRECISION,
    reactive_power_mvar DOUBLE PRECISION,
    commitment_status BOOLEAN,
    -- Costs
    generation_cost DOUBLE PRECISION,
    startup_cost DOUBLE PRECISION,
    shutdown_cost DOUBLE PRECISION,
    -- Constraints status
    at_pmin BOOLEAN DEFAULT FALSE,
    at_pmax BOOLEAN DEFAULT FALSE,
    ramp_limited BOOLEAN DEFAULT FALSE,
    -- Shadow prices
    lambda_p DOUBLE PRECISION,
    lambda_q DOUBLE PRECISION
);

CREATE INDEX idx_dispatch_exec ON generator_dispatch_results (execution_id, time_step);
CREATE INDEX idx_dispatch_gen ON generator_dispatch_results (generator_id, target_datetime);
CREATE INDEX idx_dispatch_scenario ON generator_dispatch_results (execution_id, scenario_type);

-- ============================================================================
-- BUS RESULTS TABLE
-- ============================================================================
CREATE TABLE bus_results (
    result_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    execution_id UUID REFERENCES lascopf_executions(execution_id) ON DELETE CASCADE,
    time_step INTEGER NOT NULL,
    target_datetime TIMESTAMP,
    bus_id TEXT NOT NULL,
    scenario_type TEXT DEFAULT 'BASE',
    -- Voltage solution
    voltage_magnitude_pu DOUBLE PRECISION,
    voltage_angle_rad DOUBLE PRECISION,
    -- Power balance
    net_injection_mw DOUBLE PRECISION,
    net_injection_mvar DOUBLE PRECISION,
    -- Shadow prices (locational marginal prices)
    lmp_energy DOUBLE PRECISION,
    lmp_congestion DOUBLE PRECISION,
    lmp_loss DOUBLE PRECISION,
    lmp_total DOUBLE PRECISION
);

CREATE INDEX idx_bus_results_exec ON bus_results (execution_id, time_step);
CREATE INDEX idx_bus_results_bus ON bus_results (bus_id, target_datetime);

-- ============================================================================
-- BRANCH FLOW RESULTS TABLE
-- ============================================================================
CREATE TABLE branch_flow_results (
    result_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    execution_id UUID REFERENCES lascopf_executions(execution_id) ON DELETE CASCADE,
    time_step INTEGER NOT NULL,
    target_datetime TIMESTAMP,
    branch_id TEXT NOT NULL,
    scenario_type TEXT DEFAULT 'BASE',
    -- Power flows
    from_bus_active_power_mw DOUBLE PRECISION,
    from_bus_reactive_power_mvar DOUBLE PRECISION,
    to_bus_active_power_mw DOUBLE PRECISION,
    to_bus_reactive_power_mvar DOUBLE PRECISION,
    -- Loading
    loading_percentage DOUBLE PRECISION,
    -- Constraint status
    flow_constrained BOOLEAN DEFAULT FALSE,
    shadow_price DOUBLE PRECISION
);

CREATE INDEX idx_branch_results_exec ON branch_flow_results (execution_id, time_step);
CREATE INDEX idx_branch_results_branch ON branch_flow_results (branch_id, target_datetime);

-- ============================================================================
-- CONVERGENCE HISTORY TABLE
-- ============================================================================
CREATE TABLE convergence_history (
    history_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    execution_id UUID REFERENCES lascopf_executions(execution_id) ON DELETE CASCADE,
    iteration INTEGER NOT NULL,
    -- Residuals
    primal_residual DOUBLE PRECISION,
    dual_residual DOUBLE PRECISION,
    -- Objective values
    objective_value DOUBLE PRECISION,
    -- Timing
    iteration_time_seconds DOUBLE PRECISION,
    cumulative_time_seconds DOUBLE PRECISION,
    -- Metadata
    recorded_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_conv_history_exec ON convergence_history (execution_id, iteration);

-- ============================================================================
-- DATA