"""Reproducible V17 hardware-to-frontier-density feasibility audit.

KiCad native physical sizes and connections are read from the frozen PCB.
A target W/in3 is a research hurdle, never an achieved electrical result.
Use KiCad 10 python for --write/--check; source SHA changes fail closed.
"""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import sys
import pcbnew as k

ROOT = Path(__file__).resolve().parents[1]
BOARD_REL = "hardware/dcx_main/g2/d1_lane_a_connectivity/six_net_trial_04_NOT_FOR_FAB.kicad_pcb"
OUT_REL = "hardware/dcx_main/g2/d1_lane_a_frontier_feasibility_20261115_NOT_FOR_FAB.json"
PCB_SHA = "85fff295c2c8bd594266881b711584be02b40b2158e266e8df4a2ba77d6bb76c"
CIN_V = 48.0
VOUT_V = 2.0
I_OUT_A = 100.0
HEIGHT_RESEARCH_MM = 4.0
HEIGHT_LEGACY_MM = 16.0
T530_OEM_B_COURTYARD_MM = (9.12, 5.10)
T530_BODY_SEATED_HEIGHT_MAX_MM = 4.3  # official KEMET 470uF X 7343 package
T530_CAPACITANCE_UF = 470.0  # T530X477M006ATE004 official part
T530_EXPECTED_VALUE = 'T530X477M006ATE004'
W_PER_IN3_PER_W_PER_CM3 = 16.387064
FOCUS_DENSITY = 4000.0
BROADER_STRETCH_DENSITY = 6500.0
FRONTIER = [
  dict(name="48V/1.8V integrated magnetic converter, IEEE TIE 2024",
       density_w_in3=1037.0, voltage_output_v=1.8, note="120A continuous; 93.1% peak efficiency",doi="10.1109/TIE.2023.3310020"),
  dict(name="48V/1.8V matrix LLC bus converter APEC 2024",
       density_w_in3=2400.0, voltage_output_v=1.8, note="840W design, estimated/projected density; NOT a directly comparable fully measured efficiency point",doi="10.1109/APEC48139.2024.10509453"),
  dict(name="48V/1V 405A GaN SBC, APEC 2025",
       density_w_in3=3048.0, voltage_output_v=1.0, note="measured 405A; different output voltage and topology",doi="10.1109/APEC48143.2025.10977131"),
  dict(name="10:1 LLC DCX CPSS TPEA 2026",
       density_w_in3=3548.0, voltage_output_v=6.0, note="density measured/reported at 60V in, 10:1 =6V out; at 48V 85A and 98.8% peak efficiency are separate operating points",doi="10.24295/CPSSTPEA.2026.00024"),
  dict(name="48V/12V 10MHz autotransformer DCX APEC 2026",
       density_w_in3=6100.0, voltage_output_v=12.0, note="436W 48/12V; not a 24:1 converter; 94.2% peak efficiency",doi="10.1109/APEC51134.2026.11517110"),
]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def rounded(x,places=4):
    return round(x,places)

def density_to_geometry(watts,density,height_mm):
    volume_cm3 = watts*W_PER_IN3_PER_W_PER_CM3/density
    area_mm2 = volume_cm3*1000/height_mm
    return {"density_w_in3": density,"density_w_cm3":rounded(density/W_PER_IN3_PER_W_PER_CM3,3),
            "max_module_volume_cm3":rounded(volume_cm3,4),
            "height_assumed_mm":height_mm,
            "max_footprint_area_mm2":rounded(area_mm2,3),
            "square_equivalent_edge_mm":rounded(math.sqrt(area_mm2),3)}

