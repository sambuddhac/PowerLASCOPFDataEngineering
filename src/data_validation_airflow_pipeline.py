# data_engineering/validation/expectations.py

"""
Great Expectations validation suite for PowerLASCOPF data
"""

import great_expectations as gx
from great_expectations.core.batch import BatchRequest
from great_expectations.checkpoint import SimpleCheckpoint
import pandas as pd
from typing import Dict, Any


class PowerSystemDataValidator:
    """Validator for power system measurements"""
    
    def __init__(self, context_root_dir: str = "./gx"):
        self.context = gx.get_context(context_root_dir=context_root_dir)
    
    def create_power_measurements_suite(self) -> str:
        """Create expectation suite for power measurements"""
        
        suite_name = "power_measurements_suite"
        
        # Create or get existing suite
        try:
            suite = self.context.get_expectation_suite(suite_name)
        except:
            suite = self.context.add_expectation_suite(suite_name)
        
        # Define expectations
        validator = self.context.get_validator(
            batch_request=BatchRequest(
                datasource_name="postgres_datasource",
                data_connector_name="default_inferred_data_connector",
                data_asset_name="power_measurements"
            ),
            expectation_suite_name=suite_name
        )
        
        # Voltage magnitude constraints (0.9 - 1.1 pu)
        validator.expect_column_values_to_be_between(
            column="voltage_magnitude",
            min_value=0.85,
            max_value=1.15,
            mostly=0.98,  # 98% should be within normal limits
            meta={
                "notes": "Voltage should be within ±10% of nominal (with 2% tolerance)"
            }
        )
        
        # Voltage angle constraints (-π to π radians)
        validator.expect_column_values_to_be_between(
            column="voltage_angle_rad",
            min_value=-3.15,
            max_value=3.15
        )
        
        # Frequency constraints (59.5 - 60.5 Hz for 60Hz system)
        validator.expect_column_values_to_be_between(
            column="frequency_hz",
            min_value=59.5,
            max_value=60.5,
            mostly=0.999,
            meta={
                "notes": "Frequency should be tightly controlled"
            }
        )
        
        # No null values in critical columns
        for column in ["bus_id", "voltage_magnitude", "active_power_mw"]:
            validator.expect_column_values_to_not_be_null(
                column=column
            )
        
        # Measurement quality should be high
        validator.expect_column_values_to_be_between(
            column="measurement_quality",
            min_value=80,
            max_value=100,
            mostly=0.95
        )
        
        # Time should be increasing and not in future
        validator.expect_column_values_to_be_increasing(
            column="time",
            strictly=False
        )
        
        validator.save_expectation_suite(discard_failed_expectations=False)
        
        return suite_name
    
    def create_generator_measurements_suite(self) -> str:
        """Create expectation suite for generator measurements"""
        
        suite_name = "generator_measurements_suite"
        
        try:
            suite = self.context.get_expectation_suite(suite_name)
        except:
            suite = self.context.add_expectation_suite(suite_name)
        
        validator = self.context.get_validator(
            batch_request=BatchRequest(
                datasource_name="postgres_datasource",
                data_connector_name="default_inferred_data_connector",
                data_asset_name="generator_measurements"
            ),
            expectation_suite_name=suite_name
        )
        
        # Active power should be non-negative for most generators
        validator.expect_column_values_to_be_between(
            column="active_power_mw",
            min_value=0,
            max_value=10000,  # Reasonable upper bound
            mostly=0.98
        )
        
        # Commitment status should be boolean
        validator.expect_column_values_to_be_in_set(
            column="commitment_status",
            value_set=[True, False, None]
        )
        
        # Generator type should be valid
        validator.expect_column_values_to_be_in_set(
            column="generator_type",
            value_set=["THERMAL", "HYDRO", "WIND", "SOLAR", "STORAGE", "NUCLEAR"]
        )
        
        # Marginal cost should be reasonable
        validator.expect_column_values_to_be_between(
            column="marginal_cost",
            min_value=0,
            max_value=1000,  # $/MWh
            mostly=0.95
        )
        
        validator.save_expectation_suite(discard_failed_expectations=False)
        
        return suite_name
    
    def create_branch_measurements_suite(self) -> str:
        """Create expectation suite for branch/line measurements"""
        
        suite_name = "branch_measurements_suite"
        
        try:
            suite = self.context.get_expectation_suite(suite_name)
        except:
            suite = self.context.add_expectation_suite(suite_name)
        
        validator = self.context.get_validator(
            batch_request=BatchRequest(
                datasource_name="postgres_datasource",
                data_connector_name="default_inferred_data_connector",
                data_asset_name="branch_measurements"
            ),
            expectation_suite_name=suite_name
        )
        
        # Loading percentage should be 0-100% (with some tolerance)
        validator.expect_column_values_to_be_between(
            column="loading_percentage",
            min_value=0,
            max_value=120,  # Allow slight overload
            mostly=0.99
        )
        
        # Power flow conservation check
        # |P_from + P_to| should be small (losses)
        validator.expect_column_pair_values_a_to_be_greater_than_b(
            column_a="from_bus_active_power_mw",
            column_b="to_bus_active_power_mw",
            or_equal=True,
            mostly=0.5  # Direction dependent
        )
        
        validator.save_expectation_suite(discard_failed_expectations=False)
        
        return suite_name
    
    def validate_dataframe(self, df: pd.DataFrame, suite_name: str) -> Dict[str, Any]:
        """Validate a dataframe against an expectation suite"""
        
        # Create batch from dataframe
        batch = self.context.sources.add_or_update_pandas(
            "pandas_datasource"
        ).read_dataframe(df)
        
        # Run validation
        results = batch.validate(
            expectation_suite_name=suite_name
        )
        
        return {
            "success": results.success,
            "statistics": results.statistics,
            "results": [
                {
                    "expectation_type": result.expectation_config.expectation_type,
                    "success": result.success,
                    "observed_value": result.result.get("observed_value"),
                }
                for result in results.results
            ]
        }


