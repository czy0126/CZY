"""Regression tests for the pure helpers in tools/tank_metrics.py.

The raw-file interface is not tested (one bench, one file); the pieces that can
silently mis-window or mis-sign a number are: edge detection, period recovery,
the zero-crossing slope, the trapezoid integral, the per-channel gate split
(round-2 P1), the time-weighted average, and the window-wide extremes.
"""

from __future__ import annotations

import numpy as np
import pytest

from tank_metrics import (
    average_metrics,
    crossing,
    edges,
    integrate,
    pair_metrics,
    period_and_window,
    periods,
    span_extremes,
    time_average,
)

T = np.arange(0.0, 20e-6, 1e-9)
# integer-sample square wave: high for the first 3 us of every 5 us period,
# so the rising edges land exactly on 5/10/15 us with no float-modulo drift
SAMPLES = np.round(T / 1e-9).astype(int)
SQUARE = np.where((SAMPLES % 5000) < 3000, 11.0, 0.0)


def test_edges_finds_rising_crossings_only() -> None:
    rises = edges(T, SQUARE)
    assert np.allclose(rises, [5e-6, 10e-6, 15e-6], atol=1e-12)


def test_period_recovered_from_repeated_edges() -> None:
    period, t0, t1 = period_and_window(T, SQUARE)
    assert abs(period - 5e-6) < 2e-9
    assert abs(t1 - 15e-6) < 1e-12
    assert abs(t1 - t0 - period) < 1e-20


def test_edges_debounces_a_gate_glitch() -> None:
    """A gate that crosses 2 V, dips back, and re-crosses within a few ns is ONE edge.

    Observed on sim/v2/sr_tank_dual.raw: two rising crossings 3.8 ns apart made
    period_and_window() average a 3.8 ns "period" into its mean and report
    1.2019 us for a stage running at ~275 kHz.
    """
    glitched = SQUARE.copy()
    # at the 10 us edge: high at 10.000 us, low 10.001-10.002 us, high from 10.003 us
    glitched[(SAMPLES == 10_001) | (SAMPLES == 10_002)] = 0.0
    rises = edges(T, glitched)
    assert len(rises) == 3, f"expected one edge per half period, got {len(rises)}"
    period, _, _ = period_and_window(T, glitched)
    assert abs(period - 5e-6) < 2e-9


def test_crossing_returns_time_and_slope() -> None:
    # rectifying current is NEGATIVE on this bench, so the reverse-current onset
    # is the rising (negative -> positive) crossing, not the falling one
    current = np.linspace(-40.0, 40.0, T.size)  # -40 A -> +40 A over 20 us
    tc, slope = crossing(T, current)
    assert abs(tc - 10e-6) < 2e-9
    assert abs(slope - 80.0 / 20e-6) < 1e3


def test_pair_metrics_uses_measured_current_signs() -> None:
    """I < 0 is rectifying, I > 0 is reverse (measured on startup_ct.raw)."""
    t = np.arange(0.0, 1e-6 + 0.5e-9, 1e-9)[:1001]
    ia = np.where(t < 0.5e-6, -20.0, np.where(t < 0.7e-6, 10.0, 0.0))
    ia = np.where(t >= 0.8e-6, -5.0, ia)  # overlap tail: both channels forward
    data = {
        "V(a1)": np.where(t < 0.5e-6, -0.03, np.where(t < 0.7e-6, 0.7, np.where(t >= 0.8e-6, -0.05, 0.0))),
        "V(b1)": np.where(t >= 0.8e-6, -0.05, 0.0),
        "I(VSa1)": ia,
        "I(VSb1)": np.where(t >= 0.8e-6, -10.0, 0.0),
        "V(ga1)": np.where(t < 0.6e-6, 11.0, 0.0),
        "V(gb1)": np.where(t >= 0.8e-6, 11.0, 0.0),
    }
    m = pair_metrics(t, data, 1, 0.0, 1e-6)
    # rtol 5e-3 absorbs one 1 ns sample cell of edge smear (5 A * 1 ns = 5 nC on
    # a ~1 uC result); the real raw file refines its time step around edges
    assert np.isclose(m["q_port_a_fwd_nc"], 11_000.0, rtol=5e-3)  # 20A*0.5us + 5A*0.2us
    assert np.isclose(m["q_port_a_rev_nc"], 2_000.0, rtol=5e-3)  # 10A*0.2us
    assert np.isclose(m["ifwd_a_pk_a"], 20.0)
    assert np.isclose(m["irev_a_pk_a"], 10.0)
    assert np.isclose(m["qovl_nc"], 1_000.0, rtol=5e-3)  # min(5,10) over 0.2 us
    assert np.isclose(m["eovl_uj"], 0.15, rtol=5e-3)  # (0.25+0.5) W * 0.2 us


