"""Unit checks for the streamed cold/fault analyser.

The large raws are not committed (and take minutes to scan), so these tests use
synthetic arrays for the event logic and temporary decks for the cold-start
guard.  The integration evidence lives in the JSON records, not here.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import analyze_v3_transient as avt


def test_fault_engagement_is_the_pwl_halfway_point():
    assert avt.engage_time(5.5e-3, 5.6e-3) == pytest.approx(5.55e-3)


def test_the_fault_load_is_the_parallel_combination():
    """The fault branch is a 1 mOhm switch *plus* a 1 mOhm resistor, in parallel.

    That 2 mOhm branch against the 20 mOhm parent gives the 1.818 mOhm the
    inherited comment quotes.  This candidate runs 15.4 mOhm, so the real
    post-fault load is 1.770 mOhm (8.7x), not 11x.  Dividing by the nominal RL
    would overstate the load power by that same severity.
    """
    branch = 2e-3
    assert avt.parallel_load_ohm(15.4e-3, branch) == pytest.approx(1.77011e-3, rel=1e-4)
    assert avt.parallel_load_ohm(20e-3, branch) == pytest.approx(1.81818e-3, rel=1e-4)
    assert avt.parallel_load_ohm(15.4e-3, branch) < 15.4e-3


def test_the_fault_branch_is_read_from_the_deck():
    """Ron (1 mOhm) and Rflt (1 mOhm) are in series; hard-coding either lies."""
    deck = Path(__file__).resolve().parent.parent / "sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.cir"
    assert avt.deck_fault_branch_ohm(deck) == pytest.approx(2e-3)
    assert avt.parallel_load_ohm(0.0154, avt.deck_fault_branch_ohm(deck)) == pytest.approx(
        1.77011e-3, rel=1e-4)


def test_cold_start_guard_sees_directives_but_not_comments(tmp_path):
    cold = tmp_path / "cold.cir"
    cold.write_text("* .ic V(out)=2\n.tran 0 8m 0 10n uic\n", encoding="utf-8")
    assert avt.deck_has_ic(cold) is False
    warm = tmp_path / "warm.cir"
    warm.write_text(".tran 0 8m 0 10n uic\n.ic V(out)=1.89\n", encoding="utf-8")
    assert avt.deck_has_ic(warm) is True


def test_deck_stop_parses_spice_time_literals(tmp_path):
    """The target decks say ``.tran 0 8m 0 10n uic``; ``8m`` is not a float.

    LTspice treats ``m`` as milli (``MEG`` is 1e6), so a naive ``float()`` on
    the token either crashes or, if someone "fixes" it as SI, multiplies the
    stop time by a billion.
    """
    deck = tmp_path / "stop.cir"
    for token, expected in (("8m", 8e-3), ("1000u", 1e-3), ("0.008", 8e-3)):
        deck.write_text(f".tran 0 {token} 0 10n uic\n", encoding="utf-8")
        assert avt.deck_stop_s(deck) == pytest.approx(expected)
    deck.write_text(".tran 0 8M 0 10n uic\n", encoding="utf-8")
    assert avt.deck_stop_s(deck) == pytest.approx(8e-3)  # SPICE: M is milli


def test_first_cross_ignores_time_before_the_fault():
    t = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    y = np.array([0.0, 2.0, 0.0, 1.5, 0.0])
    assert avt.first_cross(t, y, 1.0, after=2.0) == 3.0


def test_low_runs_reports_open_ended_shutdown():
    t = np.arange(0.0, 11.0, 1.0)
    gate = np.array([5, 5, 0, 0, 0, 5, 5, 5, 0, 0, 0], dtype=float)
    runs = avt.low_runs(t, gate, level=1.0, after=0.0)
    assert (2.0, 4.0, False) in runs
    assert runs[-1] == (8.0, 10.0, True)


def test_peak_after_is_bounded_by_the_trip_instant():
    t = np.arange(0.0, 6.0, 1.0)
    y = np.array([0.0, 10.0, -30.0, 20.0, 5.0, 0.0])
    value, when = avt.peak_after(t, y, after=1.0, before=3.0)
    assert value == 30.0
    assert when == 2.0
