"""OEM source-of-truth checks for the routed fast-OC bench board.

The fast-OC PCB previously specified D1,D2=BAT54 on SOD-123 lands.
ST's BAT54 (no Z) is SOT-23; BAT54ZFILM is the SOD-123 orderable item.
A KiCad DRC cannot detect this part/package procurement mismatch.
https://www.st.com/resource/en/datasheet/bat54.pdf
https://www.ti.com/product/TLV3501/part-details/TLV3501AIDBVR
https://www.ti.com/packaging/docs/carriermaterial/carrierlookup?OPN=LM4040D25IDBZR&state=details
"""
from __future__ import annotations

import csv
import json
import re

import make_fast_oc_eco as eco
import make_fast_oc_pcb as pcb

OEM = {
    "U1": ("TLV3501AIDBVR", "Package_TO_SOT_SMD:SOT-23-6"),
    "U2": ("LM4040D25IDBZR", "Package_TO_SOT_SMD:SOT-23"),
    "D1": ("BAT54ZFILM", "Diode_SMD:D_SOD-123"),
    "D2": ("BAT54ZFILM", "Diode_SMD:D_SOD-123"),
}


def test_source_part_table_is_vendor_orderable_and_footprint_consistent():
    actual = {p.ref: p for p in eco.parts()}
    for ref, (orderable, footprint) in OEM.items():
        assert actual[ref].value == orderable, ref
        assert actual[ref].footprint == footprint, ref
    assert actual["D1"].nets == {"1": "INP", "2": "PGND"}
    assert actual["D2"].nets == {"1": "V5", "2": "INP"}
    assert "NC" not in actual["U2"].note
    assert "anode" in actual["U2"].note


def test_oem_bom_matches_regenerated_source_and_has_four_real_ordering_ids(tmp_path, monkeypatch):
    with (eco.OUT / "BOM.csv").open(encoding="utf-8", newline="") as fh:
        committed = list(csv.DictReader(fh))
    monkeypatch.setattr(eco, "OUT", tmp_path)
    eco.bom(eco.parts())
    with (tmp_path / "BOM.csv").open(encoding="utf-8", newline="") as fh:
        generated = list(csv.DictReader(fh))
    assert committed == generated
    lookup = {row["Reference"]: row for row in committed}
    assert len(lookup) == len(committed) == 26
    assert {ref for ref, row in lookup.items() if row["MPN"]} == set(OEM)
    for ref, (orderable, footprint) in OEM.items():
        assert lookup[ref]["Value"] == lookup[ref]["MPN"] == orderable
        assert lookup[ref]["Footprint"] == footprint
        assert lookup[ref]["Qty"] == "1"
    assert all(row["MPN"] == "" for row in committed if row["Reference"] not in OEM)
    # 22 other orderable MPNs remain unselected: not a completed procurement BOM.


def _instance_value(contents: str, ref: str) -> str:
    loc = contents.find(f'(property "Reference" "{ref}"')
    assert loc >= 0, f"missing placed {ref}"
    fragment = contents[loc:loc + 900]
    match = re.search(r'\(property "Value" "([^"]+)"', fragment)
    assert match, f"missing placed Value property for {ref}"
    return match.group(1)


def test_schematic_and_routed_native_board_use_same_exact_orderable_values():
    schematic = (pcb.OUT / "fast_oc.kicad_sch").read_text(encoding="utf-8")
    native_pcb = (pcb.OUT / pcb.BOARD).read_text(encoding="utf-8")
    for ref, (orderable, _fp) in OEM.items():
        assert _instance_value(schematic, ref) == orderable
        assert _instance_value(native_pcb, ref) == orderable
    # The KiCad symbol remains Comparator:TLV3501AIDBV from the standard
    # library. This is a logical symbol ID, not a fabricated orderable MPN.
    assert '(lib_id "Comparator:TLV3501AIDBV")' in schematic


def test_exported_netlist_and_assembly_do_not_use_generic_bat54_package():
    netlist = (pcb.OUT / "fast_oc.net").read_text(encoding="utf-8")
    drawing = (pcb.FAB / "assembly.svg").read_text(encoding="utf-8")
    position = (pcb.FAB / f"{pcb.POS_PREFIX}-pos.csv").read_text(encoding="utf-8")
    for ref, (part, footprint) in OEM.items():
        assert re.search(
            r'\(ref "' + re.escape(ref) + r'"\)\s*\(value "' +
            re.escape(part) + r'"\)\s*\(footprint "' +
            re.escape(footprint) + r'"\)', netlist)
        assert part in drawing
        assert part in position
    for path in (netlist, drawing, position):
        assert not re.search(r'\bBAT54\b', path), "do not order generic BAT54"


def test_manufacturing_index_is_bound_to_the_corrected_board_hash_and_not_released():
    index = json.loads((pcb.ROOT / "pcb/manufacturing/index.json").read_text())
    row = next(r for r in index["boards"] if r["id"] == "fast_oc")
    manifest = json.loads(pcb.FAB_MANIFEST.read_text())
    assert row["board_sha256"] == manifest["board_sha256"]
    assert row["status"] == "FAB_PACKAGE_PRESENT"
    assert manifest["flags"] == {"hardware_built": False,
                                 "fabrication_approved": False}
    assert index["note"].startswith("A view over committed artefacts")
