"""The D1 fabrication gate must fail closed on incomplete CAD evidence."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import d1_fabrication_gate as gate


def test_real_baseline_is_not_fabrication_approved():
    result = gate.build()
    assert result["release_approved"] is False
    assert result["status"] == "NOT_FOR_FAB"
    assert result["checks"]["golden_subnet_matches"] is True
    assert result["checks"]["cached_netlist_report_matches_live_native_export"] is True
    assert result["checks"]["native_editable_project_present"] is True
    assert result["counts"]["golden_references"] == 66
    assert result["counts"]["golden_logical_pins"] == 193
    assert set(result["counts"]["magnetics_missing_physical_pads"]) == {"CT","T1","T2","T3","T4"}
    assert result["counts"]["refs_with_placeholders"]
    assert result["counts"]["bom_rows_not_selected"]
    assert len(result["counts"]["real_hardware_bom_refs_not_in_golden"]) == 17
    # All 17 peripherals are drawn in the native schematic now, and the check
    # is keyed to the native export -- so this one check passes while the
    # board-level blockers (magnetics, placeholders, ERC, PCB) remain.
    assert result["counts"]["real_hardware_bom_refs_not_in_native_design"] == []
    assert len(result["counts"]["real_hardware_bom_refs_covered_by_native_design"]) == 17
    assert result["checks"]["all_required_real_hardware_bom_refs_in_native_design"] is True


def test_a_boolean_approved_is_not_evidence(tmp_path: Path):
    bad = tmp_path / "approval.json"
    bad.write_text('{"approved": true}', encoding="utf-8")
    res = gate._manual_gate(bad, ("reviewer", "revision", "report_path"))
    assert not res["passed"]
    # Even a complete label must reference a genuine file and be human-reviewed;
    # this gate checks required evidence fields, NOT their semantic authenticity.
    bad.write_text('{"approved": false, "reviewer":"X", "revision":"R", "report_path":"some.pdf"}', encoding="utf-8")
    assert not gate._manual_gate(bad, ("reviewer","revision","report_path"))["passed"]


def test_snapshot_regeneration_matches_committed_file():
    expected = json.loads(gate.OUT.read_text(encoding="utf-8"))
    assert expected == gate.build(), "run python tools/d1_fabrication_gate.py --write"


def test_release_cli_intentionally_returns_nonzero():
    assert gate.build()["blockers"]


def test_approved_string_without_on_disk_original_and_matching_digest_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    original = tmp_path / "erc-report.txt"
    original.write_text("ERC: reviewed (synthetic test)", encoding="utf-8")
    approval = tmp_path / "approval.json"
    base = {"approved": True, "reviewer": "test reviewer", "revision": "R1",
            "report_path": "erc-report.txt"}
    approval.write_text(json.dumps(base), encoding="utf-8")
    assert not gate._manual_gate(approval, ("report_path", "reviewer", "revision"))["passed"]
    base["report_sha256"] = hashlib.sha256(original.read_bytes()).hexdigest()
    approval.write_text(json.dumps(base), encoding="utf-8")
    assert gate._manual_gate(approval, ("report_path", "reviewer", "revision"))["passed"]
    original.write_text("tampered", encoding="utf-8")
    assert not gate._manual_gate(approval, ("report_path", "reviewer", "revision"))["passed"]
    base["report_path"] = "../outside.txt"
    approval.write_text(json.dumps(base), encoding="utf-8")
    assert not gate._manual_gate(approval, ("report_path", "reviewer", "revision"))["passed"]


def test_bom_only_real_components_cannot_be_hidden_by_outdated_coverage_json(monkeypatch):
    original = gate.bomcov.build

    def add_discovered_missing_part():
        result = original()
        result["required_bom_refs_missing_from_golden"].append({"ref": "NEW_CAD_REQUIREMENT"})
        return result

    monkeypatch.setattr(gate.bomcov, "build", add_discovered_missing_part)
    report = gate.build()
    assert "NEW_CAD_REQUIREMENT" in report["counts"]["real_hardware_bom_refs_not_in_golden"]
    assert report["release_approved"] is False


def test_stale_cached_netlist_cannot_stay_green_when_native_export_changes(monkeypatch):
    """Mutating a known U2 exposed pad must immediately block without --write."""
    original_read = gate._read

    def mutated(path):
        value = original_read(path)
        if path == gate.HW / "gen/netlist_export_raw.json":
            value = copy.deepcopy(value)
            assert value["value"]["refs"]["U2"]["11"] == "PGND"
            value["value"]["refs"]["U2"]["11"] = "VIN"
        return value

    monkeypatch.setattr(gate, "_read", mutated)
    report = gate.build()
    assert report["checks"]["cached_netlist_report_matches_live_native_export"] is False
    assert report["checks"]["golden_subnet_matches"] is False
    assert any(row["ref"] == "U2" for row in report["counts"]["live_native_netlist_missing_or_wrong"])
    assert report["release_approved"] is False
