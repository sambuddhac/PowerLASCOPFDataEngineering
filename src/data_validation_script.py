# scripts/validate_all_data.py

"""
Validation script to check data quality for all loaded cases
Uses Great Expectations to validate power system data
"""

import sys
from pathlib import Path
import psycopg2
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_engineering.validation.expectations import PowerSystemDataValidator


class DataQualityValidator:
    """Validate all loaded power system data"""
    
    def __init__(self):
        self.db_config = {
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
        
        self.validator = PowerSystemDataValidator()
        self.validation_results = []
    
    def get_all_cases(self):
        """Get list of all cases in database"""
        conn = psycopg2.connect(**self.db_config['metadata'])
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT case_name FROM network_topology ORDER BY case_name")
        cases = [row[0] for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        return cases
    
    def validate_case(self, case_name: str):
        """Validate one case"""
        print(f"\nValidating: {case_name}")
        print("-" * 60)
        
        conn_ts = psycopg2.connect(**self.db_config['timeseries'])
        
        case_results = {
            'case_name': case_name,
            'validations': {},
            'overall_success': True
        }
        
        try:
            # Validate power measurements
            print("  Checking power measurements...")
            power_query = f"""
                SELECT * FROM power_measurements 
                WHERE case_name = '{case_name}'
                AND time >= NOW() - INTERVAL '7 days'
                LIMIT 10000
            """
            
            power_df = pd.read_sql(power_query, conn_ts)
            
            if not power_df.empty:
                power_results = self.validator.validate_dataframe(
                    power_df,
                    'power_measurements_suite'
                )
                
                case_results['validations']['power_measurements'] = power_results
                
                if power_results['success']:
                    print("    ✓ Power measurements: PASSED")
                else:
                    print("    ✗ Power measurements: FAILED")
                    case_results['overall_success'] = False
                    
                    # Print failures
                    for result in power_results['results']:
                        if not result['success']:
                            print(f"      - {result['expectation_type']}: {result.get('observed_value')}")
            else:
                print("    ⚠ No power measurements found")
                case_results['validations']['power_measurements'] = {'success': False, 'error': 'No data'}
                case_results['overall_success'] = False
            
            # Validate generator measurements
            print("  Checking generator measurements...")
            gen_query = f"""
                SELECT * FROM generator_measurements 
                WHERE case_name = '{case_name}'
                AND time >= NOW() - INTERVAL '7 days'
                LIMIT 10000
            """
            
            gen_df = pd.read_sql(gen_query, conn_ts)
            
            if not gen_df.empty:
                gen_results = self.validator.validate_dataframe(
                    gen_df,
                    'generator_measurements_suite'
                )
                
                case_results['validations']['generator_measurements'] = gen_results
                
                if gen_results['success']:
                    print("    ✓ Generator measurements: PASSED")
                else:
                    print("    ✗ Generator measurements: FAILED")
                    case_results['overall_success'] = False
                    
                    for result in gen_results['results']:
                        if not result['success']:
                            print(f"      - {result['expectation_type']}: {result.get('observed_value')}")
            else:
                print("    ⚠ No generator measurements found")
            
            # Check data coverage
            print("  Checking data coverage...")
            coverage_query = f"""
                SELECT 
                    MIN(time) as earliest,
                    MAX(time) as latest,
                    COUNT(DISTINCT DATE(time)) as days_covered,
                    COUNT(*) as total_measurements
                FROM power_measurements
                WHERE case_name = '{case_name}'
            """
            
            coverage_df = pd.read_sql(coverage_query, conn_ts)
            if not coverage_df.empty:
                row = coverage_df.iloc[0]
                print(f"    Earliest: {row['earliest']}")
                print(f"    Latest: {row['latest']}")
                print(f"    Days covered: {row['days_covered']}")
                print(f"    Total measurements: {row['total_measurements']}")
                
                case_results['coverage'] = {
                    'earliest': str(row['earliest']),
                    'latest': str(row['latest']),
                    'days_covered': int(row['days_covered']),
                    'total_measurements': int(row['total_measurements'])
                }
            
        finally:
            conn_ts.close()
        
        self.validation_results.append(case_results)
        
        return case_results['overall_success']
    
    def validate_topology(self, case_name: str):
        """Validate network topology"""
        print(f"  Checking network topology...")
        
        conn = psycopg2.connect(**self.db_config['metadata'])
        cursor = conn.cursor()
        
        try:
            # Get topology
            cursor.execute("""
                SELECT system_data, num_buses, num_generators, num_branches
                FROM network_topology
                WHERE case_name = %s
            """, (case_name,))
            
            row = cursor.fetchone()
            if not row:
                print(f"    ✗ Topology not found")
                return False
            
            system_data, num_buses, num_gens, num_branches = row
            
            # Validate counts match
            actual_buses = len(system_data['buses'])
            actual_gens = len(system_data['generators'])
            actual_branches = len(system_data['branches'])
            
            if actual_buses == num_buses and actual_gens == num_gens and actual_branches == num_branches:
                print(f"    ✓ Topology counts match")
            else:
                print(f"    ✗ Topology counts mismatch:")
                print(f"      Buses: {actual_buses} vs {num_buses}")
                print(f"      Generators: {actual_gens} vs {num_gens}")
                print(f"      Branches: {actual_branches} vs {num_branches}")
                return False
            
            # Check for required fields
            required_bus_fields = ['number', 'name', 'base_voltage']
            for bus in system_data['buses']:
                if not all(field in bus for field in required_bus_fields):
                    print(f"    ✗ Bus missing required fields: {bus.get('name')}")
                    return False
            
            required_gen_fields = ['name', 'bus_number', 'pmin', 'pmax']
            for gen in system_data['generators']:
                if not all(field in gen for field in required_gen_fields):
                    print(f"    ✗ Generator missing required fields: {gen.get('name')}")
                    return False
            
            print(f"    ✓ All components have required fields")
            
            # Check contingencies
            cursor.execute("""
                SELECT COUNT(*) FROM contingencies
                WHERE topology_id = (
                    SELECT topology_id FROM network_topology WHERE case_name = %s
                )
            """, (case_name,))
            
            cont_count = cursor.fetchone()[0]
            print(f"    ✓ Contingencies defined: {cont_count}")
            
            return True
            
        finally:
            cursor.close()
            conn.close()
    
    def generate_report(self):
        """Generate validation report"""
        print("\n" + "="*60)
        print("VALIDATION SUMMARY")
        print("="*60)
        
        total_cases = len(self.validation_results)
        passed_cases = sum(1 for r in self.validation_results if r['overall_success'])
        
        print(f"\nTotal cases validated: {total_cases}")
        print(f"Passed: {passed_cases}")
        print(f"Failed: {total_cases - passed_cases}")
        
        print("\nDetailed Results:")
        print("-" * 60)
        
        for result in self.validation_results:
            status = "✓ PASS" if result['overall_success'] else "✗ FAIL"
            print(f"{result['case_name']:<20} {status}")
            
            if 'coverage' in result:
                cov = result['coverage']
                print(f"  Coverage: {cov['days_covered']} days, {cov['total_measurements']} measurements")
        
        # Write detailed report to file
        report_path = Path("validation_report.txt")
        with open(report_path, 'w') as f:
            f.write("PowerLASCOPF Data Validation Report\n")
            f.write("="*60 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            for result in self.validation_results:
                f.write(f"\nCase: {result['case_name']}\n")
                f.write("-" * 60 + "\n")
                f.write(f"Overall Status: {'PASS' if result['overall_success'] else 'FAIL'}\n\n")
                
                if 'validations' in result:
                    for val_type, val_result in result['validations'].items():
                        f.write(f"{val_type}:\n")
                        f.write(f"  Success: {val_result.get('success', False)}\n")
                        
                        if 'statistics' in val_result:
                            stats = val_result['statistics']
                            f.write(f"  Evaluated: {stats.get('evaluated_expectations', 0)}\n")
                            f.write(f"  Passed: {stats.get('successful_expectations', 0)}\n")
                            f.write(f"  Failed: {stats.get('unsuccessful_expectations', 0)}\n")
                        
                        f.write("\n")
        
        print(f"\nDetailed report written to: {report_path}")
        
        return passed_cases == total_cases


def main():
    """Main execution"""
    print("="*60)
    print("PowerLASCOPF Data Validation")
    print("="*60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    validator = DataQualityValidator()
    
    # Get all cases
    cases = validator.get_all_cases()
    print(f"Found {len(cases)} cases to validate:")
    for case in cases:
        print(f"  • {case}")
    
    # Validate each case
    all_passed = True
    for case in cases:
        # Validate topology
        topo_ok = validator.validate_topology(case)
        
        # Validate time-series data
        ts_ok = validator.validate_case(case)
        
        if not (topo_ok and ts_ok):
            all_passed = False
    
    # Generate report
    report_ok = validator.generate_report()
    
    print(f"\nCompleted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    if all_passed and report_ok:
        print("\n✓ All validations passed!")
        sys.exit(0)
    else:
        print("\n✗ Some validations failed. Check validation_report.txt for details")
        sys.exit(1)


if __name__ == "__main__":
    main()