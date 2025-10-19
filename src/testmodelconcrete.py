# set working directory
import os
os.chdir("/Users/cwayner/Documents/Senior Thesis/Model Inputs/test")

# install package in terminal using pip3 install <package_name> -t <project_path>
from pyomo.environ import *

# Create data import structure
data = DataPortal()

# Load indices that require CSVs
data.load(filename='fips_test.csv', set='SourceCounty')  # i
data.load(filename='fips_test.csv', set='ProdCounty')  # j
data.load(filename='ResourcesDelim_test.csv', set='Biomass')  # a

# load in parameter CSVs
data.load(filename="BTcostdelimtest.csv", param='FP')
data.load(filename="county_distances_test.csv", param='TD')
data.load(filename="county_basin_distances_test.csv", param='CD')
data.load(filename="CO2transportprice.csv", param='CTP')
data.load(filename="NZA_Basin_Seq_Cost_test.csv", param='CIP')
data.load(filename="EER_bioenergy_generation_core_2040_test.csv", param='EERP')
data.load(filename="BTproddelimtest.csv", param='BP')
data.load(filename="NZA_Basin_Seq_Capacity_test.csv", param='SCAP')
data.load(filename="county_to_EER_test.csv", param='QIJ')
data.load(filename="Biomass_to_Energy_by_EER_tech.csv", param='BC')
data.load(filename="Bioenergy_to_CO2_by_EER_tech.csv", param='PC')


# initialize model
model = ConcreteModel()

# initialize all indices
model.SourceCounty = Set(initialize=data['SourceCounty'])
model.ProdCounty = Set(initialize=data['ProdCounty'])
model.Biomass = Set(initialize=data['Biomass'])
model.Year = Set(initialize=[2022, 2024, 2026, 2028, 2030, 2032, 2035, 2040])  # year
model.EERregion = Set(initialize=['texas agg.'])  # EER zone
model.Tech = Set(initialize=["bio-gasification fischer-tropsch w/cc", "bio-gasification h2 w/cc", "biomass fast pyrolysis", "biomass fast pyrolysis w/cc"])  # type of technology
model.Basin = Set(initialize=["West Texas", "Gulf Coast", "Lower Midwest"])  # basins

# initialize parameters
model.FP = Param(model.Biomass, model.SourceCounty, model.Year, initialize=data['FP'], default=1000)  # feedstock price ($/ton) indexed by type of feedstock
model.TP = Param(initialize=0.163)  # transport price in $/ton-mi
model.TD = Param(model.SourceCounty, model.ProdCounty, initialize=data['TD'], default=1000)  # transport distance (mi) indexed by feedstock source and sink counties
model.CD = Param(model.ProdCounty, model.Basin, initialize=data['CD'], default=1000)  # CO2 transport distance (mi??) indexed by feedstock sink county and basin
model.CTP = Param(model.Year, initialize=data['CTP'])  # CO2 transport price ($/mi), indexed by year
model.CIP = Param(model.Basin, initialize=data['CIP'])  # CO2 injection price ($/ton), indexed by basin
model.EERP = Param(model.Tech, model.EERregion, model.Year, initialize=data['EERP'])  # EER energy prod (GWh) indexed by production facility, EER region, year
model.BP = Param(model.Biomass, model.SourceCounty, model.Year, initialize=data['BP'], default=0)  # total biomass potential (ton) indexed by type of resource, county, year
model.SCAP = Param(model.Basin, initialize=data['SCAP'])  # CO2 injection capacity (ton) indexed by basin
model.PCAP = Param(initialize=1000000)  # CO2 pipeline capacity placeholder
model.QIJ = Param(model.SourceCounty, initialize=data['QIJ'])  # converts county FIPS code (i or j) to EER region q
model.BC = Param(model.Tech, initialize=data['BC'])  # specifies how much biomass is consumed per GWh of energy production
model.PC = Param(model.Tech,initialize=data['PC'])  # specifies how much CO2 is produced per GWh of energy production

# create decision variables (known as Var in Pyomo)
model.x = Var(model.Biomass, model.SourceCounty, model.ProdCounty, model.Year, domain=PositiveReals)  # feedstock production indexed by feedstock, source county, year
model.y = Var(model.Tech, model.ProdCounty, model.Basin, model.Year, domain=PositiveReals)  # CO2 transport amount indexed by prod facility, CO2 source county, basin, year
model.z = Var(model.Basin, model.Year, domain=PositiveReals)  # CO2 injection amount indexed by basin and year
model.u = Var(model.Tech, model.ProdCounty, model.Year, domain=PositiveReals)  # conversion tech energy production in GWh, indexed by prod facility, CO2 source county, year


