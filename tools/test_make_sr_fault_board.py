"""Tests for the single-pair UCC24624 SR fault-shutdown validation board.

The point of these tests is not that the generator runs.  It is that the two
claims the roadmap makes about SR shutdown are enforced by the *artefacts*:

* in NORMAL operation exactly one entity can pull VG high, and the optional
  clamp cannot do anything until somebody populates two DNP links;
* the REG crowbar is the *faster* path and a VDD cut is not, by a factor that is
  recomputed from the datasheet constants rather than copied from the report --
  but its delay is quoted at the 3.63 V turn-off threshold and is explicitly
  labelled an estimate, not a hardware worst case.

Run:
    python -m pytest tools/test_make_sr_fault_board.py -q
"""

from __future__ import annotations

import json
import math

import pytest

import make_sr_fault_board as board
import make_sr_fault_board_pcb as pcb

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
    d40 = by_ref(parts, "D40")
    assert d40.value.startswith("5V1")
    # ``Part.nets`` maps *symbol* pins, and ``validate()`` requires that key set
    # to equal the symbol's pin numbers exactly -- so a two-pin zener can only
    # ever reach pads 1 and 2 of its footprint.  The SOT-23 land this part sat
    # on until 2026-11-06 therefore left pad 3 (the cathode, and the third pin of
    # the package) as spare copper: the clamp was an open circuit, and the
    # netless-pad test in the PCB module blessed it as "intentional".
    assert pcb.pad_numbers(d40.footprint) == ["1", "2"]
    assert d40.nets == {"1": "FAULT_G", "2": "PGND"}


# ---------------------------------------------------------------- arithmetic
def test_crowbar_numbers_match_the_closed_form(report):
    c = board.C_REG_BYPASS + board.C_REG_HF
    r = board.R_CROWBAR + board.RDS_SELECTED
    assert report["crowbar"]["c_reg_f"] == pytest.approx(c)
    assert report["crowbar"]["stored_energy_j"] == pytest.approx(0.5 * c * board.VREG_TYP ** 2)
    assert report["crowbar"]["tau_s"] == pytest.approx(r * c)


def test_the_uvlo_time_is_the_late_turn_off_threshold(report):
    """The delay must cover a part that turns off at 3.63 V, not the 4.25 V typ/max.

    Using the high threshold makes the crowbar look ~1.5 us faster than a
    low-threshold device can deliver.  The 2026-11-05 review called that out;
    this test keeps the number on the slow side.
    """
    c = board.C_REG_BYPASS + board.C_REG_HF
    r = board.R_CROWBAR + board.RDS_SELECTED
    assert report["crowbar"]["time_to_uvlo_s"] == pytest.approx(
        r * c * math.log(board.VREG_TYP / board.VREGOFF_MIN))
    assert report["crowbar"]["time_to_uvlo_at_max_threshold_s"] == pytest.approx(
        r * c * math.log(board.VREG_TYP / board.VREGOFF_MAX))
    assert report["crowbar"]["time_to_uvlo_s"] > report["crowbar"]["time_to_uvlo_at_max_threshold_s"]
    assert board.VREGOFF_MIN == pytest.approx(3.63)


def test_the_crowbar_is_reported_as_an_estimate_not_a_worst_case(report):
    """The review's finding: none of these numbers is a hardware worst case."""
    band = report["crowbar"]["worst_case"]
    assert band["is_worst_case"] is False
    assert band["reasons"], "an estimate without reasons is a claim"
    joined = " ".join(band["reasons"]).lower()
    assert "reg" in joined or "regulator" in joined


def test_the_released_energy_is_the_11v_to_3p63v_difference(report):
    c = board.C_REG_BYPASS + board.C_REG_HF
    crow = report["crowbar"]
    released = 0.5 * c * (board.VREG_TYP ** 2 - board.VREGOFF_MIN ** 2)
    assert crow["energy_released_to_uvlo_j"] == pytest.approx(released)
    assert crow["resistor_share_j"] + crow["fet_share_j"] == pytest.approx(released)


