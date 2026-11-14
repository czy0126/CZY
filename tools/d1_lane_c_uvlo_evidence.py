"""Issue #133 Lane C UVLO / driver-hold-up first-order remote LTspice receipt.

Native KiCad HS reference and source 12V rails are a provisional candidate.
This simulation uses ideal comparator/switch and cannot qualify MOSFET off-time.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
D=ROOT/"design/v3/stage_f/d1_lane_c_g0"
STEM="d1_lane_c_uvlo_holdup_illustrative_NOT_FOR_FAB"
DECK=D/(STEM+".cir")
LOG=D/(STEM+".log")
RAWGZ=D/(STEM+".raw.gz")
REPORT=D/"d1_lane_c_uvlo_holdup_receipt_NOT_FOR_FAB.json"
# These identify the earlier KiCad candidate against which the *original*
# model was submitted. Preserve this evidence anchor after unrelated hardware
# interface revisions; never silently retarget prior raw data to new CAD.
MODELED_NATIVE_SCHEMATIC_SHA="665eeea9b9dd230978921f24a39289d8d9f98cfde910661b3b0c7405917b1856"
MODELED_NATIVE_BOM_SHA="ddcb8f73237e1786ff0743f544414aa76f660860373f1819ab9d6f4c049f49e2"
sys.path.insert(0,str(ROOT/"tools"))
import d1_lane_c_hs_candidate as hw
import d1_lane_c_sim_evidence as shared

def hash_bytes(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def scalar(log:str,key:str)->float:
    m=re.search(r"(?mi)^"+re.escape(key)+r":\s*V\(HOLD\)\s*=\s*([0-9.E+-]+)\s+at\s+[0-9.eE+-]+",log)
    if m is None:raise ValueError("LTspice missing HOLD sample: "+key)
    return float(m.group(1))

def build():
    parts,symbols,expected=hw.expected_text()
    native=hw.check_native(parts,expected)
    required={
        "Rtop RAW SNS 100k",
        "Rbottom SNS 0 10k",
        "Cfilter SNS 0 1n",
        "Rfeedback GOOD SNS 1Meg",
        "Chold HOLD 0 22u",
        "Ihouse HOLD 0 0.02",
        ".ic V(SNS)=1.09 V(GOOD)=5 V(HOLD)=11.5 V(GATE)=12",
        ".tran 0 300u 0 5n uic",
    }
    deck=DECK.read_bytes()
    dt=deck.decode("utf-8")
    missing=sorted(x for x in required if x not in dt.splitlines())
    if missing:raise ValueError("model deviates from provisional KiCad parts: "+str(missing))
    if "NOT cold startup." not in dt or "NOT DERATED" not in dt:
        raise ValueError("model caveats missing")
    log=LOG.read_bytes()
    lt=log.decode("utf-8")
    if "LTspice 26.0.2 for Windows" not in lt or "Total elapsed time:" not in lt:
        raise ValueError("incomplete or wrong LTspice log")
    rawgz=RAWGZ.read_bytes()
    raw=gzip.decompress(rawgz)
    if not raw.startswith(b"Title:") or b"No. Variables:" not in raw[:1000]:
        raise ValueError("raw trace header invalid")
    trip=shared.parse_measure(lt,"uvlo_fall_time")
    gate=shared.parse_measure(lt,"gate_cross_1p3")
    at130=scalar(lt,"hold_at_130u")
    at200=scalar(lt,"hold_at_200u")
    if not (100e-6<trip<150e-6 and trip<gate<trip+50e-6):
        raise ValueError("fault timeline violates model expectations")
    if not (7.5<at200<=at130<15):
        raise ValueError("nominal driver hold-up failed in model")
    if native["uvlo_nominal"]["hold_up_dc_bias_and_esr_verified"]:
        raise ValueError("hold-up cannot be automatically approved")
    return {
        "kind":"D1_LANE_C_UVLO_HOLDUP_SIM_RECEIPT",
        "status":"IDEALIZED_UVLO_AND_HOLDUP_SIMULATED_G0_NOT_APPROVED",
        "remote_engine":"winsrv LTspice 26.0.2",
        "deck_sha256":hash_bytes(deck),
        "log_sha256":hash_bytes(log),
        "raw_sha256":hash_bytes(raw),
        "raw_gzip_sha256":hash_bytes(rawgz),
        "raw_bytes":len(raw),"raw_gzip_bytes":len(rawgz),
        # Prior raw/log run is tied to the original electrical candidate,
        # NOT automatically to U20's newly added emergency-stop/HS interlock.
        "native_candidate_schematic_sha256":MODELED_NATIVE_SCHEMATIC_SHA,
        "native_candidate_bom_sha256":MODELED_NATIVE_BOM_SHA,
        "current_candidate_schematic_sha256":native["output_schematic_sha256"],
        "current_candidate_bom_sha256":native["output_bom_sha256"],
        "candidate_matches_original_simulation_snapshot":
            native["output_schematic_sha256"]==MODELED_NATIVE_SCHEMATIC_SHA and
            native["output_bom_sha256"]==MODELED_NATIVE_BOM_SHA,
        "model_includes_new_external_estop_and_hs_monitor_gate":False,
        "simulation_must_not_be_claimed_for_latest_full_enable_chain":True,
        "uvlo_trip_model_time_s":trip,
        "gate_threshold_model_time_s":gate,
        "ideal_switch_gate_delay_after_uvlo_s":gate-trip,
        "driver_hold_voltage_130us":at130,
        "driver_hold_voltage_200us":at200,
        "initial_12v_ramp_collapse_at_s":100e-6,
        "pre_diode_uvlo_threshold_nominal_falling_v":10.6,
        "pre_diode_uvlo_threshold_nominal_rising_v":11.1,
        "hold_up_nominal_f":22e-6,
        "housekeeping_current_assumed_a":0.02,
        "gate_capacitance_assumed_f":6.7e-9,
        "driver_max_delay_verified":False,
        "full_vendor_capacitance_derating_verified":False,
        "real_comparator_delay_and_ics_modelled":False,
        "real_hardware_waveform_verified":False,
        "real_48v_12v_converter_specified":False,
        "bench_primary_secondary_bias_isolated":False,
        "primary_hs_gate_measurement_in_hardware":False,
        "g0_approved":False,"g1_approved":False,"energization_allowed":False,
    }

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    a=parser.parse_args()
    data=build()
    text=json.dumps(data,indent=2,ensure_ascii=False)+"\n"
    if a.write: REPORT.write_text(text,encoding="utf-8")
    elif not REPORT.is_file() or REPORT.read_text("utf-8")!=text:
        raise SystemExit("uvlo receipt stale/missing")
    print(data["status"],data["ideal_switch_gate_delay_after_uvlo_s"])
if __name__=="__main__":
    main()