# =============================================================================
# data_engineering/ingestion/load_examples.py
# =============================================================================

"""
Load PowerLASCOPF example cases into database
"""

import os
import json
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List
import numpy as np


class ExampleCaseLoader:
    """Load example cases from PowerLASCOPF.jl into database"""
    
    def __init__(self, db_config: Dict[str, str]):
        self.db_config = db_config
        self.metadata_conn = None
        self.timeseries_conn = None
    
    def connect(self):
        """Establish database connections"""
        self.metadata_conn = psycopg2.connect(**self.db_config["metadata"])
        self.timeseries_conn = psycopg2.connect(**self.db_config["timeseries"])
    
    def close(self):
        """Close database connections"""
        if self.metadata_conn:
            self.metadata_conn.close()
        if self.timeseries_conn:
            self.timeseries_conn.close()
    
    def load_case_from_matpower(self, case_file: str, case_name: str):
        """
        Load a MATPOWER case file and populate database
        
        This is a simplified example - you'd parse actual MATPOWER format
        """
        
        # Parse MATPOWER file (simplified)
        case_data = self._parse_matpower_file(case_file)
        
        # Insert network topology
        topology_id = self._insert_network_topology(case_name, case_data)
        
        # Generate and insert time-series data
        self._generate_time_series_data(topology_id, case_name, case_data)
        
        # Create contingencies
        self._create_contingencies(topology_id, case_data)
        
        return topology_id
    
    def _parse_matpower_file(self, case_file: str) -> Dict:
        """Parse MATPOWER case file - simplified example"""
        
        # In practice, you'd use a proper MATPOWER parser
        # For now, return example structure
        return {
            "base_mva": 100.0,
            "buses": [
                {"number": 1, "name": "Bus1", "base_voltage": 138.0, 
                 "voltage_magnitude": 1.0, "angle": 0.0, "area": "Area1", "zone": "Zone1"},
                {"number": 2, "name": "Bus2", "base_voltage": 138.0,
                 "voltage_magnitude": 1.0, "angle": 0.0, "area": "Area1", "zone": "Zone1"},
            ],
            "generators": [
                {"name": "Gen1", "bus_name": "Bus1", "type": "THERMAL",
                 "pmin": 10.0, "pmax": 100.0, "rating": 110.0,
                 "cost_linear": 30.0, "cost_fixed": 0.0, "startup_cost": 100.0,
                 "ramp_up": 30.0, "ramp_down": 30.0},
            ],
            "branches": [
                {"name": "Line1-2", "from_bus_name": "Bus1", "to_bus_name": "Bus2",
                 "resistance": 0.01, "reactance": 0.1, "shunt_susceptance": 0.0,
                 "rating": 150.0},
            ],
            "loads": [
                {"name": "Load1", "bus_name": "Bus1", 
                 "active_power": 50.0, "reactive_power": 20.0},
            ]
        }
    
    def _insert_network_topology(self, case_name: str, case_data: Dict) -> int:
        """Insert network topology into database"""
        
        cursor = self.metadata_conn.cursor()
        
        query = """
            INSERT INTO network_topology (
                case_name, num_buses, num_generators, num_branches, num_loads,
                base_mva, system_data, description, source
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING topology_id
        """
        
        cursor.execute(query, (
            case_name,
            len(case_data["buses"]),
            len(case_data["generators"]),
            len(case_data["branches"]),
            len(case_data["loads"]),
            case_data["base_mva"],
            json.dumps(case_data),
            f"Example case: {case_name}",
            "MATPOWER"
        ))
        
        topology_id = cursor.fetchone()[0]
        self.metadata_conn.commit()
        cursor.close()
        
        print(f"Inserted topology {topology_id} for case {case_name}")
        return topology_id
    
    def _generate_time_series_data(self, topology_id: int, case_name: str, 
                                   case_data: Dict, num_hours: int = 168):
        """Generate synthetic time-series data for testing"""
        
        start_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        times = [start_time + timedelta(hours=i) for i in range(num_hours)]
        
        cursor = self.timeseries_conn.cursor()
        
        # Generate bus measurements
        for bus in case_data["buses"]:
            for t in times:
                # Add some realistic variation
                voltage = bus["voltage_magnitude"] + np.random.normal(0, 0.01)
                angle = bus["angle"] + np.random.normal(0, 0.05)
                
                cursor.execute("""
                    INSERT INTO power_measurements (
                        time, bus_id, bus_name, voltage_magnitude, voltage_angle_rad,
                        frequency_hz, measurement_quality, source, case_name
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    t, str(bus["number"]), bus["name"],
                    voltage, angle, 60.0, 100, "SIMULATED", case_name
                ))
        
        # Generate generator measurements with daily load profile
        for gen in case_data["generators"]:
            for i, t in enumerate(times):
                hour_of_day = t.hour
                # Simple daily load profile
                load_factor = 0.6 + 0.3 * np.sin((hour_of_day - 6) * np.pi / 12)
                power = gen["pmin"] + load_factor * (gen["pmax"] - gen["pmin"])
                power += np.random.normal(0, 2)  # Add noise
                
                cursor.execute("""
                    INSERT INTO generator_measurements (
                        time, generator_id, generator_name, bus_id, active_power_mw,
                        reactive_power_mvar, commitment_status, marginal_cost,
                        generator_type, source, case_name
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    t, gen["name"], gen["name"], "1",
                    power, power * 0.3, True, gen["cost_linear"],
                    gen["type"], "SIMULATED", case_name
                ))
        
        # Generate load measurements
        for load in case_data["loads"]:
            for i, t in enumerate(times):
                hour_of_day = t.hour
                # Daily load profile
                load_factor = 0.6 + 0.3 * np.sin((hour_of_day - 6) * np.pi / 12)
                active = load["active_power"] * load_factor + np.random.normal(0, 1)
                reactive = load["reactive_power"] * load_factor
                
                cursor.execute("""
                    INSERT INTO load_measurements (
                        time, load_id, load_name, bus_id, active_power_mw,
                        reactive_power_mvar, source, case_name
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    t, load["name"], load["name"], "1",
                    active, reactive, "SIMULATED", case_name
                ))
        
        self.timeseries_conn.commit()
        cursor.close()
        
        print(f"Generated {num_hours} hours of time-series data")
    
    def _create_contingencies(self, topology_id: int, case_data: Dict):
        """Create N-1 contingencies for branches and generators"""
        
        cursor = self.metadata_conn.cursor()
        
        # Branch contingencies (N-1)
        for branch in case_data["branches"]:
            cursor.execute("""
                INSERT INTO contingencies (
                    topology_id, contingency_name, contingency_type,
                    affected_branches, probability, severity_level, description
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                topology_id,
                f"N-1_{branch['name']}",
                "N-1",
                [branch["name"]],
                0.01,
                2,
                f"Single line outage: {branch['name']}"
            ))
        
        # Generator contingencies (N-1)
        for gen in case_data["generators"]:
            cursor.execute("""
                INSERT INTO contingencies (
                    topology_id, contingency_name, contingency_type,
                    affected_generators, probability, severity_level, description
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                topology_id,
                f"N-1_{gen['name']}",
                "N-1",
                [gen["name"]],
                0.005,
                3,
                f"Single generator outage: {gen['name']}"
            ))
        
        self.metadata_conn.commit()
        cursor.close()
        
        print(f"Created contingencies for topology {topology_id}")


# =============================================================================
# data_engineering/orchestration/airflow_dags/daily_pipeline.py
# =============================================================================

"""
Airflow DAG for daily PowerLASCOPF execution
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from datetime import datetime, timedelta
import subprocess
import json
import sys
import os

# Add data_engineering to path
sys.path.insert(0, '/opt/airflow/plugins')

from data_engineering.validation.expectations import PowerSystemDataValidator
from data_engineering.ingestion.load_examples import ExampleCaseLoader

default_args = {
    'owner': 'lascopf',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'lascopf_daily_pipeline',
    default_args=default_args,
    description='Daily PowerLASCOPF execution pipeline',
    schedule_interval='0 2 * * *',  # Run at 2 AM daily
    catchup=False,
    tags=['lascopf', 'optimization', 'daily']
)


def check_database_connection(**context):
    """Verify database connections are working"""
    
    # Check metadata database
    metadata_hook = PostgresHook(postgres_conn_id='lascopf_metadata')
    metadata_conn = metadata_hook.get_conn()
    cursor = metadata_conn.cursor()
    cursor.execute("SELECT 1")
    result = cursor.fetchone()
    assert result[0] == 1, "Metadata database connection failed"
    cursor.close()
    metadata_conn.close()
    
    # Check timeseries database
    timeseries_hook = PostgresHook(postgres_conn_id='lascopf_timeseries')
    timeseries_conn = timeseries_hook.get_conn()
    cursor = timeseries_conn.cursor()
    cursor.execute("SELECT 1")
    result = cursor.fetchone()
    assert result[0] == 1, "TimescaleDB connection failed"
    cursor.close()
    timeseries_conn.close()
    
    print("✓ Database connections verified")


def load_example_case(**context):
    """Load example case data if not already loaded"""
    
    case_name = context['dag_run'].conf.get('case_name', 'RTS_GMLC')
    
    db_config = {
        "metadata": {
            "host": "postgres",
            "port": 5432,
            "database": "lascopf_metadata",
            "user": "lascopf",
            "password": "lascopf_pass_2024"
        },
        "timeseries": {
            "host": "timescaledb",
            "port": 5432,
            "database": "lascopf_timeseries",
            "user": "lascopf",
            "password": "lascopf_pass_2024"
        }
    }
    
    loader = ExampleCaseLoader(db_config)
    loader.connect()
    
    try:
        # Check if case already exists
        cursor = loader.metadata_conn.cursor()
        cursor.execute(
            "SELECT topology_id FROM network_topology WHERE case_name = %s",
            (case_name,)
        )
        result = cursor.fetchone()
        
        if result:
            topology_id = result[0]
            print(f"Case {case_name} already loaded with topology_id={topology_id}")
        else:
            # Load new case
            case_file = f"/opt/airflow/example_cases/{case_name}.m"
            topology_id = loader.load_case_from_matpower(case_file, case_name)
            print(f"Loaded new case {case_name} with topology_id={topology_id}")
        
        # Push topology_id to XCom for downstream tasks
        context['task_instance'].xcom_push(key='topology_id', value=topology_id)
        context['task_instance'].xcom_push(key='case_name', value=case_name)
        
    finally:
        loader.close()


def validate_input_data(**context):
    """Validate input data quality using Great Expectations"""
    
    case_name = context['task_instance'].xcom_pull(key='case_name')
    
    validator = PowerSystemDataValidator()
    
    # Create expectation suites if they don't exist
    validator.create_power_measurements_suite()
    validator.create_generator_measurements_suite()
    validator.create_branch_measurements_suite()
    
    # Load recent data for validation
    timeseries_hook = PostgresHook(postgres_conn_id='lascopf_timeseries')
    
    # Validate power measurements
    power_query = f"""
        SELECT * FROM power_measurements 
        WHERE case_name = '{case_name}'
        AND time >= NOW() - INTERVAL '24 hours'
    """
    power_df = timeseries_hook.get_pandas_df(power_query)
    
    if not power_df.empty:
        power_results = validator.validate_dataframe(
            power_df, 
            "power_measurements_suite"
        )
        
        if not power_results["success"]:
            failed_expectations = [
                r for r in power_results["results"] if not r["success"]
            ]
            print(f"⚠ Power measurements validation warnings: {failed_expectations}")
        else:
            print("✓ Power measurements validation passed")
    
    # Validate generator measurements
    gen_query = f"""
        SELECT * FROM generator_measurements 
        WHERE case_name = '{case_name}'
        AND time >= NOW() - INTERVAL '24 hours'
    """
    gen_df = timeseries_hook.get_pandas_df(gen_query)
    
    if not gen_df.empty:
        gen_results = validator.validate_dataframe(
            gen_df,
            "generator_measurements_suite"
        )
        
        if not gen_results["success"]:
            failed_expectations = [
                r for r in gen_results["results"] if not r["success"]
            ]
            print(f"⚠ Generator measurements validation warnings: {failed_expectations}")
        else:
            print("✓ Generator measurements validation passed")


def prepare_julia_input(**context):
    """Prepare input files for Julia solver"""
    
    topology_id = context['task_instance'].xcom_pull(key='topology_id')
    case_name = context['task_instance'].xcom_pull(key='case_name')
    execution_date = context['execution_date']
    
    config = {
        "topology_id": topology_id,
        "case_name": case_name,
        "execution_date": execution_date.isoformat(),
        "optimization_horizon_hours": 24,
        "num_time_steps": 24,
        "admm_rho": 1.0,
        "app_beta": 1.0,
        "app_gamma": 1.0,
        "max_iterations": 100,
        "convergence_tolerance": 1e-4
    }
    
    # Write config to file
    config_path = f"/tmp/lascopf_config_{execution_date.strftime('%Y%m%d')}.json"
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    context['task_instance'].xcom_push(key='config_path', value=config_path)
    print(f"✓ Configuration written to {config_path}")


def execute_julia_solver(**context):
    """Execute PowerLASCOPF Julia solver"""
    
    config_path = context['task_instance'].xcom_pull(key='config_path')
    
    # Julia script path
    julia_script = "/app/scripts/run_lascopf.jl"
    
    # Execute Julia
    cmd = [
        "docker", "exec", "lascopf_julia_solver",
        "julia", "--project=/app", julia_script, config_path
    ]
    
    print(f"Executing: {' '.join(cmd)}")
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=3600  # 1 hour timeout
    )
    
    if result.returncode != 0:
        print(f"STDERR: {result.stderr}")
        raise RuntimeError(f"Julia solver failed with code {result.returncode}")
    
    print(f"STDOUT: {result.stdout}")
    
    # Parse execution_id from output
    for line in result.stdout.split('\n'):
        if 'execution_id:' in line:
            execution_id = line.split(':')[1].strip()
            context['task_instance'].xcom_push(key='execution_id', value=execution_id)
            print(f"✓ Solver completed with execution_id={execution_id}")
            break