def test_the_reg_current_limit_lengthens_the_discharge(report):
    """A constant REG injection is the sensitivity the review asked for.

    ``t = RC ln[(V0 - IR)/(Vth - IR)]`` only holds while I*R < Vth; the 95 mA
    figure is a 8 V condition, so this is a sensitivity, not a guarantee.
    """
    c = board.C_REG_BYPASS + board.C_REG_HF
    r = board.R_CROWBAR + board.RDS_SELECTED
    ir = board.IREGLIM_MAX_A * r
    expected = r * c * math.log((board.VREG_TYP - ir) / (board.VREGOFF_MIN - ir))
    assert report["crowbar"]["time_to_uvlo_with_reg_current_limit_s"] == pytest.approx(expected)
    assert report["crowbar"]["time_to_uvlo_with_reg_current_limit_s"] > report["crowbar"]["time_to_uvlo_s"]
    assert ir < board.VREGOFF_MIN


def test_the_crowbar_scenarios_name_both_the_placeholder_and_the_bom_target(report):
    rows = report["crowbar"]["scenarios"]
    rds = [row["rds_on_ohm"] for row in rows]
    assert rds == sorted(rds)
    assert board.RDS_ON_CROWBAR in rds
    assert board.RDS_BOM_TARGET in rds
    assert board.RDS_SELECTED in rds
    assert 0.0 in rds, "the R44-only ideal clamp is the review's 11.98 us figure"
    times = [row["time_to_uvlo_s"] for row in rows]
    assert all(a < b for a, b in zip(times, times[1:])), times


def test_the_headline_is_the_selected_part_not_the_old_placeholder(report):
    """The review's wording: do not keep quoting the 1.5 ohm placeholder.

    The placeholder row is slower (14.8 W R44 peak at 1.5 ohm becomes 25.2 W at
    0.048 ohm), so leaving it as the headline would understate the stress the
    selected part actually produces.
    """
    crow = report["crowbar"]
    assert crow["r_total_ohm"] == pytest.approx(board.R_CROWBAR + board.RDS_SELECTED)
    old = next(r for r in crow["scenarios"] if r["rds_on_ohm"] == board.RDS_ON_CROWBAR)
    assert crow["time_to_uvlo_s"] < old["time_to_uvlo_s"]
    assert "placeholder" in crow["note"]
    pulse = report["crowbar_pulse"]
    assert pulse["r44_peak_power_w"] > (board.VREG_TYP / (board.R_CROWBAR + 1.5)) ** 2 * board.R_CROWBAR


def test_the_selected_q41_records_the_gate_it_was_taken_at(report):
    """3.3 V harness x 10k/11k = 3.0 V, which is not a datasheet column."""
    sel = report["q41_selection"]
    assert sel["mpn"] == "AO3400A"
    assert (board.ROOT / sel["mpn_source"]).is_file()
    assert sel["gate_level_v_at_3v3_harness"] == pytest.approx(3.0, abs=0.01)
    assert sel["rds_used_ohm"] == pytest.approx(0.048)
    assert sel["rds_used_ohm"] == board.RDS_SELECTED, "the report and the arithmetic must agree"
    assert sel["qualified"] is False, "selected is not qualified"
    assert sel["open_items"], "an unqualified part without open items is a claim"
    assert sel["pins"] == {"1": "G", "2": "S", "3": "D"}
    assert sel["abs_max_vds_v"] >= board.VREG_TYP
    assert sel["idm_a"] > sel["stress_check"]["peak_current_a"]


def test_the_turn_on_crossing_is_labelled_an_estimate(report):
    """The review asked for turn-on SOA; the repository has no SOA curve."""
    t = report["q41_selection"]["turn_on_estimate"]
    assert t["time_to_threshold_s"] > 0
    assert t["miller_crossing_s"] > 0
    assert "ESTIMATE" in t["status"].upper()
    assert "unverified" in t["status"].lower()


