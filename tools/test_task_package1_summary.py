"""Tests for the round-4 summary arithmetic (pure helpers only)."""

from __future__ import annotations

import numpy as np

from task_package1_summary import episodes, f_law_khz, relative, sr_allocation


def test_f_law_matches_ucc25600_at_both_ends() -> None:
    # SS = 3.982 V zeroes the 1.81 mA term -> RT-only 200.609 kHz.
    assert np.isclose(f_law_khz(3.982), 200.609, rtol=2e-4)
    # SS = 0 gives I_TOT = 2.5615 + 1.81 mA -> about 328 kHz.
    assert np.isclose(f_law_khz(0.0), 328.4, rtol=3e-3)
    # The law is monotone falling in V_SS over the useful range.
    assert f_law_khz(1.0) > f_law_khz(2.0) > f_law_khz(3.0)


def test_episodes_merge_short_gaps_and_report_peak() -> None:
    t = np.arange(0.0, 20e-6, 1e-8)
    v = np.zeros_like(t)
    v[(t >= 2e-6) & (t < 4e-6)] = 1.2
    v[(t >= 4.5e-6) & (t < 6e-6)] = 2.5  # 0.5 us gap -> merged
    v[(t >= 12e-6) & (t < 13e-6)] = 1.5
    eps = episodes(t, v, 1.0, debounce=1e-6)
    assert len(eps) == 2
    assert np.isclose(eps[0]["start_s"], 2e-6, atol=1e-8)
    assert np.isclose(eps[0]["peak_v"], 2.5)
    assert np.isclose(eps[1]["start_s"], 12e-6, atol=1e-8)


def test_relative_is_signed_percent_of_reference() -> None:
    assert np.isclose(relative(100.0, 101.0), 1.0)
    assert np.isclose(relative(100.0, 99.0), -1.0)


def test_sr_allocation_excludes_gate_resistor_from_the_port_loss_share() -> None:
    """Rg heat is in the ledger but not in machine Pin: do not count it twice."""
    full = {"p_total_loss_w": 10.0, "p_sr_branch_8device_w": 4.0, "p_rg_8device_w": 0.2}
    row = sr_allocation(full)
    assert np.isclose(row["p_sr_share_of_total_loss_pct"], 40.0)
    assert np.isclose(row["p_other_model_loss_w"], 6.0)
    # Rg stays reported separately and is never subtracted a second time.
    assert np.isclose(full["p_sr_branch_8device_w"] + full["p_rg_8device_w"], 4.2)


def test_sr_allocation_survives_a_zero_loss_window() -> None:
    row = sr_allocation({"p_total_loss_w": 0.0, "p_sr_branch_8device_w": 0.0})
    assert np.isnan(row["p_sr_share_of_total_loss_pct"])
    assert row["p_other_model_loss_w"] == 0.0