def test_pair_metrics_classifies_each_channel_by_its_own_gate() -> None:
    """Round-2 P1 counterexample: B on, A off must NOT book A's energy as conduction.

    The old code used `ga_on | gb_on` for the a-channel VDS_A * I_A, so during the
    handover (B already on, A already off) A's port energy was folded into the
    channel-on bucket.  With A's own gate it belongs to the off bucket.
    """
    t = np.arange(0.0, 1e-6 + 0.5e-9, 1e-9)[:1001]
    # window 0.2..0.6 us: channel A carries -8 A at V(a1) = -0.05 V (0.4 W)
    # while V(ga1)=0 (OFF) and V(gb1)=11 (B is the one on).
    a_on = (t >= 0.2e-6) & (t < 0.6e-6)
    data = {
        "V(a1)": np.where(a_on, -0.05, 0.0),
        "V(b1)": np.zeros_like(t),
        "I(VSa1)": np.where(a_on, -8.0, 0.0),
        "I(VSb1)": np.zeros_like(t),
        "V(ga1)": np.zeros_like(t),  # A OFF
        "V(gb1)": np.where(a_on, 11.0, 0.0),  # B ON
    }
    m = pair_metrics(t, data, 1, 0.0, 1e-6)
    assert np.isclose(m["e_port_a_on_uj"], 0.0, atol=1e-9)
    assert np.isclose(m["e_port_a_off_uj"], 0.4 * 0.4e-6 * 1e6, rtol=5e-3)  # 0.16 uJ
    assert np.isclose(m["e_port_b_on_uj"], 0.0, atol=1e-9)  # B carries no current
    assert np.isclose(m["e_port_a_off_uj"] + m["e_port_a_on_uj"], m["e_port_a_total_uj"], rtol=1e-9)


def test_overlap_split_by_gate_state() -> None:
    """Same forward current through both channels is a fault only with both gates ON.

    With both gates OFF it is the dead-time freewheel through the two body diodes
    -- the normal commutation path in this topology (measured: 2.765 A of it in
    sim/v2/sr_tank_dual at 0.0 gate-voltage overlap).  The split must separate them.
    """
    t = np.arange(0.0, 1e-6 + 0.5e-9, 1e-9)[:1001]
    fwd = (t >= 0.2e-6) & (t < 0.4e-6)  # both channels forward, gates ON
    off = (t >= 0.6e-6) & (t < 0.8e-6)  # both channels forward, gates OFF
    data = {
        # VDS is negative while current flows drain->source (V = I*RdsOn < 0), so
        # V*I > 0 in both regions and the energies are real heat
        "V(a1)": np.where(fwd, -0.03, np.where(off, -0.05, 0.0)),
        "V(b1)": np.where(fwd, -0.03, np.where(off, -0.05, 0.0)),
        "I(VSa1)": np.where(fwd, -6.0, np.where(off, -4.0, 0.0)),
        "I(VSb1)": np.where(fwd, -8.0, np.where(off, -10.0, 0.0)),
        "V(ga1)": np.where(fwd, 11.0, 0.0),
        "V(gb1)": np.where(fwd, 11.0, 0.0),
    }
    m = pair_metrics(t, data, 1, 0.0, 1e-6)
    assert np.isclose(m["qovl_nc"], 2_000.0, rtol=5e-3)  # 6A*0.2us + 4A*0.2us
    assert np.isclose(m["qovl_on_nc"], 1_200.0, rtol=5e-3)  # both gates ON
    assert np.isclose(m["qovl_off_nc"], 800.0, rtol=5e-3)  # both gates OFF, freewheel
    assert np.isclose(m["qovl_on_nc"] + m["qovl_off_nc"] + m["qovl_mixed_nc"], m["qovl_nc"], rtol=5e-3)
    assert np.isclose(m["eovl_on_uj"], 0.084, rtol=5e-3)  # (0.03*6 + 0.03*8) W * 0.2 us
    assert np.isclose(m["eovl_off_uj"], 0.14, rtol=5e-3)  # (0.05*4 + 0.05*10) W * 0.2 us


