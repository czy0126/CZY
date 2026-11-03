"""The direct cold-start burden record must agree with the derived one.

This file guards two different things:

* the arithmetic of ``waveform_stats`` (a synthetic square pulse has a known
  answer, so a unit or weighting slip cannot hide);
* the committed record: every check true, the peak and energy inside 3 % of the
  derived record, and the first 200 us reproducible from the raw.

The raw is ~14 GB and lives outside Git, so the raw-derived tests skip when it
or the record is absent -- CI still validates the shipped JSON's invariants.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import startup_burden_direct as direct

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "design/v3/bom/startup_burden_direct.json"
LEVELS = {"quarter_of_p70": 0.375, "p70": 1.5}


def test_a_square_pulse_has_the_obvious_energy_and_mean():
    t = np.linspace(0.0, 1e-3, 1001)
    volts = np.ones_like(t)
    data = {"V(ocd)": volts, "V(ocm)": np.zeros_like(t), "I(Rbur)": volts,
            "V(out)": 2.0 * volts, "V(ss)": volts}
    stats = direct.waveform_stats(t, data, 1.0, LEVELS)
    assert stats["peak_w"] == 1.0
    assert stats["energy_mj"] == pytest.approx(1.0, rel=1e-6)
    assert stats["mean_mw"] == pytest.approx(1000.0, rel=1e-6)
    assert stats["peak_voltage_v"] == 1.0
    assert stats["time_above"]["above_quarter_of_p70_us"] == pytest.approx(1000.0, rel=1e-3)
    assert stats["time_above"]["above_p70_us"] == 0.0


def test_a_reversed_zero_crossing_carries_little_energy():
    t = np.linspace(0.0, 1e-3, 1001)
    volts = np.ones_like(t)
    volts[500:503] = -0.01  # a millivolt-scale dip, as the bridge model makes
    data = {"V(ocd)": volts, "V(ocm)": np.zeros_like(t), "I(Rbur)": volts,
            "V(out)": volts, "V(ss)": volts}
    stats = direct.waveform_stats(t, data, 1.0, LEVELS)
    assert stats["voltage_min_v"] == -0.01
    assert stats["negative_samples"] == 3
    assert stats["negative_energy_share"] < 1e-3


def test_a_genuine_inversion_exceeds_the_energy_bound():
    t = np.linspace(0.0, 1e-3, 1001)
    volts = np.ones_like(t)
    volts[:500] = -1.0  # half the record reversed: not a zero-crossing artifact
    data = {"V(ocd)": volts, "V(ocm)": np.zeros_like(t), "I(Rbur)": volts,
            "V(out)": volts, "V(ss)": volts}
    stats = direct.waveform_stats(t, data, 1.0, LEVELS)
    assert stats["negative_energy_share"] > 1e-3


def test_the_comparison_is_elementwise_and_signed():
    diff = direct.comparison({"peak_w": 1.02, "t_peak_ms": 1.30, "energy_mj": 0.78},
                             {"peak_w": 1.00, "t_peak_ms": 1.29, "energy_mj": 0.80,
                              "source": "x.json"})
    assert diff["peak_deviation_pct"] == pytest.approx(2.0, rel=1e-6)
    assert diff["energy_deviation_pct"] == pytest.approx(-2.5, rel=1e-6)
    assert diff["t_peak_shift_ms"] == pytest.approx(0.01)


def test_the_reference_is_the_derived_record_not_a_copy():
    reference = direct.derived_reference()
    derived = json.loads(direct.DERIVED_JSON.read_text(encoding="utf-8"))
    assert reference["peak_w"] == derived["results"]["startup"]["peak_w"]
    assert reference["source"].endswith("startup_burden_pulse.json")


@pytest.mark.skipif(not RECORD.is_file(), reason="direct record not generated yet")
def test_every_shipped_check_is_true():
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert record["checks"]["ok"] is True
    for name, value in record["checks"].items():
        assert value is True, name


@pytest.mark.skipif(not RECORD.is_file(), reason="direct record not generated yet")
def test_the_record_is_internally_consistent():
    results = json.loads(RECORD.read_text(encoding="utf-8"))["results"]
    measured, rating = results["measured"], results["rating"]
    assert measured["peak_w"] == pytest.approx(measured["peak_voltage_v"] ** 2
                                               / results["burden_ohm"], rel=1e-4)
    assert rating["peak_over_p70"] == pytest.approx(
        measured["peak_w"] / rating["rated_power_w"], rel=1e-4)
    assert abs(results["direct_vs_derived"]["peak_deviation_pct"]) < 3.0
    assert abs(results["direct_vs_derived"]["energy_deviation_pct"]) < 3.0


@pytest.mark.skipif(not (RECORD.is_file() and direct.RAW.is_file()),
                    reason="cold-start burden raw is gitignored")
def test_the_first_200_microseconds_reproduce_from_the_raw():
    from ascii_raw_window import read_window

    results = json.loads(RECORD.read_text(encoding="utf-8"))["results"]
    recorded = results["head_slice"]
    t, data = read_window(direct.RAW, direct.COLUMNS, 0.0, direct.HEAD_SLICE_S)
    levels = direct.derived.thresholds(direct.derived.candidate_rating())
    regenerated = direct.waveform_stats(t, data, results["burden_ohm"], levels)
    assert regenerated["samples"] == recorded["samples"]
    assert regenerated["peak_w"] == recorded["peak_w"]
    assert regenerated["energy_mj"] == recorded["energy_mj"]
