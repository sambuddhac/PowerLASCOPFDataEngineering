# PowerLASCOPF.jl Quick Reference Guide

## 🚀 Quick Start (30 Minutes)

### 1. Start Infrastructure
```bash
cd docker
docker-compose up -d
docker-compose ps  # Verify all services running
```

### 2. Load Example Data
```bash
python scripts/load_example_cases.py
```

### 3. Trigger Pipeline
```bash
# Via Airflow UI: http://localhost:8080
# Or via CLI:
docker exec lascopf_airflow_webserver airflow dags trigger lascopf_daily_pipeline
```

### 4. Check Results
```bash
docker exec lascopf_postgres psql -U lascopf -d lascopf_metadata -c \
  "SELECT * FROM v_latest_executions LIMIT 5;"
```

---

## 📊 Architecture Overview

```
Data Sources → Ingestion → Validation → TimescaleDB/PostgreSQL
                                              ↓
                                         Julia Solver
                                              ↓
                                      Results Storage
                                              ↓
                                    Grafana Dashboards
```

**Key Components:**
- **TimescaleDB**: Time-series measurements
- **PostgreSQL**: Metadata and results
- **Airflow**: Pipeline orchestration
- **Julia**: LASCOPF solver engine
- **Grafana**: Monitoring and visualization

---

## 🔧 Essential Commands

### Docker Management
```bash
# Start/Stop
docker-compose up -d
docker-compose down

# View logs
docker-compose logs -f <service>

# Restart service
docker-compose restart <service>

# Clean restart
docker-compose down -v && docker-compose up -d
```

### Database Access
```bash
# PostgreSQL
docker exec -it lascopf_postgres psql -U lascopf -d lascopf_metadata

# TimescaleDB
docker exec -it lascopf_timescale psql -U lascopf -d lascopf_timeseries

# Common queries
\dt              # List tables
\d table_name    # Describe table
SELECT COUNT(*) FROM power_measurements;
```

### Julia Development
```bash
# Enter Julia container
docker exec -it lascopf_julia_solver julia --project=/app

# Run tests
julia --project=. -e 'using Pkg; Pkg.test()'

# Update packages
julia --project=. -e 'using Pkg; Pkg.update()'
```

### Airflow Management
```bash
# List DAGs
docker exec lascopf_airflow_webserver airflow dags list

# Trigger DAG
docker exec lascopf_airflow_webserver airflow dags trigger lascopf_daily_pipeline

# View task logs
docker exec lascopf_airflow_webserver airflow tasks logs lascopf_daily_pipeline <task_id> <date>
```

---

## 📁 Key File Locations

### Configuration
- Docker: `docker/docker-compose.yml`
- Database schemas: `database/init_*.sql`
- Airflow DAGs: `data_engineering/orchestration/airflow_dags/`
- Julia config: `Project.toml`, `Manifest.toml`

### Code
- Julia solver: `src/PowerLASCOPF.jl`
- Data interface: `src/data_interface/`
- Python pipelines: `data_engineering/`
- Execution scripts: `scripts/`

### Data
- Example cases: `example_cases/`
- Logs: `/var/log/airflow/` (in container)
- Results: Database tables

---

## 🗄️ Database Schema Reference

### TimescaleDB Tables
| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `power_measurements` | Bus measurements | time, bus_id, voltage_magnitude |
| `generator_measurements` | Generator data | time, generator_id, active_power_mw |
| `branch_measurements` | Line flows | time, branch_id, loading_percentage |
| `load_measurements` | Load data | time, load_id, active_power_mw |

### PostgreSQL Tables
| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `network_topology` | System topology | topology_id, case_name, system_data |
| `contingencies` | Contingency definitions | contingency_id, affected_branches |
| `lascopf_executions` | Solver runs | execution_id, convergence_status |
| `generator_dispatch_results` | Dispatch solutions | execution_id, generator_id, active_power_mw |
| `bus_results` | Voltage solutions | execution_id, bus_id, lmp_total |

---

## 🔍 Monitoring & Debugging

### Check System Health
```bash
# Database connections
docker exec lascopf_timescale pg_isready
docker exec lascopf_postgres pg_isready

# Service status
docker-compose ps

# Resource usage
docker stats
```

### View Logs
```bash
# Airflow scheduler
docker-compose logs -f airflow-scheduler

# Julia solver output
docker-compose logs -f julia-solver

# Database logs
docker-compose logs -f timescaledb
docker-compose logs -f postgres
```

### Grafana Dashboards
Access: http://localhost:3000

**Key Metrics to Monitor:**
- Solver convergence rate
- Execution time trends
- Data quality metrics
- System LMP trends
- Generator dispatch patterns

---

## 🧪 Testing

### Unit Tests
```bash
# Julia tests
julia --project=. test/runtests.jl

# Python tests
pytest test/ -v
```

### Integration Test
```bash
# End-to-end pipeline
python scripts/integration_test.py

# Manual solver test
julia --project=. scripts/run_lascopf.jl /tmp/test_config.json
```

### Data Validation
```bash
# Run Great Expectations
great_expectations checkpoint run power_measurements_checkpoint

# Manual validation
python scripts/test_validation.py
```

---

## ⚙️ Configuration Parameters

