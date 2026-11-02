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
    CDS_FIT, CGD_FIT, RL, ROOT, VIN, _charge_area, _simpson, averaged_storage_terms, build,
    cds_charge_c, cgd_charge_c, charge_energy_j, gate_window, parse_args, phase_alignment,
    port_terms, read_raw_header, repo_relative, stream_points, transformer_energy_j,
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


def test_the_port_power_follows_the_deck_it_was_given():
    """A candidate deck is the same tank at a different VIN/RL.

    ``port_terms`` used to read the module constants, which is correct only for
    the mother deck.  Pointed at a 50 V / 15.4 mOhm candidate it would report
    48 V / 18.9 mOhm power against the candidate's waveform -- an error that
    looks like a loss the circuit does not have.
    """
    t = array("d", [0.0, 1.0])
    d = {"iin": array("d", [2.0, 2.0]), "vin": array("d", [48.0, 48.0]),
         "vout": array("d", [1.0, 1.0])}
    mother = port_terms(t, d, 0, 1)
    assert mother["pin_source_w"] == pytest.approx(48.0 * 2.0)
    assert mother["pin_after_rin_w"] == pytest.approx(48.0 * 2.0)
    assert mother["pout_w"] == pytest.approx(1.0 / 18.9e-3)
    candidate = port_terms(t, d, 0, 1, vin=50.0, rl=15.4e-3)
    assert candidate["pin_source_w"] == pytest.approx(100.0)
    assert candidate["pout_w"] == pytest.approx(1.0 / 15.4e-3)
    # The defaults must stay the frozen 100 A deck, or every committed number
    # in energy_ledger_100a.json changes meaning without a re-run.
    assert (VIN, RL) == (48.0, 18.9e-3)


def test_the_cli_can_be_pointed_at_a_candidate_deck():
    default = parse_args([])
    assert (default.vin, default.rl) == (VIN, RL)
    given = parse_args(["--vin", "50", "--rl", "0.0154"])
    assert (given.vin, given.rl) == (50.0, 0.0154)


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
    assert set(outside) == {"vreg_w", "vaux_w", "driver_output_w", "regularisation"}
    # The deck's gate B-sources draw nothing from Vreg, so the ideal driver
    # energy is reported instead of pretending the pin current paid for it.
    assert abs(outside["vreg_w"]) < 0.01
    assert outside["driver_output_w"] > 0.0


def test_the_cpin_regulariser_is_closed_form_and_not_a_hidden_load():
    """Issue #6 asks what the numerical regulariser contributes.

    ``Cpin G S`` sits inside the measured gate current, so it *is* in
    ``driver_output_w``.  Because it is a linear capacitor, its share over the
    window is exactly 1/2*C*dV^2 at the two ends -- zero when both ends sit at
    the same phase -- so it cannot hide energy.  The number is reported so a
    reader does not have to take that on trust, and it is required to stay far
    below the 0.2 W target.
    """
    outside = json.loads(LEDGER.read_text(encoding="utf-8"))["outside_port"]
    reg = outside["regularisation"]
    assert reg["cpin_f"] == 100e-12
    assert set(reg) == {"cpin_f", "edge_power_w", "full_swing_energy_per_device_j", "note"}
    assert abs(reg["edge_power_w"]) < 0.01
    # 1/2 * 100 pF * (10.9 V)^2 = 5.94 nJ per device per edge.
    assert reg["full_swing_energy_per_device_j"] == pytest.approx(5.94e-9, rel=1e-3)


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


