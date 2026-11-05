"""P0-3's second half: a rise/fall budget that adds only what is not measured.

The measured front end in ``design/v3/stage_f/d0_trip_timing.json`` runs the
real burden and both RC poles on the deck, so it *is* the detection term.
Adding ``filter_poles_us`` on top would count the same 47 us and 75 us twice
and turn a 10 us fast channel into a 130 us one -- the exact double-count
these tests exist to prevent.

The remaining stages are pinned four ways: the permit rail, whose fall time
is set by eight resistors that exist for an unrelated reason, a gate that
stays on for a hundred microseconds behind a dead driver, the comparator and
latch delays whose vendor tables are now vendored, and every number that is
still not a guarantee left labelled as what it actually is.
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
    assert release["sr_pulldowns_carry_most_of_the_discharge"] is True


def test_the_enable_pull_ups_hold_the_released_rail_above_ground():
    """The rail does not discharge to 0 V: eight UCC27524A ENA/ENB pins pull it
    toward their 12 V supply through ~200k each.  It settles at a ceiling, and
    the ceiling -- not the exponential alone -- decides whether the drivers can
    ever read disabled."""
    release = budget.build()["stages"]["permit_release"]
    assert release["sr_pullup_ohm"] == pytest.approx(25e3, rel=0.01)
    assert release["ceiling_v"] == pytest.approx(0.259, abs=0.01)
    assert release["ceiling_below_vd_is_max"] is True
    assert release["ceiling_below_ven_min"] is True
    assert release["sr_pullup_is_a_typical_not_a_guarantee"] is True


def test_without_the_pulldowns_the_drivers_stay_enabled_forever():
    """This is the whole argument for keeping eight resistors that look
    redundant: delete them and the remaining 200 k pull-ups win the divider, so
    the node parks at ~3.1 V -- above VDIS and above VEN.  The permit rail then
    never disables anything, at any time, not merely later."""
    release = budget.build()["stages"]["permit_release"]
    assert release["without_pulldowns_ceiling_v"] > release["vd_is_max_v"]
    assert release["without_pulldowns_never_disables"] is True
    assert release["without_pulldowns_ceiling_v"] == pytest.approx(3.12, abs=0.15)


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


def test_the_detector_path_is_the_branch_resistor_not_the_gate_resistor():
    """A dead driver leaves the gate two paths to ground: its 10k pull-down and
    the detector's 1k + BAT54 + 22k/6.2k = 29.2k.  That 1k sits between the gate
    and its diode; the 2.2 ohm gate resistor sits between the driver and the
    gate and is not in this path at all.  Substituting one for the other reads
    7.38k instead of 7.45k -- small, but it is the number the docs quote."""
    for channel in ("sr", "primary"):
        stage = budget.build()["stages"]["gate_discharge"][channel]
        assert stage["detector_branch_ohm"] == pytest.approx(29.2e3, rel=0.001)
        assert stage["detector_branch_ref"].startswith("R")
        assert stage["gate_resistor_ohm"] < 10.0  # the 2.2 ohm, not the 1k
        assert stage["pulldown_ohm"] == pytest.approx(7.45e3, rel=0.001)


# -------------------------------------------------- what the budget cannot know
def test_the_budget_names_what_it_cannot_know():
    """Both chip stages now carry a number, so the list of unknowns has to be
    about *why the numbers are not guarantees* -- a typ-only comparator, a latch
    max at one supply, switching parameters the vendor does not production-test
    -- rather than about a page missing from the repository."""
    result = budget.build()
    assert result["stages"]["permit_release"]["sr_pin_capacitance_known"] is False
    joined = " ".join(result["not_worst_case_because"])
    assert "LM393" in joined
    assert "CD4013" in joined
    assert "not tested in production" in joined


def test_the_comparator_stage_is_typ_only_and_says_so():
    """LM393 section 5.11 publishes a typical and no maximum column at all, so
    1.3 us is a nominal: a slower part lengthens every total, which is one
    reason the sum is a floor rather than a worst case.  The same table gives
    0.3 us for a TTL-level step -- response time is a function of overdrive --
    and the budget takes the slower of the two published typicals."""
    comparator = budget.build()["stages"]["comparator"]
    assert comparator["us"] == pytest.approx(1.3)
    assert comparator["typ_only"] is True
    assert comparator["published_max_us"] is None
    assert comparator["large_overdrive_typ_us"] == pytest.approx(0.3)
    assert "references/datasheets/lm393.txt" in comparator["source"]
    assert "5.11" in comparator["source"]


def test_the_two_priced_comparators_assert_on_the_rising_edge():
    """LM393 section 7.2.2.1: the output goes high impedance when IN+ exceeds
    IN-, and sinks when it does not.  Both trip comparators put the
    burden-derived node on IN+, so a trip *lifts* the output -- and section
    7.2.2.4 makes the rise the edge the pull-up sets.  The budget prices these
    two because the measured detection term ends at their inputs."""
    c = budget.build()["stages"]["comparator"]
    assert c["priced_channels"] == ["U3A", "U3B"]
    assert c["fault_output_edges"]["U3A"] == "rising"
    assert c["fault_output_edges"]["U3B"] == "rising"
    assert c["priced_channels_all_assert_by_a_rise"] is True
    assert c["the_cited_figure_covers_the_edge_the_priced_channels_use"] is True


def test_the_rail_supervisors_assert_on_the_falling_edge_the_pull_up_cannot_slow():
    """The other three channels put a healthy-rail divider on IN+, so a fault
    *lowers* the output.  Section 7.2.2.4 gives that edge as R_CE * CL: it is
    set by the output transistor, not by the resistor to 5 V, which is why the
    board's 10 k pull-ups cannot be charged against those three."""
    c = budget.build()["stages"]["comparator"]
    assert {k: v for k, v in c["fault_output_edges"].items()
            if k != "U5B"} == {"U3A": "rising", "U3B": "rising",
                               "U4A": "falling", "U4B": "falling",
                               "U5A": "falling"}
    assert c["pull_up_independent_channels"] == ["U4A", "U4B", "U5A"]


