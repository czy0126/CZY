"""Tests for tools/ct_design.py.

The chain is `mean(R_b*|i_sec|) * 24/(Rf+Rd1+Rd2)` -- linear in current, with no
clipping term.  Three tests are load-bearing:

  * `test_the_chain_is_linear_in_current` -- a CT secondary is a current source,
    so the burden sees i*R whatever the diode drop.  A clipped-rectifier model
    once lived here and was refuted by the deck (0.061 V predicted against
    0.834 V measured), taking the trip estimate from 24.2 A to 41.5 A.
  * `test_the_algebra_reproduces_the_measured_deck` -- the committed
    `oc_network_ct10.json` is the simulation's own answer; the closed form has
    to land within a couple of percent of it or the model has drifted again.
  * `test_the_deck_header_falls_out_of_the_sinusoidal_idealisation` -- the deck's
    own header states 0.04365 V/A and 22.9 A, and both must still appear.

The remaining tests pin the smaller pieces: divider gain, flux, burden power.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from ct_design import (
    AE_M2,
    BSAT_T,
    BURDEN_CHOICES,
    BURDEN_OHM,
    INTENDED_TRIP_A,
    N2_TURNS,
    RECT_FACTOR,
    R_D1_OHM,
    R_D2_OHM,
    R_F_OHM,
    TURNS_RATIO,
    V_OC_TRIP,
    burden_average,
    burden_for_trip,
    burden_power,
    compliance_voltage,
    divider_gain,
    evaluate,
    flux_peak,
    half_cycle_charge,
    oc_pin_voltage,
    schottky_drop,
    sinusoidal_average,
    trip_average_current,
    trip_peak_current,
)

ROOT = Path(__file__).resolve().parent.parent
MEASURED_10R = ROOT / "design/v3/bom/oc_network_ct10.json"
MEASURED_47R = ROOT / "design/v3/bom/oc_network_ct47.json"

GAIN = R_D2_OHM / (R_F_OHM + R_D1_OHM + R_D2_OHM)
I_PK = 13.88142


def test_divider_gain_includes_the_filter_resistor():
    """Rf sits ahead of the divider tap, so it belongs in the top leg: 24/35, not 24/34."""
    assert abs(divider_gain() - 24.0 / 35.0) < 1e-15
    assert abs(divider_gain() - R_D2_OHM / (R_D1_OHM + R_D2_OHM)) > 1e-3


def test_the_chain_is_linear_in_current():
    """Doubling the current doubles the burden volts: the bridge does not clip."""
    assert burden_average(20.0, 10.0) == pytest.approx(2 * burden_average(10.0, 10.0), rel=1e-15)
    assert burden_average(1.0, BURDEN_OHM) == pytest.approx(0.1, rel=1e-15)
    # nothing in the chain can make the output fall to zero at low current
    assert oc_pin_voltage(0.5, 10.0) > 0.0
    assert oc_pin_voltage(0.5, 10.0) < oc_pin_voltage(1.0, 10.0)


def test_the_diode_drop_is_compliance_voltage_not_signal_loss():
    """The burden average takes no Vf argument, and adding Vf only raises the flux."""
    assert "vf" not in burden_average.__code__.co_varnames
    assert "vf" not in oc_pin_voltage.__code__.co_varnames
    q, period = 2.2e-5, 5e-6
    without = flux_peak(q, period, 10.0, 0.0)
    with_vf = flux_peak(q, period, 10.0, compliance_voltage(0.0835))
    assert with_vf > without
    assert compliance_voltage(0.0835) == pytest.approx(2 * schottky_drop(0.0835))


def test_the_deck_header_falls_out_of_the_sinusoidal_idealisation():
    """sim/v3/*.cir states 0.04365 V/A and 22.9 A; both must fall out of the idealisation."""
    slope = sinusoidal_average(1.0, BURDEN_OHM) * GAIN
    assert slope == pytest.approx(0.04365, abs=5e-6)
    assert V_OC_TRIP / slope == pytest.approx(22.9, abs=0.05)
    assert abs(RECT_FACTOR - 2 / math.pi) < 1e-15


def test_trip_current_inverts_the_oc_pin_voltage():
    for r_b in BURDEN_CHOICES:
        i_trip = trip_average_current(r_burden=r_b)
        assert oc_pin_voltage(i_trip, r_b) == pytest.approx(V_OC_TRIP, rel=1e-12)


def test_a_larger_burden_trips_sooner():
    """47 ohm with the 110k divider would trip at 19.9 A -- under the intended 22.9 A."""
    trips = [trip_peak_current(1.6611, r_burden=r_b) for r_b in BURDEN_CHOICES]
    assert all(b < a for a, b in zip(trips, trips[1:]))
    assert trip_peak_current(1.6611, r_burden=47.0, gain=24 / 135) == pytest.approx(19.9, abs=0.1)


def test_the_as_built_burden_is_nearly_the_ideal_value():
    """10.58 ohm puts 22.9 A exactly on the threshold; the board has 10, i.e. 5.5 % off."""
    ideal = burden_for_trip(INTENDED_TRIP_A, 1.6611)
    assert ideal == pytest.approx(10.58, abs=0.05)
    assert abs(ideal / BURDEN_OHM - 1.0) < 0.06


def test_the_algebra_reproduces_the_measured_deck():
    """The committed measurement is the simulation's answer; the closed form must match it.

    This is the regression that a clipped-rectifier model cannot pass: it would
    predict 0.06 V where the deck measured 0.834 V.
    """
    data = json.loads(MEASURED_10R.read_text(encoding="utf-8"))
    i_avg = data["primary"]["i_avg_a"]
    r_b = data["network"]["burden_ohm"]
    measured = data["measured"]["v_ocd_mean_v"]
    predicted = burden_average(i_avg, r_b)
    assert predicted == pytest.approx(measured, rel=0.01)
    # and the trip reported by the measurement agrees with the closed form
    assert data["trip"]["extrapolated_a"] == pytest.approx(
        trip_peak_current(peak_to_average=data["primary"]["peak_to_average"], r_burden=r_b,
                          gain=data["measured"]["divider_gain"]), rel=0.02)


def test_the_model_scales_across_the_burden_change():
    """47 ohm should read 4.7x the burden volts of 10 ohm (minus the divider change)."""
    ten = json.loads(MEASURED_10R.read_text(encoding="utf-8"))["measured"]["v_ocd_mean_v"]
    forty_seven = json.loads(MEASURED_47R.read_text(encoding="utf-8"))["measured"]["v_ocd_mean_v"]
    assert forty_seven / ten == pytest.approx(47.0 / BURDEN_OHM, rel=0.03)


def test_flux_includes_the_compliance_voltage_and_stays_far_below_saturation():
    q, period = 2.2e-5, 5e-6
    vf = compliance_voltage(0.0835)
    expected = (10.0 * q / TURNS_RATIO + vf * 0.5 * period) / (N2_TURNS * AE_M2)
    assert flux_peak(q, period, 10.0, vf) == pytest.approx(expected, rel=1e-15)
    assert flux_peak(q, period, 100.0, vf) / BSAT_T < 0.05


def test_burden_power_scales_with_resistance():
    assert burden_power(9.45, 20.0) == pytest.approx(2 * burden_power(9.45, 10.0), rel=1e-15)
    assert burden_power(9.45, 10.0) == pytest.approx(0.0893, abs=1e-4)


def test_evaluate_reports_one_row_per_burden():
    measured = {"q_half_c": 2.2e-5, "period_s": 5e-6, "i_avg_a": 8.36,
                "i_rms_a": 9.45, "i_pk_a": 13.88, "peak_to_average": 1.661}
    rows = evaluate(measured)
    assert [row["burden_ohm"] for row in rows] == list(BURDEN_CHOICES)
    assert rows[0]["trip_peak_a"] == pytest.approx(24.2, abs=0.4)
    assert rows[0]["trip_margin_vs_rated"] == pytest.approx(1.74, abs=0.03)


def test_half_cycle_charge_of_a_sinusoid_matches_the_closed_form(tmp_path):
    """Q_half = I_pk/(pi*f) for a sinusoid; check the raw-window path reproduces it."""
    f, i_pk = 200.622e3, 13.88142
    period = 1.0 / f
    t = np.arange(0.0, 22 * period, period / 400.0)
    i = i_pk * np.sin(2 * np.pi * f * t)
    header = ("Title: t\nPlotname: Transient Analysis\nFlags: real forward nocompression\n"
              "No. Variables: 2\nNo. Points:            0\nVariables:\n\t0\ttime\ttime\n"
              "\t1\tI(Lr)\tcurrent\nValues:\n")
    lines = [header]
    for idx, (tt, ii) in enumerate(zip(t, i)):
        lines.append(f"{idx}\t\t{tt:.12e}\n\t{ii:.12e}\n")
    raw = tmp_path / "ct.raw"
    raw.write_text("".join(lines), encoding="latin-1")

    out = half_cycle_charge(raw, 0.0, 22 * period * 1e6)
    assert out["q_half_c"] == pytest.approx(i_pk / (np.pi * f), rel=1e-2)
    assert out["i_pk_a"] == pytest.approx(i_pk, rel=1e-2)
    # a sinusoid's peak-to-average is pi/2, whatever the frequency
    assert out["peak_to_average"] == pytest.approx(np.pi / 2, rel=2e-2)
