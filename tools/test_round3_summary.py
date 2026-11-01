"""Tests for round3_summary.primary_freq_khz.

The SR gate period jitters (+-1.3 %) and V(sw) edge detection at a fixed level
sometimes misses a transition (a 9.97 us gap) or catches a half-cycle
(2.49 us).  The primary frequency must be the median of the plausible
rise-to-rise intervals, not their mean and not the gate period.
"""

from __future__ import annotations

import numpy as np
import pytest

from round3_summary import primary_freq_khz

PERIOD = 4.985e-6


def square(t: np.ndarray, period: float, high: float = 48.0) -> np.ndarray:
    """Ideal square wave with one rise per period."""
    return np.where((t % period) < period / 2.0, high, 0.0)


def test_primary_freq_from_sw_ignores_missing_edge() -> None:
    t = np.arange(0.0, 60e-6, 2e-8)
    sw = square(t, PERIOD)
    # One rise fails to reach the 10 V level: that interval shows as ~9.97 us.
    sw = np.where((t > 22e-6) & (t < 26e-6), np.minimum(sw, 9.0), sw)
    data = {"V(sw)": sw, "V(out)": np.full_like(t, 1.89)}
    assert primary_freq_khz(t, data) == pytest.approx(1e-3 / PERIOD, rel=5e-3)


def test_primary_freq_ignores_spurious_rise() -> None:
    t = np.arange(0.0, 60e-6, 2e-8)
    sw = square(t, PERIOD)
    # A glitch rise mid-cycle splits one interval into 3.5 + 1.4 us.
    sw = np.where((t > 18.5e-6) & (t < 18.6e-6), 48.0, sw)
    data = {"V(sw)": sw, "V(out)": np.full_like(t, 1.89)}
    assert primary_freq_khz(t, data) == pytest.approx(1e-3 / PERIOD, rel=5e-3)


def test_primary_freq_refuses_half_cycle_only_trace() -> None:
    # Only 2.49 us intervals are visible: the tool must not call that the
    # primary period, it must report "no plausible interval".
    t = np.arange(0.0, 60e-6, 2e-8)
    sw = np.where(((t % (PERIOD / 2.0)) < PERIOD / 4.0), 48.0, 0.0)
    data = {"V(sw)": sw, "V(out)": np.full_like(t, 1.89)}
    assert np.isnan(primary_freq_khz(t, data))


def test_primary_freq_nan_when_no_edges() -> None:
    t = np.arange(0.0, 10e-6, 2e-8)
    data = {"V(sw)": np.zeros_like(t), "V(out)": np.full_like(t, 1.89)}
    assert np.isnan(primary_freq_khz(t, data))


def test_primary_freq_follows_gate_period_off_band() -> None:
    # 284.4 kHz soft-start snapshot: 3.52 us period, outside the 200.6 kHz band.
    period = 3.52e-6
    t = np.arange(0.0, 60e-6, 2e-8)
    sw = np.where((t % period) < period / 2.0, 48.0, 0.0)
    data = {"V(sw)": sw, "V(out)": np.full_like(t, 1.66)}
    assert primary_freq_khz(t, data, gate_period_s=period) == pytest.approx(
        1e-3 / period, rel=5e-3)


def test_primary_freq_respects_window_bounds() -> None:
    """A per-window query must not be answered by the whole file's median.

    The cold-start report asks for the frequency in successive windows of one
    8 ms raw.  The first 1 ms runs at a very different period than the settled
    end; if the edges are not scoped to the window, every row gets the same
    start-up-contaminated number (observed: 248.86 kHz in four windows while
    the settled gate was 201.1 kHz).
    """
    early, late = 5.0e-6, 3.333e-6
    t = np.arange(0.0, 200e-6, 2e-8)
    sw = np.where(t < 100e-6, square(t, early), square(t, late))
    data = {"V(sw)": sw, "V(out)": np.full_like(t, 1.89)}
    assert primary_freq_khz(t, data, gate_period_s=late, t0=100e-6, t1=200e-6) == pytest.approx(
        1e-3 / late, rel=5e-3)
    assert primary_freq_khz(t, data, gate_period_s=early, t0=0.0, t1=100e-6) == pytest.approx(
        1e-3 / early, rel=5e-3)
