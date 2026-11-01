"""Tests for tools/fault_metrics.py (pure helpers, no raw loading)."""

from __future__ import annotations

import numpy as np
import pytest

from fault_metrics import engage_time, first_up, low_runs


def test_engage_time_is_the_2p5_v_crossing_of_the_ramp() -> None:
    # Legacy deck: 0->5 V ramp from 3.9 to 4.0 ms crosses 2.5 V at 3.95 ms.
    assert engage_time(3.9e-3, 4.0e-3) == pytest.approx(3.95e-3)
    # Round-4 cold_oc deck: 5.5 -> 5.6 ms crosses 2.5 V at 5.55 ms.
    assert engage_time(5.5e-3, 5.6e-3) == pytest.approx(5.55e-3)


def test_first_up_ignores_samples_before_the_engagement() -> None:
    t = np.array([0.0, 1e-3, 2e-3, 3e-3])
    y = np.array([5.0, 5.0, 0.0, 5.0])
    assert first_up(t, y, 1.0, 1.5e-3) == 3e-3
    assert first_up(t, y, 1.0, 3.5e-3) is None


def test_low_runs_splits_and_marks_an_open_ended_tail() -> None:
    t = np.linspace(0.0, 10e-6, 11)
    y = np.concatenate([np.ones(3), np.zeros(2), np.ones(3), np.zeros(3)])
    runs = low_runs(t, y, 1.0, 0.0)
    assert len(runs) == 2
    assert runs[0][0] == t[3] and runs[0][1] == t[4] and runs[0][2] is False
    assert runs[1][0] == t[8] and runs[1][1] == t[-1] and runs[1][2] is True
