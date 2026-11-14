"""V17 five short primary-cell routes; no claim of power/EMC signoff."""
import hashlib
import json
import pytest

import g2_v16_floorplan_screen as source
import g2_v17_compact_emc_screen as layout
import g2_v17_pgnd_power_route_screen as ground
import g2_v17_route_conservative_signal as signals
import g2_v17_bcu_short_control_bridges as bridge
import g2_v17_u2_fine_escape as gd
import g2_v17_local_primary_gate_routes as gate


def test_five_short_primary_gate_connections_are_source_locked():
    d=gate.generate()
    assert d["source_v15_sha"]==source.sha(source.NATIVE)
    assert d["source_v17_sha"]==source.sha(layout.OUT)
    assert d["source_pgnd_sha"]==source.sha(ground.OUT)
    assert d["source_signal_sha"]==source.sha(signals.OUT)
    assert d["source_bcu_sha"]==source.sha(bridge.OUT)
    assert d["source_gd_sha"]==source.sha(gd.OUT)
    expected=[("GL_DRV","U2.10","R5.1"),
              ("GH","R4.2","QH.4"),
              ("GL","R5.2","QL.4"),
              ("GL","R5.2","R19.1"),
              ("HB","C5.1","D_BT.1")]
    assert [(r["net"],r["from"],r["to"]) for r in d["routes"]]==expected
    assert d["route_count"]==5
    assert sum(len(x["segments"]) for x in d["routes"])==7
    assert set(r["layer"] for r in d["routes"])=={"F.Cu"}
    assert all(.20<=r["width_mm"]<=.35 and r["length_mm"]<=8
               for r in d["routes"])
    assert all(r["net"] not in gate.FORBIDDEN for r in d["routes"])
    assert {"VIN_P","SW","GH_DRV"}.issubset(set(d["excluded_power_and_high_side_blocked_nets"]))
    assert d["net_route_preview_only"]
    assert not d["gate_loop_parasitics_extracted"]
    assert not d["physical_emc_qualified"]
    assert not d["native_drc_verified"]
    assert not d["fab_release"]


def test_actual_board_gate_increment_did_not_disconnect_pgnd_or_silence_manufacturing():
    meta=json.loads((source.G/"g2_v17_real_kicad_native_build_NOT_FOR_FAB.json").read_text("utf8"))
    drc=json.loads((source.G/"g2_v17_KICAD_NATIVE_DRC_NOT_FOR_FAB.json").read_text("utf8"))
    assert meta["local_primary_gate_route_count"]==5
    assert meta["local_primary_gate_track_segments"]==7
    assert meta["native_actual_footprints"]==149
    assert meta["native_actual_footprint_pads"]==419
    assert meta["native_actual_tracks"]==165
    assert meta["native_actual_vias"]==359
    assert len(drc["unconnected_items"])==9
    assert len(drc["violations"])==2
    desc=" ".join(i["description"] for row in drc["unconnected_items"] for i in row["items"])
    for net in ("PGND","GL","GL_DRV","GD1","GD2","VCC12"):
        assert "["+net+"]" not in desc
    for net in ("GH_DRV","SW","VIN_P","HB"):
        assert "["+net+"]" in desc
    assert not meta["real_fabrication_release"]


def test_source_lock_fail_closed_on_wrong_native_revision(monkeypatch):
    monkeypatch.setattr(source,"EXPECTED_V15_SHA256","0"*64)
    with pytest.raises(ValueError,match="Native V15 source changed"):
        gate.generate()
