"""Tests for the TLV3501 fast-overcurrent ECO module.

The interesting claims are not "the generator ran".  They are:

* the comparator's shutdown pin is held LOW -- on a TLV3501 a high SHDN
  *disables* the part, so the obvious "tie it to the supply" wiring produces a
  fast comparator that never switches;
* the push-pull output cannot reach FAST_EXT_N except through the open-drain
  NMOS; D0 receives the independent active-low signal at J10.4;
* the 1 us input pole plus the 12 ns over-temperature comparator delay is
  recomputed from the datasheet constants, not copied out of the report.

Run:
    python -m pytest tools/test_make_fast_oc_eco.py -q
"""

from __future__ import annotations

import json
import re

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
    assert by_ref(parts, "U1").value == "TLV3501AIDBVR"
    assert by_ref(parts, "U2").value == "LM4040D25IDBZR"
    assert by_ref(parts, "Q1").value == "2N7002"
    assert by_ref(parts, "D1").value == "BAT54W"
    assert by_ref(parts, "D2").value == "BAT54W"
    assert all(by_ref(parts, ref).footprint == "Diode_SMD:D_SOD-123"
               for ref in ("D1", "D2"))


def _pads_in(footprint: str) -> int:
    lib, name = footprint.split(":", 1)
    path = board.ROOT / "hardware" / "stock_footprints" / f"{lib}.pretty" / f"{name}.kicad_mod"
    return len(set(re.findall(r'\(pad "([^"]+)"', path.read_text(encoding="utf-8"))))


def test_every_symbol_pin_has_a_pad_in_its_footprint(parts):
    """A six-pin comparator on a three-pad SOT-23 is not assembleable.

    U1 shares nothing with U2 but a package family; the DBV package of the
    TLV3501 has six pins and the schematic table gave it the three-pad SOT-23
    that the two-pin shunt reference legitimately uses.  ERC cannot see this
    -- it never looks at footprints -- so the check has to read the land.
    """
    for part in parts:
        if not part.footprint:
            continue
        pads = _pads_in(part.footprint)
        assert pads >= len(part.nets), f"{part.ref}: {len(part.nets)} pins on {pads} pads"


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
    """The module keeps its active-low open-drain output, separate from U3B.
    The only path is U1.5 -> R5 -> Q1 gate -> Q1.3.
    """
    members = report["net_map"]["FAST_EXT_N"]
    assert "Q1.3" in members
    assert "U1.5" not in members
    assert by_ref(parts, "R5").nets == {"1": "OUT", "2": "Q1G"}
    assert by_ref(parts, "Q1").nets["3"] == "FAST_EXT_N"


def test_the_input_protection_is_two_diodes_and_a_series_divider(parts):
    assert by_ref(parts, "D1").nets == {"1": "INP", "2": "PGND"}
    assert by_ref(parts, "D2").nets == {"1": "V5I", "2": "INP"}
    assert by_ref(parts, "R2").nets == {"1": "OCD", "2": "INP"}


def test_every_mpn_in_the_bom_is_traced_to_a_datasheet_in_the_repository(parts):
    """Same rule as the SR board: a code with no source is an invented part.

    "BAT54" on a SOD-123 land was the review's example -- the same short name
    is SOT-23 at Nexperia and SOT323 as BAT54W, so the string cannot be ordered
    and must not sit in the MPN column.
    """
    for part in parts:
        if not part.mpn:
            assert part.mpn_source == "TO_SELECT", part.ref
            continue
        path = board.ROOT / part.mpn_source
        assert path.is_file(), f"{part.ref}: {part.mpn_source} does not exist"
        assert part.mpn in path.read_text(encoding="utf-8", errors="replace"), part.ref


def test_the_input_diodes_name_the_sod_123_part_not_the_short_name(parts):
    for ref in ("D1", "D2", "D3"):
        part = by_ref(parts, ref)
        assert part.mpn == "BAT54W-E3-08"
        assert part.mpn_source == "references/datasheets/bat54w.txt"
        assert part.footprint == "Diode_SMD:D_SOD-123"
        assert part.value == "BAT54W"


