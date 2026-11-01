"""Tests for tools/board_netlist.py.

The point of the tool is that the board's connectivity is *derived* from the deck,
so these tests check the derivation stayed faithful: the cavity chain is what the
simulation says, the transformer halves share one centre-tap pin, and no part in
the netlist is missing from the BOM.
"""

from __future__ import annotations

import csv

import pytest

from board_netlist import (
    DECK, ROOT, bom_gaps, build, deck_lines, expand_refs, lint, merge, parse_elements,
    winding_layout,
)

BOM = ROOT / "design/v3/bom/bom_draft.csv"


@pytest.fixture(scope="module")
def netlist():
    result = build()
    rows, conflicts = merge(result["rows"])
    return result, rows, conflicts


def pins_of(rows, ref):
    return {row["pin"]: row["net"] for row in rows if row["ref"] == ref}


def net_refs(rows, net):
    return sorted({row["ref"] for row in rows if row["net"] == net})


def test_every_deck_element_is_accounted_for(netlist):
    result, _, _ = netlist
    assert result["unmapped"] == []
    assert result["fallback_nets"] == []


def test_the_netlist_lints_clean(netlist):
    _, rows, conflicts = netlist
    assert conflicts == []
    checks = lint(rows, conflicts)
    assert checks["ok"], checks["single_pin_nets"]
    assert checks["pins"] == len(rows)


def test_high_side_fets_are_wired_across_the_input(netlist):
    _, rows, _ = netlist
    assert pins_of(rows, "QH") == {"D": "VIN_P", "S": "SW", "G": "GH"}
    assert pins_of(rows, "QL") == {"D": "SW", "S": "PGND", "G": "GL"}


def test_the_cavity_is_cr_then_ct_then_lr(netlist):
    """sw -Cr- CR_CT -CT- CT_LR -Lr- primary, exactly as the deck chains them."""
    _, rows, _ = netlist
    assert pins_of(rows, "Cr") == {"N1": "SW", "N2": "CR_CT"}
    assert pins_of(rows, "CT") == {"PRI_A": "CR_CT", "PRI_B": "CT_LR",
                                   "SEC_A": "CS1", "SEC_B": "CS2"}
    assert pins_of(rows, "Lr") == {"N1": "CT_LR", "N2": "PRI_T1"}


def test_the_four_primaries_are_in_series_and_end_at_pgnd(netlist):
    _, rows, _ = netlist
    assert net_refs(rows, "PRI_T1") == ["Lr", "T1"]
    assert net_refs(rows, "PRI_12") == ["T1", "T2"]
    assert net_refs(rows, "PRI_23") == ["T2", "T3"]
    assert net_refs(rows, "PRI_34") == ["T3", "T4"]
    assert "T4" in net_refs(rows, "PGND")


def test_each_transformer_has_five_pins_and_one_centre_tap(netlist):
    """Both half-windings share T.CTAP, so it appears twice and must merge to one net."""
    _, rows, conflicts = netlist
    assert conflicts == []
    for i in (1, 2, 3, 4):
        pins = pins_of(rows, f"T{i}")
        assert len(pins) == 5, pins
        assert pins["CTAP"] == "VOUT"
        assert pins["SEC_A"] == f"SEC{i}_A"
        assert pins["SEC_B"] == f"SEC{i}_B"


def test_synchronous_rectifiers_go_from_secondary_to_pgnd(netlist):
    _, rows, _ = netlist
    for i in (1, 2, 3, 4):
        assert pins_of(rows, f"SR{i}A") == {"D": f"SEC{i}_A", "G": f"GA{i}", "S": "PGND"}
        assert pins_of(rows, f"SR{i}B") == {"D": f"SEC{i}_B", "G": f"GB{i}", "S": "PGND"}


def test_u1_pin_numbers_match_the_verified_map(netlist):
    _, rows, _ = netlist
    assert pins_of(rows, "U1") == {
        "1": "DT", "2": "RT", "3": "OC", "4": "SS",
        "5": "GD2", "6": "PGND", "7": "VCC12", "8": "GD1"}


def test_the_sr_controllers_carry_their_own_reg_caps(netlist):
    _, rows, _ = netlist
    for i, n in enumerate((3, 4, 5, 6), start=1):
        assert pins_of(rows, f"U{n}")["3"] == f"REG{i}"
        assert net_refs(rows, f"REG{i}") == [f"C{n + 4}", f"U{n}"]


def test_the_sr_gate_goes_through_its_2r2(netlist):
    """The UCC24624 output is VG; the SR gate is one 2.2 ohm resistor away."""
    _, rows, _ = netlist
    for i in (1, 2, 3, 4):
        for half in ("A", "B"):
            resistor = f"R{18 + 2 * i + (half == 'B')}"
            assert net_refs(rows, f"VG{i}_{half}") == [resistor, f"U{i + 2}"]
            assert net_refs(rows, f"G{half}{i}") == [resistor, f"SR{i}{half}"]


