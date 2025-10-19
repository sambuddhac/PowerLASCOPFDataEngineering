# PowerLASCOPF Data Sources & Integration Guide

## Overview

This guide provides comprehensive information about publicly available power system data sources that can be used to populate your PowerLASCOPF databases.

---

## 1. IEEE Test Cases (Free & Publicly Available)

### RTS-GMLC (Reliability Test System - Grid Modernization Lab Consortium)

**Source**: https://github.com/GridMod/RTS-GMLC

**What it includes**:
- 73 buses
- 156 generators (nuclear, coal, gas, wind, solar PV, hydro, storage)
- 121 branches (105 AC lines, 15 transformers, 1 DC line)
- Hourly load profiles for full year
- Wind and solar generation profiles
- Generator cost data and operating parameters
- Geographic and temporal variability

**Why it's perfect for PowerLASCOPF**:
- Modern generation mix (renewables + storage)
- Comprehensive time-series data
- Well-documented and maintained
- Used by NREL and DOE researchers

**Data formats available**:
- CSV (SourceData folder)
- MATPOWER format
- PLEXOS format
- PowerWorld format
- PRESCIENT format
- SIENNA (PowerSystems.jl) format ← **PERFECT FOR YOUR PROJECT!**

**How to use**:
```bash
# Clone the repository
git clone https://github.com/GridMod/RTS-GMLC.git

# Data is in:
# SourceData/ - CSV files for all components
# FormattedData/SIENNA/ - PowerSystems.jl format
```

---

### IEEE 14-Bus System

**Source**: https://github.com/MATPOWER/matpower/blob/master/data/case14.m

**What it includes**:
- 14 buses
- 5 generators
- 20 branches
- 11 loads
- Portion of American Electric Power System (1962)

**Download**: https://labs.ece.uw.edu/pstca/pf14/ieee14cdf.txt

---

### IEEE 118-Bus System

**Source**: https://github.com/MATPOWER/matpower/blob/master/data/case118.m

**What it includes**:
- 118 buses
- 54 generators (19 generators + 35 synchronous condensers)
- 186 branches
- 91 loads
- Portion of American Electric Power System (Midwestern US, 1962)

**Download**: https://labs.ece.uw.edu/pstca/pf118/ieee118cdf.txt

---

### Other IEEE Test Cases

**Source**: https://labs.ece.uw.edu/pstca/

Available cases:
- IEEE 9-bus
- IEEE 24-bus (RTS-79, RTS-96)
- IEEE 30-bus
- IEEE 57-bus
- IEEE 300-bus
- Polish system (2383-bus, 2746-bus, 3120-bus)

---

## 2. Real-World Grid Data

### Open Power System Data (Europe)

**Source**: https://open-power-system-data.org/

**What it includes**:
- Installed generation capacity by country/technology
- Individual power plant data (conventional and renewable)
- Hourly electricity consumption data
- Spot prices
- Wind and solar generation (measured and forecasted)
- Cross-border flows

**Countries covered**: EU27 + UK, Norway, Switzerland

**Time range**: 2015-present (updated regularly)

**Data formats**: CSV, SQLite

**How to use**:
```python
import pandas as pd

# Load time series data
url = 'https://data.open-power-system-data.org/time_series/latest/time_series_60min_singleindex.csv'
df = pd.read_csv(url)

# Filter for specific country
germany_data = df[df['cet_cest_timestamp'].str.contains('DE')]
```

---

### Ausgrid (Australia)

**Source**: https://www.ausgrid.com.au/Industry/Our-Research/Data-to-share

**What it includes**:
- Solar home electricity data (4064 non-solar + solar homes)
- Zone substation load profiles (180+ substations)
- 15-minute interval data
- Power outage records
- 2010-2014 historical data

**Use case**: Load forecasting, demand response, renewable integration

---

### IEEE Data Port

**Source**: https://ieee-dataport.org/keywords/scada

**What it includes**:
- SCADA measurements from industrial control systems
- Wind turbine performance data
- Cybersecurity datasets for power systems
- Various operational scenarios

**Note**: Requires IEEE account (free for members)

---

## 3. Synthetic Data Generation Tools

### NREL System Advisor Model (SAM)

**Source**: https://sam.nrel.gov/

**Use**: Generate solar and wind profiles for any location

---

### PowerGenome (Your Project!)

**Source**: https://github.com/sambuddhac/PowerGenome/tree/export_powerlascopf_formats

**What it does**:
- Aggregates data from multiple sources (EIA, ABB, EPA)
- Builds future scenarios
- Generates time-series profiles
- **YOUR BRANCH**: Exports to PowerLASCOPF format!

---

## 4. Example Cases from PowerLASCOPF.jl Repository

Based on typical Sienna/PowerSystems.jl examples, your `example_cases/` folder likely contains:

### Expected Structure:
```
example_cases/
├── RTS_GMLC/
│   ├── user_descriptors.yaml
│   ├── System.json  # PowerSystems.jl serialized
│   └── time_series_storage/
├── case5/
│   └── case5.m  # MATPOWER format
├── case14/
│   └── case14.m
├── case118/
│   └── case118.m
└── README.md
```

