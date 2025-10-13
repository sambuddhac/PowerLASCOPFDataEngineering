# PowerLASCOPF.jl Complete Implementation Guide

## Prerequisites Installation

### 1. Install Docker and Docker Compose

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install docker.io docker-compose

# macOS
brew install docker docker-compose

# Verify installation
docker --version
docker-compose --version
```

### 2. Clone Your Repository

```bash
git clone https://github.com/sambuddhac/PowerLASCOPF.jl.git
cd PowerLASCOPF.jl
git checkout sams_POMDP_integration
```

---

## STEP 1: Set Up Docker Infrastructure (30 minutes)

### 1.1 Create Directory Structure

```bash
# From PowerLASCOPF.jl root directory
mkdir -p docker
mkdir -p database
mkdir -p data_engineering/{ingestion,validation,transformation,orchestration/airflow_dags}
mkdir -p scripts
mkdir -p config
mkdir -p monitoring/grafana/{dashboards,datasources}
```

### 1.2 Copy Docker Files

Copy the `docker-compose.yml` and Dockerfiles from the artifacts I provided into the `docker/` directory.

```bash
# Move to docker directory
cd docker

# Copy docker-compose.yml (from artifact)
# Copy Dockerfile.julia (from artifact)
# Copy Dockerfile.airflow (from artifact)
```

### 1.3 Create Database Initialization Scripts

Copy the SQL scripts from the artifacts:

```bash
# Copy init_timescale.sql to database/
# Copy init_postgres.sql to database/
```

### 1.4 Create Environment File

Create `docker/.env`:

```bash
cat > docker/.env << 'EOF'
# Database passwords
DB_PASSWORD=lascopf_pass_2024
MINIO_PASSWORD=lascopf_minio_2024

# Airflow
AIRFLOW_UID=50000
AIRFLOW_GID=0

# Julia
JULIA_NUM_THREADS=8
EOF
```

### 1.5 Start Docker Infrastructure

```bash
cd docker

# Start all services
docker-compose up -d

# Check status
docker-compose ps

# You should see all services running:
# - timescaledb
# - postgres
# - redis
# - minio
# - airflow-webserver
# - airflow-scheduler
# - airflow-worker
# - julia-solver
# - grafana
```

### 1.6 Verify Database Connections

```bash
# Test TimescaleDB
docker exec lascopf_timescale psql -U lascopf -d lascopf_timeseries -c "SELECT version();"

# Test PostgreSQL
docker exec lascopf_postgres psql -U lascopf -d lascopf_metadata -c "SELECT version();"

# Check tables were created
docker exec lascopf_timescale psql -U lascopf -d lascopf_timeseries -c "\dt"
docker exec lascopf_postgres psql -U lascopf -d lascopf_metadata -c "\dt"
```

### 1.7 Access Web Interfaces

- **Airflow**: http://localhost:8080 (user: airflow, password: airflow)
- **MinIO Console**: http://localhost:9001 (user: lascopf, password: lascopf_minio_2024)
- **Grafana**: http://localhost:3000 (user: admin, password: admin)

---

## STEP 2: Set Up Julia Data Interface (45 minutes)

### 2.1 Add Required Julia Packages

Update your `Project.toml`:

```toml
[deps]
PowerSystems = "bcd98974-b02a-5e2f-9ee0-a103f5c450dd"
PowerSimulations = "e690365d-45e2-57bb-ac84-44ba829e73c4"
InfrastructureSystems = "2cd47ed4-ca9b-11e9-27f2-ab636fb57511"
LibPQ = "194296ae-ab2e-5f79-8cd4-7183a0a5a0d1"
DataFrames = "a93c6f00-e57d-5684-b7b6-d8193f3e46c0"
JSON3 = "0f8b85d8-7281-11e9-16c2-39a750bddbf1"
UUIDs = "cf7118a7-6976-5b1a-9a39-7adc72f591a4"
Dates = "ade2ca70-3891-5945-98fb-dc099432e06a"
JuMP = "4076af6c-e467-56ae-b986-b466b2749572"
Ipopt = "b6b21f68-93f8-5de0-b562-5493be1d77c9"
```

Install packages:

```bash
cd PowerLASCOPF.jl

