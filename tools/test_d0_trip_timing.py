"""Tests for tools/d0_trip_timing.py, the P0-3 answer.

Issue #36 forbids announcing that ``FAST_TRIP`` is both faster *and* more
sensitive than ``HARD_TRIP``.  The record this tool writes has to keep the two
claims separable, so the tests pin:

* the ordering (the fast channel fires earlier, at a *higher* current), which
  is what makes "faster" true and "more sensitive" false;
* the unit conversion.  The two thresholds are not on the same node: the hard
  one sits behind the ``Rf``/``Rd1``/``Rd2`` divider, the fast one on the
  burden.  Converting both with one slope inflates the fast channel by
  1/gain = 1.46x, and the tests below cross-check the gain against two node
  voltages measured independently rather than against the formula that wrote it;
* the filter poles, because the deck's ``OC`` node is two cascaded sections
  (47 us and 75.4 us), not the single "47 us" it is often called.

Run:
    python -m pytest tools/test_d0_trip_timing.py -q
"""

from __future__ import annotations

import json

import pytest

import ct_design as ct
import d0_trip_timing as timing

JSON = timing.OUT
HARD_RAW = timing.ROOT / (timing.HARD_DECK[:-4] + ".raw")
FAST_RAW = timing.ROOT / (timing.FAST_DECK[:-4] + ".raw")


