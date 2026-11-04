"""Tests for the single-pair UCC24624 SR fault-shutdown validation board.

The point of these tests is not that the generator runs.  It is that the two
claims the roadmap makes about SR shutdown are enforced by the *artefacts*:

* in NORMAL operation exactly one entity can pull VG high, and the optional
  clamp cannot do anything until somebody populates two DNP links;
* the REG crowbar is the fast path and a VDD cut is not, by a factor that is
  recomputed from the datasheet constants rather than copied from the report.

Run:
    python -m pytest tools/test_make_sr_fault_board.py -q
"""

from __future__ import annotations

import json
import math

import pytest

import make_sr_fault_board as board

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
    """A part table entry that misses a pin leaves a real pin floating.

    ``validate`` already checks this, but the test calls it explicitly so a
    future refactor cannot quietly drop the check.
    """
    for part in parts:
        assert set(part.nets) == set(board.pin_numbers(symbols[part.lib]))


def test_no_two_different_parts_share_a_pin_tip(parts, symbols):
    board.validate_no_coincident_tips(parts, symbols)


def test_the_two_sr_fets_and_the_controller_are_present(parts):
    assert by_ref(parts, "U1").value == "UCC24624DR"
    for ref in ("Q1", "Q2"):
        assert by_ref(parts, ref).value == "BSC010N04LS6"


def test_vg1_is_driven_by_one_controller_pin_and_nothing_else(parts, report):
    """The roadmap forbids hard-parallel second push-pull drivers onto VG."""
    # U1 pin 1 is the only active driver; Rg1 leads to the MOSFET, TP5 is a
    # probe, and R47 is the DNP clamp link (pin 2 faces VG1).
    members = report["net_map"]["VG1"]
    assert members == ["R47.2", "Rg1.1", "TP5.1", "U1.1"], members


def test_the_gate_clamp_links_are_dnp_so_the_default_build_cannot_contend(parts):
    for ref in ("R47", "R48", "Q42", "Q43"):
        assert by_ref(parts, ref).dnp, f"{ref} must be DNP on the default build"


def test_the_crowbar_parts_are_populated(parts):
    for ref in ("Q41", "R44", "R43"):
        assert not by_ref(parts, ref).dnp, f"{ref} is the primary shutdown path"


def test_vss_and_pgnd_are_separate_nets_tied_by_the_offset_resistor(report, parts):
    """The SR gate loop must be measurable through a Kelvin return.

    If VSS were merged into PGND the 1 mR shunt drop would be invisible and the
    board could not show where the gate current actually returns.
    """
    assert set(report["net_map"]["VSS"]) == {"R1.1", "TP11.1", "U1.5"}
    assert "PGND" not in " ".join(report["net_map"]["VSS"])
    assert by_ref(parts, "R1").nets == {"1": "VSS", "2": "SR_SRC"}
    assert by_ref(parts, "Rsh1").nets == {"1": "SR_SRC", "2": "PGND"}


def test_the_fault_input_filter_is_not_milliseconds(parts):
    """10 k + 1 nF = 10 us.  A 1 ms debounce would swamp every gate delay."""
    c40 = by_ref(parts, "C40")
    assert c40.value.startswith("1nF")
    assert board.FAULT_RC_S <= 10e-6


def test_the_fault_input_has_a_default_low_and_a_clamp(parts):
    assert by_ref(parts, "R41").nets["2"] == "PGND"
    assert by_ref(parts, "D40").value.startswith("BZX84C5V1")


# ---------------------------------------------------------------- arithmetic
def test_crowbar_numbers_match_the_closed_form(report):
    c = board.C_REG_BYPASS + board.C_REG_HF
    r = board.R_CROWBAR + board.RDS_ON_CROWBAR
    assert report["crowbar"]["c_reg_f"] == pytest.approx(c)
    assert report["crowbar"]["stored_energy_j"] == pytest.approx(0.5 * c * board.VREG_TYP ** 2)
    assert report["crowbar"]["tau_s"] == pytest.approx(r * c)
    assert report["crowbar"]["time_to_uvlo_s"] == pytest.approx(
        r * c * math.log(board.VREG_TYP / board.VREGOFF_MAX))


def test_a_vdd_cut_is_orders_of_magnitude_slower_than_the_crowbar(report):
    """This is the roadmap's 'cutting VDD alone is not a guarantee', as a ratio."""
    ratio = report["vdd_cut"]["time_to_reg_uvlo_s"] / report["crowbar"]["time_to_uvlo_s"]
    assert ratio > 1000, ratio