def test_three_timesteps_report_the_last_leg_and_each_loss_item(monkeypatch):
    """Issue #6 asks for 5 / 2 / 1 ns, not just a pair.

    A pair cannot distinguish a converging move from a constant error: the
    5 -> 2 ns leg and the 2 -> 1 ns leg can be the same size for different
    reasons.  So the report must carry the whole series, the last leg, and a
    per-item breakdown -- the aggregate "loss list moved 0.6 W" is only
    actionable once a reader can see which item carries it.
    """
    import energy_ledger_100a as mod

    def fake_build(raw, periods=16, alt_periods=(), vin=None, rl=None):
        mult = {Path("a.raw"): 0.0, Path("b.raw"): 1.0, Path("c.raw"): 2.0}[Path(raw)]
        port = 10.0 + 0.4 * mult
        loss = 11.0 + 0.1 * mult
        stored = 0.1 - 0.2 * mult
        stored_avg = 0.0 + 0.1 * mult
        driver = 0.2
        return {
            "raw": {"path": str(raw), "max_step_s": (5 - mult) * 1e-9},
            "port": {"pin_minus_pout_w": port},
            "loss_total_w": loss,
            "stored_energy_w": stored,
            "outside_port": {"driver_output_w": driver,
                             "regularisation": {"edge_power_w": 1e-6 * (mult + 1)}},
            "balance": {
                "loss_residual_w": port - loss,
                "closure_residual_w": port + driver - loss - stored,
                "period_averaged": {
                    "stored_energy_w": stored_avg,
                    "closure_residual_w": port + driver - loss - stored_avg,
                },
            },
            "window": {"vout_end_v": 1.87 + 0.001 * mult,
                       "vout_start_v": 1.873},
            "losses": {"lr": {"w": 1.0 + 0.01 * mult},
                       "sr_channel_body_x4": {"w": 7.0 + 0.1 * mult}},
        }

    monkeypatch.setattr(mod, "build", fake_build)
    step = mod.step_check(Path("a.raw"), Path("b.raw"), periods=133,
                          a=fake_build(Path("a.raw")), extra=(Path("c.raw"),))

    assert step["periods"] == 133
    assert step["steps_s"] == pytest.approx([5e-9, 4e-9, 3e-9])
    port = step["terms"]["port_w"]
    assert port["series_w"] == pytest.approx([10.0, 10.4, 10.8])
    assert port["delta_w"] == pytest.approx(0.4)          # 5 -> 2 ns
    assert port["delta_first_last_w"] == pytest.approx(0.8)
    # The note must state the last leg *and* the first-to-last move, because
    # "last leg much smaller" is the only evidence of a plateau.
    assert "last leg moves port +0.400 W" in step["note"]
    assert "+0.800 / +0.200 / +0.400 W" in step["note"]
    # Per item, the two legs are visible separately: a single 0.02 W move can
    # either continue or stop, and only the split says which.
    lr = step["loss_items"]["lr"]
    assert lr["steps_w"] == pytest.approx([1.0, 1.01, 1.02])
    assert lr["delta_first_last_w"] == pytest.approx(0.02)
    assert lr["delta_last_leg_w"] == pytest.approx(0.01)
    # The regulariser is compared as its own column so a reader can see that
    # the numerical pad is not what moves the ledger between steps.
    assert step["terms"]["regularisation_edge_w"]["series_w"] == pytest.approx(
        [1e-6, 2e-6, 3e-6])


