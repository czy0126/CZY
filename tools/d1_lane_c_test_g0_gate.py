"""Regression checks for Issue #133 isolated protection wiring contract."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d1_lane_c_g0_gate as gate
import make_d0_protection_board as d0

def test_all_ten_gates_have_independent_real_driver_bleeds_and_sense():
    report = gate.build()
    assert len(report["channels"]) == 10
    assert [c["kind"] for c in report["channels"]] == ["SR"] * 8 + ["PRIMARY"] * 2
    assert len({c["sense_diode"] for c in report["channels"]}) == 10
    assert report["structure_audit"]["enable_pulldowns"] == 8
    assert report["structure_audit"]["selected_pins_exported_kicad_netlist_checked"] > 80

def test_cannot_approve_on_structure_or_comparator_typical_only():
    report = gate.build()
    assert report["existing_evidence"]["timing_lm393_max"] is None
    assert report["structure_audit"]["main_board_pin_parity_proven"] is False
    assert report["gate_0_approved"] is False
    assert report["gate_1_measured_success"] is False
    assert report["energization_allowed"] is False
    assert all(c["status"] == "PENDING" for c in report["fault_injections"])

@pytest.mark.parametrize("ref", ["R36", "R43", "R45", "D9", "D18", "R56", "R65", "R46", "R47"])
def test_mutation_of_a_safety_connection_is_rejected(ref):
    parts = d0.parts()
    changed = []
    for part in parts:
        if part.ref == ref:
            broken = {"1": "UNSAFE_MUTATION", **{k:v for k,v in part.nets.items() if k != "1"}}
            changed.append(replace(part, nets=broken))
        else:
            changed.append(part)
    with pytest.raises(ValueError):
        gate.inspect_wiring(changed)


def test_corrupted_kicad_netlist_not_accepted_as_a_valid_gate_export():
    original = gate.D0_NET.read_text("utf-8")
    corrupted = original.replace('(name "/GA1")', '(name "/GA1_BAD")', 1)
    with pytest.raises(ValueError, match="exported netlist disagrees"):
        gate.verify_exported_netlist(d0.parts(), {"R48", "R56", "R66"}, corrupted)

def test_missing_gate_or_enable_cannot_be_hidden_by_a_green_report():
    parts = [p for p in d0.parts() if p.ref != "R41"]
    with pytest.raises(ValueError, match="missing device"):
        gate.inspect_wiring(parts)

def test_bootstrap_to_pgnd_is_never_accepted_as_a_real_halfbridge():
    report = gate.build()
    assert report["structure_audit"]["bench_bootstrap_c29_to_pgnd"] == "NOT_VALIDATED_FOR_REAL_HS"
    assert "U18" in str(report["g0_blockers"])