def test_the_board_pull_up_is_not_the_one_the_typical_was_measured_with():
    """Section 5.11 measured 1.3 us through 5.1 k and 15 pF.  Every LM393
    output here rides a 10 k, i.e. 1.96x, and the extra time constant that adds
    to the priced (rising) edge is dR * CL = 73.5 ns -- 5.7 % of the cited
    typical.  It is stated as a time constant, not as a delay: the interval to
    the 1.4 V crossing is a fraction of it, so this over-states rather than
    under-states, and it is exact only in the CL the datasheet assumed."""
    c = budget.build()["stages"]["comparator"]
    assert c["output_pull_up_ohm"] == pytest.approx(10e3)
    assert c["cited_test_pull_up_ohm"] == pytest.approx(5.1e3)
    assert c["pull_up_is_larger_than_the_cited_condition"] is True
    assert c["pull_up_added_time_constant_us"] == pytest.approx(0.0735, abs=1e-6)
    assert c["pull_up_added_time_constant_fraction_of_the_cited_typical"] == pytest.approx(
        0.0565, abs=1e-3)
    assert c["added_term_is_proportional_to_load_capacitance"] is True
    assert c["load_capacitance_measured"] is False


def test_a_changed_pull_up_moves_the_added_term(monkeypatch):
    """The 73.5 ns has to be arithmetic on the part table, not a sentence
    copied next to the number: doubling all six pull-ups has to double it."""
    original = board.parts()
    outputs = {"HARD_TRIP", "FAST_TRIP", "ANY_ON", "V5_OK", "V12P_OK", "V12S_OK"}

    def doubled():
        return [replace(part, value="20k")
                if part.lib == "Device:R" and part.value == "10k"
                and part.nets.get("1") == "V5"
                and part.nets.get("2") in outputs
                else part for part in original]

    monkeypatch.setattr(board, "parts", doubled)
    c = budget.build()["stages"]["comparator"]
    assert c["output_pull_up_ohm"] == pytest.approx(20e3)
    assert c["pull_up_added_time_constant_us"] == pytest.approx(
        (20e3 - 5.1e3) * 15e-12 * 1e6, abs=1e-6)


def test_a_rewired_comparator_input_is_not_silently_repriced(monkeypatch):
    """The fault direction is declared per channel and the net is checked, the
    same way the eight enable pull-downs are named by reference: swapping a
    comparator's inputs has to break the tool, not quietly keep the old
    edge."""
    original = board.parts()

    def swapped():
        out = []
        for part in original:
            if part.ref == "U3" and part.unit == 1:
                nets = dict(part.nets)
                nets["2"], nets["3"] = nets["3"], nets["2"]
                part = replace(part, nets=nets)
            out.append(part)
        return out

    monkeypatch.setattr(board, "parts", swapped)
    with pytest.raises(SystemExit):
        budget.build()


