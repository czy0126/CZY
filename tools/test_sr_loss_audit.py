"""The SR audit's arithmetic and the boundary it is allowed to move.

Three things are locked here:

1. the audit's own arithmetic on synthetic data -- the gate KCL identity, the
   forward/reverse split of the body diode, and the linear Cout/Lr correction;
2. the reason the correction exists at all: ``loss_main`` must keep excluding
   ``sr_gate_resistor_x8`` (a port-powered-loss list) while ``driver_w`` keeps
   adding the external driver output, so the two are not on the same boundary;
3. the committed report must not have flipped a status or moved the budget.
"""
from __future__ import annotations

import json
from array import array
from pathlib import Path

import pytest

import energy_ledger_100a as el
import sr_loss_audit as audit

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "design/v3/stage_f/sr_loss_audit.json"
ALIGNED_LEDGER = ROOT / "design/v3/stage_f/energy_ledger_100a_phase_aligned.json"


def synthetic() -> tuple[array, dict[str, array]]:
    """Four samples spanning 3 us, window [0, 3]: one full 'period' pair."""
    t = array("d", [0.0, 1e-6, 2e-6, 3e-6])
    const = lambda value: array("d", [value] * 4)  # noqa: E731
    gate = const(5.0)
    # KCL at the gate pin: the driver supplies i_lg + vg/Rgs (Cpin edge is 0).
    drain_current = -(1e-3 + 5.0 / audit.RGS_OHM)
    d = {
        "vga": gate, "vgb": gate,
        "bd1": const(drain_current), "bd2": const(drain_current),
        "a_lg": const(1e-3), "b_lg": const(1e-3),
        "a_rg": const(1e-3), "b_rg": const(1e-3),
    }
    return t, d


def test_the_gate_loop_closes_on_driver_output_minus_rg_rgs_cpin():
    t, d = synthetic()
    budget = audit.gate_budget(t, d, 0, 3)
    assert budget["kcl_residual_x8_w"] == pytest.approx(0.0, abs=1e-12)
    assert budget["sinks_x8_w"] == pytest.approx(
        4.0 * (budget["per_half"]["a"]["gate_resistor_w"]
               + budget["per_half"]["a"]["gate_source_resistor_w"]
               + budget["per_half"]["b"]["gate_resistor_w"]
               + budget["per_half"]["b"]["gate_source_resistor_w"]))
    # The sinks are *inside* the driver's output, not a separate source.
    assert budget["sinks_x8_w"] < budget["driver_output_w"]


def test_the_body_diode_split_keeps_forward_positive_and_reverse_negative():
    t = array("d", [0.0, 1e-6, 2e-6, 3e-6])
    d = {
        "a_di": array("d", [0.0] * 4), "a_si": array("d", [0.5] * 4),
        "b_di": array("d", [0.0] * 4), "b_si": array("d", [0.5] * 4),
        "a_bch": array("d", [0.0] * 4), "b_bch": array("d", [0.0] * 4),
        # vds = -0.5 V; positive diode current conducts, negative recovers.
        "a_dbd": array("d", [2.0, 2.0, -2.0, -2.0]),
        "b_dbd": array("d", [2.0, 2.0, -2.0, -2.0]),
    }
    split = audit.sr_split(t, d, 0, 3, periods=1)
    # Per half the trapezoid mean is 1.5/3 = 0.5 W; both halves, scaled to the
    # eight devices, so each term is 4 * (0.5 + 0.5) = 4 W.  The symmetric
    # waveform makes them cancel exactly, which is the split's own check.
    assert split["body_diode_forward_w"] == pytest.approx(4.0)
    assert split["body_diode_reverse_w"] == pytest.approx(-4.0)
    assert split["body_diode_w"] == pytest.approx(0.0, abs=1e-12)
    assert split["body_diode_w"] == pytest.approx(
        split["body_diode_forward_w"] + split["body_diode_reverse_w"])
    assert split["total_w"] == pytest.approx(split["channel_w"] + split["body_diode_w"])


