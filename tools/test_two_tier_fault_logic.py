"""Exhaustive fault gating + real reset edge/release SEQUENCE in reference logic."""
import itertools
import json
import two_tier_fault_logic as m

def healthy_inputs(**override):
    base=dict(primary_bias_good=True,secondary_bias_good=True,
              ct_signal_valid=True,comparator_bias_good=True,
              start_sequence_ready=True,operator_run=True,all_ten_gates_off=True)
    return m.Inputs(**{**base,**override})

def test_all_input_combinations_no_bypass_and_held_reset_never_clears():
    names=("hard_trip","fast_trip","armed","primary_bias_good","secondary_bias_good",
           "ct_signal_valid","comparator_bias_good","start_sequence_ready",
           "operator_run","reset_ack","all_ten_gates_off")
    # 2^11 inputs x 2 prior latch states x 4 stored reset qualifications
    for bits in itertools.product((False,True),repeat=len(names)):
        i=m.Inputs(**dict(zip(names,bits)))
        for prev in (False,True):
            for prev_high,low_seen in itertools.product((False,True),repeat=2):
                mem=m.ResetMemory(prev_high,low_seen)
                r=m.transition(prev,i,mem)
                assert r["primary_en_permit"]==r["secondary_sr_permit"]
                if i.hard_trip or not all((i.primary_bias_good,i.secondary_bias_good,
                                           i.ct_signal_valid,i.comparator_bias_good)):
                    assert r["all_ten_gate_disable"] and r["latched_off_next"]
                    assert not r["primary_en_permit"]
                    assert not r["reset_accepted"]
                if r["reset_accepted"]:
                    assert prev and low_seen and not prev_high and i.reset_ack
                    assert i.all_ten_gates_off and i.start_sequence_ready
                    assert not r["fault_effective"]
                if i.reset_ack and prev_high:
                    assert not r["reset_accepted"]
                if not i.reset_ack and not prev:
                    assert not r["reset_accepted"]

def test_fast_trip_masking_is_not_hard_trip_masking():
    assert m.transition(False,healthy_inputs(fast_trip=True,armed=False))["primary_en_permit"]
    assert not m.transition(False,healthy_inputs(fast_trip=True,armed=True))["primary_en_permit"]
    assert not m.transition(False,healthy_inputs(hard_trip=True,armed=False,reset_ack=True))["primary_en_permit"]

def test_power_recovery_with_stuck_high_reset_does_not_spontaneously_start():
    mem=m.ResetMemory()
    trip=m.transition(True,healthy_inputs(primary_bias_good=False,reset_ack=True),mem)
    assert trip["latched_off_next"]
    mem=m.ResetMemory(**trip["reset_memory_next"])
    for _ in range(10):
        r=m.transition(True,healthy_inputs(reset_ack=True),mem)
        assert r["latched_off_next"] and not r["reset_accepted"]
        mem=m.ResetMemory(**r["reset_memory_next"])
    # Releasing ACK while all rails healthy arms one fresh edge.
    release=m.transition(True,healthy_inputs(reset_ack=False),mem)
    assert release["latched_off_next"]
    assert release["reset_memory_next"]["ack_low_seen_while_healthy"]
    mem=m.ResetMemory(**release["reset_memory_next"])
    clear=m.transition(True,healthy_inputs(reset_ack=True),mem)
    assert clear["reset_accepted"]
    assert not clear["latched_off_next"]
    assert clear["primary_en_permit"] and clear["secondary_sr_permit"]

def test_ack_pressed_during_fault_requires_new_release_after_fault_clears():
    healthy=healthy_inputs(reset_ack=False)
    ready=m.transition(True,healthy)
    mem=m.ResetMemory(**ready["reset_memory_next"])
    trip=m.transition(True,healthy_inputs(hard_trip=True,reset_ack=True),mem)
    assert trip["latched_off_next"] and not trip["reset_accepted"]
    assert not trip["reset_memory_next"]["ack_low_seen_while_healthy"]
    mem=m.ResetMemory(**trip["reset_memory_next"])
    recovered=m.transition(True,healthy_inputs(reset_ack=True),mem)
    assert recovered["latched_off_next"] and not recovered["reset_accepted"]
    assert not recovered["primary_en_permit"]

def test_reset_needs_all_ten_gates_off_and_no_hard_trip():
    released=m.ResetMemory(False,True)
    assert not m.transition(True,healthy_inputs(all_ten_gates_off=False,reset_ack=True),released)["reset_accepted"]
    assert not m.transition(True,healthy_inputs(hard_trip=True,reset_ack=True),released)["reset_accepted"]
    assert not m.transition(True,healthy_inputs(secondary_bias_good=False,reset_ack=True),released)["reset_accepted"]

def test_truth_table_and_unimplemented_flags_match_generator():
    assert json.loads(m.OUT.read_text(encoding="utf-8"))==m.example_records()
    table=m.example_records()
    assert len(table["cases"])==14
    assert not table["protection_approved"]
    assert not table["physical_ack_edge_memory_has_been_built"]
