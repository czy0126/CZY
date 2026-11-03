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
    assert result["checks"]["controller_rt_dt_roles_match_native_netlist"] is True
    assert result["checks"]["cached_netlist_report_matches_live_native_export"] is True
    assert result["checks"]["native_editable_project_present"] is True
    assert result["checks"]["independent_fault_shutdown_design_evidence"] is False
    assert "independent_fault_shutdown_design_evidence" in result["blockers"]
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


def test_protection_gate_refuses_missing_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "PROTECTION_APPROVAL", tmp_path / "missing.json")
    result = gate._protection_design_gate()
    assert result["passed"] is False
    assert "absent" in result["reason"]


def test_protection_gate_requires_all_flags_vendor_source_and_cad_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    approval = tmp_path / "hardware/dcx_main/protection_design_approved.json"
    approval.parent.mkdir(parents=True)
    monkeypatch.setattr(gate, "PROTECTION_APPROVAL", approval)
    sources = {
        "native_project_path": "hardware/dcx_main/dcx_main_board.eprj2",
        "fault_analysis_path": "docs/fault_review.md",
        "driver_shutdown_path": "docs/driver_review.md",
        "power_sequence_path": "docs/power_sequence.md",
        "vendor_soa_path": "docs/vendor_soa.md",
    }
    record = {
        "approved": True, "review_scope": "PRE_FAB_PROTECTION_DESIGN_ONLY",
        "reviewer": "reviewer", "revision": "R2",
        "simulated_fault_vin_v": [48, 50],
        "simulated_fault_load_a": 120,
    }
    record.update(sources)
    for field, rel in sources.items():
        file = tmp_path / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("synthetic-only file for test", encoding="utf-8")
        record[field[:-5] + "_sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    approval.write_text(json.dumps(record), encoding="utf-8")
    assert gate._protection_design_gate()["passed"] is False
    flags = (
        "independent_primary_and_all_eight_sr_inhibit_reviewed",
        "gate_disable_on_any_bias_loss_reviewed",
        "fault_latch_and_controlled_restart_reviewed",
        "startup_masking_and_fault_during_mask_reviewed",
        "physical_gate_driver_and_clamp_conflict_reviewed",
        "vendor_pulse_soa_and_winding_stress_reviewed",
    )
    for key in flags:
        record[key] = True
    record["simulated_fault_vin_v"] = [48]
    approval.write_text(json.dumps(record), encoding="utf-8")
    assert gate._protection_design_gate()["passed"] is False
    record["simulated_fault_vin_v"] = [48, 50]
    record["review_scope"] = "HARDWARE_RATED"
    approval.write_text(json.dumps(record), encoding="utf-8")
    assert gate._protection_design_gate()["passed"] is False
    record["review_scope"] = "PRE_FAB_PROTECTION_DESIGN_ONLY"
    approval.write_text(json.dumps(record), encoding="utf-8")
    assert gate._protection_design_gate()["passed"] is True
    # Edited CAD invalidates source hash; even a synthetic approval fails.
    (tmp_path / sources["native_project_path"]).write_bytes(b"modified CAD")
    assert gate._protection_design_gate()["passed"] is False


def test_wrong_rt_dt_candidate_mapping_blocks_controller_gate(monkeypatch):
    import d1_functional_net_audit as functional
    original=functional.compare
    def mutate(*args, **kwargs):
        result=original(*args,**kwargs)
        return {**result,"passed":False,"problems":["injected wrong RT candidate"]}
    monkeypatch.setattr(gate.functional_audit,"compare",mutate)
    report=gate.build()
    assert report["release_approved"] is False
    assert not report["checks"]["controller_rt_dt_roles_match_native_netlist"]
    assert "controller_rt_dt_roles_match_native_netlist" in report["blockers"]
    assert report["counts"]["functional_control_net_mismatches"]==["injected wrong RT candidate"]
