"""V17 U2 fine-pitch F/B escape is source locked and DRC-gated."""
import json
import math

import pytest
from shapely.geometry import Point, box

import g2_v16_floorplan_screen as source
import g2_v17_compact_emc_screen as layout
import g2_v17_route_conservative_signal as signal
import g2_v17_bcu_short_control_bridges as bridge
import g2_v17_pgnd_power_route_screen as ground
import g2_v17_u2_fine_escape as escape


def test_source_locked_0p5_pitch_escape_preserves_separate_signal_nets():
    actual=escape.generate()
    assert actual["source_native_sha"]==source.sha(source.NATIVE)
    assert actual["source_layout_sha"]==source.sha(layout.OUT)
    assert actual["source_signal_sha"]==source.sha(signal.OUT)
    assert actual["source_bcu_sha"]==source.sha(bridge.OUT)
    assert actual["source_pgnd_sha"]==source.sha(ground.OUT)
    assert actual["nominal_clearance_mm"]==.20
    assert actual["pad_pitch_mm"]==.5
    assert not actual["gd2_through_via_in_U2_pad"]
    assert [r["net"] for r in actual["routes"]]==["GD1","GD2","GD2"]
    assert [r["layer"] for r in actual["routes"]]==["F.Cu","F.Cu","B.Cu"]
    assert sum(len(r["segments"]) for r in actual["routes"])==6
    assert all(r["width_mm"]>=.20 for r in actual["routes"])
    assert len(actual["via_sites"])==2
    assert {x["net"] for x in actual["via_sites"]}=={"GD2"}
    assert {x["ref"] for x in actual["via_sites"]}=={"U2_ESC_GD2","R10"}
    assert not actual["native_drc_verified"]
    assert not actual["emc_signoff"]
    assert not actual["fab_release"]


def test_fine_pitch_u2_gd2_through_via_is_outside_the_actual_small_pad():
    native,_=source.load()
    pads=source.transferred_pad_records(native,layout.layout(native))
    gd2=next(x for x in pads if x["ref"]=="U2" and x["number"]=="8" and x["net"]=="GD2")
    gd1=next(x for x in pads if x["ref"]=="U2" and x["number"]=="7" and x["net"]=="GD1")
    pitch=gd2["geom"].centroid.distance(gd1["geom"].centroid)
    assert pitch==pytest.approx(.5,abs=.002)
    assert gd2["geom"].area<.30 # Too small for 0.70-mm through via.
    d=json.loads(escape.OUT.read_text("utf8"))
    via=next(v for v in d["via_sites"] if v["ref"]=="U2_ESC_GD2")
    assert not gd2["geom"].intersects(Point(via["x_mm"],via["y_mm"]).buffer(via["radius_mm"]))
    assert via["drill_mm"]==.30
    assert via["radius_mm"]==.35


def test_escape_preflight_rejects_unlike_net_copper_and_via_shorts():
    obstacle=[{"ref":"Q1","number":"1","net":"SW",
               "layer":1,"geom":box(13,9,15,11)}]
    with pytest.raises(ValueError,match="crosses pad"):
        escape._safe_segment("GD1",((10,10),(20,10)),obstacle,[],[],"F.Cu")
    nearvia={"ref":"X","pad":"1","net":"GD2","x_mm":14,
             "y_mm":10,"radius_mm":.35,"drill_mm":.30}
    with pytest.raises(ValueError,match="unlike-net pad"):
        escape._safe_via(nearvia,obstacle,[],[])
    wrongnet={"ref":"U2","pad":"7","net":"GD2","x_mm":14,
              "y_mm":10,"radius_mm":.35,"drill_mm":.30}
    with pytest.raises(ValueError,match="unlike-net"):
        escape._safe_via(wrongnet,obstacle,[],[])


def test_kicad_native_drc_has_no_new_gd_or_pgnd_open_items():
    d=json.loads((source.G/"g2_v17_KICAD_NATIVE_DRC_NOT_FOR_FAB.json").read_text("utf8"))
    m=json.loads((source.G/"g2_v17_real_kicad_native_build_NOT_FOR_FAB.json").read_text("utf8"))
    netdescs=" ".join(i["description"] for x in d["unconnected_items"] for i in x["items"])
    assert all("["+net+"]" not in netdescs for net in ("GD1","GD2","VCC12","PGND"))
    assert len(d["unconnected_items"])==13
    assert len(d["violations"])==2
    assert m["native_actual_vias"]==359
    assert m["native_actual_tracks"]==161
    assert m["control_U1_VCC12_feed_via_count"]==1
    assert m["U2_GD1_GD2_fine_escape_segments"]==6
    assert not m["real_fabrication_release"]
