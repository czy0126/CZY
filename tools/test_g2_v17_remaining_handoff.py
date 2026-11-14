"""Machine-verifiable remaining native DRC and engineering handoff."""
import hashlib
import json
from collections import Counter

import pytest
import g2_v17_remaining_powercell_handoff as report


def test_remaining_unconnected_are_grounded_in_current_KiCad_drc():
    d=report.generate()
    assert d["native_board_sha256"]==report.sha(report.PCB)
    assert d["native_drc_sha256"]==report.sha(report.DRC)
    assert d["native_meta_sha256"]==report.sha(report.META)
    assert d["status"]=="SOURCE_LOCKED_NATIVE_DRC_REMAINING_ISSUES_NOT_FOR_FAB"
    assert d["unconnected_total"]==13
    assert d["by_net"]=={
        "GH":1,"GH_DRV":1,"HB":1,"OC":1,"SW":7,"VIN_P":2}
    assert all(len(d["net_endpoints"][n])==num
               for n,num in d["by_net"].items())
    assert d["remaining_violation_types"]=={"clearance":2}
    assert len(d["remaining_native_U2_violations"])==2
    assert all("U2" in " ".join(x["items"]) for x in d["remaining_native_U2_violations"])
    assert not d["fab_release"]
    assert not d["whole_board_drc_green"]
    assert not d["simulated_power_electronics_verified"]


def test_hot_loops_and_fault_sense_have_explicit_manufacturing_gates():
    d=json.loads(report.OUT.read_text("utf8"))
    groups={x["group"]:x for x in d["groups"]}
    assert set(groups)=={
        "primary_switch_node","primary_input_path",
        "high_side_gate_bootstrap","fault_sense_control"}
    assert groups["primary_switch_node"]["nets"]==["SW"]
    assert groups["primary_input_path"]["nets"]==["VIN_P"]
    assert groups["high_side_gate_bootstrap"]["nets"]==["GH","GH_DRV","HB"]
    assert groups["fault_sense_control"]["nets"]==["OC"]
    assert all(row["must_validate"] and row["do_not"] and row["priority"]
               for row in groups.values())
    assert any("100A" in x for x in d["additional_hard_gates"])
    assert any("DOT" in x for x in d["additional_hard_gates"])


def test_drc_count_regression_cannot_be_silenced(monkeypatch):
    monkeypatch.setattr(report,"EXPECTED",{"SW":0})
    with pytest.raises(ValueError,match="drift"):
        report.generate()
