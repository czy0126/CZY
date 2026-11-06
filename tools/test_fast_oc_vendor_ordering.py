"""OEM source-of-truth checks for the routed fast-OC bench board.

The fast-OC PCB previously specified D1,D2=BAT54 on SOD-123 lands.
The plain BAT54 is SOT-23; the SOD-123 orderable item this repository can
document is Vishay's BAT54W-E3-08 (references/datasheets/bat54w.txt).  A KiCad
DRC cannot detect this part/package procurement mismatch, so the check has to
read the generated artefacts.

U1/U2 are written as the orderable reel/tape codes.  Their data sheets are not
in this repository, so the BOM's MPN column stays empty for them (MPN_Source =
TO_SELECT) while the Value column carries the code that was selected.
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
    "D1": ("BAT54W", "Diode_SMD:D_SOD-123"),
    "D2": ("BAT54W", "Diode_SMD:D_SOD-123"),
}
# Only the diodes have a data sheet in this repository, so only they may carry
# an orderable code in the BOM's MPN column.
MPN = {"D1": "BAT54W-E3-08", "D2": "BAT54W-E3-08"}


def test_source_part_table_is_vendor_orderable_and_footprint_consistent():
    actual = {p.ref: p for p in eco.parts()}
    for ref, (orderable, footprint) in OEM.items():
        assert actual[ref].value == orderable, ref
        assert actual[ref].footprint == footprint, ref
    for ref, orderable in MPN.items():
        assert actual[ref].mpn == orderable, ref
        assert (eco.ROOT / actual[ref].mpn_source).is_file(), ref
    assert actual["D1"].nets == {"1": "INP", "2": "PGND"}
    assert actual["D2"].nets == {"1": "V5I", "2": "INP"}
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
    assert len(lookup) == len(committed) == 27
    assert {ref for ref, row in lookup.items() if row["MPN"]} == {"D1", "D2", "D3"}
    for ref, (orderable, footprint) in OEM.items():
        assert lookup[ref]["Value"] == orderable
        assert lookup[ref]["Footprint"] == footprint
        assert lookup[ref]["Qty"] == "1"
    for ref, orderable in MPN.items():
        assert lookup[ref]["MPN"] == orderable
        assert lookup[ref]["MPN_Source"].startswith("references/datasheets/")
    # U1/U2 are selected by reel code but have no data sheet here, so their MPN
    # column must stay empty: a filled MPN would claim a trace this repo cannot show.
    for ref in ("U1", "U2"):
        assert lookup[ref]["MPN"] == ""
        assert lookup[ref]["MPN_Source"] == "TO_SELECT"
    # 24 other orderable MPNs remain unselected: not a completed procurement BOM.


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
    # A bare BAT54 is the SOT-23 part.  The netlist's Description property may
    # still name it as the part this is *not*, so read the orderable fields
    # instead of the whole text.
    assert not re.search(r'\(value "BAT54"\)', netlist), "do not order generic BAT54"
    assert not re.search(r'\(footprint "[^"]*:BAT54"\)', netlist)
    assert not re.search(r'(?:^|,)BAT54(?:,|$)', position, re.MULTILINE)
    assert not re.search(r'>BAT54<', drawing)


def test_manufacturing_index_is_bound_to_the_corrected_board_hash_and_not_released():
    index = json.loads((eco.ROOT / "pcb/manufacturing/index.json").read_text())
    row = next(r for r in index["boards"] if r["id"] == "fast_oc")
    manifest = json.loads(pcb.FAB_MANIFEST.read_text())
    assert row["board_sha256"] == manifest["board_sha256"]
    assert row["status"] == "FAB_PACKAGE_PRESENT"
    assert manifest["flags"] == {"hardware_built": False,
                                 "fabrication_approved": False}
    assert index["note"].startswith("A view over committed artefacts")
