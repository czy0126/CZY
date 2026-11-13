"""Source-locked physical KiCad V17 DRC audit, never a manufacturing signoff.

Must fail if the board drifts from the recorded DRC: rerun KiCad 10 CLI and
record a new board hash after legitimate changes. Outstanding unconnected nets are NOT passed.
"""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
BOARD=G/"dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb"
D=G/"g2_v17_KICAD_NATIVE_DRC_NOT_FOR_FAB.json"
META=G/"g2_v17_real_kicad_native_build_NOT_FOR_FAB.json"

def test_native_kicad_board_binary_tracks_and_pad_inventory():
    assert BOARD.is_file() and BOARD.stat().st_size>100000
    m=json.loads(META.read_text("utf8"))
    assert m["saved_board_sha256"]==hashlib.sha256(BOARD.read_bytes()).hexdigest()
    assert m["native_actual_footprints"]==149
    assert m["native_actual_footprint_pads"]==419
    assert m["native_actual_copper_zones"]==7
    assert m["native_actual_vias"]==359
    assert m["auxiliary_pgnd_return_via_count"]==14
    assert m["control_U1_VCC12_feed_via_count"]==1
    assert m["U2_GD1_GD2_fine_escape_via_count"]==2
    assert m["short_BCu_control_bridge_count"]==3
    assert m["local_primary_gate_route_count"]==5
    assert m["local_primary_gate_track_segments"]==7
    assert m["native_actual_tracks"]==135
    assert m["native_actual_tracks"]>70
    assert m["native_edge_cut_shapes"]==13
    assert m["board_12_layers_real"] is True
    assert m["saved_zones_filled"] is True
    assert m["real_fabrication_release"] is False

def test_actual_kicad_native_drc_zero_shorts_but_not_zero_unconnected():
    r=json.loads(D.read_text("utf8"))
    assert r["kicad_version"]=="10.0.6"
    counts=Counter(v["type"] for v in r["violations"])
    assert counts=={"clearance":2}
    assert len(r["unconnected_items"])==24
    desc=" ".join(x["description"] for v in r["unconnected_items"] for x in v["items"])
    assert " [PGND]" not in desc
    assert " [VOUT]" not in desc
    assert " [SW]" in desc
    assert " [VIN_P]" in desc
    assert " [GD1]" not in desc and " [GD2]" not in desc
    assert " [VCC12]" not in desc
    assert " [GL]" not in desc and " [GL_DRV]" not in desc

def test_actual_unresolved_U2_is_not_silenced():
    r=json.loads(D.read_text("utf8"))
    for violation in r["violations"]:
        assert violation["type"]=="clearance"
        names=" ".join(p["description"] for p in violation["items"])
        assert "U2" in names
    assert all(not k for k in [
        json.loads(META.read_text("utf8"))["real_fabrication_release"],
        json.loads((G/"g2_v17_integrated_pgnd_vout_review_LOCKED_NOT_FOR_FAB.json").read_text("utf8"))["fab_release"]
    ])
