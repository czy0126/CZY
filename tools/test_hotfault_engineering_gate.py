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
