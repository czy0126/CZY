from __future__ import annotations
import json
import pytest
import ledger_issue6_triage as t


def test_every_aligned_step_is_carried_not_just_the_first_three():
    """E6-3 added a 0.5 ns leg; a three-column report silently dropped it."""
    d = t.build()
    assert d["target_w_unchanged"] == pytest.approx(0.2)
    assert d["aligned_steps_ns"] == ["5", "2", "1", "0.5"]
    assert len(d["after_gate_sinks_aligned_w"]) == 4
    assert len(d["original_aligned_w"]) == 4
    assert d["status"].endswith("NOT_CLOSED")
    assert not d["canonical_ledger_closure_approved"]
    assert not d["numerical_step_convergence_approved"]
    assert d["important_uncertainty"]["body_diode_forward_loss_across_step_w"] > 1.0


def test_the_half_nanosecond_leg_refutes_the_plateau():
    """5 / 2 / 1 ns agreed to 0.016 W and looked flat; 0.5 ns does not.

    The triage must say that plainly, otherwise the three-point series gets
    quoted as convergence in exactly the way E6-3 existed to prevent.
    """
    d = t.build()
    assert d["plateau_reached"] is False
    assert d["last_leg_w"] > 0.2
    assert d["residual_at_finest_step_w"] > 0.2


def test_the_group_symmetry_record_carries_the_split_bound():
    """E6-4: the x4 scaling rests on four identical groups, but only pairs 1
    and 4 have probes.  The record must carry the measured ratio, the worst
    I2R error it implies, and say plainly that pairs 2/3 are UNKNOWN."""
    d = t.build()
    symmetry = d["group_symmetry"]
    assert symmetry["measured_groups"] == [1, 4]
    assert symmetry["unmeasured_groups"] == [2, 3]
    ratios = symmetry["pair4_over_pair1_rms"]
    assert ratios["aligned_5ns"]["a"] == pytest.approx(1.0, abs=1e-9)
    assert ratios["aligned_1ns"]["a"] == pytest.approx(0.9793, abs=1e-3)
    assert ratios["aligned_1ns"]["b"] == pytest.approx(1.0197, abs=1e-3)
    assert symmetry["worst_i2r_error_pct"]["case"] == "aligned_1ns"
    assert symmetry["worst_i2r_error_pct"]["percent"] > 3.0
    assert symmetry["circulating_difference_rms_a"]["aligned_1ns"]["a"] > 0.5
    entry = next(e for e in d["next_discriminating_experiments"] if e["id"] == "E6-4")
    assert entry["status"] == "done"
    assert "UNKNOWN" in entry["result"]
    assert "1 ns" in entry["result"]


def test_the_diode_split_says_which_term_moves():
    """E6-1: "the SR loss does not converge" has to name a component.

    The channel term is flat across the four aligned steps; the body-diode
    forward term carries the whole movement, and reverse recovery must stay
    negative (it returns energy) on every run.
    """
    d = t.build()
    entry = next(e for e in d["next_discriminating_experiments"] if e["id"] == "E6-1")
    assert entry["status"] == "done"
    split = d["diode_split"]
    assert split["channel_step_spread_w"] < 0.1
    assert split["body_diode_forward_step_spread_w"] > 2.0
    assert split["body_diode_forward_share_of_sr_move"] > 1.0
    assert set(split["body_diode_reverse_w"]) == {"5", "2", "1", "0.5"}
    assert all(value < 0.0 for value in split["body_diode_reverse_w"].values())
    assert "body-diode forward" in entry["result"]
    assert "reverse recovery" in entry["result"]
    assert "pairs 2 and 3" in entry["result"]


def test_the_gate_sink_correction_is_measured_not_asserted():
    """E6-2: the closure correction must be the KCL-consistent Rg + Rgs sinks.

    Re-adding the whole Bdrive output would double count; the correction is
    instead the two resistors the driver output feeds, measured from the gate
    waveform on the same 133-cycle window.
    """
    d = t.build()
    entry = next(e for e in d["next_discriminating_experiments"] if e["id"] == "E6-2")
    assert entry["status"] == "done"
    correction = d["gate_sink_correction"]
    assert set(correction["per_step_w"]) == {"5", "2", "1", "0.5"}
    assert correction["sinks_w_5ns"] == pytest.approx(0.2175, abs=5e-3)
    assert correction["spread_across_steps_w"] < 0.01
    assert correction["kcl_residual_max_w"] < 1e-3
    assert "Rg" in entry["result"] and "Rgs" in entry["result"]
    assert "NOT_CLOSED" in entry["result"]


def test_checked_in_diagnostic_is_reproducible():
    assert json.loads(t.OUT.read_text(encoding="utf-8")) == t.build()
