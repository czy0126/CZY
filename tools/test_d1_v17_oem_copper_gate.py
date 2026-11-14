"""Regression on three real, SHA-bound saved V17 OEM mainboard candidates."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import d1_v17_oem_copper_gate as mod

def test_integrated_oem_and_real_power_routing_evidence():
    d=mod.audit()
    assert d["status"]=="WIP_NOT_FOR_FAB"
    assert [p["unconnected"] for p in d["stages"]]==[9,8,7]
    assert [p["rule_violations"] for p in d["stages"]]==[0,0,0]
    assert d["replaced_oem_footprints"]==72
    assert d["rotated_180_for_net_polarity"]==36
    assert d["remaining_missing_magnetics"]==["CT","T1","T2","T3","T4"]
    assert d["fab_release"] is False
    assert all(p["ignored_drc_checks"] for p in d["stages"])

def test_input_and_sw_partial_power_connections_are_real():
    d=mod.audit()
    a,b,c=d["stages"]
    assert (a["unconnected_by_net"]["VIN_P"],b["unconnected_by_net"]["VIN_P"],c["unconnected_by_net"]["VIN_P"])==(2,1,1)
    assert (a["unconnected_by_net"]["SW"],b["unconnected_by_net"]["SW"],c["unconnected_by_net"]["SW"])==(3,3,2)

def test_report_is_deterministic():
    assert mod.audit()==mod.audit()
    assert mod.main(["--check"])==0
