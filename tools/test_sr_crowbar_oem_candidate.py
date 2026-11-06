"""SR REG-crowbar Q41 procurement evidence; candidate is NOT hardware release.

Keep Q41's electrical nets and SOT-23 pads while replacing an open-ended
"30V MOSFET" procurement field with a real OEM-catalog part number.
Native schematic and PCB value text intentionally remain GENERIC until
a full schematic/assembly ECO, and the old RDS=1.5-ohm scenarios remain
conservative hypothetical calculations rather than claimed AO3400A data.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

import make_sr_fault_board as board

EVIDENCE = board.ROOT / "references/datasheets/ao3400a_oem_parameters.txt"
BOM = board.OUT / "BOM.csv"
SCHEMATIC = board.OUT / "sr_fault_validation.kicad_sch"
NETLIST = board.OUT / "sr_fault_validation.net"
PCB = board.OUT / "sr_fault_validation.kicad_pcb"
OEM_URL = "https://www.aosmd.com/products/mosfets/low-voltage-mosfets-12v-30v/ao3400a"


def test_reg_crowbar_candidate_is_sourced_and_existing_footprint_matches():
    q41 = next(p for p in board.parts() if p.ref == "Q41")
    assert q41.lib == "Transistor_FET:Q_NMOS_GSD"
    assert q41.footprint == "Package_TO_SOT_SMD:SOT-23"
    assert q41.nets == {"1": "RC_G", "2": "PGND", "3": "REG_CROW"}
    assert q41.mpn == "AO3400A"
    assert q41.mpn_source == EVIDENCE.relative_to(board.ROOT).as_posix()
    source = EVIDENCE.read_text(encoding="utf-8")
    assert OEM_URL in source
    assert "30 V" in source
    assert "48 milliohm" in source
    assert "1=G, 2=S, 3=D" in source


def test_physical_bom_has_exactly_one_q41_row_and_real_vendor_code():
    with BOM.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    q41 = [row for row in rows if row["Reference"] == "Q41"]
    assert len(q41) == 1
    assert q41[0]["MPN"] == "AO3400A"
    assert q41[0]["MPN_Source"] == EVIDENCE.relative_to(board.ROOT).as_posix()
    assert q41[0]["Footprint"] == "Package_TO_SOT_SMD:SOT-23"
    assert q41[0]["Qty"] == "1"
    assert q41[0]["DNP"] == ""
    # This is a factual procurement candidate, not a 25C/125C pulse SOA sign-off.
    assert "Rds(on)" in q41[0]["Note"]


def test_native_layout_is_still_an_unchanged_sot23_circuit():
    netlist = NETLIST.read_text(encoding="utf-8")
    assert re.search(
        r'\(ref "Q41"\)\s*\(value "NMOS 30V IDM>=3A"\)\s*'
        r'\(footprint "Package_TO_SOT_SMD:SOT-23"\)', netlist)
    schematic = SCHEMATIC.read_text(encoding="utf-8")
    assert '(property "Reference" "Q41"' in schematic
    assert '(property "Value" "NMOS 30V IDM>=3A"' in schematic
    pcb = PCB.read_text(encoding="utf-8")
    assert '(property "Reference" "Q41"' in pcb
    assert '(property "Value" "NMOS 30V IDM>=3A"' in pcb


def test_q41_is_not_counted_as_performance_or_fab_approval():
    summary = json.loads((board.OUT / "sr_fault_validation.json").read_text(encoding="utf-8"))
    assert summary["fabrication_approved"] is False
    assert summary["hardware_built"] is False
    assert summary["crowbar"]["worst_case"]["qualified"] is False if "qualified" in summary["crowbar"]["worst_case"] else True
    # AOS's 30A pulsed current and 48mohm @2.5V (25C) cannot qualify
    # 14.8 W short-pulse behaviour without a real fixture and thermal proof.
    assert summary["crowbar_pulse"]["fet_energy_j"] > 0


def test_q40_status_fet_has_an_exact_real_onsemi_order_code():
    q40 = next(p for p in board.parts() if p.ref == "Q40")
    assert q40.value == "2N7002"
    assert q40.mpn == "2N7002LT1G"
    assert q40.mpn_source == "references/datasheets/2n7002lt1g_onsemi_oem_parameters.txt"
    assert q40.nets == {"1": "FAULT_G", "2": "PGND", "3": "FAULT_N"}
    assert q40.footprint == "Package_TO_SOT_SMD:SOT-23"
    evidence = (board.ROOT / q40.mpn_source).read_text(encoding="utf-8")
    assert "https://www.onsemi.com/download/data-sheet/pdf/2n7002l-d.pdf" in evidence
    assert "pin 1 GATE, pin 2 SOURCE, pin 3 DRAIN" in evidence
    with BOM.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    ordered = [row for row in rows if row["Reference"] == "Q40"]
    assert len(ordered) == 1
    assert ordered[0]["MPN"] == "2N7002LT1G"
    assert ordered[0]["MPN_Source"] == q40.mpn_source
    assert ordered[0]["Qty"] == "1"
