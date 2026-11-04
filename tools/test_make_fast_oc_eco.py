"""Tests for the TLV3501 fast-overcurrent ECO module.

The interesting claims are not "the generator ran".  They are:

* the comparator's shutdown pin is held LOW -- on a TLV3501 a high SHDN
  *disables* the part, so the obvious "tie it to the supply" wiring produces a
  fast comparator that never switches;
* the push-pull output cannot reach FAST_TRIP except through the open-drain
  NMOS, because D0's FAST_TRIP is a wired-OR node;
* the 1 us input pole plus the 12 ns over-temperature comparator delay is
  recomputed from the datasheet constants, not copied out of the report.

Run:
    python -m pytest tools/test_make_fast_oc_eco.py -q
"""

from __future__ import annotations

import json

import pytest

import make_fast_oc_eco as board
from make_sr_fault_board import pin_numbers

OUT = board.OUT


@pytest.fixture(scope="module")
def symbols() -> dict[str, str]:
    return board.build_symbols()


@pytest.fixture(scope="module")
def parts(symbols: dict[str, str]) -> list[board.Part]:
    ps = [board.snap(p) for p in board.parts()]
    board.validate(ps, symbols)
    return ps


@pytest.fixture(scope="module")
def report(parts: list[board.Part]) -> dict:
    return board.report(parts)


def by_ref(parts: list[board.Part], ref: str) -> board.Part:
    for p in parts:
        if p.ref == ref:
            return p
    raise AssertionError(f"{ref} not in the part table")


# ---------------------------------------------------------------- structure
def test_every_part_has_exactly_the_pins_its_symbol_defines(parts, symbols):
    for part in parts:
        assert set(part.nets) == set(pin_numbers(symbols[part.lib])), part.ref


def test_no_two_different_parts_share_a_pin_tip(parts, symbols):
    board.validate_no_coincident_tips(parts, symbols)


def test_the_comparator_and_the_open_drain_stage_are_present(parts):
    assert by_ref(parts, "U1").value == "TLV3501AIDBV"
    assert by_ref(parts, "U2").value == "LM4040DBZ-2.5"
    assert by_ref(parts, "Q1").value == "2N7002"


def test_shutdown_is_pulled_low_because_high_disables_the_comparator(parts, report):
    """TLV3501: SHDN within 0.9 V of V+ disables; >1.7 V below V+ enables.

    A module that ties SHDN to V+ passes ERC and never commutates.  The net
    must therefore be PGND-referenced and must not touch V5.
    """
    assert report["net_map"]["SHDN"] == ["R8.2", "TP6.1", "U1.6"]
    assert by_ref(parts, "U1").nets["6"] == "SHDN"
    assert by_ref(parts, "R8").nets == {"1": "PGND", "2": "SHDN"}
    assert "V5" not in report["net_map"]["SHDN"]


def test_the_push_pull_output_reaches_fast_trip_only_through_the_nmos(parts, report):
    """D0's FAST_TRIP is a wired-OR of open-drain drivers; a push-pull output
    tied to it would fight U3B.  The only path is U1.5 -> R5 -> Q1 gate -> Q1.3.
    """
    members = report["net_map"]["FAST_TRIP"]
    assert "Q1.3" in members
    assert "U1.5" not in members
    assert by_ref(parts, "R5").nets == {"1": "OUT", "2": "Q1G"}
    assert by_ref(parts, "Q1").nets["3"] == "FAST_TRIP"


def test_the_input_protection_is_two_diodes_and_a_series_divider(parts):
    assert by_ref(parts, "D1").nets == {"1": "INP", "2": "PGND"}
    assert by_ref(parts, "D2").nets == {"1": "V5", "2": "INP"}
    assert by_ref(parts, "R2").nets == {"1": "OCD", "2": "INP"}


def test_q1_is_off_when_the_comparator_has_no_supply(parts):
    """Loss of 5 V must not assert a fault; R6 is the default-state element."""
    assert by_ref(parts, "R6").nets == {"1": "Q1G", "2": "PGND"}