@pytest.fixture(scope="module")
def data() -> dict:
    assert JSON.is_file(), f"{JSON} is missing -- run python tools/d0_trip_timing.py"
    return json.loads(JSON.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ ordering
def test_the_fast_channel_fires_first(data):
    r = data["results"]
    assert r["fast_delay_us"] < r["hard_delay_us"]
    assert r["fast_is_earlier_us"] == pytest.approx(
        r["hard_delay_us"] - r["fast_delay_us"])


def test_the_fast_channel_needs_more_current_so_it_is_not_more_sensitive(data):
    """Both halves of the issue's sentence, in one place.

    "Faster" and "more sensitive" are independent: this record says the fast
    channel wins the race by ~30 us and loses the sensitivity comparison by
    ~5 A.  A future edit that makes it more sensitive must change this test on
    purpose, not by accident.
    """
    r = data["results"]
    assert r["fast_threshold_current_a"] > r["hard_threshold_current_a"]
    assert r["fast_threshold_is_higher_by_a"] == pytest.approx(
        r["fast_threshold_current_a"] - r["hard_threshold_current_a"])


def test_the_pre_fault_operating_point_is_well_clear_of_both_thresholds(data):
    r = data["results"]
    assert r["hard_pre_fault_fraction_of_threshold"] < 1.0
    assert r["fast_pre_fault_fraction_of_threshold"] < 1.0
    assert r["hard_threshold_margin_x"] == pytest.approx(
        1 / r["hard_pre_fault_fraction_of_threshold"])
    assert r["fast_threshold_margin_x"] == pytest.approx(
        1 / r["fast_pre_fault_fraction_of_threshold"])


# -------------------------------------------------------------- unit anchors
def test_the_two_thresholds_are_converted_with_the_divider_gain_between_them(data):
    """The hard threshold is on the OC pin, the fast one on the burden.

    Written as "the burden moves this many volts per amp, and each node reads
    its own threshold against that", so a conversion that forgets the gain
    fails here instead of silently reading 46 % high.
    """
    t, r = data["threshold"], data["results"]
    oc_v_per_a = t["hard_v"] / r["hard_threshold_current_a"]
    burden_v_per_a = oc_v_per_a / ct.divider_gain()
    assert t["burden_node_v_per_a_peak"] == pytest.approx(burden_v_per_a, rel=1e-9)
    assert r["fast_threshold_current_a"] == pytest.approx(
        t["fast_v"] / burden_v_per_a, rel=1e-9)


def test_the_measured_nodes_confirm_the_divider_gain(data):
    """Independent cross-check: two raw runs, two nodes, one ratio.

    ``hard_pre_fault_node_v`` is measured on the unprotected run at the OC pin;
    ``fast_pre_fault_node_v`` is measured on the prot-B run at the burden.  If
    ``Rf`` were not in the divider (gain 24/34 instead of 24/35) or a node were
    mislabelled, this ratio would move.  The 5 us window mean of the spiky
    burden biases the ratio by ~0.2 %, hence the 1 % tolerance.
    """
    r = data["results"]
    measured = r["hard_pre_fault_node_v"]["mean_v"] / r["fast_pre_fault_node_v"]["mean_v"]
    assert measured == pytest.approx(ct.divider_gain(), rel=0.01)


def test_the_two_runs_share_their_trajectory_up_to_the_fast_trip(data):
    """Otherwise the two crossings are not the same fault and cannot be ranked."""
    assert data["checks"]["pre_trip_trajectories_agree_within_1e-3_v"]
    assert data["results"]["pre_trip_node_delta_v"] < 1e-3


# ------------------------------------------------------------------- poles
def test_the_oc_node_has_two_poles_and_the_fast_node_has_one(data):
    """The second OC pole is the slow one (75.4 us > 47 us).

    Calling the hard channel a "47 us" filter understates it by 1.6x, and that
    number is what the sensitivity comparison leans on.
    """
    poles = data["threshold"]["filter_poles_us"]
    assert poles["oc_stage_1"] == pytest.approx(47.0)
    assert poles["oc_stage_2"] == pytest.approx(75.42857142857143)
    assert poles["oc_stage_2"] > poles["oc_stage_1"]
    assert poles["fast"] == pytest.approx(10.0)


def test_the_poles_follow_the_part_values_and_not_a_remembered_number():
    """Change a capacitor in the deck and the record must move with it."""
    assert timing.RF_OHM * timing.CF_F == pytest.approx(47e-6)
    thevenin = timing.RD2_OHM * (timing.RD1_OHM + timing.RF_OHM) / (
        timing.RD1_OHM + timing.RF_OHM + timing.RD2_OHM)
    assert thevenin == pytest.approx(7542.857142857143, rel=1e-12)


# --------------------------------------------------------------- fail closed
def test_the_record_is_measurement_not_approval(data):
    assert data["kind"] == "D0_TRIP_TIMING"
    for flag in ("hardware_built", "fabrication_approved", "ten_physical_gate_shutdown_verified"):
        assert flag not in json.dumps(data), flag


def test_the_fault_instant_comes_from_the_deck_and_the_two_runs_agree(data):
    assert data["fault"]["saved_us"] > 0
    assert "Vfltctl_hot" in data["fault"]["source"]
    assert data["checks"]["fault_injected_at_the_same_instant"]


def test_two_runs_that_inject_at_different_times_are_refused(monkeypatch):
    calls = iter([
        {"absolute_us": 2175.0, "saved_us": 175.0, "tstart_us": 2000.0},
        {"absolute_us": 2175.0, "saved_us": 175.5, "tstart_us": 2000.0},
    ])
    monkeypatch.setattr(timing, "fault_instant", lambda _deck: next(calls))
    with pytest.raises(SystemExit, match="same instant"):
        timing.build(HARD_RAW, FAST_RAW)


def test_a_missing_raw_is_an_error_not_an_empty_record(tmp_path):
    with pytest.raises(SystemExit, match="both runs"):
        timing.main(["--hard-raw", str(tmp_path / "absent.raw"),
                     "--fast-raw", str(tmp_path / "absent.raw"),
                     "--json", str(tmp_path / "x.json")])
    assert not (tmp_path / "x.json").exists()


# ------------------------------------------------------------- regeneration
@pytest.mark.skipif(not (HARD_RAW.is_file() and FAST_RAW.is_file()),
                    reason="the two 1 GB raws are gitignored")
def test_the_committed_numbers_regenerate_from_the_raws(data):
    regenerated = timing.build(HARD_RAW, FAST_RAW)
    assert regenerated["results"] == data["results"]
    assert regenerated["threshold"] == data["threshold"]
    assert regenerated["checks"] == data["checks"]
