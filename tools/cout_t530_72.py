"""Cost-unrestricted, original-OEM-sourced 6.3V alternative to 2.5V Cout.

This is a REAL 72-body G1 XY geometry study, not a bill of materials released to
manufacture. It keeps high-voltage P0 targets separate from the earlier
15x A720 2.5V simulation model.

Factory source is the KEMET T530 exact-order part sheet already captured in
hardware/dcx_main/oem_sourcing_inputs_2026-11-09.json. Its 4 mOhm rating is
100kHz/25C, NOT a measured 100C/200kHz ESR. Calculations at 125C use the
separately listed 100kHz ripple rating (2.05 Arms/unit), NOT the 45C figure.

    python tools/cout_t530_72.py --check
    python tools/cout_t530_72.py --export /tmp/t530_72_layout.json

An export provides XY and a collision audit for a *new* native board.
It never adds solder pads to the live EasyEDA PCB. Existing PGND/VOUT copper
intersects this zone and must be rerouted into designed high-current conductors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import g2_board_keepout as K

ROOT = Path(__file__).resolve().parents[1]
SOURCING = ROOT / "hardware/dcx_main/oem_sourcing_inputs_2026-11-09.json"
TARGETS = ROOT / "hardware/dcx_main/oem_sourcing_screen_2026-11-09.json"
BASE = ROOT / "hardware/dcx_main/g1/dcx_main_board_g1_signal_stubs.eprj2"
COLS, ROWS = 18, 4
X0_MM, XPITCH_MM = 8.0, 8.3
Y0_MM, YPITCH_MM = 92.0, 6.4
# Conservative trial envelope adds a DESIGN margin of 0.3 mm total to the
# data-sheet L/W nominal dimensions. No claim that this equals the OEM max or
# soldering courtyard; real pad/footprint approval still mandatory.
EXTRA_BODY_MM = 0.3
VISIBLE_PAD_GAP_MM = 0.3
MM_PER_MIL = 0.0254
BOARD_WIDTH_MM, BOARD_HEIGHT_MM = 155, 131
BUDGET_UOHM = 70


def get_part() -> tuple[dict, dict, dict]:
    src = json.loads(SOURCING.read_text(encoding="utf-8"))
    target = json.loads(TARGETS.read_text(encoding="utf-8"))["targets"]
    sources = {x["id"]:x for x in src["sources"]}
    cap = next(c for c in src["capacitor_candidates"]
               if c["mpn"] == "T530X477M006ATE004")
    exact = sources[cap["source_id"]]
    if (exact["grade"] != "EXACT_OEM_PART_SHEET"
            or exact["mpn"] != cap["mpn"]
            or not exact["official_url"].startswith("https://")
            or cap["cap_uF"] != 470
            or cap["min_cap_fraction"] != .8
            or cap["nominal_voltage_v_at_or_below_105c"] != 6.3
            or cap["voltage_v_at_125c"] != 4.22
            or cap["esr_mohm_at_100khz"] != 4
            or cap["esr_test_temp_c"] != 25
            or cap["ripple_rms_a_at_100khz_by_temp_c"]["125"] != 2.05
            or cap["body_height_max_mm"] != 4.3):
        raise ValueError("T530 original part sourcing changed; requalify the array")
    if (target["bank_cap_esr_budget_mohm"] != .07
            or target["capacitance_min_mf"] != 7.05
            or target["bank_ripple_required_arms"] != 84.092907
            or target["preferred_vrating_v"] != 6.3):
        raise ValueError("Performance-first RFQ changed; requalify part counts")
    return cap,exact,target


def bounds(x: float, y: float, w: float, h: float) -> tuple:
    return x-w/2,y-h/2,x+w/2,y+h/2


def touches(a,b,gap=0.) -> bool:
    """Conservative axis-aligned 2D rectangular proximity check."""
    return (a[0]-gap < b[2] and b[0]-gap < a[2]
            and a[1]-gap < b[3] and b[1]-gap < a[3])


def segment_hits_rectangle(a,b,r) -> bool:
    """Finite-segment vs AABB, including segments wholly inside the box."""
    x0,y0=a;x1,y1=b
    dx,dy=x1-x0,y1-y0
    tmin,tmax=0.,1.
    for p,q in ((-dx,x0-r[0]),(dx,r[2]-x0),
                (-dy,y0-r[1]),(dy,r[3]-y0)):
        if abs(p)<1e-12:
            if q<0:return False
        else:
            t=q/p
            if p<0:tmin=max(tmin,t)
            else:tmax=min(tmax,t)
            if tmin>tmax:return False
    return True


def units(w,h) -> list:
    return [{
      "ref":f"CHV{row*COLS+col+1:02}",
      "candidate_position_mm":[round(X0_MM+col*XPITCH_MM,4),
                               round(Y0_MM+row*YPITCH_MM,4)],
      "row":row+1,"column":col+1,
      "positive_net":"VOUT","negative_net":"PGND",
      "polarized_device":True,
      "actual_schematic_component":False,
      "actual_native_pcb_component":False,
      "oem_pad_land_pattern_qualified":False,
    } for row in range(ROWS) for col in range(COLS)]


def report() -> dict:
    p,manufacturer,t=get_part()
    native=K.read_source()
    if hashlib.sha256(BASE.read_bytes()).hexdigest()!=K.EXPECTED_BOARD_SHA256:
        raise ValueError("Wrong native G1 source for T530 placement")
    w=p["body_length_mm"]+EXTRA_BODY_MM
    h=p["body_width_mm"]+EXTRA_BODY_MM
    items=units(w,h)
    boxes=[bounds(*u["candidate_position_mm"],w,h) for u in items]
    for i,box in enumerate(boxes):
        if not (2.0<=box[0] and box[2]<=BOARD_WIDTH_MM-2.0
                and 2.0<=box[1] and box[3]<=BOARD_HEIGHT_MM-2.0):
            raise ValueError(f"Envelope {items[i]['ref']} outside board margin")
        for prev in boxes[:i]:
            if touches(box,prev):
                raise ValueError(f"Two Cout body envelopes physically overlap at {i}")
    oldpads=[]
    for i,box in enumerate(boxes):
        for pad in native["pads"]:
            if touches(box,K.pad_bbox(pad),VISIBLE_PAD_GAP_MM):
                oldpads.append({"unit":items[i]["ref"],"ref":pad.get("ref"),
                        "pin":pad.get("PadNumber"),"net":pad.get("Net")})
    if oldpads:
        raise ValueError(f"T530 trial body collides with current G1 pad: {oldpads[:5]}")
    # A copper route running underneath an insulated capacitor body is not
    # itself a metal short. Flag all of them because the actual two SMD lands,
    # solder-mask, inner pours and thermal/cold-plate spacing remain unresolved.
    crossing=[]
    for i,box in enumerate(boxes):
        for line in native["lines"]:
            half=float(line["width"])*MM_PER_MIL/2
            fat=(box[0]-.25-half,box[1]-.25-half,box[2]+.25+half,box[3]+.25+half)
            a=(float(line["x1"])*MM_PER_MIL,-float(line["y1"])*MM_PER_MIL)
            b=(float(line["x2"])*MM_PER_MIL,-float(line["y2"])*MM_PER_MIL)
            if segment_hits_rectangle(a,b,fat):
                crossing.append({"unit":items[i]["ref"],"net":line["net"],
                                 "existing_copper_id":line["id"]})
    n=COLS*ROWS
    bank_esr=p["esr_mohm_at_100khz"]/n
    required_ripple=t["bank_ripple_required_arms"]
    nominal_cap_uF=n*p["cap_uF"]
    return {
      "schema":"g2_t530_72_cost_unrestricted/1",
      "status":"OEM_VERIFIED_6P3V_COUT_CONCEPT_REQUIRES_POWER_REROUTE_NOT_FOR_FAB",
      "part":{"mpn":p["mpn"],"vendor":manufacturer["maker"],
        "exact_order_oem_url":manufacturer["official_url"],
        "oem_provenance":"hardware/dcx_main/oem_sourcing_inputs_2026-11-09.json",
        "capacitance_uF":p["cap_uF"],
        "rated_v_at_or_below_105c":p["nominal_voltage_v_at_or_below_105c"],
        "rated_v_at_125c":p["voltage_v_at_125c"],
        "esr_mohm_at_100khz_25c":p["esr_mohm_at_100khz"],
        "ripple_a_at_100khz_125c":p["ripple_rms_a_at_100khz_by_temp_c"]["125"],
        "body_nominal_mm":[p["body_length_mm"],p["body_width_mm"]],
        "max_height_mm":p["body_height_max_mm"],
        "trial_body_mm_including_0p3_assumed_margin":[w,h]},
      "requirements":{"voltage_p0_min_v":4.0,
         "voltage_preferred_v":t["preferred_vrating_v"],
         "minimum_nominal_capacity_mF":t["capacitance_min_mf"],
         "ripple_p0_arms":required_ripple,
         "bank_esr_mohm_at_operating_frequency_and_temperature":
            t["bank_cap_esr_budget_mohm"],
         "separate_copper_joints_mohm":t["bank_copper_and_joint_separate_budget_mohm"]},
      "arithmetic_100khz_25c_only":{
        "minimum_count_for_c_nominal":math.ceil(t["capacitance_min_mf"]*1000/p["cap_uF"]),
        "minimum_count_for_ideal_esr":math.ceil(p["esr_mohm_at_100khz"]/
                                                       t["bank_cap_esr_budget_mohm"]),
        "chosen_count":n,
        "nominal_capacity_mF":round(nominal_cap_uF/1000,6),
        "initial_tolerance_min_mF":round(nominal_cap_uF*p["min_cap_fraction"]/1000,6),
        "bank_esr_mohm_25c":round(bank_esr,9),
        "esr_arithmetic_margin_mohm_at_25c":round(t["bank_cap_esr_budget_mohm"]-bank_esr,9),
        "maximum_allowed_esr_per_part_mohm_at_hot_frequency":
            round(n*t["bank_cap_esr_budget_mohm"],6),
        "allowed_esr_increase_over_25c_before_limit_pct":
            round(100*(n*t["bank_cap_esr_budget_mohm"]/p["esr_mohm_at_100khz"]-1),4),
        "bank_125c_ripple_nameplate_sum_a_at_100khz":
            round(n*p["ripple_rms_a_at_100khz_by_temp_c"]["125"],6),
        "assumed_equal_ripple_per_unit_a":round(required_ripple/n,6),
        "125c_ripple_arithmetic_only_pass":
            n*p["ripple_rms_a_at_100khz_by_temp_c"]["125"]>=required_ripple,
        "voltage_nominal_and_125c_at_least_4v":
            min(p["nominal_voltage_v_at_or_below_105c"],p["voltage_v_at_125c"])>=4.,
        "hot_200khz_esr_qualified":False,
        "hot_200khz_ripple_qualified":False,
        "startup_dynamics_qualified":False,
        "ac_current_sharing_qualified":False,
        "thermal_qualified":False},
      "placement":{
        "board_source_sha256":K.EXPECTED_BOARD_SHA256,
        "board_readback_lines":len(native["lines"]),
        "board_readback_pads":len(native["pads"]),
        "board_readback_vias":len(native["vias"]),
        "grid_columns":COLS,"grid_rows":ROWS,
        "row_x_start_mm":X0_MM,"column_pitch_mm":XPITCH_MM,
        "row_y_start_mm":Y0_MM,"row_pitch_mm":YPITCH_MM,
        "body_gap_x_mm":round(XPITCH_MM-w,5),
        "body_gap_y_mm":round(YPITCH_MM-h,5),
        "manufacturer_courtyard_verified":False,
        "current_native_component_count_added":0,
        "existing_pad_body_conflicts":oldpads,
        "existing_copper_traversals_count":len(crossing),
        "existing_copper_traversals_by_net":dict(sorted(Counter(x["net"] for x in crossing).items())),
        "existing_copper_traversals_for_eco":crossing,
        "units":items},
      "hardware_gates":{
        "nominal_esr_arithmetic_at_25c_pass":bank_esr<=t["bank_cap_esr_budget_mohm"],
        "supplier_6p3v_identity_known":True,
        "official_25c_100khz_specs_known":True,
        "actual_pad_polarity_approved":False,
        "actual_72_components_in_schematic_and_pcb":False,
        "corrected_100a_high_current_copper_in_native_board":False,
        "coldplate_and_16mm_full_assembly_qualified":False,
        "100c_200khz_esr_ripple_current_startup_qualified":False,
        "complete_original_native_drc_zero":False,
        "fab_approved":False},
      "next_real_eda_eco":"Copy current 107-line native PCB and revise VOUT/PGND high-current conductors before replacing single Cout placeholder; create 72 real OEM-approved footprints with true VOUT/PGND polarity and confirm 0.7mm provisional body gaps, 65 copper traversals, pad geometry, new native DRC, hot 200kHz ESR, 33.84mF startup/soft-start and 16mm full thermal assembly.",
    }


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    arg=ap.add_mutually_exclusive_group(required=True)
    arg.add_argument("--check",action="store_true")
    arg.add_argument("--export",type=Path)
    a=ap.parse_args()
    data=report()
    assert data["arithmetic_100khz_25c_only"]["chosen_count"]==72
    assert data["hardware_gates"]["fab_approved"] is False
    if a.export:
        a.export.parent.mkdir(parents=True,exist_ok=True)
        a.export.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",
                            encoding="utf-8")
        print(a.export)
    else:
        info=data["arithmetic_100khz_25c_only"]
        print(json.dumps({"status":data["status"],
            "count":info["chosen_count"],
            "mF_nominal":info["nominal_capacity_mF"],
            "ESR_25C_mOhm":info["bank_esr_mohm_25c"],
            "hot_200khz_verified":info["hot_200khz_esr_qualified"],
            "copper_zone_overlaps":data["placement"]["existing_copper_traversals_count"],
            "fab_approved":False},indent=2))


if __name__=="__main__":
    main()