# Start Julia REPL
julia --project=.

# In Julia REPL:
julia> using Pkg
julia> Pkg.instantiate()
julia> Pkg.add(["LibPQ", "JSON3"])
julia> Pkg.precompile()
```

### 2.2 Create Data Interface Module

Create the file structure:

```bash
mkdir -p src/data_interface
touch src/data_interface/DataLoader.jl
touch src/data_interface/DataValidator.jl
touch src/data_interface/ResultsWriter.jl
```

Copy the `DataLoader.jl` code from the artifact into `src/data_interface/DataLoader.jl`.

### 2.3 Update Main Module

Edit `src/PowerLASCOPF.jl` to include the data interface:

```julia
module PowerLASCOPF

using Reexport

# Core dependencies
@reexport using PowerSystems
@reexport using PowerSimulations
@reexport using InfrastructureSystems

# Your existing includes
include("models/solver_models/solver_model_types.jl")
include("models/solver_models/ExtendedThermalGenerationCost.jl")
include("models/solver_models/gensolver_first_base.jl")

# NEW: Data interface
include("data_interface/DataLoader.jl")
using .DataLoader

export DataLoader,
       DatabaseConnection,
       load_network_topology,
       load_time_series_data,
       save_execution_metadata,
       save_dispatch_results

end # module
```

### 2.4 Test Database Connection

Create a test script `scripts/test_db_connection.jl`:

```julia
using PowerLASCOPF

# Test database connection
db = DatabaseConnection()

println("✓ Database connections established")

# Test query
using LibPQ
result = execute(db.metadata_conn, "SELECT COUNT(*) FROM network_topology")
println("Network topologies in database: ", first(result)[1])

close(db)
println("✓ Connection closed successfully")
```

Run the test:

```bash
julia --project=. scripts/test_db_connection.jl
```

---

## STEP 3: Set Up Python Data Pipeline (60 minutes)

### 3.1 Create Python Package Structure

```bash
cd data_engineering

# Create __init__.py files
touch __init__.py
touch ingestion/__init__.py
touch validation/__init__.py
touch transformation/__init__.py
```

### 3.2 Install Python Dependencies

Create `data_engineering/requirements.txt` (from artifact) and install:

```bash
cd data_engineering
pip install -r requirements.txt

# Or use virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3.3 Set Up Great Expectations

```bash
cd data_engineering

# Initialize Great Expectations
great_expectations init

# This creates a gx/ directory with configuration
```

### 3.4 Configure Great Expectations for PostgreSQL

Edit `data_engineering/gx/great_expectations.yml`:

```yaml
datasources:
  postgres_datasource:
    class_name: Datasource
    execution_engine:
      class_name: SqlAlchemyExecutionEngine
      connection_string: postgresql://lascopf:lascopf_pass_2024@localhost:5432/lascopf_timeseries
    data_connectors:
      default_inferred_data_connector:
        class_name: InferredAssetSqlDataConnector
        include_schema_name: true
```

### 3.5 Create Validation Scripts

Copy the `expectations.py` and `load_examples.py` code from artifacts into:
- `data_engineering/validation/expectations.py`
- `data_engineering/ingestion/load_examples.py`

### 3.6 Test Data Validation

Create `scripts/test_validation.py`:

```python
import sys
sys.path.insert(0, 'data_engineering')

from validation.expectations import PowerSystemDataValidator

# Initialize validator
validator = PowerSystemDataValidator()

# Create expectation suites
print("Creating expectation suites...")
validator.create_power_measurements_suite()
validator.create_generator_measurements_suite()
validator.create_branch_measurements_suite()

print("✓ Validation suites created successfully")
```

Run:

```bash
python scripts/test_validation.py
```

---

## STEP 4: Configure Airflow Pipeline (45 minutes)

### 4.1 Set Up Airflow Connections

Access Airflow UI at http://localhost:8080 and add connections:

