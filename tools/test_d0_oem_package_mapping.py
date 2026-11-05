"""Vendor-specific D0 bench package audit.

A clean KiCad ERC compares electrical pin names, not an actual orderable
part's body and numbering. These tests protect a real mis-assignment found
2026-11-05: TL431LP (TI TO-92) had an SOT-23 footprint.

The built-in KiCad TL431LP symbol labels pad 1 REF / pad 3 K, whereas TI's
LP physical numbering is 1 K / 3 REF.  This project's *specific* 2.5-V
shunt intentionally shorts REF and K, so their swap is electrically
equivalent; a later adjustable-feedback ECO is NOT allowed to assume that.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import make_d0_protection_board as board

TI_TL431_LP_PINS = {"1": "CATHODE", "2": "ANODE", "3": "REF"}
TI_TL431_LP_FOOTPRINT = "Package_TO_SOT_THT:TO-92_Inline"
SOT23_WRONG = "Package_TO_SOT_SMD:SOT-23"
DATA = board.ROOT / "pcb/d0_protection"


def test_ti_tl431lp_has_to92_footprint_and_safe_ref_k_short():
    parts = [part for part in board.parts() if part.ref == "U2"]
    assert len(parts) == 1
    part = parts[0]
    assert part.lib == "Reference_Voltage:TL431LP"
    assert part.value == "TL431LP"
    assert part.footprint == TI_TL431_LP_FOOTPRINT, (
        "LP is TI's 3-pin TO-92; SOT-23 would need the DBZ part and "
        "a differently numbered symbol, not a drop-in footprint"
    )
    assert set(part.nets) == set(TI_TL431_LP_PINS)
    # TI physical pin 1 = K, pin 3 = REF; KiCad library names are reversed.
    # In this fixed 2.500-V reference ONLY, both are intentionally shorted.
    assert part.nets["1"] == part.nets["3"] == "REF_2V5"
    assert part.nets["2"] == "PGND"


def test_generated_bom_keeps_vendor_package_and_pin_claim():
    with (DATA / "BOM.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    actual = [row for row in rows if row["Reference"] == "U2"]
    assert len(actual) == 1
    assert actual[0]["Value"] == "TL431LP"
    assert actual[0]["Footprint"] == TI_TL431_LP_FOOTPRINT
    assert "K=1, A=2, REF=3" in actual[0]["Note"]
    assert "DESIGN_PROPOSAL" in actual[0]["Provenance"]


def test_native_schematic_instance_not_just_the_library_default():
    text = (DATA / "d0_protection.kicad_sch").read_text(encoding="utf-8")
    # The library cache already had the correct TO-92 default but the
    # *placed U2 instance* overrode it to SOT-23. Inspect that instance.
    start = text.index('(lib_id "Reference_Voltage:TL431LP")')
    end = text.find("\n\t(symbol", start + 1)
    block = text[start: end if end != -1 else len(text)]
    assert '(property "Reference" "U2"' in block
    assert f'(property "Footprint" "{TI_TL431_LP_FOOTPRINT}"' in block
    assert f'(property "Footprint" "{SOT23_WRONG}"' not in block


def test_native_netlist_instance_matches_frozen_oem_package():
    text = (DATA / "d0_protection.net").read_text(encoding="utf-8")
    assert re.search(
        r'\(ref "U2"\)\s*\(value "TL431LP"\)\s*'
        r'\(footprint "' + re.escape(TI_TL431_LP_FOOTPRINT) + r'"\)',
        text,
    ), "regenerate the netlist after changing the native U2 footprint"
    assert not re.search(
        r'\(ref "U2"\)\s*\(value "TL431LP"\)\s*'
        r'\(footprint "' + re.escape(SOT23_WRONG) + r'"\)',
        text,
    )


def test_vendor_package_fix_does_not_claim_pcb_or_hardware_release():
    report = json.loads((DATA / "report.json").read_text(encoding="utf-8"))
    assert report["hardware_built"] is False
    assert report["fabrication_approved"] is False
    assert not list(DATA.glob("*.kicad_pcb")), "native PCB needs a separate DRC/DFM review"
