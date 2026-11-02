"""Missing approval, spoofed evidence and SS threshold cannot clear F01."""
from __future__ import annotations

import hashlib
import json
import pytest
import hotfault_engineering_gate as gate
import d1_unclosed_risks as risk


def test_no_missing_supplier_or_simulated_evidence_is_approved():
    d = gate.build()
    assert d["status"] == "HOT_FAULT_SIMULATION_NOT_VERIFIED"
    assert {row["case"] for row in d["cases"]} == {"48v_120a", "50v_120a"}
    assert not d["all_independent_hotfault_cases_accepted"]
    assert not d["hardware_continuous_rating_approved"]


def test_f01_remains_blocked_even_if_cold_fault_ss_increases(monkeypatch):
    original = risk._load

    def changed(path):
        j = original(path)
        if path.name == "fault_48v_120a_target.json":
            j["ss_at_engage_v"] = 4.4
        return j

    monkeypatch.setattr(risk, "_load", changed)
    d = risk.build()
    assert d["evidence"]["48v_120a_fault_vss_at_engage_v"] == 4.4
    assert d["evidence"]["ss_rt_only_threshold_v"] < 4.4
    assert next(x for x in d["risks"] if x["id"] == "F01")["blocked"] is True


def test_invalid_or_unreviewed_approval_does_not_count(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "PP", tmp_path)
    path = tmp_path / "hotfault_48v_120a_engineering_review.json"
    path.write_text(json.dumps({"approved": True, "reviewer": "name",
                                "revision": "R1"}), encoding="utf-8")
    d = gate.inspect("48v_120a")
    assert d["accepted"] is False
    assert "missing" in d["reason"]


def test_missing_or_external_evidence_never_confirms_review():
    digest = hashlib.sha256(b"data").hexdigest()
    assert gate._valid_repo_file("../report.txt", digest) is None
    assert gate._valid_repo_file("C:\\\\secret\\\\file.raw", digest) is None
    assert gate._valid_repo_file("design/v3/not-actually-here.pdf", digest) is None


def test_repo_risk_register_is_current():
    result = risk.build()
    assert result["evidence"]["independent_hotfault_simulation_accepted"] is False
    assert next(x for x in result["risks"] if x["id"] == "F01")["blocked"]


def test_valid_engineering_evidence_is_possible_but_report_hash_tampering_fails(tmp_path, monkeypatch):
    """No real qualification claimed: use synthetic evidence in isolated tmp dir."""
    from validate_hotfault_log import CASES as CONFIG, sha as digest_deck
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "PP", tmp_path)
    case = "48v_120a"
    (tmp_path / f"hotfault_{case}.json").write_text(json.dumps({
        "reached_tstop": True, "solver_prefix_only": False,
        "raw_bytes": 125000,
        "fault": {"sr_gate_latched_at_end": False},
    }), encoding="utf-8")
    summary = tmp_path / "summary.json"
    wave = tmp_path / "waveform_review.md"
    summary.write_text(json.dumps({
        "case": case,
        "status": "LOG_PRECHECK_PASS_REQUIRES_WAVEFORM_AND_DEVICE_REVIEW",
        "raw_bytes": 125000, "not_rated": True, "blockers": [],
        "deck_sha256": digest_deck(CONFIG[case]["deck"]),
    }), encoding="utf-8")
    wave.write_text("Synthetic waveform engineering review, TEST ONLY", encoding="utf-8")
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    data = {
        "approved": True, "reviewer": "synthetic test reviewer",
        "revision": "TEST-R1", "validation_path": "summary.json",
        "validation_sha256": sha(summary), "waveform_review_path": "waveform_review.md",
        "waveform_review_sha256": sha(wave),
        "pre_fault_settled": True, "switch_and_oc_verified": True,
        "gate_shutdown_verified": True, "peak_stress_reviewed": True,
        "waveform_full_duration_verified": True,
    }
    approval = tmp_path / f"hotfault_{case}_engineering_review.json"
    approval.write_text(json.dumps(data), encoding="utf-8")
    assert gate.inspect(case)["accepted"]
    wave.write_text(wave.read_text(encoding="utf-8") + " TAMPERED", encoding="utf-8")
    assert not gate.inspect(case)["accepted"]



def test_actual_records_cannot_be_signed_off_when_sr_gate_high_or_solver_partial():
    for case in gate.CASES:
        measured = json.loads((gate.PP / f"hotfault_{case}.json").read_text(encoding="utf-8"))
        assert measured["fault"]["sr_gate_latched_at_end"] is True
        result = gate.inspect(case)
        assert not result["accepted"]
        if case == "48v_120a":
            assert measured["reached_tstop"] and not measured["solver_prefix_only"]
            assert "SR gate still high" in result["reason"]
        else:
            assert not measured["reached_tstop"] and measured["solver_prefix_only"]
            assert "solver prefix" in result["reason"]


def test_synthetic_approval_cannot_override_solver_prefix_or_high_sr_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "PP", tmp_path)
    case = "48v_120a"
    summary = tmp_path / f"hotfault_{case}.json"
    summary.write_text(json.dumps({
        "reached_tstop": False, "solver_prefix_only": True,
        "raw_bytes": 125000, "fault": {"sr_gate_latched_at_end": False},
    }), encoding="utf-8")
    assert "solver prefix" in gate.inspect(case)["reason"]
    obj = json.loads(summary.read_text(encoding="utf-8"))
    obj.update(reached_tstop=True, solver_prefix_only=False)
    obj["fault"]["sr_gate_latched_at_end"] = True
    summary.write_text(json.dumps(obj), encoding="utf-8")
    assert "SR gate still high" in gate.inspect(case)["reason"]
