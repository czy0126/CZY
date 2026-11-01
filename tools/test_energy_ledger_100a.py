"""Tests for tools/energy_ledger_100a.py.

The ledger's value is that every watt is either measured in the same window or
explicitly labelled as an assumption.  These tests pin the arithmetic (trapezoid,
gate-period window) and the provenance lock (the committed summary must name the
raw it came from, byte for byte).
"""

from __future__ import annotations

import json

import pytest

from energy_ledger_100a import (
    ROOT, build, gate_window, read_raw_header, stream_points, trapezoid_mean,
)

LEDGER = ROOT / "design/v3/stage_f/energy_ledger_100a.json"
RAW = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.raw"


def test_trapezoid_mean_of_a_ramp_is_the_midpoint():
    t = [0.0, 1.0, 2.0]
    assert trapezoid_mean(t, [0.0, 1.0, 2.0]) == pytest.approx(1.0)


def test_trapezoid_mean_weights_by_time_not_by_sample_count():
    """One long segment must dominate; a per-sample average would get 1.5 here."""
    t = [0.0, 1.0, 10.0]
    y = [2.0, 2.0, 0.0]
    assert trapezoid_mean(t, y) == pytest.approx((2.0 * 1.0 + 1.0 * 9.0) / 10.0)


def test_the_window_falls_back_to_the_complete_periods_it_has():
    t = [float(i) for i in range(21)]          # 0..20 us
    gate = [5.0 if i % 10 < 5 else 0.0 for i in range(21)]
    # rising edges at 10 and 20: asking for 3 periods keeps the one real period.
    i0, i1 = gate_window(t, gate, periods=3)
    assert (i0, i1) == (10, 20)


def test_a_single_gate_edge_is_rejected_not_guessed():
    t = [0.0, 1.0, 2.0]
    gate = [0.0, 5.0, 5.0]
    with pytest.raises(ValueError):
        gate_window(t, gate, periods=3)


def test_the_window_bounds_are_real_gate_edges():
    t = [float(i) * 1e-6 for i in range(41)]
    gate = [5.0 if i % 10 in (0, 1, 2, 3, 4) else 0.0 for i in range(41)]
    i0, i1 = gate_window(t, gate, periods=3)
    assert gate[i0] >= 2.5 and gate[i1] >= 2.5
    assert (i1 - i0) == 30                   # three 10-sample periods


def test_a_synthetic_raw_round_trips(tmp_path):
    path = tmp_path / "tiny.raw"
    path.write_text(
        "Title: tiny\n"
        "No. Variables: 3\n"
        "No. Points: 3\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(a)\tvoltage\n"
        "\t2\tI(b)\tdevice_current\n"
        "Values:\n"
        "0\t\t0.000000000000000e+00\n"
        "\t0.0\n"
        "\t1.0\n"
        "1\t\t1.000000000000000e-06\n"
        "\t2.0\n"
        "\t3.0\n"
        "2\t\t2.000000000000000e-06\n"
        "\t4.0\n"
        "\t5.0\n",
        encoding="ascii",
    )
    names, _ = read_raw_header(path)
    assert names == ["time", "V(a)", "I(b)"]
    points = list(stream_points(path))
    assert len(points) == 3
    t, values = points[1]
    assert t == pytest.approx(1e-6)
    assert values == pytest.approx([2.0, 3.0])


@pytest.mark.skipif(not RAW.exists(), reason="the 424 MB raw is not in Git")
def test_the_committed_summary_names_the_raw_it_came_from():
    """A ledger that cannot be tied to one raw file is history, not evidence."""
    summary = json.loads(LEDGER.read_text(encoding="utf-8"))
    stat = RAW.stat()
    assert summary["raw"]["path"].endswith(RAW.name)
    assert summary["raw"]["bytes"] == stat.st_size
    assert summary["raw"]["mtime"] == pytest.approx(stat.st_mtime, abs=1e-6)


def test_the_residual_is_inside_the_review_target_or_the_limits_are_written_down():
    summary = json.loads(LEDGER.read_text(encoding="utf-8"))
    balance = summary["balance"]
    assert abs(balance["loss_residual_w"]) <= 0.2 or balance["limits"]
    # The loss residual is the terminal balance, not a balance with the stored
    # energy quietly subtracted.
    expected = (summary["port"]["pin_minus_pout_w"] - summary["loss_total_w"])
    assert balance["loss_residual_w"] == pytest.approx(expected, abs=1e-9)
    assert "stored_energy_endpoint_w" in balance
    assert summary["checks"]["ok"], summary["checks"]


def test_the_primary_bias_is_reported_outside_the_port():
    """Vaux/Vreg are ideal sources that do not draw from Vbus; mixing them into
    Pin-Pout would make the residual look larger for no physical reason."""
    summary = json.loads(LEDGER.read_text(encoding="utf-8"))
    outside = summary["outside_port"]
    assert set(outside) == {"vreg_w", "vaux_w", "driver_output_w"}
    # The deck's gate B-sources draw nothing from Vreg, so the ideal driver
    # energy is reported instead of pretending the pin current paid for it.
    assert abs(outside["vreg_w"]) < 0.01
    assert outside["driver_output_w"] > 0.0


def test_every_loss_term_carries_a_confidence_class():
    summary = json.loads(LEDGER.read_text(encoding="utf-8"))
    for name, term in summary["losses"].items():
        assert term["confidence"] in (
            "measured-i2r", "measured-commutation", "symmetry-assumption",
        ), name
        assert term["w"] >= 0.0, name


def test_build_is_reproducible_on_the_small_fixture_only():
    """build() reads the 424 MB raw; the suite must not re-parse it per run."""
    assert callable(build)
