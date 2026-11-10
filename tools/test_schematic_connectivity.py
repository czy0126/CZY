"""Connectivity reconstruction: read the live netlist instead of exporting it.

Every manufacturing export returns null on a ``--path``-opened native project,
so the only reader the editor still answers is its primitive database: wires
carry the editor's own net name, pins carry their schematic coordinate.  This
module turns that capture into a pin -> net map and is only allowed to be
evidence because the same code reproduces the Nov 6 editor export on the
reference board, pin for pin.
"""
import json

import pytest

import schematic_connectivity as mod


def _envelope(wires, components):
    return {"ok": True, "value": {
        "status": "CONNECTIVITY",
        "opened_by": "path",
        "project_name": "unit",
        "wires": wires,
        "components": components,
    }}


def test_a_pin_on_a_wire_endpoint_takes_that_wire_net():
    capture = _envelope(
        [{"line": [0, 0, 10, 0], "net": "VIN"}],
        [{"ref": "R1", "pins": [{"number": "1", "x": 0, "y": 0},
                                {"number": "2", "x": 10, "y": 0}]}])
    assert mod.reconstruct(capture)["refs"] == {"R1": {"1": "VIN", "2": "VIN"}}


def test_a_pin_on_no_wire_is_the_empty_net_and_is_named():
    capture = _envelope(
        [{"line": [0, 0, 10, 0], "net": "VIN"}],
        [{"ref": "R1", "pins": [{"number": "1", "x": 0, "y": 0},
                                {"number": "2", "x": 99, "y": 99}]}])
    out = mod.reconstruct(capture)
    assert out["refs"]["R1"] == {"1": "VIN", "2": ""}
    assert out["unmatched"] == [{"ref": "R1", "pin": "2", "x": 99.0, "y": 99.0}]


def test_two_nets_meeting_at_one_point_fails_closed():
    capture = _envelope(
        [{"line": [0, 0, 10, 0], "net": "VIN"},
         {"line": [0, 0, 0, 10], "net": "VOUT"}],
        [{"ref": "R1", "pins": [{"number": "1", "x": 0, "y": 0}]}])
    with pytest.raises(ValueError, match="two nets"):
        mod.reconstruct(capture)


def test_a_pin_inside_a_wire_segment_is_refused_not_guessed():
    capture = _envelope(
        [{"line": [0, 0, 10, 0], "net": "VIN"}],
        [{"ref": "R1", "pins": [{"number": "1", "x": 5, "y": 0}]}])
    with pytest.raises(ValueError, match="inside a wire"):
        mod.reconstruct(capture)


def test_a_wire_without_a_net_is_refused():
    capture = _envelope(
        [{"line": [0, 0, 10, 0], "net": None}],
        [{"ref": "R1", "pins": [{"number": "1", "x": 0, "y": 0}]}])
    with pytest.raises(ValueError, match="no net name"):
        mod.reconstruct(capture)


def test_a_capture_that_is_not_a_connectivity_read_is_refused():
    with pytest.raises(ValueError, match="CONNECTIVITY"):
        mod.reconstruct({"ok": True, "value": {"status": "INVENTORY"}})


def test_diff_names_the_renamed_designator_and_the_identical_rest():
    reference = {"R8": {"1": "VCC12", "2": "RUN"}, "R1": {"1": "DT", "2": "U1"}}
    candidate = {"R6": {"1": "VCC12", "2": "RUN"}, "R1": {"1": "DT", "2": "U1"}}
    out = mod.diff_netlists(reference, candidate)
    assert out["refs_only_in_reference"] == ["R8"]
    assert out["refs_only_in_candidate"] == ["R6"]
    assert out["changed"] == []
    assert out["identical"] is False


def test_diff_reports_a_changed_pin_net():
    out = mod.diff_netlists({"R1": {"1": "A", "2": "B"}}, {"R1": {"1": "A", "2": "C"}})
    assert out["changed"] == [{"ref": "R1", "pins": {"2": {"reference": "B", "candidate": "C"}}}]


REFERENCE_CAPTURE = mod.ROOT / "hardware/dcx_main/gen/reference_schematic_connectivity.json"
HISTORICAL_EXPORT = mod.ROOT / "hardware/dcx_main/gen/netlist_export_raw.json"
G1_CAPTURE = mod.ROOT / "hardware/dcx_main/g1/g1_schematic_connectivity_raw.json"
G1_NETLIST = mod.ROOT / "hardware/dcx_main/g1/g1_live_netlist.json"


def test_the_committed_reference_capture_reproduces_the_nov6_editor_export():
    """The whole method rests on this: same code, known-good board, same answer."""
    historical = json.loads(HISTORICAL_EXPORT.read_text(encoding="utf-8"))["value"]["refs"]
    rebuilt = mod.reconstruct(json.loads(REFERENCE_CAPTURE.read_text(encoding="utf-8")))
    assert rebuilt["refs"] == historical
    assert [(u["ref"], u["pin"], u["x"], u["y"]) for u in rebuilt["unmatched"]] == [
        ("D_CT1", "2", 1380.0, 1155.0), ("D_CT2", "2", 1760.0, 1155.0),
        ("D_CT3", "2", 2140.0, 1155.0), ("D_CT4", "2", 240.0, 1455.0),
        ("U2", "2", 565.0, 4330.0)]


def test_g1_live_netlist_differs_from_the_nov6_export_by_one_designator():
    """R8 was excluded from BOM/PCB and the export renumbered it to R6."""
    report = json.loads(G1_NETLIST.read_text(encoding="utf-8"))
    live = mod.reconstruct(json.loads(G1_CAPTURE.read_text(encoding="utf-8")))["refs"]
    historical = json.loads(HISTORICAL_EXPORT.read_text(encoding="utf-8"))["value"]["refs"]
    assert live["R6"] == {"1": "VCC12", "2": "RUN"}
    assert "R8" not in live
    assert report["diff"] == mod.diff_netlists(historical, live)
    assert report["diff"]["refs_only_in_reference"] == ["R8"]
    assert report["diff"]["refs_only_in_candidate"] == ["R6"]
    assert report["diff"]["changed"] == []
    assert report["manufacturing_approved"] is False