### These cases should be loaded into your database!

---

## 5. Data Integration Strategy

### Step 1: Load IEEE Test Cases

```python
# File: scripts/load_ieee_cases.py

import psycopg2
import json
from pathlib import Path

db_config = {
    "host": "localhost",
    "port": 5433,
    "database": "lascopf_metadata",
    "user": "lascopf",
    "password": "lascopf_pass_2024"
}

def load_mat power_case(case_file, case_name):
    """Load MATPOWER case into database"""
    
    # Parse MATPOWER file (use scipy.io.loadmat or custom parser)
    case_data = parse_matpower(case_file)
    
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()
    
    # Convert to JSON format
    system_json = {
        "base_mva": float(case_data['baseMVA']),
        "buses": convert_buses(case_data['bus']),
        "generators": convert_generators(case_data['gen'], case_data['gencost']),
        "branches": convert_branches(case_data['branch']),
        "loads": extract_loads(case_data['bus'])
    }
    
    # Insert into database
    cursor.execute("""
        INSERT INTO network_topology (
            case_name, num_buses, num_generators, num_branches, num_loads,
            base_mva, system_data, description, source
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING topology_id
    """, (
        case_name,
        len(system_json['buses']),
        len(system_json['generators']),
        len(system_json['branches']),
        len(system_json['loads']),
        system_json['base_mva'],
        json.dumps(system_json),
        f"IEEE {case_name} test case",
        "MATPOWER"
    ))
    
    topology_id = cursor.fetchone()[0]
    conn.commit()
    
    return topology_id

# Load all cases
cases = [
    ("example_cases/case5/case5.m", "case5"),
    ("example_cases/case14/case14.m", "case14"),
    ("example_cases/case118/case118.m", "case118")
]

for case_file, case_name in cases:
    if Path(case_file).exists():
        topology_id = load_matpower_case(case_file, case_name)
        print(f"✓ Loaded {case_name} with topology_id={topology_id}")
```

---

### Step 2: Load RTS-GMLC Data

```python
# File: scripts/load_rts_gmlc.py

import pandas as pd
from pathlib import Path

# Path to RTS-GMLC repository
rts_path = Path("../RTS-GMLC")

# Load generator data
gen_df = pd.read_csv(rts_path / "SourceData" / "gen.csv")
bus_df = pd.read_csv(rts_path / "SourceData" / "bus.csv")
branch_df = pd.read_csv(rts_path / "SourceData" / "branch.csv")

# Load time series
load_ts = pd.read_csv(rts_path / "SourceData" / "timeseries_data_files" / "Load" / "regional_Load.csv")
wind_ts = pd.read_csv(rts_path / "SourceData" / "timeseries_data_files" / "WIND" / "wind_total_2007.csv")
solar_ts = pd.read_csv(rts_path / "SourceData" / "timeseries_data_files" / "PV" / "pv_2007.csv")

# Insert into database
def load_rts_gmlc(db_config):
    conn = psycopg2.connect(**db_config)
    
    # Insert topology
    topology_id = insert_rts_topology(conn, bus_df, gen_df, branch_df)
    
    # Insert time series
    insert_load_timeseries(conn, topology_id, load_ts)
    insert_wind_timeseries(conn, topology_id, wind_ts)
    insert_solar_timeseries(conn, topology_id, solar_ts)
    
    # Generate contingencies
    generate_n1_contingencies(conn, topology_id, branch_df, gen_df)
    
    conn.close()
    
    return topology_id
```

---

### Step 3: Generate Synthetic Measurements

```python
# File: scripts/generate_synthetic_data.py

import numpy as np
from datetime import datetime, timedelta

def generate_realistic_measurements(topology_id, case_name, num_days=7):
    """Generate synthetic SCADA-like measurements"""
    
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()
    
    # Get network components
    cursor.execute("""
        SELECT system_data FROM network_topology WHERE topology_id = %s
    """, (topology_id,))
    
    system_data = json.loads(cursor.fetchone()[0])
    
    start_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Generate hourly data
    for hour in range(num_days * 24):
        timestamp = start_time + timedelta(hours=hour)
        hour_of_day = timestamp.hour
        
        # Daily load curve (sinusoidal)
        load_factor = 0.6 + 0.3 * np.sin((hour_of_day - 6) * np.pi / 12)
        
        # Bus measurements
        for bus in system_data['buses']:
            voltage = bus.get('voltage_magnitude', 1.0) + np.random.normal(0, 0.01)
            angle = bus.get('angle', 0.0) + np.random.normal(0, 0.05)
            
            cursor.execute("""
                INSERT INTO power_measurements (
                    time, bus_id, bus_name, voltage_magnitude, voltage_angle_rad,
                    frequency_hz, measurement_quality, source, case_name
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                timestamp,
                str(bus['number']),
                bus['name'],
                voltage,
                angle,
                60.0 + np.random.normal(0, 0.02),
                np.random.randint(95, 101),
                "SYNTHETIC",
                case_name
            ))
        
        # Generator measurements
        for gen in system_data['generators']:
            power = gen['pmin'] + load_factor * (gen['pmax'] - gen['pmin'])
            power += np.random.normal(0, gen['pmax'] * 0.02)  # 2% noise
            
            cursor.execute("""
                INSERT INTO generator_measurements (
                    time, generator_id, generator_name, bus_id,
                    active_power_mw, reactive_power_mvar,
                    commitment_status, marginal_cost,
                    generator_type, source, case_name
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                timestamp,
                gen['name'],
                gen['name'],
                str(gen['bus_number']),
                power,
                power * 0.3,  # Assume power factor
                True,
                gen.get('cost_linear', 30.0),
                gen['type'],
                "SYNTHETIC",
                case_name
            ))
    
    conn.commit()
    conn.close()
```

