"""The hot-fault extractor's arithmetic, on synthetic inputs only.

ELE-08 is a *steady-state-initialized* fault, so the extractor must answer two
questions the cold-start tool does not:

1. was the converter actually settled before the fault landed (``.ic V(ss)=4``
   is a starting condition, not a proof), and
2. where on the *rebased* saved axis did the fault engage?  ``Tstart`` shifts
   every stored timestamp, so the real deck's 2175 us PWL crossing is stored
   at 175 us.  The fixture below keeps its own synthetic absolute times; it
   exercises the same subtraction, not the shipped deck's numbers.
"""
from __future__ import annotations

import numpy as np
import pytest

import hot_fault_metrics as hf

DECK_TEXT = """\
.param VIN=48 RL=15.4m
.tran 0 1200u 880u 5n uic
.ic V(out)=1.89 V(ss)=4
Vfltctl_hot ctl_hot 0 PWL(0 0 1050u 0 1060u 5 1200u 5)
Sflt_hot out flt_hot ctl_hot 0 HOTFLT
Rflt_hot flt_hot 0 1m
.model HOTFLT SW(Ron=1m Roff=1G Vt=2.5)
.end
"""


def test_the_rebased_fault_instant_comes_from_tran_and_pwl_not_a_typed_offset():
    window = hf.saved_fault_window(DECK_TEXT)
    assert window["tstart_s"] == pytest.approx(880e-6)
    assert window["ramp_start_abs_s"] == pytest.approx(1050e-6)
    assert window["ramp_end_abs_s"] == pytest.approx(1060e-6)
    assert window["engage_abs_s"] == pytest.approx(1055e-6)
    # Saved axis = absolute minus Tstart.
    assert window["engage_rebased_s"] == pytest.approx(175e-6)


def test_the_saved_stop_is_tstop_minus_tstart_not_tstop():
    """A deck that stops at 1200 us and saves from 880 us ends its raw at
    320 us.  Comparing that against 1200 us would call a complete run a
    collapsed prefix -- the same axis trap as start-side measurements."""
    assert hf.saved_stop_s(DECK_TEXT) == pytest.approx(320e-6)


def test_the_fault_branch_is_ron_plus_the_series_resistor_from_the_deck():
    assert hf.fault_branch_ohm(DECK_TEXT) == pytest.approx(2e-3)


def test_a_steady_window_with_ripple_is_reported_with_its_ripple():
    t = np.linspace(0.0, 10e-6, 11)
    y = 2.0 + 0.01 * np.sin(np.linspace(0, 2 * np.pi, 11))
    stats = hf.window_stats(t, y, 0.0, 10e-6)
    assert stats["mean"] == pytest.approx(2.0, abs=1e-9)
    assert stats["pp"] > 0.0
    assert stats["min"] < stats["mean"] < stats["max"]


def test_pre_fault_stability_requires_both_soft_start_done_and_flat_vout():
    t = np.linspace(0.0, 50e-6, 501)
    d = {
        "V(out)": np.full_like(t, 1.89),
        "V(ss)": np.full_like(t, 5.0),
        "V(oc)": np.full_like(t, 0.68),
    }
    settled = hf.pre_fault_state(t, d, 0.0, 50e-6)
    assert settled["soft_start_finished"] is True
    assert settled["vout_flat"] is True
    assert settled["stable_at_design_point"] is True

    # Same flat output, but the soft start never reached regulation.
    d["V(ss)"] = np.full_like(t, 3.78)
    not_settled = hf.pre_fault_state(t, d, 0.0, 50e-6)
    assert not_settled["soft_start_finished"] is False
    assert not_settled["stable_at_design_point"] is False

    # Settled SS but the output still ramping by more than the drift limit.
    d["V(ss)"] = np.full_like(t, 5.0)
    d["V(out)"] = 1.80 + 0.10 * (t / t[-1])
    ramp = hf.pre_fault_state(t, d, 0.0, 50e-6)
    assert ramp["soft_start_finished"] is True
    assert ramp["vout_flat"] is False
    assert ramp["stable_at_design_point"] is False


def test_the_trip_delay_is_measured_from_engagement_not_from_zero():
    t = np.linspace(0.0, 300e-6, 3001)
    voc = np.where(t < 175e-6, 0.68, 0.68 + (t - 175e-6) * 1e4)
    trip = hf.trip_delay(t, voc, 175e-6, level=1.0)
    # 0.32 V at 1e4 V/s -> 32 us after engagement.
    assert trip["trip_s"] == pytest.approx(207e-6, abs=1e-6)
    assert trip["delay_from_engage_us"] == pytest.approx(32.0, abs=1.0)


def test_the_gate_report_distinguishes_a_latched_gate_from_a_low_one():
    """A shutdown bridge has no drain edge to reset the SR timing model, so a
    gate can re-assert with no switching.  The report must show that instead
    of repeating the old "drive stayed low until the end" claim."""
    t = np.linspace(0.0, 100e-6, 1001)
    latched = np.where(t < 60e-6, 0.0, 10.9)
    info = hf.gate_after_trip(t, latched, 50e-6)
    assert info["high_at_end"] is True
    assert info["high_fraction"] == pytest.approx(0.8, abs=5e-3)
    low = np.zeros_like(t)
    assert hf.gate_after_trip(t, low, 50e-6)["high_at_end"] is False
    # The 50 V record latches the *other* channel: the caller must look at
    # both, not assume channel A is the one that stays on.
    assert hf.gate_after_trip(t, np.where(t < 60e-6, 10.9, 0.0), 50e-6)["high_at_end"] is False


def test_the_log_parser_reads_elapsed_time_and_meas_results():
    text = """\
Total elapsed time: 261.447 seconds.
hot_oc_before: MAX(v(oc))=0.683414 FROM 0.00012 TO 0.00017
hot_oc_trip: v(oc)=1 AT 2.05e-4
"""
    log = hf.parse_log(text)
    assert log["solver_completed"] is True
    assert log["total_elapsed_s"] == pytest.approx(261.447)
    assert log["measurements"]["hot_oc_before"] == pytest.approx(0.683414)
    assert log["measurements"]["hot_oc_trip"] == pytest.approx(2.05e-4)


def test_a_killed_run_without_elapsed_time_is_not_reported_as_complete():
    log = hf.parse_log("Circuit: hot fault\n")
    assert log["solver_completed"] is False
    assert log["total_elapsed_s"] is None


def test_a_run_that_says_simulation_failed_is_not_reported_as_complete():
    """LTspice prints ``Total elapsed time`` before giving up as well, so the
    elapsed marker alone reports a hard convergence failure as a finished run.
    The 2 fF B control died this way at 264.515 us of 320 us."""
    log = hf.parse_log("Convergence Failure:  Time step too small; time = 0.00226451, timestep = 1.25e-18\n"
                       "Simulation Failed: Iteration limit reached\n"
                       "Total elapsed time: 1374.729 seconds.\n")
    assert log["solver_completed"] is False
    assert log["total_elapsed_s"] == pytest.approx(1374.729)
