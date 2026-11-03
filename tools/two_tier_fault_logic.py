"""Fail-closed reference STATE MACHINE for D1 hard and fast protection.

Not hardware, not a timing model.  Fault SET always dominates reset.
Manual reset is a fresh rising edge *after a healthy low release was observed*.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
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

@dataclass(frozen=True)
class ResetMemory:
    """Abstract externally stored reset qualifier; physical circuit UNDESIGNED.

    After power-up, after any fault, or after supply loss, low_seen must be
    false. A reset acknowledgment held high cannot count as a fresh edge.
    """
    reset_ack_was_high:bool=False
    ack_low_seen_while_healthy:bool=False

def transition(latched_off:bool, i:Inputs, memory:ResetMemory|None=None)->dict:
    if memory is None:
        memory=ResetMemory()
    healthy=(i.primary_bias_good and i.secondary_bias_good and
             i.ct_signal_valid and i.comparator_bias_good)
    active_hard=i.hard_trip or not healthy
    active_fast=i.fast_trip and i.armed
    fault=active_hard or active_fast
    ready=(healthy and not fault and i.start_sequence_ready and
           i.all_ten_gates_off)
    fresh_release=bool(latched_off and ready and not i.reset_ack)
    low_seen=bool(latched_off and ready and
                  (memory.ack_low_seen_while_healthy or fresh_release))
    rising_ack=bool(i.reset_ack and not memory.reset_ack_was_high)
    reset_valid=bool(latched_off and low_seen and rising_ack)
    # Set wins on faults, even when the acknowledgment is held high.
    next_latched=bool(fault or (latched_off and not reset_valid))
    # When a fault occurs, invalidate the release token; a fresh release then
    # a new acknowledgment are required after *this* fault clears.
    next_memory=ResetMemory(
        reset_ack_was_high=bool(i.reset_ack),
        ack_low_seen_while_healthy=bool(next_latched and ready and low_seen))
    permits=bool(healthy and i.start_sequence_ready and i.operator_run and
                 not next_latched and not active_hard)
    return {"hard_fault_effective":bool(active_hard),
            "fast_fault_effective":bool(active_fast),
            "fault_effective":bool(fault),
            "reset_ack_rising_edge":rising_ack,
            "reset_low_seen_while_healthy":low_seen,
            "reset_accepted":reset_valid,
            "latched_off_next":next_latched,
            "primary_en_permit":permits,
            "secondary_sr_permit":permits,
            "all_ten_gate_disable":not permits,
            "reset_memory_next":asdict(next_memory)}

def example_records()->dict:
    base=dict(primary_bias_good=True,secondary_bias_good=True,
              ct_signal_valid=True,comparator_bias_good=True,
              start_sequence_ready=True,operator_run=True,all_ten_gates_off=True)
    fresh=ResetMemory(reset_ack_was_high=False,ack_low_seen_while_healthy=True)
    high=ResetMemory(reset_ack_was_high=True,ack_low_seen_while_healthy=False)
    examples=[
      ("POWER_UP_UNHEALTHY",True,Inputs(),ResetMemory()),
      ("RAILS_HEALTHY_NO_ACK",True,Inputs(**base),ResetMemory()),
      ("ACK_PREMATURE_NO_PRIOR_RELEASE",True,Inputs(**base,reset_ack=True),ResetMemory()),
      ("ACK_SAFE_AFTER_LOW_RELEASE",True,Inputs(**base,reset_ack=True),fresh),
      ("ACK_HELD_DURING_POWER_RECOVERY",True,Inputs(**base,reset_ack=True),high),
      ("RUN_COLD_UNARMED_FAST_ONLY",False,Inputs(**base,fast_trip=True,armed=False),ResetMemory()),
      ("HARD_SHORT_UNARMED",False,Inputs(**base,hard_trip=True,armed=False),ResetMemory()),
      ("CLEAR_FAULT_BUT_NO_ACK",True,Inputs(**base),ResetMemory()),
      ("FAST_ARMED",False,Inputs(**base,fast_trip=True,armed=True),ResetMemory()),
      ("SENSOR_OPEN_UNARMED",False,Inputs(**{**base,"ct_signal_valid":False,"armed":False}),ResetMemory()),
      ("SUPERVISOR_POWER_LOST",False,Inputs(**{**base,"comparator_bias_good":False}),ResetMemory()),
      ("RESET_DURING_HARD_FAULT",True,Inputs(**base,hard_trip=True,reset_ack=True),fresh),
      ("RESET_BEFORE_GATES_OFF",True,Inputs(**{**base,"reset_ack":True,"all_ten_gates_off":False}),fresh),
      ("OPERATOR_RUN_LOW",False,Inputs(**{**base,"operator_run":False}),ResetMemory()),
    ]
    return {"kind":"TWO_TIER_HARD_AND_FAST_LOGIC_TRUTH_TABLE",
            "evidence_level":"BOOLEAN_ONLY_NOT_A_POWER_STAGE_OR_HARDWARE_SIM",
            "protection_approved":False,
            "hardware_latch_exists":False,
            "reset_requires_external_gate_off_measurement":True,
            "reset_requires_new_manual_rising_edge_after_healthy_release":True,
            "physical_ack_edge_memory_has_been_built":False,
            "cases":[{"case":name,"initial_latched_off":initial,
              "initial_reset_memory":asdict(mem),
              "inputs":asdict(inp),"outputs":transition(initial,inp,mem)}
              for name,initial,inp,mem in examples]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--check",action="store_true")
    p.add_argument("--write",action="store_true")
    opt=p.parse_args()
    spec=json.loads(SPEC.read_text(encoding="utf-8"))
    if (spec["hardware_implemented"] or spec["fabrication_approval"] or
        spec["state_machine_only_not_board_evidence"] is not True):
        raise SystemExit("reference logic was wrongly promoted to real hardware")
    if spec.get("physical_ack_edge_memory_built") is not False:
        raise SystemExit("reset edge memory hardware claim cannot be accepted")
    expected=json.dumps(example_records(),ensure_ascii=False,indent=2)+"\n"
    if opt.write:OUT.write_text(expected,encoding="utf-8",newline="\n")
    elif opt.check and (not OUT.exists() or OUT.read_text(encoding="utf-8")!=expected):
        raise SystemExit("truth table stale: regenerate with --write")
    print("Hard-trip active at startup; held reset after fault cannot restart; hardware NOT designed.")
if __name__=="__main__":main()