def test_the_deck_parameter_correction_is_exact_and_linear():
    """A candidate Cout larger than the tool's constant must debit the closure."""
    t = array("d", [0.0, 1e-6, 2e-6, 3e-6])
    d = {
        "vout": array("d", [1.0, 1.0, 1.0, 1.1]),
        "ilr": array("d", [0.0, 0.0, 0.0, 0.0]),
    }
    edges = [0, 1, 2, 3]
    deck = {"cout_f": el.COUT_F + 1e-3, "lr_h": el.LR_H}
    result = audit.storage_parameters(t, d, edges, 0, 3, deck)
    span = 3e-6
    assert result["delta_stored_single_j"] == pytest.approx(0.5 * 1e-3 * (1.21 - 1.0))
    assert result["delta_closure_single_w"] == pytest.approx(
        -result["delta_stored_single_j"] / span)
    # Period-averaged ends: mean(v^2) over [0,1] vs [2,3].
    assert result["delta_stored_period_averaged_j"] == pytest.approx(
        0.5 * 1e-3 * ((1.0 + 1.21) / 2.0 - 1.0))
    # Equal parameters must be a true no-op, not a tiny rounding residue.
    same = audit.storage_parameters(t, d, edges, 0, 3,
                                    {"cout_f": el.COUT_F, "lr_h": el.LR_H})
    assert same["delta_closure_single_w"] == 0.0
    assert same["delta_closure_period_averaged_w"] == 0.0


def test_the_missing_deck_is_reported_as_no_adjustment():
    t = array("d", [0.0, 1e-6, 2e-6, 3e-6])
    d = {"vout": array("d", [1.0] * 4), "ilr": array("d", [0.0] * 4)}
    result = audit.storage_parameters(t, d, [0, 1, 2, 3], 0, 3,
                                      {"cout_f": None, "lr_h": None})
    assert result["delta_closure_single_w"] == 0.0
    assert "no adjustment" in result["note"]


def test_ltspice_value_literals_are_parsed_not_assumed():
    assert audit._number("7.05m") == pytest.approx(7.05e-3)
    assert audit._number(".92u") == pytest.approx(0.92e-6)
    assert audit._number("4") == pytest.approx(4.0)
    with pytest.raises(ValueError):
        audit._number("TO SELECT")


def test_loss_main_excludes_the_gate_resistor_that_driver_w_includes():
    """This asymmetry is the defect the audit measures; it must stay visible."""
    losses = {"sr_gate_resistor_x8": {"w": 1.0},
              "sr_channel_body_pair1": {"w": 2.0},
              "rin": {"w": 3.0}}
    names = el.main_loss_names(losses)
    assert "sr_gate_resistor_x8" not in names
    assert "sr_channel_body_pair1" not in names
    assert "rin" in names


def test_the_probe_map_covers_every_internal_the_audit_reads():
    probes = audit.probe_map()
    names = set(probes.values())
    required = {"vga", "vgb", "bd1", "bd2", "a_lg", "b_lg", "a_rg", "b_rg",
                "a_bch", "b_bch", "a_dbd", "b_dbd", "a_di", "b_di", "a_si", "b_si",
                "a_cds", "b_cds", "a_cgd", "b_cgd", "a_ld", "b_ld", "isa1", "isb1",
                "isa4", "isb4"}
    assert required <= names


def load_report() -> dict:
    if not REPORT.exists():
        pytest.fail(f"{REPORT} must be committed alongside the tool")
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_the_budget_and_the_published_statuses_are_untouched():
    report = load_report()
    assert report["budget_w"] == pytest.approx(0.2)
    assert report["results"]["closure_status_flipped_by_this_audit"] is False
    assert report["results"]["numerical_convergence_approved"] is False
    assert report["results"]["efficiency_conclusion_approved"] is False
    for status in report["results"]["ledger_closure_status_unchanged"].values():
        assert status == "NOT_CLOSED"


