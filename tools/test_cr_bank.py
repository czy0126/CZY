"""Tests for tools/cr_bank.py.

Cout is a capacitance floor: more is always allowed.  Cr is not.  The tank has to
run below resonance (M > 1), so fr = 1/(2 pi sqrt(L C)) must stay above the
200.622 kHz clock, and the first article trims the external inductor to
L_total(C) - L_leak.  That makes the bank a *band* coupled to the Lr trim, and
these tests pin the band, the coupling and the procurement rule that falls out.
"""

from __future__ import annotations

import math

import pytest

import cr_bank
from cr_bank import (
    LEAKAGE_TRIM_END_H,
    band_landings,
    deck_params,
    max_nominal_for_tolerance,
    report,
    trim_external,
    tuning,
)

TANK = {
    "total_target_h": 1.0e-6,
    "leakage_model_h": 8.0e-8,
    "external_target_h": 9.2e-7,
    "resonant_khz": 202.12697985378801,
    "clock_khz": 200.622,
}
C_TARGET = 6.2e-7

# What the tank has actually been run at, and therefore all the bank is allowed to
# move within: total 1.00-1.08 uH (1.0 uH external at nominal leakage is 1.08 uH),
# which in external terms is the 0.875-1.0 uH trim window.
TESTED = {"l_total_h": (1.0e-6, 1.08e-6), "l_external_h": (0.875e-6, 1.0e-6)}


def test_the_design_point_is_the_product_of_the_two_simulated_values():
    t = tuning(TANK, C_TARGET, TESTED)
    assert t["lc_product_s2"] == pytest.approx(TANK["total_target_h"] * C_TARGET, rel=1e-12)
    assert t["resonant_hz"] == pytest.approx(202126.97985378801, rel=1e-9)
    # the deck reaches the design frequency only because the two agree
    assert 1.0 / (2 * math.pi * math.sqrt(t["lc_product_s2"])) == pytest.approx(t["resonant_hz"], rel=1e-9)


def test_the_band_is_set_by_the_simulated_inductance_not_by_the_clock():
    t = tuning(TANK, C_TARGET, TESTED)
    # top of the band: the design total inductance, i.e. the 620 nF point itself
    assert t["c_max_f"] == pytest.approx(C_TARGET, rel=1e-12)
    # bottom: a nominal 1.0 uH external part with the model leakage, total 1.08 uH
    assert t["c_min_f"] == pytest.approx(t["lc_product_s2"] / 1.08e-6, rel=1e-12)
    # the clock alone would allow more capacitance; the simulated Lr window is the tighter bound
    assert t["c_clock_ceiling_f"] > t["c_max_f"]
    assert t["c_clock_ceiling_f"] == pytest.approx(
        1.0 / (2 * math.pi * 200622.0) ** 2 / TANK["total_target_h"], rel=1e-12)


def test_the_top_of_the_band_needs_the_nominal_external_inductor():
    t = tuning(TANK, C_TARGET, TESTED)
    # 620 nF with the model leakage: exactly the 0.92 uH external target
    assert trim_external(C_TARGET, t["lc_product_s2"], TANK["leakage_model_h"]) == pytest.approx(9.2e-7, rel=1e-12)
    # 620 nF with the 0.125 uH trim end: exactly the 0.875 uH that was run
    assert trim_external(C_TARGET, t["lc_product_s2"], LEAKAGE_TRIM_END_H) == pytest.approx(8.75e-7, rel=1e-12)


def test_the_whole_band_trims_inside_the_simulated_external_window():
    t = tuning(TANK, C_TARGET, TESTED)
    lo, hi = t["l_external_tested_h"]
    for c in (t["c_min_f"], 0.5 * (t["c_min_f"] + t["c_max_f"]), t["c_max_f"]):
        for leakage in (TANK["leakage_model_h"], LEAKAGE_TRIM_END_H):
            ext = trim_external(c, t["lc_product_s2"], leakage)
            assert lo - 1e-15 <= ext <= hi + 1e-15


def test_five_percent_up_on_a_620_nf_bank_leaves_the_simulated_window():
    t = tuning(TANK, C_TARGET, TESTED)
    lo, _hi = t["l_external_tested_h"]
    worst = C_TARGET * 1.05
    assert worst > t["c_max_f"]
    assert trim_external(worst, t["lc_product_s2"], TANK["leakage_model_h"]) < lo
    # the shortfall is small but real: 2.62 nH, i.e. 0.3 % below the end that was run
    assert lo - trim_external(worst, t["lc_product_s2"], TANK["leakage_model_h"]) == pytest.approx(2.619e-9, abs=1e-12)


def test_tolerance_grades_set_the_highest_buildable_nominal():
    t = tuning(TANK, C_TARGET, TESTED)
    one = max_nominal_for_tolerance(t, 0.01)
    five = max_nominal_for_tolerance(t, 0.05)
    assert one > five
    assert five == pytest.approx(t["c_max_f"] / 1.05, rel=1e-12)
    # +-10 % parts cannot be placed anywhere in the band
    assert max_nominal_for_tolerance(t, 0.10) < t["c_min_f"]


