"""Physical procurement BOM: one row for one real package, even multi-unit ICs."""
from __future__ import annotations

import csv
import json
import re
from dataclasses import replace

import pytest

import make_d0_protection_board as board


DATA = board.ROOT / "pcb/d0_protection"
HEF4093BT = "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"


def read_bom(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_190_unique_physical_parts_are_not_232_drawn_symbol_units():
    parts = board.parts()
    physical = board.physical_components(parts)
    assert len(parts) == 235
    assert len([p for p in parts if not p.ref.startswith("#")]) == 232
    assert len(physical) == 190
    assert len({p.ref for p in physical}) == 190
    assert all(p.unit >= 1 for p in physical)
    assert {p.ref for p in physical} == {
        p.ref for p in parts if not p.ref.startswith("#")
    }
    assert board.report(parts)["physical_parts"] == len(physical)


def test_native_generated_bom_matches_program_and_one_qty_per_package(tmp_path, monkeypatch):
    actual = read_bom(DATA / "BOM.csv")
    monkeypatch.setattr(board, "OUT", tmp_path)
    board.bom(board.parts())
    generated = read_bom(tmp_path / "BOM.csv")
    assert actual == generated
    assert len(actual) == 190
    assert len({row["Reference"] for row in actual}) == 190
    assert all(row["Qty"] == "1" for row in actual)
    assert actual[0]["Reference"] == "J1"
    assert next(x for x in actual if x["Reference"] == "U13")["Footprint"] == HEF4093BT


def test_multiunit_logic_package_is_counted_once_and_all_units_are_retained():
    ps = board.parts()
    for ref, expected_units in {
        "U3": 3, "U4": 3, "U5": 3,
        "U6": 5, "U7": 5, "U8": 5, "U9": 5,
        "U10": 5, "U11": 7, "U12": 3, "U13": 5, "U19": 5,
    }.items():
        units = [p.unit for p in ps if p.ref == ref]
        assert sorted(units) == list(range(1, expected_units + 1))
        assert len([p for p in board.physical_components(ps) if p.ref == ref]) == 1


def test_conflicting_units_cannot_silently_select_one_wrong_part():
    ps = board.parts()
    old = next(p for p in ps if p.ref == "U13")
    for mutation in (
        {"footprint": "Package_DIP:DIP-14_W7.62mm"},
        {"value": "UNREVIEWED_MPN"},
        {"lib": "4xxx:WRONG"},
        {"dnp": True},
        {"source": "UNREVIEWED"},
    ):
        with pytest.raises(ValueError, match="conflicting BOM"):
            board.physical_components(ps + [replace(old, unit=99, **mutation)])
    with pytest.raises(ValueError, match="duplicate schematic unit"):
        board.physical_components(ps + [old])


def test_nexperia_hef4093bt_is_so14_not_dip14_across_all_five_units():
    sch = board.parts()
    devices = [p for p in sch if p.ref == "U13"]
    assert len(devices) == 5
    assert all(p.lib == "4xxx:HEF4093B" for p in devices)
    assert all(p.value == "HEF4093BT" for p in devices)
    assert all(p.footprint == HEF4093BT for p in devices)
    assert [p.unit for p in devices] == [1, 2, 3, 4, 5]
    assert all(p.nets.get("14") == "V5" for p in devices if p.unit == 5)
    assert all(p.nets.get("7") == "PGND" for p in devices if p.unit == 5)


def test_placed_native_schematic_and_exported_netlist_use_vendor_package():
    schematic = (DATA / "d0_protection.kicad_sch").read_text(encoding="utf-8")
    token = '\n\t(symbol\n\t\t(lib_id "4xxx:HEF4093B")'
    chunks = schematic.split(token)
    assert len(chunks) == 6
    for unit, chunk in enumerate(chunks[1:], 1):
        part = chunk.split('\n\t(symbol\n', 1)[0]
        assert f'(unit {unit})' in part
        assert f'(property "Footprint" "{HEF4093BT}"' in part
        assert '(property "Footprint" "Package_DIP:DIP-14_W7.62mm"' not in part
    netlist = (DATA / "d0_protection.net").read_text(encoding="utf-8")
    assert re.search(
        r'\(ref "U13"\)\s*\(value "HEF4093BT"\)\s*'
        r'\(footprint "' + re.escape(HEF4093BT) + r'"\)',
        netlist,
    )


def test_committed_report_now_counts_physical_packages_without_fake_fab_claim():
    report = json.loads((DATA / "report.json").read_text(encoding="utf-8"))
    recomputed = board.report(board.parts())
    assert report["physical_parts"] == recomputed["physical_parts"] == 190
    assert report["part_instances"] == recomputed["part_instances"] == 235
    assert not report["hardware_built"]
    assert not report["fabrication_approved"]
