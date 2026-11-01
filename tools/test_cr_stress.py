"""Tests for tools/cr_stress.py.

Integrating the series current gives the capacitor voltage, so the tests use
waveforms whose integral has a closed form: a constant current (a ramp) and a
sinusoid (1/(wC) amplitude).
"""

from __future__ import annotations

import numpy as np
import pytest

from cr_stress import cr_voltage, esr_ceiling


def ramp_setup(i_a: float, c_f: float, t_end: float = 10e-6, n: int = 10001):
    t = np.linspace(0.0, t_end, n)
    return t, np.full_like(t, i_a), c_f


def test_constant_current_gives_a_linear_ramp_of_slope_i_over_c():
    t, i, c = ramp_setup(2.0, 1e-6)
    out = cr_voltage(t, i, c)
    expected_pp = 2.0 * 10e-6 / 1e-6      # I*t/C
    assert abs(out["v_pp"] - expected_pp) < 1e-9
    # slope check on the raw swing, independent of the mean-centring:
    # at the midpoint the charge is I*t_mid/C = 2 A * 5 us / 1 uF = 10 V
    mid = out["v"][len(t) // 2] - out["v"][0]
    assert abs(mid - 10.0) < 1e-9


def test_sinusoid_amplitude_is_one_over_omega_c():
    t = np.linspace(0.0, 10e-6, 20001)
    f, i_pk, c = 200.0e3, 10.0, 0.62e-6
    i = i_pk * np.sin(2 * np.pi * f * t)
    out = cr_voltage(t, i, c)
    expected_pp = 2 * i_pk / (2 * np.pi * f * c)
    assert abs(out["v_pp"] - expected_pp) / expected_pp < 1e-3


def test_v_dc_sets_the_absolute_level():
    t, i, c = ramp_setup(1.0, 1e-6)
    grounded = cr_voltage(t, i, c)
    raised = cr_voltage(t, i, c, v_dc=24.0)
    assert abs(raised["v_mean"] - 24.0) < 1e-9
    assert abs(raised["v_max"] - grounded["v_max"] - 24.0) < 1e-9


def test_integer_periods_return_to_the_starting_charge():
    t = np.linspace(0.0, 3 / 200.6e3, 20001)
    i = 13.88 * np.sin(2 * np.pi * 200.6e3 * t)
    assert abs(cr_voltage(t, i, 0.62e-6)["periodicity_residual_v"]) < 1e-6


def test_non_integer_periods_leave_a_residual_that_is_reported_not_hidden():
    t = np.linspace(0.0, 1.5 / 200.6e3, 20001)
    i = 13.88 * np.sin(2 * np.pi * 200.6e3 * t)
    assert abs(cr_voltage(t, i, 0.62e-6)["periodicity_residual_v"]) > 1.0


def test_esr_ceiling_follows_i_squared():
    assert abs(esr_ceiling(9.45, 1.0) - 1.0 / 9.45**2) < 1e-15
    # doubling the current quarters the allowed ESR
    assert abs(esr_ceiling(18.9, 1.0) - esr_ceiling(9.45, 1.0) / 4) < 1e-15
    with pytest.raises(ValueError):
        esr_ceiling(0.0, 1.0)


def test_zero_capacitance_is_rejected():
    t, i, _ = ramp_setup(1.0, 1e-6)
    with pytest.raises(ValueError):
        cr_voltage(t, i, 0.0)
