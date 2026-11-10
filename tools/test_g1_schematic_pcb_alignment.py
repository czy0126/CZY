"""G1 native saved-board evidence: no "0 netlist errors" invented from a legacy map."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g1_schematic_pcb_alignment as G


def test_saved_g1_reopen_and_native_schematic_are_separate_provenance_sources():
    value = G.report()
    assert value["native_schematic_component_count"] == 83
    assert value["native_pcb_component_count"] == 77
    assert value["native_pcb_pad_count"] == 299
    assert value["native_pcb_placed_pad_count"] == 275
    assert value["native_pcb_anonymous_magnetic_pad_count"] == 24
    assert value["schematic_only_refs"] == ["CT", "R6", "T1", "T2", "T3", "T4"]
    assert value["pcb_only_refs"] == []
    assert value["unplaced_real_magnetic_footprint_refs"] == [
        "CT", "T1", "T2", "T3", "T4"]
    assert value["unplaced_designators_explicitly_double_dnp"] == ["R6"]
    assert value["historical_schematic_ref_renamed_or_missing"] == ["R8"]
    assert value["native_schematic_refs_not_in_legacy_export"] == ["R6"]
    assert value["anonymous_pad_matches_legacy_magnetic_net_multiset"] is True
    assert value["placed_pads_matching_legacy_netlist"] == 275
    assert value["placed_pads_mismatching_legacy_netlist"] == []
    assert value["native_drc"]["netlist_errors"] == 1
    assert value["native_drc"]["connection_errors"] == 206
    assert value["native_drc"]["physical_errors"] == 0
    assert value["current_schematic_netlist_reexported_from_same_board"] is False
    assert value["netlist_drc_error_root_cause_proven"] is False
    assert value["fabrication_approved"] is False


def test_g1_free_magnetic_pads_are_not_manufacturer_real_pads():
    _, schematic, pcb, drc = G.fail_if_bad_native_capture()
    legacy = G.doc(G.OLD_NETLIST)["value"]["refs"]
    free = [x for x in pcb["pads"] if not x.get("ref")]
    damaged = copy.deepcopy(pcb["pads"])
    for p in damaged:
        if not p.get("ref"):
            p["Net"] = "FABRICATED_NET"
            break
    bad = G.compare(schematic["components"], pcb["components"], damaged,
                    legacy, drc["raw"])
    assert bad["anonymous_pad_matches_legacy_magnetic_net_multiset"] is False
    assert bad["detected_data_disagreements"]
    assert bad["fabrication_approved"] is False
    assert len(free) == 24


def test_legacy_pin_net_mismatch_cannot_go_unreported():
    _, schematic, pcb, drc = G.fail_if_bad_native_capture()
    legacy = G.doc(G.OLD_NETLIST)["value"]["refs"]
    changed = copy.deepcopy(pcb["pads"])
    for p in changed:
        if p.get("ref") == "U2" and str(p.get("PadNumber")) == "1":
            p["Net"] = "UNSAFE_DIFFERENT_NET"
            break
    result = G.compare(schematic["components"], pcb["components"], changed,
                       legacy, drc["raw"])
    assert result["placed_pads_mismatching_legacy_netlist"]
    assert result["fabrication_approved"] is False


def test_matching_schematic_legacy_export_is_not_real_netlist_erc_pass():
    actual = G.report()
    assert actual["placed_pads_mismatching_legacy_netlist"] == []
    assert actual["native_drc"]["netlist_errors"] != 0
    assert actual["current_schematic_netlist_reexported_from_same_board"] is False
    assert G.doc(G.OUT) == actual


def test_unknown_pcb_pad_ref_and_duplicate_schematic_designator_fail():
    _, sch, pcb, drc = G.fail_if_bad_native_capture()
    legacy = G.doc(G.OLD_NETLIST)["value"]["refs"]
    with_unknown = copy.deepcopy(pcb["pads"])
    with_unknown[0]["ref"] = "NOT_AN_ACTUAL_PCB_COMPONENT"
    try:
        G.compare(sch["components"], pcb["components"], with_unknown, legacy, drc["raw"])
    except ValueError as exc:
        assert "has no placed component" in str(exc)
    else:
        raise AssertionError("unknown placed pad accepted")
    duplicate = sch["components"] + [sch["components"][0]]
    try:
        G.compare(duplicate, pcb["components"], pcb["pads"], legacy, drc["raw"])
    except ValueError as exc:
        assert "Duplicate native schematic" in str(exc)
    else:
        raise AssertionError("duplicate schematic designator accepted")
