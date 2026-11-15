"""Regression tests for compact circuit-first scope and inherited KiCad ERC."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import d1_compact_scope_gate as g

def test_compact_docs_no_unrelated_architecture():
    data=g.validate()
    assert data["tracked_unrelated_paths"]==0
    assert not data["C0_integrated_finished"]
    assert not data["power_on_release"]

def test_banned_tracked_paths():
    assert g.blocked_path("design/v3/fullbrick_embedded_cooling/foo.scad")
    assert g.blocked_path("docs/agent/FULLBRICK_V1_ACCEPTANCE.md")
    assert not g.blocked_path("hardware/dcx_main/g2/compact_g0_circuit_reference_NOT_FOR_FAB/sch.pdf")

def test_banned_rated_goals_in_project_spec():
    assert g.check_doc("目标 1800 A 已加入")
    assert g.check_doc("3.6 kW full brick")
    assert g.check_doc("Fullbrick_embedded_cooling")
    assert not g.check_doc("目标200A→400A→600A")

def test_schematic_real_source_hash_and_erc():
    assert g.sha(g.SCH)==g.EXPECTED_SCH_SHA
    data=g.validate()
    assert data["native_V5_ERC_violations"]==0
    assert len(data["native_V5_ignored_ERC_types"])==4
    assert data["four_reference_sheets_are_not_connected_as_one_circuit"]
