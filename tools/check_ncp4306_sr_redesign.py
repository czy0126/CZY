"""Cross-check NCP4306 alternative against real native SR nets and timing.
Does NOT claim hardware protection or safety certification.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
SPEC=ROOT/"hardware/dcx_main/ncp4306_sr_redesign_candidate.json"
NATIVE=ROOT/"hardware/dcx_main/gen/netlist_export_raw.json"
OUT=ROOT/"design/v3/power_priority/ncp4306_trig_timing_screen.json"
REPORT=ROOT/"hardware/dcx_main/ncp4306_redesign_check.json"
def edge_us(vcc:float,cap_pf:float,r_pull:float=10000,internal_sink_ua:float=15,threshold_v:float=2.2)->float:
    if vcc<=0 or cap_pf<=0 or r_pull<=0: raise ValueError("positive VCC, C, R required")
    vend=vcc-r_pull*internal_sink_ua*1e-6
    if vend<=threshold_v: raise ValueError("TRIG cannot reach disable threshold")
    return -r_pull*cap_pf*1e-12*math.log1p(-threshold_v/vend)*1e6

def calculate()->dict:
    arr=[]
    for v in (8,10,12):
        for c in (25,50,100,200):
            t=edge_us(v,c)
            arr.append({"vcc_v":v,"external_pin_cap_pf":c,"pullup_ohm":10000,
                        "max_internal_sink_ua":15,"threshold_high_worst_v":2.2,
                        "rc_to_trip_us":round(t,6),
                        "max_pd_and_blanking_us":0.0965,
                        "screened_pin_to_driver_off_us":round(t+0.0965,6),
                        "additional_comparator_latch_gate_discharge_us":None,
                        "approval":"NOT_RATED"})
    return {
        "kind":"OPEN_DRAIN_TRIG_UP_EDGE_LIMITING_ONLY",
        "value_domain":"CALCULATED_NOT_MEASURED",
        "reference":"onsemi NCP4306 Rev.9 Feb 2026 Table5",
        "gate_driver_sr_count":8,
        "assumed_pull_up_ohm":10000,
        "threshold_v_max":2.2,
        "trig_sink_ua_max":15,
        "trigger_blank_ns_max":80,
        "trigger_pd_ns_max":16.5,
        "rise_is_simple_first_order_RC_only":True,
        "unknowns_not_included":[
            "TRIG pin physical capacitance including PCB and transistor parasitics",
            "driver gate discharging time (R_G*Q_G) and Miller dv/dt",
            "comparator and hardware latch propagation min/max",
            "interconnect and isolation latency",
            "low-side Kelvin ground bounce",
            "trigger pulse 10ns minimum and blanking behavior",
            "cross-channel skew, dead time and startup short"],
        "cases":arr,
        "release_approved":False,
    }
def verify(candidate=None, native=None)->dict:
    if candidate is None:candidate=json.loads(SPEC.read_text(encoding="utf-8"))
    if native is None:native=json.loads(NATIVE.read_text(encoding="utf-8"))["value"]["refs"]
    errors=[]
    ch=candidate["channels"]
    expected={f"SR{i}{s}" for i in range(1,5) for s in ("A","B")}
    if len(ch)!=8 or {x["sr_mosfet"] for x in ch}!=expected:
        errors.append("eight MOSFET controllers required")
    if {x["new_controller"] for x in ch}!={f"U{i}" for i in range(7,15)}:
        errors.append("unique proposed U7-U14 required")
    if candidate["physical_implementation"]!="NOT_STARTED" or candidate["fabrication_release"]:
        errors.append("design candidate MUST NOT claim actual hardware completion")
    if candidate["datasheet_limits"]["trip_blank_max_ns"]!=80 or candidate["datasheet_limits"]["trip_pd_max_ns"]!=16.5:
        errors.append("onsemi timing constants differ from Rev9")
    for x in ch:
        sr=x["sr_mosfet"]
        mos=native.get(sr,{})
        r=native.get(x["current_gate_resistor"],{})
        if mos.get("4")!=x["current_gate_net"] or mos.get("5")!=x["current_drain_net"]:
            errors.append(sr+" MOS gate/drain changed")
        if any(mos.get(k)!="PGND" for k in ("1","2","3")):
            errors.append(sr+" MOS source Kelvin domain mismatch")
        if r!={"1":x["current_controller_VG_net"],"2":x["current_gate_net"]}:
            errors.append(sr+" Rg existing net changed")
        if native.get(x["current_controller"],{}).get(x["current_controller_VG_pin"])!=x["current_controller_VG_net"]:
            errors.append(sr+" original UCC24624 VG pin mismatch")
        p=x["new_pin_map"]
        if p!={"1":"VCC12_S","2":"R_MIN_TOFF_"+sr,"3":"R_MIN_TON_"+sr,
              "4":"LLD_"+sr,"5":"SR_DISABLE_"+sr,"6":x["current_drain_net"],
              "7":"PGND","8":"GDRV_"+sr}:
            errors.append(sr+" new NCP4306 native pin function invalid")
        if x["external_TRIG_pullup_ohm"]!=10000 or not x["controller_replace_not_add"] or x["installed_in_native_eda"]:
            errors.append(sr+" cannot pass until real native redesign")
    return {"kind":"SR_CONTROLLER_REPLACEMENT_INTERFACE_PREFLIGHT",
            "source":"native logical netlist and NCP4306 Rev9 pins",
            "maps_match_current_native":not errors,"errors":errors,
            "actual_eight_controller_swap_done":False,
            "actual_hard_disable_wired_and_tested":False,
            "startup_and_fault_verified":False,
            "fabrication_approved":False}
def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--write",action="store_true")
    p.add_argument("--check",action="store_true")
    a=p.parse_args()
    r=verify()
    if r["errors"]:raise SystemExit("; ".join(r["errors"]))
    wanted=[(REPORT,json.dumps(r,ensure_ascii=False,indent=2)+"\n"),
            (OUT,json.dumps(calculate(),ensure_ascii=False,indent=2)+"\n")]
    for file,content in wanted:
        if a.write:file.write_text(content,encoding="utf-8",newline="\n")
        elif a.check and (not file.is_file() or file.read_text(encoding="utf-8")!=content):
            raise SystemExit("stale candidate read-only register: "+str(file))
    print("8 SR native pin maps checked. NCP4306 alternate NOT implemented; TRIG delay screen NOT rated.")
    return 0
if __name__=="__main__":raise SystemExit(main())
