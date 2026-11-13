"""KiCad V17 U2 0.5-mm-pitch gate-control breakout engineering trial.

GD1 escapes on F.Cu. GD2 exits the fine-pitch pad on F.Cu, then crosses
on B.Cu via two *ordinary through* vias. Never put a 0.70-mm via in U2.8
0.30-mm-high pad; never route either control signal through PGND/Kelvin.
This is a source-locked candidate, not manufacturing/EMC approval.
"""
from __future__ import annotations
import json, math
from shapely.geometry import Point, LineString, box
import g2_v16_floorplan_screen as base
import g2_v17_compact_emc_screen as layout
import g2_v17_pgnd_power_route_screen as power
import g2_v17_route_conservative_signal as signals
import g2_v17_bcu_short_control_bridges as bridge

OUT=base.G/"g2_v17_u2_gd1_gd2_layer_escape_NOT_FOR_FAB.json"
WIDTH=.20
CLEAR=.20
GUARD=.01
VIA_RADIUS=.35
VIA_DRILL=.30

def _pad(pads,ref,num,net):
    result=[p for p in pads if p["ref"]==ref and p["number"]==num
            and p["net"]==net and p["layer"]==1]
    if len(result)!=1:
        raise ValueError(f"Missing/ambiguous native {ref}.{num}[{net}]")
    return result[0]

def _xy(p):
    return tuple(float(v) for v in p["geom"].centroid.coords[0])

def _safe_segment(net,points,obstacles,tracks,vias,layer):
    line=LineString(points)
    if not (line.length>0 and
            1<line.bounds[0] and line.bounds[2]<154 and
            1<line.bounds[1] and line.bounds[3]<112):
        raise ValueError("Candidate escape extends outside safe PCB outline")
    # One expansion of the candidate trace covers its half-width plus the
    # actual same-layer clearance; no accidental double-counting.
    guard=line.buffer(WIDTH/2+CLEAR+GUARD,cap_style="round")
    for p in obstacles:
        if p["net"]==net:
            continue
        if p["layer"]==12 or (layer=="F.Cu" and p["layer"]==1) or (layer=="B.Cu" and p["layer"]==2):
            if guard.intersects(p["geom"]):
                raise ValueError(f"{net} {layer} crosses pad {p['ref']}.{p['number']}[{p['net']}]")
    for other,old,old_layer,old_width in tracks:
        if other==net or old_layer!=layer:
            continue
        if line.distance(old)<WIDTH/2+old_width/2+CLEAR+GUARD:
            raise ValueError(f"{net} {layer} crosses unlike-net copper track {other}")
    for via in vias:
        if via["net"]!=net and line.distance(Point(via["x_mm"],via["y_mm"]))<VIA_RADIUS+WIDTH/2+CLEAR+GUARD:
            raise ValueError(f"{net} {layer} crosses unlike-net via {via['net']} {via['ref']}")
    return line

def _safe_via(v,obstacles,tracks,vias):
    pt=Point(v["x_mm"],v["y_mm"])
    for p in obstacles:
        if p["net"]!=v["net"] and pt.buffer(VIA_RADIUS+CLEAR+GUARD).intersects(p["geom"]):
            raise ValueError(f"GD2 via intersects unlike-net pad {p['ref']}.{p['number']}")
    for other,old,layer,width in tracks:
        if other!=v["net"] and pt.distance(old)<VIA_RADIUS+width/2+CLEAR+GUARD:
            raise ValueError("GD2 through-via touches an unlike-net track "+other)
    for other in vias:
        if other["net"]!=v["net"] and pt.distance(Point(other["x_mm"],other["y_mm"]))<2*VIA_RADIUS+CLEAR+GUARD:
            raise ValueError("GD2 via touches existing "+other["net"])
    return True

