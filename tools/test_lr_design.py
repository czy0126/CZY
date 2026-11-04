"""Tests for tools/lr_design.py.

The sizing rule is `B = L*I/(N*Ae) <= 0.9*Bsat` at the worst fault current, so
the tests pin that identity and the two OC-delay cases that it decides.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lr_design import (
    LK_MODEL_H,
    LR_TARGET_H,
    LR_TOTAL_H,
    PEAKS_A,
    PHYSICAL_PEAKS,
    SATURATION_MARGIN,
    candidate,
    external_lr_h,
    paired_flux,
    peak_flux_t,
    physical_peak_report,
    resonant_khz,
    saturation_current_a,
    tank_total_h,
    turns_required,
    winding_loss,
)
from magnetics_design import CORE
from make_physical_decks import VARIANTS

AE = float(CORE["Ae_m2"])
BSAT = float(CORE["Bsat_T"])
DECK = Path(__file__).resolve().parent.parent / "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"


def test_flux_is_linear_in_current_and_hits_bsat_at_isat():
    isat = saturation_current_a(LR_TARGET_H, 2, AE, BSAT)
    assert abs(peak_flux_t(LR_TARGET_H, isat, 2, AE) - BSAT) < 1e-12
    half = peak_flux_t(LR_TARGET_H, isat / 2.0, 2, AE)
    assert abs(half - BSAT / 2.0) < 1e-12


def test_turns_required_follows_the_margin_rule():
    assert turns_required(LR_TARGET_H, PEAKS_A["fault_slow_oc_51us"], AE, BSAT) == 3
    assert turns_required(LR_TARGET_H, PEAKS_A["fault_fast_oc_13us"], AE, BSAT) == 2
    assert turns_required(LR_TARGET_H, PEAKS_A["startup"], AE, BSAT) == 1


def test_gap_grows_with_turns_at_fixed_inductance():
    two, three = candidate(LR_TARGET_H, 2), candidate(LR_TARGET_H, 3)
    assert two["gap_mm"] < three["gap_mm"]
    assert 0.5 < two["gap_mm"] < 0.8


def test_two_turns_pass_only_with_the_fast_oc():
    two = candidate(LR_TARGET_H, 2)
    assert two["passes_fast_oc"] is True
    assert two["passes_slow_oc"] is False
    assert abs(two["worst_flux_frac_bsat"] - two["flux_t"]["fault_slow_oc_51us"] / BSAT) < 1e-12
    assert two["flux_t"]["fault_fast_oc_13us"] <= SATURATION_MARGIN * BSAT


def test_three_turns_pass_both_and_one_turn_never_does():
    three = candidate(LR_TARGET_H, 3)
    assert three["passes_slow_oc"] is True
    assert candidate(LR_TARGET_H, 1)["passes_fast_oc"] is False


def deck_lr_external_h() -> float:
    text = DECK.read_text(encoding="utf-8")
    match = re.search(r"LR_TOTAL=([0-9.]+)u", text)
    assert match, "LR_TOTAL is gone from the deck"
    return float(match.group(1)) * 1e-6


def test_the_decks_external_lr_plus_model_leakage_is_the_design_total():
    """Issue #4 reads the deck's 0.92 uH as a mismatch with the 1.0 uH target.
    The deck's Lr is the *external* part and the model adds 80 nH of leakage
    (4 x Lp*(1-k^2) at k=.999, Lp=10 uH), so 0.92 + 0.08 = 1.00 uH total."""
    external = deck_lr_external_h()
    assert abs(external - external_lr_h(LK_MODEL_H)) < 5e-9
    assert abs(tank_total_h(external) - LR_TOTAL_H) < 5e-9


def test_model_leakage_follows_from_the_deck_coupling_factor():
    text = DECK.read_text(encoding="utf-8")
    lp = float(re.search(r"LP=([0-9.]+)u", text).group(1)) * 1e-6
    k = float(re.search(r"K1 Lp1.*?([0-9.]+)\s*$", text, re.M).group(1))
    four_in_series = 4 * lp * (1 - k * k)
    assert abs(four_in_series - LK_MODEL_H) < 2e-9, (
        f"deck leakage is {four_in_series * 1e9:.1f} nH, LK_MODEL_H says {LK_MODEL_H * 1e9:.1f} nH")


def test_the_tank_resonance_stays_just_above_the_clock():
    """The tank is tuned to 1.00 uH total = 202.1 kHz, above the 200.6 kHz clock.
    An untrimmed 1.0 uH external part would make the total 1.08 uH = 194.6 kHz,
    i.e. below the clock -- the reason the part has to be trimmed."""
    tuned = resonant_khz(LR_TOTAL_H)
    untrimmed = resonant_khz(tank_total_h(LR_TARGET_H))
    assert tuned > 200.622 and tuned - 200.622 < 3.0
    assert untrimmed < 200.622


def test_winding_loss_scales_with_current_squared():
    base = winding_loss(2, 200.622e3, 9.45014)
    doubled = winding_loss(2, 200.622e3, 2 * 9.45014)
    assert abs(doubled["loss_w"] - 4.0 * base["loss_w"]) < 1e-9
    assert base["loss_w"] < 0.447   # the deck's lumped 5 mohm Rser is conservative


# --- the measured physical peaks decide the turn count ---------------------

def test_a_measured_peak_is_evaluated_at_the_inductance_it_ran_on():
    """`candidate()` holds I fixed while L sweeps, which is conservative.  A
    measured peak already contains its own L, so pairing it with another one is
    simply wrong -- B scales with that L."""
    case = {"current_a": 80.0, "external_lr_h": 1.0e-6}
    other = {"current_a": 80.0, "external_lr_h": 0.875e-6}
    assert paired_flux(case, 3) == pytest.approx(paired_flux(other, 3) * 1.0 / 0.875, rel=1e-12)
    assert paired_flux(case, 3) == pytest.approx(peak_flux_t(1.0e-6, 80.0, 3, AE), rel=1e-12)


def test_every_physical_peak_names_a_deck_that_ran_at_its_inductance():
    """Provenance lock: the number and the deck's LR_TOTAL must agree, or the
    flux is computed at an inductance the simulation never had."""
    generated = {dst for _src, dst, *_rest in VARIANTS.values()}
    root = DECK.parent.parent.parent
    for name, case in PHYSICAL_PEAKS.items():
        assert case["deck"] in generated, f"{name} is not a generated variant deck"
        deck = root / case["deck"]
        assert deck.exists(), deck
        text = deck.read_text(encoding="utf-8")
        lr = float(re.search(r"LR_TOTAL=([0-9.]+)u", text).group(1)) * 1e-6
        assert lr == pytest.approx(case["external_lr_h"], abs=5e-9), name


def test_two_turns_is_past_bsat_at_the_measured_fault_peak():
    """The 84 A ride-through peak is what kills 2 turns: at 2 turns B is above
    Bsat itself (0.323 T vs 0.310 T), so no leakage trim rescues it the way the
    73.7 A frozen-deck number suggested."""
    case = physical_peak_report()["cases"]["fault_phys_ride_through"]
    assert case["flux_t_at_2"] > BSAT
    assert case["exceeds_bsat_at_2"] is True
    assert case["flux_t_at_3"] <= SATURATION_MARGIN * BSAT


def test_the_physical_report_picks_the_worst_min_turns():
    data = physical_peak_report()
    assert data["min_turns_all"] == max(c["min_turns"] for c in data["cases"].values())
    for case in data["cases"].values():
        assert case["min_turns"] == turns_required(
            case["external_lr_h"], case["current_a"], AE, BSAT)


def test_the_trim_end_is_the_worst_case_and_a_measured_peak_cannot_be_scaled():
    """0.875 uH external (0.125 uH leakage) is the low end of the trim window and
    the worst current.  Scaling the 1.0 uH peak by 1/L predicts 96.0 A; the deck
    gives 104.17 A, so the volt-second rule under-predicts by 8.5 % and must not
    be used to move a measured peak to another inductance."""
    cases = physical_peak_report()["cases"]
    worst = max(cases.values(), key=lambda c: c["flux_t_at_3"])
    assert worst["external_lr_h"] == pytest.approx(0.875e-6)
    assert worst["flux_t_at_3"] == pytest.approx(0.234, abs=5e-4)
    assert worst["flux_t_at_3"] <= SATURATION_MARGIN * BSAT
    scaled = cases["fault_phys_ride_through"]["current_a"] * 1.0 / 0.875
    assert worst["current_a"] > scaled * 1.05


def test_three_turns_holds_at_the_worst_measured_peak():
    three = candidate(LR_TARGET_H, 3)
    worst = max(physical_peak_report()["cases"].values(),
                key=lambda c: c["flux_t_at_3"])
    assert worst["flux_t_at_3"] <= SATURATION_MARGIN * BSAT
    # ...and it is *worse* than the frozen-deck table says: 3 turns is fine, but
    # the 73.7 A rule under-predicted the flux by 14 %.
    assert worst["flux_t_at_3"] > three["worst_flux_t"]


# ------------------------------------------------------- catalogue core design
def _catalogue(core_id):
    from lr_design import catalogue_core_design
    return next(c for c in catalogue_core_design()["cores"] if c["id"] == core_id)


def test_the_elp32_catalogue_row_reproduces_the_designed_gap():
    """The catalogue table and ``candidate()`` are two paths through the same
    AL; if they ever disagree, one of them is quoting a number nobody sized."""
    row = _catalogue("ELP32_I32")
    three = next(t for t in row["turns"] if t["turns"] == 3)
    # the report rounds the gap to 4 decimals, so the tolerance is half a unit
    # in the last place, not a relative epsilon
    assert three["gap_mm"] == pytest.approx(candidate(LR_TARGET_H, 3)["gap_mm"], abs=5e-5)
    assert three["gap_inside_published_validity"] is True


def test_the_elp38_gap_is_recomputed_from_its_own_al_not_carried_over():
    """8400 nH of ungapped AL is 33 % more than ELP32's 6300 nH, so the same
    1.0 uH at 3 turns needs 2.1651 mm of grinding -- beyond TDK's published
    0.10-2.00 mm range for the gap/AL relationship.  At 2 turns it is 0.9461 mm
    and the measured peaks stay at 75.8 % of Bsat (0.2349 T / 0.310 T)."""
    row = _catalogue("ELP38_I38")
    three = next(t for t in row["turns"] if t["turns"] == 3)
    two = next(t for t in row["turns"] if t["turns"] == 2)
    assert three["gap_mm"] == pytest.approx(2.1651, abs=1e-4)
    assert three["gap_inside_published_validity"] is False
    assert two["gap_mm"] == pytest.approx(0.9461, abs=1e-4)
    assert two["gap_inside_published_validity"] is True
    assert two["passes_margin_at_paired_peaks"] is True
    assert two["worst_paired_flux_t"] == pytest.approx(0.2349, abs=5e-5)


def test_the_catalogue_flux_pairs_each_peak_with_its_own_inductance():
    row = _catalogue("ELP38_I38")
    three = next(t for t in row["turns"] if t["turns"] == 3)
    case = PHYSICAL_PEAKS["fault_lrmin_ride_through"]
    expected = peak_flux_t(case["external_lr_h"], case["current_a"], 3, 194e-6)
    # 6-decimal rounding in the report, hence half a unit in the last place
    assert three["paired_flux_t"]["fault_lrmin_ride_through"] == pytest.approx(expected, abs=5e-7)


def test_every_catalogue_row_with_magnetics_names_its_datasheet():
    elp32, elp38 = _catalogue("ELP32_I32"), _catalogue("ELP38_I38")
    for row in (elp32, elp38):
        assert row["datasheet"].startswith("references/datasheets/")
        assert row["datasheet_confidence"].startswith("TDK PRIMARY DATASHEET")
        assert row["gapping_constants_published_for"] == ["N87"]
    assert elp32["window_height_mm"] == pytest.approx(3.2)
    assert elp38["window_height_mm"] == pytest.approx(4.45)
    assert elp38["window_width_per_side_mm"] == pytest.approx(6.35)
