"""Liquid-cooled, low-profile 48V/2V DCX research tradeoff screen.

This is conditional thermo-electric bounding-box arithmetic, NOT a verified
power-converter design, FEM, CFD, native PCB placement, or demonstrated result.
Locks the prior PCB/copper feasibility evidence to prevent silent drift.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PREV = ROOT/"hardware/dcx_main/g2/d1_lane_a_current_scaling_buried_winding_20261115_NOT_FOR_FAB.json"
OUT = ROOT/"hardware/dcx_main/g2/d1_lane_a_liquid_cooled_novelty_tradeoff_20261115_NOT_FOR_FAB.json"
PREV_CANON_SHA = "4b8d9ebc147a45e2b8f9005595774e192d79be26583e484875bf406f60367197"
CM3_PER_IN3 = 16.387064
INPUT_V = 48
OUTPUT_V = 2
COPPER_RHO20 = 1.724e-8
COPPER_ALPHA_PER_C = .00393
COPPER_REFERENCE_C = 100
THERMAL_DELTA_T_TARGET_K = 50.
WATER_RHO_KG_PER_L = 1.0
WATER_CP_J_KG_K = 4180.
PUMP_ASSUMED_EFFICIENCY = .25
FLOW_LPM = (.5, 1., 3.)
DELTA_P_KPA = (10.,20.,50.)
RESISTANCE_HOT_PAIR_MICROOHM = (10.,20.,30.,50.)
EFFICIENCY_HYPOTHESES = (.93,.95,.97)
# All dimensions below are unconstrained aspirational bounding boxes, *not* a
# manufactured layout. The cooling plate thickness includes structure but not
# the lateral connector/hoses/CDU. Power stage volume includes all essential
# power-conversion components (once actual CAD validates their placement).
OPTIONS = (
 dict(id="E200_copper_stack_cooling_coupon",current_a=200,cells=4,stage_xyz_mm=(24,20,5),coldplate_t_mm=2.5,
      reason="four 50-A local SR+embedded-winding cells: real coupon/assembly validation first"),
 dict(id="E400_functional_target",current_a=400,cells=8,stage_xyz_mm=(30,24,5.5),coldplate_t_mm=2.5,
      reason="8x50A integrated matrix with side SR and co-located positive/negative output collectors"),
 dict(id="E500_intermediate_stretch",current_a=500,cells=10,stage_xyz_mm=(30,25,5.5),coldplate_t_mm=2.5,
      reason="same selected module footprint as E600 but less demanding current/heat"),
 dict(id="E600_main_research",current_a=600,cells=12,stage_xyz_mm=(30,25,5.5),coldplate_t_mm=2.5,
      reason="12x50A hypothetically; balance, rectifier routing, terminals and ferrite may not fit"),
 dict(id="E800_ultrahigh_current_risk",current_a=800,cells=16,stage_xyz_mm=(36,30,6),coldplate_t_mm=3,
      reason="not a current record; 2026 48V/2V 800A published, our distinctive challenge must be thickness/cooled-density/efficiency"),
)
BENCHMARKS = (
 dict(name="IPEC 2026 48V to 2V 800A 4-module coupled ladder inductor",
      url="https://orbit.dtu.dk/en/publications/high-current-48-v-converter-with-integrated-coupled-inductors-for/",
      vin=48,vout=2,iout_a=800,full_load_efficiency=.898,
      published_density_w_in3=1570.4,
      density_boundary="paper abstract reports power density; verify actual boundary/module/cooling before apples-to-apples",
      distinction="already 800A; cannot claim current novelty at only 600A"),
 dict(name="Energies 2026 side-connected planar matrix",
      url="https://www.mdpi.com/1996-1073/19/9/2049",
      vin=60,vout=6,iout_a=140,full_load_efficiency=.975,
      published_density_w_in3=3066,
      density_boundary="60V/6V/140A prototype, forced-air; 48V/4.8V peak 98.8% is separate condition",
      distinction="side rectification and current-sharing are prior art"),
 dict(name="IEEE TPEL 2026 direct liquid cooling planar transformer",
      url="https://eurekamag.com/research/105/970/105970483.php",
      vin=None,vout=None,iout_a=None,full_load_efficiency=None,
      published_density_w_in3=None,
      density_boundary="cooling techniques and temperature reduction, not comparable 48V/2V full-module density",
      distinction="direct cooling of winding and cooling-enabled conductor already shown; novelty must go beyond it"),
 dict(name="IJHMT 2022 directly cooled planar transformer dielectric fluids",
      url="https://www.sciencedirect.com/science/article/pii/S0017931022002915",
      vin=None,vout=None,iout_a=None,full_load_efficiency=None,
      published_density_w_in3=None,
      density_boundary="0.4-4LPM cooling experiment, not a 48V/2V converter",
      distinction="liquid cooling of planar windings alone already tested"),
)

def canon_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()

def rho_hot(temp_c=COPPER_REFERENCE_C):
    return COPPER_RHO20*(1+COPPER_ALPHA_PER_C*(temp_c-20))

def copper_pair_example(current_a=600,each_rail_length_mm=5,
                        width_mm=20,thickness_mm=.8,temp_c=100):
    """Two rails of identical resistive straight copper, no contact/skin/pad losses."""
    Rone = rho_hot(temp_c)*(each_rail_length_mm*.001)/(width_mm*thickness_mm*1e-6)
    return {
      "current_a":current_a,
      "each_rail_length_mm":each_rail_length_mm,
      "each_rail_width_mm":width_mm,
      "each_rail_copper_thickness_mm":thickness_mm,
      "pair_copper_hot_R_microohm_DC_ideal":round(2*Rone*1e6,3),
      "pair_copper_hot_P_w_DC_ideal":round(current_a**2*2*Rone,3),
      "contact_via_spreading_and_AC_losses_included":False,
      "material_temperature_c_assumed":temp_c,
    }

def fluid(flow_lpm,pressure_kpa,loss_w):
    m_dot=flow_lpm*WATER_RHO_KG_PER_L/60.
    deltaT=loss_w/(m_dot*WATER_CP_J_KG_K)
    hydraulic_power=pressure_kpa*1000*flow_lpm/60000
    return {"flow_lpm":flow_lpm,"pressure_drop_kpa_assumed":pressure_kpa,
            "liquid_water_nominal_temp_rise_k":round(deltaT,3),
            "hydraulic_pumping_w":round(hydraulic_power,3),
            "external_pump_electric_w_at_25pct_assumed":round(hydraulic_power/PUMP_ASSUMED_EFFICIENCY,3),
            "water_cp_density_assumed_not_verified_for_actual_coolant":True,
            "fluid_bulk_rise_NOT_component_hotspot":True}

def option(o):
    i=o["current_a"]; p=OUTPUT_V*i
    x,y,h=o["stage_xyz_mm"];plate=o["coldplate_t_mm"]
    stage_cm3=x*y*h/1000.
    cooled_cm3=x*y*(h+plate)/1000.
    effs=[]
    for eta in EFFICIENCY_HYPOTHESES:
        loss=p*(1/eta-1)
        pump_flows=[fluid(q,20.,loss) for q in FLOW_LPM]
        effs.append({"hypothetical_electrical_full_load_efficiency":eta,
                     "conditional_electrical_loss_w":round(loss,3),
                     "conditional_total_heat_extraction_rtheta_50K_per_W_required_K_W":round(THERMAL_DELTA_T_TARGET_K/loss,3),
                     "coolant_bulk_and_pump_nominal_20kPa":pump_flows,
                     "efficiency_is_measured":False})
    return {
        "case_id":o["id"],
        "output_voltage_v":OUTPUT_V,
        "output_current_a":i,
        "output_power_w":p,
        "parallel_local_sr_winding_cells":o["cells"],
        "nominal_load_current_a_per_cell":round(i/o["cells"],2),
        "stage_bbox_xyz_mm_hypothetical":[x,y,h],
        "coldplate_t_mm_assumed":plate,
        "module_plus_coldplate_total_height_mm":round(h+plate,3),
        "module_only_bbox_cm3":round(stage_cm3,4),
        "coolplate_included_bbox_cm3":round(cooled_cm3,4),
        "conditional_module_only_density_w_in3":round(p*CM3_PER_IN3/stage_cm3,1),
        "conditional_coldplate_included_density_w_in3":round(p*CM3_PER_IN3/cooled_cm3,1),
        "current_density_a_per_footprint_mm2_conditional":round(i/(x*y),4),
        "output_pair_hot_resistance_scenarios":[
           dict(pair_resistance_microohm=r,
                pair_I2R_loss_w=round(i*i*r*1e-6,3),
                pair_DC_drop_mV=round(i*r*1e-3,3),
                this_is_total_of_both_polarities_with_contacts_idealized=True)
           for r in RESISTANCE_HOT_PAIR_MICROOHM],
        "efficiency_heat_cooling_scenarios":effs,
        "same_full_enclosure_contains_magnetics_drivers_sr_capacitors_terminals_validated":False,
        "coldplate_milled_sealed_corrosion_leak_manufacturer_qualified":False,
        "real_cfd_temperature_and_pressure_verified":False,
        "native_full_layered_pcb_geometry_completed":False,
        "continuous_output_current_measured":False,
        "model_only":True,
        "why_candidate":o["reason"]
    }

def evaluate():
    if canon_sha(PREV)!=PREV_CANON_SHA:
        raise ValueError("Source changed; do not silently reuse previous buried-winding feasibility")
    previous=json.loads(PREV.read_text("utf8"))
    if previous.get("status")!="RESEARCH_FEASIBILITY_SCREEN_NOT_FAB_NOT_PERFORMANCE":
        raise ValueError("Unexpected source analysis status")
    scenarios=[option(o) for o in OPTIONS]
    assert all(q["nominal_load_current_a_per_cell"]==50 for q in scenarios)
    result={
      "schema":"d1_coldplate_compatible_frontier_tradeoff/1",
      "status":"NOVELTY_AND_THERMAL_ENVELOPE_RESEARCH_ONLY_NO_FAB_OR_600A_PROOF",
      "source_sha256_canonical_lf":{str(PREV.relative_to(ROOT)).replace("\\","/"):PREV_CANON_SHA},
      "benchmark_evidence_not_comparable_without_matching_conditions":list(BENCHMARKS),
      "strategy":"higher continuous output current, thin electrical stack, detachable thin sealed coldplate and local coupled electromagnetics/thermal optimization",
      "system_spec":{"input_v":INPUT_V,"nominal_output_v":OUTPUT_V,"fixed_ratio_only_after_circuit_magnetics_validation":True,
                     "module_only_height_research_mm_max":5.5,
                     "total_module_plus_coldplate_height_target_mm_max":8.,
                     "official_3LPM_coldplate_interface_deferred_but_coldplate_thermal_contact_constraints_active":True,
                     "efficiency_design_preference":.95,"efficiency_research_floor_conditional":.93,
                     "do_not_remove_aux_driver_loss_from_eta":True,
                     "water_rho_kg_L_assumed":WATER_RHO_KG_PER_L,
                     "water_Cp_J_kg_K_assumed":WATER_CP_J_KG_K},
      "novelty_hypotheses_not_unpublished_claims":[
        dict(id="N1",
             hypothesis="At the same 48V/2V point and identical pump input and module footprint, thermal-aware PCB fractional winding/side SR layout may raise continuous thermally-safe current compared with conventional via-collected winding.",
             control="same GaN, SR, core material, electrical ratio, flow/pump/coolant, load, plate area and measurement",
             baseline="conventional internally paralleled planar secondary, vias collecting on surfaces, externally cooled",
             candidate="12-16layer copper winding with local side SR plus paired output collectors and thermally co-designed plate",
             primary_metric="maximum 30min continuous I at same max device/core temp and specified voltage/EMI",
             minimum_research_effect_pct_Icont_at_equal_hotspot=15,
             novelty_gate="must show statistically repeatable increase vs baseline with all devices in bounding box"),
        dict(id="N2",
             hypothesis="Co-optimizing winding copper, magnetic fringing regions and coolant impingement/hotspot paths may reduce layer-to-layer RMS-current imbalance, total AC winding loss and hotspot temp at identical net heat flux.",
             control="same magnetic core/current/frequency and coolant inlet temperature/flow/Δp",
             baseline="layout-only thermal plate under SR and transformer; no joint magnetics/cooling layout",
             candidate="sealed electrically insulated coldplate selectively below inner-copper exit/rectifier hot-spots",
             primary_metric="Rac/rdc, branch Irms spread, max hotspot at 600A, Δp and pump W",
             minimum_research_hotspot_reduction_kelvin_at_same_power_current_pump=10,
             novelty_gate="Maxwell losses -> CFD -> measured 3D thermal map cross-validated; no claim of first liquid-cooled transformer"),
        dict(id="N3",
             hypothesis="A co-designed short positive+negative output metal pair/side-plated terminal may improve *total* VOUT+PGND hot I2R compared with wide-DC PCB via-only routing at 400-600A.",
             control="same PCB stack copper, SRs, total current, terminal footprint and temperature",
             baseline="via-collected VOUT/PGND breakout",
             candidate="local rectification and adjacent wide/edge collector rails with short symmetric return",
             primary_metric="four-wire total hot VOUT+PGND microohm and I2R/area",
             research_target_real_hot_pair_with_terminals_microohm=20,
             novelty_gate="copper+contact+spreading/thermal real measurements not only ideal rho L/A"),
      ],
      "comparison_A_B_C_D_design_of_experiments":[
        {"group":"A","definition":"conventional planar matrix PCB secondary + vias + same attached coldplate",
         "variables":"reference core/cell-count/stackup/frequency/area"},
        {"group":"B","definition":"A + winding side-connected SR and short paired positive/negative collectors",
         "isolated_effect":"current redistribution and short-copper effect"},
        {"group":"C","definition":"B + thermal-targeted sealed channel pattern at identical pump power",
         "isolated_effect":"liquid path vs electrical placement co-optimization"},
        {"group":"D","definition":"C + jointly optimized winding copper layer order, MMF/AC loss and local coolant return route",
         "isolated_effect":"interaction, not just coldplate added to same design"},
      ],
      "initial_low_profile_geom_and_current_cases":scenarios,
      "pump_pressure_sensitivity_example_600A_95pct_efficiency":[fluid(q,dp,OUTPUT_V*600*(1/.95-1))
                                                               for q in (1.,3.) for dp in DELTA_P_KPA],
      "thermal_bulk_coolant_deltaT_not_sufficient":"Hotspot-to-liquid thermal resistance and flow maldistribution govern; bulk ΔT alone cannot prove safe cooling",
      "two_rail_hot_copper_dc_examples":[
          copper_pair_example(current_a=600,thickness_mm=t)
          for t in (.07,.30,.80,1.0)],
      "coolplate_cross_section_policy":{
         "power_stage_top_to_bottom":"GaN+SR and bottom-sourced heat, planar inner PCB winding, embedded/inserted ferrite legs, bonded heat spreader + dielectric TIM",
         "fluid_boundaries":"sealed passive copper/metal coldplate under electrical insulation; no conductive liquid exposed to energized copper",
         "edge_ports":"coolant fittings/manifold moved laterally/out of module footprint; INCLUDE active manifold volume separately when benchmarking complete assembly",
         "water_path_pressure_drop_cfd":False,
         "mechanical_full_8mm_height_verified":False,
         "leak_pressure_and_dielectric_test_done":False,
      },
      "go_no_go":[
         "G0 V17 native board: full 5 magnetics, SCH/ERC/D0 protection and limited energy startup must first pass",
         "E1 200A: source-locked 12-16layer copper matrix winding + side-SR + paired terminals; supplier stackup/cross section and Maxwell/thermal",
         "E2 400A: conditional >=95% full load and limited module+plate height <=8mm; baseline A vs B/C ablation, no false volume excludes",
         "E3 500-600A: >=93-95% conditional full load, stable 30min temperatures, cooling and 4-terminal loss; only after E2 protection",
         "DFM: supplier annular-ring plating, insulation, layered ferrite fit, cavity seal, galvanic corrosion/leak, coolant pressure",
         "Metrics: report W/in3 both power-only and plate-inclusive AND electric efficiency vs pump-inclusive efficiency separately",
      ],
      "engineering_state":{
         "new_physical_PCB_completed":False,
         "new_PCB_winding_Maxwell_completed":False,
         "microchannel_CFD_completed":False,
         "700_800A_claimed":False,
         "coolant_inlet_to_junction_Rtheta_measured":False,
         "research_not_fab":True
      }
    }
    return result

def main():
    parser=argparse.ArgumentParser()
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    args=parser.parse_args()
    data=evaluate()
    body=json.dumps(data,ensure_ascii=False,indent=2)+"\n"
    if args.write:
        OUT.write_text(body,encoding="utf8")
    elif OUT.read_text("utf8")!=body:
        raise ValueError("stale co-design screen")
    focus=[{"case":s["case_id"],"i_A":s["output_current_a"],
            "electrical_height_mm":s["stage_bbox_xyz_mm_hypothetical"][2],
            "total_height_with_plate_mm":s["module_plus_coldplate_total_height_mm"],
            "density_electrical_w_in3":s["conditional_module_only_density_w_in3"],
            "density_plate_included_w_in3":s["conditional_coldplate_included_density_w_in3"],
            "loss_95pct_w":s["efficiency_heat_cooling_scenarios"][1]["conditional_electrical_loss_w"]}
           for s in data["initial_low_profile_geom_and_current_cases"]]
    print(json.dumps({"status":data["status"],"cases":focus,
                      "copper_600A_5mm_20mm_hot_uohm":[p["pair_copper_hot_R_microohm_DC_ideal"] for p in data["two_rail_hot_copper_dc_examples"]]}))

if __name__=="__main__":
    try:main()
    except (ValueError,KeyError,OSError) as exc:
        print("COOLED FRONTIER GATE FAIL:",exc,file=sys.stderr)
        sys.exit(1)
