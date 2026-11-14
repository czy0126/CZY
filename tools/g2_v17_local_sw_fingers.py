"""V17 LOCAL SW finger ties and limited low-current switch references.

This intentionally does not connect QH to QL power devices, VIN_P, Cr
power capacitor, or the resonant transformer. Matching SW net names
does not establish a current-rated, low-inductance half-bridge hot loop.

The QH adjacent equal-net copper finger links are short pad-scale
0.75-mm copper bridges; the two separate R18/C5 tracks are *sense /
bootstrap SW references*, never power-current straps. Source-locked
to actual V15 pad numbers and all previously routed copper.
"""
from __future__ import annotations
import json,math
from shapely.geometry import Point,LineString,box
import g2_v16_floorplan_screen as base
import g2_v17_compact_emc_screen as layout
import g2_v17_pgnd_power_route_screen as power
import g2_v17_route_conservative_signal as router
import g2_v17_bcu_short_control_bridges as bcu
import g2_v17_u2_fine_escape as fine
import g2_v17_local_primary_gate_routes as gate
import g2_v17_short_sr_drain_kelvin as sr
import g2_v17_remaining_vdb as vdb

OUT=base.G/"g2_v17_local_SW_finger_reference_NOT_FOR_FAB.json"
# The two QH 1/2/3 finger links must not be reported as a qualified
# wide SW inter-device conductor. All are explicitly narrow local links.
PAIRS=(
 ("QH","1","QH","2",.75,1.6,"same_device_finger_strap"),
 ("QH","2","QH","3",.75,1.6,"same_device_finger_strap"),
 ("QH","1","R18","2",.30,3.6,"low_current_sw_reference"),
 ("R18","2","C5","2",.20,6.7,"bootstrap_sw_reference"),
)

def _point(pads,ref,pin):
    found=[q for q in pads if q["ref"]==ref and q["number"]==pin
           and q["net"]=="SW" and q["layer"]==1]
    if len(found)!=1:
        raise ValueError(f"Missing / ambiguous real SW pad {ref}.{pin}")
    return tuple(found[0]["geom"].centroid.coords[0])

def generate():
    n,slots=base.load()
    pads=base.transferred_pad_records(n,layout.layout(n))
    pg=power.generate()
    files={"signal":router.OUT,"bcu":bcu.OUT,"fine":fine.OUT,
           "gate":gate.OUT,"sr":sr.OUT,"vdb":vdb.OUT}
    models={k:json.loads(v.read_text("utf8")) for k,v in files.items()}
    sources={"source_v15_sha":base.sha(base.NATIVE),
             "source_layout_sha":base.sha(layout.OUT),
             "source_pgnd_sha":base.sha(power.OUT),
             "source_signal_sha":base.sha(router.OUT),
             "source_bcu_sha":base.sha(bcu.OUT),
             "source_fine_sha":base.sha(fine.OUT),
             "source_gate_sha":base.sha(gate.OUT),
             "source_sr_sha":base.sha(sr.OUT),
             "source_vdb_sha":base.sha(vdb.OUT)}
    for field,model,subkey in [
        ("source_v15_sha","vdb","source_v15_sha"),
        ("source_signal_sha","vdb","source_signal_sha"),
        ("source_sr_sha","vdb","source_sr_sha"),
        ("source_gate_sha","sr","source_gate_sha"),
        ("source_bcu_sha","fine","source_bcu_sha")]:
        if models[model][subkey]!=sources[field]:
            raise ValueError(f"SW local reference stale source: {field}")
    via_fields=("planned_via_in_pad_sites",
                "additional_local_driver_reg_pgnd_and_Cout_stitches",
                "control_U1_U2_PGND_via_sites",
                "auxiliary_12V_S_and_12V_via_sites",
                "auxiliary_pgnd_return_via_sites",
                "control_U1_VCC12_feed_via_sites")
    vias=[(v["net"],Point(v["x_mm"],v["y_mm"]),.35)
          for k in via_fields for v in pg[k]]
    vias.extend((v["net"],Point(v["x_mm"],v["y_mm"]),.35)
                for item in models["bcu"]["bridges"] for v in item["via_sites"])
    vias.extend((v["net"],Point(v["x_mm"],v["y_mm"]),.35)
                for v in models["fine"]["via_sites"])
    obstacles=[(q["net"],q["geom"],q["layer"]) for q in pads]
    for s in slots["slots"]:
        obstacles.append(("",box(s["x_min_mm"],s["y_min_mm"]+13,
                                  s["x_max_mm"],s["y_max_mm"]+13).buffer(.6),1))
    tracks=[(r["net"],LineString(edge)) for r in models["signal"]["segments"] for edge in r["segments"]]
    tracks.extend((r["net"],LineString(edge)) for r in models["fine"]["routes"]
                  if r["layer"]=="F.Cu" for edge in r["segments"])
    for k in ("gate","sr","vdb"):
        tracks.extend((r["net"],LineString(edge)) for r in models[k]["routes"] for edge in r["segments"])
    for k in ("input_pgnd_to_QL_pad_target","control_U2_pgnd9_to_exposed_pgnd11_link"):
        tracks.append(("PGND",LineString(pg[k]["path_mm"])))
    planned=[]
    oldw,oldc=router.WIDTH,router.MINCLEAR
    try:
        router.MINCLEAR=.25
        for src,pin,dst,dstpin,width,max_len,role in PAIRS:
            a=_point(pads,src,pin)
            b=_point(pads,dst,dstpin)
            length=math.dist(a,b)
            if not (0<length<max_len and 4<min(a[0],b[0]) and max(a[0],b[0])<70
                    and 3<min(a[1],b[1]) and max(a[1],b[1])<24):
                raise ValueError(f"Unqualified SW local path envelope {src}.{pin}->{dst}.{dstpin}")
            router.WIDTH=width
            if router.path_collision([a,b],"SW",obstacles,tracks,vias):
                raise ValueError(f"SW local path collides with foreign copper: {src}.{pin}->{dst}.{dstpin}")
            segment=[list(a),list(b)]
            tracks.append(("SW",LineString(segment)))
            planned.append({"net":"SW","from":src+"."+pin,"to":dst+"."+dstpin,
                            "function":role,"width_mm":width,"length_mm":round(length,5),
                            "layer":"F.Cu","segments":[segment],
                            "current_rating_verified":False})
    finally:
        router.WIDTH,router.MINCLEAR=oldw,oldc
    result={"status":"V17_LOCAL_SW_FINGERS_AND_SENSE_NOT_FOR_FAB",
            **sources,"routes":planned,
            "QH_to_QL_power_continuity_complete":False,
            "half_bridge_hot_loop_current_qualified":False,
            "bootstrap_sw_reference_emc_approved":False,
            "native_drc_passed":False,"fab_release":False}
    OUT.write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"routes":len(planned),"lengths_mm":[r["length_mm"] for r in planned],
                      "finger_straps":sum(r["function"]=="same_device_finger_strap" for r in planned),
                      "sensing_references":sum(r["function"]!="same_device_finger_strap" for r in planned)}))
    return result

if __name__=="__main__":
    generate()