def test_every_case_reproduces_the_committed_ledger_number():
    """If a raw or a ledger JSON is replaced, this is the first thing that breaks."""
    report = load_report()
    assert report["checks"]["ok"] is True
    assert report["cases"]
    for case in report["cases"]:
        assert case["closure"]["matches_published"] is True, case["name"]
        assert abs(case["dimensions"]["gate_pin_kcl_w"]) <= 1e-3, case["name"]
        assert case["sr_dissipation"]["body_diode_forward_w"] > 0.0, case["name"]
        assert case["sr_dissipation"]["body_diode_reverse_w"] < 0.0, case["name"]
        # Mean current is charge over the window, and the resulting drop must
        # be a body-diode drop.  A q*periods/span slip reads 5 mV and passes
        # every sign check, so this identity is the only thing that catches it.
        assert case["sr_dissipation"]["forward_current_a"] == pytest.approx(
            case["sr_dissipation"]["forward_charge_c"] / case["window"]["span_s"],
            rel=1e-12), case["name"]
        assert 0.2 < case["sr_dissipation"]["mean_forward_voltage_v"] < 2.0, case["name"]


def test_the_gate_drive_correction_is_what_moves_the_closure():
    report = load_report()
    results = report["results"]
    before = results["aligned_closure_before_period_averaged_w"]
    after = results["aligned_closure_after_period_averaged_w"]
    # Every column was *outside* the budget before the correction, so the
    # correction is doing work rather than confirming a number already green.
    assert all(abs(x) > 0.2 for x in before)
    assert all(abs(a) < abs(b) for a, b in zip(after, before))
    # The correction itself must be step-independent, or it is a fudge factor.
    assert results["aligned_gate_drive_sinks_spread_across_steps_w"] < 0.005


def test_the_four_step_series_has_no_plateau_at_half_a_nanosecond():
    """E6-3: the 0.5 ns leg exists to tell a plateau from an oscillation.

    With 5 / 2 / 1 ns the corrected closure looked stable
    (0.3258 / 0.3139 / 0.3095 W).  Three points are enough to look flat and
    not enough to prove it: the fourth leg moves the closure by 0.21 W and
    puts the loss residual back above 0.2 W.  So the earlier "stable" reading
    was a three-point coincidence and must never be quoted as convergence.
    """
    report = load_report()
    results = report["results"]
    assert results["aligned_steps_ns"] == ["5", "2", "1", "0.5"]
    series = results["aligned_closure_after_period_averaged_w"]
    assert len(series) == 4
    # The first three really do agree; the fourth is the one that breaks it.
    assert max(series[:3]) - min(series[:3]) < 0.05
    assert series[3] - series[2] > 0.2
    assert results["aligned_closure_after_within_budget_period_averaged"] is False
    # The loss residual -- the quantity the 0.2 W target is actually about --
    # leaves the budget at the finest step as well.  It lives in the ledger's
    # step_check, not in this report.
    ledger = json.loads(ALIGNED_LEDGER.read_text(encoding="utf-8"))
    residuals = ledger["step_check"]["terms"]["residual_w"]["series_w"]
    assert residuals[-1] > 0.2
    # The prose is generated from the series, so it may not keep claiming a
    # budget the finest step fails -- but it must say how many do pass.
    assert "all 4 inside the 0.2 W budget" not in report["conclusion"]
    assert "only 3 of 4 inside the 0.2 W budget" in report["conclusion"]
    assert "0.5 ns" in report["conclusion"]


def test_the_sixteen_period_window_stays_unusable_after_the_correction():
    report = load_report()
    assert report["results"]["sixteen_period_closure_is_usable"] is False
    assert report["results"]["sixteen_period_closure_step_spread_after_w"] > 0.2


def test_the_step_instability_is_the_body_diode_not_the_channel():
    report = load_report()
    results = report["results"]
    assert results["body_diode_forward_step_spread_w"] > 5.0 * results["channel_step_spread_w"]
    assert results["body_diode_forward_share_of_sr_move"] > 0.9