# create objective function
# define function
def obj_rule(model):
    expr = sum(model.FP[a, i, t] * model.x[a, i, j, t] for a in model.Biomass
               for i in model.SourceCounty for j in model.ProdCounty for t in model.Year)  # feedstock production cost
    expr += sum(model.TP * model.TD[i, j] * model.x[a, i, j, t] for i in model.SourceCounty for j in model.ProdCounty
                for a in model.Biomass for t in model.Year)  # transport cost feedstock to production facility
    expr += sum(model.CD[j, b] * model.y[p, j, b, t] * model.CTP[t] for j in model.ProdCounty for b in model.Basin
                for p in model.Tech for t in model.Year)  # CO2 transport cost from production facility to basin
    expr += sum(model.z[b, t] * model.CIP[b] for b in model.Basin for t in model.Year)  # CO2 injection cost
    return expr


# add as Objective in Pyomo (default is to minimize)
model.f = Objective(rule=obj_rule)


# add constraints


# First constraint: EER energy production in GWh equals conversion tech energy capacity.
# Requires the creation of a parameter (QIJ) that maps sink county j to EER region q
def energy_prod_rule(model, proc, q, time):
    subset = {(p, j, year) for p in model.Tech for j in model.ProdCounty for year in model.Year
              if model.QIJ[j] == q and p == proc and year == time}
    return sum(model.u[m] for m in subset) == model.EERP[proc, q, time]


model.energy_prod = Constraint(model.Tech, model.EERregion, model.Year, rule=energy_prod_rule)


# Second constraint: total feedstock production equals total feedstock consumed
# Sums over county and type of feedstock/type of production facility (increments by year)
# Multiplies by conversion factor (BC) to turn energy production (u) into biomass consumption
def feedstock_cons_rule(model, j, year):
    return sum(model.x[a, i, j, year] for a in model.Biomass for i in model.SourceCounty) == \
           sum((model.BC[p] * model.u[p, j, year]) for p in model.Tech)


model.feedstock_cons = Constraint(model.ProdCounty, model.Year, rule=feedstock_cons_rule)


# Third constraint: amount of feedstock produced less than biomass potential (BP)
def feedstock_total_rule(model, feed, county, year):
    return sum(model.x[feed, county, j, year] for j in model.ProdCounty) <= model.BP[feed, county, year]


model.feedstock_total = Constraint(model.Biomass, model.SourceCounty, model.Year, rule=feedstock_total_rule)


# Fourth constraint: amount of CO2 injected must be less than basin capacity (SCAP)
def basin_cap_rule(model, b):
    return sum(model.z[b, year] for year in model.Year) <= model.SCAP[b]


model.basin_cap = Constraint(model.Basin, rule=basin_cap_rule)


# Fifth constraint: amount of CO2 transported must be less than pipeline capacity (PCAP)
def pipe_cap_rule(model, j, b, year):
    return sum(model.y[p, j, b, year] for p in model.Tech) <= model.PCAP


model.pipe_cap = Constraint(model.ProdCounty, model.Basin, model.Year, rule=pipe_cap_rule)


# Sixth constraint: amount of CO2 transported must be equal to amount from generation sources
# Multiplies by conversion factor (PC) to turn energy production (u) into tons of CO2
def gen_pipe_rule(model, p, j, year):
    return sum(model.y[p, j, b, year] for b in model.Basin) == (model.u[p, j, year] * model.PC[p])


model.gen_pipe = Constraint(model.Tech, model.ProdCounty, model.Year, rule=gen_pipe_rule)


# Seventh constraint: amount of CO2 transported to each basin must be equal to amount sequestered
def pipe_basin_rule(model, b, year):
    return sum(model.y[p, j, b, year] for p in model.Tech for j in model.ProdCounty) == model.z[b, year]


model.pipe_basin = Constraint(model.Basin, model.Year, rule=pipe_basin_rule)

# initialize data instance
solver = SolverFactory('glpk')
solver.solve(model)

# export results!

# production (x)
with open('results_biomass.csv', 'w') as f:
    f.write('Resource, County, Year, Production\n')
    for feed in model.Biomass:
        for county in model.SourceCounty:
            for county2 in model.ProdCounty:
                for year in model.Year:
                    f.write('"{}","{}","{}", "{}", {} \n'.format(feed, county, county2, year, model.x[feed, county, county2, year].value))

# energy (u)
with open('results_energy.csv', 'w') as f:
    f.write('Tech, County, Year, Energy\n')
    for tech in model.Tech:
        for county in model.ProdCounty:
            for year in model.Year:
                f.write('"{}","{}","{}", {} \n'.format(tech, county, year, model.u[tech, county, year].value))

# CO2 transport (j)
with open('results_CO2trans.csv', 'w') as f:
    f.write('Tech, County, Basin, Year, Amount\n')
    for tech in model.Tech:
        for county in model.ProdCounty:
            for basin in model.Basin:
                for year in model.Year:
                    f.write('"{}","{}","{}", {}, {} \n'.format(tech, county, basin, year, model.y[tech, county, basin,
                                                                                                  year].value))
# CO2 sequestration (z)
with open('results_CO2seq.csv', 'w') as f:
    f.write('Basin, Year, Amount\n')
    for basin in model.Basin:
        for year in model.Year:
            f.write('"{}",{},{} \n'.format(basin, year, model.z[basin, year].value))

