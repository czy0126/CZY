"""D0 cannot inherit an unorderable SOD-123 BAT54 from circuit simulation.

14 independent Schottky instances need the actual ST SOD-123 item
BAT54ZFILM; the plain BAT54 is a different SOT-23 physical package.
Do not confuse topology sourced from SPICE with verified manufacturer MPN.
https://www.st.com/resource/en/datasheet/bat54.pdf
"""
from __future__ import annotations

import csv
import json
import re

import make_d0_protection_board as d0

REFS = [f"D{i}" for i in range(5, 19)]
OEM = "BAT54ZFILM"
FOOTPRINT = "Diode_SMD:D_SOD-123"
DATA = d0.ROOT / "pcb/d0_protection"


def test_all_ct_bridge_and_ten_gate_max_diodes_use_real_sod123_ordering():
    ps = {p.ref: p for p in d0.parts()}
    assert len(REFS) == 14
    assert all(ps[ref].value == OEM for ref in REFS)
    assert all(ps[ref].footprint == FOOTPRINT for ref in REFS)
    assert len({p.ref for p in ps.values()}) == len(ps)


def test_bom_exactly_contains_fourteen_non_ambiguous_vendor_diodes():
    with (DATA / "BOM.csv").open(encoding="utf-8", newline="") as f:
        rows = {r["Reference"]: r for r in csv.DictReader(f)}
    for ref in REFS:
        assert rows[ref]["Value"] == OEM
        assert rows[ref]["Footprint"] == FOOTPRINT
        assert rows[ref]["Qty"] == "1"
    assert all(rows[ref]["Value"] != "BAT54" for ref in REFS)


def test_native_schematic_and_ki_cad_export_have_same_14_ordering_values():
    schematic = (DATA / "d0_protection.kicad_sch").read_text(encoding="utf-8")
    netlist = (DATA / "d0_protection.net").read_text(encoding="utf-8")
    for ref in REFS:
        at = schematic.find(f'(property "Reference" "{ref}"')
        assert at >= 0
        assert f'(property "Value" "{OEM}"' in schematic[at:at + 500]
        assert re.search(
            r'\(ref "' + re.escape(ref) + r'"\)\s*\(value "' + OEM +
            r'"\)\s*\(footprint "' + re.escape(FOOTPRINT) + r'"\)', netlist
        )
    assert '(property "Value" "BAT54"' not in schematic


def test_eng_report_preserves_unapproved_hardware_claim():
    report = json.loads((DATA / "report.json").read_text(encoding="utf-8"))
    by_ref = {p["ref"]: p for p in report["parts"]}
    assert all(by_ref[ref]["value"] == OEM for ref in REFS)
    assert report["hardware_built"] is False
    assert report["fabrication_approved"] is False
