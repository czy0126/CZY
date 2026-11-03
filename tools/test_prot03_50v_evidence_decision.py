"""A complete simulation pair is not equivalent to a good peak protector."""
import json
from copy import deepcopy
import pytest
import prot03_50v_evidence_decision as x

def test_snapshot_is_derived_from_real_committed_records():
    z=x.build()
    assert json.loads(x.OUT.read_text(encoding="utf-8"))==z
    assert z["A_2fF"]["base_full_320us"] and z["A_2fF"]["candidate_full_320us"]
    assert z["A_2fF"]["pre_fault_vout_delta_mv"]==0.0
    assert z["A_2fF"]["trip_after_base_ipri_peak_us"]>0
    assert z["A_2fF"]["ipri_peak_a_control"]==z["A_2fF"]["ipri_peak_a_candidate"]
    assert z["A_2fF"]["sr_peak_a_control"]==z["A_2fF"]["sr_peak_a_candidate"]
    assert z["A_2fF"]["sr_total_i2t_reduction_percent"]<1.0
    assert not z["B_previous_1fF"]["base_full_320us"]
    assert z["B_previous_1fF"]["candidate_full_320us"]
    assert z["B_2fF"]["status"]=="UNAVAILABLE_NO_COMMITTED_2FF_B_RECORD"
    assert not z["hardware_gate_passed"] and not z["manufacture_approved"]

def test_overstated_or_changed_A_peak_relief_refused():
    a=json.loads(x.A.read_text(encoding="utf-8"))
    a=deepcopy(a)
    a["results"]["relief"]["sr_forward_peak_rel"]=-0.5
    with pytest.raises(ValueError,match="A has changed"):
        x.build(a=a)
def test_sweep_B_can_be_simulation_paired_but_never_hardware_approved():
    b=json.loads(x.B_OLD.read_text(encoding="utf-8"))
    b=deepcopy(b)
    b["coverage"].update(base_reached_saved_stop=True,candidate_reached_saved_stop=True)
    b["checks"].update(the_pre_fault_operating_points_match_within_1_mv=True,
                       the_declared_window_is_fully_covered=True)
    z=x.build(b_2f_override=b)
    assert z["B_2fF"]["status"]=="MATCHED_FULL_WINDOW_SIMULATED_ONLY"
    assert not z["hardware_gate_passed"] and not z["manufacture_approved"]
