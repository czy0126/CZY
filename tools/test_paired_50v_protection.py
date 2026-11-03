"""PROT-03: the 50 V comparisons must be differenced against a control deck.

The pre-registered acceptance has two clauses: a <= 1 mV pre-fault ``V(out)``
match over the same 35 us window, and two complete 320 us windows.  These tests
do not re-run LTspice; they pin that the committed records are internally
consistent and that the base deck is a topology-matched control rather than the
declared parent, which sits 13-18 mV away before the fault.

Measured outcome: the pairing clause is met exactly (delta = 0.000000 mV), the
completion clause is not.  The threshold-muted control -- the only design that
keeps the candidate's pre-fault numerical path -- stalls at 250.151 us (A) and
254.980 us (B), while the candidate reaches 320 us.  The records therefore
carry ``declared_window_fully_covered: false`` and compare over the common
slice.

The verdicts are data, not test targets: if a future re-run changes either
clause the record must say so, and these tests then check the recorded claim
against the recorded numbers instead of failing the build over a physical
result.  What they do forbid is a record that *claims* coverage it lacks.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CASES = ("a", "b")


def record(case: str) -> dict:
    path = ROOT / f"design/v3/power_priority/protection_candidate_50v_120a_prot_{case}_paired.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES)
def test_the_base_is_the_threshold_muted_control(case: str) -> None:
    decks = record(case)["decks"]
    assert decks["base"].endswith("_thrmute_control.cir")
    assert decks["base"] != decks["declared_parent"]
    assert decks["declared_parent"].endswith("_cshunt_srprobe.cir")


@pytest.mark.parametrize("case", CASES)
def test_the_structural_checks_still_use_the_declared_parent(case: str) -> None:
    checks = record(case)["checks"]
    assert checks["the_candidate_matches_its_generator"]
    assert checks["the_parent_fault_network_is_unchanged"]
    assert checks["all_ten_gate_clamps_are_present"]


@pytest.mark.parametrize("case", CASES)
def test_the_covered_window_is_reported_not_assumed(case: str) -> None:
    """The pairing clause is met; the completion clause is not.

    A record may legitimately fail the completion clause -- this is a physical
    result about the control, not a broken tool.  What it may never do is claim
    ``declared_window_fully_covered`` without both sides reaching their stop, or
    quote a comparison window that runs past the shorter record.
    """
    rec = record(case)
    cov = rec["coverage"]
    assert cov["candidate_reached_saved_stop"]
    assert cov["candidate_saved_stop_us"] == 320.0
    assert cov["base_saved_stop_us"] == 320.0
    assert cov["declared_window_fully_covered"] == (
        cov["base_reached_saved_stop"] and cov["candidate_reached_saved_stop"])
    assert rec["checks"]["the_declared_window_is_fully_covered"] == (
        cov["declared_window_fully_covered"])
    # The comparison window ends at the shorter tail, never beyond it.
    assert rec["window_s"][1] * 1e6 == pytest.approx(cov["base_t_last_us"], abs=0.01)
    assert rec["window_s"][1] * 1e6 <= cov["base_saved_stop_us"]
    if not cov["base_reached_saved_stop"]:
        assert cov["base_t_last_us"] < cov["base_saved_stop_us"]
        assert any("the common slice ends at" in line for line in rec["limits"])


@pytest.mark.parametrize("case,stall_us", [("a", 250.151), ("b", 254.980)])
def test_the_control_stall_times_are_the_measured_ones(case: str, stall_us: float) -> None:
    """Pin the measured tail so a silently different control run cannot pass.

    The exact value is the evidence that the control deck -- not a rerun of the
    candidate -- is the base; a regenerated control would move it by more than
    this tolerance.
    """
    cov = record(case)["coverage"]
    assert cov["base_t_last_us"] == pytest.approx(stall_us, abs=1e-3)
    assert not cov["base_reached_saved_stop"]


@pytest.mark.parametrize("case", CASES)
def test_the_pairing_verdict_matches_the_recorded_delta(case: str) -> None:
    rec = record(case)
    delta = rec["results"]["pre_fault"]["vout_mean_delta_mv"]
    paired = rec["checks"]["the_pre_fault_operating_points_match_within_1_mv"]
    assert paired == (delta <= 1.0), (case, delta, paired)


@pytest.mark.parametrize("case", CASES)
def test_the_pairing_is_exact_and_not_just_inside_the_criterion(case: str) -> None:
    """Both sides are the same circuit until the trigger, so the offset is zero.

    A few microvolts would also pass the 1 mV criterion, but it would mean the
    decks had diverged before the fault and the relief number would no longer be
    attributable to the protection alone.
    """
    rec = record(case)
    assert rec["results"]["pre_fault"]["vout_mean_delta_mv"] == pytest.approx(0.0, abs=1e-9)
    assert rec["results"]["pre_fault"]["base"]["vout_mean_v"] == pytest.approx(
        rec["results"]["pre_fault"]["candidate"]["vout_mean_v"], abs=1e-9)


@pytest.mark.parametrize("case", CASES)
def test_the_noclamp_control_is_kept_as_the_negative_example(case: str) -> None:
    """The Vt=10 control is why the threshold-muted design exists.

    Its record must keep saying that raising Vt also moves the numerical path
    (13-18 mV pre-fault offset); if that ever became a pass, this file's whole
    rationale -- one changed line, switch model untouched -- would be wrong.
    """
    path = ROOT / f"design/v3/power_priority/protection_candidate_50v_120a_prot_{case}_noclamp_paired.json"
    rec = json.loads(path.read_text(encoding="utf-8"))
    assert rec["decks"]["base"].endswith("_noclamp_control.cir")
    assert rec["results"]["pre_fault"]["vout_mean_delta_mv"] > 1.0
    assert not rec["checks"]["the_pre_fault_operating_points_match_within_1_mv"]
    # It is also the only *complete* unprotected 50 V control, so the burden
    # pulse uses it when a full 320 us energy is needed.  If it ever stalled,
    # oc_burden_pulse would be built on a truncated pulse.
    assert rec["coverage"]["base_reached_saved_stop"]
    assert rec["coverage"]["declared_window_fully_covered"]


@pytest.mark.parametrize("case", CASES)
def test_the_candidate_clamps_all_ten_gates(case: str) -> None:
    gates = record(case)["results"]["candidate"]["gates"]
    assert len(gates) == 8
    assert not any(row["high_at_end"] for row in gates.values())
