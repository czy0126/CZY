"""D1 reference logic for hardware protection architecture only.

This is a truth table, not synthesizable hardware, timing model or proof.
Initial state is locked OFF; HARD comparator must not be blanked at startup.
"""
from __future__ import annotations
from dataclasses import dataclass
import argparse
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
SPEC=ROOT/"hardware/dcx_main/two_tier_protection_logic_contract.json"
OUT=ROOT/"design/v3/power_priority/two_tier_fault_truth_table.json"
@dataclass(frozen=True)
class Inputs:
    hard_trip:bool=False
    fast_trip:bool=False
    armed:bool=False
    primary_bias_good:bool=False
    secondary_bias_good:bool=False
    ct_signal_valid:bool=False
    comparator_bias_good:bool=False
    start_sequence_ready:bool=False
    operator_run:bool=False
    reset_ack:bool=False
    all_ten_gates_off:bool=False

def transition(latched_off:bool, i:Inputs)->dict:
    healthy=(i.primary_bias_good and i.secondary_bias_good and
             i.ct_signal_valid and i.comparator_bias_good)
    active_hard=i.hard_trip or not healthy
    active_fast=i.fast_trip and i.armed
    fault=active_hard or active_fast
    reset_valid=(i.reset_ack and healthy and not fault and
                 i.start_sequence_ready and i.all_ten_gates_off)
    # Set trip ALWAYS dominates reset; no auto-restart on power restoration.
    next_latched=bool(fault or (latched_off and not reset_valid))
    permits=bool(healthy and i.start_sequence_ready and i.operator_run and
                 not next_latched and not active_hard)
    return {"hard_fault_effective":bool(active_hard),
            "fast_fault_effective":bool(active_fast),
            "fault_effective":bool(fault),
            "reset_accepted":bool(reset_valid and latched_off),
            "latched_off_next":bool(next_latched),
            "primary_en_permit":permits,
            "secondary_sr_permit":permits,
            "all_ten_gate_disable":not permits}

def example_records()->dict:
    base=dict(primary_bias_good=True,secondary_bias_good=True,
              ct_signal_valid=True,comparator_bias_good=True,
              start_sequence_ready=True,operator_run=True,all_ten_gates_off=True)
    steps=[
      ("POWER_UP_UNHEALTHY",True,Inputs()),
      ("RAILS_HEALTHY_NO_ACK",True,Inputs(**base)),
      ("ACK_SAFE",True,Inputs(**base,reset_ack=True)),
      ("RUN_COLD_UNARMED_FAST_ONLY",False,Inputs(**base,fast_trip=True,armed=False)),
      ("HARD_SHORT_UNARMED",False,Inputs(**base,hard_trip=True,armed=False)),
      ("CLEAR_FAULT_BUT_NO_ACK",True,Inputs(**base)),
      ("FAST_ARMED",False,Inputs(**base,fast_trip=True,armed=True)),
      ("SENSOR_OPEN_UNARMED",False,Inputs(**{**base,"ct_signal_valid":False,"armed":False})),
      ("SUPERVISOR_POWER_LOST",False,Inputs(**{**base,"comparator_bias_good":False})),
      ("RESET_DURING_HARD_FAULT",True,Inputs(**base,hard_trip=True,reset_ack=True)),
      ("RESET_BEFORE_GATES_OFF",True,Inputs(**{**base,"reset_ack":True,"all_ten_gates_off":False})),
      ("OPERATOR_RUN_LOW",False,Inputs(**{**base,"operator_run":False})),
    ]
    return {"kind":"TWO_TIER_HARD_AND_FAST_LOGIC_TRUTH_TABLE",
            "evidence_level":"BOOLEAN_ONLY_NOT_A_POWER_STAGE_OR_HARDWARE_SIM",
            "protection_approved":False,
            "hardware_latch_exists":False,
            "reset_requires_external_gate_off_measurement":True,
            "cases":[{"case":name,"initial_latched_off":initial,
              "inputs":vars(inp),"outputs":transition(initial,inp)} for name,initial,inp in steps]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--check",action="store_true")
    p.add_argument("--write",action="store_true")
    opt=p.parse_args()
    spec=json.loads(SPEC.read_text(encoding="utf-8"))
    if spec["hardware_implemented"] or spec["fabrication_approval"] or spec["state_machine_only_not_board_evidence"] is not True:
        raise SystemExit("wrongly promoted a reference truth table to real hardware")
    expected=json.dumps(example_records(),ensure_ascii=False,indent=2)+"\n"
    if opt.write:OUT.write_text(expected,encoding="utf-8",newline="\n")
    elif opt.check and (not OUT.exists() or OUT.read_text(encoding="utf-8")!=expected):
        raise SystemExit("truth table stale")
    print("Two-tier protection reference: hard trip active at startup; no board hardware approved")
if __name__=="__main__":main()
