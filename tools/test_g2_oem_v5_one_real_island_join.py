"""G2 REAL native EasyEDA C111.1 to C112.1 VCC12_S isolated-net ECO tests.

This trial physically reduced G2 disconnected objects 173 -> 172 in genuine
saved+reopened EDA. 72 OEM cap symbolic/footprint parity and 100A bus
remain unqualified. Only these real native DRC receipts can prove progress.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
G2=ROOT/"hardware/dcx_main/g2"
sys.path.insert(0,str(G2))
import connect_t530_oem_16x5_bipolar as B
import route_t530_oem_v5_one_real_island_join as V
import apply_t530_density_b_v2_native as A

def read(p):
    return json.loads(p.read_text(encoding="utf-8"))

def test_true_native_v5_two_islands_connected_with_source_provenance():
    d=read(V.DELTA)
    order=read(V.PLAN)
    assert V.TARGET.is_file() and V.TARGET!=B.TARGET
    assert d["previous_native_drc"]=={"Connection Error":173,"Netlist Error":1}
    assert d["actual_native_drc"]=={"Connection Error":172,"Netlist Error":1}
    assert d["source_sha256"]==V.sha(V.SOURCE)
    assert d["candidate_sha256"]==V.sha(V.TARGET)
    assert d["plan_sha256"]==V.sha(V.PLAN)
    assert not order["preflight_problems"]
    assert len(order["paths"])==1 and len(order["tracks"])==3
    assert order["paths"][0]["net"]=="VCC12_S"
    assert order["paths"][0]["start"]=="C111.1"
    assert order["paths"][0]["end"]=="C112.1"
    assert order["paths"][0]["verified_distinct_native_copper_islands"]

def test_real_eda_readback_and_drc_prove_actual_new_copper():
    actual=read(V.REOPEN)
    assert actual["ok"] is True
    value=actual["value"]
    assert len(value["components"])==77
    assert len(value["pads"])==443
    assert len(value["vias"])==90
    assert len(value["nets"])==65
    assert len(value["lines"])>=398
    order=V.plan()
    assert V.verify(value,order)==read(V.DELTA)["reopen"]
    drc=read(V.RAW)
    assert drc["ok"] is True
    assert A.R.categories(drc)=={"Connection Error":172,"Netlist Error":1}
    assert "Physical Error" not in A.R.categories(drc)

def test_standalone_copper_connects_both_real_different_islands():
    order=V.plan()
    assert order["schema"]=="D1_G2_REAL_NATIVE_V5_VCC12S_C111_C112_ONE_ISLAND_JOIN"
    assert order["high_current_nets_untouched"] is True
    assert order["gate_kelvin_and_mag_terminal_nets_untouched"] is True
    assert order["true_oem_72_schematic_components_present"] is False
    assert order["100A_power_copper_qualified"] is False
    assert order["manufacturing_approved"] is False

def test_reconnecting_existing_same_island_is_refused(monkeypatch):
    monkeypatch.setattr(V,"PAIRS",(("VCC12_S","C106","1","U4","7",68.0),))
    with pytest.raises(ValueError,match="SAME physical copper island"):
        V.plan()

def test_power_bus_routing_not_added_by_control_script(monkeypatch):
    monkeypatch.setattr(V,"PAIRS",(("PGND","QL","2","U2","1",68.0),))
    with pytest.raises(ValueError,match="Unsafe changes"):
        V.plan()
