"""Tests for tools/make_physical_decks.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from make_physical_decks import VARIANTS, variant_text

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = "\n".join([
    ".param VIN=48 RL=18.9m LP=10u LR_TOTAL=.92u CR_TOTAL=620n",
    "Lr nct p1 {LR_TOTAL} Rser=5m",
    "Cout out sgnd 4m Rser=0.2m",
    ".tran 0 1000u 880u 5n uic",
])


def test_only_the_two_physical_elements_change():
    out = variant_text(SAMPLE, "1u", "7.05m")
    assert "LR_TOTAL=1u" in out and "LR_TOTAL=.92u" not in out
    assert "Cout out sgnd 7.05m Rser=0.2m" in out and "Cout out sgnd 4m" not in out
    assert out.count("\n") == SAMPLE.count("\n")
    assert ".tran 0 1000u 880u 5n uic" in out


def test_the_lr_value_goes_to_arbitrary_targets():
    assert "LR_TOTAL=.875u" in variant_text(SAMPLE, ".875u", "7.05m")


def test_a_missing_pattern_is_an_error_not_a_silent_no_op():
    with pytest.raises(ValueError, match="LR_TOTAL"):
        variant_text(SAMPLE.replace("LR_TOTAL=.92u ", ""), "1u", "7.05m")


def test_a_duplicated_pattern_is_rejected():
    with pytest.raises(ValueError, match="exactly one"):
        variant_text(SAMPLE + "\n" + SAMPLE, "1u", "7.05m")


def test_an_lr_element_that_ignores_the_param_is_rejected():
    """If `Lr` were hard-coded, swapping LR_TOTAL would silently do nothing."""
    broken = SAMPLE.replace("Lr nct p1 {LR_TOTAL}", "Lr nct p1 1u")
    with pytest.raises(ValueError, match="does not use LR_TOTAL"):
        variant_text(broken, "1u", "7.05m")


def test_the_variants_cover_the_issue_4_cases():
    assert VARIANTS["phys"][2:] == ("1u", "7.05m", None, None)
    assert VARIANTS["cout7m"][2:] == (".92u", "7.05m", None, None)
    assert VARIANTS["lrmin"][2:] == (".875u", "7.05m", None, None)
    assert VARIANTS["cold_oc_lrmin"][2] == ".875u"


def test_the_timestep_rewrite_keeps_stop_start_and_tstart():
    """Issue #6 needs the same instrumented deck at 2 ns.  Only the max
    timestep may change: stop/start/Tstart decide which window the raw holds,
    and the 5 ns and 2 ns runs must share one."""
    out = variant_text(SAMPLE, step="2n")
    assert ".tran 0 1000u 880u 2n uic" in out
    assert "LR_TOTAL=.92u" in out and "Cout out sgnd 4m" in out


def test_a_deck_without_a_parsable_tran_line_is_rejected():
    with pytest.raises(ValueError, match=r"\.tran"):
        variant_text(SAMPLE.replace(".tran 0 1000u 880u 5n uic", ".tran 0 1m uic"), step="2n")


def test_the_ledger_2n_variant_only_changes_the_timestep():
    src, dst, lr, cout, step, stop = VARIANTS["ledger2n"]
    assert src.endswith("_ledger.cir") and dst.endswith("_ledger2n.cir")
    assert (lr, cout, step, stop) == (None, None, "2n", None)


def test_the_50v_120a_2ns_variant_only_changes_the_timestep():
    """ELE-09 needs a same-window 2 ns companion: if the 0.499 W loss residual
    is the SR body-diode step artifact, this is the run that shows it.  VIN, RL
    and Tstart must stay put or the comparison would mix in a circuit change."""
    src, dst, lr, cout, step, stop = VARIANTS["vin50_i120_cin_2n"]
    assert src.endswith("vin50_i120_cin.cir")
    assert dst.endswith("vin50_i120_cin_2n.cir")
    assert (lr, cout, step, stop) == (None, None, "2n", None)
    text = variant_text((ROOT / src).read_text(encoding="utf-8"), step=step)
    assert ".tran 0 1000u 880u 2n uic" in text
    assert "VIN=50 RL=16.3m" in text


def test_the_50v_120a_aligned_variant_only_stops_later():
    """ELE-09 needs the phase-aligned window at 50 V/120 A too.  Its 22-period
    step pair showed the port term moving 0.41 W, so a longer window is the
    only way to tell a real gap from an endpoint artefact.  VIN, RL, Tstart and
    the timestep must all stay identical to the 22-period deck."""
    src, dst, lr, cout, step, stop = VARIANTS["vin50_i120_cin_aligned"]
    assert src.endswith("vin50_i120_cin.cir")
    assert dst.endswith("vin50_i120_cin_aligned.cir")
    assert (lr, cout, step, stop) == (None, None, None, "1550u")
    text = variant_text((ROOT / src).read_text(encoding="utf-8"), stop=stop)
    assert ".tran 0 1550u 880u 5n uic" in text
    assert "VIN=50 RL=16.3m" in text


def test_the_aligned_variant_only_moves_the_stop_time():
    """Issue #6 needs the same instrumented deck saved over one phase-
    aligned window.  Start and Tstart must not move, or the run would no
    longer sample the same settled 100 A state as the 16-period raw."""
    src, dst, lr, cout, step, stop = VARIANTS["ledger_aligned"]
    assert (lr, cout, step) == (None, None, None), "only the stop may change"
    out = variant_text(SAMPLE, stop=stop)
    assert out.strip().endswith(".tran 0 1550u 880u 5n uic")
    assert "LR_TOTAL=.92u" in out and "Cout out sgnd 4m" in out
