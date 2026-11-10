"""Fail-closed regression for the G1 100 A source-to-load interface screen.

The screen exists to answer one question with geometry taken from the live
native readback: can a bottom-side two-pole bar pair carry the four CTAP and
eight SR-source lands to a load interface inside the 150 uohm both-rail
placeholder budget?  The tests lock the decisions that matter, including the
ways the first version of this screen was too optimistic:

* the transverse path (pads on the bar centreline, terminal at the inner edge)
  is a real term -- 0.5 square per rail -- and charging it flips 39 x 4 mm
  from "barely passes" to "fails at every lug width";
* collector loss is flat over a whole feed interval, so the 39 mm lug is a
  design choice, not a physical bound; the centre feed is the worst corner;
* each scenario row computes its own leg length from its own bar width -- the
  30 mm row is not the 39 mm row and at 50 uohm joints it fails;
* the J_OUT termination is only a lower bound because its VOUT leg crosses
  the PGND bar;
* the 30 uohm transition, the 20/50 uohm joints and the 6.798 uohm external
  pair are unverified math cases, and the report says so;
* the numbers are bound to the candidate SHA, the canonical readback hash, the
  actual D-02 parent file and the base-board outline report, so a different
  board, a stale receipt or a shifted geometry is refused.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g1_100a_output_interface as O


def test_equal_tap_collector_is_load_weighted_not_full_length():
    taps = [37.0, 75.0, 113.0, 151.0]
    assert O.weighted_length_mm(taps, 151.0) == pytest.approx(33.25, abs=1e-9)
    assert O.weighted_length_mm(taps, 37.0) == pytest.approx(33.25, abs=1e-9)
    assert O.weighted_length_mm(taps, 75.0) == pytest.approx(14.25, abs=1e-9)
    assert O.weighted_length_mm(taps, 94.0) == pytest.approx(14.25, abs=1e-9)
    with pytest.raises(ValueError):
        O.weighted_length_mm([], 0.0)
    with pytest.raises(ValueError):
        O.weighted_length_mm([37.0, 75.0], 20.0)


def test_best_feed_grid_is_clamped_to_the_tap_span():
    # round(lo + n*0.1) overshoots a 140.0 upper tap unless the grid is clamped.
    feed, loss = O.best_feed([37.0002, 75.0011, 112.9995, 140.0])
    assert 37.0002 <= feed <= 140.0
    assert loss == pytest.approx(13.5622, abs=0.01)


def test_feed_plateau_is_flat_between_the_central_taps():
    lo, hi, loss = O.feed_plateau([37.0002, 75.0011, 112.9995, 151.0005])
    # The taps themselves are plateau endpoints; a 0.1 mm grid alone would stop
    # 0.1 mm short of both and understate the widest equal-loss pitch.
    assert (lo, hi) == pytest.approx((75.0011, 112.9995), abs=1e-4)
    assert loss == pytest.approx(14.2497, abs=1e-3)
    # Every feed in the interval is equally low-loss ...
    for x in (76.0, 94.0, 110.0):
        assert O.weighted_length_mm([37.0002, 75.0011, 112.9995, 151.0005], x) == pytest.approx(loss, abs=1e-3)
    # ... while an end feed is not.
    assert O.weighted_length_mm([37.0002, 75.0011, 112.9995, 151.0005], 37.0002) == pytest.approx(33.25, abs=0.01)


def test_sheet_resistance_and_bar_math_at_100c():
    # rho(100C) = 1.724e-8*(1+0.00393*80) = 2.2660256e-8 ohm*m
    assert O.bar_uohm(132.29, 30.0, 5.0) == pytest.approx(19.988, abs=0.01)
    assert O.bar_uohm(27.0, 39.0, 3.0) == pytest.approx(5.229, abs=0.01)
    assert O.sheet_uohm_per_square(3.0) == pytest.approx(7.5534, abs=1e-4)
    assert O.bar_uohm(1.0, 30.0, 5.0) > O.bar_uohm(1.0, 30.0, 6.0)
    with pytest.raises(ValueError):
        O.bar_uohm(1.0, 0.0, 5.0)


def test_through_post_is_a_lower_bound_not_a_measurement():
    # 1.5 mm diameter, 1.6 mm board, 100 C
    assert O.post_uohm(1.5, 1.6) == pytest.approx(20.518, abs=0.01)
    assert O.post_uohm(1.5, 1.6) > O.post_uohm(1.5, 1.6, temp_c=20.0)


def test_lands_come_from_the_live_readback_not_from_constants():
    value, identity = O.load()
    lands = O.find_lands(value)
    assert [round(p["x_mm"], 4) for p in lands["vout"]] == [
        37.0002, 75.0011, 112.9995, 151.0005]
    assert len(lands["pgnd"]) == 8
    assert {round(p["y_mm"], 2) for p in lands["pgnd"]} == {84.47}
    assert len(lands["jout"]) == 2
    assert identity["candidate_sha256"] == O.sha256_file(O.BOARD)


def test_rotated_sr_tab_reports_its_true_extents():
    # 23.6 x 129.9 mil RECT at Rotation 90: the 129.9 mil side lies along x.
    value, identity = O.load()
    lands = O.find_lands(value)
    tab = lands["pgnd"][0]
    assert tab["rotation_deg"] == 90.0
    assert tab["half_x_mm"] == pytest.approx(1.6497, abs=1e-4)
    assert tab["half_y_mm"] == pytest.approx(0.2997, abs=1e-4)


def test_board_only_native_necks_never_reach_the_budget():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    baseline = result["topologies"]["board_only_existing"]
    by_um = {s["nominal_thickness_um"]: s for s in baseline["scenarios"]}
    assert by_um[70]["combined_necks_uohm"] == pytest.approx(1882.827, abs=0.5)
    assert all(not s["within_complete_rail_budget"] for s in baseline["scenarios"])
    assert baseline["times_budget_at_70um"] == pytest.approx(12.552, abs=0.01)
    assert "neck" in baseline["scope"]
    # The neck tool's own limitation names the Lr board; this report runs on the
    # signal-stubs candidate and must restate its own binding.
    assert all("Lr board" not in m for m in baseline["model_limitations"])
    assert any("signal-stubs" in m for m in baseline["model_limitations"])


def test_central_reference_is_under_budget_with_the_transverse_term_charged():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    central = result["topologies"]["central_two_pole_bar"]["reference"]
    assert central["bar_width_mm"] == 39.0
    assert central["bar_thickness_mm"] == 5.0
    assert central["one_dimensional_uohm"] == pytest.approx(6.199, abs=0.01)
    assert central["transverse_allowance_uohm"] == pytest.approx(4.532, abs=0.01)
    assert central["bar_uohm"] == pytest.approx(10.731, abs=0.01)
    assert central["total_uohm"] == pytest.approx(147.529, abs=0.01)
    assert central["margin_uohm"] == pytest.approx(2.471, abs=0.01)
    assert central["meets_150_uohm"] is True
    # The 5 mm reference would also pass without the transverse term; it is the
    # 4 mm cases that the term flips (asserted in the next test).
    assert central["total_uohm"] - central["transverse_allowance_uohm"] < 150.0


def test_four_mm_fails_at_every_lug_width_at_50_uohm_joints_only():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    conclusion = result["conclusion"]
    assert conclusion["verdict_joint_scenario_uohm"] == 50.0
    assert conclusion["four_mm_best_case_uohm"] == pytest.approx(150.212, abs=0.01)
    assert conclusion["four_mm_fails_at_every_lug_width_at_50_uohm_joints"] is True
    assert all(not c["meets_150_uohm"]
               for c in conclusion["four_mm_configurations"])
    centre = conclusion["centre_fed_four_mm"]
    assert centre["total_uohm"] == pytest.approx(155.205, abs=0.01)
    assert centre["margin_uohm"] < 0.0
    # The transverse allowance is what flips 4 mm: without it the best 4 mm row
    # would be 144.547 uohm and pass.
    best = next(c for c in conclusion["four_mm_configurations"]
                if c["feed"] == "widest_equal_loss")
    assert best["total_uohm"] - best["transverse_allowance_uohm"] < 150.0
    # The same report declares 20 uohm joints, where 4 mm (and 2 mm) pass; the
    # unconditional "4 mm fails" wording would be false.
    by_joint = {v["separable_joint_uohm_each"]: v for v in conclusion["per_joint_verdicts"]}
    assert by_joint[50.0]["four_mm_meets_150_uohm"] is False
    assert by_joint[50.0]["thinnest_modelled_passing_bar_mm"] == 5.0
    assert by_joint[20.0]["four_mm_meets_150_uohm"] is True
    assert by_joint[20.0]["thinnest_modelled_passing_bar_mm"] == 2.0


def test_the_centre_feed_is_one_mid_pitch_choice_not_a_bound():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    conclusion = result["conclusion"]
    centre_5mm = conclusion["centre_fed_reference_thickness"]
    assert centre_5mm["total_uohm"] == pytest.approx(151.523, abs=0.01)
    assert centre_5mm["meets_150_uohm"] is False
    by_thickness = {(c["feed"], c["bar_thickness_mm"]): c
                    for c in result["topologies"]["central_two_pole_bar"]["configurations"]}
    assert by_thickness[("centre", 6.0)]["total_uohm"] == pytest.approx(149.069, abs=0.01)
    assert by_thickness[("centre", 6.0)]["meets_150_uohm"] is True
    assert by_thickness[("widest_equal_loss", 6.0)]["total_uohm"] == pytest.approx(145.741, abs=0.01)
    assert conclusion["minimum_modelled_passing_thickness_at_50_uohm_mm"] == 5.0
    # Narrower equal-loss pitches are reachable and worse than the centre feed,
    # so the centre-feed number is a choice, not a worst-case bound.
    rows = {r["leg_width_mm"]: r for r in
            result["topologies"]["central_two_pole_bar"]["leg_width_sensitivity"]}
    assert rows[12.0]["total_uohm"] > centre_5mm["total_uohm"]
    assert rows[8.0]["total_uohm"] > rows[12.0]["total_uohm"]


def test_leg_width_break_even_is_a_design_requirement_at_the_reference():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    central = result["topologies"]["central_two_pole_bar"]
    feeds = central["feeds"]
    assert feeds["centre"]["pole_pitch_mm"] == pytest.approx(18.5992, abs=1e-3)
    assert feeds["centre"]["leg_width_mm"] == pytest.approx(16.5992, abs=1e-3)
    assert feeds["widest_equal_loss"]["pole_pitch_mm"] == pytest.approx(51.6001, abs=1e-3)
    assert feeds["widest_equal_loss"]["leg_width_mm"] == pytest.approx(39.0, abs=1e-6)
    assert feeds["widest_equal_loss"]["vout_flat_interval_mm"] == pytest.approx(
        [75.0011, 112.9995], abs=1e-3)
    assert feeds["widest_equal_loss"]["pgnd_flat_interval_mm"] == pytest.approx(
        [61.3994, 89.4004], abs=1e-3)
    break_even = result["conclusion"]["leg_width_break_even_mm"]
    assert break_even == pytest.approx(21.2551, abs=0.01)
    # The centre-feed lug is below the break-even, so a 39 x 5 mm pass *requires*
    # choosing a wider pitch; it is not available at the centre feed.
    assert feeds["centre"]["leg_width_mm"] < break_even
    assert break_even < feeds["widest_equal_loss"]["leg_width_mm"]


def test_leg_width_sensitivity_shows_where_the_pass_breaks():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    rows = {r["leg_width_mm"]: r for r in
            result["topologies"]["central_two_pole_bar"]["leg_width_sensitivity"]}
    assert rows[39.0]["meets_150_uohm"] is True
    assert rows[39.0]["total_uohm"] == pytest.approx(147.529, abs=0.01)
    assert rows[22.0]["meets_150_uohm"] is True
    assert rows[20.0]["meets_150_uohm"] is False
    assert rows[16.5992]["total_uohm"] == pytest.approx(151.523, abs=0.01)
    assert rows[8.0]["total_uohm"] == pytest.approx(158.998, abs=0.01)


def test_each_scenario_uses_its_own_bar_width_for_the_leg():
    # The first version applied the 39 mm leg to every row; the 30 mm bar sits
    # 4.5 mm further from each row centre, and at 50 uohm joints that flips the
    # verdict from pass to fail.
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    rows = {(r["bar_width_mm"], r["bar_thickness_mm"]): r
            for r in result["topologies"]["central_two_pole_bar"]["scenarios_at_widest_feed"]}
    assert rows[(30.0, 5.0)]["leg_length_mm"] == pytest.approx(
        {"vout": 17.2351, "pgnd": 17.2351}, abs=1e-3)
    assert rows[(39.0, 5.0)]["leg_length_mm"] == pytest.approx(
        {"vout": 12.7351, "pgnd": 12.7351}, abs=1e-3)
    case_50 = rows[(30.0, 5.0)]["cases"][1]
    assert case_50["separable_joint_uohm_each"] == 50.0
    assert case_50["total_uohm"] == pytest.approx(150.748, abs=0.01)
    assert case_50["meets_150_uohm"] is False


def test_jout_is_a_non_realizable_lower_bound_not_a_candidate():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    jout = result["topologies"]["jout_terminated_bar"]
    assert jout["vout_leg_crosses_pgnd_bar"] is True
    assert jout["realizable_as_drawn"] is False
    assert jout["leg_width_is_a_lower_bound"] is True
    assert jout["reference"]["total_uohm"] == pytest.approx(154.944, abs=0.01)
    assert jout["reference"]["meets_150_uohm"] is False
    assert jout["collector_equivalent_length_mm"]["vout"] == pytest.approx(15.0003, abs=1e-2)
    assert result["conclusion"]["jout_terminated_bar_is_the_100a_path"] is False


def test_the_joint_requirement_is_the_deliverable_not_a_relaxed_budget():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    central = result["topologies"]["central_two_pole_bar"]["reference"]
    # 150 - bar 10.731 - 30 transition - 6.798 external, split over two poles.
    assert central["max_separable_joint_uohm_each"] == pytest.approx(51.235, abs=0.01)
    assert result["design_basis"]["both_rails_budget_uohm"] == 150.0
    assert result["design_basis"]["transition_allowance_uohm"] == 30.0
    assert result["design_basis"]["transition_allowance_is_unverified"] is True
    assert result["design_basis"]["joints_per_pole"] == 1
    assert result["design_basis"]["requires_one_verified_separable_joint_per_pole"] is True
    assert result["fabrication_approved"] is False


def test_the_external_pair_is_flagged_unverified_with_its_alternatives():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    basis = result["design_basis"]
    assert basis["external_link_uohm"] == pytest.approx(6.798, abs=1e-9)
    assert basis["external_link_case"] == "reduced_2_contacts_50x2x15"
    assert basis["external_link_is_unverified"] is True
    assert basis["external_link_cases_are_math_only"] is True
    assert basis["source_hardware_qualified"] is False
    assert "UNVERIFIED" in basis["source_status"]
    alternatives = result["conclusion"]["external_link_same_joint_alternatives"]
    assert alternatives, "the same-joint alternatives must be reported"
    assert all(a["total_uohm"] > 150.0 for a in alternatives), (
        "every same-joint alternative must show why the chosen pair is the only pass")


def test_transition_allowance_bounds_and_break_even():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    conclusion = result["conclusion"]
    bounds = conclusion["transition_modelled_bounds_uohm"]
    # Two 1.5 mm x 1.6 mm posts in series vs all 12 lands in parallel.
    assert bounds["one_post_per_rail_in_series"] == pytest.approx(41.034, abs=0.01)
    assert bounds["all_12_lands_paralleled"] == pytest.approx(7.694, abs=0.01)
    assert conclusion["transition_break_even_uohm"] == pytest.approx(32.471, abs=0.01)
    assert bounds["all_12_lands_paralleled"] < conclusion["transition_break_even_uohm"]
    assert conclusion["transition_break_even_uohm"] < bounds["one_post_per_rail_in_series"]


def test_single_land_current_sharing_is_reported_as_a_failure():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    conclusion = result["conclusion"]
    assert conclusion["current_sharing"].startswith("equal")
    assert conclusion["single_land_total_uohm"] == pytest.approx(161.953, abs=0.01)
    assert conclusion["single_land_total_uohm"] > 150.0


def test_geometry_reports_the_real_obstacles_instead_of_pretending_none():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    geometry = result["geometry"]
    assert geometry["board_mm"] == [155.0, 131.0]
    assert geometry["max_centred_bar_width_mm"] == pytest.approx(39.4, abs=1e-9)
    assert geometry["terminal_y_mm"] == pytest.approx(52.2351, abs=1e-6)
    assert geometry["jout_inside_bar_pair"] is False
    assert geometry["bars_inside_board"] is True
    assert geometry["bottom_copper_under_pgnd_bar"], (
        "the central signal cluster must be reported, not silently ignored")
    # The outline comes from the *base* board report, not from the candidate or
    # its D-02 parent; the label must say so, and the md5 must be verified.
    assert geometry["board_outline_is_base_board_provenance"] is True
    assert geometry["board_outline_is_parent_provenance"] is False
    assert geometry["base_board_file_md5_verified"] is True
    assert geometry["board_outline_dimensions_verified"] is False
    assert "base board" in geometry["board_outline_source"]
    assert "neither the candidate" in geometry["board_outline_source"]
    assert geometry["board_outline_consistent_with_lands"] is True
    # The rotated SR tab widens the PGND bar by 1.35 mm on each side.
    assert geometry["pgnd_bar_rect_mm"]["x"] == pytest.approx([11.751, 139.051], abs=1e-3)


def test_a_bar_that_overhangs_the_outline_is_refused():
    value, identity = O.load()
    lands = O.find_lands(value)
    with pytest.raises(ValueError, match="overhangs"):
        O._geometry(value, lands, 39.0, dict(identity, board_mm=[100.0, 100.0]))


def test_geometry_counts_through_vias_as_well_as_tracks():
    value, identity = O.load()
    result = O.build(value=value, identity=identity)
    geometry = result["geometry"]
    vias = geometry["bottom_vias_under_pgnd_bar"]
    assert len(vias) == 4
    assert {v["net"] for v in vias} == {"VCC12", "PGND", "CS1"}
    assert geometry["bottom_vias_under_vout_bar"] == []
    assert len(geometry["bottom_tracks_under_pgnd_bar"]) == 5


def test_the_parent_binding_hashes_the_real_d02_file():
    value, identity = O.load()
    assert identity["parent_cad_sha256"] == O.sha256_file(O.PARENT)
    assert identity["parent_cad_sha256"] == identity["report_parent_sha256"]
    assert identity["parent_cad_sha256"].startswith("552628f0")
    assert identity["outline"]["md5_verified"] is True
    assert identity["outline"]["board_path"].endswith("dcx_main_board_g1.eprj2")


def test_a_receipt_naming_a_different_parent_is_refused(monkeypatch):
    # Point the receipt's parent at the base board: the path check must fire
    # before any hash comparison, so a receipt copy can never stand in.
    monkeypatch.setattr(O, "PARENT", O.G1 / "dcx_main_board_g1.eprj2")
    with pytest.raises(ValueError, match="different parent board"):
        O.load()


def test_a_failed_or_inconsistent_receipt_is_refused(tmp_path, monkeypatch):
    report = json.loads(O.REVIEW.read_text(encoding="utf-8"))
    cases = [
        ("status", "REVIEW_FAILED", {}, "accepted"),
        ("cad_unchanged", False, {}, "unchanged CAD"),
        ("geometry", None, {"status": "NOT_REOPENED"}, "reopened geometry"),
    ]
    for name, bad_value, geometry_patch, match in cases:
        edited = dict(report)
        if name == "geometry":
            edited["geometry"] = dict(report["geometry"], **geometry_patch)
        else:
            edited[name] = bad_value
        path = tmp_path / f"receipt_{name}.json"
        path.write_text(json.dumps(edited), encoding="utf-8")
        monkeypatch.setattr(O, "REVIEW", path)
        with pytest.raises(ValueError, match=match):
            O.load()


def test_a_receipt_bound_to_another_board_or_readback_is_refused():
    value, identity = O.load()
    for key in ("candidate_sha256", "report_candidate_sha256", "readback_sha256",
                "readback_value_sha256", "parent_cad_sha256"):
        tampered = dict(identity, **{key: "0" * 64})
        with pytest.raises(ValueError, match=key):
            O.build(value=value, identity=tampered)
    tampered = dict(identity, native_drc_passed=True)
    with pytest.raises(ValueError, match="DRC"):
        O.build(value=value, identity=tampered)
    unverified = dict(identity, outline=dict(identity["outline"], md5_verified=False))
    with pytest.raises(ValueError, match="outline"):
        O.build(value=value, identity=unverified)


def test_shifted_geometry_cannot_ride_the_bound_readback_hash():
    value, identity = O.load()
    shifted = json.loads(json.dumps(value))
    shifted["pads"][0]["X"] += 100.0
    with pytest.raises(ValueError, match="readback_value_sha256"):
        O.build(value=shifted, identity=identity)


def test_a_committed_report_reproduces():
    value, identity = O.load()
    assert O.build(value=value, identity=identity) == json.loads(
        O.REPORT.read_text(encoding="utf-8"))