def test_the_drain_sense_is_a_kelvin_link_not_a_short(netlist):
    """Shorting VD to SEC would hide the whole point of a Kelvin connection."""
    _, rows, _ = netlist
    for i in (1, 2, 3, 4):
        for half in ("A", "B"):
            link = f"R{26 + 2 * i + (half == 'B')}"
            assert net_refs(rows, f"VD{i}_{half}") == [link, f"U{i + 2}"]
            assert link in net_refs(rows, f"SEC{i}_{half}")
            assert f"U{i + 2}" not in net_refs(rows, f"SEC{i}_{half}")


def test_u2_bridges_the_controller_and_the_gate_resistors(netlist):
    _, rows, _ = netlist
    u2 = pins_of(rows, "U2")
    assert u2["7"] == "GD1" and u2["8"] == "GD2"
    assert u2["4"] == "GH_DRV" and u2["10"] == "GL_DRV"
    assert net_refs(rows, "GH_DRV") == ["R4", "U2"]
    assert net_refs(rows, "GL_DRV") == ["R5", "U2"]


def test_conflicting_pin_claims_are_reported():
    rows = [
        {"net": "A", "ref": "X", "pin": "1", "basis": "", "deck_element": ""},
        {"net": "B", "ref": "X", "pin": "1", "basis": "", "deck_element": ""},
    ]
    merged, conflicts = merge(rows)
    assert len(merged) == 1
    assert conflicts == ["X.1: A vs B"]


def test_the_parser_drops_model_names_and_parameters():
    elements = parse_elements([
        "R1 a b 10k", "C1 a 0 1u Rser=5m", "Xsa1 da1 ga1 sgnd SR_DEVICE",
        "Xsr1 a1 b1 ga1 gb1 reg sgnd pre1 SR_TIMING PGD=0 CGATE=0",
        "SH vin sw gh sw PRI_SW", "B1 ovl 0 V=min(1,2)", ".tran 0 1m",
    ])
    assert elements["R1"] == ["a", "b"]
    assert elements["C1"] == ["a", "0"]
    assert elements["Xsa1"] == ["da1", "ga1", "sgnd"]
    assert elements["Xsr1"] == ["a1", "b1", "ga1", "gb1", "reg", "sgnd", "pre1"]
    assert elements["SH"] == ["vin", "sw", "gh"]      # nc- dropped, not a pin
    assert elements["B1"] == ["ovl", "0"]


def test_every_netlist_part_is_in_the_bom(netlist):
    _, rows, _ = netlist
    with BOM.open(encoding="utf-8", newline="") as fh:
        covered: set[str] = set()
        for row in csv.DictReader(fh):
            covered |= set(expand_refs(row["ref"]))
    missing = sorted({row["ref"] for row in rows} - covered)
    assert missing == [], missing


def test_ref_expansion_handles_both_halves_of_a_range():
    """'SR1A-SR4B' is eight refs, not four -- the pin map names both halves."""
    assert set(expand_refs("SR1A-SR4B")) == {f"SR{i}{h}" for i in (1, 2, 3, 4) for h in "AB"}
    assert set(expand_refs("R20-R27")) == {f"R{n}" for n in range(20, 28)}
    assert set(expand_refs("QH QL")) == {"QH", "QL"}
    assert set(expand_refs("C101-C112")) == {f"C{n}" for n in range(101, 113)}


def test_no_bom_ref_is_absent_from_the_netlist(netlist):
    """A BOM line with no pin anywhere is either an omission or a phantom part."""
    _, rows, _ = netlist
    gaps = bom_gaps({row["ref"] for row in rows})
    assert gaps["bom_refs_without_a_pin"] == [], gaps["bom_refs_without_a_pin"]


def test_the_exclusion_list_does_not_shadow_a_real_part(netlist):
    """Excluded refs must genuinely have no pins, or the check is being bypassed."""
    _, rows, _ = netlist
    refs = {row["ref"] for row in rows}
    gaps = bom_gaps(refs)
    assert set(gaps["excluded"]) & refs == set()
    # and the list covers the whole decoupling block the pin map calls for
    assert {f"C{n}" for n in range(101, 113)} <= set(gaps["excluded"])


def test_the_bootstrap_diode_holds_off_the_full_input_voltage():
    """`Dbt aux hb` with `Cbt hb sw`: when QH is on, the cathode sits VIN above VCC12.

    So the reverse voltage is 48 V, not the 25 V the BOM once claimed.  The BOM row
    must keep saying so or a 25 V part gets bought.
    """
    lines = deck_lines(ROOT / DECK)
    dbt = next(line.split() for line in lines if line.split()[0] == "Dbt")
    cbt = next(line.split() for line in lines if line.split()[0] == "Cbt")
    assert dbt[1:3] == ["aux", "hb"]
    assert cbt[1:3] == ["hb", "sw"]

    with BOM.open(encoding="utf-8", newline="") as fh:
        row = next(r for r in csv.DictReader(fh) if r["ref"] == "D_BT")
    assert "48 V" in row["value_or_rating"]
    assert "25 V" not in row["value_or_rating"]