def test_vdd_cut_time_matches_the_capacitance_and_run_current(report):
    c = board.C1_F + board.C2_F + board.C3_F
    expected = c * (board.VDD_NOM - board.VREGON_MAX) / board.IVDD_RUN_MAX
    assert report["vdd_cut"]["c_vdd_f"] == pytest.approx(c)
    assert report["vdd_cut"]["time_to_reg_uvlo_s"] == pytest.approx(expected)


def test_passive_gate_discharge_matches_rgs_times_ciss(report):
    assert report["gate_discharge"]["passive_tau_s"] == pytest.approx(
        board.R_GS * board.CISS_MAX)


def test_a_2n7002_class_clamp_cannot_hold_the_gate_below_threshold(report):
    row = next(r for r in report["vg_clamp_table"] if r["rds_on_ohm"] == 1.5)
    assert row["vg_hold_v"] > board.VGS_TH_MIN
    assert not row["below_vgs_th_min"]


def test_a_clamp_that_works_demands_more_current_than_the_controller_sources(report):
    row = next(r for r in report["vg_clamp_table"] if r["rds_on_ohm"] == 0.02)
    assert row["below_vgs_th_min"]
    assert row["exceeds_ic_source_limit"]
    assert row["ic_dissipation_w"] > 10.0


def test_the_clamp_table_is_monotonic_in_rds_on(report):
    rows = report["vg_clamp_table"]
    assert [r["rds_on_ohm"] for r in rows] == sorted(r["rds_on_ohm"] for r in rows)
    assert all(a["vg_hold_v"] < b["vg_hold_v"] for a, b in zip(rows, rows[1:]))


# ---------------------------------------------------------------- states
def test_every_state_names_a_vg_driver_and_a_pulldown(report):
    for state in report["states"]:
        for key in ("state", "entry", "vg_high_driver", "vg_low_driver",
                    "reg_owner", "vdd_owner", "gate_pulldown", "expected"):
            assert state.get(key), f"{state.get('state')} is missing {key}"


def test_the_state_list_covers_the_roadmap_cases(report):
    names = {s["state"] for s in report["states"]}
    assert names == {"NORMAL", "FAULT_REG_CROWBAR", "FAULT_VDD_CUT",
                     "FAULT_VG_CLAMP", "STANDBY", "POWER_DOWN"}


def test_the_delay_budget_takes_the_slowest_branch_not_the_sum(report):
    """The roadmap's rule: t_stop = t_common + max(t_primary, t_SR).

    On this board the SR branch is the slow one, because REG UVLO (~14 us)
    dominates the 4 A gate sink (~16 ns).  A test that assumed the primary
    branch was slower would hide the very trade-off the board exists to show.
    """
    budget = report["delay_budget"]
    assert "max(" in budget["rule"] and "not add" in budget["rule"]
    sr = budget["sr_branch"]["total_s"]
    primary = budget["primary_branch_reference"]["total_s"]
    assert budget["max_branch_s"] == pytest.approx(max(sr, primary))
    assert budget["slowest_branch"] == "sr"
    # The SR branch is dominated by REG UVLO, not by the gate sink.
    assert budget["sr_branch"]["reg_to_uvlo_s"] > 10 * budget["sr_branch"]["vg_active_low_s"]
    # And the serial sum would be measurably wrong, which is why the rule exists.
    assert budget["max_branch_s"] < sr + primary


# ---------------------------------------------------------------- artefacts
def test_the_generated_schematic_is_current(symbols, parts):
    text = board.schematic(symbols, parts)
    assert (OUT / "sr_fault_validation.kicad_sch").read_text(encoding="utf-8") == text


def test_the_generated_report_is_current(parts, report):
    on_disk = json.loads((OUT / "sr_fault_validation.json").read_text(encoding="utf-8"))
    assert on_disk == report


def test_the_erc_report_is_clean_and_not_stale():
    sch = OUT / "sr_fault_validation.kicad_sch"
    violations = board.erc_violations(OUT / "erc.json", newer_than=sch)
    assert violations == []


def test_the_netlist_contains_the_critical_nets():
    text = (OUT / "sr_fault_validation.net").read_text(encoding="utf-8")
    for net in ("VDD", "REG", "VG1", "VG2", "VD1", "VD2", "VSS", "SR_SRC",
                "SEC_A", "SEC_B", "VOUT", "FAULT_IN", "FAULT_G", "REG_CROW"):
        assert f'(name "/{net}")' in text, net


def test_the_honesty_flags_stay_false(report):
    assert report["hardware_built"] is False
    assert report["fabrication_approved"] is False
    assert "not_hardware" in report["evidence_level"].lower()


def test_observations_cite_a_datasheet_or_the_board_scope(report):
    for obs in report["observations"]:
        assert obs["evidence"].strip(), obs["id"]
        assert obs["status"] in {"DESIGN_DECISION", "DESIGN_ESTIMATE", "BOUNDARY"}, obs["id"]
