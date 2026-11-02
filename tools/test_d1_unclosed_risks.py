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


def test_committed_register_is_reproducible():
    assert json.loads(r.OUT.read_text(encoding="utf-8")) == r.build()
