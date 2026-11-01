"""The D1 fabrication gate must fail closed on incomplete CAD evidence."""
from __future__ import annotations

import json
from pathlib import Path

import d1_fabrication_gate as gate


def test_real_baseline_is_not_fabrication_approved():
    result = gate.build()
    assert result["release_approved"] is False
    assert result["status"] == "NOT_FOR_FAB"
    assert result["checks"]["golden_subnet_matches"] is True
    assert result["checks"]["native_editable_project_present"] is True
    assert result["counts"]["golden_references"] == 66
    assert result["counts"]["golden_logical_pins"] == 193
    assert set(result["counts"]["magnetics_missing_physical_pads"]) == {"CT","T1","T2","T3","T4"}
    assert result["counts"]["refs_with_placeholders"]
    assert result["counts"]["bom_rows_not_selected"]


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