**Connection 1: lascopf_metadata**
- Conn Id: `lascopf_metadata`
- Conn Type: `Postgres`
- Host: `postgres`
- Schema: `lascopf_metadata`
- Login: `lascopf`
- Password: `lascopf_pass_2024`
- Port: `5432`

**Connection 2: lascopf_timeseries**
- Conn Id: `lascopf_timeseries`
- Conn Type: `Postgres`
- Host: `timescaledb`
- Schema: `lascopf_timeseries`
- Login: `lascopf`
- Password: `lascopf_pass_2024`
- Port: `5432`

### 4.2 Copy DAG File

Copy the `daily_pipeline.py` from artifact to:

```bash
cp <from_artifact> data_engineering/orchestration/airflow_dags/daily_pipeline.py
```

### 4.3 Verify DAG in Airflow

1. Go to Airflow UI: http://localhost:8080
2. Click on "DAGs" - you should see `lascopf_daily_pipeline`
3. Toggle the DAG to "On"
4. Click on the DAG name to view the graph

### 4.4 Test DAG Components

Click "Trigger DAG" with configuration:

```json
{
  "case_name": "case5",
  "test_mode": true
}
```

Monitor the execution in the Airflow UI.

---

## STEP 5: Load Example Data and Run Complete Pipeline (90 minutes)

### 5.1 Prepare Example Case Data

Create a script to load your example cases:

```bash
# Create script
cat > scripts/load_example_cases.py << 'EOF'
import sys
sys.path.insert(0, 'data_engineering')

from ingestion.load_examples import ExampleCaseLoader

db_config = {
    "metadata": {
        "host": "localhost",
        "port": 5433,
        "database": "lascopf_metadata",
        "user": "lascopf",
        "password": "lascopf_pass_2024"
    },
    "timeseries": {
        "host": "localhost",
        "port": 5432,
        "database": "lascopf_timeseries",
        "user": "lascopf",
        "password": "lascopf_pass_2024"
    }
}

loader = ExampleCaseLoader(db_config)
loader.connect()

try:
    # Load case5 example
    print("Loading case5...")
    topology_id = loader.load_case_from_matpower(
        "example_cases/case5.m",
        "case5"
    )
    print(f"✓ Loaded case5 with topology_id={topology_id}")
    
    # Load case118 example
    print("Loading case118...")
    topology_id = loader.load_case_from_matpower(
        "example_cases/case118.m",
        "case118"
    )
    print(f"✓ Loaded case118 with topology_id={topology_id}")
    
finally:
    loader.close()

print("\n✓ All example cases loaded successfully!")
EOF
```

Run the script:

```bash
python scripts/load_example_cases.py
```

### 5.2 Verify Data in Database

```bash
# Check network topologies
docker exec lascopf_postgres psql -U lascopf -d lascopf_metadata -c \
  "SELECT topology_id, case_name, num_buses, num_generators FROM network_topology;"

# Check time-series data
docker exec lascopf_timescale psql -U lascopf -d lascopf_timeseries -c \
  "SELECT case_name, COUNT(*) as measurements FROM power_measurements GROUP BY case_name;"
```

### 5.3 Create Julia Execution Script

Copy the `run_lascopf.jl` script from artifact to `scripts/run_lascopf.jl`.

### 5.4 Test Julia Solver Manually

Create a test configuration:

```bash
cat > /tmp/test_config.json << 'EOF'
{
  "topology_id": 1,
  "case_name": "case5",
  "execution_date": "2024-01-15T00:00:00",
  "optimization_horizon_hours": 24,
  "num_time_steps": 24,
  "admm_rho": 1.0,
  "app_beta": 1.0,
  "app_gamma": 1.0,
  "max_iterations": 10,
  "convergence_tolerance": 0.001
}
EOF
```

Test the solver:

```bash
# Copy config into container
docker cp /tmp/test_config.json lascopf_julia_solver:/tmp/

# Run solver
docker exec lascopf_julia_solver julia --project=/app /app/scripts/run_lascopf.jl /tmp/test_config.json
```

### 5.5 Run Complete Airflow Pipeline

1. Go to Airflow UI
2. Find `lascopf_daily_pipeline` DAG
3. Click "Trigger DAG w/ config"
4. Enter configuration:

