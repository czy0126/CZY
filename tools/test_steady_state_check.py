"""Tests for the window-convergence helpers.

The tool is a reporting layer, but its two arithmetic choices are easy to get
wrong: which edges count as a complete period, and whether "sharing" compares a
ratio or an absolute charge.  Both are pinned here.
"""

from __future__ import annotations

import numpy as np

from steady_state_check import periods_in, relative_gap, window_summary


def _synthetic() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    t = np.arange(0.0, 20e-6 + 5e-9, 5e-9)
    period = 5e-6
    phase = np.mod(t, period)
    gate = np.where(phase < 2e-6, 11.0, 0.0)
    data = {
        "V(ga1)": gate,
        "V(out)": np.full(t.size, 1.9),
        "V(a1)": np.full(t.size, -0.05),
        "I(VSa1)": np.full(t.size, -10.0),
    }
    return t, data


def test_periods_in_returns_only_complete_gate_periods() -> None:
    t, data = _synthetic()
    wins = periods_in(t, data["V(ga1)"], 0.0, 20e-6)
    # The signal starts high, so the rise at t=0 is not an edge: 5/10/15/20 us
    # give 3 complete periods, and no period may be truncated at the boundary.
    assert len(wins) == 3
    assert all(np.isclose(b - a, 5e-6, rtol=2e-3) for a, b in wins)


def test_window_summary_reports_frequency_and_time_average() -> None:
    t, data = _synthetic()
    row = window_summary(t, data, 1, 0.0, 20e-6)
    assert np.isclose(row["freq_khz"], 200.0, rtol=1e-3)
    assert np.isclose(row["vout_time_avg_v"], 1.9, rtol=1e-9)
    assert np.isclose(row["qvfwd_mean_nc"], 50_000.0, rtol=1e-3)  # 10 A * 5 us
    assert row["qvrev_mean_nc"] == 0.0


def test_relative_gap_is_symmetric_relative_difference() -> None:
    assert np.isclose(relative_gap(100.0, 101.0), 1.0)
    assert np.isclose(relative_gap(100.0, 99.0), 1.0)


def test_sharing_is_compared_as_a_ratio_not_an_absolute_charge() -> None:
    """Two windows with the same 100 % share must not report a sharing gap."""
    share_a, share_b = 100.000, 100.000
    assert relative_gap(share_a, share_b) == 0.0


def _four_group() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    t, data = _synthetic()
    # Four identical groups, each delivering 25 A into the 1.9 V output node.
    for n in (1, 2, 3, 4):
        data[f"V(a{n})"] = np.full(t.size, -0.025)
        data[f"I(VSa{n})"] = np.full(t.size, -25.0)
    return t, data


def test_group_sharing_uses_average_output_current_not_qrev() -> None:
    t, data = _four_group()
    row = window_summary(t, data, 1, 0.0, 20e-6)
    for n in (1, 2, 3, 4):
        assert np.isclose(row[f"iout_g{n}_a"], 25.0, rtol=1e-9)
        assert np.isclose(row[f"irms_g{n}_a"], 25.0, rtol=1e-9)
    assert np.isclose(row["iout_sum_a"], 100.0, rtol=1e-9)
    assert np.isclose(row["iout_spread_pct"], 0.0, atol=1e-9)
    # Lsa_n carries V(out)-V(a_n) = 1.925 V; 20 us over 3 complete 5 us periods.
    assert np.isclose(row["flux_g1_vs"], 1.925 * 20e-6 / 3, rtol=1e-9)


def test_unequal_groups_report_a_nonzero_spread() -> None:
    t, data = _four_group()
    data["I(VSa2)"] = np.full(t.size, -20.0)
    row = window_summary(t, data, 1, 0.0, 20e-6)
    # currents 25/20/25/25 -> mean 23.75, spread (25-20)/23.75 = 21.05 %
    assert np.isclose(row["iout_spread_pct"], 100.0 * 5.0 / 23.75, rtol=1e-9)


def test_single_instrumented_group_reports_no_spread() -> None:
    t, data = _synthetic()
    row = window_summary(t, data, 1, 0.0, 20e-6)
    assert row["iout_spread_pct"] == 0.0
    assert "qrev_ratio_pair4_over_pair1_pct" not in row


def test_group_current_sums_both_devices_of_a_pair() -> None:
    """A rectifier group is an a/b pair; counting only 'a' halves the total.

    The first full-machine run reported 47.6 A where Pout/Vout demanded 94.6 A:
    every group's 'b' device was silently dropped from the sum.
    """
    t, data = _four_group()
    for n in (1, 2, 3, 4):
        data[f"V(b{n})"] = np.full(t.size, -0.025)
        data[f"I(VSb{n})"] = np.full(t.size, -25.0)
    row = window_summary(t, data, 1, 0.0, 20e-6)
    for n in (1, 2, 3, 4):
        assert np.isclose(row[f"iout_g{n}_a"], 50.0, rtol=1e-9)
        assert np.isclose(row[f"irms_g{n}_a"], 50.0, rtol=1e-9)
        assert np.isclose(row[f"p_port_g{n}_w"], 1.25, rtol=1e-9)  # 2 * (-0.025)*(-25) W
    assert np.isclose(row["iout_sum_a"], 200.0, rtol=1e-9)
    assert np.isclose(row["iout_spread_pct"], 0.0, atol=1e-9)
