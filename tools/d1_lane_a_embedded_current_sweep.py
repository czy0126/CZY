"""D1 embedded PCB windings + output-current scaling feasibility, source-locked.

All electrical loss/thermal results are conditional algebra, not LTspice,
Maxwell, prototype heat or manufacturability verification. Actual existing
ELP38 Lr DFM coupon evidence is read from repository by pinned LF SHA.
Never use these hypothetical geometry/efficiency points as achieved power.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"hardware/dcx_main/g2/d1_lane_a_current_scaling_buried_winding_20261115_NOT_FOR_FAB.json"
LRSRC=ROOT/"hardware/dcx_main/pcb_winding/ELP38_Lr_3turn_PCB_embedded_DFM_via_screen_NOT_FOR_FAB.json"
MAGSRC=ROOT/"design/v3/maxwell/pcb_embedded_lr_3turn_candidate.json"
FRONTIER=ROOT/"hardware/dcx_main/g2/d1_lane_a_frontier_feasibility_20261115_NOT_FOR_FAB.json"
FROZEN_SHA={
    LRSRC:"5e48fced49c02db78fb65b21b6378bfbcdfa5363ae26298fb7d5b70ce0c2865b",
    MAGSRC:"434018e533924780801ce91b6adc6ccaf92a0a1f82549e1d73a627d8a72311f0",
    FRONTIER:"afae3cd7906189e46c3fc33a06bfe5aebda6e5c58f192a22ac4b09e868682cdd",
}
W_IN3_FACTOR=16.387064 # 1in³ = 16.387064 cm³
COPPER_RHO20=1.724e-8
COPPER_ALPHA=0.00393
MU0=4*math.pi*1e-7
VOUT_V=2
VIN_V=48
TARGET_DENSITY=4000
TMAX_ALLOWED_DELTA_C=50.0 # thermal design assumption
CANDIDATES=[
    {"iout_a":100,"cells":2,"example_mm":(20,18,4.2),"note":"electrical G0 platform only, do not adopt volume as achieved"},
    {"iout_a":150,"cells":3,"example_mm":(18,16,4.2),"note":"prior very aggressive 300W envelope, likely ferrite/driver/terminal DFM blocked"},
    {"iout_a":200,"cells":4,"example_mm":(24,17,4.0),"note":"200A midstage, 4mm complete-assembly constraint not physically proven"},
    {"iout_a":300,"cells":6,"example_mm":(30,20,4.0),"note":"recommended first frontier architecture candidate: 6x50A low-voltage secondary cells"},
    {"iout_a":400,"cells":8,"example_mm":(32,25,4.0),"note":"second-stage high-current scaling: 8x50A, higher heat/current-sharing burden"},
    {"iout_a":500,"cells":10,"example_mm":(36,28,4.0),"note":"high-risk extrapolation only; not a rated semiconductor/magnetic configuration"},
]
# These are assumed *whole module boxes* rather than CAD achievements.
# Example package heights 4.0-4.2 are pressure-test requirements; 6mm
# mechanical escape route should not be confused with achieving 4000W/in3.
LEGACY_PAIR_R_MICROOHM=50.0
RESEARCH_PAIR_R_MICROOHM=20.0
# one ideal 1.6 mm PTH at 100 C / 25um plating; no current crowding or
# pad/busbar/thermal effects. A 300A full-stack via choke isn't acceptable.
PCB_TRANSFER_BUDGET_MICROOHM=20.0

STUDIES=[
    dict(year=2024,doi="10.1109/OJPEL.2024.3490601",
         url="https://ieeexplore.ieee.org/document/10741344/",
         vin_v=40,vout_v=1,current_a=200,power_w=200,density_w_in3=1394,
         full_load_efficiency=None,peak_efficiency=0.97,
         board_layers=6,method="1/10 fractional-turn 6-layer planar winding, SR/caps co-packaged",
         evidence_class="measured prototype; 97% peak not full-load"),
    dict(year=2024,doi="10.1109/TIE.2023.3310020",
         url="https://ieeexplore.ieee.org/document/10246797/",
         vin_v=48,vout_v=1.8,current_a=120,power_w=216,density_w_in3=1037,
         full_load_efficiency=None,peak_efficiency=0.931,board_layers=None,
         method="integrated transformer/inductor with buried vias",
         evidence_class="120A continuous measured; 300A peak is pulsed for 2ms"),
    dict(year=2026,doi="10.1109/TPEL.2026.3695451",
         url="https://portalcientifico.upm.es/en/ipublic/item/10546947",
         vin_v=48,vout_v=1,current_a=2200,power_w=2200,density_w_in3=1365,
         full_load_efficiency=None,peak_efficiency=0.936,board_layers=None,
         method="four series-input parallel-output modules, 5mm 3oz multilayer segmented matrix winding",
         evidence_class="up to 2200A; >90% range 200-2000A; reported density uses segmented transformer area"),
    dict(year=2026,doi="10.3390/en19092049",
         url="https://www.mdpi.com/1996-1073/19/9/2049",
         vin_v=60,vout_v=6,current_a=140,power_w=840,density_w_in3=3066,
         full_load_efficiency=.975,peak_efficiency=.988,board_layers=36,
         method="PCB inner windings + external core, lateral side-connected SR and copper-plated output terminations",
         evidence_class="3066 W/in3 full load at 60V/6V/140A; 98.8% peak at 48V/4.8V/50A is different point; Tmax 105 C"),
    dict(year=2026,doi="10.1109/APEC51134.2026.11516705",
         url="https://doi.org/10.1109/APEC51134.2026.11516705",
         vin_v=48,vout_v=1.1,current_a=300,power_w=330,density_w_in3=None,
         full_load_efficiency=.8504,peak_efficiency=.903,board_layers=None,
         method="merged Buck-Boost LLC, 2.8mm thick and split multi-cell matrix",
         evidence_class="300A 48V/1.1V full-load 85.04%, not a 2V efficiency projection"),
    dict(year=2025,doi="10.1109/TIE.2025.3577302",
         url="https://xplorestaging.ieee.org/document/11077445",
         vin_v=24,vout_v=16,current_a=.2,power_w=3.2,density_w_in3=None,
         full_load_efficiency=None,peak_efficiency=.872,board_layers=None,
         method="magnetic ferrite core itself embedded in a PCB, unlike normal buried copper winding",
         evidence_class="3.2W low-power flyback demonstration; cannot extrapolate to 600W without FEA/DFM"),
    dict(year=2025,doi=None,
         url="https://www.vicorpower.com/resource-library/case-studies/aerospace-and-defense/eo-ir-airborne-infrared-countermeasures",
         vin_v=None,vout_v=2,current_a=130,power_w=None,density_w_in3=None,
         full_load_efficiency=None,peak_efficiency=.97,board_layers=None,
         method="isolated VTM fixed-ratio VTM current multiplier commercial alternative",
         evidence_class="up to 130A and 97% peak, not a known 48:2 rated point; don't claim matched comparison"),
]

def canon_sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()

def thermal_budget(power_w,eff):
    loss=power_w*(1/eff-1)
    return dict(efficiency=eff,
                conditional_total_loss_w=round(loss,3),
                delta_temperature_assumed_c=TMAX_ALLOWED_DELTA_C,
                required_best_case_lumped_rtheta_c_per_w=round(TMAX_ALLOWED_DELTA_C/loss,3),
                note="lumped 50 C rise/total loss is a heat-extraction target, not hotspot junction-to-coolant proof")

def envelope(c:dict):
    current=c["iout_a"];power=VOUT_V*current
    x,y,z=c["example_mm"]
    v_mm3=x*y*z
    vol=v_mm3/1000
    density=power/vol*W_IN3_FACTOR
    maxvol=power*W_IN3_FACTOR/TARGET_DENSITY
    m={"Iout_a":current,"Pout_w":power,"cells":c["cells"],
       "secondary_cell_target_avg_a":round(current/c["cells"],2),
       "native_dcx_24to1_dc_ratio_unverified":True,
       "hypothetical_whole_module_xyz_mm":[x,y,z],
       "hypothetical_envelope_cm3":round(vol,4),
       "conditional_density_w_in3":round(density,1),
       "alternative_5_6_8mm_research_envelopes":alternate_packaging_options(current),
       "design_target_w_in3":TARGET_DENSITY,
       "maximum_complete_volume_for_4000_w_in3_cm3":round(maxvol,4),
       "hypothetical_rectangle_meets_density_arithmetic":density>=TARGET_DENSITY,
       "component_packability_confirmed":False,
       "magnetic_window_and_real_turn_ratio_confirmed":False,
       "pcb_ferrite_pcb_assembly_height_verified":False,
       "coldplate_continuous_heat_path_verified":False,
       "copper_output_pair_budget":[
            {"pair_hot_resistance_microohm":r,
             "conditional_loop_loss_w":round(current**2*r*1e-6,3),
             "conditional_loop_voltage_drop_mv":round(current*r*1e-3,3)}
            for r in (LEGACY_PAIR_R_MICROOHM,RESEARCH_PAIR_R_MICROOHM)],
       "full_load_loss_scenarios":[thermal_budget(power,e) for e in (.95,.97,.98)],
       "status":"GEOMETRIC_AND_DC_HEAT_BUDGET_ONLY_NOT_VERIFIED",
       "note":c["note"]}
    return m

def alternate_packaging_options(i_a):
    """Whole-module bounding-box alternatives: tall shapes reduce winding stack constraints but need smaller X/Y."""
    examples={200:[(22,15,5),(20,16,5)],300:[(24,17,6),(20,20,6)],400:[(26,20,6),(23,23,6)],500:[(23,22,8),(22,23,8)]}
    out=[]
    for x,y,z in examples.get(i_a,[]):
        vol=x*y*z/1000
        den=2*i_a/vol*W_IN3_FACTOR
        out.append({"bounding_mm":[x,y,z],"volume_cm3":round(vol,4),
                    "conditional_density_w_in3":round(den,1),
                    "mathematically_ge_4000":den>=4000,
                    "actual_pcb_placement_or_ferrite_fit_verified":False})
    return out

def stackup_geometry_lower_bounds():
    """Illustrative geometric copper+dielectric minimum, NOT a maker-qualified stackup."""
    cases=[]
    for layer_count in (12,16,24,36):
        copper_um=70
        between_um=80
        thickness_mm=(layer_count*copper_um+(layer_count-1)*between_um)/1000
        cases.append({
            "copper_layers":layer_count,
            "assumed_each_copper_um":copper_um,
            "assumed_each_dielectric_between_layers_um":between_um,
            "minimum_theoretical_board_build_mm":round(thickness_mm,3),
            "fits_inside_entire_4mm_box_alone":thickness_mm<=4.0,
            "remaining_height_if_4mm_box_before_core_components_solder_mm":round(4-thickness_mm,3),
            "real_mfr_stackup_verified":False
        })
    return cases

def via_model(lr:dict,mag:dict):
    rows=lr["via_plating_sensitivity"]
    r25=next(x for x in rows if x["trial_barrel_thickness_um"]==25)
    one_r=r25["via_R_100C_ohm_DC_ideal"]
    minimum=math.ceil(one_r/(PCB_TRANSFER_BUDGET_MICROOHM*1e-6))
    # output 300 A via-only topology is DFM anti-pattern; a copper-plated
    # side termination/multilayer collector avoids single via chokepoint.
    return {
      "original_embedded_Lr_rms_at_100A_output_a":lr["Lr_rms_at_100A_output_A"],
      "original_embedded_Lr_transient_peak_a":lr["highest_existing_Lr_transient_peak_A"],
      "original_board_thickness_mm":lr["barrel_length_mm"],
      "original_candidate_6_layers_turn_w_mm":round(mag["board"]["trace_width_mm"],3),
      "original_candidate_each_copper_um":round(mag["board"]["copper_thickness_per_layer_mm"]*1000,1),
      "assumed_via_finished_drill_mm":lr["barrel_assumed_finished_drill_mm"],
      "assumed_barrel_plating_um":25,
      "single_ideal_100c_via_dc_resistance_milliohm":round(one_r*1e3,4),
      "single_ideal_100c_via_copper_area_mm2":r25["copper_barrel_annulus_area_mm2"],
      "minimum_parallel_ideal_vias_for_one_20_microohm_interlayer_transition":minimum,
      "for_300a_ideal_copper_barrel_only_rms_current_a_per_via":round(300/minimum,2),
      "net_reality":"This minimum consumes the ENTIRE allowed 20 microohm output loop budget in one step; real needed count is larger because landing/pad spreading, nonuniform current, plating and thermal effects are not included.",
      "actual_300a_via_transition_qualified":False,
      "mitigation":"Avoid full 300A through a small PTH bank; integrate inner secondary copper to adjacent side metallization/output positive+negative collectors and parallel independent 50A rectifier cells",
    }

def evaluate():
    for f,h in FROZEN_SHA.items():
        if canon_sha(f)!=h:
            raise ValueError(f"frozen source drift: {f.relative_to(ROOT)}")
    l=json.loads(LRSRC.read_text("utf8"))
    mag=json.loads(MAGSRC.read_text("utf8"))
    prior=json.loads(FRONTIER.read_text("utf8"))
    if l["status"]!="DFM_AND_100C_VIA_RESISTANCE_TRIAL_NOT_FOR_FAB":
        raise ValueError("wrong embedded-Lr DFM source")
    if mag["board"]["layers"]!=["F.Cu","In1.Cu","In2.Cu","In3.Cu","In4.Cu","B.Cu"]:
        raise ValueError("embedded Lr witness changed")
    if prior["source_pcb_sha256"]!="85fff295c2c8bd594266881b711584be02b40b2158e266e8df4a2ba77d6bb76c":
        raise ValueError("V17 base not matching frontier source")
    rows=[envelope(x) for x in CANDIDATES]
    for row in rows:
        assert row["secondary_cell_target_avg_a"]==50
        assert not row["component_packability_confirmed"]
    skin={f"{f_khz}kHz":round(math.sqrt(2*COPPER_RHO20/(2*math.pi*f_khz*1000*MU0))*1e6,1)
          for f_khz in (200,500,1000)}
    return {
       "schema":"d1_embedded_winding_current_scaling/1",
       "theoretical_unqualified_stackup_geometry_bounds":stackup_geometry_lower_bounds(),
       "status":"RESEARCH_FEASIBILITY_SCREEN_NOT_FAB_NOT_PERFORMANCE",
       "source_canonical_lf_sha256":{str(p.relative_to(ROOT)).replace("\\","/"):h for p,h in FROZEN_SHA.items()},
       "target_input_v":VIN_V,"target_nominal_output_v":VOUT_V,
       "current_points_100_to_500A":rows,
       "design_target_w_in3":TARGET_DENSITY,
       "volume_is_inclusive_of_all_mandatory_devices_magnetics_control_drivers_capacitors_terminals":"required for any claimed output, not verified in these bounding boxes",
       "copper_skin_depth_20c_um":skin,
       "buried_winding_proof_existing_Lr_only":via_model(l,mag),
       "winding_embedded_in_pcb_feasibility":{
          "type":"LITHOGRAPHIC_COPPER_ON_MULTILAYER_INTERNAL_LAYERS",
          "evidence":"existing 6-layer 3-turn ELP38 Lr KiCad coupon plus multiple 48V high-current peer-reviewed prototype papers",
          "status":"STRONGLY_SUPPORTED_FOR_COPPER_WINDING_NOT_CURRENT_300A_OUTPUT_BRIDGE",
          "factory_layer_count_and_copper_thickness_verified":False,
          "manufacturer_core_slot_and_dielectric_verified":False,
          "winding_matrix_fem_300a_validated":False,
       },
       "ferrite_core_completely_embedded_inside_laminate":{
          "status":"HIGH_RISK_UNPROVEN_AT_48V_2V_600W",
          "evidence":"2025 3.2W 24V/16V full-embedded core flyback paper is NOT 48V/2V high current evidence",
          "recommendation":"prefer multilayer copper windings with external low-profile ferrite inserted into milled core windows/slots or clamped to PCB",
       },
       "technical_options":[
           {"id":"A","description":"12-16 layer planar copper windings, external slotted low-profile ferrite, 4-6 lateral 50A SR cells",
            "recommended_role":"200A/2V first functional high-density magnetics coupon",
            "risk":"moderate/high","G0_gate":"real 24:1 functional netlist with CT and Lr route + OEM stackup"},
           {"id":"B","description":"24-36 layer single-core matrix with side-connected SR/copper-plated terminations, 6-8x50A cells",
            "recommended_role":"300A primary research/400A stretch after A validated",
            "risk":"high","G0_gate":"actual fab process and solderable side-pad pattern; Maxwell AC loss/thermal/imbalance proof"},
           {"id":"C","description":"multilayer PCB with ferrite core fully buried inside laminate",
            "recommended_role":"later independent low-power coupon only",
            "risk":"very high","G0_gate":"supplier process + dielectric/heat/stress + measured ferrite BH and gap proof"},
       ],
       "published_sources_operating_points_not_equivalent":STUDIES,
       "research_requirements":{
           "effective_24_1_ratio":"verify primary half/full bridge factor, series-input/parallel-secondary turns and rectifier actual topology; do not multiply nominal coil turns as ratios",
           "primary_ZVS":"measure at minimum/maximum input and partial/full load, not only f=fr",
           "secondary_current_balance":"measure per leg and per copper layer, not just total output current",
           "magnetics":"extract full winding L matrix, Bpeak, proximity AC copper loss, ferrite temp material BH, gap fringe, Maxwell mesh convergence",
           "pcb_routing":"physical via barrel DFM, return plane proximity, Kelvin Vgs, output positive and negative collectors together",
           "protection":"D0 default OFF / UVLO / OC / softstart verified before power-on",
           "heat":"separate junction-hotspot vs total lumped thermal budget; cooling geometry may be designed now but manufacturing 3 LPM deferred",
           "factory":"laminate thickness, 70um actual inner copper, insulation, via fill/plate/microsection, edge castellations, mechanical ferrite fit",
           "efficiency":"report full-load efficiency at 48V->2V incl driver/aux and thermal stabilized waveforms",
       },
       "manufacturable_pcb_finished":False,
       "full_fem_done_for_this_200_300_400A_architecture":False,
       "prototype_efficiency_or_density_measured":False,
    }

def main(argv=None):
    ap=argparse.ArgumentParser()
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    args=ap.parse_args(argv)
    data=evaluate()
    body=json.dumps(data,indent=2,ensure_ascii=False)+"\n"
    if args.write:
        DATA.write_text(body,encoding="utf8")
    elif DATA.read_text("utf8")!=body:
        raise ValueError("current scaling sweep report stale")
    report=[dict(current_a=r["Iout_a"],vol_cm3=r["hypothetical_envelope_cm3"],density_w_in3=r["conditional_density_w_in3"],
                 loss_w_97pct=r["full_load_loss_scenarios"][1]["conditional_total_loss_w"]) for r in data["current_points_100_to_500A"]]
    print(json.dumps({"status":data["status"],"candidates":report,
                      "min_ideal_25um_PTH_vias_full_20uohm":data["buried_winding_proof_existing_Lr_only"]["minimum_parallel_ideal_vias_for_one_20_microohm_interlayer_transition"]}))
if __name__=="__main__":
    try:main()
    except (KeyError,ValueError,OSError) as e:
        print(f"RESEARCH GATE FAILED: {e}",file=sys.stderr)
        sys.exit(1)
