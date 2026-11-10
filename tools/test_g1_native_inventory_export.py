"""The read-only G1 capture summary must report what was captured, not guess.

``export_native_inventory.py`` opens the real board and cannot run in CI, but
its printed summary is plain arithmetic over the captured components.  The G1
export renumbers the excluded EN pull-up (R8 -> R6), so a summary that looks the
designator up and prints ``null`` reads like "the board lost its pull-up" when
the capture actually proves the opposite.  These tests pin the honest reading.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G1 = ROOT / "hardware/dcx_main/g1"
sys.path.insert(0, str(G1))
spec = importlib.util.spec_from_file_location(
    "g1_export_native_inventory", G1 / "export_native_inventory.py")
n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)

G1_CAPTURE = G1 / "g1_native_inventory_raw.json"
NOV6_CAPTURE = ROOT / "hardware/dcx_main/gen/native_inventory_raw.json"


def _components(path):
    return json.loads(path.read_text(encoding="utf-8"))["value"]["components"]


def test_renamed_pullup_is_reported_by_its_captured_designator():
    summary = n.summarize("dcx_main_board_g1_lr_repack.eprj2", "ab" * 32,
                          _components(G1_CAPTURE))
    assert summary["captured_components"] == 83
    # R8 does not exist under that designator after the excluded-part renumber.
    assert summary["r8_by_designator"] is None
    # ...and the two-flag-disabled row is what the gate then resolves to R8.
    assert summary["double_dnp_refs"] == ["R6"]
    assert summary["manufacturing_approved"] is False
    assert summary["board_sha256"] == "ab" * 32


def test_a_capture_that_still_has_r8_shows_its_real_flags():
    summary = n.summarize("dcx_main_board.eprj2", "cd" * 32,
                          _components(NOV6_CAPTURE))
    assert summary["r8_by_designator"] == {
        "add_into_bom": True, "add_into_pcb": True, "value": "1kΩ"}
    assert summary["double_dnp_refs"] == []


def test_partial_dnp_and_unreadable_flags_are_not_counted_as_dnp():
    # A flag that failed to read is not False; only an explicit False counts.
    components = [
        {"ref": "R8", "value": "10k", "add_into_bom": {"read_error": "x"},
         "add_into_pcb": False},
        {"ref": "R9", "value": "1k", "add_into_bom": False, "add_into_pcb": True},
    ]
    summary = n.summarize("board.eprj2", "ef" * 32, components)
    assert summary["double_dnp_refs"] == []
    assert summary["r8_by_designator"]["add_into_bom"] == {"read_error": "x"}