def test_the_deck_does_not_load_the_bootstrap_capacitor():
    """`Bgh` sits between gh0 and sw, not between hb and sw, so no gate charge ever
    crosses Cbt: the model holds HB a fixed 12 V above SW and cannot show droop.

    Every bootstrap number in the BOM (9.6 mA average, 218 mV droop) is therefore
    analytic, not measured.  If this ever fails, the deck gained a real gate load
    and those numbers must be re-derived from a run.
    """
    lines = deck_lines(ROOT / DECK)
    touch_hb = sorted(line.split()[0] for line in lines if "hb" in line.split()[1:4])
    assert touch_hb == ["Cbt", "Dbt"]

    bgh = next(line.split() for line in lines if line.startswith("Bgh "))
    assert bgh[1:3] == ["gh0", "sw"]


def test_the_centre_tap_joins_s_a_dot_to_s_b_non_dot():
    """The deck writes `Lsa out a1` and `Lsb b1 out`; SPICE puts the dot on the
    first node.  So CTAP is S_A's DOT and S_B's NON-dot.  Joining the two DOTs at
    the tap would make both halves the same polarity: the rectifier would no
    longer be full-wave and the two SEC terminals would carry the same phase.
    """
    report = winding_layout()
    assert report["ok"], [check for check in report["checks"] if not check["ok"]]
    for i in (1, 2, 3, 4):
        transformer = report["transformers"][f"T{i}"]
        a, b = transformer["secondary_a"], transformer["secondary_b"]
        assert (a["dot_pin"], a["non_dot_pin"]) == ("CTAP", "SEC_A")
        assert (b["dot_pin"], b["non_dot_pin"]) == ("SEC_B", "CTAP")
        assert a["dot_node"] == b["non_dot_node"] == "out"
        assert a["non_dot_node"] == f"a{i}"
        assert b["dot_node"] == f"b{i}"
        assert a["dot_node"] != b["dot_node"]


def test_the_primary_units_are_series_aiding():
    """p1 -> p2 -> p3 -> p4 -> 0: each Lp's NON-dot meets the next Lp's DOT."""
    report = winding_layout()
    assert report["ok"], [check for check in report["checks"] if not check["ok"]]
    transformers = report["transformers"]
    for i in (1, 2, 3):
        assert (transformers[f"T{i}"]["primary"]["non_dot_node"]
                == transformers[f"T{i + 1}"]["primary"]["dot_node"])
    assert transformers["T1"]["primary"]["dot_node"] == "p1"
    assert transformers["T4"]["primary"]["non_dot_node"] == "0"


def test_the_deck_dot_order_matches_the_board_pin_order():
    """A pin name is only useful if it is the pin that carries the DOT."""
    report = winding_layout()
    assert report["ok"], [check for check in report["checks"] if not check["ok"]]
    for i in (1, 2, 3, 4):
        transformer = report["transformers"][f"T{i}"]
        for key in ("primary", "secondary_a", "secondary_b"):
            assert transformer[key]["board_pins"][0] == transformer[key]["dot_pin"]


def test_a_reversed_secondary_half_fails_the_polarity_check(tmp_path):
    """Net names alone cannot catch this: swapping the two nodes of one L keeps
    every net label and only reverses that half-winding."""
    text = (ROOT / DECK).read_text(encoding="utf-8", errors="replace")
    assert "Lsb1 b1 out" in text
    bad = tmp_path / "reversed.cir"
    bad.write_text(text.replace("Lsb1 b1 out", "Lsb1 out b1"), encoding="utf-8")
    report = winding_layout(bad)
    assert report["ok"] is False
    failed = [check["name"] for check in report["checks"] if not check["ok"]]
    assert any("T1" in name and "S_B" in name for name in failed), failed


def test_the_polarity_map_is_generated_and_current(tmp_path):
    """The manufacturing CSV/JSON and the first-article record are generated, not
    retyped; a stale file would let the shop floor build the old definition."""
    import winding_polarity

    winding_polarity.write(tmp_path)
    for name in ("winding_polarity.json", "winding_polarity.csv",
                 "first_article_polarity_record.csv"):
        committed = ROOT / "design/v3/magnetics" / name
        assert committed.exists(), name
        assert (tmp_path / name).read_text(encoding="utf-8") == committed.read_text(encoding="utf-8"), name


def test_the_polarity_map_covers_every_manufacturing_terminal():
    """P1/P2/P3, S_A, S_B, CTAP, SEC_A and SEC_B must all be named somewhere."""
    import winding_polarity

    report = winding_polarity.build()
    terminals = {row["terminal"] for row in report["terminals"]}
    for expected in ("P1_IN", "P1_OUT", "P2_IN", "P2_OUT", "P3_IN", "P3_OUT",
                     "CTAP", "SEC_A", "SEC_B"):
        assert expected in terminals, expected
    assert report["ok"], report["checks"]


def test_the_generated_files_are_current(tmp_path):
    """The committed CSV must match a fresh run, or the board model has drifted."""
    import board_netlist

    out = tmp_path / "board_netlist.csv"
    board_netlist.write_csv(merge(board_netlist.build()["rows"])[0], out)
    committed = ROOT / "design/v3/pcb/board_netlist.csv"
    assert out.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8")


def test_the_deck_referenced_still_exists():
    assert (ROOT / DECK).exists()
