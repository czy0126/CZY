"""Tests for tools/oc_network_check.py.

The tool only reads a raw, so the tests synthesise one.  That keeps them honest:
the expected divider gain and the expected trip current are written into the
fixture by hand, and the tool has to recover them from the file.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import ct_design
from oc_network_check import analyze, crossing_times, trapezoid_mean, whole_period_window

TRACES = ["V(sw)", "I(Lr)", "V(ocd)", "V(oc1)", "V(oc)"]
PERIOD = 5e-6
EDGE0 = 0.5e-6
DUTY = 0.5


def write_raw(path, t, columns):
    """A minimal LTspice ASCII raw: `i<TAB>t<TAB>v1` then one `\\t v` line per variable."""
    names = ["time"] + list(columns)
    lines = ["Title: synthetic", "Plotname: Transient Analysis", "Flags: real",
             f"No. Variables: {len(names)}", f"No. Points: {t.size}", "Variables:"]
    lines += [f"\t{i}\t{name}\t{name}" for i, name in enumerate(names)]
    lines.append("Values:")
    for k in range(t.size):
        # LTspice writes `index<TAB><TAB>time`, then one continuation line per
        # variable after time -- see tools/test_ascii_raw_window.py.
        lines.append(f"{k}\t\t{t[k]:.9e}")
        lines += [f"\t{columns[name][k]:.9e}" for name in columns]
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    return path


def square(t, high=48.0):
    phase = np.mod(t - EDGE0, PERIOD)
    return np.where(phase < DUTY * PERIOD, high, 0.0)


def fixture(path, gain=0.685714, burden_v=0.2, i_lr=10.0, span_us=130.0):
    t = np.arange(0.0, span_us * 1e-6, 2.5e-7)
    return write_raw(path, t, {
        "V(sw)": square(t),
        "I(Lr)": np.full(t.size, i_lr),
        "V(ocd)": np.full(t.size, burden_v),
        "V(oc1)": np.full(t.size, burden_v),
        "V(oc)": np.full(t.size, burden_v * gain),
    })


def test_crossing_times_interpolates_between_samples():
    t = np.array([0.0, 1.0, 2.0, 3.0])
    v = np.array([0.0, 4.0, 8.0, 12.0])
    crossings = crossing_times(t, v, 6.0)
    assert crossings.size == 1
    assert crossings[0] == pytest.approx(1.5)


def test_whole_period_window_ends_on_an_edge(tmp_path):
    raw = fixture(tmp_path / "a.raw")
    t, data = _read(raw)
    start, end, period = whole_period_window(t, data["V(sw)"], 22)
    assert period == pytest.approx(PERIOD, rel=1e-3)
    assert (end - start) / PERIOD == pytest.approx(22, rel=1e-3)
    assert t[-1] >= end > start


def test_trapezoid_mean_is_not_the_sample_mean():
    """A ramp sampled evenly: the trapezoid mean of the endpoints equals the exact one."""
    t = np.array([0.0, 1.0, 2.0])
    v = np.array([0.0, 2.0, 4.0])
    assert trapezoid_mean(v, t) == pytest.approx(2.0)


def test_the_measured_divider_gain_is_the_hand_written_one(tmp_path):
    """24k / (1k + 10k + 24k) = 0.685714: built into the fixture, recovered by the tool."""
    raw = fixture(tmp_path / "b.raw", gain=24 / 35)
    result = analyze(raw, 10.0, 10e3)
    assert result["measured"]["divider_gain"] == pytest.approx(24 / 35, rel=1e-5)
    assert result["measured"]["v_oc_mean_v"] == pytest.approx(0.2 * 24 / 35, rel=1e-5)
    assert result["residual"]["divider_gain"] == pytest.approx(0.0, abs=1e-6)


def test_the_burden_residual_is_a_ratio_not_a_voltage(tmp_path):
    """10 ohm at 20 A is 2.0 V, and the fixture's 0.3 V has to show up as -85 %."""
    raw = fixture(tmp_path / "c.raw", burden_v=0.3, i_lr=20.0)
    result = analyze(raw, 10.0, 10e3)
    predicted = ct_design.burden_average(20.0, 10.0)
    assert predicted == pytest.approx(2.0, rel=1e-15)
    assert result["predicted"]["v_ocd_mean_v"] == pytest.approx(predicted, rel=1e-5)
    # residuals are published to 4 decimals, so compare absolutely
    assert result["residual"]["v_ocd"] == pytest.approx((0.3 - predicted) / predicted, abs=1e-4)


def test_the_extrapolated_trip_scales_the_measured_peak_by_the_headroom(tmp_path):
    """The chain is linear, so the trip is just i_pk / headroom -- no bisection."""
    raw = fixture(tmp_path / "d.raw", gain=24 / 35)
    result = analyze(raw, 10.0, 10e3)
    headroom = 1 / (0.2 * 24 / 35)
    assert result["trip"]["headroom_ratio"] == pytest.approx(headroom, rel=1e-3)
    assert result["trip"]["extrapolated_a"] == pytest.approx(10.0 * headroom, rel=1e-3)
    # and the closed form, fed the fixture's own peak-to-average (1.0, it is a flat line)
    assert result["trip"]["from_algebra_a"] == pytest.approx(
        ct_design.trip_peak_current(1.0, r_burden=10.0, gain=24 / 35), rel=1e-3)


def test_a_window_without_enough_edges_is_rejected(tmp_path):
    raw = fixture(tmp_path / "e.raw", span_us=20.0)
    with pytest.raises(ValueError, match="switching edges"):
        analyze(raw, 10.0, 10e3)


def test_the_assumptions_are_stated(tmp_path):
    raw = fixture(tmp_path / "f.raw")
    assumptions = " ".join(analyze(raw, 10.0, 10e3)["assumptions"])
    assert "ideal" in assumptions and "junction capacitance" in assumptions


def _read(path):
    from ascii_raw_window import read_window

    return read_window(path, TRACES, 0.0, None)


def test_the_primary_current_is_read_from_the_right_column(tmp_path):
    raw = fixture(tmp_path / "g.raw", i_lr=13.88)
    result = analyze(raw, 47.0, 110e3)
    assert result["primary"]["i_pk_a"] == pytest.approx(13.88, rel=1e-6)
    assert result["primary"]["i_rms_a"] == pytest.approx(13.88, rel=1e-6)


def test_a_dead_burden_gives_no_headroom_rather_than_a_division_error(tmp_path):
    raw = fixture(tmp_path / "h.raw", burden_v=0.0, gain=0.0)
    result = analyze(raw, 10.0, 10e3)
    assert result["trip"]["headroom_ratio"] is None
    assert math.isnan(result["measured"]["divider_gain"])
