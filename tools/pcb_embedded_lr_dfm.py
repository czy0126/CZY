"""Quantify real PCB-embedded Lr *candidate* transition-via DC bottleneck.

Strictly a source-bound manufacturability screening extension for the
independent six-layer KiCad board; it is NOT the production EasyEDA motherboard
and cannot qualify through-hole impulse, AC, thermal or dielectric behavior.
The *actual Lr RMS* is 9.450157 A, not the 100-A converter output current.

Usage:
    python tools/pcb_embedded_lr_dfm.py --write
    python tools/pcb_embedded_lr_dfm.py --check
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path

import pcb_embedded_lr as native

ROOT=native.ROOT
ASSUMPTIONS=ROOT/"design/v3/maxwell/pcb_embedded_lr_dfm_assumptions.json"
REPORT=native.OUT/"ELP38_Lr_3turn_PCB_embedded_DFM_via_screen_NOT_FOR_FAB.json"
RFQ=native.OUT/"ELP38_Lr_3turn_PCB_embedded_factory_review_NOT_FOR_FAB.csv"

def sha_lf(path:Path)->str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()

def validate():
    assumptions=json.loads(ASSUMPTIONS.read_text(encoding="utf-8"))
    trial,case,routes,slots,endpoints,measured=native.design()
    data=json.loads(native.REPORT.read_text(encoding="utf-8"))
    if data!=measured:
        raise ValueError("Existing native six-layer PCB winding trial is stale relative to source geometry")
    content=native.PCB.read_text(encoding="utf-8")
    if content!=native.contents()[0]:
        raise ValueError("Native PCB copper geometry is stale or edited without validation")
    if len(routes)!=3 or len(endpoints)!=4 or len(slots)!=3:
        raise ValueError("Expected exactly three routed series turns, two series transition vias")
    if content.count("(via (at ")!=2:
        raise ValueError("Native PCB no longer has the accepted two series transition vias")
    if assumptions["schema"]!="D1_PCB_EMBEDDED_LR_VIA_DFM_SENSITIVITY_V1":
        raise ValueError("Wrong DFM assumptions contract")
    board=trial["board"]
    if not math.isclose(assumptions["assumed_finished_drill_mm"],
                        board["transition_via_drill_mm"],abs_tol=1e-9):
        raise ValueError("Barrel trial drill differs from actual embedded-board CAD")
    if not math.isclose(assumptions["board_thickness_mm"],
                        board["nominal_thickness_mm"],abs_tol=1e-9):
        raise ValueError("Plated barrel length differs from native stackup")
    if assumptions["manufacturer_plating_verified"] or assumptions["manufacturer_stackup_verified"]:
        raise ValueError("Assumed copper/stack-up data may not self-certify a manufacturer")
    if any(not (0 < value/1000 < board["transition_via_drill_mm"]/2)
           for value in assumptions["assumed_barrel_plating_um"]):
        raise ValueError("PTH plating thickness outside annular geometry")
    if (len(assumptions["assumed_barrel_plating_um"])!=3
            or sorted(assumptions["assumed_barrel_plating_um"])!=assumptions["assumed_barrel_plating_um"]):
        raise ValueError("Expected three sorted distinct trial plating thicknesses")
    return assumptions,trial,case,measured

def evaluate():
    assumptions,trial,case,existing=validate()
    board=trial["board"];physical=trial["physics"]
    load=json.loads((ROOT/trial["load_source"]).read_text(encoding="utf-8"))
    i_rms=load["copper_loss_basis"]["rated_100a_a"]
    i_overload=load["copper_loss_basis"]["current_a"]
    peak=max(x["current_a"] for x in load["physical_peaks"]["cases"].values())
    rho20=physical["copper_rho20_ohm_m"]
    rho_hot=rho20*(1+physical["copper_alpha_per_k"]*
                    (assumptions["copper_barrel_temperature_c"]-
                     physical["nominal_reference_temp_c"]))
    d_mm=assumptions["assumed_finished_drill_mm"]
    length_mm=assumptions["board_thickness_mm"]
    a_foil=existing["dc_copper_only_estimate"]["effective_copper_section_per_turn_mm2"]
    winding_pdc=existing["dc_copper_only_estimate"]["Pdc_100c_100a_output_w"]
    results=[]
    for plating_um in assumptions["assumed_barrel_plating_um"]:
        t_mm=plating_um/1000
        # Finished drill diameter is inner hole diameter; plating forms
        # annulus *outside* that diameter. This is a best-case straight shell.
        a_mm2=math.pi/4*((d_mm+2*t_mm)**2-d_mm**2)
        r_hot=rho_hot*length_mm*1e-3/(a_mm2*1e-6)
        results.append({
            "trial_barrel_thickness_um":plating_um,
            "copper_barrel_annulus_area_mm2":round(a_mm2,7),
            "via_R_100C_ohm_DC_ideal":round(r_hot,9),
            "rated_RMS_9p45A_current_density_A_mm2":round(i_rms/a_mm2,3),
            "overload_RMS_11p22A_current_density_A_mm2":round(i_overload/a_mm2,3),
            "fault_peak_ge_104A_current_density_A_mm2":round(peak/a_mm2,1),
            "single_via_Pdc_rated_W":round(i_rms*i_rms*r_hot,6),
            "two_vias_series_Pdc_rated_W":round(2*i_rms*i_rms*r_hot,6),
            "single_via_Pdc_overload_W":round(i_overload*i_overload*r_hot,6),
            "current_density_vs_bilayer_foil_ratio":round(a_foil/a_mm2,3),
            "plating_and_thermal_unverified":True,
        })
    assert len(results)==3
    assert all(results[i]["single_via_Pdc_rated_W"]>results[i+1]["single_via_Pdc_rated_W"]
               for i in range(2))
    report={
        "schema":"D1_EMBEDDED_PCB_LR_MANUFACTURABILITY_SCREEN_V1",
        "status":"DFM_AND_100C_VIA_RESISTANCE_TRIAL_NOT_FOR_FAB",
        "source_sha256_canonical_lf":{
            a.relative_to(ROOT).as_posix():sha_lf(a)
            for a in (ASSUMPTIONS,native.CONFIG,native.REPORT,
                      ROOT/trial["load_source"])},
        "native_cad_exact_sha256":hashlib.sha256(native.PCB.read_bytes()).hexdigest(),
        "model_construction":"three series turns, each two equal parallel 70um x 2.5mm copper layers",
        "Lr_rms_at_100A_output_A":i_rms,
        "Lr_overload_rms_A":i_overload,
        "highest_existing_Lr_transient_peak_A":peak,
        "one_turn_pair_parallel_copper_area_mm2":a_foil,
        "pair_foil_rated_RMS_current_density_A_mm2":round(i_rms/a_foil,3),
        "three_turns_no_via_Pdc_100C_W":winding_pdc,
        "via_count_in_series":2,
        "barrel_length_mm":length_mm,
        "barrel_assumed_finished_drill_mm":d_mm,
        "via_plating_sensitivity":results,
        "critical_conclusions":[
            "The Lr winding carries about 9.45A RMS at 100A converter output, NOT 100A DC output",
            "A SINGLE finished 0.35mm PTH per series transition is a high-current-density choke relative to the two-layer foil",
            "Two transition barrels, pads, plating and hot-spot thermal resistance are unqualified; computed DC losses omit pad/return spreading",
            "No 200kHz fringing/proximity/eddy current or thermal field result can be inferred from these DC values",
            "The 3-turn analytic 2.356mm gap lies outside the cited 2mm sample equation; OEM N97 100C L(I) and tolerances are unverified",
            "Standalone KiCad winding is not placed into, or net-parity checked against, the full EasyEDA power motherboard",
            "T1–T4 multiport 3:1:1 and CT require independent PCB layer winding designs and DOT/insulation approvals",
        ],
        "manufacturer_copper_barrel_qualified":False,
        "manufacturer_6layer_thickcopper_stackup_qualified":False,
        "fault_peak_and_200kHz_ac_current_qualified":False,
        "actual_total_16mm_assembly_qualified":False,
        "main_power_board_winding_integrated":False,
        "not_for_fab":True,
    }
    return report,assumptions

def contents():
    report,assumptions=evaluate()
    body=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    buff=io.StringIO(newline="")
    writer=csv.writer(buff,lineterminator="\n")
    writer.writerow(["item","source_or_required_fact","requested_supplier_qualification","evidence_status"])
    writer.writerow(["native_geometry",native.PCB.relative_to(ROOT).as_posix(),
                     "actual 3-turn 6-layer copper, three ferrite apertures and winding terminals","ENGINEERING_TRIAL_ONLY"])
    for row in report["via_plating_sensitivity"]:
        writer.writerow([f"series_via_{row['trial_barrel_thickness_um']}um_trial",
             f"{row['copper_barrel_annulus_area_mm2']}mm² / "+str(row["single_via_Pdc_rated_W"])+"W nominal",
             "Obtain actual minimum plated barrel copper per coupon, demonstrate local rise at 9.45A RMS / >=104A pulse",
             "UNVERIFIED_COMPUTED_DC_ONLY"])
    for i,q in enumerate(assumptions["manufacturing_questions"],1):
        writer.writerow([f"DFM_Q{i:02d}","",
                         q,"PENDING_VENDOR_DOCUMENT_OR_FIRST_ARTICLE"])
    writer.writerow(["release","", "No first-article PCB fabrication or high-energy gate approval without N97 L(I), insulation, thermal and current evidence", "NOT_FOR_FAB"])
    return body,buff.getvalue()

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--write",action="store_true")
    p.add_argument("--check",action="store_true")
    a=p.parse_args()
    report,csv_text=contents()
    if a.write:
        REPORT.write_text(report,encoding="utf-8",newline="\n")
        RFQ.write_text(csv_text,encoding="utf-8",newline="\n")
    if a.check:
        if not REPORT.exists() or REPORT.read_text(encoding="utf-8")!=report:
            raise SystemExit("Embedded winding PTH report stale; --write")
        if not RFQ.exists() or RFQ.read_text(encoding="utf-8")!=csv_text:
            raise SystemExit("Embedded winding manufacturer DFM RFQ stale; --write")
    if not a.write and not a.check:
        print(report)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
