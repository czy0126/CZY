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


def test_the_native_gap_is_the_golden_gap_minus_what_the_schematic_contains():
    """The golden list is deck-derived; the native export is the real evidence."""
    result = bc.build()
    golden = {x["ref"] for x in result["required_bom_refs_missing_from_golden"]}
    native = {x["ref"] for x in result["required_bom_refs_missing_from_native_design"]}
    covered = set(result["covered_by_native_design"])
    assert covered | native == golden
    assert not covered & native


def test_a_ref_in_the_native_export_stops_being_reported_missing(tmp_path, monkeypatch):
    """Proves the gate check can pass: it was unpassable when keyed to golden."""
    export = tmp_path / "native.json"
    export.write_text(json.dumps({"value": {"refs": {"R7": {"1": "EN", "2": "PGND"}}}}),
                      encoding="utf-8")
    monkeypatch.setattr(bc, "NATIVE", export)
    result = bc.build()
    assert "R7" in result["covered_by_native_design"]
    assert "R7" not in {x["ref"] for x in result["required_bom_refs_missing_from_native_design"]}
    assert "R7" in {x["ref"] for x in result["required_bom_refs_missing_from_golden"]}