def validate_results(**context):
    """Validate solver results"""
    
    execution_id = context['task_instance'].xcom_pull(key='execution_id')
    
    metadata_hook = PostgresHook(postgres_conn_id='lascopf_metadata')
    
    # Check execution status
    query = """
        SELECT convergence_status, objective_value, solve_time_seconds, final_iteration
        FROM lascopf_executions
        WHERE execution_id = %s
    """
    
    result = metadata_hook.get_first(query, parameters=(execution_id,))
    
    if not result:
        raise ValueError(f"Execution {execution_id} not found in database")
    
    status, objective, solve_time, iterations = result
    
    print(f"Status: {status}")
    print(f"Objective: {objective}")
    print(f"Solve time: {solve_time}s")
    print(f"Iterations: {iterations}")
    
    if status != "CONVERGED":
        raise RuntimeError(f"Solver did not converge: {status}")
    
    # Validate dispatch results exist
    dispatch_query = """
        SELECT COUNT(*) FROM generator_dispatch_results
        WHERE execution_id = %s
    """
    
    dispatch_count = metadata_hook.get_first(dispatch_query, parameters=(execution_id,))
    
    if dispatch_count[0] == 0:
        raise ValueError("No dispatch results found")
    
    print(f"✓ Found {dispatch_count[0]} dispatch results")