### ADMM/APP Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `admm_rho` | 1.0 | ADMM penalty parameter |
| `app_beta` | 1.0 | APP regularization (interval) |
| `app_gamma` | 1.0 | APP regularization (coupling) |
| `max_iterations` | 100 | Maximum solver iterations |
| `convergence_tolerance` | 1e-4 | Convergence threshold |

### System Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `num_time_steps` | 24 | Optimization horizon |
| `base_mva` | 100.0 | Base power (MVA) |
| `optimization_horizon_hours` | 24 | Look-ahead period |

---

## 🚨 Common Issues

### Issue: DAG Not Running
**Check:**
1. Airflow connections configured?
2. DAG toggle enabled in UI?
3. Check scheduler logs

**Fix:**
```bash
docker-compose restart airflow-scheduler
docker exec lascopf_airflow_webserver airflow dags list-runs -d lascopf_daily_pipeline
```

### Issue: Julia Package Errors
**Check:**
1. Project.toml correct?
2. Packages installed?

**Fix:**
```bash
docker exec lascopf_julia_solver julia --project=/app -e 'using Pkg; Pkg.resolve(); Pkg.instantiate()'
```

### Issue: Database Connection Failed
**Check:**
1. Containers running?
2. Correct credentials?
3. Port conflicts?

**Fix:**
```bash
docker-compose down
docker-compose up -d
# Wait 30 seconds for initialization
docker exec lascopf_postgres pg_isready
```

### Issue: Out of Memory
**Fix:**
```yaml
# Edit docker-compose.yml
services:
  julia-solver:
    deploy:
      resources:
        limits:
          memory: 8G
```

---

## 📈 Performance Tuning

### Julia Optimization
```julia
# Enable multi-threading
ENV["JULIA_NUM_THREADS"] = "8"

# BLAS threads
using LinearAlgebra
BLAS.set_num_threads(8)

# Precompile packages
using Pkg
Pkg.precompile()
```

### Database Optimization
```sql
-- Add indexes
CREATE INDEX CONCURRENTLY idx_custom ON table_name (column);

-- Vacuum
VACUUM ANALYZE table_name;

-- Check slow queries
SELECT * FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;
```

### Airflow Scaling
```yaml
# docker-compose.yml
airflow-worker:
  deploy:
    replicas: 4  # Multiple workers
```

---

## 📚 Example Workflows

### 1. Daily Production Run
```bash
# Automated via Airflow (2 AM daily)
# Manual trigger:
curl -X POST http://localhost:8080/api/v1/dags/lascopf_daily_pipeline/dagRuns \
  -H "Content-Type: application/json" \
  -d '{"conf": {"case_name": "RTS_GMLC"}}'
```

### 2. Load New Case Study
```python
from data_engineering.ingestion.load_examples import ExampleCaseLoader

loader = ExampleCaseLoader(db_config)
loader.connect()
topology_id = loader.load_case_from_matpower("case_new.m", "case_new")
loader.close()
```

### 3. Query Results
```julia
using PowerLASCOPF.DataLoader

db = DatabaseConnection()
query = """
    SELECT g.generator_id, g.active_power_mw, b.lmp_total
    FROM generator_dispatch_results g
    JOIN bus_results b ON g.execution_id = b.execution_id 
        AND g.time_step = b.time_step
    WHERE g.execution_id = 'your-execution-id'
"""
results = execute(db.metadata_conn, query)
close(db)
```

---

## 🔐 Security Checklist

- [ ] Change default passwords in `.env`
- [ ] Enable SSL for database connections
- [ ] Set up firewall rules
- [ ] Implement API authentication
- [ ] Regular security updates
- [ ] Backup encryption
- [ ] Access logging enabled

---

## 📞 Quick Help

| Issue | Solution |
|-------|----------|
| Container won't start | Check logs: `docker-compose logs <service>` |
| Can't connect to DB | Verify: `docker exec <container> pg_isready` |
| Solver fails | Check config: `cat /tmp/test_config.json` |
| DAG not visible | Restart scheduler, check DAG file syntax |
| Slow performance | Check resources: `docker stats` |

---

## 📝 Useful SQL Queries

```sql
-- Recent executions
SELECT * FROM v_latest_executions LIMIT 10;

-- Convergence statistics
SELECT 
    execution_id,
    AVG(iteration_time_seconds) as avg_iter_time,
    MAX(primal_residual) as max_primal_res
FROM convergence_history
GROUP BY execution_id;

-- System-wide generation
SELECT 
    time_step,
    SUM(active_power_mw) as total_generation,
    AVG(generation_cost) as avg_cost
FROM generator_dispatch_results
WHERE execution_id = 'your-id'
GROUP BY time_step;

-- LMP statistics
SELECT * FROM v_lmp_statistics 
WHERE execution_id = 'your-id'
ORDER BY time_step;
```

---

## 🎯 Next Steps After Setup

1. **Validate Installation**
   - Run all tests
   - Execute sample case
   - Verify results in Grafana

2. **Load Your Data**
   - Import actual network topology
   - Add historical measurements
   - Define contingencies

3. **Customize Solver**
   - Integrate your ADMM/APP code
   - Tune parameters
   - Add custom constraints

4. **Scale Up**
   - Add more workers
   - Enable distributed computing
   - Optimize database queries

5. **Production Ready**
   - Set up monitoring
   - Configure backups
   - Document procedures

---

**Version**: 1.0.0  
**Last Updated**: December 2024