```json
{
  "case_name": "case5"
}
```

5. Click "Trigger"
6. Monitor execution in Graph View

### 5.6 Verify Results

```bash
# Check execution results
docker exec lascopf_postgres psql -U lascopf -d lascopf_metadata -c \
  "SELECT execution_id, case_name, convergence_status, objective_value, solve_time_seconds 
   FROM v_latest_executions 
   LIMIT 5;"

# Check dispatch results
docker exec lascopf_postgres psql -U lascopf -d lascopf_metadata -c \
  "SELECT execution_id, COUNT(*) as num_results, SUM(active_power_mw) as total_generation
   FROM generator_dispatch_results 
   GROUP BY execution_id 
   ORDER BY execution_id DESC 
   LIMIT 5;"
```

---

## STEP 6: Set Up Monitoring and Visualization (30 minutes)

### 6.1 Configure Grafana Data Sources

1. Access Grafana: http://localhost:3000
2. Login (admin/admin)
3. Go to Configuration → Data Sources
4. Add PostgreSQL data source:
   - Name: `PowerLASCOPF Metadata`
   - Host: `postgres:5432`
   - Database: `lascopf_metadata`
   - User: `lascopf`
   - Password: `lascopf_pass_2024`
   - SSL Mode: `disable`

5. Add TimescaleDB data source:
   - Name: `PowerLASCOPF Timeseries`
   - Host: `timescaledb:5432`
   - Database: `lascopf_timeseries`
   - User: `lascopf`
   - Password: `lascopf_pass_2024`
   - SSL Mode: `disable`

### 6.2 Create Dashboard

Create `monitoring/grafana/dashboards/lascopf_dashboard.json`:

```json
{
  "dashboard": {
    "title": "PowerLASCOPF Monitoring",
    "panels": [
      {
        "title": "Execution Status",
        "targets": [
          {
            "rawSql": "SELECT execution_time, convergence_status, solve_time_seconds FROM lascopf_executions ORDER BY execution_time DESC LIMIT 20",
            "format": "table"
          }
        ]
      },
      {
        "title": "Convergence History",
        "targets": [
          {
            "rawSql": "SELECT iteration, primal_residual, dual_residual FROM convergence_history WHERE execution_id = (SELECT execution_id FROM lascopf_executions ORDER BY execution_time DESC LIMIT 1)",
            "format": "time_series"
          }
        ]
      }
    ]
  }
}
```

Import the dashboard in Grafana UI.

---

## Troubleshooting Guide

### Docker Issues

**Problem**: Containers not starting
```bash
# Check logs
docker-compose logs -f <service_name>

# Restart specific service
docker-compose restart <service_name>

# Full restart
docker-compose down
docker-compose up -d
```

### Database Connection Issues

**Problem**: Can't connect to database
```bash
# Check if databases are ready
docker exec lascopf_postgres pg_isready
docker exec lascopf_timescale pg_isready

# Check port conflicts
netstat -an | grep 5432
netstat -an | grep 5433
```

### Julia Package Issues

**Problem**: Package precompilation fails
```bash
# Clear Julia depot
rm -rf ~/.julia/compiled

# Reinstall packages
julia --project=. -e 'using Pkg; Pkg.resolve(); Pkg.instantiate(); Pkg.precompile()'
```

### Airflow DAG Issues

**Problem**: DAG not appearing
```bash
# Check DAG for syntax errors
python data_engineering/orchestration/airflow_dags/daily_pipeline.py

# Restart Airflow scheduler
docker-compose restart airflow-scheduler
```

---

## Next Steps

1. **Add More Test Cases**: Load RTS-GMLC and other example cases
2. **Customize Algorithms**: Integrate your actual ADMM/APP implementation
3. **Scale Up**: Configure distributed computing for larger systems
4. **Add Real-Time Pipeline**: Set up Kafka for streaming data
5. **Production Deployment**: Move to cloud infrastructure (AWS/Azure/GCP)

---

## Maintenance Commands

```bash
# View logs
docker-compose logs -f airflow-