def test_no_single_standard_film_value_lands_in_the_band():
    t = tuning(TANK, C_TARGET, TESTED)
    landings = band_landings(t, cr_bank.E12_NF, max_parts=6, target_f=C_TARGET)
    assert landings
    assert all(landing["n_parts"] >= 2 for landing in landings)
    # 560 nF is under the band and 680 nF is over it
    assert all(landing["total_f"] >= t["c_min_f"] for landing in landings)
    assert all(landing["total_f"] <= t["c_max_f"] for landing in landings)


def test_the_nearest_landing_is_the_two_part_bank_on_target():
    t = tuning(TANK, C_TARGET, TESTED)
    landings = band_landings(t, cr_bank.E12_NF, max_parts=6, target_f=C_TARGET)
    best = landings[0]
    assert best["values_nf"] == [150, 470]
    assert best["n_parts"] == 2
    assert best["total_f"] == pytest.approx(C_TARGET, rel=1e-12)
    assert best["delta_frac"] == pytest.approx(0.0, abs=1e-12)


def test_per_part_current_follows_capacitance_not_the_part_count():
    t = tuning(TANK, C_TARGET, TESTED)
    landings = band_landings(t, cr_bank.E12_NF, max_parts=6, target_f=C_TARGET)
    best = landings[0]
    shares = {round(p["c_f"] * 1e9): p for p in best["per_part"]}
    # unequal parts split by capacitance: 470/620 carries three quarters of the ripple
    assert shares[470]["share_frac"] == pytest.approx(470 / 620, rel=1e-12)
    assert shares[150]["share_frac"] == pytest.approx(150 / 620, rel=1e-12)
    # so the big part needs a 7.16 A rating, not the 4.73 A an equal-share guess gives
    assert shares[470]["irms_a"] == pytest.approx(9.450157142630292 * 470 / 620, rel=1e-9)
    assert shares[150]["irms_a"] == pytest.approx(9.450157142630292 * 150 / 620, rel=1e-9)


def test_equal_parts_share_equally_and_land_below_target():
    t = tuning(TANK, C_TARGET, TESTED)
    landings = band_landings(t, cr_bank.E12_NF, max_parts=6, target_f=C_TARGET)
    equal = [landing for landing in landings if len({p["c_f"] for p in landing["per_part"]}) == 1]
    assert equal, "a four-way split should be available"
    for landing in equal:
        for part in landing["per_part"]:
            assert part["share_frac"] == pytest.approx(1.0 / landing["n_parts"], rel=1e-12)


def test_deck_and_jsons_agree_about_the_tank():
    params = deck_params(cr_bank.DECK)
    assert params["CR_TOTAL"] == pytest.approx(C_TARGET, rel=1e-12)
    assert params["LR_TOTAL"] == pytest.approx(TANK["external_target_h"], rel=1e-12)


def test_the_report_reads_its_numbers_from_the_deck_and_the_two_json_files():
    data = report()
    assert data["requirements"]["capacitance_f"] == pytest.approx(C_TARGET, rel=1e-12)
    assert data["tuning"]["resonant_hz"] == pytest.approx(202126.97985378801, rel=1e-9)
    assert data["sources"]["deck"].endswith("sr_tank_dual_v33_ss_1ms_100a.cir")
    assert data["checks"]["deck_capacitance_matches_the_stress_run"] is True
    assert data["checks"]["deck_external_inductance_matches_the_tank_target"] is True


def test_the_report_says_no_capacitor_datasheet_was_read():
    data = report()
    assert data["no_capacitor_datasheet_in_repository"] is True
    assert "not a selected part" in data["status"]
    for landing in data["landings"]:
        assert all("mpn" not in part for part in landing["per_part"])


def test_every_reported_landing_keeps_the_trim_inside_the_window():
    data = report()
    lo, hi = data["tuning"]["l_external_tested_h"]
    assert data["landings"]
    for landing in data["landings"]:
        for leakage in (data["requirements"]["leakage_model_h"], LEAKAGE_TRIM_END_H):
            ext = trim_external(landing["total_f"], data["tuning"]["lc_product_s2"], leakage)
            assert lo - 1e-15 <= ext <= hi + 1e-15


def test_holding_the_product_fixed_moves_the_tank_impedance_not_the_frequency():
    data = report()
    total_h = data["tuning"]["l_total_tested_h"]
    # at the band bottom the trim restores fr, but Z0 = sqrt(L/C) = L / sqrt(LC) scales with L
    assert data["results"]["tank_impedance_ratio_at_band_bottom"] == pytest.approx(total_h[1] / total_h[0], rel=1e-12)
    assert data["results"]["tank_impedance_ohm_at_design"] == pytest.approx(
        math.sqrt(total_h[0] / data["requirements"]["capacitance_f"]), rel=1e-12)
    assert 1.05 < data["results"]["tank_impedance_ratio_at_band_bottom"] < 1.10


def test_the_physical_results_are_not_in_the_checks_block():
    data = report()
    # structural gates only; the physics lives in results
    assert set(data["checks"]) == {
        "deck_capacitance_matches_the_stress_run",
        "deck_external_inductance_matches_the_tank_target",
        "the_design_product_reproduces_the_tank_frequency",
        "every_landing_is_inside_the_band",
        "every_landing_keeps_fr_above_the_clock",
    }
    assert "c_band_f" in data["results"]
