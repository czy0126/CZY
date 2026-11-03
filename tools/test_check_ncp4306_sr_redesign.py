"""NCP4306 pinout and math are data-backed but NEVER hardware approval."""
from copy import deepcopy
import json
import pytest
import check_ncp4306_sr_redesign as m
def test_eight_real_native_mos_connections():
    a=m.verify()
    assert a["maps_match_current_native"],a["errors"]
    assert not a["fabrication_approved"]
    assert not a["actual_eight_controller_swap_done"]
    assert len(json.loads(m.SPEC.read_text(encoding="utf-8"))["channels"])==8
def test_wrong_mos_gate_is_not_hidden():
    n=json.loads(m.NATIVE.read_text(encoding="utf-8"))["value"]["refs"]
    n=deepcopy(n)
    n["SR3B"]["4"]="BAD_GATE"
    a=m.verify(native=n)
    assert not a["maps_match_current_native"]
def test_duplicate_channel_or_forged_approval_is_blocked():
    cfg=json.loads(m.SPEC.read_text(encoding="utf-8"))
    cfg["channels"][0]["new_controller"]="U8"
    assert not m.verify(candidate=cfg)["maps_match_current_native"]
    cfg=json.loads(m.SPEC.read_text(encoding="utf-8"))
    cfg["fabrication_release"]=True
    assert not m.verify(candidate=cfg)["maps_match_current_native"]
def test_trip_rising_edge_includes_slowest_disabling_threshold_blank_and_pd():
    assert m.edge_us(8,100)>m.edge_us(12,100)
    x=m.calculate()
    assert len(x["cases"])==12
    assert x["gate_driver_sr_count"]==8
    assert all(z["max_pd_and_blanking_us"]==0.0965 for z in x["cases"])
    assert not x["release_approved"]
    row=next(z for z in x["cases"] if z["vcc_v"]==8 and z["external_pin_cap_pf"]==100)
    assert row["screened_pin_to_driver_off_us"]>0.4
    assert row["additional_comparator_latch_gate_discharge_us"] is None
    assert json.loads(m.OUT.read_text(encoding="utf-8"))==x
    assert json.loads(m.REPORT.read_text(encoding="utf-8"))==m.verify()
    with pytest.raises(ValueError,match="cannot reach"):m.edge_us(2.3,100)
