"""True OEM-native V2 connectivity-island diagnosis and fail-closed ECO preflight.

Does NOT claim that the actual EasyEDA DRC 173/1 has been reduced, or that
the aborted GUI V4 candidate was saved or validated.
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
import g2_oem_net_islands as G
import route_t530_oem_v4_real_island_join as V


def test_real_native_baseline_sha_and_all_control_islands():
    result=G.report()
    assert result["native_drc"]=={"Connection Error":173,"Netlist Error":1}
    assert result["source_native_16x5_eprj2_sha256"]==hashlib.sha256(
        G.BASE_BOARD.read_bytes()).hexdigest()
    assert result["source_native_readback_canonical_lf_sha256"]==G.sha_lf(G.BASE)
    assert result["100A_or_fabrication_approved"] is False
    assert result["independent_topological_screen_not_a_DRC_substitute"]
    groups=result["per_control_net"]
    assert groups["VCC12_S"]["island_count_geometry_screen"]==6
    assert groups["OCM"]["island_count_geometry_screen"]==3
    assert groups["OC"]["island_count_geometry_screen"]==2
    assert groups["OCD"]["island_count_geometry_screen"]==2
    assert groups["REG1"]["island_count_geometry_screen"]==2
    assert groups["GD1"]["island_count_geometry_screen"]==3


def test_corresponding_native_copper_nodes_physically_share_an_island():
    groups=G.report()["per_control_net"]
    vcc=groups["VCC12_S"]["islands"]
    assert any({"C105.1","U3.7"}.issubset(x["pads"]) for x in vcc)
    assert any({"C106.1","U4.7"}.issubset(x["pads"]) for x in vcc)
    assert any({"C109.1","C110.1","C111.1"}.issubset(x["pads"]) for x in vcc)
    assert any(x["pads"]==["C112.1"] for x in vcc)
    oc=groups["OC"]["islands"]
    assert any({"R16.2","R17.1","U1.3"}.issubset(x["pads"]) for x in oc)
    assert any(x["pads"]==["C12.1"] for x in oc)


def test_source_island_routes_v4_connect_two_DISTINCT_native_islands_only():
    plan=V.plan()
    assert plan["schema"]=="D1_G2_REAL_NATIVE_V4_DISTINCT_ISLAND_JOINS_2_LINKS"
    assert not plan["preflight_problems"]
    assert len(plan["tracks"])==6 and len(plan["paths"])==2
    assert {(x["net"],x["start"],x["end"]) for x in plan["paths"]}=={
        ("VCC12_S","C111.1","C112.1"),("OCM","R17.2","C11.2")}
    assert all(x["verified_distinct_native_copper_islands"] for x in plan["paths"])
    assert plan["100A_power_copper_qualified"] is False
    assert plan["manufacturing_approved"] is False
    assert all(x["net"] not in {"VOUT","PGND","VIN_P","SW"}
               for x in plan["tracks"])


def test_repeating_a_same_island_route_is_rejected_before_GUI(monkeypatch):
    monkeypatch.setattr(V,"PAIRS",(
        ("VCC12_S","C105","1","U3","7",68.0),
        ("OCM","R17","2","C11","2",63.4),
    ))
    with pytest.raises(ValueError,match="SAME physical copper island"):
        V.plan()


def test_repeating_a_fab_power_route_is_prohibited(monkeypatch):
    monkeypatch.setattr(V,"PAIRS",(
        ("PGND","QL","2","U2","1",68.0),
        ("OCM","R17","2","C11","2",63.4),
    ))
    with pytest.raises(ValueError,match="Unsafe changes"):
        V.plan()


def test_provenance_error_blocks_consuming_modified_parent(monkeypatch):
    monkeypatch.setattr(G,"sha",lambda *_:"0"*64)
    with pytest.raises(ValueError,match="differs from verified"):
        G.report()


def test_saved_island_report_is_stable_and_never_approves_fab():
    r=G.report()
    assert G.REPORT.read_text(encoding="utf-8")==json.dumps(
        r,ensure_ascii=False,indent=2)+"\n"
    assert all(x["native_link_routed_and_DRC_improved"] is False
               for x in r["physical_island_candidates_not_native_DRC_fixes"])
    assert r["true_72_component_instances_and_schematic_parity"] is False