def test_the_land_in_use_is_compared_against_the_vendor_recommendation(report):
    """The vendored land is not Vishay's; the delta is reported, not hidden.

    Parsed from the footprint file, so swapping the library footprint changes
    the report instead of leaving a stale assertion.
    """
    land = report["d12_selection"]["land"]
    pads = board._vendored_pads(board.ROOT / board.D12_FP_FILE)
    assert pads["1"]["w_mm"] == land["vendored_pad_mm"][0]
    assert pads["1"]["h_mm"] == land["vendored_pad_mm"][1]
    assert land["vendor_centre_spacing_mm"] == pytest.approx(
        board.D12_VENDOR_GAP + board.D12_VENDOR_PAD_W)
    assert land["centre_spacing_delta_mm"] == pytest.approx(
        land["vendored_centre_spacing_mm"] - land["vendor_centre_spacing_mm"])
    # The footprint in use must at least cover the vendor land.
    assert land["vendored_pad_mm"][0] >= board.D12_VENDOR_PAD_W
    assert land["vendored_pad_mm"][1] >= board.D12_VENDOR_PAD_H
    assert abs(land["centre_spacing_delta_mm"]) < 0.1
    assert "NOT_THE_VENDOR_LAND" in land["verdict"]


def test_the_diode_selection_is_not_reported_as_qualified(report):
    sel = report["d12_selection"]
    assert sel["qualified"] is False
    assert sel["open_items"], "an unqualified part without open items is a claim"
    assert sel["datasheet"]["vrr_v"] >= board.V5 * 2, "30 V against a 5 V rail"
    assert sel["datasheet"]["ifsm_a"] > 0


def test_the_bom_file_carries_the_diode_codes(parts):
    import csv

    rows = {r["Reference"]: r for r in
            csv.DictReader((OUT / "BOM.csv").open(encoding="utf-8"))}
    assert rows["D1"]["MPN"] == "BAT54W-E3-08"
    assert rows["D1"]["MPN_Source"] == "references/datasheets/bat54w.txt"
    assert rows["D2"]["MPN"] == "BAT54W-E3-08"
    assert rows["R2"]["MPN"] == "" and rows["R2"]["MPN_Source"] == "TO_SELECT"


def test_q1_is_off_when_the_comparator_has_no_supply(parts):
    """Loss of 5 V must not assert a fault; R6 is the default-state element."""
    assert by_ref(parts, "R6").nets == {"1": "Q1G", "2": "PGND"}


# ------------------------------------------------------- rail isolation
def test_the_only_pull_up_on_the_output_is_referenced_to_the_connector(parts, report):
    """The healthy level must not depend on a rail that D2 can backfeed.

    With the pull-up on V5I, an open J1.1 left R7 fed by whatever the OCD
    divider could push through D2 -- an unspecified band below the
    comparator's 2.7 V minimum.  R7's top is now the connector net and Q1 can
    only pull down, so a lost J1.1 holds FAST_EXT_N low by construction.
    """
    assert report["net_map"]["FAST_EXT_N"] == ["J1.4", "Q1.3", "R7.2", "TP5.1"]
    assert by_ref(parts, "R7").nets == {"1": "V5", "2": "FAST_EXT_N"}
    assert by_ref(parts, "Q1").nets["3"] == "FAST_EXT_N"
    v5, v5i = set(report["net_map"]["V5"]), set(report["net_map"]["V5I"])
    # J1.1 is the only external source, and R7 is the only load on it.
    assert "J1.1" in v5
    assert {r for r in v5 if r.endswith(".1")} >= {"J1.1", "R7.1"}
    assert "R7.1" not in v5i, "the pull-up must not sit on the backfeedable rail"


def test_d3_is_the_only_element_between_the_connector_and_the_module_rail(parts):
    """Anything else bridging V5 and V5I would reopen the backfeed path."""
    bridges = [(p.ref, p.nets) for p in parts
               if not p.ref.startswith("#")
               and {"V5", "V5I"} <= set(p.nets.values())]
    assert bridges == [("D3", {"1": "V5I", "2": "V5"})]
    # Cathode (pin 1) on the module side, anode on the connector: current can
    # only flow inward.
    assert by_ref(parts, "D3").nets["1"] == "V5I"
    assert by_ref(parts, "D3").nets["2"] == "V5"


