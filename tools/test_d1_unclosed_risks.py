"""Simulation derived risk assessment must not promote modeled output to a rating."""
from __future__ import annotations

import json
import pytest
import d1_unclosed_risks as r


def test_real_fault_peak_fails_two_turns_not_three():
    j = r.build()
    e = j["evidence"]
    assert e["48v_120a_fault_peak_primary_a"] == pytest.approx(84.826801, abs=1e-3)
    assert e["lr_2turn_flux_at_fault_peak_t"] > e["lr_0p9_bsat_limit_t"]
    assert e["lr_3turn_flux_at_fault_peak_t"] < e["lr_0p9_bsat_limit_t"]
    assert j["continuous_power_approved"] is False


def test_actual_partial_fault_and_loss_gaps_cannot_be_marked_done():
    j = r.build()
    assert j["evidence"]["48v_120a_fault_solver_prefix_only"]
    assert j["evidence"]["48v_120a_fault_vss_at_engage_v"] < 4.0
    assert j["evidence"]["50v_120a_model_loss_residual_w"] > j["evidence"]["target_residual_w"]
    assert j["evidence"]["50v_120a_model_closure_status"] == "NOT_CLOSED"
    assert all(x["blocked"] for x in j["risks"])


def test_settled_fault_evidence_is_recorded_without_unblocking_anything():
    """ELE-08's value is that the fault now lands on a measured settled state.
    Recording it must not promote the gate: no 50 V counterpart, no hardware."""
    j = r.build()
    e = j["evidence"]
    assert e["hotfault_48v_120a_stable_at_design_point"] is True
    assert e["hotfault_48v_120a_pre_fault_vss_v"] >= 4.8
    assert e["hotfault_48v_120a_solver_completed"] is True
    assert e["hotfault_48v_120a_lr_peak_before_trip_a"] == pytest.approx(97.442664, abs=1e-4)
    # The settled fault is worse than the cold-start fault for the 2-turn core.
    assert (e["hotfault_48v_120a_2turn_flux_at_fault_peak_t"]
            > e["lr_2turn_flux_at_fault_peak_t"])
    assert e["hotfault_48v_120a_2turn_flux_at_fault_peak_t"] > e["lr_0p9_bsat_limit_t"]
    assert e["hotfault_48v_120a_3turn_flux_at_fault_peak_t"] < e["lr_0p9_bsat_limit_t"]
    assert e["hotfault_50v_120a_stable_at_design_point"] is True
    assert e["hotfault_50v_120a_pre_fault_vss_v"] >= 4.8
    assert e["hotfault_50v_120a_solver_completed"] is False
    assert e["hotfault_50v_120a_solver_prefix_only"] is True
    assert e["hotfault_50v_120a_lr_peak_before_trip_a"] == pytest.approx(101.2627, abs=1e-3)
    assert (e["hotfault_50v_120a_lr_peak_before_trip_a"]
            > e["hotfault_48v_120a_lr_peak_before_trip_a"])
    assert e["hotfault_50v_120a_2turn_flux_at_fault_peak_t"] > e["lr_0p9_bsat_limit_t"]
    assert e["hotfault_50v_120a_3turn_flux_at_fault_peak_t"] < e["lr_0p9_bsat_limit_t"]
    assert all(x["blocked"] for x in j["risks"])


def test_the_loss_gap_is_not_a_short_window_artifact_but_stays_blocked():
    """ELE-09's decisive leg: 133 aligned periods confirm the same ~0.49 W.

    The short 22-period window was the thing under suspicion, so the register
    must carry both readings and show that the gap barely moved while the
    long window can resolve the 0.2 W target.  Recording that must not unblock
    anything -- an unresolved gap is still an unresolved gap.
    """
    j = r.build()
    e = j["evidence"]
    assert e["50v_120a_aligned_window_periods"] == 133
    assert e["50v_120a_aligned_loss_residual_w"] == pytest.approx(0.492054, abs=1e-5)
    assert e["50v_120a_aligned_loss_residual_w"] > e["target_residual_w"]
    # "Stable" here means the window change moved it by far less than the gap
    # itself; it is not a claim that the gap is acceptable.
    assert abs(e["50v_120a_loss_residual_moves_between_windows_w"]) < 0.05
    assert abs(e["50v_120a_loss_residual_moves_between_windows_w"]) < (
        e["50v_120a_aligned_loss_residual_w"] / 2)
    assert e["50v_120a_aligned_resolves_0p2_w"] is True
    assert e["50v_120a_model_closure_status"] == "NOT_CLOSED"
    assert all(x["blocked"] for x in j["risks"])


def test_committed_register_is_reproducible():
    assert json.loads(r.OUT.read_text(encoding="utf-8")) == r.build()
