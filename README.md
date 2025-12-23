<div align="center">
  <img src="power_systems_pipeline.png" alt="PowerLASCOPFDataEngineering Pipeline" width="1000"/>
  <h1>PowerLASCOPFDataEngineering Pipeline</h1>
</div>

# PowerLASCOPFDataEngineering
This repository does data engineering for PowerLASCOPF.jl with data ingestion, storage, manipulation, containerization, feeding into the PowerLASCOPF.jl model, and processing results

# PowerLASCOPF.jl Data Engineering Architecture

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     DATA SOURCES LAYER                          │
├─────────────────────────────────────────────────────────────────┤
│  • SCADA/EMS Systems    • Weather APIs    • Market Data         │
│  • Historical Archives  • Forecast Data   • Topology Changes    │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   INGESTION LAYER                               │
├─────────────────────────────────────────────────────────────────┤
│  • Python/Julia API Clients                                     │
│  • Kafka Consumers (Real-time)                                  │
│  • Batch Extractors (Scheduled)                                 │
│  • File Watchers (S3/Local)                                     │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                 RAW DATA STORAGE                                │
├─────────────────────────────────────────────────────────────────┤
│  • S3/MinIO (Data Lake)                                         │
│  • TimescaleDB (Time-series)                                    │
│  • PostgreSQL (Metadata)                                        │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│              TRANSFORMATION LAYER (Airflow)                     │
├─────────────────────────────────────────────────────────────────┤
│  • Data Validation (Great Expectations)                         │
│  • Cleaning & Normalization                                     │
│  • Feature Engineering                                          │
│  • Format Conversion (to PowerSystems.jl)                       │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│              PROCESSED DATA STORAGE                             │
├─────────────────────────────────────────────────────────────────┤
│  • Parquet Files (Columnar)                                     │
│  • HDF5 (Julia-optimized)                                       │
│  • PostgreSQL (Relational queries)                              │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│            POWERLASCOPF.jl EXECUTION LAYER                      │
├─────────────────────────────────────────────────────────────────┤
│  • Data Loading Module                                          │
│  • ADMM/APP Solver Engine                                       │
│  • Distributed Computing (Julia)                                │
│  • Results Aggregation                                          │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│               RESULTS & ANALYTICS LAYER                         │
├─────────────────────────────────────────────────────────────────┤
│  • Results Database (PostgreSQL/TimescaleDB)                    │
│  • Visualization Dashboard (Grafana/Plotly)                     │
│  • Report Generation (Jupyter/Pluto)                            │
│  • API Endpoints (FastAPI/Genie.jl)                             │
└─────────────────────────────────────────────────────────────────┘
```

## Detailed Component Design

### 1. Data Ingestion Module

**File Structure:**
```
PowerLASCOPF.jl/
├── data_engineering/
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── scada_client.py
│   │   ├── weather_api.py
│   │   ├── market_data.py
│   │   └── kafka_consumers.py
│   ├── validation/
│   │   ├── schemas.py
│   │   ├── expectations.py
│   │   └── quality_checks.py
│   ├── transformation/
│   │   ├── cleaners.py
│   │   ├── converters.py
│   │   └── powersystems_builder.py
│   └── orchestration/
│       └── airflow_dags/
│           ├── daily_ingest.py
│           ├── realtime_stream.py
│           └── model_execution.py
```

### 2. Data Pipeline Architecture

#### Pipeline 1: Batch Historical Data
```python
# airflow_dags/daily_ingest.py
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'lascopf',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'retries': 3,
    'retry_delay': timedelta(minutes=5)
}

dag = DAG(
    'lascopf_daily_ingest',
    default_args=default_args,
    schedule_interval='@daily',
    catchup=False
)

# Task 1: Extract from multiple sources
extract_scada = PythonOperator(
    task_id='extract_scada_data',
    python_callable=extract_scada_function,
    dag=dag
)

extract_weather = PythonOperator(
    task_id='extract_weather_data',
    python_callable=extract_weather_function,
    dag=dag
)