def test_only_the_one_nanosecond_run_breaks_group_symmetry():
    """E6-4: the four secondary groups are identical in every deck, so a
    pair4/pair1 ratio away from 1 is a numerical split of the parallel
    branches, not physics.  Three runs give exactly 1; the 1 ns run gives
    +/-2 % in opposite directions, and that is the only measured bound on the
    x4 scaling error.  Keep it visible: a future rerun that happens to land on
    1 everywhere must not silently erase the caveat."""
    report = load_report()
    results = report["results"]
    ratios = results["pair4_over_pair1_rms_current"]
    assert sorted(ratios) == ["aligned_0p5ns", "aligned_1ns", "aligned_2ns", "aligned_5ns"]
    for name in ("aligned_5ns", "aligned_2ns", "aligned_0p5ns"):
        assert ratios[name]["a"] == pytest.approx(1.0, abs=1e-9), name
        assert ratios[name]["b"] == pytest.approx(1.0, abs=1e-9), name
    assert ratios["aligned_1ns"]["a"] == pytest.approx(0.9793, abs=1e-3)
    assert ratios["aligned_1ns"]["b"] == pytest.approx(1.0197, abs=1e-3)
    # Opposite directions: the *pair average* is preserved, so this is a
    # redistribution between parallel branches rather than a current error.
    assert ratios["aligned_1ns"]["a"] * ratios["aligned_1ns"]["b"] == pytest.approx(1.0, abs=2e-3)
    bound = results["pair4_over_pair1_i2r_error_bound_pct"]
    assert bound["aligned_1ns"] > 3.0, "the 2 % RMS split is a 4 % I2R error"
    assert results["pair_split_circulating_rms_a"]["aligned_1ns"]["a"] > 0.5
    # Pairs 2 and 3 must stay UNKNOWN, and the report must say so in prose.
    assert results["sr_group_symmetry_unmeasured"] == [2, 3]
    limits = " ".join(report["limits"])
    assert "pairs 2 and 3" in limits
    assert "1 ns" in limits


def test_the_group_symmetry_check_names_what_it_cannot_measure():
    """E6-4: only pairs 1 and 4 have terminal current probes.  A 2:1 RMS
    difference between them must show up as a 4:1 I2R scaling ratio, and pairs
    2/3 must be reported UNKNOWN rather than silently assumed equal."""
    t = array("d", [0.0, 1e-6, 2e-6, 3e-6])
    d = {
        "isa1": array("d", [1.0, 1.0, 1.0, 1.0]),
        "isb1": array("d", [2.0, 2.0, 2.0, 2.0]),
        "isa4": array("d", [2.0, 2.0, 2.0, 2.0]),
        "isb4": array("d", [2.0, 2.0, 2.0, 2.0]),
    }
    result = audit.group_symmetry(t, d, 0, 3)
    assert result["measured_groups"] == [1, 4]
    assert result["unmeasured_groups"] == [2, 3]
    assert "no current probes" in result["unmeasured_reason"]
    assert result["pair4_over_pair1_rms"]["a"] == pytest.approx(2.0)
    assert result["pair4_over_pair1_rms"]["b"] == pytest.approx(1.0)
    assert result["i2r_scaling_ratio"]["a"] == pytest.approx(4.0)
    assert result["i2r_scaling_ratio"]["b"] == pytest.approx(1.0)


def test_the_group_split_deviation_bounds_the_x4_scaling_error():
    """E6-4: when pair 4 departs from pair 1, the x4 scaling inherits the
    departure *squared*.  Report the bound instead of letting a reader assume
    the four groups shared exactly."""
    t = array("d", [0.0, 1e-6, 2e-6, 3e-6])
    d = {
        "isa1": array("d", [1.0, 1.0, 1.0, 1.0]),
        "isb1": array("d", [2.0, 2.0, 2.0, 2.0]),
        "isa4": array("d", [2.0, 2.0, 2.0, 2.0]),
        "isb4": array("d", [2.0, 2.0, 2.0, 2.0]),
    }
    result = audit.group_symmetry(t, d, 0, 3)
    # 2:1 in RMS is 4:1 in I2R, i.e. a 300 % scaling error on that half.
    assert result["pair_split_deviation_max"] == pytest.approx(1.0)
    assert result["i2r_scaling_error_bound_pct"] == pytest.approx(300.0)
    # The difference current is what flows in the loop between the branches.
    assert result["circulating_difference_rms_a"]["a"] == pytest.approx(1.0)
    assert result["circulating_difference_rms_a"]["b"] == pytest.approx(0.0)


