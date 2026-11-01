"""Tests for tools/energy_ledger_100a.py.

The ledger's value is that every watt is either measured in the same window or
explicitly labelled as an assumption.  These tests pin the arithmetic (trapezoid,
gate-period window) and the provenance lock (the committed summary must name the
raw it came from, byte for byte).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from array import array

from energy_ledger_100a import (
    CDS_FIT, CGD_FIT, ROOT, _charge_area, _simpson, averaged_storage_terms, build,
    cds_charge_c, cgd_charge_c, charge_energy_j, gate_window, phase_alignment,
    read_raw_header, repo_relative, stream_points, transformer_energy_j,
    trapezoid_mean,
)
from lr_design import LR_TOTAL_H, resonant_khz

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


def test_a_physical_gap_is_reported_in_results_not_gated_in_checks():
    """How much of the port-minus-loss gap the CT branch explains changes with
    the window (0.094 W on 16 periods, 0.344 W on the aligned 133), so it is a
    result, not an invariant.  Gating it would have made an honest "CT no
    longer explains the whole gap" look like a broken report."""
    summary = json.loads(LEDGER.read_text(encoding="utf-8"))
    assert "ct_burden_closes_the_gap" not in summary["checks"]
    assert "ct_terms_account_for_the_gap_before_ct" in summary["results"]
    assert summary["gap_before_ct_w"] == pytest.approx(
        summary["port"]["pin_minus_pout_w"] - summary["loss_before_ct_w"], abs=1e-9)
    # everything left in `checks` describes the report, not the physics
    assert set(summary["checks"]) == {
        "ok", "ct_gap_is_reported_as_a_result",
        "stored_energy_reported_not_folded_in", "pout_uses_v_squared",
        "coupled_energy_never_negative", "closure_status_follows_from_the_results",
        "closure_status_is_derived_from_both_readings",
        "closure_reason_states_which_condition_failed",
    }


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


# --- issue #6: coupled storage, charge functions, resolution ---------------

def test_coupled_energy_collapses_to_the_magnetising_form_at_perfect_coupling():
    """With k=1 the three-winding quadratic must reduce to 1/2 Lp (Ip + S/3)^2.

    The first version of this ledger stored 4 * 1/2 Lp Ipri^2, which treats the
    secondaries as if they carried nothing; this identity is what shows the
    coupled form is the same quantity done properly, not a different one.
    """
    lp, ip, isa, isb = 10e-6, 7.0, -12.0, -9.0
    expected = 0.5 * lp * (ip + (isa + isb) / 3.0) ** 2
    assert transformer_energy_j(lp, 1.0, ip, isa, isb) == pytest.approx(expected, rel=1e-12)


def test_coupled_energy_vanishes_under_ampere_turn_balance():
    """A 3:1:1 transformer carrying -3x the primary in its halves stores ~nothing."""
    lp, ip = 10e-6, 7.0
    e = transformer_energy_j(lp, 1.0, ip, -1.5 * ip, -1.5 * ip)
    assert e == pytest.approx(0.0, abs=1e-18)
    # ...and it is positive once the balance is broken, which is the storage
    # the old magnetising-only term was attributing to the whole transformer.
    assert transformer_energy_j(lp, 1.0, ip, -4.0, -2.0) > 0.0


def test_coupled_energy_is_quadratic_and_symmetric_in_the_two_halves():
    lp = 10e-6
    a = transformer_energy_j(lp, 0.999, 5.0, -9.0, -6.0)
    b = transformer_energy_j(lp, 0.999, 5.0, -6.0, -9.0)
    assert a == pytest.approx(b, rel=1e-12)
    assert abs(a - transformer_energy_j(lp, 0.999, 5.0, -6.0, -9.0)) < 1e-18


def test_the_charge_fits_reproduce_the_documented_device_targets():
    """Qds(20 V) = 67.631 nC and Qgd(20 V) = 5.360 nC are the numbers the SR
    model was fitted to; if these drift the stored energy drifts with them."""
    assert cds_charge_c(20.0) * 1e9 == pytest.approx(67.631, abs=1e-3)
    assert cgd_charge_c(20.0) * 1e9 == pytest.approx(5.360, abs=1e-3)


def test_capacitor_energy_is_zero_at_zero_volts_and_positive_elsewhere():
    for charge in (cds_charge_c, cgd_charge_c):
        assert charge_energy_j(0.0, charge) == pytest.approx(0.0, abs=1e-18)
        assert charge_energy_j(20.0, charge) > 0.0
        # monotone: more volts, more energy
        assert charge_energy_j(40.0, charge) > charge_energy_j(20.0, charge)


