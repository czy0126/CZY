"""Tests for tools/output_path_budget.py (Issue #12 item 4).

The sheet-resistance arithmetic is exact; the *geometry* it is applied to comes
from the placement study, so these tests are mostly about making sure the two
stay wired together.  If someone moves J_OUT in `main_board_mechanical.PARTS`
and the gap does not change, the tool has stopped reading the board and started
reprinting a number.

The one result worth defending is the negative one: **no combination of copper
weight and busbar width closes 0.15 mohm.**  A test asserts that, because the
temptation is to widen the busbar until the table looks green and quietly drop
the joint term.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import connector_budget as cb  # noqa: E402
import main_board_mechanical as mbm  # noqa: E402
import output_path_budget as opb  # noqa: E402

JSON = Path(__file__).resolve().parent.parent / "design/v3/pcb/output_path_budget.json"


# ---------------------------------------------------------------- sheet model
def test_one_square_scales_with_copper_weight():
    """R_sheet = rho/t, so halving the thickness doubles the resistance."""
    a = opb.sheet_ohm_square(2 * opb.OZ_M)
    b = opb.sheet_ohm_square(4 * opb.OZ_M)
    assert a == pytest.approx(2 * b, rel=1e-12)
    # 2 oz annealed copper at 100 C: rho = 1.724e-8 * (1 + 0.00393*80) = 2.266e-8
    assert a * 1e3 == pytest.approx(0.3237, abs=1e-4)


def test_the_budget_is_a_square_count_not_an_ohm_value():
    """The whole point of the reformulation: 0.15 mohm is 0.46 squares at 2 oz."""
    r_sq = opb.sheet_ohm_square(2 * opb.OZ_M)
    assert opb.DESIGN_BASIS_OHM / r_sq == pytest.approx(0.46, abs=0.01)
    data = opb.budget(2 * opb.OZ_M)
    assert data["budget_in_squares"] == pytest.approx(0.46, abs=0.01)


def test_bad_thickness_is_rejected():
    with pytest.raises(ValueError):
        opb.sheet_ohm_square(0.0)


# ---------------------------------------------------------------- geometry
def test_the_geometry_comes_from_the_placement_not_a_constant():
    """Groups live where `main_board_mechanical.PARTS` puts them."""
    geom = opb._geometry()
    placement = {p["ref"]: p for p in mbm.report()["parts"]}
    for g in geom["groups"]:
        xs = [placement[ref]["x_mm"] for ref in g["refs"]]
        assert g["x_mm"] == pytest.approx(sum(xs) / 2.0)
        assert g["y_mm"] == placement[g["refs"][0]]["y_mm"]


def test_only_the_groups_outside_the_busbar_have_a_neck():
    """The finding, expressed as geometry: the bar is centred on the SR row, so
    it covers x = 36..116 mm while the row runs 19..133 mm.  Groups 2 and 3 sit
    under it; groups 1 and 4 each travel the same 17 mm sideways.

    This used to be 41 mm for group 1 and nothing for groups 3 and 4, because
    the bar sat at x = 100 -- centre-ish for an 80 mm board but not for the row
    it serves.  The equality of the two outer necks is the whole point of the
    centring, so it is asserted rather than the individual number.
    """
    data = opb.budget(2 * opb.OZ_M)
    necks = {row["group"]: row["horizontal_neck_mm"] for row in data["groups"]}
    assert necks[2] == 0.0 and necks[3] == 0.0, necks
    assert necks[1] > 0.0 and necks[1] == pytest.approx(necks[4]), necks
    assert data["remedy"]["groups_outside_the_busbar"] == [1, 4]


def test_the_busbar_sits_on_the_centre_of_the_row_it_serves():
    """Move a group and the bar must follow -- or at least the report must say
    it did not.  ``_sr_row_centre()`` derives 76.0 from ``SR_X0``; a literal
    there would silently reintroduce the offset that made group 1 pay 3.91x."""
    geom = opb._geometry()
    xs = [g["x_mm"] for g in geom["groups"]]
    assert geom["parts"]["J_OUT"]["x_mm"] == pytest.approx((min(xs) + max(xs)) / 2.0)


def test_the_worst_group_no_longer_exceeds_the_whole_converters_output_resistance():
    """At x = 100 group 1's plane path was 1.188 mohm against a measured
    ``r_out_equiv`` of 1.135 mohm -- one local branch larger than the whole
    converter's output-referred resistance.  Centring the bar takes it to 0.671,
    and this test is the guard on that: putting the bar back off-centre has to
    break it, otherwise the placement is not doing the work the doc claims.
    """
    data = opb.budget(2 * opb.OZ_M)
    assert data["versus_the_model"]["worst_group_over_model"] < 1.0

    geom = opb._geometry()
    off_centre = dict(geom["parts"]["J_OUT"], x_mm=100.0)
    rows = opb.per_group(geom, 2 * opb.OZ_M, opb.T_C, off_centre)
    worst = max(r["r_mohm"] for r in rows) * 1e-3
    assert worst / (data["versus_the_model"]["r_out_equiv_mohm"] * 1e-3) > 1.0


# ---------------------------------------------------------------- the negative result
def test_widening_equalises_the_groups_but_is_not_free():
    """The lever is not free, and the price is paid out of the joint budget.

    An earlier version of this table charged every option the *placed* bar's
    resistance while giving the wide option a 134 mm footprint, so widening
    looked 0.03 mohm cheaper than it is.  Carrying the current 54 mm further
    raises the bar term, and -- the part that matters -- it cuts the per-joint
    allowance ``connector_budget.joint_limit()`` publishes as the first-article
    acceptance number from 57.8 to 46.1 uohm, below the 50 uohm placeholder.
    """
    opts = {(o["copper_oz"], o["busbar"]): o for o in opb.budget(2 * opb.OZ_M)["remedy"]["options"]}
    narrow = next(v for k, v in opts.items() if k[0] == 2 and "现状" in k[1])
    wide = next(v for k, v in opts.items() if k[0] == 2 and "加宽" in k[1])
    assert wide["spread_ratio"] == pytest.approx(1.0, abs=0.01)
    assert wide["worst_group_mohm"] < narrow["worst_group_mohm"] / 2.0

    assert wide["busbar_length_mm"] > narrow["busbar_length_mm"]
    assert wide["busbar_mohm"] > narrow["busbar_mohm"]
    assert narrow["joint_limit_ohm"] == pytest.approx(cb.joint_limit()["per_joint_ohm"], rel=1e-9)
    assert wide["joint_limit_ohm"] < narrow["joint_limit_ohm"]
    assert narrow["the_50_uohm_placeholder_still_fits"] is True
    assert wide["the_50_uohm_placeholder_still_fits"] is False


def test_at_4_oz_the_wider_bar_is_the_worse_option():
    """The old table said 4 oz + widen (0.183) beat 4 oz + narrow (0.213).  With
    each option paying its own bar, the ranking flips: 0.206 narrow against
    0.214 wide.  Widening buys spread 2.20 -> 1.00 and costs 8 uohm of total
    path plus the joint allowance; it is a trade, not a free improvement."""
    opts = opb.budget(2 * opb.OZ_M)["remedy"]["options"]
    four = {o["busbar"]: o for o in opts if o["copper_oz"] == 4}
    narrow = next(v for k, v in four.items() if "现状" in k)
    wide = next(v for k, v in four.items() if "加宽" in k)
    assert narrow["path_total_mohm"] < wide["path_total_mohm"]
    assert narrow["spread_ratio"] > wide["spread_ratio"]


def test_no_option_closes_the_design_basis():
    """The honest negative, locked the same way connector_budget.py locks its.

    Best case under the equal-25A-per-group assumption is about 0.206 mohm, and
    that already assumes the 50 uohm placeholder joint is real.  If a future
    layout does close it, this test should be *updated with the evidence*, not
    relaxed -- but it must not go green by dropping the joint or busbar terms.
    """
    data = opb.budget(2 * opb.OZ_M)
    best = min(data["remedy"]["options"], key=lambda o: o["path_total_mohm"])
    assert best["copper_oz"] == 4 and "现状" in best["busbar"]
    assert best["path_total_mohm"] == pytest.approx(0.206, abs=0.01)
    assert not any(o["feasible_on_design_basis"] for o in data["remedy"]["options"])


def test_the_joint_term_is_carried_as_unverified():
    data = opb.budget(2 * opb.OZ_M)
    assert data["resistance"]["joints_are"].startswith("UNVERIFIED")
    assert data["resistance"]["joints_mohm"] == pytest.approx(
        cb.CONTACTS_PER_PATH * cb.CONTACT_OHM_PLACEHOLDER * 1e3, rel=1e-9)


def test_the_report_names_what_the_model_does_not_cover():
    not_modelled = opb.budget(2 * opb.OZ_M)["model"]["not_modelled"]
    assert any("finite-element" in x for x in not_modelled)
    assert any("via" in x for x in not_modelled)
    assert "not a rigorous" in opb.budget(2 * opb.OZ_M)["model"]["direction"]
    assert any("current sharing" in x for x in not_modelled)


def test_the_a6_document_quotes_these_numbers():
    """``A6_机械剖面_2026-11-01.md`` §4 is what a layout engineer reads.  Every
    figure there must trace back to this tool, otherwise the prose outlives the
    geometry -- and the geometry is the part that changes when someone moves a
    part."""
    doc = (Path(__file__).resolve().parent.parent
           / "design/v3/A6_机械剖面_2026-11-01.md").read_text(encoding="utf-8")
    data = opb.budget(2 * opb.OZ_M)
    assert f"{data['sheet_mohm_per_square']:.3f} mΩ/方块" in doc
    assert f"{data['budget_in_squares']:.2f} 个方块" in doc
    for row in data["groups"]:
        assert f"{row['squares']:.2f}" in doc, row["group"]
        assert f"{row['r_mohm']:.3f} mΩ" in doc, row["group"]
    for opt in data["remedy"]["options"]:
        assert f"{opt['worst_group_mohm']:.3f} mΩ" in doc, opt
        assert f"{opt['path_total_mohm']:.3f} mΩ" in doc, opt
    assert f"{data['resistance']['total_mohm']:.3f} mΩ" in doc
    assert f"{data['loss_w_at_100a']['total']:.2f} W" in doc
    assert f"{data['versus_the_model']['r_out_equiv_mohm']:.3f} mΩ" in doc


# ---------------------------------------------------------------- freshness
def test_the_committed_json_is_what_the_tool_produces():
    committed = json.loads(JSON.read_text(encoding="utf-8"))
    fresh = opb.budget(2 * opb.OZ_M)
    fresh["remedy"] = opb.remedy(2 * opb.OZ_M)
    for key in ("copper_weight_oz", "sheet_mohm_per_square", "budget_in_squares",
                "groups", "resistance", "loss_w_at_100a", "versus_the_model",
                "remedy", "model"):
        assert committed[key] == fresh[key], f"{key} is stale -- rerun the tool"
    assert committed["feasible_on_design_basis"] == fresh["feasible_on_design_basis"]


def test_four_branches_not_one_hundred_amps_through_worst_lane():
    """At four exactly 25 A currents, sum(Ibranch² * Rbranch), not 100² * max(R)."""
    data = opb.budget(2 * opb.OZ_M)
    r_eq = sum(g["r_mohm"] for g in data["groups"]) / 16.0
    assert data["resistance"]["plane_mohm"] == pytest.approx(r_eq, abs=0.001)
    assert data["loss_w_at_100a"]["plane"] == pytest.approx(
        sum(g["p_w"] for g in data["groups"]), abs=0.004)
    assert data["resistance"]["plane_mohm"] < data["worst_group"]["r_mohm"] / 4.0
    assert data["loss_w_at_100a"]["total"] < 4.0  # previous 13.33 W was a math error


def test_loss_for_power_scenario_not_confused_with_released_rating():
    data = opb.budget(2 * opb.OZ_M)
    assert data["feasible_on_design_basis"] is False
    assert data["within_exploratory_budget"] is True
    assert data["exploratory_budget_is_not_rating"] is True
    assert data["targets"]["exploratory_mohm"] == pytest.approx(0.30)