def test_the_latch_delay_is_the_set_to_output_falling_edge():
    """FF1 has SET = FLT and its ~Q is the permit term, so setting the flip-flop
    drives ~Q *down*: the applicable row is set-to-output tPHL, 200 typ /
    400 max ns at VDD = 5 V.  Quoting the clock-to-Q row (150/300 ns) would
    understate a path that never uses the clock -- D and CLK are tied off."""
    latch = budget.build()["stages"]["latch"]
    assert latch["us"] == pytest.approx(0.4)
    assert latch["typ_us"] == pytest.approx(0.2)
    assert latch["vdd_v"] == pytest.approx(5.0)
    assert latch["edge"].startswith("set to")
    assert "references/datasheets/cd4013b.txt" in latch["source"]
    assert "6.6" in latch["source"]


def test_the_sr_drivers_have_a_published_disable_delay_and_drive_low():
    """The UCC27524A datasheet is now vendored, so both halves of this question
    come from it rather than from a transcription.  Switching Characteristics
    gives the D package's EN-to-output 13 ns typ / 23 ns max, and Device Logic
    Table 6-2 (``L L Any Any -> L L``) says a low EN *drives* the output low --
    it does not tri-state.  That is what keeps the SR gate on its 2.2 ohm path
    instead of falling back to the 110 us dead-driver figure."""
    disable = budget.build()["stages"]["driver_disable"]
    assert disable["ucc27524a_us"] == pytest.approx(0.023)
    assert disable["ucc27524a_typ_us"] == pytest.approx(0.013)
    assert "references/datasheets/ucc27524a.txt" in disable["ucc27524a_source"]
    assert disable["ucc27524a_datasheet_vendored"] is True
    assert disable["ucc27524a_package"].startswith("D ")
    assert disable["ucc27524a_output_state_on_disable"] == "low"
    assert "Table 6-2" in disable["ucc27524a_output_state_reason"]
    assert disable["ucc27524a_ven_l_max_v"] == pytest.approx(1.35)
    assert disable["ucc27524a_ven_h_min_v"] == pytest.approx(1.90)
    # The datasheet says so itself -- the guard against quoting 23 ns as a
    # guaranteed max over part-to-part spread.
    assert disable["ucc27524a_switching_params_not_production_tested"] is True


def test_the_sr_drivers_drop_out_before_the_primary_driver_does():
    """Both driver families ride the same permit rail, so the crossing order is
    decided by their thresholds alone: the UCC27524A's latest-still-enabled
    point is VEN_L max 1.35 V, the UCC27282's is VDIS max 1.21 V.  Reading the
    SR release off the 1.21 V crossing would charge the eight SR drivers for
    0.07 us they do not owe."""
    release = budget.build()["stages"]["permit_release"]
    assert release["sr_driver_ven_l_max_v"] == pytest.approx(1.35)
    # A falling exponential crosses the *higher* threshold first, so the eight
    # SR drivers read disabled 74 ns before the primary pair does.
    assert release["sr_driver_release_us"] < release["fastest_us"]
    assert release["sr_driver_release_precedes_ucc27282"] is True
    # And 0.79 us is well inside the 1.5 us TDIS the primary then waits out,
    # which is the whole point: the SR branch is not the slow one.
    tdis = budget.build()["stages"]["driver_disable"]["ucc27282_tdis_us"]
    assert release["sr_driver_release_us"] < tdis


def test_the_primary_branch_not_the_sr_branch_sets_the_all_ten_low_time():
    """Both branches hang off the same permit rail, so 'all ten gates low' is
    the max, not the sum: the SR branch answers 23 ns after the rail falls while
    the primary waits out the UCC27282's 1.5 us TDIS."""
    totals = budget.build()["totals"]
    assert totals["primary_branch_floor_us"] > totals["sr_branch_floor_us"]
    assert totals["slowest_branch"] == "primary"
    assert totals["driver_branch_us"] == pytest.approx(
        totals["primary_branch_floor_us"])