def test_time_average_is_time_weighted_not_sample_mean() -> None:
    """A non-uniform raw grid must not let a fast edge outvote the flat part.

    A 2 ns triangular spike at 2 V inside a 1 us window of 0 V: the sample mean
    is 0.4 V (it weights the two spike samples equally with the flat ones), the
    time average is 2 ns x 2 V / 2 / 1 us = 2 mV.
    """
    t = np.array([0.0, 0.5e-6, 0.5e-6 + 1e-9, 0.5e-6 + 2e-9, 1e-6])
    v = np.array([0.0, 0.0, 2.0, 0.0, 0.0])
    sample_mean = float(v.mean())
    avg = time_average(t, v)
    assert abs(avg - 2e-3) < 1e-6
    assert abs(sample_mean - avg) > 0.39


def test_span_extremes_takes_the_true_maximum() -> None:
    """The stress number is the window maximum, not the mean of per-period peaks.

    One 12 A spike inside an otherwise 5 A window: a per-period average can hide
    it between periods, but span_extremes must report 12 A.
    """
    t = np.arange(0.0, 5e-6 + 0.5e-9, 1e-9)
    ia = np.full_like(t, -5.0)
    ia[1000] = 12.0
    data = {
        "V(a1)": np.full_like(t, -0.02),
        "V(b1)": np.full_like(t, -0.02),
        "I(VSa1)": ia,
        "I(VSb1)": np.full_like(t, -5.0),
        "V(out)": np.full_like(t, 1.6),
    }
    ext = span_extremes(t, data, 1, 0.0, 5e-6)
    assert np.isclose(ext["span_irev_a_max_a"], 12.0)
    assert np.isclose(ext["span_ifwd_a_max_a"], 5.0)
    assert np.isclose(ext["span_vout_time_avg_v"], 1.6)


def test_periods_returns_requested_complete_windows() -> None:
    # SQUARE rises at 5/10/15 us: three edges bound only two complete periods
    windows = periods(T, SQUARE, count=2)
    assert len(windows) == 2
    assert all(abs(t1 - t0 - 5e-6) < 2e-9 for t0, t1 in windows)
    assert windows[-1][1] == 15e-6  # last complete period ends at the last edge
    with pytest.raises(SystemExit):
        periods(T, SQUARE, count=3)  # asking for more periods than the edges bound


def test_average_metrics_reports_mean_and_spread() -> None:
    """A beating tank gives every period a different reverse charge; one period is noise."""
    runs = [{"q_port_a_rev_nc": v} for v in (100.0, 200.0, 300.0)]
    avg = average_metrics(runs)
    assert avg["q_port_a_rev_nc"] == 200.0
    assert avg["q_port_a_rev_nc_min"] == 100.0
    assert avg["q_port_a_rev_nc_max"] == 300.0
    assert abs(avg["q_port_a_rev_nc_spread_pct"] - 100.0) < 1e-9


def test_integrate_of_constant_is_rectangle() -> None:
    one = np.ones_like(T)
    assert abs(integrate(T, one) - (T[-1] - T[0])) < 1e-15


def test_integrate_ignores_masked_intervals_via_factor() -> None:
    one = np.ones_like(T)
    mask = (T < 10e-6).astype(float)
    assert abs(integrate(T, one, mask) - 10e-6) < 5e-9