# ---------------------------------------------------------------- arithmetic
def test_trip_and_release_match_the_three_resistor_network(report):
    d = report["threshold"]
    g = 1.0 / (1.0 / board.R_TOP + 1.0 / board.R_BOT + 1.0 / board.R_HYST)
    up = (board.VREF / g) * board.R_TOP
    down = (board.VREF / g - board.V5 / board.R_HYST) * board.R_TOP
    assert d["trip_burden_v"] == pytest.approx(up)
    assert d["release_burden_v"] == pytest.approx(down)
    assert d["trip_current_a"] == pytest.approx(up / board.BURDEN_V_PER_A)


def test_the_nominal_threshold_is_the_divider_ratio_not_the_hysteresis_point(report):
    d = report["threshold"]
    assert d["nominal_trip_current_a"] == pytest.approx(
        board.VREF * (board.R_TOP + board.R_BOT) / board.R_BOT / board.BURDEN_V_PER_A)


def test_the_hysteresis_is_a_few_amps_and_positive(report):
    d = report["threshold"]
    assert d["hysteresis_a"] > 1.0
    assert d["hysteresis_a"] < 10.0
    assert d["trip_current_a"] > d["release_current_a"]


def test_the_input_pole_is_one_microsecond(report):
    assert report["threshold"]["input_tau_s"] == pytest.approx(
        board.C_IN * board.R_TOP * board.R_BOT / (board.R_TOP + board.R_BOT))


def test_the_delay_budget_uses_the_over_temperature_number_not_the_typical(report):
    """The roadmap forbids quoting the typical propagation delay as a system
    worst case.  The budget therefore uses the 5 mV, 125 C number."""
    d = report["delay"]
    assert d["comparator_worst_s"] == board.TPD_MAX_5MV_OVER_TEMP
    assert d["comparator_worst_s"] > d["comparator_typ_s"]
    assert "125" in d["worst_case_basis"] and "5 mV" in d["worst_case_basis"]
    assert d["module_total_s"] == pytest.approx(
        d["input_tau_s"] + d["comparator_worst_s"] + d["gate_network_s"])


def test_the_module_is_two_orders_of_magnitude_faster_than_the_filtered_path(report):
    d = report["delay"]
    assert d["improvement_factor"] > 100
    assert d["existing_path_total_s"] > 100 * d["module_total_s"]


def test_the_existing_path_is_three_cascaded_poles(report):
    stages = report["delay"]["existing_path"]
    assert [s["stage"] for s in stages] == ["rf_cf", "rd1_rd2_coc", "r12_c13"]
    assert stages[0]["tau_s"] == pytest.approx(47e-6, rel=1e-3)
    assert stages[1]["tau_s"] == pytest.approx(70.588e-6, rel=1e-3)
    assert stages[2]["tau_s"] == pytest.approx(10e-6, rel=1e-3)


# ---------------------------------------------------------------- whole machine
def test_the_system_stop_is_not_the_module_delay(report):
    """The 121x figure is detection only.  The machine waits for the slowest
    shutdown branch, so the two numbers must not be conflated."""
    sd = report["system_delay"]
    assert sd["detection_module_s"] == pytest.approx(report["delay"]["module_total_s"])
    # The machine ratio must be far smaller than the detection-only ratio: if a
    # future edit made them equal, the 121x line could be quoted as the system
    # number, which is exactly what the roadmap forbids.
    assert sd["system_improvement_factor"] < report["delay"]["improvement_factor"] / 5
    assert sd["system_floor_s"] > 5 * sd["detection_module_s"]


def test_the_shutdown_branch_comes_from_the_sr_board_report(report):
    sr = json.loads((board.ROOT / "pcb/sr_fault_validation/sr_fault_validation.json")
                    .read_text(encoding="utf-8"))["delay_budget"]
    branch = sr["sr_branch"]
    expected = (branch["crowbar_fet_turn_on_s"] + branch["reg_to_uvlo_s"]
                + branch["vg_active_low_s"])
    sd = report["system_delay"]
    assert sd["sr_branch_s"] == pytest.approx(expected)
    assert sd["slowest_branch"] == "sr"
    # The board's own max_branch_s is larger by its input RC, which the main
    # board does not have; the difference must be exactly that RC.
    assert sr["max_branch_s"] - sd["sr_branch_s"] == pytest.approx(branch["input_rc_s"])


