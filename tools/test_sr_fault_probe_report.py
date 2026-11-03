"""The probe report may describe a high gate; it must never call that safe."""
from __future__ import annotations

import numpy as np
import pytest

import sr_fault_probe_report as report


def test_a_short_gate_spike_is_not_a_sustained_rise():
    t = np.arange(0, 5e-6, 5e-9)
    gate = np.zeros_like(t)
    gate[100:102] = 12.0          # 10 ns spike, shorter than the 200 ns debounce
    gate[300:] = 12.0             # real latch
    rise = report.last_sustained_rise(t, gate, after=0.0)
    assert rise == float(t[300])


def test_summarize_reports_the_high_device_and_its_forward_i2t():
    t = np.arange(0, 10e-6, 10e-9)
    data = {}
    for pair in report.PAIRS:
        for side in report.SIDES:
            gate, vds, current = report.device_traces(pair, side)
            data[gate] = np.zeros_like(t)
            data[vds] = np.zeros_like(t)
            data[current] = np.zeros_like(t)
    gate, vds, current = report.device_traces(2, "b")
    high = t >= 4e-6
    data[gate][high] = 12.0
    data[current][high] = -100.0  # negative I(VS) is forward conduction
    out = report.summarize(t, data, trip_s=1e-6, saved_stop_s=10e-6)

    assert out["any_gate_high_at_end"] is True
    assert out["devices_high_at_end"] == ["2B"]
    assert out["reached_tstop"] is True
    row = out["devices"]["2B"]
    assert abs(row["gate_last_rise_us"] - 4.0) < 0.02
    assert row["i_forward_peak_post_a"] == 100.0
    assert abs(row["i2t_forward_post_a2s"] - 100.0**2 * 6e-6) / (100.0**2 * 6e-6) < 0.01
    assert abs(row["conduction_while_gate_high_a"] - 100.0) < 1e-9
    assert out["devices"]["1A"]["gate_high_at_end"] is False
    # The same device is high only in the final interval, so the latch block
    # and the post-trip total coincide here.
    assert out["final_latch_devices"] == ["2B"]
    assert abs(out["devices"]["2B"]["final_latch"]["i_abs_max_a"] - 100.0) < 1e-9
    assert abs(out["devices"]["2B"]["final_latch"]["i2t_abs_a2s"]
               - 100.0**2 * 6e-6) / (100.0**2 * 6e-6) < 0.01


def test_the_final_latch_is_only_the_rise_that_survives_to_the_end():
    t = np.arange(0, 10e-6, 10e-9)
    gate = np.zeros_like(t)
    gate[300:500] = 12.0     # high, then released
    gate[700:] = 12.0        # final latch
    assert report.final_high_start(t, gate, after=1e-6) == float(t[700])
    # A gate that is high for a while but low at the end is not a latch.
    gate2 = np.zeros_like(t)
    gate2[300:500] = 12.0
    assert report.final_high_start(t, gate2, after=1e-6) is None


def test_drive_release_comes_from_the_first_low_run_longer_than_10us():
    t = np.arange(0, 30e-6, 10e-9)
    gate = np.full_like(t, 12.0)
    gate[500:520] = 0.0      # 200 ns drive edge, not a release
    gate[1000:] = 0.0        # released from 10 us on
    assert abs(report.drive_release_us(t, gate, trip_s=0.0) - 10.0) < 0.01
    # No sustained low at all -> no release time, not a zero.
    assert report.drive_release_us(t, np.full_like(t, 12.0), trip_s=0.0) is None


def test_latch_i2t_is_separate_from_the_normal_on_time_after_trip():
    """285 A during the release delay must not be billed to the final latch."""
    t = np.arange(0, 10e-6, 10e-9)
    gate = np.zeros_like(t)
    current = np.zeros_like(t)
    vds = np.zeros_like(t)
    gate[100:200] = 12.0      # gate still on from the switching cycle
    current[100:200] = -250.0
    gate[700:] = 12.0         # final latch in the dead state
    current[700:] = -1.0
    row = report.device_summary(t, gate, vds, current, trip_s=0.0)
    assert row["i_forward_peak_post_a"] == 250.0
    assert row["final_latch"]["i_abs_max_a"] == 1.0
    assert abs(row["final_latch"]["i2t_abs_a2s"] - 1.0**2 * 3e-6) / 3e-6 < 0.01


def test_a_raw_without_eight_device_probes_is_refused_not_summarized():
    """The base hot-fault raw saves pair 1/4 only; it must not be read as eight."""
    t = np.arange(0, 5e-6, 10e-9)
    data = {"V(ga1)": np.zeros_like(t), "V(gb1)": np.zeros_like(t)}
    with pytest.raises(ValueError, match="lacks eight-device probes"):
        report.require_traces(data)


def test_a_truncated_record_is_a_prefix_not_a_pass():
    t = np.arange(0, 9e-6, 10e-9)
    data = {}
    for pair in report.PAIRS:
        for side in report.SIDES:
            gate, vds, current = report.device_traces(pair, side)
            data[gate] = np.zeros_like(t)
            data[vds] = np.zeros_like(t)
            data[current] = np.zeros_like(t)
    out = report.summarize(t, data, trip_s=1e-6, saved_stop_s=10e-6)
    assert out["reached_tstop"] is False
    assert out["solver_prefix_only"] is True


def test_timing_can_come_from_a_convergence_record():
    # The 50 V eight-device deck is a child of the cshunt variant; its trip
    # must be the variant's, not the stalled base record's 214.915 us.
    spec = report.CASES["50v_120a_cshunt"]
    base = {"results": {"variant": {"trip_s": 215.01441126260292e-6},
                        "variant_saved_stop_s": 319.99999999999994e-6}}
    assert report.timing(base, spec) == (215.01441126260292e-6, 319.99999999999994e-6)
    # Hot-fault records keep their own shape and are read at the top level.
    assert report.timing({"fault": {"trip_s": 1e-4}, "saved_stop_s": 3.2e-4}, {}) == (1e-4, 3.2e-4)