def test_the_pulse_table_splits_the_energy_between_r44_and_q41(report):
    pulse = report["crowbar_pulse"]
    crow = report["crowbar"]
    assert pulse["r44_energy_j"] == pytest.approx(crow["resistor_share_j"])
    assert pulse["fet_energy_j"] == pytest.approx(crow["fet_share_j"])
    assert pulse["r44_peak_power_w"] == pytest.approx(
        (board.VREG_TYP / crow["r_total_ohm"]) ** 2 * board.R_CROWBAR)
    assert pulse["r44_mean_power_w"] == pytest.approx(
        pulse["r44_energy_j"] / crow["time_to_uvlo_s"])
    assert pulse["repetition"]["1_per_s_w"] == pytest.approx(pulse["r44_energy_j"] * 1)
    assert pulse["repetition"]["10_per_s_w"] == pytest.approx(pulse["r44_energy_j"] * 10)
    # The vendor pulse curve is looked up against a pulse width, so the energy
    # has to be convertible into one: W = E/P_peak for a rectangular pulse.
    assert pulse["r44_equivalent_pulse_width_s"] == pytest.approx(
        pulse["r44_energy_j"] / pulse["r44_peak_power_w"])


def test_the_pulse_rating_and_temperature_are_reported_as_unverified(report):
    """No 1206 pulse curve and no Q41 thermal model exist in this repository."""
    pulse = report["crowbar_pulse"]
    assert pulse["r44_pulse_rating_j"] is None
    assert pulse["q41_thermal"] is None
    note = pulse["temperature_note"].lower()
    assert "unverified" in note or "no vendor" in note


def test_every_mpn_in_the_bom_is_traced_to_a_datasheet_in_the_repository(parts):
    """An MPN with no source is an invented part number.

    The BOM carried an empty MPN column, which reads as "not filled in yet"
    rather than "not sourced" -- and the difference matters, because a
    fabricator quotes whatever is written there.  Now a row either names an
    orderable code whose string appears in a datasheet this repository holds,
    or says TO_SELECT in the source column.
    """
    for part in parts:
        if not part.mpn:
            assert part.mpn_source == "TO_SELECT", part.ref
            continue
        path = board.ROOT / part.mpn_source
        assert path.is_file(), f"{part.ref}: {part.mpn_source} does not exist"
        assert part.mpn in path.read_text(encoding="utf-8", errors="replace"), part.ref


def test_the_two_silicon_parts_have_their_orderable_code(parts):
    """The datasheets in references/ carry the ordering tables, so these two
    are the only rows that can be sourced without a vendor enquiry."""
    assert by_ref(parts, "U1").mpn == "UCC24624DR"          # TI ordering table
    assert by_ref(parts, "Q1").mpn == "BSC010N04LS6"        # Infineon ordering code
    assert by_ref(parts, "Q2").mpn == "BSC010N04LS6"
    assert by_ref(parts, "Q41").mpn == "AO3400A"            # AOS datasheet, Rev 3.1
    assert by_ref(parts, "Q41").mpn_source == "references/datasheets/ao3400a.txt"
    assert by_ref(parts, "C4").mpn_source == "TO_SELECT"


def test_the_bom_file_says_the_same_thing_as_the_part_table(parts):
    """Read the CSV, not the generator's list: the fabricator gets the file.

    A column added to ``bom()`` but never written, or written under a different
    header, passes a test that asks the part table instead.
    """
    import csv

    rows = list(csv.DictReader((OUT / "BOM.csv").open(encoding="utf-8")))
    assert {r["Reference"] for r in rows} == {p.ref for p in parts if not p.ref.startswith("#")}
    by = {r["Reference"]: r for r in rows}
    assert by["U1"]["MPN"] == "UCC24624DR"
    assert by["U1"]["MPN_Source"].startswith("references/datasheets/")
    assert by["Q1"]["MPN"] == "BSC010N04LS6"
    assert by["Q41"]["MPN"] == "AO3400A" and by["Q41"]["MPN_Source"].endswith("ao3400a.txt")
    assert by["C4"]["MPN"] == "" and by["C4"]["MPN_Source"] == "TO_SELECT"


