"""Tests for tools/transformer_flux.py.

The tool measures the transformer flux from the saved secondary voltages
instead of the ideal ``V*t_on/(N*Ae)`` square wave, so the tests have to pin
two things the earlier draft got wrong:

* one half-cycle crosses the *whole* peak-to-peak excursion -- the positive and
  negative halves are two measurements of the same swing, not two halves to be
  added;
* a "period" is two consecutive half-cycles, so the per-period list must step
  by two.  Overlapping pairs double every number and still look plausible.

The synthetic square waves below have closed-form volt-seconds, so the
arithmetic is checked against an answer rather than against itself.

Run:
    python -m pytest tools/test_transformer_flux.py -q
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

import transformer_flux as tf
from magnetics_design import CORE

JSON = tf.ROOT / "design/v3/magnetics/transformer_flux_100a.json"
RAW = tf.ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw"
FAULT_JSON = tf.ROOT / "design/v3/magnetics/transformer_flux_fault_48v.json"
FAULT_RAW = tf.ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.raw"
AE = float(CORE["Ae_m2"])
BSAT = float(CORE["Bsat_T"])


def square(periods: int = 3, samples_per_half: int = 101,
           high: float = 1.0, low: float = -1.0, dt: float = 1e-6):
    """A two-level drive with no sample exactly on a transition."""
    n = periods * 2 * samples_per_half
    t = np.arange(n, dtype=float) * dt
    v = np.empty(n)
    for i in range(n):
        v[i] = high if (i // samples_per_half) % 2 == 0 else low
    return t, v


# --------------------------------------------------------------- half cycles
def test_only_complete_half_cycles_are_kept():
    """The first and last segments of a window are cut short by the window
    edges; counting them would report a smaller swing than the drive has."""
    t, v = square(periods=3, samples_per_half=101)
    segments = tf.half_cycles(t, v)
    assert len(segments) == 4          # 6 halves; the first and last are cut short
    assert all(s["t_end_s"] > s["t_start_s"] for s in segments)


def test_a_half_cycle_carries_the_volt_seconds_of_the_whole_half_period():
    t, v = square(periods=2, samples_per_half=11, dt=1e-6)
    segment = tf.half_cycles(t, v)[0]
    # The first complete segment is the low half: 10 intervals at -1 V.  The
    # trapezoid spends one interval straddling the jump, which is exactly zero
    # for a symmetric +1/-1 edge.
    assert abs(segment["volt_seconds"]) == pytest.approx(10e-6, rel=1e-12)


def test_too_few_complete_half_cycles_is_an_error():
    t = np.linspace(0.0, 3.0, 301)
    with pytest.raises(ValueError):
        tf.flux_report(t, np.ones_like(t), AE)


# ------------------------------------------------------------------- flux
def test_the_half_cycle_swing_is_the_peak_to_peak_not_half_of_it():
    """This is the defect the first draft had: a symmetric drive moves the core
    from -B_ac to +B_ac in *one* half-cycle, so mean(positive) + mean(negative)
    is twice the excursion."""
    t, v = square(periods=3, samples_per_half=101, high=20.0, low=-20.0, dt=1e-7)
    report = tf.flux_report(t, v, AE)
    half_period = 100 * 1e-7
    expected = 20.0 * half_period / AE
    assert report["peak_to_peak_t"] == pytest.approx(expected, rel=1e-3)
    assert report["ac_amplitude_t"] == pytest.approx(expected / 2.0, rel=1e-3)


def test_a_symmetric_drive_has_no_per_period_imbalance():
    t, v = square(periods=4, high=37.0, low=-37.0, dt=1e-7)
    report = tf.flux_report(t, v, AE)
    assert report["cumulative_net_t"] == pytest.approx(0.0, abs=1e-12)
    assert report["max_abs_period_net_t"] == pytest.approx(0.0, abs=1e-12)
    assert report["signs_alternate"] is True


def test_periods_step_by_two_and_the_drift_adds_up_once():
    """An asymmetric square wave leaves eps of a half-swing every period.  With
    stride-2 pairing the cumulative drift after k periods is exactly k times
    the per-period net; overlapping pairs would double it."""
    periods, eps = 3, 0.10
    t, v = square(periods=periods, high=1.0, low=-(1.0 - eps), dt=1e-7)
    report = tf.flux_report(t, v, AE)
    half_period = 100 * 1e-7
    per_period = eps * 1.0 * half_period / AE
    # 3 periods -> 6 halves -> 4 complete halves -> 2 whole periods.  The 1 %
    # slack is the trapezoid spreading each jump over one sample.
    assert len(report["period_net_t"]) == 2
    assert report["period_net_t"][0] == pytest.approx(per_period, rel=2e-2)
    assert report["cumulative_net_t"] == pytest.approx(2 * report["period_net_t"][0], rel=1e-12)
    assert report["cumulative_abs_t"] == pytest.approx(2 * abs(report["period_net_t"][0]), rel=1e-12)


def test_the_drift_bound_is_never_smaller_than_one_period():
    t, v = square(periods=3, high=1.0, low=-0.8, dt=1e-7)
    report = tf.flux_report(t, v, AE)
    assert report["cumulative_abs_t"] >= report["max_abs_period_net_t"]


# -------------------------------------------------------------- deck values
def test_the_leakage_is_derived_from_the_decks_own_lp_and_k():
    const = tf.deck_constants()
    assert const["lp_h"] == pytest.approx(10e-6)
    assert const["k"] == pytest.approx(0.999)
    assert const["lsa_h"] == pytest.approx(10e-6 / 9.0)
    assert const["leakage_h"] == pytest.approx(10e-6 / 9.0 * (1 - 0.999 ** 2))


# ---------------------------------------------------------------- artefact
@pytest.fixture(scope="module")
def committed() -> dict:
    return json.loads(JSON.read_text(encoding="utf-8"))


def test_the_committed_report_is_the_one_the_tool_writes(committed):
    assert committed["status"].startswith("MEASUREMENT_ON_APPLIED_VOLT_SECONDS")
    assert committed["deck"] == tf.DECK
    assert set(committed["windings"]) == {"T1", "T4"}


def test_both_secondaries_agree_because_they_share_one_core(committed):
    """The A and B halves are separate windings on the same core.  They are
    compared on the alignment-free quantities only: each cumulative drift is
    referenced to its own first zero crossing, and the two halves cross zero a
    few tens of ns apart near the dead time."""
    for winding in committed["windings"].values():
        swing = winding["A"]["peak_to_peak_t"]
        assert winding["winding_agreement_t"] < 0.02 * swing
        for key in ("peak_to_peak_t", "delta_b_positive_half_t", "delta_b_negative_half_t"):
            assert winding["A"][key] == pytest.approx(winding["B"][key],
                                                      abs=0.02 * abs(winding["A"][key]))


def test_the_two_probed_transformers_are_the_same_measurement(committed):
    t1, t4 = committed["windings"]["T1"], committed["windings"]["T4"]
    assert t1["A"]["peak_to_peak_t"] == pytest.approx(t4["A"]["peak_to_peak_t"], abs=1e-9)
    assert t1["B"]["peak_to_peak_t"] == pytest.approx(t4["B"]["peak_to_peak_t"], abs=1e-9)


def test_the_results_are_internally_consistent(committed):
    r = committed["results"]
    assert r["peak_to_peak_t"] == pytest.approx(2.0 * r["ac_amplitude_t"], rel=1e-12)
    assert r["ac_amplitude_frac_bsat"] == pytest.approx(r["ac_amplitude_t"] / BSAT, rel=1e-12)
    assert r["peak_to_peak_frac_bsat"] == pytest.approx(r["peak_to_peak_t"] / BSAT, rel=1e-12)
    assert r["cumulative_abs_t"] >= abs(r["cumulative_net_t"])
    assert r["cumulative_abs_t"] >= r["max_abs_period_net_t"]


def test_the_measured_swing_matches_the_square_wave_formula_to_a_few_percent(committed):
    """Same quantity, two derivations.  A ratio near 2 means the peak-to-peak
    was built from two half-swings added together."""
    assert 0.90 < committed["results"]["measured_over_analytic"] < 1.10


def test_the_leakage_bound_is_a_small_fraction_of_the_swing(committed):
    r = committed["results"]
    assert 0.0 < r["leakage_flux_bound_t"] < 0.05 * r["peak_to_peak_t"]


def test_the_report_states_what_it_cannot_claim(committed):
    caveats = " ".join(committed["caveats"])
    assert "arbitrary" in caveats                       # no magnetizing current saved
    assert "T2/T3" in caveats                           # represented, not measured
    assert "linear" in caveats                          # no B-H saturation model
    assert committed["checks"]
    assert all(committed["checks"].values())


@pytest.mark.skipif(not RAW.is_file(), reason="the 313 MB raw is gitignored")
def test_the_committed_report_names_the_raw_it_came_from(committed):
    raw = committed["raw"]["path"]
    assert raw.endswith(RAW.name)
    stat = os.stat(raw)
    assert committed["raw"]["bytes"] == stat.st_size
    assert committed["raw"]["mtime"] == pytest.approx(stat.st_mtime, abs=1e-6)


@pytest.mark.skipif(not (JSON.exists() and RAW.is_file()),
                    reason="the 313 MB raw is not in Git")
def test_the_committed_numbers_regenerate_from_the_raw(committed):
    regenerated = tf.report(RAW)
    assert regenerated["windings"] == committed["windings"]
    assert regenerated["results"] == committed["results"]


# -------------------------------------------------------------- fault window
def test_the_fault_instant_comes_from_the_switch_ramp_not_the_pwl_start():
    """The control ramps 0->5 V over 2170..2180 us; the switch closes where the
    ramp crosses Vt.  Reading the first PWL point would put the fault 5 us early."""
    fault = tf.fault_instant(tf.ROOT / tf.FAULT_DECK)
    assert fault["absolute_us"] == pytest.approx(2175.0, abs=1e-9)
    assert fault["saved_us"] == pytest.approx(175.0, abs=1e-9)   # .tran Tstart = 2000 us
    assert fault["switch_threshold_v"] == pytest.approx(2.5)


def test_the_fault_split_measures_before_and_bounds_after():
    half, samples = 1e-6, 100
    dt = half / samples
    periods = 20
    t = np.arange(periods * 2 * samples, dtype=float) * dt
    v = np.where((np.arange(len(t)) // samples) % 2 == 0, 1.0, -1.0)
    tail = 20e-6
    t_post = t[-1] + dt + np.arange(int(tail / dt)) * dt
    t = np.concatenate([t, t_post])
    v = np.concatenate([v, np.full(len(t_post), 0.05)])
    result = tf.fault_window(t, v, AE, t[-len(t_post) - 1])
    assert result["pre_fault"]["peak_to_peak_t"] == pytest.approx(1.0 * half / AE, rel=1e-2)
    assert result["fault_segment_net_t"] == pytest.approx(0.05 * tail / AE, rel=1e-2)


def test_a_fault_with_no_room_on_one_side_is_an_error():
    t, v = square(periods=3)
    with pytest.raises(ValueError):
        tf.fault_window(t, v, AE, t[-2])


@pytest.fixture(scope="module")
def fault_committed() -> dict:
    return json.loads(FAULT_JSON.read_text(encoding="utf-8"))


def test_the_fault_report_is_the_48v_window(fault_committed):
    assert fault_committed["status"].startswith("APPLIED_VOLT_SECONDS_IN_THE_48V_FAULT")
    assert fault_committed["deck"] == tf.FAULT_DECK
    assert fault_committed["fault"]["saved_us"] == pytest.approx(175.0)
    assert set(fault_committed["windings"]) == {"T1"}


def test_the_fault_window_does_not_grow_the_swing(committed, fault_committed):
    """Same core, same drive, different deck: the pre-fault swing must land near
    the 100 A measurement.  A value near twice it would be halves added again."""
    steady = committed["results"]["peak_to_peak_t"]
    pre = fault_committed["results"]["pre_fault_peak_to_peak_t"]
    assert 0.9 < pre / steady < 1.1


def test_the_fault_results_are_internally_consistent(fault_committed):
    r = fault_committed["results"]
    assert r["pre_fault_peak_to_peak_t"] == pytest.approx(
        2.0 * r["pre_fault_ac_amplitude_t"], rel=1e-12)
    assert r["pre_fault_peak_to_peak_frac_bsat"] == pytest.approx(
        r["pre_fault_peak_to_peak_t"] / BSAT, rel=1e-12)
    assert r["pre_fault_ac_amplitude_frac_bsat"] == pytest.approx(
        r["pre_fault_ac_amplitude_t"] / BSAT, rel=1e-12)
    assert r["fault_segment_net_bound_frac_bsat"] == pytest.approx(
        r["fault_segment_net_bound_t"] / BSAT, rel=1e-12)
    assert r["fault_segment_net_bound_t"] > 0


def test_the_fault_segment_is_a_bound_not_a_measurement(fault_committed):
    """After the trip the two halves sit on their SRs, so their integrals stop
    being two views of one flux.  The report must take the larger and say why --
    averaging them would manufacture agreement that the physics does not have."""
    a = fault_committed["windings"]["T1"]["A"]["fault_segment_net_t"]
    b = fault_committed["windings"]["T1"]["B"]["fault_segment_net_t"]
    assert abs(a - b) > 0.10 * max(abs(a), abs(b))
    assert fault_committed["results"]["fault_segment_net_bound_t"] == pytest.approx(
        max(abs(a), abs(b)), rel=1e-12)
    assert "stop agreeing" in " ".join(fault_committed["caveats"])


def test_the_fault_bound_is_far_below_saturation(fault_committed):
    assert fault_committed["results"]["fault_segment_net_bound_frac_bsat"] < 0.05
    assert all(fault_committed["checks"].values())


@pytest.mark.skipif(not FAULT_RAW.is_file(), reason="the 1 GB fault raw is gitignored")
def test_the_committed_fault_numbers_regenerate_from_the_raw(fault_committed):
    regenerated = tf.fault_report(FAULT_RAW)
    assert regenerated["windings"] == fault_committed["windings"]
    assert regenerated["results"] == fault_committed["results"]
