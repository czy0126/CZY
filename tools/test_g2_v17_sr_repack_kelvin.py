"""SR Kelvin re-layout and current KiCad native DRC physical evidence.

The only accepted route for SEC_n A/B is a <=3.2 mm short single-layer
resistor-to-native-FET sense-pad stub; a long near-source power trace
is NOT a valid substitute. VD1_B/2_B are 0.20-mm F.Cu sense lines, not
switch-node current conductors. Any native DRC/geometry regression fails.
"""
from collections import Counter
import hashlib
import json
import math

import pytest
import g2_v16_floorplan_screen as native
import g2_v17_compact_emc_screen as layout
import g2_v17_pgnd_power_route_screen as ground
import g2_v17_route_conservative_signal as signal
import g2_v17_bcu_short_control_bridges as bcu
import g2_v17_u2_fine_escape as fine
import g2_v17_local_primary_gate_routes as gate
import g2_v17_short_sr_drain_kelvin as sr
import g2_v17_remaining_vdb as vdb

G=native.G
BOARD=G/"dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb"

def test_SR_sense_resistors_are_relocated_close_to_REAL_switched_FET_pads():
    n,_=native.load()
    xy=layout.layout(n)
    assert all(xy[f"R{k}"][1]==54.5 for k in range(28,36))
    report=layout.generate()
    assert report["cross_net_pad_clearance_fail_count"]==0
    assert not report["trial_nonbank_courtyard_pad_envelope_conflicts"]
    assert not report["slot_to_pad_conflicts"]
    assert not report["core_body_to_component_pad_failures"]
    assert report["real_native_associated_pads_checked"]==419
    assert report["board_envelope_candidate_mm"]==[155.,113.,16.]
    # Before moving R28..35 from y=68 to y=54.5, each resistor was
    # 10.8 mm from the same SR6 drain pad. 2.682 now is local.
    pads=native.transferred_pad_records(n,xy)
    for k in range(1,5):
        for side in ("A","B"):
            ref=f"R{28+2*(k-1)+(side=='B')}"
            srref=f"SR{k}{side}"
            net=f"SEC{k}_{side}"
            start=next(x for x in pads if x["ref"]==ref and x["number"]=="1" and x["net"]==net)
            endpoint=next(x for x in pads if x["ref"]==srref and x["number"]=="6" and x["net"]==net)
            assert start["geom"].centroid.distance(endpoint["geom"].centroid)<3.2


def test_all_8_source_locked_short_SEC_connections_avoid_hot_loop_and_other_nets():
    d=sr.generate()
    assert len(d["routes"])==8
    assert [x["net"] for x in d["routes"]]==[
        f"SEC{i}_{bank}" for i in range(1,5) for bank in ("A","B")]
    assert all(x["layer"]=="F.Cu" and x["width_mm"]==.20
               and len(x["segments"])==1 and x["actual_length_mm"]<3.2
               for x in d["routes"])
    assert d["source_v15_sha"]==native.sha(native.NATIVE)
    assert d["source_layout_sha"]==native.sha(layout.OUT)
    assert d["source_pgnd_sha"]==native.sha(ground.OUT)
    assert d["source_signal_sha"]==native.sha(signal.OUT)
    assert d["source_bcu_sha"]==native.sha(bcu.OUT)
    assert d["source_gd_sha"]==native.sha(fine.OUT)
    assert d["source_gate_sha"]==native.sha(gate.OUT)
    assert not d["real_sr_oem_pinout_confirmed"]
    assert not d["kelvin_loop_inductance_extracted"]
    assert not d["fab_release"]


def test_two_remaining_VD_B_driver_sense_routes_preserve_source_ownership():
    d=vdb.generate()
    assert [(x["net"],x["from"],x["to"]) for x in d["routes"]]==[
        ("VD1_B","U3.6","R29.2"),("VD2_B","U4.6","R31.2")]
    assert all(x["layer"]=="F.Cu" and x["width_mm"]==.20
               and 10<x["length_mm"]<17.5 for x in d["routes"])
    assert sum(len(x["segments"]) for x in d["routes"])==8
    assert d["source_sr_sha"]==native.sha(sr.OUT)
    assert d["source_v15_sha"]==native.sha(native.NATIVE)
    assert not d["kelvin_loop_emc_verified"]
    assert not d["fabrication_approved"]


def test_real_KiCad_pcb_and_current_DRC_all_SEC_and_VDB_connected_but_not_released():
    meta=json.loads((G/"g2_v17_real_kicad_native_build_NOT_FOR_FAB.json").read_text("utf8"))
    drc=json.loads((G/"g2_v17_KICAD_NATIVE_DRC_NOT_FOR_FAB.json").read_text("utf8"))
    assert hashlib.sha256(BOARD.read_bytes()).hexdigest()==meta["saved_board_sha256"]
    assert meta["native_actual_footprints"]==149
    assert meta["native_actual_footprint_pads"]==425
    assert meta["native_actual_tracks"]==165
    assert meta["native_actual_vias"]==359
    assert meta["short_SR_drain_Kelvin_track_count"]==8
    assert meta["short_SR_drain_Kelvin_longest_mm"]<3.2
    assert meta["completed_remaining_VD_B_track_count"]==8
    assert len(drc["unconnected_items"])==9
    c=Counter(x["type"] for x in drc["violations"])
    assert c=={}
    remain=" ".join(x["description"] for row in drc["unconnected_items"] for x in row["items"])
    assert not any("["+net+"]" in remain for net in
        ([f"SEC{i}_{side}" for i in range(1,5) for side in ("A","B")] +
         [f"VD{i}_B" for i in range(1,5)] +
         ["PGND","VOUT","GD1","GD2","GL","GL_DRV","VCC12"]))
    assert all("["+net+"]" in remain for net in ("SW","VIN_P","GH_DRV","HB","OC"))
    assert not meta["real_fabrication_release"]


def test_corrupted_locked_SR_input_sources_are_rejected(monkeypatch):
    monkeypatch.setattr(native,"EXPECTED_V15_SHA256","0"*64)
    with pytest.raises(ValueError,match="Native V15 source changed"):
        sr.generate()
    with pytest.raises(ValueError,match="Native V15 source changed"):
        vdb.generate()