def generate():
    native,slots=base.load()
    pads=base.transferred_pad_records(native,layout.layout(native))
    pg=power.generate()
    sg=json.loads(signals.OUT.read_text("utf8"))
    bg=json.loads(bridge.OUT.read_text("utf8"))
    if (sg["source_V15_sha"]!=base.sha(base.NATIVE) or
        sg["source_V17_sha"]!=base.sha(layout.OUT) or
        bg["source_signal_sha"]!=base.sha(signals.OUT) or
        bg["source_v17_sha"]!=base.sha(layout.OUT)):
        raise ValueError("Outdated GD1/GD2 source projection")
    all_vias=[v for key in ("planned_via_in_pad_sites",
                           "additional_local_driver_reg_pgnd_and_Cout_stitches",
                           "control_U1_U2_PGND_via_sites",
                           "auxiliary_12V_S_and_12V_via_sites",
                           "auxiliary_pgnd_return_via_sites",
                           "control_U1_VCC12_feed_via_sites")
                for v in pg[key]]
    all_vias += [v for x in bg["bridges"] for v in x["via_sites"]]
    tracks=[(r["net"],LineString(e),"F.Cu",r["width_mm"])
            for r in sg["segments"] for e in r["segments"]]
    tracks += [(r["net"],LineString(e),"B.Cu",r["width_mm"])
               for r in bg["bridges"] for e in r["segments"]]
    for name in ("input_pgnd_to_QL_pad_target",
                 "control_U2_pgnd9_to_exposed_pgnd11_link"):
        q=pg[name]
        tracks.append(("PGND",LineString(q["path_mm"]),"F.Cu",q["width_mm"]))
    # Keep actual board slots out of all top-layer escapes.
    keepouts=[box(s["x_min_mm"],s["y_min_mm"]+13,
                  s["x_max_mm"],s["y_max_mm"]+13).buffer(.6)
              for s in slots["slots"]]
    first=_xy(_pad(pads,"U2","7","GD1"))
    last=_xy(_pad(pads,"R9","1","GD1"))
    second=_xy(_pad(pads,"U2","8","GD2"))
    end=_xy(_pad(pads,"R10","1","GD2"))
    # Reviewed bend and fanout site, valid only for this source/layout hash.
    midx=61.17
    fan=(58.5,17.4)
    gd1=[first,(midx,first[1]),(midx,last[1]),last]
    gd2_front=[second,(57.2,second[1]),fan]
    gd2_back=[fan,end]
    via_sites=[{"ref":"U2_ESC_GD2","pad":"FANOUT","net":"GD2",
                "x_mm":fan[0],"y_mm":fan[1],"radius_mm":VIA_RADIUS,"drill_mm":VIA_DRILL},
               {"ref":"R10","pad":"1","net":"GD2",
                "x_mm":round(end[0],6),"y_mm":round(end[1],6),
                "radius_mm":VIA_RADIUS,"drill_mm":VIA_DRILL}]
    # Enforce the free fanout via is NOT inside U2's fine-pitch pin.
    u2pad=_pad(pads,"U2","8","GD2")
    if u2pad["geom"].buffer(.05).intersects(Point(*fan).buffer(VIA_RADIUS)):
        raise ValueError("GD2 through-via illegally placed in fine-pitch U2.8")
    if not _pad(pads,"R10","1","GD2")["geom"].buffer(.02).contains(Point(*end)):
        raise ValueError("GD2 end via detached from R10")
    for v in via_sites:
        _safe_via(v,pads,tracks,all_vias)
    # Each new line must be screened against all *other-net* new lines/vias;
    # no crossing is hidden by the fact that both are GD control functions.
    added=[]
    for net,layer,points in (("GD1","F.Cu",gd1),
                             ("GD2","F.Cu",gd2_front),
                             ("GD2","B.Cu",gd2_back)):
        for a,b in zip(points,points[1:]):
            seg=_safe_segment(net,(a,b),pads,tracks+added,all_vias+via_sites,layer)
            if any(seg.intersects(k) for k in keepouts):
                raise ValueError("GD control crosses magnetic slot keepout")
            added.append((net,seg,layer,WIDTH))
    route_entries=[{"net":"GD1","layer":"F.Cu","width_mm":WIDTH,
                    "segments":[[list(a),list(b)] for a,b in zip(gd1,gd1[1:])]},
                   {"net":"GD2","layer":"F.Cu","width_mm":WIDTH,
                    "segments":[[list(a),list(b)] for a,b in zip(gd2_front,gd2_front[1:])]},
                   {"net":"GD2","layer":"B.Cu","width_mm":WIDTH,
                    "segments":[[list(a),list(b)] for a,b in zip(gd2_back,gd2_back[1:])]}]
    result={"status":"U2_GD1_GD2_SOURCE_LOCKED_FINE_PITCH_TRIAL_NOT_FOR_FAB",
            "source_native_sha":base.sha(base.NATIVE),
            "source_layout_sha":base.sha(layout.OUT),
            "source_signal_sha":base.sha(signals.OUT),
            "source_bcu_sha":base.sha(bridge.OUT),
            "source_pgnd_sha":base.sha(power.OUT),
            "pad_pitch_mm":.5,
            "nominal_clearance_mm":CLEAR,
            "gd2_through_via_in_U2_pad":False,
            "routes":route_entries,"via_sites":via_sites,
            "native_drc_verified":False,"emc_signoff":False,"fab_release":False}
    OUT.write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"routes":len(route_entries),
        "segments":sum(len(r["segments"]) for r in route_entries),
        "vias":len(via_sites)},ensure_ascii=True))
    return result

if __name__=="__main__":
    generate()
