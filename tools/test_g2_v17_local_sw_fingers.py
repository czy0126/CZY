"""V17 approved-only local SW finger and low-current pickup pilots."""
import hashlib
import json
from collections import Counter

import pytest
import g2_v16_floorplan_screen as source
import g2_v17_compact_emc_screen as layout
import g2_v17_local_sw_fingers as sw
import g2_v17_remaining_powercell_handoff as handoff

G=source.G
PCB=G/"dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb"

def test_same_net_qh_fingers_are_strapped_locally_not_power_qualified():
    data=sw.generate()
    assert data["source_v15_sha"]==source.sha(source.NATIVE)
    assert data["source_layout_sha"]==source.sha(layout.OUT)
    assert [(x["from"],x["to"],x["width_mm"],x["function"]) for x in data["routes"]]==[
        ("QH.1","QH.2",.75,"same_device_finger_strap"),
        ("QH.2","QH.3",.75,"same_device_finger_strap"),
        ("QH.1","R18.2",.30,"low_current_sw_reference"),
        ("R18.2","C5.2",.20,"bootstrap_sw_reference")]
    assert [x["net"] for x in data["routes"]]==["SW"]*4
    assert [x["layer"] for x in data["routes"]]==["F.Cu"]*4
    assert [round(x["length_mm"],2) for x in data["routes"]]==[1.27,1.27,3.25,6.31]
    assert all(len(x["segments"])==1 for x in data["routes"])
    assert all(not x["current_rating_verified"] for x in data["routes"])
    assert not data["QH_to_QL_power_continuity_complete"]
    assert not data["half_bridge_hot_loop_current_qualified"]
    assert not data["bootstrap_sw_reference_emc_approved"]
    assert not data["native_drc_passed"] and not data["fab_release"]

def test_local_SW_physical_board_native_drc_progress_no_pgnd_regression():
    meta=json.loads((G/"g2_v17_real_kicad_native_build_NOT_FOR_FAB.json").read_text("utf8"))
    drc=json.loads((G/"g2_v17_KICAD_NATIVE_DRC_NOT_FOR_FAB.json").read_text("utf8"))
    assert hashlib.sha256(PCB.read_bytes()).hexdigest()==meta["saved_board_sha256"]
    assert meta["source_SW_local_fingers_sha256"]==source.sha(sw.OUT)
    assert meta["local_SW_same_device_fingers_and_reference_tracks"]==4
    assert meta["native_actual_tracks"]==165
    assert meta["native_actual_vias"]==359
    assert len(drc["unconnected_items"])==9
    assert Counter(v["type"] for v in drc["violations"])=={"clearance":2}
    desc=" ".join(q["description"] for e in drc["unconnected_items"] for q in e["items"])
    assert "[PGND]" not in desc
    assert "[SW]" in desc and "[VIN_P]" in desc and "[GH_DRV]" in desc
    assert not meta["real_fabrication_release"]

def test_unclosed_sw_current_path_is_not_hidden():
    data=handoff.generate()
    assert data["by_net"]["SW"]==3
    assert data["unconnected_total"]==9
    assert data["local_SW_finger_source_sha256"]==source.sha(sw.OUT)
    group=next(x for x in data["groups"] if x["group"]=="primary_switch_node")
    assert "3 SW" in group["do_not"]
    assert not data["whole_board_drc_green"]
    assert not data["fab_release"]

def test_wrong_V15_revision_is_not_accepted(monkeypatch):
    monkeypatch.setattr(source,"EXPECTED_V15_SHA256","0"*64)
    with pytest.raises(ValueError,match="Native V15 source changed"):
        sw.generate()