def test_the_shared_stage_is_the_sum_of_the_stages_that_are_actually_in_series():
    """Detection stops at the comparator input, so the comparator and the latch
    sit in series with the permit rail and the driver -- the two driver branches
    are the only parallel pair.  Every one of those stages moves both channel
    floors by the same amount, which is why the 29.88 us detection gap survives
    the sum unchanged."""
    result = budget.build()
    stages, totals = result["stages"], result["totals"]
    assert totals["shared_after_detection_us"] == pytest.approx(
        stages["comparator"]["us"] + stages["latch"]["us"]
        + totals["driver_branch_us"])
    assert totals["hard_channel_floor_us"] == pytest.approx(44.18, abs=0.02)
    assert totals["fast_channel_floor_us"] == pytest.approx(14.30, abs=0.02)


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
        + totals["shared_after_detection_us"])
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


def test_weakening_the_sr_pulldowns_parks_the_rail_in_the_hysteresis_band(monkeypatch):
    """Ten times weaker pull-downs put the released rail at ~1.48 V: below VEN
    min (1.54 V) but above VDIS max (1.21 V).  That is inside the EN pin's own
    0.3 V hysteresis, so whether the driver ends up enabled depends on which
    state it was in -- the worst kind of margin.  The same 10x on R44 buys 5 %."""
    original = board.parts

    def weaker_parts():
        return [replace(part, value="47k")
                if part.ref in {f"R{n}" for n in range(36, 44)} else part
                for part in original()]

    before = budget.permit_rail_release({p.ref: p for p in original()})
    monkeypatch.setattr(board, "parts", weaker_parts)
    after = budget.permit_rail_release({p.ref: p for p in weaker_parts()})
    assert after["ceiling_v"] > before["ceiling_v"]
    assert after["ceiling_above_vd_is_max"] is True
    assert after["ceiling_below_ven_min"] is True
    assert not after["ceiling_below_vd_is_max"]
    # The rail no longer crosses, so it has no release time at all -- not a
    # longer one.  build() is what turns that into a refusal.
    assert after["fastest_us"] is None
    assert after["guaranteed_us"] is None
    with pytest.raises(SystemExit, match="never read"):
        budget.build()


# ------------------------------------ the external fast path's two new gates
def _tokens_near(lines: list[str], needle: str, span: int = 12) -> list[str]:
    start = next(i for i, line in enumerate(lines) if needle in line)
    tokens: list[str] = []
    for line in lines[start:start + span]:
        tokens.extend(line.replace(",", " ").split())
    return tokens


def test_the_external_fast_path_prices_the_two_new_gates():
    """The review asks for the real delay of the added inverter and OR.  Both
    datasheets publish a maximum, so this is the one stretch of the external
    path that is a number rather than a floor -- 110 ns plus 250 ns."""
    result = budget.build()
    logic = result["stages"]["external_fast_logic"]
    assert logic["us"] == pytest.approx(0.36)
    assert logic["typ_us"] == pytest.approx(0.18)
    by_ref = {stage["ref"]: stage for stage in logic["stages"]}
    assert by_ref["U11"]["max_ns"] == pytest.approx(budget.CD4069UB_TPD_MAX_NS)
    assert by_ref["U19"]["max_ns"] == pytest.approx(budget.CD4071B_TPD_MAX_NS)
    assert result["external_fast_path"]["logic_us"] == pytest.approx(logic["us"])
    assert result["external_fast_path"]["logic_typ_us"] == pytest.approx(logic["typ_us"])


def test_the_two_logic_stages_read_their_wiring_back_from_the_part_table():
    """Same rule as the comparator fault directions: the chain in the JSON has
    to be the chain on the board.  A unit re-numbered or a gate replaced breaks
    the tool rather than being re-priced on the old wiring."""
    logic = budget.build()["stages"]["external_fast_logic"]
    assert [stage["input_net"] for stage in logic["stages"]] == ["FAST_EXT_N", "FAST_EXT_H"]
    assert [stage["output_net"] for stage in logic["stages"]] == ["FAST_EXT_H", "FAST_COMBINED"]
    parts = {(p.ref, p.unit): p for p in board.parts()}
    inverter, gate = parts[("U11", 6)], parts[("U19", 1)]
    assert inverter.nets["12"] == gate.nets["2"]
    assert inverter.nets["13"] == "FAST_EXT_N"
    assert gate.nets["1"] == "FAST_TRIP"
    assert gate.nets["3"] == "FAST_COMBINED"


