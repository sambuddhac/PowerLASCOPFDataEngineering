# data_engineering/transformation/matpower_parser.py

"""
MATPOWER case file parser for PowerLASCOPF
Converts MATPOWER .m files to PowerLASCOPF database format
"""

import re
import numpy as np
from typing import Dict, List, Tuple
from pathlib import Path


class MATPOWERParser:
    """Parse MATPOWER case files (.m format)"""
    
    def __init__(self, case_file: str):
        self.case_file = Path(case_file)
        if not self.case_file.exists():
            raise FileNotFoundError(f"Case file not found: {case_file}")
        
        self.case_data = {}
        self.parse()
    
    def parse(self):
        """Parse the MATPOWER case file"""
        with open(self.case_file, 'r') as f:
            content = f.read()
        
        # Extract base MVA
        self.case_data['baseMVA'] = self._extract_base_mva(content)
        
        # Extract bus data
        self.case_data['bus'] = self._extract_matrix(content, 'mpc.bus')
        
        # Extract generator data
        self.case_data['gen'] = self._extract_matrix(content, 'mpc.gen')
        
        # Extract branch data
        self.case_data['branch'] = self._extract_matrix(content, 'mpc.branch')
        
        # Extract generator cost data
        self.case_data['gencost'] = self._extract_matrix(content, 'mpc.gencost')
        
        # Extract bus names if available
        self.case_data['bus_name'] = self._extract_bus_names(content)
    
    def _extract_base_mva(self, content: str) -> float:
        """Extract base MVA from file"""
        match = re.search(r'mpc\.baseMVA\s*=\s*(\d+\.?\d*)', content)
        if match:
            return float(match.group(1))
        return 100.0  # Default
    
    def _extract_matrix(self, content: str, matrix_name: str) -> np.ndarray:
        """Extract a matrix from MATPOWER format"""
        # Find the matrix definition
        pattern = rf'{matrix_name}\s*=\s*\[(.*?)\];'
        match = re.search(pattern, content, re.DOTALL)
        
        if not match:
            return np.array([])
        
        matrix_str = match.group(1)
        
        # Parse rows
        rows = []
        for line in matrix_str.split('\n'):
            # Remove comments
            line = re.sub(r'%.*$', '', line)
            line = line.strip()
            
            if not line or line.startswith('%'):
                continue
            
            # Remove semicolons and split by whitespace
            line = line.rstrip(';').strip()
            if line:
                # Split by whitespace and convert to floats
                try:
                    row = [float(x) for x in line.split()]
                    if row:  # Only add non-empty rows
                        rows.append(row)
                except ValueError:
                    continue
        
        if rows:
            return np.array(rows)
        return np.array([])
    
    def _extract_bus_names(self, content: str) -> List[str]:
        """Extract bus names if available"""
        pattern = r'mpc\.bus_name\s*=\s*\{(.*?)\};'
        match = re.search(pattern, content, re.DOTALL)
        
        if not match:
            return []
        
        names_str = match.group(1)
        names = []
        
        for line in names_str.split('\n'):
            line = line.strip()
            if line.startswith("'"):
                # Extract string between quotes
                name = re.search(r"'(.*?)'", line)
                if name:
                    names.append(name.group(1))
        
        return names
    
    def to_powerlascopf_json(self) -> Dict:
        """Convert parsed data to PowerLASCOPF JSON format"""
        
        bus_data = self.case_data['bus']
        gen_data = self.case_data['gen']
        branch_data = self.case_data['branch']
        gencost_data = self.case_data['gencost']
        bus_names = self.case_data.get('bus_name', [])
        
        # Convert buses
        buses = []
        for i, bus_row in enumerate(bus_data):
            bus_dict = {
                'number': int(bus_row[0]),
                'name': bus_names[i] if i < len(bus_names) else f"Bus{int(bus_row[0])}",
                'type': int(bus_row[1]),  # 1=PQ, 2=PV, 3=ref, 4=isolated
                'Pd': float(bus_row[2]),  # Active power demand (MW)
                'Qd': float(bus_row[3]),  # Reactive power demand (MVAr)
                'Gs': float(bus_row[4]),  # Shunt conductance (MW at V=1.0 pu)
                'Bs': float(bus_row[5]),  # Shunt susceptance (MVAr at V=1.0 pu)
                'area': int(bus_row[6]),
                'voltage_magnitude': float(bus_row[7]),  # p.u.
                'angle': float(bus_row[8]),  # degrees
                'base_voltage': float(bus_row[9]) if len(bus_row) > 9 else 138.0,  # kV
                'zone': int(bus_row[10]) if len(bus_row) > 10 else 1,
                'voltage_max': float(bus_row[11]) if len(bus_row) > 11 else 1.1,
                'voltage_min': float(bus_row[12]) if len(bus_row) > 12 else 0.9
            }
            buses.append(bus_dict)
        
        # Convert generators
        generators = []
        for i, gen_row in enumerate(gen_data):
            gen_dict = {
                'name': f"Gen{i+1}",
                'bus_number': int(gen_row[0]),
                'bus_name': self._get_bus_name(int(gen_row[0]), buses),
                'type': 'THERMAL',  # Default, could be inferred from cost data
                'Pg': float(gen_row[1]),  # Active power output (MW)
                'Qg': float(gen_row[2]),  # Reactive power output (MVAr)
                'qmax': float(gen_row[3]),  # Max reactive power (MVAr)
                'qmin': float(gen_row[4]),  # Min reactive power (MVAr)
                'Vg': float(gen_row[5]),  # Voltage magnitude setpoint (p.u.)
                'mbase': float(gen_row[6]),  # Base MVA
                'status': int(gen_row[7]),  # Status (1=on, 0=off)
                'pmax': float(gen_row[8]),  # Max active power (MW)
                'pmin': float(gen_row[9]),  # Min active power (MW)
                'rating': float(gen_row[8])  # Use pmax as rating
            }
            
            # Add cost data if available
            if i < len(gencost_data):
                cost_row = gencost_data[i]
                model_type = int(cost_row[0])  # 1=piecewise linear, 2=polynomial
                
                if model_type == 2:  # Polynomial cost
                    n_coeffs = int(cost_row[3])  # Number of coefficients
                    coeffs = cost_row[4:4+n_coeffs]
                    
                    if n_coeffs == 3:  # Quadratic: c2*P^2 + c1*P + c0
                        gen_dict['cost_quadratic'] = float(coeffs[0])
                        gen_dict['cost_linear'] = float(coeffs[1])
                        gen_dict['cost_constant'] = float(coeffs[2])
                    elif n_coeffs == 2:  # Linear: c1*P + c0
                        gen_dict['cost_quadratic'] = 0.0
                        gen_dict['cost_linear'] = float(coeffs[0])
                        gen_dict['cost_constant'] = float(coeffs[1])
                    else:
                        gen_dict['cost_linear'] = 30.0  # Default
                        gen_dict['cost_constant'] = 0.0
                else:
                    gen_dict['cost_linear'] = 30.0  # Default for piecewise
                    gen_dict['cost_constant'] = 0.0
                
                gen_dict['startup_cost'] = float(cost_row[1])
                gen_dict['shutdown_cost'] = float(cost_row[2])
            else:
                gen_dict['cost_linear'] = 30.0
                gen_dict['cost_constant'] = 0.0
                gen_dict['startup_cost'] = 0.0
                gen_dict['shutdown_cost'] = 0.0
            
            # Add ramp rates (default if not specified)
            gen_dict['ramp_up'] = gen_dict['pmax'] * 0.5  # 50% per hour default
            gen_dict['ramp_down'] = gen_dict['pmax'] * 0.5
            
            generators.append(gen_dict)
        
        # Convert branches
        branches = []
        for i, branch_row in enumerate(branch_data):
            branch_dict = {
                'name': f"Line{i+1}",
                'from_bus': int(branch_row[0]),
                'to_bus': int(branch_row[1]),
                'from_bus_name': self._get_bus_name(int(branch_row[0]), buses),
                'to_bus_name': self._get_bus_name(int(branch_row[1]), buses),
                'resistance': float(branch_row[2]),  # p.u.
                'reactance': float(branch_row[3]),  # p.u.
                'shunt_susceptance': float(branch_row[4]),  # p.u.
                'rating_a': float(branch_row[5]),  # MVA rating
                'rating_b': float(branch_row[6]),  # MVA rating (emergency)
                'rating_c': float(branch_row[7]),  # MVA rating (emergency)
                'ratio': float(branch_row[8]) if branch_row[8] != 0 else 1.0,  # Transformer ratio
                'angle': float(branch_row[9]),  # Transformer phase shift angle (degrees)
                'status': int(branch_row[10]),  # Status (1=in-service, 0=out)
                'angle_min': float(branch_row[11]) if len(branch_row) > 11 else -360.0,
                'angle_max': float(branch_row[12]) if len(branch_row) > 12 else 360.0
            }
            
            # Determine if transformer or line
            if branch_dict['ratio'] != 1.0 or branch_dict['angle'] != 0.0:
                branch_dict['type'] = 'transformer'
            else:
                branch_dict['type'] = 'line'
            
            branches.append(branch_dict)
        
        # Extract loads from bus data
        loads = []
        for bus in buses:
            if bus['Pd'] > 0 or bus['Qd'] > 0:
                load_dict = {
                    'name': f"Load_{bus['name']}",
                    'bus_number': bus['number'],
                    'bus_name': bus['name'],
                    'active_power': bus['Pd'],
                    'reactive_power': bus['Qd']
                }
                loads.append(load_dict)
        
        return {
            'base_mva': self.case_data['baseMVA'],
            'buses': buses,
            'generators': generators,
            'branches': branches,
            'loads': loads
        }
    
    def _get_bus_name(self, bus_number: int, buses: List[Dict]) -> str:
        """Get bus name by number"""
        for bus in buses:
            if bus['number'] == bus_number:
                return bus['name']
        return f"Bus{bus_number}"
    
    def get_statistics(self) -> Dict:
        """Get statistics about the parsed case"""
        return {
            'num_buses': len(self.case_data['bus']),
            'num_generators': len(self.case_data['gen']),
            'num_branches': len(self.case_data['branch']),
            'num_loads': np.sum(self.case_data['bus'][:, 2] > 0),  # Buses with Pd > 0
            'base_mva': self.case_data['baseMVA'],
            'total_generation_capacity_mw': np.sum(self.case_data['gen'][:, 8]),  # Sum of pmax
            'total_load_mw': np.sum(self.case_data['bus'][:, 2])  # Sum of Pd
        }


def parse_matpower_file(case_file: str) -> Dict:
    """
    Convenience function to parse MATPOWER file
    
    Args:
        case_file: Path to MATPOWER .m file
    
    Returns:
        Dictionary in PowerLASCOPF format
    """
    parser = MATPOWERParser(case_file)
    return parser.to_powerlascopf_json()


# Example usage and testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python matpower_parser.py <case_file.m>")
        sys.exit(1)
    
    case_file = sys.argv[1]
    
    try:
        parser = MATPOWERParser(case_file)
        
        print("=" * 60)
        print(f"Parsed: {case_file}")
        print("=" * 60)
        
        stats = parser.get_statistics()
        for key, value in stats.items():
            print(f"{key}: {value}")
        
        print("\n" + "=" * 60)
        print("PowerLASCOPF JSON Format:")
        print("=" * 60)
        
        import json
        json_data = parser.to_powerlascopf_json()
        print(json.dumps(json_data, indent=2))
        
    except Exception as e:
        print(f"Error parsing file: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)