"""PROT03 decision: never promote a killed control to a complete pair."""
from copy import deepcopy
import json
import pytest
import prot03_50v_evidence_decision as x

def test_all_latest_evidence_and_future_actions_derive_from_committed_records():
    record=x.build()
    assert json.loads(x.OUT.read_text(encoding="utf-8"))==record
    assert record["A_2fF"]["base_full_320us"] and record["A_2fF"]["candidate_full_320us"]
    assert record["A_2fF"]["trip_after_base_ipri_peak_us"]>0
    assert record["A_2fF"]["ipri_peak_a_control"]==record["A_2fF"]["ipri_peak_a_candidate"]
    assert record["A_2fF"]["sr_peak_a_control"]==record["A_2fF"]["sr_peak_a_candidate"]
    assert record["A_2fF"]["sr_total_i2t_reduction_percent"]<1.0
    assert record["B_previous_1fF"]["control_end_us"]==pytest.approx(254.980482,abs=.001)
    assert record["B_2fF"]["control_end_us"]==pytest.approx(264.514946,abs=.001)
    assert record["B_5fF"]["control_end_us"]==pytest.approx(235.889681,abs=.001)
    assert record["B_cshunt_nonmonotone"]
    assert all(not record[k]["control_full_320us"] for k in ("B_previous_1fF","B_2fF","B_5fF"))
    assert record["numeric_solver_next_step"]["status"]=="UNRUN"
    assert record["numeric_solver_next_step"]["model"].endswith("sr_timing_v3_4_age_rail.lib")
    assert not record["manufacture_approved"] and not record["hardware_gate_passed"]

def test_completed_b5f_cannot_be_falsely_presented_as_a_safety_result():
    b5=deepcopy(json.loads(x.B_5F.read_text(encoding="utf-8")))
    b5["coverage"]["base_reached_saved_stop"]=True
    with pytest.raises(ValueError,match="new matched complete B result"):
        x.build(b5=b5)

def test_changed_A_peak_reduction_needs_new_engineering_review():
    a=deepcopy(json.loads(x.A.read_text(encoding="utf-8")))
    a["results"]["relief"]["sr_forward_peak_rel"]=-.5
    with pytest.raises(ValueError,match="A peak relief changed"):
        x.build(a=a)

def test_that_a_control_got_beyond_264us_does_not_mislabel_it_320us():
    b2=deepcopy(json.loads(x.B_2F_DIAG.read_text(encoding="utf-8")))
    b2["results"]["variant_t_last_us"]=310
    z=x.build(b2=b2)
    assert not z["B_2fF"]["completed_matched_pair"]
    assert not z["hardware_gate_passed"]
