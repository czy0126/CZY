"""Dependency-graph safety and separation of model vs physical release."""
from __future__ import annotations

import copy
import csv
import json

import pytest

import check_d1_parallel_execution as checker


def from_sources():
    with checker.TASK_CSV.open(encoding="utf-8-sig", newline="") as stream:
        tasks = list(csv.DictReader(stream))
    gates = json.loads(checker.GATE_JSON.read_text(encoding="utf-8"))
    return tasks, gates


def test_source_plan_has_six_parallel_tracks_and_not_ready_hardware():
    output = checker.validate()
    assert output["task_count"] >= 29
    assert len(output["lanes"]) == 6
    assert output["dependency_graph_acyclic"] is True
    assert output["gate_checks"]["hardware_release"] is False
    assert output["gate_checks"]["all_not_ready"] is True
    assert output["scope"] == "DOCUMENT_ONLY_NOT_HARDWARE_SIGNOFF"


def test_zero_dependency_launch_lanes_are_not_blocked_by_other_work():
    rows, _ = from_sources()
    mapping = {r["task_id"]: r for r in rows}
    parallel_now = ("B01", "C01", "C02", "D01", "D02",
                    "E01", "E03", "F01", "F02", "F03")
    for key in parallel_now:
        assert checker.dependencies(mapping[key]) == [], key
    assert checker.dependencies(mapping["A02"]) == ["A01"]


def test_priority_m1_never_waits_for_optional_10a_model_or_bom_ledger():
    _, gates = from_sources()
    by_id = {g["gate_id"]: g for g in gates["gates"]}
    assert "A02" in by_id["M0_5A"]["prerequisite_task_ids"]
    assert "A03" not in by_id["M1"]["prerequisite_task_ids"]
    assert by_id["M0_5A"]["hardware_power_on_authorized"] is False
    assert by_id["M0_10A"]["hardware_power_on_authorized"] is False
    assert by_id["M1"]["nature"] == "HARDWARE_LOW_ENERGY_SAFETY_REVIEW"
    assert by_id["M3"]["nature"] == "HIGH_CURRENT_HARDWARE"
    assert not gates["all_hardware_release"]


def test_self_reference_unknown_id_and_cycles_are_rejected():
    rows, _ = from_sources()
    bad = copy.deepcopy(rows)
    bad[0]["depends_on"] = bad[0]["task_id"]
    with pytest.raises(ValueError, match="self-dependency"):
        checker.validate_rows(bad)
    bad = copy.deepcopy(rows)
    bad[0]["depends_on"] = "Z98"
    with pytest.raises(ValueError, match="unknown task"):
        checker.validate_rows(bad)
    bad = copy.deepcopy(rows)
    mapping = {r["task_id"]: r for r in bad}
    # Cycle A01 -> A02 -> A01; since A02 already depends on A01.
    mapping["A01"]["depends_on"] = "A02"
    with pytest.raises(ValueError, match="cycle"):
        checker.validate_rows(bad)


def test_gate_not_ready_or_auto_power_on_claim_fails_closed():
    rows, gates = from_sources()
    optimistic = copy.deepcopy(gates)
    optimistic["gates"][2]["ready"] = True
    with pytest.raises(ValueError, match="do not mark gates ready"):
        checker.validate_gates(optimistic, rows)
    optimistic = copy.deepcopy(gates)
    optimistic["gates"][2]["hardware_power_on_authorized"] = True
    with pytest.raises(ValueError, match="auto-enable power"):
        checker.validate_gates(optimistic, rows)
    optimistic = copy.deepcopy(gates)
    optimistic["all_hardware_release"] = True
    with pytest.raises(ValueError, match="authorize hardware"):
        checker.validate_gates(optimistic, rows)


def test_missing_physical_signoff_evidence_and_future_gate_reference_fail():
    rows, gates = from_sources()
    bad = copy.deepcopy(gates)
    bad["gates"][2]["human_evidence"] = []
    with pytest.raises(ValueError, match="missing evidence"):
        checker.validate_gates(bad, rows)
    bad = copy.deepcopy(gates)
    bad["gates"][2]["prerequisite_gate_ids"] = ["M3"]
    with pytest.raises(ValueError, match="future/self-dependent"):
        checker.validate_gates(bad, rows)


def test_marking_task_verified_without_its_signed_evidence_is_not_allowed():
    rows, _ = from_sources()
    copied = copy.deepcopy(rows)
    copied[0]["status"] = "VERIFIED"
    with pytest.raises(ValueError, match="human-verified evidence"):
        checker.validate_rows(copied)