def calculate():
    file = ROOT/BOARD_REL
    if sha(file)!=PCB_SHA:
        raise ValueError("Frozen physical V17 PCB SHA changed: revalidate this analysis")
    b=k.LoadBoard(str(file))
    f={o.GetReference():o for o in b.GetFootprints()}
    if len(f)!=149 or b.GetCopperLayerCount()!=12:
        raise ValueError("PCB footprint/copper-layer integrity drift")
    missing=[q for q in ("CT","T1","T2","T3","T4") if q not in f]
    if len(missing)!=5:
        raise ValueError("Missing magnetics updated, evaluate new final PCB")
    t530=[q for q in f if q.startswith("CHB")]
    if len(t530)!=72:
        raise ValueError("Unexpected OEM T530 BOM count")
    if any(f[ref].GetValue()!=T530_EXPECTED_VALUE for ref in t530):
        raise ValueError("One or more product T530 footprints changed")
    outlines=[]
    for sh in b.GetDrawings():
        if sh.GetLayer()!=k.Edge_Cuts:continue
        box=sh.GetBoundingBox()
        x,y=k.ToMM(box.GetWidth()),k.ToMM(box.GetHeight())
        if x>100 and y>100:outlines.append((x,y))
    if len(outlines)!=1:raise ValueError("Outer-board outline not unique")
    width,height=outlines[0]
    area=width*height
    p_out=VOUT_V*I_OUT_A
    cap_area=len(t530)*math.prod(T530_OEM_B_COURTYARD_MM)
    nets=collections.defaultdict(lambda:{"pad_count":0,"track_length_mm":0.0,"via_count":0,"track_count":0})
    for o in b.GetFootprints():
        for q in o.Pads():
            if q.GetNetname():nets[q.GetNetname()]["pad_count"]+=1
    for tr in b.GetTracks():
        n=tr.GetNetname()
        if isinstance(tr,k.PCB_VIA):
            nets[n]["via_count"]+=1
        elif isinstance(tr,k.PCB_TRACK):
            s,e=tr.GetStart(),tr.GetEnd()
            nets[n]["track_length_mm"]+=math.hypot(k.ToMM(s.x-e.x),k.ToMM(s.y-e.y))
            nets[n]["track_count"]+=1
    selected=("VIN_P","SW","CR_CT","CT_LR","PRI_T1","VOUT","PGND","GH","GH_DRV","OC")
    required_unmodeled=[n for n in ("CR_CT","CT_LR","PRI_T1")
                        if nets[n]["pad_count"]==1 and nets[n]["track_count"]==0]
    if set(required_unmodeled)!={"CR_CT","CT_LR","PRI_T1"}:
        raise ValueError("Frozen missing-magnetic copper status has changed")
    selected_stats={n:{k:rounded(v,3) if isinstance(v,float) else v for k,v in nets[n].items()}
                    for n in selected}
    high_power_watts=2.0*150.0
    high_power_geom_mm=(18.0,16.0,4.2)
    high_power_cm3=math.prod(high_power_geom_mm)/1000.0
    high_power_density=high_power_watts*W_PER_IN3_PER_W_PER_CM3/high_power_cm3
    high_power_current_density=150.0/(high_power_geom_mm[0]*high_power_geom_mm[1])
    performance_budgets={}
    for eff in (.95,.96,.97,.98):
        performance_budgets[f"full_load_{eff*100:g}pct"]={
          "loss_watts":rounded(p_out*(1/eff-1),3),
          "loss_budgets_are_target_not_test_results":True}
    product_tgt=density_to_geometry(p_out,FOCUS_DENSITY,HEIGHT_RESEARCH_MM)
    wider=density_to_geometry(p_out,BROADER_STRETCH_DENSITY,HEIGHT_RESEARCH_MM)
    return {
      "schema":"d1_frontier_feasibility/1",
      "status":"DESIGN_FEASIBILITY_ONLY_NO_PERFORMANCE_DEMONSTRATED",
      "source_pcb_sha256":PCB_SHA,"source_path":BOARD_REL,
      "reference_48_to_2v": {"Vin_nominal_V":CIN_V,"Vout_nominal_V":VOUT_V,
                            "Iout_reference_A":I_OUT_A,"Pout_reference_W":p_out,
                            "ratio_reference":CIN_V/VOUT_V,
                            "ratio_requires_real_schematic_circuit_verification":True},
      "existing_legacy_verification_platform":{
         "board_mm":[rounded(width,2),rounded(height,2)],
         "board_area_mm2":rounded(area,2),
         "reference_height_mm":HEIGHT_LEGACY_MM,
         "envelope_volume_cm3":rounded(area*HEIGHT_LEGACY_MM/1000,3),
         "density_at_reference_200W_w_in3":rounded(p_out*W_PER_IN3_PER_W_PER_CM3/(area*HEIGHT_LEGACY_MM/1000),2),
         "density_at_reference_200W_w_cm3":rounded(p_out/(area*HEIGHT_LEGACY_MM/1000),4),
         "footprints":149,"layers_declared":12,"zones":len(list(b.Zones())),
         "missing_real_magnetics":missing,
         "actual_full_module_density_measured":False
      },
      "capacitor_blocker":{
         "oem_units":len(t530),
         "oem_B_one_courtyard_mm":list(T530_OEM_B_COURTYARD_MM),
         "nominal_courtyard_total_mm2":rounded(cap_area,3),
         "manufacturer_per_cap_nominal_uF":T530_CAPACITANCE_UF,
         "nominal_parallel_array_capacitance_mF":rounded(len(t530)*T530_CAPACITANCE_UF/1000,3),
         "manufacturer_max_seated_height_mm":T530_BODY_SEATED_HEIGHT_MAX_MM,
         "product_4mm_research_envelope_has_single_cap_height_violation_without_recess":T530_BODY_SEATED_HEIGHT_MAX_MM>HEIGHT_RESEARCH_MM,
         "manufacturer_datasheet_uri":"https://search.kemet.com/download/specsheet/T530X477M006ATE004",
         "courtyard_area_over_4000_w_in3_max_module_area_factor":rounded(cap_area/product_tgt["max_footprint_area_mm2"],2),
         "interpretation":"Even the summed planar capacitor courtyards cannot fit the entire target-module 2D footprint; 72-COUT product BOM architecture must change. This is area arithmetic, not a packing proof.",
         "no_unverified_replacement_capacitance_claim":True,
      },
      "targets_not_achieved":{
         "primary_48v_2v_density_challenge":product_tgt,
         "broader_all_ratio_exploratory_challenge":wider,
         "density_includes":"required onboard capacitors, controls, drivers, switches, magnetics, electrical terminals, insulation and necessary packaging in actual bounding box",
         "coolplate_reporting":"module-only and coldplate-inclusive density must be stated separately; cannot omit required onboard cooling for continuous operation",
         "actual_power_density_qualified":False,
      },
      "published_frontier_operating_points_not_directly_comparable":FRONTIER,
      "exploratory_150A_product_envelope_NOT_A_CAD":{
        "voltage_v":2.0,"current_a":150.0,"power_w":high_power_watts,
        "bounding_dimensions_assumed_mm":list(high_power_geom_mm),
        "bounding_volume_cm3":rounded(high_power_cm3,4),
        "conditional_density_w_in3":rounded(high_power_density,1),
        "conditional_footprint_current_density_a_mm2":rounded(high_power_current_density,4),
        "full_load_97pct_total_loss_budget_w":rounded(high_power_watts*(1/.97-1),3),
        "full_load_98pct_total_loss_budget_w":rounded(high_power_watts*(1/.98-1),3),
        "output_pair_hot_resistance_target_microohm":50,
        "output_pair_drop_at_150A_mV":rounded(150.0*50/1000.0,3),
        "output_pair_loss_at_150A_w":rounded(150.0**2*50e-6,3),
        "geometry_placement_thermal_and_current_fabrication_validated":False,
        "status":"BOUNDING_BOX_MATH_ONLY_NOT_LAYOUT_OR_MODEL_VALIDATION"
      },
      "loss_budget_at_reference_point":performance_budgets,
      "actual_selected_net_geometry":{
         "notes":"Summed copper segment lengths are not one point-to-point conduction loop length.",
         "nets":selected_stats,
         "no_full_EMI_or_current_rating_from_KiCad_DRC":True
      },
      "G0_G1_functional_witness":"PENDING full CT,T1-T4 24-terminal 12-layer winding and real SCH/ERC/driver/UVLO/D0 tests",
      "research_direction":[
        "Keep present 0/0 PCB only for functionality + model validation; do not shrink it by affine scaling.",
        "Investigate a NEW single-power-cell compact planar matrix transformer with shared core and short side-contact SR, not four far separated core groups.",
        "Use physically complete 24:1 mapping (series primary / parallel low-voltage secondaries) and validate actual startup, circulating currents and polarity before CAD freeze.",
        "Exploit fractional-turn or integrated-leakage winding options only after Maxwell matrix and thermal/SOA prove they are viable.",
        "Abandon unqualified 72 x large T530 for product SKU: derive required output capacitance from transient charge, ripple and current stress, then design close-coupled small-cap arrays + explicit system load decoupling boundary.",
        "Route positive AND return output metal as co-designed low-ESL pair with multiple symmetric SR cells and plated output terminations; prohibit skinny 100A traces/via bottlenecks.",
        "Co-package high-side/low-side gate drivers adjacent to switching bridge with local return loops; optimize OC noise path and Kelvin source.",
        "After working G1, freeze native CAD and optimize via frequency, device loss, core geometry, output termination, packaging and heat extraction as a co-design rather than decorative DRC zero."
      ],
      "release_permission":False,
    }

def main():
    ap=argparse.ArgumentParser()
    grp=ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--write",action="store_true")
    grp.add_argument("--check",action="store_true")
    args=ap.parse_args()
    data=calculate()
    out=ROOT/OUT_REL
    body=json.dumps(data,ensure_ascii=False,indent=2)+"\n"
    if args.write:
        out.write_text(body,encoding="utf8")
    elif out.read_text("utf8")!=body:
        raise ValueError("Stale performance-screen report; recompute after any PCB change")
    print(json.dumps({"status":data["status"],
      "legacy_density_W_in3":data["existing_legacy_verification_platform"]["density_at_reference_200W_w_in3"],
      "max_volume_for_4000_W_in3_cm3":data["targets_not_achieved"]["primary_48v_2v_density_challenge"]["max_module_volume_cm3"],
      "legacy_72_courtyard_area_factor":data["capacitor_blocker"]["courtyard_area_over_4000_w_in3_max_module_area_factor"]}))
if __name__=="__main__":
    try:main()
    except (ValueError,OSError) as exc:
        print("FRONTIER GATE FAIL",exc,file=sys.stderr);sys.exit(1)
