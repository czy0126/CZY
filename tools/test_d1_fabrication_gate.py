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


def _native_ref_nets():
    exported = gate._read(gate.HW / "gen/netlist_export_raw.json")
    return copy.deepcopy(exported["value"]["refs"])


def test_primary_driver_is_structurally_blocked_by_always_on_r8():
    result = gate._primary_en_default_low_precheck(_native_ref_nets())
    assert result["passed"] is False
    assert any("R8" in p for p in result["problems"])


def test_driver_static_preflight_can_accept_removed_constant_pullup_only():
    nets = _native_ref_nets()
    del nets["R8"]
    result = gate._primary_en_default_low_precheck(nets)
    assert result["passed"]
    assert result["problems"] == []
    # The check is intentionally limited; it does not prove protection.
    assert "no proof" in result["limited_scope"]


def test_reversing_r8_pins_or_renaming_resistor_cannot_hide_run_pullup():
    for mode in ("reverse", "rename", "duplicate"):
        nets = _native_ref_nets()
        if mode == "reverse":
            nets["R8"] = {"1": "RUN", "2": "VCC12"}
        elif mode == "rename":
            nets["R88"] = nets.pop("R8")
        else:
            nets["R88"] = nets.pop("R8")
            nets["R89"] = {"1": "RUN", "2": "VCC12"}
        result = gate._primary_en_default_low_precheck(nets)
        assert not result["passed"]
        assert any("unconditional resistor pullup" in p for p in result["problems"])


def test_no_primary_en_pin_or_missing_r7_passive_pulldown_is_a_veto():
    for case in ("missing_u2", "en_short_vcc", "missing_r7", "wrong_r7"):
        nets = _native_ref_nets()
        nets.pop("R8")
        if case == "missing_u2":
            del nets["U2"]["6"]
        elif case == "en_short_vcc":
            nets["U2"]["6"] = "VCC12"
        elif case == "missing_r7":
            del nets["R7"]
        else:
            nets["R7"]["2"] = "VCC12"
        assert not gate._primary_en_default_low_precheck(nets)["passed"]


def test_forged_protection_approval_cannot_override_live_r8_hazard(monkeypatch):
    monkeypatch.setattr(gate, "_protection_design_gate", lambda: {
        "passed": True, "reason": "synthetic approval for negative test"})
    report = gate.build()
    assert report["checks"]["independent_fault_shutdown_design_evidence"] is False
    assert not report["release_approved"]
    assert "independent_fault_shutdown_design_evidence" in report["blockers"]


def test_fabrication_gate_rejects_edited_cache_physical_pad_approval(monkeypatch):
    original_read = gate._read

    def forged_cache(path):
        document = original_read(path)
        if path == gate.CONTRACT:
            document = copy.deepcopy(document)
            for sym in document["symbols"]:
                sym["physical_pad_map_verified"] = True
                for i, pin in enumerate(sym["pins"], 1):
                    pin["physical_pad"] = str(i)
        return document

    monkeypatch.setattr(gate, "_read", forged_cache)
    import pytest
    with pytest.raises(ValueError, match="differs from live SPICE/native source"):
        gate.build()


def test_native_mpn_readback_and_r8_inclusion_are_explicit_fab_blockers():
    audit = gate._native_mpn_and_r8_precheck()
    assert audit["snapshot_matches_live_capture"] is True
    assert audit["manufacturer_target_conflicts"] == 39
    assert audit["r8_in_bom"] is True
    assert audit["r8_in_pcb"] is True
    assert audit["passed"] is False
    result = gate.build()
    assert result["checks"]["native_manufacturer_ids_and_r8_dnp_verified"] is False
    assert "native_manufacturer_ids_and_r8_dnp_verified" in result["blockers"]
    assert result["counts"]["native_mpn_target_conflicts"] == 39


def test_native_mpn_precheck_rejects_good_looking_but_unrecorded_readback(monkeypatch):
    # A fabricated in-memory report cannot supersede the actual native
    # inventory and its committed, independently regenerable audit.
    new_report = gate.native_bom.audit().copy()
    new_report["manufacturer_target_conflicts"] = 0
    new_report["original_r8_in_bom"] = False
    new_report["original_r8_in_pcb"] = False
    monkeypatch.setattr(gate.native_bom, "audit", lambda: new_report)
    check = gate._native_mpn_and_r8_precheck()
    assert check["snapshot_matches_live_capture"] is False
    assert check["passed"] is False


