"""Guards for the step-length operating-point audit (ELE-09 follow-up).

The committed JSON cannot be rebuilt in CI (the four raws are not in Git), so
these tests pin the metric definitions on synthetic data and then check that
the shipped record still carries its own invariants.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import sr_step_operating_point as s

OUT = Path(__file__).resolve().parent.parent / "design/v3/stage_f/sr_step_operating_point.json"


def synthetic() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Three gate periods, a diode pulse in the middle of each."""
    fs = 1e-9
    t = np.arange(0.0, 22e-6, fs)
    gate = np.where((t % 5e-6) < 2e-6, 10.0, 0.0)
    pulse = np.zeros_like(t)
    for start in (2.0e-6, 7.0e-6, 12.0e-6):
        pulse[(t >= start) & (t < start + 100e-9)] = 10.0
    vds = np.where(pulse > 0, -0.8, -0.001)
    d = {"V(out)": np.full_like(t, 1.9), "V(ga1)": gate,
         "V(xsa1:di)": vds, "V(xsa1:si)": np.zeros_like(t),
         "I(xsa1:Dbd)": pulse}
    return t, d


def test_period_metrics_measure_the_pulse_it_is_given() -> None:
    t, d = synthetic()
    spans = s.periods(t, d["V(ga1)"])
    assert len(spans) == 3
    row = s.period_metrics(t, d, spans[0])
    assert row["on_time_ns"] == pytest.approx(2000.0, rel=1e-3)
    assert row["charge_uc"] == pytest.approx(1.0, rel=1e-2)     # 10 A x 100 ns
    assert row["peak_a"] == pytest.approx(10.0)
    assert row["vout_mean_v"] == pytest.approx(1.9)
    # 0.8 V x 10 A x 100 ns over a 4.985 us period
    assert row["diode_loss_w"] == pytest.approx(0.8e-6 / 4.985e-6, rel=2e-2)


def test_quadrature_rules_agree_on_a_smooth_integrand() -> None:
    t, d = synthetic()
    spans = s.periods(t, d["V(ga1)"])
    spread = s.quadrature_spread(t, d, spans)
    assert spread["max_rel_charge"] < 0.02
    assert spread["max_rel_loss"] < 0.05


def test_rank_inversion_is_the_inverse_ordering() -> None:
    assert s.rank([10.0, 30.0, 20.0]) == [0, 2, 1]
    vout = [1.8848, 1.8894, 1.8980, 1.9040]   # ascending 2n, 5n, 1n, 0.5n
    loss = [0.5795, 0.4902, 0.4048, 0.2950]   # descending in the same order
    assert s.rank(loss) == [len(vout) - 1 - r for r in s.rank(vout)]


def test_the_committed_record_still_carries_its_invariants() -> None:
    if not OUT.exists():
        pytest.skip("operating-point audit not generated locally")
    j = json.loads(OUT.read_text(encoding="utf-8"))
    r, c = j["results"], j["checks"]
    assert all(c.values()), c
    assert len(r["steps_ns"]) == 4
    # The claim is that the files differ far more than the integration rule.
    assert r["quadrature_within_raw_max_rel"] < 0.02
    assert r["charge_cross_raw_rel"] > 10 * r["quadrature_within_raw_max_rel"]
    # And that they are not sitting on the same operating point.
    assert r["vout_spread_mv"] > 10.0
    assert r["on_time_spread_ns"] > 50.0
    assert r["loss_vs_vout_inverse_monotone"] is True
    # The sensitivity is derived from the two spreads, not remembered
    # separately, so it has to stay consistent with them.
    assert r["diode_loss_spread_x8_w"] == pytest.approx(
        8.0 * (max(r["diode_loss_w"]) - min(r["diode_loss_w"])), rel=1e-12)
    assert r["sr_loss_per_volt_w"] == pytest.approx(
        r["diode_loss_spread_x8_w"] / (r["vout_spread_mv"] * 1e-3), rel=1e-9)
    assert r["sr_loss_sensitivity_vs_port"] == pytest.approx(
        r["sr_loss_per_volt_w"] / r["port_w_per_volt_w"], rel=1e-9)
    # Same order as the port's 2V/RL: that is what makes the operating point,
    # not the integration rule, decide the size of this term.
    assert 0.2 < r["sr_loss_sensitivity_vs_port"] < 5.0