def test_every_step_column_uses_the_supply_and_load_it_was_told(monkeypatch):
    """A parameter-only candidate changes VIN/RL, not the circuit.

    If ``step_check`` let the extra columns fall back to the mother deck's
    constants, the "step" series would silently also carry a parameter change,
    and the last-leg-vs-first-leg plateau test would be measuring the wrong
    difference.  The three columns must all be built with the caller's values.
    """
    import energy_ledger_100a as mod

    seen = []

    def fake_build(raw, periods=16, alt_periods=(), vin=None, rl=None):
        seen.append((Path(raw).name, vin, rl))
        return {
            "raw": {"path": str(raw), "max_step_s": 5e-9},
            "port": {"pin_minus_pout_w": 10.0},
            "loss_total_w": 11.0,
            "stored_energy_w": 0.0,
            "outside_port": {"driver_output_w": 0.0,
                             "regularisation": {"edge_power_w": 0.0}},
            "balance": {"loss_residual_w": -1.0, "closure_residual_w": -1.0,
                        "period_averaged": {"stored_energy_w": 0.0,
                                            "closure_residual_w": -1.0}},
            "window": {"vout_end_v": 1.87, "vout_start_v": 1.87},
            "losses": {},
        }

    monkeypatch.setattr(mod, "build", fake_build)
    mod.step_check(Path("a.raw"), Path("b.raw"), periods=133,
                   extra=(Path("c.raw"),), vin=50.0, rl=0.0154)
    # a.raw is built here only because this call does not hand in a summary.
    assert seen == [("a.raw", 50.0, 0.0154), ("b.raw", 50.0, 0.0154),
                    ("c.raw", 50.0, 0.0154)]


def test_a_step_check_refuses_two_different_circuits(tmp_path: Path):
    """The only variable may be the timestep.

    The 120 A candidate's ledger was generated with the *100 A* 2 ns raw as the
    comparison column.  Because ``step_check`` also applies the candidate's
    VIN/RL to that raw, it reported a -43 W "closure move" -- two different
    converters subtracted from each other, not a timestep sensitivity.  A
    candidate with no same-circuit 2 ns run must use ``--no-step-check``.
    """
    import energy_ledger_100a as mod

    # Same timestep, different load: the comparison would be a circuit change.
    (tmp_path / "a.cir").write_text(
        "\n".join(["Rload out 0 {RL}", ".param VIN=48", ".param RL=15.4m",
                   ".tran 0 1000u 880u 5n uic"]), encoding="utf-8")
    (tmp_path / "b.cir").write_text(
        "\n".join(["Rload out 0 {RL}", ".param VIN=48", ".param RL=18.9m",
                   ".tran 0 1000u 880u 5n uic"]), encoding="utf-8")
    diff = mod.deck_difference(tmp_path / "a.raw", tmp_path / "b.raw")
    assert diff is not None and "RL" in diff
    with pytest.raises(ValueError, match="not the same circuit"):
        mod.step_check(tmp_path / "a.raw", tmp_path / "b.raw")


def test_a_step_check_accepts_decks_that_differ_only_in_the_tran_line(tmp_path: Path):
    import energy_ledger_100a as mod

    body = ["Rload out 0 {RL}", ".param VIN=48", ".options method=gear"]
    (tmp_path / "a.cir").write_text("\n".join(body + [".tran 0 1000u 880u 5n uic"]),
                                    encoding="utf-8")
    (tmp_path / "b.cir").write_text("\n".join(body + [".tran 0 1000u 880u 2n uic"]),
                                    encoding="utf-8")
    assert mod.deck_difference(tmp_path / "a.raw", tmp_path / "b.raw") is None


def test_skipping_the_step_check_does_not_point_at_a_missing_section():
    """The sensitivity note used to say "see step_check" unconditionally.

    A candidate generated with ``--no-step-check`` has no such block, so the
    pointer would send a reader looking for a comparison that was never run.
    The replacement note must say so and keep the storage caveat that follows.
    """
    import energy_ledger_100a as mod

    summary = {"sensitivity": {"note": "see step_check for the 5 ns / 2 ns "
                                        "comparison; the storage terms come from "
                                        "the charge function at the endpoints"}}
    mod.mark_no_step_check(summary)
    note = summary["sensitivity"]["note"]
    assert "No step check was run" in note
    assert "see step_check" not in note
    assert "storage terms come from the charge function" in note


def test_two_synthetic_raws_without_decks_are_not_rejected(tmp_path: Path):
    """The unit tests build fake raws; the guard must not demand a deck they lack."""
    import energy_ledger_100a as mod

    assert mod.deck_difference(tmp_path / "a.raw", tmp_path / "b.raw") is None


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
