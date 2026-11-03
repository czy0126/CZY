"""All critical invalid conditions must always force BOTH primary and all SR gate permits off."""
from dataclasses import replace
import itertools
import json
import two_tier_fault_logic as m

def test_all_input_combinations_have_no_bypassed_hard_trip_or_bias_loss():
    names=("hard_trip","fast_trip","armed","primary_bias_good","secondary_bias_good",
           "ct_signal_valid","comparator_bias_good","start_sequence_ready",
           "operator_run","reset_ack","all_ten_gates_off")
    for bits in itertools.product((False,True),repeat=len(names)):
        obj=m.Inputs(**dict(zip(names,bits)))
        for prev in (False,True):
            r=m.transition(prev,obj)
            assert r["primary_en_permit"]==r["secondary_sr_permit"]
            if obj.hard_trip or not all((obj.primary_bias_good,obj.secondary_bias_good,
                                         obj.ct_signal_valid,obj.comparator_bias_good)):
                assert r["all_ten_gate_disable"] and r["latched_off_next"]
                assert not r["primary_en_permit"]
            if r["reset_accepted"]:
                assert prev and obj.all_ten_gates_off and obj.start_sequence_ready
                assert not r["fault_effective"]
def test_fast_trip_only_can_be_masked_but_hard_never_is():
    safe=dict(primary_bias_good=True,secondary_bias_good=True,ct_signal_valid=True,
              comparator_bias_good=True,start_sequence_ready=True,operator_run=True,
              all_ten_gates_off=True)
    assert m.transition(False,m.Inputs(**safe,fast_trip=True,armed=False))["primary_en_permit"]
    assert not m.transition(False,m.Inputs(**safe,fast_trip=True,armed=True))["primary_en_permit"]
    assert not m.transition(False,m.Inputs(**safe,hard_trip=True,armed=False,reset_ack=True))["primary_en_permit"]
def test_rearm_is_explicit_and_powerup_initially_latched():
    safe=dict(primary_bias_good=True,secondary_bias_good=True,ct_signal_valid=True,
              comparator_bias_good=True,start_sequence_ready=True,operator_run=True,
              all_ten_gates_off=True)
    assert m.transition(True,m.Inputs(**safe))["latched_off_next"]
    assert m.transition(True,m.Inputs(**safe,reset_ack=True))["primary_en_permit"]
    assert json.loads(m.OUT.read_text(encoding="utf-8"))==m.example_records()
    assert not m.example_records()["protection_approved"]
