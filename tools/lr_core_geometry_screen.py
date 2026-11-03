"""Strict catalog core height + flux cross-section screen; never qualify magnetics from nominal dimensions."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
REQ=ROOT/"design/v3/power_priority/high_margin_design_gate.json"
SRC=ROOT/"design/v3/power_priority/lr_tdk_catalog_core_source.json"
OUT=ROOT/"design/v3/power_priority/lr_tdk_catalog_core_screen.json"
PDF="https://www.tdk-electronics.tdk.com/download/2527774/1e429cb7ad3fd0be062bcfe03f8ed498/ferrites-planar-cores-pb.pdf"
def build() -> dict:
    high=json.loads(REQ.read_text(encoding="utf-8"))
    config=json.loads(SRC.read_text(encoding="utf-8"))
    req=config["requirements"]
    design=high["magnetics"]
    if abs(req["minimum_amin_3turn_mm2"]-design["three_turn_min_ae_mm2"])>1e-6:
        raise ValueError("minimum Lr 3turn Amin diverged from live high-margin gate")
    if abs(req["minimum_amin_4turn_mm2"]-design["four_turn_min_ae_mm2"])>1e-6:
        raise ValueError("minimum Lr 4turn Amin diverged from live high-margin gate")
    if req["converter_max_total_height_mm"]!=high["constraints"]["maximum_assembly_height_mm"]:
        raise ValueError("converter height gate has changed")
    if req["magnetic_b_limit_t"]!=design["design_flux_limit_t"]:
        raise ValueError("magnetic flux design gate changed")
    rows=[]
    for c in config["cores"]:
        nom=c["core_height_nom_mm"]+c["plate_height_nom_mm"]
        hmin=nom-c["core_height_tolerance_mm"]-c["plate_height_tolerance_mm"]
        hmax=nom+c["core_height_tolerance_mm"]+c["plate_height_tolerance_mm"]
        b3=req["model_three_turn_b_at_128mm2_t"]*128/c["amin_mm2"]
        b4=b3*.75
        height=hmax<=req["converter_max_total_height_mm"]
        area3=b3<=req["magnetic_b_limit_t"]
        area4=b4<=req["magnetic_b_limit_t"]
        if c["amin_mm2"]<=0 or hmin<=0:
            raise ValueError("invalid core dimensions")
        rows.append({**c,"core_plus_plate_height_min_mm":round(hmin,2),
            "core_plus_plate_height_nom_mm":round(nom,2),
            "core_plus_plate_height_max_mm":round(hmax,2),
            "height_under_converter_limit_by_core_alone":height,
            "flux_model_3turn_t":round(b3,6),
            "flux_model_4turn_t":round(b4,6),
            "three_turn_area_pass":area3,
            "four_turn_area_pass":area4,
            "three_turn_joint_pass":height and area3,
            "four_turn_joint_pass":height and area4,
            "complete_mechanical_stack_verified":False,"gap_and_L_I_100c_verified":False,
            "full_assembly_height_verified":False,
            "physical_terminals_and_windings_verified":False,
            "disposition":("HEIGHT_CORE_ONLY_PASS_REQUIRES_FULL_STACK" if height and area3 else
               "REJECT_STANDARD_UNMODIFIED_AS_HEIGHT_EXCEEDS_TOTAL_LIMIT" if not height else
               "REJECT_FOR_THREE_AND_FOUR_TURN_FLUX_AT_RFQ_CURRENT")})
    if len(rows)!=5:raise ValueError("5 catalog candidates required")
    if any(r["three_turn_joint_pass"] or r["four_turn_joint_pass"] for r in rows):
        raise ValueError("Unexpected passing standard core: redesign conclusion needs reviewer update")
    return {**{k:v for k,v in config.items() if k!="cores"},
            "cores":rows,
            "status":"NO_UNMODIFIED_STANDARD_SET_SATISFIES_THREE_OR_FOUR_TURN_AREA_AND_FULL_HEIGHT",
            "conclusion":"No evaluated TDK standard ELP+I set meets conservative flux area and <=10mm core-only max height concurrently. A raw core set alone would also need PCB, winding, adhesive, tolerance, clearance and actual L(I); therefore no geometry can be approved for the complete converter.",
            "next_vendor_requested_response":[
                "Dimensioned custom E/I planar magnetic drawing with worst-case total core+gaps+windings+PCB/insertion/adhesive height inside 10mm converter envelope",
                "For Lr 3-turn candidate: core cross-section Amin>=200mm2 preferred; 4-turn candidate >=150mm2 preferred; propose custom reduced-height assembly without assuming catalog geometry retains effective area",
                "Detailed winding pattern, copper resistance and high frequency AC loss vs 200.6kHz and 100C",
                "Actual L(I) and differential incremental L at 100C 0A through >=121.52A with full requested L and Bsat margin",
                "AL/gap tolerance, clamping, fringing and near-copper heating",
                "Real T1-T4 + CT mechanical 24 logical-terminal to pad map including DOT and CTAP/CT polarity"],
            "fab_release":False}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--check",action="store_true")
    p.add_argument("--write",action="store_true")
    a=p.parse_args()
    obj=build()
    data=json.dumps(obj,ensure_ascii=False,indent=2)+"\n"
    if a.write:OUT.write_text(data,encoding="utf-8",newline="\n")
    elif a.check and (not OUT.is_file() or OUT.read_text(encoding="utf-8")!=data):
        raise SystemExit("catalog core geometry screen stale")
    print("5 TDK sets screened: none pass both 10mm core-only height and RFQ flux; custom planar core needed")
if __name__=="__main__":main()