def test_the_sr_front_end_rc_is_not_charged_to_the_main_board(report):
    sd = report["system_delay"]
    terms = sd["sr_branch_terms"]
    assert terms["excluded_input_rc_s"] == pytest.approx(10e-6)
    assert "validation board" in terms["excluded_input_rc_reason"]
    # The charged branch is exactly the three terms, with the RC kept aside.
    summed = (terms["crowbar_fet_turn_on_s"] + terms["reg_to_uvlo_s"]
              + terms["vg_active_low_s"])
    assert sd["sr_branch_s"] == pytest.approx(summed)
    assert sd["sr_branch_s"] < terms["excluded_input_rc_s"] * 2


def test_the_unmodelled_latch_is_reported_as_a_floor_not_a_worst_case(report):
    sd = report["system_delay"]
    assert sd["common_logic_s"] is None
    assert "floor" in sd["common_logic_note"]
    assert sd["system_floor_s"] == pytest.approx(
        sd["detection_module_s"] + max(sd["sr_branch_s"], sd["primary_branch_s"]))


def test_the_equation_is_the_roadmap_one(report):
    assert report["system_delay"]["equation"] == (
        "t_stop = t_CT/rectifier/filter + t_cmp + t_common_logic "
        "+ max(t_primary, t_SR)")


# ---------------------------------------------------------------- boundaries
def test_every_published_fault_peak_stays_inside_the_common_mode_range(report):
    for row in report["common_mode"]["rows"]:
        assert row["within_common_mode"], row
        assert row["within_absolute_max"], row


def test_the_common_mode_limit_is_recomputed_not_quoted(report):
    cm = report["common_mode"]
    expected = (board.V5 - board.CM_HIGH_MARGIN) * (board.R_TOP + board.R_BOT) / board.R_BOT \
        / board.BURDEN_V_PER_A
    assert cm["current_at_common_mode_limit_a"] == pytest.approx(expected)
    assert cm["current_at_common_mode_limit_a"] > max(board.KNOWN_PEAKS_A.values())


def test_the_threshold_sits_above_the_frozen_short_circuit_and_below_the_severe_faults(report):
    """That ordering is a design decision, so it is a test, not a comment.

    The frozen deck peaks at 73.68 A and is left to the controller's own
    overcurrent; the 84-101 A severe faults are what this module exists for.
    """
    trip = report["threshold"]["trip_current_a"]
    assert board.KNOWN_PEAKS_A["frozen_short_circuit_deck"] < trip
    assert trip < board.KNOWN_PEAKS_A["cold_start_fault"]
    assert trip < board.KNOWN_PEAKS_A["hotfault_50v_prefix"]


def test_the_reference_bias_is_about_a_milliamp(report):
    assert report["supply"]["bias_current_a"] == pytest.approx(
        (board.V5 - board.VREF) / board.R_BIAS)
    assert 1e-3 < report["supply"]["bias_current_a"] < 2e-3


def test_the_unverified_corner_is_named_as_unverified(report):
    """The LM4040 minimum operating current is not in this repository."""
    text = report["supply"]["minimum_reference_current"]
    assert "UNVERIFIED" in text


# ---------------------------------------------------------------- artefacts
def test_the_generated_schematic_is_current(symbols, parts):
    assert (OUT / "fast_oc.kicad_sch").read_text(encoding="utf-8") == board.schematic(
        symbols, parts)


def test_the_generated_report_is_current(parts, report):
    on_disk = json.loads((OUT / "fast_oc.json").read_text(encoding="utf-8"))
    assert on_disk == report


def test_the_erc_report_is_clean_and_not_stale():
    sch = OUT / "fast_oc.kicad_sch"
    assert board.erc_violations(OUT / "erc.json", newer_than=sch) == []


def test_the_netlist_contains_every_module_net():
    text = (OUT / "fast_oc.net").read_text(encoding="utf-8")
    for net in ("V5", "PGND", "OCD", "INP", "REF", "OUT", "Q1G",
                "SHDN", "FAST_TRIP"):
        assert f'(name "/{net}")' in text, net


def test_the_honesty_flags_stay_false(report):
    assert report["hardware_built"] is False
    assert report["fabrication_approved"] is False
    assert "not_hardware" in report["evidence_level"].lower()


def test_observations_cite_evidence_and_an_allowed_status(report):
    for obs in report["observations"]:
        assert obs["evidence"].strip(), obs["id"]
        assert obs["status"] in {"DESIGN_FACT", "DESIGN_DECISION",
                                 "DESIGN_ESTIMATE", "BOUNDARY"}, obs["id"]