def generate_report(**context):
    """Generate summary report and visualizations"""
    
    execution_id = context['task_instance'].xcom_pull(key='execution_id')
    
    metadata_hook = PostgresHook(postgres_conn_id='lascopf_metadata')
    
    # Query results summary
    summary_query = """
        SELECT 
            e.execution_time,
            e.convergence_status,
            e.objective_value,
            e.solve_time_seconds,
            COUNT(DISTINCT gd.generator_id) as num_generators,
            SUM(gd.active_power_mw) as total_generation_mw,
            SUM(gd.generation_cost) as total_cost
        FROM lascopf_executions e
        LEFT JOIN generator_dispatch_results gd ON e.execution_id = gd.execution_id
        WHERE e.execution_id = %s
        GROUP BY e.execution_id, e.execution_time, e.convergence_status, 
                 e.objective_value, e.solve_time_seconds
    """
    
    summary = metadata_hook.get_pandas_df(summary_query, parameters=(execution_id,))
    
    print("\n" + "="*60)
    print("LASCOPF EXECUTION SUMMARY")
    print("="*60)
    print(summary.to_string(index=False))
    print("="*60 + "\n")
    
    # Store report path
    report_path = f"/tmp/lascopf_report_{execution_id}.txt"
    with open(report_path, 'w') as f:
        f.write(summary.to_string(index=False))
    
    context['task_instance'].xcom_push(key='report_path', value=report_path)


# Define task dependencies
check_db = PythonOperator(
    task_id='check_database_connection',
    python_callable=check_database_connection,
    dag=dag
)

load_case = PythonOperator(
    task_id='load_example_case',
    python_callable=load_example_case,
    dag=dag
)

validate_input = PythonOperator(
    task_id='validate_input_data',
    python_callable=validate_input_data,
    dag=dag
)

prepare_input = PythonOperator(
    task_id='prepare_julia_input',
    python_callable=prepare_julia_input,
    dag=dag
)

execute_solver = PythonOperator(
    task_id='execute_julia_solver',
    python_callable=execute_julia_solver,
    dag=dag
)

validate_output = PythonOperator(
    task_id='validate_results',
    python_callable=validate_results,
    dag=dag
)

generate_summary = PythonOperator(
    task_id='generate_report',
    python_callable=generate_report,
    dag=dag
)

# Set up task dependencies
check_db >> load_case >> validate_input >> prepare_input >> execute_solver >> validate_output >> generate_summary