def test_the_bom_carries_the_same_stress_the_report_computes(parts, report):
    """The ECO's acceptance is formula = schematic = BOM.

    A BOM line that still says "Rds <= 0.1 ohm" without naming the gate
    voltage, or a resistor note quoting no energy, would let the assembler
    pick a part the arithmetic never covered.
    """
    pulse = report["crowbar_pulse"]
    q41 = by_ref(parts, "Q41")
    r44 = by_ref(parts, "R44")
    assert "3.0 V" in q41.note
    assert f"{pulse['fet_energy_j'] * 1e3:.3f} mJ" in q41.note
    assert f"{pulse['r44_energy_j'] * 1e3:.3f} mJ" in r44.note
    assert "UNVERIFIED" in r44.note


def test_the_fault_input_defaults_to_no_crowbar_and_says_so(report):
    """FAULT_IN is pulled down, so a lost fault source means no shutdown."""
    default = report["input_default"]
    assert default["fault_input_default"] == "no crowbar"
    assert "lost" in default["limitation"].lower() or "disconnected" in default["limitation"].lower()
    assert default["fault_input_pulldown_ohm"] == pytest.approx(10e3)


def test_the_status_output_needs_an_external_pull_up(report):
    """FAULT_N is open drain with a 100k pulldown, so 'high' is a divider."""
    status = report["input_default"]["status_output"]
    assert status["pulldown_ohm"] == pytest.approx(100e3)
    assert status["external_pullup_v"] == pytest.approx(3.3)
    # The pull-up and the on-board pulldown form a divider and the pin sits at
    # the pulldown end: 3.3 V * 100k / (10k + 100k) = 3.0 V.  Quoting the
    # pull-up's own share (0.3 V) inverts the divider.
    assert status["high_level_v_with_10k_pullup"] == pytest.approx(3.3 * 100e3 / 110e3)
    assert status["high_level_v_with_10k_pullup"] > 2.7


def test_the_fault_gate_voltage_is_reported_for_both_harness_levels(report):
    """The BOM's 'Rds <= 0.1 ohm' has to be quoted at the gate voltage we have."""
    drive = report["input_default"]["gate_drive"]
    assert drive["fault_g_v_at_3v3"] == pytest.approx(3.3 * 10e3 / 11e3)
    assert drive["fault_g_v_at_5v0"] == pytest.approx(5.0 * 10e3 / 11e3)
    assert "3.0 V" in drive["rds_claim"] or "3 V" in drive["rds_claim"]


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

    On this board the SR branch is the slow one, because REG UVLO (~12 us at
    the 3.63 V threshold with the selected part) dominates the ~16 ns gate
    sink.  A test that assumed the primary branch was slower would hide the
    very trade-off the board exists to show.
    """
    budget = report["delay_budget"]
    assert "max(" in budget["rule"] and "not add" in budget["rule"]
    sr = budget["sr_branch"]["total_s"]
    primary = budget["primary_branch_reference"]["total_s"]
    assert budget["max_branch_s"] == pytest.approx(max(sr, primary))
    assert budget["slowest_branch"] == "sr"
    # The SR branch is dominated by REG UVLO, not by the gate sink.
    assert budget["sr_branch"]["reg_to_uvlo_s"] > 10 * budget["sr_branch"]["vg_active_low_s"]
    # The basis line must name the part the headline actually uses: a budget
    # that still says "placeholder" while the crowbar() table quotes a
    # selected Rds(on) is two numbers wearing one label.
    basis = budget["sr_branch"]["reg_to_uvlo_basis"]
    assert board.Q41_MPN in basis
    assert f"{board.RDS_SELECTED}" in basis
    assert "placeholder" not in basis
    assert not any("no MPN" in r for r in budget["not_worst_case_reasons"])
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
