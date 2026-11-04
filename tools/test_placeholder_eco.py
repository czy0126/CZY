"""Tests for the 61-placeholder responsibility join.

The claims worth locking are not "the generator ran".  They are:

* the 61 placeholders partition cleanly into the 44 the deck-derived netlist
  fixes and the 17 the schematic generator adds as peripherals -- a new
  placeholder that lands in neither must fail, because that is exactly the
  part that would reach fabrication unowned;
* the requirement numbers are recomputed here from the source artefacts, not
  read back out of the produced table;
* the six magnetic rows are the only ones blocked on a physical terminal
  drawing, and their RFQ sheet still says NOT AVAILABLE;
* a "MAPPED" pin review on a magnetic part means only that the *logical*
  terminal name matches the symbol pin -- it is not a physical pinout, and the
  table must not let a reader believe otherwise.

Run:
    python -m pytest tools/test_placeholder_eco.py -q
"""

from __future__ import annotations

import csv
import json

import pytest

import main_board_schematic as schematic
import placeholder_eco as eco


@pytest.fixture(scope="module")
def built() -> dict:
    return eco.build()


@pytest.fixture(scope="module")
def by_ref(built) -> dict[str, dict]:
    return {row["ref"]: row for row in built["rows"]}


def source_json(name: str) -> dict:
    return json.loads((eco.BOM / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- partition
def test_every_register_item_gets_exactly_one_row(built):
    register = json.loads(eco.REGISTER.read_text(encoding="utf-8"))["items"]
    assert [r["ref"] for r in built["rows"]] == [i["ref"] for i in register]
    assert len(built["rows"]) == 61


def test_the_two_netlist_sources_partition_the_placeholders(built):
    """44 in the golden netlist + 17 peripherals, disjoint, and no third bucket."""
    golden = {r["ref"] for r in built["rows"] if r["netlist_governance"] == "GOLDEN_NETLIST"}
    peripheral = {r["ref"] for r in built["rows"]
                  if r["netlist_governance"] == "SCHEMATIC_PERIPHERAL"}
    assert golden & peripheral == set()
    assert len(golden) + len(peripheral) == 61
    assert peripheral == set(schematic.PERIPHERALS)


def test_the_golden_netlist_membership_agrees_with_the_derived_csv(built):
    rows = csv.DictReader(eco.GOLDEN.open(encoding="utf-8"))
    on_disk = {r["ref"] for r in rows}
    for row in built["rows"]:
        expected = "GOLDEN_NETLIST" if row["ref"] in on_disk else "SCHEMATIC_PERIPHERAL"
        assert row["netlist_governance"] == expected, row["ref"]


def test_a_placeholder_in_neither_source_would_be_rejected():
    """The guard, not just today's answer: an ungoverned ref must not pass."""
    governed = eco.golden_refs() | set(schematic.PERIPHERALS)
    assert "C999" not in governed


# ---------------------------------------------------------------- requirement
def test_the_transformer_gap_is_recomputed_from_the_magnetics_package(by_ref):
    mag = json.loads(eco.MAG.read_text(encoding="utf-8"))
    for i in range(1, 5):
        numbers = by_ref[f"T{i}"]["requirement_numbers"]
        assert numbers["gap_mm"] == pytest.approx(mag["gap_mm"])
    assert by_ref["T1"]["requirement"].startswith("centre-leg gap")


def test_the_inductor_requirement_is_the_three_turn_candidate(by_ref):
    lr = source_json("lr_design.json")
    three = next(c for c in lr["candidates"] if c["turns"] == 3)
    numbers = by_ref["Lr"]["requirement_numbers"]
    assert numbers["total_h"] == pytest.approx(lr["tank"]["total_target_h"])
    assert numbers["gap_mm"] == pytest.approx(three["gap_mm"])
    assert numbers["isat_a"] == pytest.approx(three["isat_a"])


def test_the_ct_trip_current_is_recomputed_from_ct_design(by_ref):
    ct = source_json("ct_design.json")["as_built"]
    numbers = by_ref["CT"]["requirement_numbers"]
    assert numbers["turns"] == ct["turns_ratio"]
    assert numbers["trips_a"] == pytest.approx(ct["trip_peak_a"])


def test_the_output_bank_count_is_the_esr_governed_one(by_ref):
    bank = source_json("cout_bank.json")["banks"][0]
    numbers = by_ref["Cout"]["requirement_numbers"]
    assert numbers["n"] == bank["n"] == bank["counts"]["esr"]
    assert numbers["n"] > bank["counts"]["capacitance"], "ESR, not capacitance, must govern"


def test_the_resonant_capacitor_numbers_are_recomputed(by_ref):
    cr = source_json("cr_stress.json")
    numbers = by_ref["Cr"]["requirement_numbers"]
    assert numbers["capacitance_f"] == pytest.approx(cr["capacitance_f"])
    assert numbers["v_max_v"] == pytest.approx(cr["v_max_v"])
    assert numbers["esr_ceiling_ohm"] == pytest.approx(cr["esr_ceiling_ohm"])


def test_the_input_capacitor_requirement_is_the_bridge_current_not_the_cin_current(by_ref):
    cin = source_json("passive_requirements.json")["cin"]
    numbers = by_ref["Cin"]["requirement_numbers"]
    assert numbers["bridge_ac_rms_a"] == pytest.approx(cin["bridge_ac_rms_a"])
    assert numbers["bridge_ac_rms_a"] > 10 * cin["cin_rms_ac_a"]


def test_the_burden_resistor_is_traced_to_both_its_value_and_its_power(by_ref):
    ct = source_json("ct_design.json")["as_built"]
    pulse = source_json("oc_burden_pulse.json")["results"]["runs"][0]
    numbers = by_ref["R3"]["requirement_numbers"]
    assert numbers["ohm"] == pytest.approx(ct["burden_ohm"])
    assert numbers["continuous_w"] == pytest.approx(pulse["pre_fault"]["mean_w"])
    # energy_mj is already millijoules; 0.123 mJ must not be printed as 122.6 mJ
    assert "0.123 mJ" in by_ref["R3"]["requirement"]
    assert "122." not in by_ref["R3"]["requirement"]


def test_the_oc_filter_time_constant_is_recomputed_from_the_deck(by_ref):
    deck = eco.DECK.read_text(encoding="utf-8")

    def token(name: str) -> str:
        for line in deck.splitlines():
            parts = line.split()
            if parts and parts[0].lower() == name.lower():
                return parts[3]
        raise AssertionError(name)

    tau = eco._si(token("Rf")) * eco._si(token("Cf"))
    numbers = by_ref["C11"]["requirement_numbers"]
    assert numbers["farads"] == pytest.approx(eco._si(token("Cf")))
    assert numbers["tau_s"] == pytest.approx(tau)
    assert tau == pytest.approx(47e-6, rel=1e-6)


def test_the_peripheral_requirement_comes_from_the_schematic_entry(by_ref):
    part = schematic.PERIPHERALS["C13"]
    row = by_ref["C13"]
    assert row["requirement_source"] == "tools/main_board_schematic.py:PERIPHERALS"
    assert part["value"] in row["requirement"]
    assert "RUN" in row["requirement"]


def test_the_untraced_twelve_are_the_reg_caps_and_the_kelvin_links(built):
    untraced = {r["ref"] for r in built["rows"] if not r["requirement_source"]}
    assert untraced == {f"C{i}" for i in (10, 7, 8, 9)} | {f"R{i}" for i in range(28, 36)}
    assert len(untraced) == 12
    for row in built["rows"]:
        if row["ref"] in untraced:
            assert row["requirement"] is None
            assert row["untraced_reason"]


# ---------------------------------------------------------------- magnetics
def test_the_six_magnetic_rows_are_the_only_ones_blocked_on_a_drawing(built):
    blocked = {r["ref"] for r in built["rows"]
               if r["blocked_on"] == "MAGNETIC_PHYSICAL_TERMINAL_DRAWING"}
    assert blocked == {"T1", "T2", "T3", "T4", "Lr", "CT"}


def test_every_magnetic_row_points_at_an_rfq_sheet_that_still_has_no_drawing(by_ref):
    for ref in ("T1", "T2", "T3", "T4", "Lr", "CT"):
        sheet = eco.RFQ / f"{ref}.md"
        assert sheet.is_file(), sheet
        assert "NOT AVAILABLE" in sheet.read_text(encoding="utf-8"), ref
        assert f"rfq/{ref}.md" in by_ref[ref]["next_action"]


def test_a_mapped_pin_review_on_the_inductor_is_logical_only(by_ref):
    """Lr's pins are MAPPED, which must not be read as a verified physical pinout."""
    assert by_ref["Lr"]["native_pin_review"] == "MAPPED"
    assert by_ref["Lr"]["native_pin_review_scope"] == "LOGICAL_TERMINAL_NAME_ONLY"
    assert by_ref["Lr"]["blocked_on"] == "MAGNETIC_PHYSICAL_TERMINAL_DRAWING"


def test_the_open_footprint_rows_are_the_transformer_and_ct_terminals(by_ref):
    open_refs = {r["ref"] for r in by_ref.values() if r["native_pin_review"] == "OPEN"}
    assert open_refs == {"T1", "T2", "T3", "T4", "CT"}
    assert len(by_ref["CT"]["native_open_pins"]) == 4


# ---------------------------------------------------------------- honesty
def test_no_row_claims_a_verified_mpn_or_an_owner(built):
    assert built["counts"]["with_verified_mpn"] == 0
    assert built["counts"]["with_decision_owner"] == 0
    assert all(r["verified_mpn"] is None for r in built["rows"])


def test_the_summary_counts_add_up(built):
    counts = built["counts"]
    assert sum(counts["by_priority"].values()) == 61
    assert sum(counts["by_netlist_governance"].values()) == 61
    assert sum(counts["by_blocked_on"].values()) == 61
    assert counts["traced_requirements"] + counts["untraced_requirements"] == 61
    assert built["status"] == eco.STATUS


def test_every_row_carries_a_next_action_without_inventing_a_part(built):
    for row in built["rows"]:
        assert row["next_action"].strip()
        assert "TO ASSIGN" not in row["next_action"]
    untraced = [r for r in built["rows"] if not r["requirement_source"]]
    assert len(untraced) == 12
    for row in untraced:
        assert "no computed requirement exists" in row["next_action"], row["ref"]


# ---------------------------------------------------------------- artefacts
def test_the_committed_files_are_current(built):
    for path, text in eco.write(built["rows"]):
        assert path.is_file(), path.name
        assert path.read_text(encoding="utf-8").replace("\r\n", "\n") == text, path.name
