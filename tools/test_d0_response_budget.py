"""P0-3's second half: a rise/fall budget that adds only what is not measured.

The measured front end in ``design/v3/stage_f/d0_trip_timing.json`` runs the
real burden and both RC poles on the deck, so it *is* the detection term.
Adding ``filter_poles_us`` on top would count the same 47 us and 75 us twice
and turn a 10 us fast channel into a 130 us one -- the exact double-count
these tests exist to prevent.

The remaining stages are pinned three ways: the permit rail, whose fall time
is set by eight resistors that exist for an unrelated reason, a gate that
stays on for a hundred microseconds behind a dead driver, and every
unpublished number left as ``None`` with the reason instead of a plausible
guess.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import d0_response_budget as budget
import make_d0_protection_board as board


# ------------------------------------- the measured term is the whole front end
def test_the_detection_term_is_the_measurement_not_the_filters_again():
    """The filters are already inside the measured delay; adding the pole list
    would double-count 47 us and 75 us."""
    stages = budget.build()["stages"]
    measured = board.trip_timing_record()
    assert measured is not None, "d0_trip_timing.json has to exist to run this"
    assert stages["detection"]["hard_us"] == pytest.approx(measured["hard_delay_us"])
    assert stages["detection"]["fast_us"] == pytest.approx(measured["fast_delay_us"])
    assert stages["detection"]["source"] == "measured"
    assert stages["detection"]["contains_the_rc_poles"] is True
    assert "oc_stage_1" not in stages
    assert "filter_poles_us" not in str(stages["detection"])


# ------------------------------- the rail falls on somebody else's resistors
def test_the_eight_enable_pulldowns_are_what_makes_the_permit_rail_fall():
    """Those 4.7k resistors exist to hold ENA/ENB low against the UCC27524A's
    internal 200 k pull-up.  They are also, by accident, 94 % of the permit
    rail's discharge conductance -- deleting them as redundant would make the
    disable path sixteen times slower.  The drawn R44/C28 filter is not the
    limiting term: it is shorter than the TDIS it feeds."""
    stages = budget.build()["stages"]
    release = stages["permit_release"]
    tdis = stages["driver_disable"]["ucc27282_tdis_us"]
    assert tdis == pytest.approx(1.5)
    assert release["sr_pulldown_count"] == 8
    assert release["fastest_us"] < release["guaranteed_us"]
    assert release["filter_to_tdis_ratio"] < 1.0  # the filter is not the delay
    assert release["release_without_sr_pulldowns_us"] > 10.0 * release["fastest_us"]
    assert release["sr_pulldowns_carry_most_of_the_discharge"] is True


def test_the_disable_threshold_is_bracketed_by_its_own_min_and_max():
    """1.21 V is the latest a pin can still read enabled, 0.70 V the earliest it
    must read disabled -- so the pair brackets the delay instead of picking one."""
    release = budget.build()["stages"]["permit_release"]
    assert release["vd_is_max_v"] == pytest.approx(1.21)
    assert release["vd_is_min_v"] == pytest.approx(0.70)
    assert release["fastest_uses_vd_is_max"] is True
    assert release["guaranteed_uses_vd_is_min"] is True
    assert release["pin_capacitance_unknown_so_this_is_a_floor"] is True


def test_the_permit_rail_is_the_five_volt_rail_and_not_the_twelve_volt_one():
    """Q2's source is V5, so the rail starts at 5 V.  Assuming 12 V would make
    every EN delay 25 % long and would also mis-state the enable margin."""
    stages = budget.build()["stages"]
    assert stages["permit_release"]["enable_rail_v"] == pytest.approx(5.0)
    assert stages["permit_release"]["rail_source_net"] == "V5"


# --------------------------------------- a dead driver is not a fast turn-off
def test_a_gate_with_a_dead_driver_stays_on_for_a_hundred_microseconds():
    """The 10k pull-down is the only path when the driver is unpowered.  It is
    three orders of magnitude slower than the driver sinking the same charge."""
    sr = budget.build()["stages"]["gate_discharge"]["sr"]
    assert sr["with_driver_ns"] < 100.0
    assert sr["pulldown_only_us"] > 100.0
    assert sr["pulldown_only_us"] * 1000.0 / sr["with_driver_ns"] > 1000.0
    assert sr["gate_load_nf"] == pytest.approx(6.7)
    assert sr["pulldown_ohm"] == pytest.approx(7.46e3, rel=0.02)


def test_the_gate_discharge_starts_at_the_driver_supply_not_the_gate_rating():
    sr = budget.build()["stages"]["gate_discharge"]["sr"]
    assert sr["gate_high_v"] == pytest.approx(12.0)
    assert sr["to_vgs_th_min_v"] == pytest.approx(1.3)
    assert sr["with_driver_ns_is_a_floor"] is True


# -------------------------------------------------- what the budget cannot know
def test_the_budget_names_what_it_cannot_know():
    stages = budget.build()["stages"]
    assert stages["comparator"]["us"] is None
    assert "LM393" in stages["comparator"]["reason"]
    assert stages["latch"]["us"] is None
    assert "CD4013" in stages["latch"]["reason"]
    assert stages["driver_disable"]["ucc27524a_us"] is None
    assert "UCC27524A" in stages["driver_disable"]["ucc27524a_reason"]
    assert stages["permit_release"]["sr_pin_capacitance_known"] is False


def test_the_budget_is_not_a_worst_case_and_says_so():
    result = budget.build()
    assert result["status"] == "RESPONSE_BUDGET_INCOMPLETE"
    assert result["is_worst_case"] is False
    assert len(result["not_worst_case_because"]) >= 3
    assert result["hardware_protection_approved"] is False
    assert result["power_stage_fabrication_approved"] is False


def test_the_two_channels_keep_their_separate_floors():
    """The fast channel is 30 us earlier at detection and then waits on the same
    permit node, so the gap narrows but does not close."""
    totals = budget.build()["totals"]
    assert totals["fast_channel_floor_us"] < totals["hard_channel_floor_us"]
    assert totals["hard_channel_floor_us"] == pytest.approx(
        budget.build()["stages"]["detection"]["hard_us"]
        + budget.build()["stages"]["permit_release"]["fastest_us"]
        + budget.build()["stages"]["driver_disable"]["ucc27282_tdis_us"]
        + budget.build()["stages"]["gate_discharge"]["sr"]["with_driver_ns"] / 1000.0)
    assert totals["detection_advantage_us"] > 25.0
    # Every stage after detection is shared, so the gap between the two totals
    # has to be exactly the gap between the two detections -- if a later stage
    # ever differed by channel, this equality is what would break.
    assert (totals["hard_channel_floor_us"] - totals["fast_channel_floor_us"]
            == pytest.approx(totals["detection_advantage_us"], abs=1e-6))


# ------------------------------------------------- recomputed, not remembered
def test_the_drawn_en_filter_is_not_what_sets_the_release(monkeypatch):
    """Ten times R44 buys 5 %: the rail is already loaded by 550 ohm, so the
    R44/C28 network is a detail, not the delay.  Anyone "sizing" it is tuning
    the wrong part, and this test is what makes that visible."""
    original = board.parts

    def slower_parts():
        return [replace(part, value="100k") if part.ref == "R44" else part
                for part in original()]

    before = budget.build()["stages"]["permit_release"]["fastest_us"]
    monkeypatch.setattr(board, "parts", slower_parts)
    after = budget.build()["stages"]["permit_release"]["fastest_us"]
    assert after < before * 1.10


def test_weakening_the_sr_pulldowns_would_cost_five_microseconds(monkeypatch):
    """They are 94 % of the conductance, so the same 10x on them is the change
    that matters -- which is why deleting them as "redundant" is not free."""
    original = board.parts

    def weaker_parts():
        return [replace(part, value="47k")
                if part.ref in {f"R{n}" for n in range(36, 44)} else part
                for part in original()]

    before = budget.build()["stages"]["permit_release"]["fastest_us"]
    monkeypatch.setattr(board, "parts", weaker_parts)
    after = budget.build()["stages"]["permit_release"]["fastest_us"]
    assert after > before * 5.0


RECORD = Path(__file__).resolve().parent.parent / "design/v3/stage_f/d0_response_budget.json"


def test_the_committed_record_is_what_the_tool_produces():
    """A reader cites the JSON, so the JSON has to be the tool's own output --
    same rule as d0_trip_timing.json."""
    assert RECORD.is_file(), "run: python tools/d0_response_budget.py --output ..."
    assert json.loads(RECORD.read_text(encoding="utf-8")) == budget.build()


def test_the_cli_fails_closed(tmp_path):
    report = tmp_path / "d0_response_budget.json"
    assert budget.main(["--require-complete", "--output", str(report)]) == 1
    assert report.is_file()
    assert "RESPONSE_BUDGET_INCOMPLETE" in report.read_text(encoding="utf-8")
