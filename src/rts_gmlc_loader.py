# data_engineering/ingestion/rts_gmlc_loader.py

"""
RTS-GMLC data loader for PowerLASCOPF
Loads data from GridMod/RTS-GMLC repository into database
"""

import pandas as pd
import psycopg2
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Tuple
import numpy as np


class RTSGMLCLoader:
    """Load RTS-GMLC data into PowerLASCOPF database"""
    
    def __init__(self, rts_path: str, db_config: Dict[str, Dict]):
        """
        Initialize loader
        
        Args:
            rts_path: Path to RTS-GMLC repository
            db_config: Database configuration with 'metadata' and 'timeseries' keys
        """
        self.rts_path = Path(rts_path)
        if not self.rts_path.exists():
            raise FileNotFoundError(f"RTS-GMLC path not found: {rts_path}")
        
        self.source_data = self.rts_path / "SourceData"
        if not self.source_data.exists():
            raise FileNotFoundError(f"SourceData not found in {rts_path}")
        
        self.db_config = db_config
        self.metadata_conn = None
        self.timeseries_conn = None
        
        # Load source data
        self.load_source_data()
    
    def connect(self):
        """Connect to databases"""
        self.metadata_conn = psycopg2.connect(**self.db_config['metadata'])
        self.timeseries_conn = psycopg2.connect(**self.db_config['timeseries'])
    
    def close(self):
        """Close database connections"""
        if self.metadata_conn:
            self.metadata_conn.close()
        if self.timeseries_conn:
            self.timeseries_conn.close()
    
    def load_source_data(self):
        """Load all source CSV files"""
        print("Loading RTS-GMLC source data...")
        
        # Load static data
        self.bus_df = pd.read_csv(self.source_data / "bus.csv")
        self.gen_df = pd.read_csv(self.source_data / "gen.csv")
        self.branch_df = pd.read_csv(self.source_data / "branch.csv")
        self.bus_map_df = pd.read_csv(self.source_data / "bus_map.csv")
        
        # Load time series paths
        ts_path = self.source_data / "timeseries_data_files"
        
        # Load profiles
        self.load_profiles = self._load_timeseries_folder(ts_path / "Load")
        self.wind_profiles = self._load_timeseries_folder(ts_path / "WIND")
        self.solar_profiles = self._load_timeseries_folder(ts_path / "PV")
        self.hydro_profiles = self._load_timeseries_folder(ts_path / "Hydro")
        
        print(f"✓ Loaded {len(self.bus_df)} buses")
        print(f"✓ Loaded {len(self.gen_df)} generators")
        print(f"✓ Loaded {len(self.branch_df)} branches")
    
    def _load_timeseries_folder(self, folder_path: Path) -> Dict[str, pd.DataFrame]:
        """Load all CSV files from a time series folder"""
        if not folder_path.exists():
            return {}
        
        profiles = {}
        for csv_file in folder_path.glob("*.csv"):
            df = pd.read_csv(csv_file)
            profiles[csv_file.stem] = df
        
        return profiles
    
    def convert_to_powerlascopf_json(self) -> Dict:
        """Convert RTS-GMLC data to PowerLASCOPF JSON format"""
        
        # Convert buses
        buses = []
        for _, bus in self.bus_df.iterrows():
            bus_dict = {
                'number': int(bus['Bus ID']),
                'name': str(bus['Bus Name']),
                'type': 1,  # Default to PQ bus
                'base_voltage': float(bus['BaseKV']),
                'voltage_magnitude': 1.0,  # Nominal
                'angle': 0.0,
                'area': str(bus['Area']),
                'zone': str(bus['Zone']),
                'voltage_min': float(bus.get('Vmin', 0.95)),
                'voltage_max': float(bus.get('Vmax', 1.05))
            }
            buses.append(bus_dict)
        
        # Convert generators
        generators = []
        for _, gen in self.gen_df.iterrows():
            gen_dict = {
                'name': str(gen['GEN UID']),
                'bus_number': int(gen['Bus ID']),
                'bus_name': self._get_bus_name(int(gen['Bus ID'])),
                'type': self._map_fuel_type(str(gen['Fuel'])),
                'pmin': float(gen['PMin MW']),
                'pmax': float(gen['PMax MW']),
                'qmin': float(gen.get('QMin MVAR', -gen['PMax MW'])),
                'qmax': float(gen.get('QMax MVAR', gen['PMax MW'])),
                'rating': float(gen['PMax MW']),
                'ramp_up': float(gen.get('Ramp Rate MW/Min', gen['PMax MW'] * 0.5)) * 60,  # Convert to MW/hr
                'ramp_down': float(gen.get('Ramp Rate MW/Min', gen['PMax MW'] * 0.5)) * 60,
                'min_up_time': float(gen.get('Min Up Time Hr', 0)),
                'min_down_time': float(gen.get('Min Down Time Hr', 0)),
                'startup_cost': float(gen.get('Start Cost Cold $', 0)),
                'cost_linear': float(gen.get('Fuel Price $/MMBTU', 0)) * float(gen.get('HR_avg_0', 10)),
                'cost_constant': float(gen.get('Non Fuel O&M $/MWh', 0)),
                'fuel': str(gen['Fuel']),
                'unit_group': str(gen.get('Unit Group', ''))
            }
            generators.append(gen_dict)
        
        # Convert branches
        branches = []
        for _, branch in self.branch_df.iterrows():
            branch_dict = {
                'name': str(branch['UID']),
                'from_bus': int(branch['From Bus']),
                'to_bus': int(branch['To Bus']),
                'from_bus_name': self._get_bus_name(int(branch['From Bus'])),
                'to_bus_name': self._get_bus_name(int(branch['To Bus'])),
                'resistance': float(branch['R']),
                'reactance': float(branch['X']),
                'shunt_susceptance': float(branch.get('B', 0)),
                'rating': float(branch.get('Cont Rating', 0)),
                'rating_emergency': float(branch.get('STE Rating', 0)),
                'ratio': float(branch.get('Tr Ratio', 1.0)),
                'angle': float(branch.get('Tr Angle', 0.0)),
                'type': 'transformer' if branch.get('Tr Ratio', 1.0) != 1.0 else 'line'
            }
            branches.append(branch_dict)
        
        # Extract loads from bus data
        loads = []
        for area in self.bus_map_df['Area'].unique():
            load_dict = {
                'name': f"Load_{area}",
                'area': str(area),
                'buses': self.bus_map_df[self.bus_map_df['Area'] == area]['Bus ID'].tolist()
            }
            loads.append(load_dict)
        
        return {
            'base_mva': 100.0,
            'buses': buses,
            'generators': generators,
            'branches': branches,
            'loads': loads
        }
    
    def _get_bus_name(self, bus_id: int) -> str:
        """Get bus name from bus ID"""
        bus = self.bus_df[self.bus_df['Bus ID'] == bus_id]
        if not bus.empty:
            return str(bus.iloc[0]['Bus Name'])
        return f"Bus{bus_id}"
    
    def _map_fuel_type(self, fuel: str) -> str:
        """Map RTS-GMLC fuel types to PowerLASCOPF types"""
        fuel_map = {
            'Coal': 'THERMAL',
            'NG': 'THERMAL',
            'Nuclear': 'NUCLEAR',
            'Oil': 'THERMAL',
            'Hydro': 'HYDRO',
            'Wind': 'WIND',
            'Solar': 'SOLAR',
            'Sync_Cond': 'SYNC_COND',
            'Storage': 'STORAGE'
        }
        return fuel_map.get(fuel, 'THERMAL')
    
    def load_into_database(self, case_name: str = "RTS_GMLC") -> int:
        """Load RTS-GMLC data into database"""
        
        self.connect()
        
        try:
            # Insert topology
            topology_id = self._insert_topology(case_name)
            
            # Insert time series
            self._insert_load_timeseries(topology_id, case_name)
            self._insert_generator_timeseries(topology_id, case_name)
            
            # Generate contingencies
            self._generate_contingencies(topology_id)
            
            print(f"✓ Successfully loaded RTS-GMLC as case '{case_name}' with topology_id={topology_id}")
            
            return topology_id
            
        finally:
            self.close()
    
    def _insert_topology(self, case_name: str) -> int:
        """Insert network topology"""
        
        cursor = self.metadata_conn.cursor()
        
        system_json = self.convert_to_powerlascopf_json()
        
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
            "RTS-GMLC: Reliability Test System - Grid Modernization Lab Consortium",
            "RTS-GMLC"
        ))
        
        topology_id = cursor.fetchone()[0]
        self.metadata_conn.commit()
        cursor.close()
        
        return topology_id
    
    def _insert_load_timeseries(self, topology_id: int, case_name: str):
        """Insert load time series data"""
        
        print("Inserting load time series...")
        cursor = self.timeseries_conn.cursor()
        
        # Use 2007 data (typical year in RTS-GMLC)
        if 'regional_Load' in self.load_profiles:
            load_df = self.load_profiles['regional_Load']
            
            # Start from Jan 1, 2024 for consistency
            start_time = datetime(2024, 1, 1, 0, 0, 0)
            
            for idx, row in load_df.iterrows():
                timestamp = start_time + timedelta(hours=idx)
                
                # Insert for each area
                for area in ['Area1', 'Area2', 'Area3']:
                    if area in row:
                        active_power = float(row[area])
                        reactive_power = active_power * 0.3  # Assume 0.95 power factor
                        
                        # Find buses in this area
                        area_buses = self.bus_map_df[self.bus_map_df['Area'] == int(area[-1])]
                        if not area_buses.empty:
                            bus_id = str(area_buses.iloc[0]['Bus ID'])
                            bus_name = self._get_bus_name(int(bus_id))
                            
                            cursor.execute("""
                                INSERT INTO load_measurements (
                                    time, load_id, load_name, bus_id,
                                    active_power_mw, reactive_power_mvar,
                                    source, case_name
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                timestamp,
                                f"Load_{area}",
                                f"Load_{area}",
                                bus_id,
                                active_power,
                                reactive_power,
                                "RTS-GMLC",
                                case_name
                            ))
                
                # Commit every 100 rows for performance
                if idx % 100 == 0:
                    self.timeseries_conn.commit()
                    print(f"  Inserted {idx} load measurements...")
        
        self.timeseries_conn.commit()
        cursor.close()
        print(f"✓ Inserted load time series")
    
    def _insert_generator_timeseries(self, topology_id: int, case_name: str):
        """Insert generator time series data"""
        
        print("Inserting generator time series...")
        cursor = self.timeseries_conn.cursor()
        
        start_time = datetime(2024, 1, 1, 0, 0, 0)
        
        # Insert renewable profiles
        for gen_idx, gen in self.gen_df.iterrows():
            gen_name = str(gen['GEN UID'])
            fuel = str(gen['Fuel'])
            bus_id = str(int(gen['Bus ID']))
            
            # Get appropriate profile
            profile = None
            if fuel == 'Wind' and 'wind_total_2007' in self.wind_profiles:
                profile = self.wind_profiles['wind_total_2007']
                # Scale to generator capacity
                if gen_name in profile.columns:
                    profile_data = profile[gen_name] * gen['PMax MW']
                else:
                    profile_data = None
            
            elif fuel == 'Solar' and 'pv_2007' in self.solar_profiles:
                profile = self.solar_profiles['pv_2007']
                if gen_name in profile.columns:
                    profile_data = profile[gen_name] * gen['PMax MW']
                else:
                    profile_data = None
            
            elif fuel == 'Hydro' and 'Hydro_1' in self.hydro_profiles:
                profile = self.hydro_profiles['Hydro_1']
                if 'Hydro' in profile.columns:
                    profile_data = profile['Hydro'] * gen['PMax MW'] / len(self.gen_df[self.gen_df['Fuel'] == 'Hydro'])
                else:
                    profile_data = None
            
            else:
                # For thermal, use base load factor
                profile_data = pd.Series([gen['PMin MW'] + 0.7 * (gen['PMax MW'] - gen['PMin MW'])] * 8760)
            
            if profile_data is not None:
                for idx, power in enumerate(profile_data[:8760]):  # Full year
                    timestamp = start_time + timedelta(hours=idx)
                    
                    cursor.execute("""
                        INSERT INTO generator_measurements (
                            time, generator_id, generator_name, bus_id,
                            active_power_mw, reactive_power_mvar,
                            commitment_status, marginal_cost,
                            generator_type, source, case_name
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        timestamp,
                        gen_name,
                        gen_name,
                        bus_id,
                        float(power) if not pd.isna(power) else 0.0,
                        float(power * 0.3) if not pd.isna(power) else 0.0,
                        True,
                        float(gen.get('Fuel Price $/MMBTU', 30.0)),
                        self._map_fuel_type(fuel),
                        "RTS-GMLC",
                        case_name
                    ))
                    
                    if idx % 1000 == 0:
                        self.timeseries_conn.commit()
        
        self.timeseries_conn.commit()
        cursor.close()
        print(f"✓ Inserted generator time series")
    
    def _generate_contingencies(self, topology_id: int):
        """Generate N-1 contingencies"""
        
        print("Generating contingencies...")
        cursor = self.metadata_conn.cursor()
        
        # Branch N-1 contingencies
        for _, branch in self.branch_df.iterrows():
            cursor.execute("""
                INSERT INTO contingencies (
                    topology_id, contingency_name, contingency_type,
                    affected_branches, probability, severity_level, description
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                topology_id,
                f"N-1_{branch['UID']}",
                "N-1",
                [str(branch['UID'])],
                0.01,
                2,
                f"Single branch outage: {branch['UID']}"
            ))
        
        # Generator N-1 contingencies (large units only)
        large_gens = self.gen_df[self.gen_df['PMax MW'] > 100]
        for _, gen in large_gens.iterrows():
            cursor.execute("""
                INSERT INTO contingencies (
                    topology_id, contingency_name, contingency_type,
                    affected_generators, probability, severity_level, description
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                topology_id,
                f"N-1_{gen['GEN UID']}",
                "N-1",
                [str(gen['GEN UID'])],
                0.005,
                3,
                f"Single generator outage: {gen['GEN UID']} ({gen['PMax MW']} MW)"
            ))
        
        self.metadata_conn.commit()
        cursor.close()
        print(f"✓ Generated contingencies")


# CLI interface
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python rts_gmlc_loader.py <path_to_RTS-GMLC>")
        sys.exit(1)
    
    rts_path = sys.argv[1]
    
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
    
    try:
        loader = RTSGMLCLoader(rts_path, db_config)
        topology_id = loader.load_into_database()
        print(f"\n✓ Successfully loaded RTS-GMLC with topology_id={topology_id}")
    except Exception as e:
        print(f"Error loading RTS-GMLC: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)