# Task 2: Validate data quality
validate_data = PythonOperator(
    task_id='validate_data',
    python_callable=validate_with_great_expectations,
    dag=dag
)

# Task 3: Transform to PowerSystems format
transform_data = PythonOperator(
    task_id='transform_to_powersystems',
    python_callable=convert_to_powersystems_format,
    dag=dag
)

# Task 4: Trigger Julia solver
run_lascopf = PythonOperator(
    task_id='run_lascopf_solver',
    python_callable=execute_julia_solver,
    dag=dag
)

# Task 5: Store results
store_results = PythonOperator(
    task_id='store_results',
    python_callable=store_results_to_db,
    dag=dag
)

# Define dependencies
[extract_scada, extract_weather] >> validate_data >> transform_data >> run_lascopf >> store_results
```

#### Pipeline 2: Real-time Streaming
```python
# kafka_consumers.py
from kafka import KafkaConsumer
import json
from timescaledb_client import store_timeseries

def consume_realtime_measurements():
    consumer = KafkaConsumer(
        'power_measurements',
        bootstrap_servers=['localhost:9092'],
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    
    for message in consumer:
        data = message.value
        # Validate
        if validate_measurement(data):
            # Store in TimescaleDB
            store_timeseries(data)
            # Check if re-optimization needed
            if should_reoptimize(data):
                trigger_lascopf_update()
```

### 3. Data Storage Schema

#### TimescaleDB Schema (Time-series data)
```sql
-- Create hypertable for power measurements
CREATE TABLE power_measurements (
    time TIMESTAMPTZ NOT NULL,
    generator_id TEXT NOT NULL,
    bus_id TEXT NOT NULL,
    active_power DOUBLE PRECISION,
    reactive_power DOUBLE PRECISION,
    voltage_magnitude DOUBLE PRECISION,
    voltage_angle DOUBLE PRECISION,
    measurement_quality INTEGER,
    PRIMARY KEY (time, generator_id)
);

SELECT create_hypertable('power_measurements', 'time');

-- Create index for fast queries
CREATE INDEX idx_generator ON power_measurements (generator_id, time DESC);
```

#### PostgreSQL Schema (Metadata & Results)
```sql
-- Network topology
CREATE TABLE network_topology (
    topology_id SERIAL PRIMARY KEY,
    valid_from TIMESTAMP NOT NULL,
    valid_until TIMESTAMP,
    system_data JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- LASCOPF execution results
CREATE TABLE lascopf_results (
    execution_id UUID PRIMARY KEY,
    execution_time TIMESTAMP NOT NULL,
    topology_id INTEGER REFERENCES network_topology(topology_id),
    convergence_status TEXT NOT NULL,
    objective_value DOUBLE PRECISION,
    solve_time_seconds DOUBLE PRECISION,
    iteration_count INTEGER,
    results_path TEXT,
    metadata JSONB
);

-- Generator dispatch results
CREATE TABLE generator_dispatch (
    result_id UUID DEFAULT gen_random_uuid(),
    execution_id UUID REFERENCES lascopf_results(execution_id),
    time_interval TIMESTAMP NOT NULL,
    generator_id TEXT NOT NULL,
    active_power DOUBLE PRECISION,
    reactive_power DOUBLE PRECISION,
    commitment_status BOOLEAN,
    PRIMARY KEY (result_id)
);
```

### 4. Julia Data Interface Module

```julia
# PowerLASCOPF.jl/src/data_interface/DataLoader.jl

module DataLoader

using DataFrames
using CSV
using HDF5
using LibPQ  # PostgreSQL client
using Parquet2
using Dates

export load_network_data, load_measurements, save_results

"""
Load network topology from PostgreSQL
"""
function load_network_data(topology_id::Int, conn::LibPQ.Connection)
    query = """
        SELECT system_data 
        FROM network_topology 
        WHERE topology_id = \$1
    """
    result = execute(conn, query, [topology_id])
    
    # Parse JSON to PowerSystems System object
    json_data = LibPQ.string_view(result[1, :system_data])
    return parse_powersystems_json(json_data)
end

"""
Load time-series measurements from TimescaleDB
"""
function load_measurements(
    start_time::DateTime,
    end_time::DateTime,
    conn::LibPQ.Connection
)
    query = """
        SELECT * FROM power_measurements
        WHERE time >= \$1 AND time <= \$2
        ORDER BY time
    """
    result = execute(conn, query, [start_time, end_time])
    return DataFrame(result)
end

"""
Load processed data from Parquet files
"""
function load_from_parquet(filepath::String)
    return Parquet2.Dataset(filepath) |> DataFrame
end

"""
Save LASCOPF results to database
"""
function save_results(
    execution_id::UUID,
    results::Dict,
    conn::LibPQ.Connection
)
    # Save metadata
    execute(conn, """
        INSERT INTO lascopf_results 
        (execution_id, execution_time, convergence_status, objective_value, solve_time_seconds)
        VALUES (\$1, \$2, \$3, \$4, \$5)
    """, [
        execution_id,
        now(),
        results["status"],
        results["objective"],
        results["solve_time"]
    ])
    
    # Save detailed generator dispatch
    for (gen_name, dispatch) in results["dispatch"]
        execute(conn, """
            INSERT INTO generator_dispatch
            (execution_id, generator_id, active_power, reactive_power)
            VALUES (\$1, \$2, \$3, \$4)
        """, [execution_id, gen_name, dispatch["P"], dispatch["Q"]])
    end
end

end # module
```

### 5. Data Validation with Great Expectations

```python
# validation/expectations.py
import great_expectations as gx

def create_power_system_expectations():
    """Define data quality expectations for power system data"""
    
    context = gx.get_context()
    
    # Create expectation suite
    suite = context.add_expectation_suite("power_measurements_suite")
    
    validator = context.sources.add_or_update_pandas(
        "power_measurements"
    ).read_dataframe(df)
    
    # Voltage magnitude constraints
    validator.expect_column_values_to_be_between(
        column="voltage_magnitude",
        min_value=0.95,
        max_value=1.05,
        mostly=0.98  # 98% of values should be within limits
    )
    
    # Power factor constraints
    validator.expect_column_values_to_be_between(
        column="power_factor",
        min_value=-1.0,
        max_value=1.0
    )
    
    # Frequency constraints
    validator.expect_column_values_to_be_between(
        column="frequency_hz",
        min_value=59.5,
        max_value=60.5
    )
    
    # No missing critical data
    validator.expect_column_values_to_not_be_null(
        column="active_power"
    )
    
    return suite
```

### 6. API Layer for Data Access

```julia
# PowerLASCOPF.jl/src/api/server.jl

using Genie, Genie.Router, Genie.Renderer.Json
using PowerLASCOPF

# Start API server
route("/api/v1/execute", method = POST) do
    payload = jsonpayload()
    
    # Load network data
    network = DataLoader.load_network_data(payload["topology_id"], db_conn)
    
    # Execute LASCOPF
    results = solve_lascopf(network, payload["config"])
    
    # Save results
    DataLoader.save_results(results, db_conn)
    
    json(Dict("execution_id" => results["id"], "status" => "success"))
end

route("/api/v1/results/:execution_id") do
    execution_id = payload(:execution_id)
    results = DataLoader.load_results(execution_id, db_conn)
    json(results)
end

up(8000, async = true)
```

## Docker Compose Setup

```yaml
# docker-compose.yml
version: '3.8'

services:
  timescaledb:
    image: timescale/timescaledb:latest-pg14
    environment:
      POSTGRES_DB: powerlascopf
      POSTGRES_USER: lascopf
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - timescale_data:/var/lib/postgresql/data
  
  postgres:
    image: postgres:14
    environment:
      POSTGRES_DB: lascopf_metadata
      POSTGRES_USER: lascopf
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    ports:
      - "5433:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
  
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
  
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: lascopf
      MINIO_ROOT_PASSWORD: ${MINIO_PASSWORD}
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data
  
  airflow-webserver:
    image: apache/airflow:2.7.0-python3.10
    environment:
      AIRFLOW__CORE__EXECUTOR: CeleryExecutor
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://lascopf:${DB_PASSWORD}@postgres/airflow
      AIRFLOW__CELERY__RESULT_BACKEND: db+postgresql://lascopf:${DB_PASSWORD}@postgres/airflow
      AIRFLOW__CELERY__BROKER_URL: redis://redis:6379/0
    volumes:
      - ./data_engineering/orchestration/airflow_dags:/opt/airflow/dags
      - ./data_engineering:/opt/airflow/plugins
    ports:
      - "8080:8080"
    depends_on:
      - postgres
      - redis
  
  julia-solver:
    build:
      context: .
      dockerfile: Dockerfile.julia
    volumes:
      - ./PowerLASCOPF.jl:/app
    environment:
      JULIA_NUM_THREADS: 8
    depends_on:
      - timescaledb
      - minio

volumes:
  timescale_data:
  postgres_data:
  minio_data:
```

## CI/CD Pipeline

```yaml
# .github/workflows/data_pipeline.yml
name: Data Pipeline CI/CD

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test-data-pipeline:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:14
        env:
          POSTGRES_DB: test_db
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: |
          pip install -r data_engineering/requirements.txt
          pip install pytest great-expectations
      
      - name: Run data validation tests
        run: |
          pytest data_engineering/tests/
      
      - name: Test Great Expectations
        run: |
          great_expectations checkpoint run power_measurements_checkpoint
  
  test-julia-solver:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Julia
        uses: julia-actions/setup-julia@v1
        with:
          version: '1.9'
      
      - name: Run Julia tests
        run: |
          julia --project=. -e 'using Pkg; Pkg.test()'
```

## Monitoring & Observability

```python
# monitoring/metrics.py
from prometheus_client import Counter, Histogram, Gauge
import logging

# Define metrics
data_ingestion_counter = Counter(
    'lascopf_data_ingestion_total',
    'Total data ingestion events',
    ['source', 'status']
)

solver_execution_time = Histogram(
    'lascopf_solver_execution_seconds',
    'Time spent in solver execution'
)

convergence_status = Gauge(
    'lascopf_convergence_status',
    'Current convergence status (1=converged, 0=failed)'
)

# Instrument code
def ingest_data_with_metrics(source):
    try:
        data = extract_data(source)
        data_ingestion_counter.labels(source=source, status='success').inc()
        return data
    except Exception as e:
        data_ingestion_counter.labels(source=source, status='failure').inc()
        logging.error(f"Ingestion failed: {e}")
        raise
```

## Learning Roadmap

### Phase 1: Foundations (2-3 months)
1. **SQL Mastery**: Complete PostgreSQL tutorial, practice complex queries
2. **Python Data Engineering**: Learn Pandas, SQLAlchemy
3. **Docker & Docker Compose**: Containerize applications
4. **Basic Airflow**: Build simple DAGs

### Phase 2: Intermediate (3-4 months)
1. **Apache Kafka**: Stream processing fundamentals
2. **Data Warehousing**: BigQuery or Snowflake
3. **Great Expectations**: Data validation
4. **CI/CD**: GitHub Actions for data pipelines

### Phase 3: Advanced (4-6 months)
1. **Distributed Computing**: PySpark, Dask
2. **Kubernetes**: Container orchestration
3. **Infrastructure as Code**: Terraform
4. **Advanced Julia**: Distributed.jl for parallel computing

### Recommended Resources
- **Books**: 
  - "Designing Data-Intensive Applications" by Martin Kleppmann
  - "Data Engineering with Python" by Paul Crickard
- **Courses**:
  - DataTalks.Club Data Engineering Zoomcamp (free)
  - Coursera: Data Engineering on Google Cloud
- **Practice**: 
  - Build end-to-end project with your PowerLASCOPF.jl
  - Contribute to open-source data projects