---

## 6. Complete Data Loading Workflow

```bash
#!/bin/bash
# File: scripts/load_all_data.sh

echo "Loading Power System Data into PowerLASCOPF Database"
echo "===================================================="

# Step 1: Ensure databases are running
echo "Step 1: Checking database connections..."
docker exec lascopf_postgres pg_isready -U lascopf
docker exec lascopf_timescale pg_isready -U lascopf

# Step 2: Load IEEE test cases
echo "Step 2: Loading IEEE test cases..."
python scripts/load_ieee_cases.py

# Step 3: Load RTS-GMLC
echo "Step 3: Loading RTS-GMLC data..."
if [ -d "../RTS-GMLC" ]; then
    python scripts/load_rts_gmlc.py
else
    echo "   Cloning RTS-GMLC repository..."
    git clone https://github.com/GridMod/RTS-GMLC.git ../RTS-GMLC
    python scripts/load_rts_gmlc.py
fi

# Step 4: Generate synthetic measurements
echo "Step 4: Generating synthetic time-series data..."
python scripts/generate_synthetic_data.py

# Step 5: Verify data
echo "Step 5: Verifying loaded data..."
docker exec lascopf_postgres psql -U lascopf -d lascopf_metadata -c \
  "SELECT case_name, num_buses, num_generators, source FROM network_topology;"

docker exec lascopf_timescale psql -U lascopf -d lascopf_timeseries -c \
  "SELECT case_name, COUNT(*) as measurements FROM power_measurements GROUP BY case_name;"

echo "===================================================="
echo "✓ Data loading complete!"
```

---

## 7. Data Quality Checklist

### For each case, verify:

- [ ] **Topology loaded**: Check `network_topology` table
- [ ] **Time-series data**: At least 24 hours of measurements
- [ ] **Generators**: Cost data and operating limits
- [ ] **Loads**: Realistic daily profiles
- [ ] **Contingencies**: N-1 scenarios defined
- [ ] **Data validation**: Great Expectations tests pass

### Validation queries:

```sql
-- Check topology
SELECT case_name, num_buses, num_generators, num_branches, num_loads
FROM network_topology
ORDER BY case_name;

-- Check time-series coverage
SELECT 
    case_name,
    MIN(time) as earliest,
    MAX(time) as latest,
    COUNT(*) as total_measurements
FROM power_measurements
GROUP BY case_name;

-- Check generators
SELECT case_name, COUNT(*) as num_measurements, AVG(active_power_mw) as avg_power
FROM generator_measurements
WHERE time >= NOW() - INTERVAL '24 hours'
GROUP BY case_name;

-- Check contingencies
SELECT topology_id, contingency_type, COUNT(*) as num_contingencies
FROM contingencies
GROUP BY topology_id, contingency_type;
```

---

## 8. Recommended Data for Your Project

### Priority 1: Start Here
1. **IEEE 14-bus**: Simple, well-understood, fast to solve
2. **IEEE 118-bus**: Medium complexity, standard benchmark
3. **Synthetic measurements**: Generate 1 week of data for both

### Priority 2: After Initial Testing
1. **RTS-GMLC**: Modern system with renewables
2. **Real load profiles**: From Open Power System Data

### Priority 3: Advanced
1. **Your own system**: Via PowerGenome export
2. **Custom scenarios**: Climate scenarios, policy changes

---

## 9. Data Sources Summary Table

| Source | Size | Generators | Time Series | Renewables | Difficulty |
|--------|------|------------|-------------|------------|------------|
| IEEE 14-bus | 14 buses | 5 | ❌ (generate) | ❌ | Easy |
| IEEE 118-bus | 118 buses | 54 | ❌ (generate) | ❌ | Easy |
| RTS-GMLC | 73 buses | 156 | ✅ (8760 hrs) | ✅ | Medium |
| Open Power System Data | Country-scale | 1000s | ✅ (years) | ✅ | Hard |
| PowerGenome | Custom | Custom | ✅ | ✅ | Medium |

---

## 10. Next Steps

1. **Clone RTS-GMLC**: `git clone https://github.com/GridMod/RTS-GMLC.git`
2. **Run load scripts**: Create the Python scripts above
3. **Verify in database**: Use validation queries
4. **Test pipeline**: Trigger Airflow DAG with loaded data
5. **Iterate**: Add more cases as needed