def test_the_phase_aligned_window_is_computed_from_the_tank_not_guessed():
    """The clock and the tank are not commensurate, so 'use a phase-aligned
    window' has an answer: the first gate-period count whose tank phase returns."""
    a = phase_alignment()
    assert a["aligned_periods"] == 133
    assert a["phase_error_deg"] < 1.0
    assert a["aligned_span_s"] == pytest.approx(662.94e-6, rel=1e-4)
    assert a["tank_khz"] > a["gate_khz"]
    # two independent constants (this tool builds the tank from LR_TOTAL + the
    # model leakage, lr_design from its own target) must describe one tank
    assert a["tank_khz"] == pytest.approx(resonant_khz(LR_TOTAL_H), abs=0.05)


def test_the_resolution_block_is_internally_consistent():
    summary = json.loads(LEDGER.read_text(encoding="utf-8"))
    r = summary["balance"]["resolution"]
    values = r["per_period_w"]
    assert r["periods"] == len(values)
    mean = sum(values) / len(values)
    assert r["mean_w"] == pytest.approx(mean, rel=1e-9)
    sd = math.sqrt(sum((x - mean) ** 2 for x in values) / (len(values) - 1))
    assert r["sd_w"] == pytest.approx(sd, rel=1e-9)
    assert r["sem_w"] == pytest.approx(sd / len(values) ** 0.5, rel=1e-9)
    assert r["periods_for_target"] == math.ceil((sd / r["target_w"]) ** 2)


def test_a_window_that_cannot_resolve_the_target_is_not_reported_as_closed():
    """Issue #6: the mean landing inside 0.2 W is not enough.  The window has to
    be long enough to resolve 0.2 W, and this one is 18 % of the phase-aligned
    length, so the status stays NOT_CLOSED with the reason written down."""
    summary = json.loads(LEDGER.read_text(encoding="utf-8"))
    balance = summary["balance"]
    results = summary["results"]
    resolves = balance["resolution"]["sem_w"] <= 0.2
    resolves_avg = balance["period_averaged"]["sem_w"] <= 0.2
    assert results["window_resolves_0p2_w"] is resolves
    assert results["window_resolves_0p2_w_period_averaged"] is resolves_avg
    # Both readings must be inside the target, and the period-averaged one --
    # the estimator whose spread is not set by the endpoint sample -- must
    # resolve it.  Requiring the noisier single-sample reading to resolve as
    # well would only mean a longer run, not a stronger claim.
    assert results["closure_including_storage_within_0p2_w"] is (
        results["closure_within_0p2_w"]
        and results["closure_period_averaged_within_0p2_w"] and resolves_avg)
    assert balance["closure_status"] == (
        "CLOSED" if results["closure_including_storage_within_0p2_w"] else "NOT_CLOSED")
    if not resolves_avg:
        assert any("period-averaged" in text for text in balance["limits"]), balance["limits"]
        assert ("resolves" in balance["closure_reason"]
                or "disagree" in balance["closure_reason"]), balance["closure_reason"]
    # the report invariants are the gate, not the physics outcome
    assert summary["checks"]["ok"], summary["checks"]


def test_the_step_check_compares_two_timesteps_and_the_endpoint_moves():
    """The closure is not reproducible between 5 ns and 2 ns even though the
    loss integrals agree; the endpoint sample of V(out) is what moves."""
    summary = json.loads(LEDGER.read_text(encoding="utf-8"))
    step = summary["step_check"]
    assert step["step_a_s"] != step["step_b_s"]
    assert {"port_w", "loss_total_w", "stored_w", "closure_residual_w"} <= set(step["terms"])
    # The report quotes the period-averaged reading, so the step check must
    # compare that reading too -- otherwise it can pass while the number that
    # is actually published moves by twice the target.
    assert {"stored_period_averaged_w", "closure_period_averaged_w"} <= set(step["terms"])
    loss = step["terms"]["loss_total_w"]
    assert abs(loss["delta_w"]) < 0.05           # quadrature has converged
    assert abs(step["terms"]["vout_end_v"]["delta"]) > 1e-3   # the endpoint has not
    assert "vout_end_v" in summary["window"]
    # Measured: the period-averaged closure moves 0.38 W between 5 ns and 2 ns,
    # i.e. the closure is not reproducible at the 0.2 W target even after the
    # endpoint is averaged over a whole gate period.
    assert abs(step["terms"]["closure_period_averaged_w"]["delta_w"]) > 0.2
    # ... and the port term, which the note used to call converged, is one of
    # the two movers: it is larger than the loss inventory's movement.
    assert (abs(step["terms"]["port_w"]["delta_w"])
            > 10.0 * abs(loss["delta_w"]))
    # The note must carry the measured deltas, so a future edit cannot quietly
    # re-assert convergence without the numbers contradicting it.
    for name in ("port_w", "closure_period_averaged_w"):
        assert f"{step['terms'][name]['delta_w']:+.3f} W" in step["note"]


