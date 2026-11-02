"""Synthetic-array checks for the steady-state stress columns.

The raw files are not committed, so the arithmetic is tested on arrays with
known extrema.  The integration evidence lives in the JSON records.
"""
from __future__ import annotations

import numpy as np
import pytest

import steady_stress as ss


def _data(vout=(1.0, 1.0, 1.0)):
    t = np.array([0.0, 1.0, 2.0])
    d = {
        "V(out)": np.array(vout, dtype=float),
        "I(Lr)": np.array([-1.0, 2.0, -3.0]),
        "V(oc)": np.array([0.2, 0.8, 0.4]),
    }
    for n in ss.NODES:
        d[f"V({n})"] = np.array([0.0, 0.0, 0.0])
    for g in ss.GATES:
        d[f"V({g})"] = np.array([0.0, 5.0, 5.0])
    for n in ss.BRANCHES:
        d[f"I(VSa{n})"] = np.array([0.0, 0.0, 0.0])
        d[f"I(VSb{n})"] = np.array([0.0, 0.0, 0.0])
    return t, d


def test_vds_is_the_drain_node_because_the_source_is_sgnd():
    t, d = _data(vout=(1.0, 1.0, 1.0))
    d["V(a1)"] = np.array([2.0, 4.0, 3.0])
    out = ss.stress_block(t, d, rl=2.0)
    assert out["sr_vds"]["max_v"] == pytest.approx(4.0)
    assert out["sr_vds"]["min_v"] == pytest.approx(0.0)
    assert "sgnd" in out["sr_vds"]["reference"]


def test_forward_peak_is_the_negative_branch_current():
    t, d = _data()
    d["I(VSa1)"] = np.array([0.0, -7.0, 2.0])
    d["I(VSa4)"] = np.array([0.0, -5.0, 1.0])
    out = ss.stress_block(t, d, rl=2.0)
    assert out["sr_current"]["forward_peak_a"] == pytest.approx(7.0)
    assert out["sr_current"]["reverse_peak_a"] == pytest.approx(2.0)


def test_oc_margin_uses_the_peak_not_the_mean():
    t, d = _data()
    out = ss.stress_block(t, d, rl=2.0)
    assert out["oc"]["max_v"] == pytest.approx(0.8)
    assert out["oc"]["margin_to_trip"] == pytest.approx(0.8)
    assert out["oc"]["mean_v"] < out["oc"]["max_v"]


def test_gate_limits_span_every_instrumented_pair():
    t, d = _data()
    d["V(gb4)"] = np.array([-3.0, 7.0, 7.0])
    out = ss.stress_block(t, d, rl=2.0)
    assert out["sr_gate"]["min_v"] == pytest.approx(-3.0)
    assert out["sr_gate"]["max_v"] == pytest.approx(7.0)


def test_output_power_is_the_mean_of_the_square():
    t, d = _data(vout=(1.0, 2.0, 1.0))
    out = ss.stress_block(t, d, rl=2.0)
    # trapezoid average of v^2 = (1+4)/2 and (4+1)/2 averaged = 2.5
    assert out["pout_w"] == pytest.approx(2.5 / 2.0)
    assert out["iout_from_v_a"] == pytest.approx(3.0 / 2.0 / 2.0)


def test_input_block_uses_kcl_and_removes_the_mean():
    t, d = _data()
    d["I(Rin)"] = np.array([2.0, 2.0, 2.0])
    d["I(Cin)"] = np.array([0.0, 1.0, 0.0])
    out = ss.stress_block(t, d, rl=0.5)
    assert out["input"]["bridge_mean_a"] == pytest.approx(1.5)
    assert out["input"]["cin_ac_rms_a"] == pytest.approx(0.5)


def test_without_input_probes_there_is_no_input_block():
    t, d = _data()
    assert "input" not in ss.stress_block(t, d, rl=0.5)


def test_cout_ripple_is_rebuilt_from_the_four_sr_currents():
    t, d = _data(vout=(1.0, 1.0, 1.0))
    d["I(VSa1)"] = np.array([0.0, -0.5, -0.5])
    d["I(VSa4)"] = np.array([0.0, -0.25, -0.25])
    out = ss.stress_block(t, d, rl=0.5)
    # secondary total = 2 * 0.75 in the tail, zero at t=0
    assert out["cout_ripple"]["load_mean_a"] == pytest.approx(1.125)
    assert out["cout_ripple"]["ripple_pk_a"] == pytest.approx(1.125)
    assert out["cout_ripple"]["mean_check_pct"] == pytest.approx(
        100.0 * (1.125 - 2.0) / 2.0)
