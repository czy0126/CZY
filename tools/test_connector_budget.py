"""Tests for tools/connector_budget.py.

The bar geometry is exact physics; the joint is a placeholder.  These tests pin
the first and make sure the second never gets reported as if it were known.
"""

from __future__ import annotations

import pytest

from connector_budget import (
    BUS_LENGTH_M,
    BUS_THICKNESS_M,
    BUS_WIDTH_M,
    CONTACT_OHM_PLACEHOLDER,
    DESIGN_BASIS_OHM,
    busbar_resistance,
    contact_weight,
    copper_rho,
    feasibility,
    input_connector,
    joint_limit,
    length_for_resistance,
    output_path,
    surface_area,
    temperature_rise,
)


def test_resistivity_rises_with_temperature_at_the_linear_rate():
    assert abs(copper_rho(20.0) - 1.724e-8) < 1e-18
    # +0.393 %/K: a 60 K rise is +23.6 %
    assert abs(copper_rho(80.0) / copper_rho(20.0) - 1.2358) < 1e-3


def test_bar_resistance_scales_with_length_and_inverse_area():
    a = busbar_resistance(0.1, 0.02, 0.002)
    assert abs(busbar_resistance(0.2, 0.02, 0.002) - 2 * a) < 1e-15
    assert abs(busbar_resistance(0.1, 0.04, 0.002) - a / 2) < 1e-15
    # 20x2 mm copper is 0.431 mohm/m at 20 C
    assert abs(a / 0.1 - 4.31e-4) < 1e-6


def test_bad_geometry_is_rejected():
    with pytest.raises(ValueError):
        busbar_resistance(0.0, 0.02, 0.002)
    with pytest.raises(ValueError):
        busbar_resistance(0.1, 0.0, 0.002)
    with pytest.raises(ValueError):
        length_for_resistance(0.0, 0.02, 0.002)
    with pytest.raises(ValueError):
        temperature_rise(-1.0, 0.08, 0.02, 0.002)


def test_surface_area_counts_faces_and_edges_only():
    assert abs(surface_area(0.08, 0.02, 0.002) - 2 * 0.022 * 0.08) < 1e-15


def test_temperature_rise_grows_with_current_and_falls_with_area():
    small = temperature_rise(50.0, 0.08, 0.02, 0.002)
    big = temperature_rise(100.0, 0.08, 0.02, 0.002)
    assert 0 < small < big
    # roughly I^2, but above 4x because rho rises with the temperature it causes
    assert 4.0 < big / small < 5.0
    assert temperature_rise(100.0, 0.08, 0.04, 0.002) < big


def test_a_better_convection_coefficient_lowers_the_rise():
    assert temperature_rise(100.0, 0.08, 0.02, 0.002, 8.0) < temperature_rise(100.0, 0.08, 0.02, 0.002, 4.0)


def test_length_for_resistance_inverts_bar_resistance():
    r = 0.1e-3
    length = length_for_resistance(r, BUS_WIDTH_M, BUS_THICKNESS_M)
    assert abs(busbar_resistance(length, BUS_WIDTH_M, BUS_THICKNESS_M) - r) < 1e-15


def test_contacts_are_flagged_unverified():
    w = contact_weight()
    assert "UNVERIFIED" in w["status"]
    assert abs(w["contact_total_ohm"] - CONTACT_OHM_PLACEHOLDER * w["contacts"]) < 1e-18
    assert w["frac_of_budget"] > 0


def test_two_placeholder_joints_already_use_up_the_whole_budget():
    """The finding behind `feasible: False`: joints, not copper, set this path."""
    p = output_path()
    assert p["feasible_with_placeholder_contacts"] is False
    assert p["bar"]["max_length_for_budget_mm"] is None
    # the two placeholders land exactly on the budget, leaving zero for copper
    assert p["contact"]["contact_total_ohm"] >= p["budget_ohm"] - 1e-15
    assert p["contact"]["frac_of_budget"] == pytest.approx(1.0)


def test_output_path_reports_the_real_totals_even_when_infeasible():
    p = output_path()
    assert p["bar"]["rise_range_k"]["h=4"] > p["bar"]["rise_range_k"]["h=8"]
    assert abs(p["total_ohm_placeholder"] - (p["bar"]["resistance_ohm"]
                                             + p["contact"]["contact_total_ohm"])) < 1e-15
    assert p["budget_w"] == pytest.approx(1.0)


def test_feasibility_shows_the_budget_is_a_choice():
    f = feasibility()
    rows = {r["joint_ohm"]: r for r in f["rows"]}
    assert rows[20e-6]["path_ohm"] < rows[50e-6]["path_ohm"] < rows[100e-6]["path_ohm"]
    assert rows[50e-6]["path_w"] > 1.0       # the self-chosen 1.0 W is not reachable there


def test_the_design_basis_is_the_number_the_efficiency_estimate_used():
    """92.33 % is carried at a 0.15 mohm path costing 1.495 W.

    Judging the connector against the stricter 0.1 mohm target while the published
    efficiency rests on 0.15 makes the two documents contradict.  Keep them tied.
    """
    assert output_path(budget_ohm=DESIGN_BASIS_OHM)["budget_w"] == pytest.approx(1.5, rel=0.01)
    assert output_path(budget_ohm=DESIGN_BASIS_OHM)["feasible_with_placeholder_contacts"] is True


def test_the_design_basis_yields_a_joint_limit_the_first_article_can_be_measured_against():
    lim = joint_limit()
    expected = (DESIGN_BASIS_OHM - busbar_resistance(BUS_LENGTH_M, BUS_WIDTH_M, BUS_THICKNESS_M)) / 2
    assert lim["per_joint_ohm"] == pytest.approx(expected)
    assert 55e-6 < lim["per_joint_ohm"] < 60e-6      # 57.8 uohm
    assert lim["placeholder_fits"] is True           # 50 uohm is inside it, with 8 uohm of slack


def test_a_longer_bar_eats_the_joint_limit():
    """The limit is not a constant: every extra mm of bar comes out of the joints."""
    assert joint_limit(length_m=0.120)["per_joint_ohm"] < joint_limit()["per_joint_ohm"]


def test_input_trace_width_is_solved_not_guessed():
    i = input_connector()
    assert i["i_rms_a"] < 10.0
    # 2 mm of 2 oz copper is not enough for the measured bridge ripple
    assert i["examples"][0]["w_per_100mm"] > 0.4
    assert i["width_for_target_mm"] > 5.0
    assert abs(i["examples"][-1]["w_per_100mm"] - i["target_w_per_100mm"]) < 1e-3