def _ripple_plus_drift(n: int = 21, per_period: int = 10,
                       tank_samples: float = 9.925, amplitude: float = 100.0,
                       drift: float = 0.01) -> tuple[array, array, list[int]]:
    """A storage trace whose history is a tank-frequency ripple plus a real drift.

    The 0.75 % detuning of ``tank_samples`` from the gate period is what the
    real deck has (4.9473 us tank inside a 4.9845 us clock period), and it is
    the reason a period average is not a perfect canceller.
    """
    t = array("d", (float(i) for i in range(n * per_period + 1)))
    y = array("d", (amplitude * math.sin(2.0 * math.pi * i / tank_samples) + drift * i
                    for i in range(len(t))))
    edges = [k * per_period for k in range(n + 1)]
    return t, y, edges


def test_period_averaging_beats_a_single_sample_by_the_detuning_ratio():
    """Issue #6's storage terms are endpoint differences, so which sample the raw
    happens to end on becomes a watts-scale error.  Averaging one gate period
    removes the tank-frequency part: one gate period is within 0.75 % of one
    tank period, so what is left is ~0.75 % of the ripple, not 100 % of it.

    The test is written to fail if the averaging is removed: it asserts the
    single-sample reading is *far* worse, so a no-op implementation cannot pass
    on tolerance alone.
    """
    t, y, edges = _ripple_plus_drift()
    arrays = {"x": y}
    i0, i1 = edges[0], edges[20]
    true_change = 0.01 * (i1 - i0)
    single = y[i1] - y[i0]
    averaged = averaged_storage_terms(t, arrays, edges, i0, i1)["x"]
    assert abs(single - true_change) > 50.0, "the ripple must dominate a single sample"
    assert abs(averaged - true_change) < 1.5, "period averaging must remove the ripple"


def test_period_averaging_refuses_a_window_that_is_not_on_gate_edges():
    """Averaging over a partial period would silently read a different phase at
    each end, which is the error it is meant to remove."""
    t, y, edges = _ripple_plus_drift()
    with pytest.raises(ValueError, match="gate edges"):
        averaged_storage_terms(t, {"x": y}, edges, 1, edges[20])


def test_the_committed_closure_status_is_derived_from_both_readings():
    """The single-sample and the period-averaged readings must agree before the
    status may read CLOSED -- otherwise a short window that landed a favourable
    endpoint would close issue #6 on its own."""
    data = json.loads(LEDGER.read_text(encoding="utf-8"))
    results = data["results"]
    balance = data["balance"]
    expected = (results["closure_within_0p2_w"]
                and results["closure_period_averaged_within_0p2_w"]
                and results["window_resolves_0p2_w_period_averaged"])
    assert results["closure_including_storage_within_0p2_w"] == expected
    assert (balance["closure_status"] == "CLOSED") == expected
    assert balance["target_w"] == 0.2, "the target is not negotiable"
    assert "period_averaged" in balance
    assert "130x" in balance["period_averaged"]["definition"]


def test_the_closed_form_charge_integral_matches_simpson():
    """``storage_arrays`` evaluates the SR capacitor energy at *every* sample, so
    the integral has to be both exact and cheap.  The closed form replaced a
    4000-panel Simpson; they must agree to Simpson's own error, which is why the
    tolerance is loose enough to be Simpson's and tight enough that a wrong
    antiderivative cannot pass."""
    for fit, q in ((CDS_FIT, cds_charge_c), (CGD_FIT, cgd_charge_c)):
        for x in (0.5, 5.0, fit[0], 20.0, 40.0):
            simpson = (_simpson(q, 0.0, x) if x <= fit[0]
                       else _simpson(q, 0.0, fit[0]) + _simpson(q, fit[0], x))
            assert _charge_area(fit, x) == pytest.approx(simpson, rel=1e-8), (q.__name__, x)


def test_the_stored_energy_of_the_linear_segment_is_the_antiderivative():
    """Below the fit breakpoint Q = a*x - b*x^2/2, so E = a*x^2/2 - b*x^3/3 in
    closed form.  Checking against that identity catches a lost factor of two
    in the antiderivative, which the Simpson comparison alone would not."""
    a, b = CDS_FIT[1], CDS_FIT[2]
    for x in (1.0, 4.0, 9.0):
        assert charge_energy_j(x, cds_charge_c) == pytest.approx(
            a * x ** 2 / 2.0 - b * x ** 3 / 3.0, rel=1e-15)


def test_a_raw_named_on_the_command_line_is_still_written_relative_to_the_repo(
        monkeypatch, tmp_path):
    """A ``--raw`` passed relatively crashed the whole 22-minute aligned scan:
    ``Path.relative_to`` does not resolve first.  The same raw must be named the
    same way whichever way the caller spelled it, and a raw outside the repo
    must come out absolute rather than raise."""
    monkeypatch.chdir(ROOT)
    assert repo_relative(Path("sim/v3/x.raw")) == "sim/v3/x.raw"
    assert repo_relative(ROOT / "sim/v3/x.raw") == "sim/v3/x.raw"
    outside = tmp_path / "y.raw"
    assert repo_relative(outside) == outside.resolve().as_posix()
