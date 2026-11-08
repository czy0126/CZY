"""Check committed editable KiCad SR bias concept against OEM pin table.

This parser validates label-to-pin connectivity in the native .kicad_sch
*without* pretending it ran KiCad ERC/DRC. Physical footprints for TPS26630
RGE24 and CSD19537Q3T are intentionally blank and block fabrication.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import make_d0_protection_board as d0
import tps26630_bias_design as spec

SCH = spec.FOLDER / "native/tps26630_sr_bias_concept.kicad_sch"
PRO = spec.FOLDER / "native/tps26630_sr_bias_concept.kicad_pro"
REFMAP = {
    "RUV_TOP": "R1", "RUV_MID": "R2", "ROV_BOT": "R3",
    "RILIM": "R4", "R_EN_SER": "R5", "R_EN_PD": "R6",
    "CDVDT": "C1", "CIN": "C2", "COUT_MODEL": "C3",
    "J_IN": "J1", "J_OUT": "J2", "J_CTRL": "J3",
}


def _locations() -> dict:
    src = SCH.read_text(encoding="utf-8")
    labels = {}
    for m in re.finditer(r'\(label "([^"]+)" \(at ([-\d.]+) ([-\d.]+) 0\)', src):
        loc = (round(float(m.group(2)), 3), round(float(m.group(3)), 3))
        labels.setdefault(loc, set()).add(m.group(1))
    ncs = set()
    for m in re.finditer(r'\(no_connect \(at ([-\d.]+) ([-\d.]+)\)', src):
        ncs.add((round(float(m.group(1)), 3), round(float(m.group(2)), 3)))
    refs = {}
    for m in re.finditer(r'\(symbol \(lib_id "([^"]+)"\)', src):
        block = src[m.start():d0.block_end(src, m.start())]
        ref_m = re.search(r'\(property "Reference" "([^"]+)"', block)
        at_m = re.search(r'\(at ([-\d.]+) ([-\d.]+) 0\)', block)
        if not ref_m or not at_m:
            raise AssertionError("native symbol has missing reference or location")
        ref = ref_m.group(1)
        if ref in refs:
            raise AssertionError(f"duplicate component {ref}")
        embedded = d0.extract_symbol(SCH, m.group(1))
        tips = d0.pin_tips(embedded)
        number_list = re.findall(r'\(pin "([^"]+)" \(uuid "', block)
        if set(number_list) != set(tips):
            raise AssertionError(f"{ref}: symbol pin/instance list mismatch")
        x, y = float(at_m.group(1)), float(at_m.group(2))
        refs[ref] = {
            n: (round(x + p[0], 3), round(y - p[1], 3))
            for n, p in tips.items()
        }
    return {"refs": refs, "labels": labels, "no_connect": ncs, "src": src}


def test_s_expression_is_balanced_and_has_native_project():
    source = SCH.read_text(encoding="utf-8")
    assert source.startswith("(kicad_sch")
    assert d0.block_end(source, 0) == len(source.rstrip())
    assert 'NOT_FOR_FAB' in source
    meta = json.loads(PRO.read_text(encoding="utf-8"))
    assert meta["meta"]["filename"] == PRO.name
    uid = re.search(r'\(uuid "([^"]+)"\)', source).group(1)
    assert meta["sheets"][0][0] == uid


def test_all_three_oem_components_have_exclusively_expected_pin_nets():
    d = _locations()
    assert set(d["refs"]) >= {"U1", "Q1", "Q2"}
    for (ref, p), net in spec.EXPECTED.items():
        sch_pin = "25" if (ref, p) == ("U1", "EP") else p
        at = d["refs"][ref][sch_pin]
        if net in {"NC", "FLOAT"}:
            assert at in d["no_connect"], (ref, p, at)
        else:
            assert net in d["labels"].get(at, set()), (ref, p, net, at)
    assert len(spec.EXPECTED) == 36


def test_bias_native_is_not_the_unsafe_old_bias_cut():
    d = _locations()
    for old in ("R57", "Q54", "Q50", "Q51", "Q55"):
        assert old not in d["refs"]
    assert "C3" in d["refs"]
    assert "(dnp yes)" in d["src"]
    assert "VDD_SR" in d["src"]


def test_enable_and_analog_divider_connect_as_drawn():
    d = _locations()
    wanted = {
        "RUV_TOP": {"1": "VIN_SYS", "2": "UVLO"},
        "RUV_MID": {"1": "UVLO", "2": "OVP"},
        "ROV_BOT": {"1": "OVP", "2": "PGND"},
        "RILIM": {"1": "ILIM", "2": "PGND"},
        "CDVDT": {"1": "DVDT", "2": "PGND"},
        "R_EN_SER": {"1": "ENABLE_5V", "2": "SHDN"},
        "R_EN_PD": {"1": "SHDN", "2": "PGND"},
        "CIN": {"1": "VIN_SYS", "2": "PGND"},
    }
    for ref, nets in wanted.items():
        for pin, expected in nets.items():
            at = d["refs"][REFMAP[ref]][pin]
            assert expected in d["labels"].get(at, set()), (ref, pin, expected, at)


def test_no_vendor_footprint_has_been_falsely_approved():
    source = SCH.read_text(encoding="utf-8")
    for lib in ("SR_Bias:TPS26630_RGE24", "SR_Bias:CSD19537Q3"):
        # The target OEM landing pattern requires physical vendor review.
        assert f'(lib_id "{lib}")' in source
    # Both custom components have blank Footprint properties (the symbol's
    # cached library footprint is also blank). Never claim ERC/PCB signoff.
    found = {}
    for m in re.finditer(r'\(symbol \(lib_id "([^"]+)"\)', source):
        block = source[m.start():d0.block_end(source, m.start())]
        reference = re.search(r'\(property "Reference" "([^"]+)"', block)
        if reference is not None:
            found[reference.group(1)] = block
    for ref in ("U1", "Q1"):
        assert ref in found
        assert '(property "Footprint" ""' in found[ref], ref

def test_native_annotation_is_numeric_and_functional_role_mapping_is_complete():
    import csv
    records = list(csv.DictReader((SCH.parent / "native_reference_map.csv").open(encoding="utf-8")))
    assert {x["functional_ref"]: x["native_ref"] for x in records} == REFMAP
    d = _locations()
    assert len({x["native_ref"] for x in records}) == len(records)
    for alias, ref in REFMAP.items():
        assert ref in d["refs"] and alias not in d["refs"], (alias, ref)
        assert re.fullmatch(r"[RCJ]\d+", ref), ref
    for ref in d["refs"]:
        if not ref.startswith("#"):
            assert re.fullmatch(r"[UQRCJ]\d+", ref), ref
