# PowerLASCOPF Data Loading Guide

## Quick Start (5 Minutes)

```bash
# 1. Ensure Docker containers are running
cd docker
docker-compose up -d
docker-compose ps  # Verify all services are running

# 2. Load all data
cd ..
python scripts/load_all_power_system_data.py

# 3. Validate loaded data
python scripts/validate_all_data.py

# 4. Test with Airflow
# Open http://localhost:8080
# Trigger DAG: lascopf_daily_pipeline with config {"case_name": "case14"}
```

---

## Table of Contents

1. [Data Sources](#data-sources)
2. [File Structure](#file-structure)
3. [Loading IEEE Test Cases](#loading-ieee-test-cases)
4. [Loading RTS-GMLC](#loading-rts-gmlc)
5. [Data Validation](#data-validation)
6. [Troubleshooting](#troubleshooting)

---

## Data Sources

### Included in Repository

**Location**: `example_cases/`

- IEEE 5-bus system (tutorial case)
- IEEE 14-bus system (standard benchmark)
- IEEE 30-bus system
- IEEE 57-bus system
- IEEE 118-bus system (large benchmark)

### External Data (Auto-downloaded)

**RTS-GMLC** (Reliability Test System)
- Repository: https://github.com/GridMod/RTS-GMLC
- Size: 73 buses, 156 generators
- Includes: Full year of hourly data for loads, wind, solar
- Auto-cloned by loading script if not present

### Data You Can Add

**MATPOWER Cases**
- Download from: https://github.com/MATPOWER/matpower/tree/master/data
- Place in: `example_cases/caseXX/caseXX.m`
- Supported formats: .m (MATPOWER format)

**Custom Cases**
- Via PowerGenome export (your branch: `export_powerlascopf_formats`)
- Via PowerSystems.jl serialization

---

## File Structure

```
PowerLASCOPF.jl/
├── example_cases/              # Test cases (included in repo)
│   ├── case5/
│   │   └── case5.m
│   ├── case14/
│   │   └── case14.m
│   └── case118/
│       └── case118.m
│
├── data_engineering/           # Data engineering code
│   ├── ingestion/
│   │   ├── load_examples.py
│   │   └── rts_gmlc_loader.py
│   ├── transformation/
│   │   └── matpower_parser.py
│   └── validation/
│       └── expectations.py
│
├── scripts/                    # Data loading scripts
│   ├── load_all_power_system_data.py  # Main loading script
│   └── validate_all_data.py           # Validation script
│
└── ../RTS-GMLC/               # External data (auto-cloned)
    └── SourceData/
        ├── bus.csv
        ├── gen.csv
        ├── branch.csv
        └── timeseries_data_files/
```

---

## Loading IEEE Test Cases

### Automatic Loading (Recommended)

```bash
# Load all IEEE cases in example_cases/
python scripts/load_all_power_system_data.py

# This will:
# 1. Check database connections
# 2. Parse all .m files in example_cases/
# 3. Generate synthetic time-series (7 days)
# 4. Create N-1 contingencies
# 5. Verify loaded data
```

### Manual Loading (Single Case)

```python
from data_engineering.transformation.matpower_parser import MATPOWERParser
import psycopg2
import json

# Parse MATPOWER file
parser = MATPOWERParser("example_cases/case14/case14.m")
system_json = parser.to_powerlascopf_json()

# Connect to database
conn = psycopg2.connect(
    host="localhost",
    port=5433,
    database="lascopf_metadata",
    user="lascopf",
    password="lascopf_pass_2024"
)

cursor = conn.cursor()

# Insert topology
cursor.execute("""
    INSERT INTO network_topology (
        case_name, num_buses, num_generators, num_branches, num_loads,
        base_mva, system_data, description, source
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING topology_id
""", (
    "case14",
    14,  # num_buses
    5,   # num_generators
    20,  # num_branches
    11,  # num_loads
    100.0,  # base_mva
    json.dumps(system_json),
    "IEEE 14-bus test case",
    "MATPOWER"
))

topology_id = cursor.fetchone()[0]
conn.commit()
print(f"Loaded case14 with topology_id={topology_id}")

cursor.close()
conn.close()
```

### Adding New MATPOWER Cases

1. **Download case file**:
   ```bash
   # Example: IEEE 300-bus
   wget https://raw.githubusercontent.com/MATPOWER/matpower/master/data/case300.m
   ```

2. **Create directory**:
   ```bash
   mkdir -p example_cases/case300
   mv case300.m example_cases/case300/
   ```

3. **Load it**:
   ```bash
   python scripts/load_all_power_system_data.py
   # Or use Python API shown above
   ```

---

## Loading RTS-GMLC

### Automatic (Recommended)

```bash
# Run main loading script and answer 'y' when prompted
python scripts/load_all_power_system_data.py

# Prompts:
# > Load RTS-GMLC data? (y/n) [y]: y
```

### Manual

```python
from data_engineering.ingestion.rts_gmlc_loader import RTSGMLCLoader

# Configure database
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

# Load RTS-GMLC
loader = RTSGMLCLoader("../RTS-GMLC", db_config)
topology_id = loader.load_into_database(case_name="RTS_GMLC")

print(f"Loaded RTS-GMLC with topology_id={topology_id}")
```

### What Gets Loaded

**From RTS-GMLC**:
- Network topology (73 buses, 156 generators, 121 branches)
- Generator data with costs and operating parameters
- 8760 hours (1 year) of:
  - Regional load profiles (3 areas)
  - Wind generation profiles (by plant)
  - Solar PV profiles (by plant)
  - Hydro availability
- N-1 contingencies (branches + large generators)

**Time to load**: ~5-10 minutes (includes full year of data)

---

## Data Validation

### Run Validation

```bash
# Validate all loaded cases
python scripts/validate_all_data.py

# Output:
# - Console summary
# - validation_report.txt (detailed)
```

### What Gets Validated

**Network Topology**:
- ✓ Component counts match (buses, generators, branches)
- ✓ Required fields present
- ✓ Contingencies defined

**Power Measurements**:
- ✓ Voltage magnitude: 0.85-1.15 p.u. (98% of values)
- ✓ Voltage angle: -π to π radians
- ✓ Frequency: 59.5-60.5 Hz (99.9% of values)
- ✓ No null values in critical columns

**Generator Measurements**:
- ✓ Active power: 0-10000 MW (98% of values)
- ✓ Generator type: Valid enum values
- ✓ Marginal cost: 0-1000 $/MWh (95% of values)

**Data Coverage**:
- ✓ At least 24 hours of data
- ✓ No large time gaps
- ✓ Sufficient measurements per bus/generator

### Validation Output

**Success**:
```
Validating: case14
------------------------------------------------------------
  Checking power measurements...
    ✓ Power measurements: PASSED
  Checking generator measurements...
    ✓ Generator measurements: PASSED
  Checking data coverage...
    Earliest: 2024-01-15 00:00:00
    Latest: 2024-01-22 00:00:00
    Days covered: 7
    Total measurements: 2352
  Checking network topology...
    ✓ Topology counts match
    ✓ All components have required fields
    ✓ Contingencies defined: 25

✓ All validations passed!
```

**Failure**:
```
Validating: case14
------------------------------------------------------------
  Checking power measurements...
    ✗ Power measurements: FAILED
      - expect_column_values_to_be_between: 
        observed_value: {'min': 0.82, 'max': 1.18}
        (2% of values outside range)

✗ Some validations failed. Check validation_report.txt
```

---

## Verify Loaded Data

### SQL Queries

```sql
-- Check loaded topologies
SELECT case_name, num_buses, num_generators, source 
FROM network_topology 
ORDER BY case_name;

-- Check time-series coverage
SELECT 
    case_name,
    MIN(time) as earliest,
    MAX(time) as latest,
    COUNT(*) as measurements
FROM power_measurements
GROUP BY case_name;

-- Check contingencies
SELECT 
    t.case_name,
    c.contingency_type,
    COUNT(*) as count
FROM contingencies c
JOIN network_topology t ON c.topology_id = t.topology_id
GROUP BY t.case_name, c.contingency_type;
```

### Using Docker

```bash
# Connect to PostgreSQL
docker exec -it lascopf_postgres psql -U lascopf -d lascopf_metadata

# Run queries
lascopf_metadata=# SELECT * FROM network_topology;
lascopf_metadata=# \q

# Connect to TimescaleDB
docker exec -it lascopf_timescale psql -U lascopf -d lascopf_timeseries

# Check measurements
lascopf_timeseries=# SELECT COUNT(*) FROM power_measurements;
lascopf_timeseries=# \q
```

---

## Testing with Loaded Data

### Trigger Airflow Pipeline

**Via Web UI**:
1. Open http://localhost:8080
2. Find DAG: `lascopf_daily_pipeline`
3. Click "Trigger DAG w/ config"
4. Enter JSON:
   ```json
   {
     "case_name": "case14"
   }
   ```
5. Click "Trigger"
6. Monitor execution in Graph View

**Via CLI**:
```bash
# Trigger with specific case
airflow dags trigger lascopf_daily_pipeline \
  --conf '{"case_name": "case14"}'

# View logs
airflow dags list-runs -d lascopf_daily_pipeline

# Check task logs
airflow tasks logs lascopf_daily_pipeline execute_julia_solver <execution_date>
```

### Manual Julia Test

```bash
# Create test config
cat > /tmp/test_config.json << EOF
{
  "topology_id": 1,
  "case_name": "case14",
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

# Run Julia solver
docker exec lascopf_julia_solver julia --project=/app \
  /app/scripts/run_lascopf.jl /tmp/test_config.json
```

---

## Troubleshooting

### Database Connection Errors

**Problem**: `psycopg2.OperationalError: could not connect to server`

**Solutions**:
```bash
# 1. Check if containers are running
docker-compose ps

# 2. Check if databases are ready
docker exec lascopf_postgres pg_isready -U lascopf
docker exec lascopf_timescale pg_isready -U lascopf

# 3. Check logs
docker-compose logs postgres
docker-compose logs timescaledb

# 4. Restart services
docker-compose restart postgres timescaledb

# 5. Full restart (WARNING: deletes data)
docker-compose down -v
docker-compose up -d
# Wait 30 seconds for initialization
python scripts/load_all_power_system_data.py
```

### MATPOWER Parsing Errors

**Problem**: `ValueError: could not convert string to float`

**Cause**: Malformed .m file or unsupported format

**Solutions**:
```bash
# 1. Verify file format
head -20 example_cases/case14/case14.m
# Should see: function mpc = case14
#             mpc.version = '2';
#             mpc.baseMVA = 100;

# 2. Download fresh copy
wget https://raw.githubusercontent.com/MATPOWER/matpower/master/data/case14.m \
  -O example_cases/case14/case14.m

# 3. Check parser with verbose output
python -c "
from data_engineering.transformation.matpower_parser import MATPOWERParser
parser = MATPOWERParser('example_cases/case14/case14.m')
print(parser.get_statistics())
"
```

### RTS-GMLC Clone Failures

**Problem**: `git clone` fails or RTS-GMLC not found

**Solutions**:
```bash
# 1. Manual clone
cd ..
git clone https://github.com/GridMod/RTS-GMLC.git

# 2. Verify structure
ls RTS-GMLC/SourceData/
# Should see: bus.csv, gen.csv, branch.csv, etc.

# 3. Check internet connection
ping github.com

# 4. Use alternate location
# Edit scripts/load_all_power_system_data.py
# Change: self.rts_gmlc_dir = Path("/path/to/your/RTS-GMLC")
```

### Validation Failures

**Problem**: Data validation fails after loading

**Common Issues**:

1. **Voltage violations**:
   ```
   expect_column_values_to_be_between: voltage_magnitude
   observed_value: {'min': 0.82, 'max': 1.18}
   ```
   
   **Solution**: Synthetic data generation might need tuning
   ```python
   # In generate_synthetic_measurements(), adjust noise:
   voltage = bus.get('voltage_magnitude', 1.0) + np.random.normal(0, 0.005)  # Reduced from 0.01
   ```

2. **Missing time-series data**:
   ```
   ⚠ No power measurements found
   ```
   
   **Solution**: Re-run synthetic data generation
   ```bash
   python -c "
   from scripts.load_all_power_system_data import PowerSystemDataManager
   mgr = PowerSystemDataManager()
   mgr.generate_synthetic_measurements(1, 'case14', num_days=7)
   "
   ```

3. **Contingency errors**:
   ```
   ⚠ No contingencies defined
   ```
   
   **Solution**: Re-generate contingencies
   ```sql
   -- Connect to database
   docker exec -it lascopf_postgres psql -U lascopf -d lascopf_metadata
   
   -- Check contingencies
   SELECT topology_id, COUNT(*) FROM contingencies GROUP BY topology_id;
   
   -- If missing, re-run load script
   ```

### Performance Issues

**Problem**: Loading RTS-GMLC takes too long (>15 minutes)

**Solutions**:
```python
# 1. Use batch commits in rts_gmlc_loader.py
# Already implemented: commits every 100 rows

# 2. Disable fsync temporarily (ONLY for initial load)
# In docker-compose.yml, add to postgres:
environment:
  POSTGRES_FSYNC: 'off'

# 3. Load in parallel (for multiple cases)
# Use multiprocessing in load_all_power_system_data.py
```

---

## Advanced Usage

### Custom Time-Series Data

```python
# Load your own time-series CSV
import pandas as pd
import psycopg2
from datetime import datetime, timedelta

# Read your data
df = pd.read_csv("my_load_data.csv")
# Expected columns: timestamp, bus_id, active_power_mw, reactive_power_mvar

conn = psycopg2.connect(**db_config['timeseries'])
cursor = conn.cursor()

for _, row in df.iterrows():
    cursor.execute("""
        INSERT INTO load_measurements (
            time, load_id, load_name, bus_id,
            active_power_mw, reactive_power_mvar,
            source, case_name
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        row['timestamp'],
        f"Load_{row['bus_id']}",
        f"Load_{row['bus_id']}",
        row['bus_id'],
        row['active_power_mw'],
        row['reactive_power_mvar'],
        "CUSTOM",
        "my_case"
    ))

conn.commit()
```

### Export to Other Formats

```python
# Export loaded case to MATPOWER format
from data_engineering.transformation.matpower_parser import MATPOWERParser
import psycopg2
import json

conn = psycopg2.connect(**db_config['metadata'])
cursor = conn.cursor()

cursor.execute("""
    SELECT system_data FROM network_topology WHERE case_name = 'case14'
""")

system_data = cursor.fetchone()[0]

# Convert back to MATPOWER format (implement reverse parser)
# ... custom code ...

cursor.close()
conn.close()
```

---

## Next Steps

After successfully loading data:

1. **Validate data quality**: `python scripts/validate_all_data.py`
2. **Run test optimization**: Trigger Airflow DAG
3. **Check results in Grafana**: http://localhost:3000
4. **Load more cases**: Add your own MATPOWER files
5. **Integrate PowerGenome**: Export from your custom branch

---

## Data Sources Reference

| Source | URL | Data Type | Size |
|--------|-----|-----------|------|
| IEEE Test Cases | https://labs.ece.uw.edu/pstca/ | Static topology | Small-Large |
| RTS-GMLC | https://github.com/GridMod/RTS-GMLC | Full system + time-series | 73 bus |
| MATPOWER Cases | https://github.com/MATPOWER/matpower/tree/master/data | Static topology | Various |
| Open Power System Data | https://open-power-system-data.org/ | European grid data | Country-scale |
| PowerGenome | https://github.com/sambuddhac/PowerGenome | Synthetic scenarios | Custom |

---

## Support

If you encounter issues not covered here:

1. Check logs: `docker-compose logs -f <service>`
2. Verify database state: `docker exec -it lascopf_postgres psql -U lascopf -d lascopf_metadata`
3. Review validation report: `cat validation_report.txt`
4. Check Airflow logs: http://localhost:8080 → DAG → Logs

For additional help, see the main PowerLASCOPF.jl documentation.