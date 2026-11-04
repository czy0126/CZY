"""Tests for tools/magnetics_design.py.

The calculator turns datasheet dimensions and one measured operating point into
a reproducible magnetic design budget.  These tests pin the numbers that the
design package quotes, so a later edit cannot silently change a drawing or a
loss table.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import magnetics_design
import pytest

from magnetics_design import (
    CORE,
    OP,
    OP_100,
    catalogue_core_stack,
    core_gap_m,
    core_loss_bound_w_per_set,
    dowell_fr,
    flux_density,
    foil_resistance,
    height_stack,
    loss_budget,
    output_estimate,
    required_vin_for_pout,
    transformer_copper_loss,
    winding_stack,
)

DESIGN = Path(__file__).resolve().parent.parent / "design" / "v3"
FED = (
    "power_priority/lr_tdk_catalog_core_source.json",
    "power_priority/lr_tdk_catalog_core_screen.json",
    "power_priority/d1_staged_target_policy.json",
    "power_priority/d1_staged_target_screen.json",
)


def _fed_tree(tmp_path: Path) -> Path:
    """A copy of just the files ``catalogue_core_stack()`` reads."""
    for rel in FED:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DESIGN / rel, target)
    return tmp_path


def test_core_gap_hits_target_inductance() -> None:
    gap = core_gap_m(10e-6, 3, CORE["Ae_m2"], CORE["AL_ungapped_nH"])
    assert gap == pytest.approx(0.1211e-3, abs=2e-6)
    # A target at or above the ungapped inductance needs no grinding.
    assert core_gap_m(56.7e-6, 3, CORE["Ae_m2"], CORE["AL_ungapped_nH"]) == 0.0
    # Lower target inductance needs a larger gap.
    assert core_gap_m(5e-6, 3, CORE["Ae_m2"], CORE["AL_ungapped_nH"]) > gap


def test_flux_density_matches_parameters_json() -> None:
    t_on = 1.0 / (2.0 * OP["f_Hz"])
    delta_b, b_pk = flux_density(6.0, t_on, 3, CORE["Ae_m2"])
    assert b_pk == pytest.approx(0.01917, abs=2e-4)
    assert delta_b == pytest.approx(2.0 * b_pk)
    # 50 V input is the worst case: 6.25 V per unit.
    _, b_pk_50 = flux_density(6.25, t_on, 3, CORE["Ae_m2"])
    assert b_pk_50 > b_pk
    assert b_pk_50 < CORE["Bsat_T"] / 10.0


def test_dowell_factor_limits() -> None:
    thin = dowell_fr(1e-6, OP["f_Hz"], 1)
    assert thin == pytest.approx(1.0, abs=0.02)
    single = dowell_fr(0.1e-3, OP["f_Hz"], 1)
    assert 1.0 <= single < 1.10
    three = dowell_fr(0.1e-3, OP["f_Hz"], 3)
    assert three > single
    assert three < 1.30


def test_foil_resistance_order_of_magnitude() -> None:
    r_one = foil_resistance(0.060, 0.018, 0.1e-3, OP["f_Hz"], 1)
    assert 0.70e-3 < r_one < 0.80e-3
    # Two parallel foils are slightly better than half of one foil because the
    # pair has a small proximity penalty.
    r_two = foil_resistance(0.060, 0.018, 0.1e-3, OP["f_Hz"], 2) / 2.0
    assert 0.35e-3 < r_two < r_one / 2.0 * 1.10


def test_core_loss_is_not_a_driver() -> None:
    t_on = 1.0 / (2.0 * OP["f_Hz"])
    _, b_pk = flux_density(6.25, t_on, 3, CORE["Ae_m2"])
    per_set = core_loss_bound_w_per_set(b_pk, OP["f_Hz"])
    assert 0.05 < per_set < 0.12
    assert 4.0 * per_set < 0.50


def test_winding_stack_fits_window() -> None:
    layers, total = winding_stack()
    assert total == pytest.approx(1.10e-3, abs=0.15e-3)
    assert total < CORE["window_height_m"] - CORE["window_tol_m"]
    # The stack must also leave room for the carrier / adhesive.
    assert total + 0.20e-3 < CORE["window_height_m"] - CORE["window_tol_m"]


def test_height_stack_has_margin_without_a_clamp() -> None:
    h = height_stack(glue_m=0.10e-3, label_m=0.05e-3, clamp_m=0.0)
    assert h["nominal_m"] == pytest.approx(9.65e-3, abs=1e-6)
    assert h["worst_case_m"] == pytest.approx(9.95e-3, abs=1e-6)
    assert h["worst_case_m"] <= 10e-3
    assert h["margin_m"] == pytest.approx(0.05e-3, abs=1e-6)


def test_height_stack_fails_with_standard_clamp() -> None:
    h = height_stack(glue_m=0.10e-3, label_m=0.05e-3, clamp_m=0.50e-3)
    assert h["worst_case_m"] > 10e-3


def test_height_worst_case_uses_max_thicknesses() -> None:
    # If the stack uses nominal glue/label for the worst case it underestimates
    # the height.  The 10 mm limit must survive the maximum adhesive and label.
    flat = height_stack(0.05e-3, 0.05e-3, 0.0,
                        glue_max_m=0.08e-3, label_max_m=0.06e-3)
    assert flat["nominal_m"] == pytest.approx(9.60e-3, abs=1e-6)
    assert flat["worst_case_m"] == pytest.approx(9.94e-3, abs=1e-6)
    assert flat["margin_m"] == pytest.approx(0.06e-3, abs=1e-6)

    pocket = height_stack(0.05e-3, 0.05e-3, -0.5e-3,
                          glue_max_m=0.08e-3, label_max_m=0.06e-3)
    assert pocket["worst_case_m"] == pytest.approx(9.44e-3, abs=1e-6)
    assert pocket["margin_m"] == pytest.approx(0.56e-3, abs=1e-6)


def test_transformer_copper_loss_budget() -> None:
    cu = transformer_copper_loss()
    assert 0.65 < cu["primary_w"] < 0.85
    assert 0.90 < cu["secondary_w"] < 1.20
    assert 1.50 < cu["total_w"] < 2.10


def test_100a_currents_are_measured_not_scaled() -> None:
    # Pinned to sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw.  A linear I^2 rescale
    # from 95 A predicts Ipri RMS 9.04 A and Isec 19.05 A; the bench gives
    # 9.45 A / 19.92 A because the current waveform form factor rises.
    assert OP_100["Iout_A"] == pytest.approx(99.82464, abs=5e-3)
    assert OP_100["Vout_V"] == pytest.approx(1.886686, abs=1e-5)
    assert OP_100["Pout_W"] == pytest.approx(188.345331, abs=0.05)
    assert OP_100["Ipri_rms_A"] > OP["Ipri_rms_A"] * 1.09
    assert OP_100["Isec_rms_A"] > OP["Isec_rms_A"] * 1.09


def test_loss_budget_at_95a_and_100a() -> None:
    at95 = loss_budget(OP)
    assert 13.0 < at95["total_loss_w"] < 15.0
    assert 92.0 < at95["efficiency_pct"] < 94.0

    at100 = loss_budget(OP_100)
    assert 14.0 < at100["total_loss_w"] < 16.5
    assert 92.0 < at100["efficiency_pct"] < 93.5
    # The measured 100 A point has 9-10 % more output than 95 A, so its total
    # loss must also be larger, but efficiency must not rise.
    assert at100["total_loss_w"] > at95["total_loss_w"]
    assert at100["efficiency_pct"] < at95["efficiency_pct"]


def test_100a_at_48v_is_below_200w() -> None:
    out48 = output_estimate(48.0, 100.0)
    assert 1.86 < out48["vout_v"] < 1.91
    assert 186.0 < out48["pout_w"] < 191.0
    # 200 W at 100 A is not reachable at 48 V with the model's drop.
    assert out48["pout_w"] < 200.0
    vin_req = required_vin_for_pout(100.0, 200.0)
    assert vin_req > 50.0


def test_output_estimate_scales_with_input() -> None:
    out46 = output_estimate(46.0, 100.0)
    out50 = output_estimate(50.0, 100.0)
    assert out46["pout_w"] < out50["pout_w"]
    assert out50["pout_w"] < 200.0


def test_the_catalogue_stack_reproduces_the_published_10mm_stack() -> None:
    # The screen must run the *same* arithmetic as the design package.  If the
    # two ever disagree, one of them is quoting a number nobody computed.
    published = magnetics_design.design_report()["height"]
    row = next(r for r in catalogue_core_stack()["cores"] if r["id"] == "ELP32_I32")
    assert row["stack_flat_no_clamp_worst_mm"] == pytest.approx(
        published["flat_no_pocket"]["worst_case_m"] * 1e3, abs=1e-9)
    assert row["stack_clamped_worst_mm"] == pytest.approx(
        published["with_0.5mm_clamp"]["worst_case_m"] * 1e3, abs=1e-9)


def test_the_catalogue_elp32_matches_the_datasheet_conversion() -> None:
    # 6.35 +- 0.15 half core plus 3.15 +- 0.15 I plate is 9.8 mm worst case; the
    # constant this module designs to must say the same thing.
    row = next(r for r in catalogue_core_stack()["cores"] if r["id"] == "ELP32_I32")
    assert row["core_pack_worst_mm"] == pytest.approx(CORE["height_max_m"] * 1e3, abs=1e-9)
    assert row["core_pack_nominal_mm"] == pytest.approx(CORE["height_nominal_m"] * 1e3, abs=1e-9)


def test_the_full_stack_moves_elp43_out_of_the_16mm_reserve() -> None:
    """The bare-core screen passed ELP43 with 2.1 mm left; the glue and the
    label are 0.14 mm, so the full stack is 1.96 mm -- under the 2 mm reserve.
    That flip is the whole reason for computing the terms the screen omitted."""
    screen = catalogue_core_stack()
    elp43 = next(r for r in screen["cores"] if r["id"] == "ELP43_I43")
    assert elp43["d1_budget_left_for_tim_cold_plate_fasteners_mm"] < screen["non_core_reserve_mm"]
    assert "ELP43_I43" in screen["screens_the_bare_core_test_passed_but_the_full_stack_does_not"]


def test_elp38_clears_16mm_and_elp32_is_the_only_10mm_set() -> None:
    screen = catalogue_core_stack()
    elp38 = next(r for r in screen["cores"] if r["id"] == "ELP38_I38")
    assert elp38["d1_clears_the_non_core_reserve"] is True
    assert elp38["d1_budget_left_for_tim_cold_plate_fasteners_mm"] == pytest.approx(3.51, abs=0.01)
    assert elp38["d3_10mm_flat_fits"] is False
    fitting_ten = [r["id"] for r in screen["cores"] if r["d3_10mm_flat_fits"]]
    assert fitting_ten == ["ELP32_I32"]


def test_a_taller_core_leaves_less_room() -> None:
    rows = sorted(catalogue_core_stack()["cores"], key=lambda r: r["core_pack_worst_mm"])
    budget = [r["d1_budget_left_for_tim_cold_plate_fasteners_mm"] for r in rows]
    assert budget == sorted(budget, reverse=True)


def test_the_height_limits_come_from_the_policy_not_from_a_literal(tmp_path, monkeypatch) -> None:
    _fed_tree(tmp_path)
    policy_path = tmp_path / "power_priority" / "d1_staged_target_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    for stage in policy["stages"]:
        if stage["id"] == "D1_100A":
            stage["height_limit_mm"] = 12.0
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(magnetics_design, "DESIGN", tmp_path)
    screen = catalogue_core_stack()
    assert screen["limits_mm"]["D1_100A_and_D2_120A"] == 12.0
    # At 12 mm only the smallest set can carry the known stack.
    assert screen["cores_clearing_the_16mm_reserve"] == ["ELP32_I32"]


def test_a_catalogue_height_that_disagrees_with_the_published_screen_is_refused(
        tmp_path, monkeypatch) -> None:
    _fed_tree(tmp_path)
    catalogue = tmp_path / "power_priority" / "lr_tdk_catalog_core_source.json"
    data = json.loads(catalogue.read_text(encoding="utf-8"))
    data["cores"][1]["plate_height_nom_mm"] += 0.5      # ELP38 plate is not 3.8 mm
    catalogue.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(magnetics_design, "DESIGN", tmp_path)
    with pytest.raises(SystemExit, match="stale"):
        catalogue_core_stack()


def test_the_screen_states_what_it_does_not_know() -> None:
    screen = catalogue_core_stack()
    unknowns = " ".join(screen["unknowns"])
    assert "L(I)" in unknowns
    assert "TIM" in unknowns
    assert screen["gate"].startswith("NOT_A_STACK")
    assert screen["non_core_terms"]["evidence"].startswith("ASSUMED/DESIGN")


def test_all_design_numbers_are_finite_and_positive() -> None:
    cu = transformer_copper_loss()
    for key, value in cu.items():
        assert math.isfinite(value)
        assert value > 0.0
