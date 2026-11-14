"""V17 Agent-A signal routes: preserve source/EMC safety and real DRC evidence."""
import hashlib
import json
from collections import Counter

from shapely.geometry import box

import g2_v17_route_conservative_signal as signals
import g2_v17_bcu_short_control_bridges as bridges

G=signals.base.G

def test_grid_detour_avoids_other_net_copper_and_never_fabricates_copper():
    other=[("SW",box(13.,9.,17.,11.),1)]
    route=signals._grid_fallback((10.,10.),(20.,10.),"RT",other,[],[])
    assert route is not None
    assert route[0]==(10.,10.) and route[-1]==(20.,10.)
    assert len(route)>=3
    assert all(not signals.path_collision([a,b],"RT",other,[],[])
               for a,b in zip(route,route[1:]))

def test_critical_existing_signal_corridors_cannot_regress():
    r=json.loads(signals.OUT.read_text("utf8"))
    count=Counter(x["net"] for x in r["segments"])
    assert r["routed_signal_edge_count"]>=38
    assert count["SS"]>=1
    assert count["OCD"]>=3
    assert count["VCC12_S"]>=4
    assert count["VCC12"]>=2
    # Two supply nets have only the six explicitly screened local branches;
    # all switching, 100A output and primary-drive nets remain forbidden.
    assert not any(x["net"] in (signals.BLOCK-{"VCC12","VCC12_S"})
                   for x in r["segments"])
    assert not r["native_drc_verified"] and not r["fab_release"]

def test_short_bcu_plan_is_three_protected_low_current_nets_only():
    d=bridges.generate()
    assert [x["net"] for x in d["bridges"]]==["RT","CS2","OCM"]
    assert {x["layer"] for x in d["bridges"]}=={"B.Cu"}
    assert sum(len(x["via_sites"]) for x in d["bridges"])==6
    assert all(x["length_mm"]<=20 for x in d["bridges"])
    assert all(x["width_mm"]==signals.WIDTH for x in d["bridges"])
    assert all(all(s["net"]==b["net"] for s in b["via_sites"])
               for b in d["bridges"])
    assert not d["via_in_pad_vendor_approved"]
    assert not d["emc_approved"] and not d["fab_release"]
    assert d["critical_long_oc_and_gd1_gd2_excluded"]

def test_native_kicad_pcb_was_rebuilt_from_locked_source_and_drc_is_not_masked():
    board=G/"dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb"
    meta=json.loads((G/"g2_v17_real_kicad_native_build_NOT_FOR_FAB.json").read_text("utf8"))
    native=json.loads((G/"g2_v17_KICAD_NATIVE_DRC_NOT_FOR_FAB.json").read_text("utf8"))
    assert hashlib.sha256(board.read_bytes()).hexdigest()==meta["saved_board_sha256"]
    assert meta["native_actual_footprints"]==149
    assert meta["native_actual_footprint_pads"]==425
    assert meta["native_actual_vias"]==359
    assert meta["auxiliary_pgnd_return_via_count"]==14
    assert meta["control_U1_VCC12_feed_via_count"]==1
    assert meta["U2_GD1_GD2_fine_escape_via_count"]==2
    assert meta["U2_GD1_GD2_fine_escape_segments"]==6
    assert meta["native_actual_tracks"]==165
    assert meta["short_SR_drain_Kelvin_track_count"]==8
    assert meta["completed_remaining_VD_B_track_count"]==8
    assert meta["local_primary_gate_route_count"]==5
    assert meta["local_primary_gate_track_segments"]==7
    assert meta["short_BCu_control_bridge_count"]==3
    assert meta["short_BCu_control_via_count"]==6
    assert meta["native_actual_copper_zones"]==11
    assert meta["saved_zones_filled"] and not meta["real_fabrication_release"]
    # Source U2 grid-rounding was corrected to the OEM nominal 0.5mm pitch;
    # do not waive real mechanical clearances or remaining electrical opens.
    assert len(native["violations"])<=2
    assert all(x["type"]=="clearance" and
               any("U2" in q.get("description","") for q in x["items"])
               for x in native["violations"])
    assert len(native["unconnected_items"])<=9
    assert not any("[PGND]" in item.get("description","")
                   for entry in native["unconnected_items"] for item in entry["items"])