def _case(name: str, step: float, diode: float, closure_single: float) -> dict:
    """The subset of a built case block ``compare_cases`` reads."""
    return {
        "name": name,
        "max_step_s": step,
        "port": {"vin_v": 50.0, "rl_ohm": 16.3e-3},
        "window": {"start_s": 0.0, "end_s": 1.0},
        "sr_dissipation": {
            "channel_w": 3.0, "body_diode_forward_w": diode,
            "body_diode_reverse_w": -0.5, "body_diode_w": diode - 0.5,
            "total_w": 3.0 + diode - 0.5,
        },
        "closure": {
            "ledger": {"single_w": closure_single, "period_averaged_w": closure_single + 0.1,
                       "closure_status": "NOT_CLOSED"},
            "after_gate_drive_single_w": closure_single - 0.2,
            "after_gate_drive_period_averaged_w": closure_single - 0.1,
        },
        "storage_parameters": {"cout_f_deck": 7.05e-3, "lr_h_deck": 1e-6},
        "per_period": {
            "channel_w": [3.0, 3.1, 3.05],
            "body_diode_w": [diode, diode + 0.2, diode + 0.1],
            "total_w": [3.0 + diode, 3.3 + diode, 3.15 + diode],
        },
    }


def test_compare_cases_reports_every_delta_as_b_minus_a():
    a = _case("five_ns", 5e-9, 6.0, 0.50)
    b = _case("two_ns", 2e-9, 5.4, 0.46)
    result = audit.compare_cases(a, b)
    assert result["steps_s"] == [5e-9, 2e-9]
    assert result["port"]["a"] == result["port"]["b"]
    assert result["sr_terms"]["body_diode_forward_w"]["delta_w"] == pytest.approx(-0.6)
    assert result["sr_terms"]["channel_w"]["delta_w"] == pytest.approx(0.0)
    assert result["closure"]["before_single_w"]["delta_w"] == pytest.approx(-0.04)
    assert result["closure"]["after_period_averaged_w"]["delta_w"] == pytest.approx(-0.04)
    # Cycle-by-cycle statistics use the *pairs* of per-period values.
    # Every period moves by the same -0.6 W in this synthetic pair.
    assert result["per_cycle_deltas"]["body_diode_w"]["mean_w"] == pytest.approx(-0.6)
    assert result["per_cycle_deltas"]["body_diode_w"]["rms_w"] == pytest.approx(0.0)
    assert result["closure_status"] == ["NOT_CLOSED", "NOT_CLOSED"]


def test_the_50v_120a_step_pair_points_at_the_two_column_ledger():
    """The 2 ns case must read the ledger whose step_check has both columns;
    the 5 ns case keeps its single-raw ledger unchanged."""
    specs = {spec["name"]: spec for spec in audit.CASES}
    assert specs["candidate_50v_120a"]["ledger"] == audit.LEDGER_50V_120A
    two = specs["candidate_50v_120a_2ns"]
    assert two["ledger"] == audit.LEDGER_50V_120A_STEPS
    assert two["raw"].endswith("_vin50_i120_cin_2n.raw")
    assert (two["periods"], two["vin"], two["rl"]) == (22, 50.0, 16.3e-3)
    # Same deck, same window: only the timestep may differ.
    assert two["vin"] == specs["candidate_50v_120a"]["vin"]
    assert two["rl"] == specs["candidate_50v_120a"]["rl"]


def test_a_case_filter_rejects_unknown_names():
    with pytest.raises(ValueError):
        audit.select_cases(["candidate_50v_110a", "not_a_case"])


def test_a_case_filter_keeps_the_cases_table_order():
    picked = audit.select_cases(["candidate_50v_120a", "candidate_50v_110a"])
    assert [case["name"] for case in picked] == [
        "candidate_50v_110a", "candidate_50v_120a"]


def test_the_111a_candidate_storage_mismatch_is_published_not_corrected_away():
    report = load_report()
    results = report["results"]
    if "candidate_111a_closure_published_single_w" not in results:
        pytest.skip("111 A raw absent from this run")
    assert results["candidate_111a_storage_parameter_mismatch"] is True
    assert results["candidate_111a_closure_after_gate_drive_within_budget"] is False
    assert any("7.05 mF" in line for line in report["limits"])
