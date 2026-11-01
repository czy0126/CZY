"""Tests for tools/lr_design.py.

The sizing rule is `B = L*I/(N*Ae) <= 0.9*Bsat` at the worst fault current, so
the tests pin that identity and the two OC-delay cases that it decides.
"""

from __future__ import annotations

from lr_design import (
    LR_TARGET_H,
    PEAKS_A,
    SATURATION_MARGIN,
    candidate,
    peak_flux_t,
    saturation_current_a,
    turns_required,
    winding_loss,
)
from magnetics_design import CORE

AE = float(CORE["Ae_m2"])
BSAT = float(CORE["Bsat_T"])


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


def test_winding_loss_scales_with_current_squared():
    base = winding_loss(2, 200.622e3, 9.45014)
    doubled = winding_loss(2, 200.622e3, 2 * 9.45014)
    assert abs(doubled["loss_w"] - 4.0 * base["loss_w"]) < 1e-9
    assert base["loss_w"] < 0.447   # the deck's lumped 5 mohm Rser is conservative
