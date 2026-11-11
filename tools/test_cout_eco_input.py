"""PR #92: OEM A720 desktop verification is not the high-voltage P0 release.

The 15-piece placement input is for the next native EasyEDA schematic/PCB ECO.
It must never claim the current single 0603 Cout became fifteen signed polymer
pads, or that F=2.4 mm is an OEM-approved solder-land pattern.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from cout_bank import spec_facts
import g2_board_keepout as K

PLACEMENT = ROOT / "hardware/dcx_main/g2/cout_a720_15part_eda_input.json"
REGISTRY = ROOT / "hardware/dcx_main/component_decision_register.json"
RFQ = ROOT / "hardware/dcx_main/performance_first_component_rfq.csv"


def source():
    return json.loads(PLACEMENT.read_text(encoding="utf-8"))


def test_oem_package_facts_match_15_source_locked_parts():
    d = source()
    o = d["part"]
    f = spec_facts()
    assert o["exact_mpn"] == "A720V477M2R5APE003"
    assert f["length_mm"] + .3 == pytest.approx(o["maximum_body_length_mm"])
    assert f["width_mm"] + .3 == pytest.approx(o["maximum_body_width_mm"])
    assert f["height_max_mm"] == pytest.approx(o["maximum_body_height_mm"])
    assert o["F_oem_terminal_dimension_mm"] == pytest.approx(
        [f["lead_pitch_mm"] - .1, f["lead_pitch_mm"] + .1])
    assert o["oem_pad_pitch_known"] is False
    assert o["land_pattern_approved"] is False
    assert o["solder_reflow_and_courtyard_approved"] is False
    assert d["status"].endswith("NOT_FOR_FAB")


def test_all_fifteen_unique_parts_planned_clear_of_existing_native_g1_pads():
    d = source()
    units = d["placement_proposal"]["units"]
    assert len(units) == 15
    assert {x["ref"] for x in units} == {f"Cout{i}" for i in range(1, 16)}
    native = K.read_source()  # checks actual EasyEDA .eprj2 SHA and 299-pad readback
    old = [x for x in native["pads"] if x.get("ref") == "Cout"]
    assert len(old) == 2  # ONE physical 0603 placeholder, not 15 polymers
    assert d["base_board"]["actually_connected_new_15_parts"] == 0
    for i, u in enumerate(units):
        x, y = u["proposed_centre_mm"]
        assert x == pytest.approx(14.0 + i * 8.2)
        assert y == pytest.approx(98.0)
        box = (x - 3.8, y - 2.3, x + 3.8, y + 2.3)
        assert box[0] >= 0 and box[2] <= 155 and box[1] >= 0 and box[3] <= 131
        # This is a *body to existing pad* gross collision veto, NOT copper or
        # courtyard/land-pattern release. Tracks, planes and terminal pads still
        # have to be designed in native EasyEDA.
        for p in native["pads"]:
            l, t, r, b = K.pad_bbox(p)
            assert r <= box[0] or box[2] <= l or b <= box[1] or box[3] <= t, (
                f"{u['ref']} outline overlaps existing {p.get('ref')}.{p.get('PadNumber')}"
            )
        assert u["net_positive"] == "VOUT"
        assert u["net_negative"] == "PGND"
        assert u["actual_native_footprint_added"] is False
        assert u["manufacturer_polarity_pin_map_approved"] is False
    assert d["placement_proposal"]["adjacent_body_gap_mm"] == pytest.approx(.6)
    assert d["placement_proposal"]["body_gap_is_NOT_manufacturing_courtyard"] is True


def test_verified_2p5v_model_candidate_must_fail_independent_4v_p0_rfq():
    d = source()
    rfq = list(csv.DictReader(RFQ.open(encoding="utf-8", newline="")))
    target = next(x for x in rfq if x["group"] == "Cout_bank_high_voltage")
    assert target["decision"] == "PENDING"
    assert ">=4V rated" in target["unlimited_cost_request"]
    assert "<=0.07mOhm" in target["unlimited_cost_request"]
    # This RFQ is generator-owned by tools/performance_first_design.py.
    # An actual P0 vendor selection has NOT happened; keep its view PENDING.
    assert target["supplier_mpn_or_custom_drawing"] == ""
    assert target["manufacturer_datasheet_or_signed_drawing"] == ""
    assert d["rfq_conflicts"]["high_voltage_pass"] is False
    assert d["rfq_conflicts"]["esr_target_pass"] is False
    assert d["rfq_conflicts"]["rated_2p5v_cannot_pass_by_increasing_parallel_count"] is True
    assert d["rfq_conflicts"]["min_no_interconnect_units_at_3mohm_0p07mohm"] == 43
    assert d["passes_native_eda"] is False
    assert d["passes_p0_high_voltage_rfq"] is False
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    c = next(x for x in reg["items"] if x["ref"] == "Cout")
    assert c["verified_mpn"] == "A720V477M2R5APE003"
    assert c["exact_part_datasheet_verified"] is True
    assert c["eda_footprint_verified"] is False
    assert c["supplier_rfq_high_voltage_target_met"] is False
    assert c["supplier_rfq_low_esr_target_met"] is False
    assert c["status"].startswith("PENDING_")