def test_the_two_gates_run_from_the_five_volt_rail_the_budget_assumes():
    """The 55/110 and 125/250 ns rows are the VDD = 5 V rows.  Reading the 10 V
    row (30/60 and 60/120 ns) would halve the price for stages that sit on V5."""
    logic = budget.build()["stages"]["external_fast_logic"]
    assert logic["supply"] == {"U11": "V5", "U19": "V5", "v": 5.0}
    # Keyed on the DIP-14 power pins (7 and 14) rather than on pin count: a
    # signal unit that happens to use two pins would otherwise pass for the
    # supply unit and the check would stop meaning anything.
    powered = [p for p in board.parts()
               if p.ref in ("U11", "U19") and set(p.nets) == {"7", "14"}]
    assert len(powered) == 2
    for part in powered:
        assert set(part.nets.values()) == {"PGND", "V5"}


def test_the_logic_delays_are_readable_in_the_vendored_datasheets():
    """A fabricated nanosecond is the failure this locks out: the number has to
    appear in the text that ships beside the PDF.  CD4071B's table pages are
    scanned images, so its text file carries a marked transcription block."""
    root = Path(__file__).resolve().parent.parent / "references/datasheets"
    inverter = (root / "cd4069ub.txt").read_text(encoding="utf-8").splitlines()
    tokens = _tokens_near(inverter, "Propagation delay time")
    assert "55" in tokens and "110" in tokens
    gate = (root / "cd4071b.txt").read_text(encoding="utf-8").splitlines()
    tokens = _tokens_near(gate, "Propagation Delay Time")
    assert "125" in tokens and "250" in tokens
    assert "APPENDED TRANSCRIPTION" in "\n".join(gate)
    assert (root / "cd4071b_p2.png").is_file()


def test_the_logic_maximum_is_a_25_degree_maximum_and_says_so():
    """Both tables print TA = 25 C in their header, so "max" bounds one
    temperature.  The budget must not let that read as a guarantee over the
    board's range."""
    result = budget.build()
    logic = result["stages"]["external_fast_logic"]
    assert logic["max_is_at_25c_only"] is True
    assert logic["max_over_temperature_us"] is None
    assert "TA = 25 C" in logic["cited_conditions"]
    assert "25 C maxima" in " ".join(result["not_worst_case_because"])


def test_the_cited_load_and_edge_bound_only_the_asserting_direction():
    """The 50 pF / 20 ns conditions are the datasheet's, not the layout's.  The
    load is heavier than the real one (one CD4071B input), which errs long; the
    edge is met by the Q1 fall but not by the R7 rise -- and a slow release
    holds the OR output at the fault level, so that direction is not a
    protection hole."""
    logic = budget.build()["stages"]["external_fast_logic"]
    assert logic["cited_load_f"] == pytest.approx(50e-12)
    assert logic["actual_load_upper_bound_f"] < logic["cited_load_f"]
    assert logic["asserting_edge_meets_the_cited_20ns"] is True
    assert "R7 10 k" in logic["releasing_edge_condition"]


def test_the_new_logic_is_priced_but_stays_out_of_the_legacy_totals():
    """The external path starts at the TLV3501 and skips the LM393 and the
    127.6 us of filtering, so its 360 ns cannot be folded into a legacy total;
    the shared stage stays what it always was."""
    result = budget.build()
    stages, totals = result["stages"], result["totals"]
    assert totals["shared_after_detection_us"] == pytest.approx(
        stages["comparator"]["us"] + stages["latch"]["us"] + totals["driver_branch_us"])
    external = result["external_fast_path"]
    assert external["status"] == "PARTIALLY_PRICED_NOT_INCLUDED_IN_TOTALS"
    assert "U11F and U19 delay" not in external["missing"]
    assert "the U6.4 AND and U10 stages after FAST_COMBINED" in external["missing"]


def test_a_gate_moved_off_the_chain_is_not_silently_repriced(monkeypatch):
    original = board.parts()

    def rewired():
        out = []
        for part in original:
            if part.ref == "U19" and part.unit == 1:
                nets = dict(part.nets)
                nets["2"] = "FAST_EXT_N"
                part = replace(part, nets=nets)
            out.append(part)
        return out

    monkeypatch.setattr(board, "parts", rewired)
    with pytest.raises(SystemExit, match="no longer in series"):
        budget.build()


def test_a_gate_swapped_for_another_part_is_not_repriced(monkeypatch):
    original = board.parts()

    def swapped():
        return [replace(part, value="CD4081BE")
                if (part.ref, part.unit) == ("U19", 1) else part
                for part in original]

    monkeypatch.setattr(board, "parts", swapped)
    with pytest.raises(SystemExit, match="not the CD4071B"):
        budget.build()


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
