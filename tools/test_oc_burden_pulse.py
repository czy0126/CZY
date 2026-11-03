"""The burden pulse must be an integral of V^2/R, not a mean-voltage square."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import oc_burden_pulse as pulse

ROOT = Path(__file__).resolve().parent.parent
COMMITTED = ROOT / "design/v3/bom/oc_burden_pulse.json"


def test_a_flat_waveform_is_the_rectangular_case():
    t = np.array([0.0, 1.0])
    v = np.array([2.0, 2.0])
    out = pulse.pulse(t, v, 10.0)
    assert out["peak_w"] == pytest.approx(0.4)
    assert out["mean_w"] == pytest.approx(0.4)
    assert out["energy_j"] == pytest.approx(0.4)
    assert out["equivalent_width_us"] == pytest.approx(1e6)


def test_the_energy_is_the_trapezoid_and_not_the_mean_voltage_squared():
    # v ramps 0 -> 10 V, so p ramps 0 -> 10 W and E = 0.5 * 10 W * 100 us.
    t = np.array([0.0, 100e-6])
    v = np.array([0.0, 10.0])
    out = pulse.pulse(t, v, 10.0)
    assert out["energy_j"] == pytest.approx(0.5e-3)
    # (mean v)^2 / R would give 2.5 W * 100 us = 0.25 mJ -- half as much.
    assert out["energy_j"] != pytest.approx(0.25e-3)
    assert out["peak_w"] == pytest.approx(10.0)
    assert out["equivalent_width_us"] == pytest.approx(50.0)


def test_a_single_sample_is_refused():
    with pytest.raises(ValueError):
        pulse.pulse(np.array([0.0]), np.array([1.0]), 10.0)


def test_the_burden_value_comes_from_the_deck_element():
    deck = "D1 cs1 ocd DSCH\nRbur ocd ocm 10\nRf ocd oc1 1k\n"
    assert pulse.burden_ohm(deck) == 10.0
    assert pulse.burden_ohm(deck.replace("Rbur ocd ocm 10", "Rbur ocd ocm 47")) == 47.0


def test_a_deck_without_the_burden_is_refused():
    with pytest.raises(ValueError):
        pulse.burden_ohm("Rf ocd oc1 1k\n")


@pytest.fixture(scope="module")
def record() -> dict:
    return json.loads(COMMITTED.read_text(encoding="utf-8"))


def test_the_stored_identity_holds(record: dict) -> None:
    for run in record["results"]["runs"]:
        f = run["fault"]
        assert f["energy_mj"] * 1e-3 == pytest.approx(
            f["mean_w"] * f["duration_us"] * 1e-6, abs=1e-6)
        assert f["equivalent_width_us"] == pytest.approx(
            f["energy_mj"] * 1e-3 / f["peak_w"] * 1e6, rel=1e-3)
        assert f["peak_w"] >= f["mean_w"]


def test_the_steady_power_is_not_the_mean_voltage_squared(record: dict) -> None:
    # A rectified CT waveform has form factor > 1, so mean(V^2)/R exceeds
    # mean(V)^2/R.  SOURCE-05 quoted the latter as the resistor's dissipation.
    for run in record["results"]["runs"]:
        pre = run["pre_fault"]
        assert pre["form_factor"] > 1.0
        assert pre["mean_w"] > pre["mean_voltage_squared_w"]
        assert pre["mean_w"] == pytest.approx(
            pre["mean_voltage_squared_w"] * pre["form_factor"] ** 2, rel=1e-3)


def test_every_run_reached_the_saved_stop(record: dict) -> None:
    assert record["checks"]["every_run_reached_the_saved_stop"]
    assert record["checks"]["the_burden_is_ten_ohms_everywhere"]
    for run in record["results"]["runs"]:
        assert run["window"]["reached_saved_stop"]


def test_each_50v_benefit_uses_its_own_complete_topology_matched_control(record: dict) -> None:
    """The base must be complete: a stalled control prices a prefix.

    The exactly-paired threshold-muted control stops at 250.151/254.980 us, so
    it cannot answer "how much energy does the burden see over the 320 us
    window".  That comparison is kept in the PROT-03 paired record instead.
    """
    by_run = {run["run"]: run for run in record["results"]["runs"]}
    for b in record["results"]["benefits"]:
        base = by_run[b["base_run"]]
        assert base["role"] == "base"
        assert base["vin_v"] == b["vin_v"]
        if b["vin_v"] == 50.0:
            assert base["deck"].endswith("_noclamp_control.cir")
            assert base["window"]["reached_saved_stop"]
    # The declared 50 V parent is kept as an unpaired reference only.
    assert by_run["50v_parent_reference"]["role"] == "reference"
    assert not any(b["base_run"] == "50v_parent_reference"
                   for b in record["results"]["benefits"])
    assert record["checks"]["the_50v_base_is_a_complete_topology_matched_control"]


def test_the_benefit_numbers_are_recomputable_from_the_rows(record: dict) -> None:
    by_run = {run["run"]: run for run in record["results"]["runs"]}
    for b in record["results"]["benefits"]:
        base = by_run[b["base_run"]]["fault"]
        cand = by_run[b["candidate_run"]]["fault"]
        assert b["energy_reduction_pct"] == pytest.approx(
            (base["energy_mj"] - cand["energy_mj"]) / base["energy_mj"] * 100.0, abs=0.01)
        assert b["peak_reduction_pct"] == pytest.approx(
            (base["peak_w"] - cand["peak_w"]) / base["peak_w"] * 100.0, abs=0.01)


def test_the_record_does_not_turn_the_peak_into_a_pass_fail(record: dict) -> None:
    assert record["results"]["pulse_curve_available"] is False
    assert record["checks"]["the_peak_is_not_reported_as_a_continuous_rating"]
    text = " ".join(record["results"]["limits"])
    assert "not a pass/fail" in text
    assert "startup pulse is not part of this record" in text
    assert "startup_burden_direct.py" in text
