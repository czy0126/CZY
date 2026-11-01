"""BOM-referenced control peripherals must not disappear from the CAD golden basis."""
from __future__ import annotations
import json
import d1_bom_coverage as bc


def test_expand_real_bom_ranges():
    assert bc.refs("U3-U6") == ["U3","U4","U5","U6"]
    assert bc.refs("R7 R8 R9 R10") == ["R7","R8","R9","R10"]
    assert bc.refs("SR1A-SR4B") == [f"SR{i}{s}" for i in range(1,5) for s in "AB"]


def test_detect_missing_decouplers_and_enable_logic():
    result = bc.build()
    missing = {x["ref"] for x in result["required_bom_refs_missing_from_golden"]}
    expected = {"R7","R8","R9","R10","C13"} | {f"C{i}" for i in range(101,113)}
    assert missing == expected
    assert result["golden_ref_count"] == 66
    assert {x["ref"] for x in result["external_interfaces_not_in_golden"]} == {"PS1"}
    assert result["not_in_bom_golden_refs"] == []


def test_bom_coverage_snapshot_matches_generator():
    assert json.loads(bc.OUT.read_text(encoding="utf-8")) == bc.build()