def test_empty_coverage_cannot_make_mpn_stopline_appear_green(monkeypatch):
    # Regression: after native device swaps it is not enough to delete the old
    # MPNs from the known-facts registry and call the resulting zero errors a pass.
    report = gate.native_bom.audit().copy()
    report["manufacturer_target_conflicts"] = 0
    report["known_mpn_and_target_rows"] = 0
    report["original_r8_in_bom"] = False
    report["original_r8_in_pcb"] = False
    monkeypatch.setattr(gate.native_bom, "audit", lambda: report)
    monkeypatch.setattr(gate, "_read", lambda path: report
                        if path == gate.native_bom.OUTPUT
                        else json.loads(path.read_text(encoding="utf-8")))
    check = gate._native_mpn_and_r8_precheck()
    assert check["snapshot_matches_live_capture"] is True
    assert check["manufacturer_target_conflicts"] == 0
    assert check["known_mpn_and_target_rows"] == 0
    assert check["passed"] is False


def test_real_double_dnp_r8_is_unpopulated_even_if_schematic_netlist_retains_ref():
    nets = _native_ref_nets()
    assert gate._primary_en_default_low_precheck(nets)["passed"] is False
    p = gate._primary_en_default_low_precheck(nets, r8_real_dnp=True)
    assert p["passed"] is True
    assert not p["problems"]
    assert "no proof" in p["limited_scope"]


def test_r8_dnp_never_hides_second_renamed_live_run_pullup():
    nets = _native_ref_nets()
    nets["R88"] = {"1": "RUN", "2": "VCC12"}
    p = gate._primary_en_default_low_precheck(nets, r8_real_dnp=True)
    assert p["passed"] is False
    assert any("R88" in s for s in p["problems"])


def test_partial_or_unmatched_r8_native_capture_cannot_bypass_static_run_check(
        monkeypatch):
    # Synthetic scenarios are not new evidence; cover branch wiring only.
    original = gate._native_mpn_and_r8_precheck()
    assert original["r8_in_bom"] is True and original["r8_in_pcb"] is True
    for state in (
            {"snapshot_matches_live_capture": False,
             "r8_in_bom": False, "r8_in_pcb": False},
            {"snapshot_matches_live_capture": True,
             "r8_in_bom": False, "r8_in_pcb": True},
            {"snapshot_matches_live_capture": True,
             "r8_in_bom": True, "r8_in_pcb": False},
    ):
        check = {**original, **state, "passed": False}
        monkeypatch.setattr(gate, "_native_mpn_and_r8_precheck",
                            lambda check=check: check)
        result = gate.build()
        assert result["checks"]["independent_fault_shutdown_design_evidence"] is False
        assert result["release_approved"] is False
        assert result["status"] == "NOT_FOR_FAB"


def test_native_r8_double_dnp_keeps_independent_protection_gate_blocked(
        monkeypatch):
    original = gate._native_mpn_and_r8_precheck()
    two_fields_dnp = {**original, "snapshot_matches_live_capture": True,
                      "r8_in_bom": False, "r8_in_pcb": False,
                      "manufacturer_target_conflicts": 38, "passed": False}
    monkeypatch.setattr(gate, "_native_mpn_and_r8_precheck",
                        lambda: two_fields_dnp)
    result = gate.build()
    assert result["status"] == "NOT_FOR_FAB"
    assert result["checks"]["native_manufacturer_ids_and_r8_dnp_verified"] is False
    assert result["checks"]["independent_fault_shutdown_design_evidence"] is False
    assert "independent_fault_shutdown_design_evidence" in result["blockers"]



def test_current_design_signoff_requires_two_rail_pre_fab_review(tmp_path, monkeypatch):
    """A full Gerber/BOM/DRC/stackup package must not bypass 100 A copper design."""
    import hashlib
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    evidence = tmp_path / "hardware/dcx_main/fabrication_approval.json"
    evidence.parent.mkdir(parents=True)
    doc = {"approved": True, "reviewer": "fixture-only", "revision": "fixture-only"}
    for field in gate.FAB_EVIDENCE:
        if not field.endswith("_path"):
            continue
        target = tmp_path / "synthetic_evidence" / (field + ".txt")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("not an actual D1 fabrication approval", encoding="utf-8")
        doc[field] = target.relative_to(tmp_path).as_posix()
        doc[field[:-5] + "_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    key = "output_two_rail_current_thermal_review_path"
    assert key in gate.FAB_EVIDENCE
    original = doc.pop(key)
    doc.pop(key[:-5] + "_sha256")
    evidence.write_text(json.dumps(doc), encoding="utf-8")
    blocked = gate._manual_gate(evidence, gate.FAB_EVIDENCE)
    assert blocked["passed"] is False
    doc[key] = original
    target = tmp_path / original
    doc[key[:-5] + "_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    evidence.write_text(json.dumps(doc), encoding="utf-8")
    # Metadata/hashes are only one pre-fab evidence contract, not physical validation.
    assert gate._manual_gate(evidence, gate.FAB_EVIDENCE)["passed"] is True