def test_every_part_that_needs_power_is_behind_d3(parts):
    """The comparator, the reference and their decoupling sit on V5I."""
    assert by_ref(parts, "U1").nets["4"] == "V5I"
    assert by_ref(parts, "R1").nets == {"1": "V5I", "2": "REF"}
    for ref in ("C1", "C2"):
        assert by_ref(parts, ref).nets == {"1": "V5I", "2": "PGND"}, ref


def test_backfeed_max_load_sensitivity_is_not_a_no_start_proof(report):
    """Recomputed from the divider, not copied from the report.

    The available current peaks with the rail at 0 V; it is the divider
    current left after the lower leg has taken its share.
    """
    bf = report["backfeed"]
    expected = (bf["common_mode_burden_v"] / board.R_TOP
                - board.VF_D3 * (1 / board.R_TOP + 1 / board.R_BOT))
    assert bf["available_current_at_design_max_a"] == pytest.approx(expected, rel=1e-3)
    assert bf["max_iq_to_available_ratio_assumption"] > 10
    assert bf["ocd_for_rail_minimum_assuming_max_iq_a"] > 10 * max(board.KNOWN_PEAKS_A.values())
    assert "UNSPECIFIED" in bf["rail_state_below_minimum"]
    assert bf["minimum_load_known"] is False
    assert bf["rail_cannot_start_proven"] is False


def test_the_verification_matrix_is_unexecuted_and_covers_the_review_cases(report):
    """The review asks for V5-open at low and high OCD, an open signal wire,
    and a whole-domain decay and recovery -- with no pass claim attached."""
    v = report["backfeed_verification"]
    assert v["status"] == "UNEXECUTED"
    ids = [c["id"] for c in v["cases"]]
    assert ids == [f"BF-{n:02d}" for n in range(1, 9)]
    for case in v["cases"]:
        assert case["executed"] is False
        assert case["result"] is None
        assert case["pass_criteria"].strip()
    names = " ".join(c["name"] for c in v["cases"]).lower()
    assert "ocd low" in names and "ocd high" in names
    assert "signal wire open" in names
    assert "decay" in names and "recovery" in names
    joined = " ".join(v["signals"])
    for signal in ("FAST_EXT_N", "FAST_COMBINED", "PERMIT"):
        assert signal in joined
    assert "current" in joined


# ---------------------------------------------------------------- arithmetic
def test_trip_and_release_match_the_three_resistor_network(report):
    d = report["threshold"]
    g = 1.0 / (1.0 / board.R_TOP + 1.0 / board.R_BOT + 1.0 / board.R_HYST)
    up = (board.VREF / g) * board.R_TOP
    down = (board.VREF / g - board.V5I / board.R_HYST) * board.R_TOP
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


def test_the_sr_front_end_is_counted_once_inside_q41_turn_on(report):
    sd = report["system_delay"]
    terms = sd["sr_branch_terms"]
    assert terms["excluded_input_rc_s"] == pytest.approx(0.0)
    assert "included in Q41" in terms["excluded_input_rc_reason"]
    # The input ladder is inside turn-on, not an additional RC delay.
    summed = (terms["crowbar_fet_turn_on_s"] + terms["reg_to_uvlo_s"]
              + terms["vg_active_low_s"])
    assert sd["sr_branch_s"] == pytest.approx(summed)
    assert terms["crowbar_fet_turn_on_s"] > 50e-9


def test_the_common_logic_is_read_from_the_d0_budget(report):
    """D0 owns the decode and the latch, so this module reads them back instead
    of keeping a second copy that can drift."""
    stages = json.loads((board.ROOT / "design/v3/stage_f/d0_response_budget.json")
                        .read_text(encoding="utf-8"))["stages"]
    sd = report["system_delay"]
    for key, channel in (("common_logic_terms", "external"),
                         ("existing_common_logic_terms", "fast")):
        terms = sd[key]
        assert terms["decode_s"] == pytest.approx(
            stages["decode"]["per_channel"][channel]["priced_max_us"] * 1e-6)
        assert terms["latch_s"] == pytest.approx(stages["latch"]["us"] * 1e-6)
        assert terms["total_s"] == pytest.approx(terms["decode_s"] + terms["latch_s"])
        assert terms["decode_gates"] == stages["decode"]["per_channel"][channel]["gates"]
    assert sd["common_logic_s"] == pytest.approx(sd["common_logic_terms"]["total_s"])
    assert sd["existing_common_logic_s"] == pytest.approx(
        sd["existing_common_logic_terms"]["total_s"])
    assert "d0_response_budget" in sd["d0_budget"]


def test_each_path_pays_its_own_decode_not_the_other_one(report):
    """The external trip crosses U11F before U19; the legacy LM393 trip enters
    U19 directly.  Each total uses its own term, and the gap is the inverter."""
    sd = report["system_delay"]
    ext, legacy = sd["common_logic_terms"], sd["existing_common_logic_terms"]
    assert "U11.6" in ext["decode_gates"] and "U11.6" not in legacy["decode_gates"]
    assert legacy["decode_gates"] == [g for g in ext["decode_gates"] if g != "U11.6"]
    assert ext["decode_s"] - legacy["decode_s"] == pytest.approx(110e-9)
    assert ext["latch_s"] == pytest.approx(legacy["latch_s"])
    slowest = max(sd["sr_branch_s"], sd["primary_branch_s"])
    assert sd["system_floor_s"] == pytest.approx(
        sd["detection_module_s"] + ext["total_s"] + slowest)
    assert sd["existing_system_floor_s"] == pytest.approx(
        report["delay"]["existing_path_total_s"] + legacy["total_s"] + slowest)
    # Charging one figure to both would fake a 0.11 us difference one way or the
    # other, so the two terms must actually differ.
    assert sd["common_logic_s"] != pytest.approx(sd["existing_common_logic_s"])


def test_the_common_logic_stays_a_floor_because_the_and_has_no_maximum(report):
    sd = report["system_delay"]
    assert sd["common_logic_is_a_floor"] is True
    assert "floor" in sd["common_logic_note"]
    for key in ("common_logic_terms", "existing_common_logic_terms"):
        assert sd[key]["unpriced_gates"] == ["U6.4"]
        assert sd[key]["complete"] is False


def test_a_moved_decode_chain_is_not_silently_repriced(tmp_path, monkeypatch):
    budget = json.loads((board.ROOT / "design/v3/stage_f/d0_response_budget.json")
                        .read_text(encoding="utf-8"))
    budget["stages"]["decode"]["per_channel"]["external"]["gates"][0] = "U19.1"
    moved = tmp_path / "d0_response_budget.json"
    moved.write_text(json.dumps(budget), encoding="utf-8")
    monkeypatch.setattr(board, "D0_BUDGET", moved)
    with pytest.raises(SystemExit, match="U11.6"):
        board.d0_common_logic()


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
    expected = (board.V5I - board.CM_HIGH_MARGIN) * (board.R_TOP + board.R_BOT) / board.R_BOT \
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
        (board.V5I - board.VREF) / board.R_BIAS)
    # D3's drop moved this from 1.04 mA to 0.88 mA; the range only guards
    # against a decade error, because the reference's minimum operating
    # current is still unverified.
    assert 0.7e-3 < report["supply"]["bias_current_a"] < 2e-3


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


def test_the_committed_erc_is_clean_and_schematic_source_is_pinned():
    """Git checkout mtime is not the time KiCad last ran on the schematic."""
    import hashlib

    sch = OUT / "fast_oc.kicad_sch"
    report = json.loads((OUT / "erc.json").read_text(encoding="utf-8"))
    assert report["source"] == sch.name
    assert board.erc_violations(OUT / "erc.json") == []
    index = json.loads((board.ROOT / "pcb/manufacturing/index.json").read_text())
    entry = next(x for x in index["boards"] if x["id"] == "fast_oc")
    assert entry["schematic_sha256"] == hashlib.sha256(sch.read_bytes()).hexdigest()
    assert entry["flags"]["fabrication_approved"] is False


def test_the_netlist_contains_every_module_net():
    text = (OUT / "fast_oc.net").read_text(encoding="utf-8")
    for net in ("V5", "V5I", "PGND", "OCD", "INP", "REF", "OUT", "Q1G",
                "SHDN", "FAST_EXT_N"):
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
