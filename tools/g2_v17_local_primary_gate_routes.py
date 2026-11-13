"""V17 local primary gate/control wiring, source-locked F.Cu pilot.

Only short, actual PAD-to-PAD connections in the existing 48-V power
cell are admitted. Does NOT route SW/VIN_P power copper, C5-U2 HB,
or the currently blocked GH_DRV (U2 to R4) high-side drive connection.
No claims of gate-loop inductance, SOA, EMC or manufacturing signoff.
"""
from __future__ import annotations
import json,math
from shapely.geometry import Point,LineString,box
import g2_v16_floorplan_screen as base
import g2_v17_compact_emc_screen as layout
import g2_v17_pgnd_power_route_screen as power
import g2_v17_route_conservative_signal as router
import g2_v17_bcu_short_control_bridges as bridge
import g2_v17_u2_fine_escape as gd

OUT=base.G/"g2_v17_local_primary_gate_routes_NOT_FOR_FAB.json"
# Explicit ownership only, no hot-loop trace, no bulk MOS power route.
# Format net, physical source ref/pin, sink ref/pin, copper width, max mm.
PAIRS=(
    ("GL_DRV","U2","10","R5","1",.20,6.0),
    ("GH","R4","2","QH","4",.35,6.0),
    ("GL","R5","2","QL","4",.35,6.0),
    ("GL","R5","2","R19","1",.25,7.0),
    ("HB","C5","1","D_BT","1",.25,8.0),
)
FORBIDDEN={"SW","VIN_P","PGND","VOUT","SEC1_A","SEC1_B","SEC2_A","SEC2_B",
           "SEC3_A","SEC3_B","SEC4_A","SEC4_B","GH_DRV"}

def _pad(pads,ref,pin,net):
    found=[p for p in pads if p["ref"]==ref and p["number"]==pin
           and p["net"]==net and p["layer"]==1]
    if len(found)!=1:
        raise ValueError(f"Unknown or ambiguous real {ref}.{pin}[{net}]")
    return found[0]

def generate():
    native,slots=base.load()
    pads=base.transferred_pad_records(native,layout.layout(native))
    g=power.generate()
    sig=json.loads(router.OUT.read_text("utf8"))
    bcu=json.loads(bridge.OUT.read_text("utf8"))
    fine=json.loads(gd.OUT.read_text("utf8"))
    if (sig["source_V15_sha"]!=base.sha(base.NATIVE)
        or sig["source_V17_sha"]!=base.sha(layout.OUT)
        or bcu["source_signal_sha"]!=base.sha(router.OUT)
        or fine["source_signal_sha"]!=base.sha(router.OUT)
        or fine["source_bcu_sha"]!=base.sha(bridge.OUT)
        or fine["source_pgnd_sha"]!=base.sha(power.OUT)):
        raise ValueError("Gate loop route input model drift")
    vias=[(v["net"],Point(v["x_mm"],v["y_mm"]),.35)
          for field in ("planned_via_in_pad_sites",
                        "additional_local_driver_reg_pgnd_and_Cout_stitches",
                        "control_U1_U2_PGND_via_sites",
                        "auxiliary_12V_S_and_12V_via_sites",
                        "auxiliary_pgnd_return_via_sites",
                        "control_U1_VCC12_feed_via_sites")
          for v in g[field]]
    vias += [(v["net"],Point(v["x_mm"],v["y_mm"]),.35)
             for x in bcu["bridges"] for v in x["via_sites"]]
    vias += [(v["net"],Point(v["x_mm"],v["y_mm"]),.35)
             for v in fine["via_sites"]]
    obstacles=[(p["net"],p["geom"],p["layer"]) for p in pads]
    for s in slots["slots"]:
        obstacles.append(("",box(s["x_min_mm"],s["y_min_mm"]+13,
                                  s["x_max_mm"],s["y_max_mm"]+13).buffer(.6),1))
    existing=[(x["net"],LineString(e))
              for x in sig["segments"] for e in x["segments"]]
    existing += [(x["net"],LineString(e)) for x in fine["routes"]
                 if x["layer"]=="F.Cu" for e in x["segments"]]
    for key in ("input_pgnd_to_QL_pad_target",
                "control_U2_pgnd9_to_exposed_pgnd11_link"):
        existing.append(("PGND",LineString(g[key]["path_mm"])))
    # The local net has an explicit short physical topology; rejecting
    # long detours is more important than minimizing unconnected count.
    routes=[]
    old_width,old_clear=router.WIDTH,router.MINCLEAR
    try:
        router.MINCLEAR=.20 # KiCad copper rule, not a global DRC exemption
        for net,src,pin,dst,dstpin,width,max_len in PAIRS:
            if net in FORBIDDEN:
                raise ValueError("Forbidden high-power/safety net "+net)
            a=tuple(_pad(pads,src,pin,net)["geom"].centroid.coords[0])
            b=tuple(_pad(pads,dst,dstpin,net)["geom"].centroid.coords[0])
            router.WIDTH=width
            path=router.find_path(a,b,net,obstacles,existing,vias,allow_grid=True)
            if path is None:
                raise ValueError(f"Failed safe short gate route {net} {src}->{dst}")
            length=sum(math.dist(u,v) for u,v in zip(path,path[1:]))
            if length>max_len or length>math.dist(a,b)*1.48+.5:
                raise ValueError(f"Gate path detour unacceptably long {net} {length:.2f}mm")
            steps=[[list(u),list(v)] for u,v in zip(path,path[1:])
                   if not router.close(u,v)]
            if not steps or any(router.path_collision(e,net,obstacles,existing,vias)
                                for e in steps):
                raise ValueError("Net/copper clearance regression in "+net)
            existing.extend((net,LineString(e)) for e in steps)
            routes.append({"net":net,"from":src+"."+pin,"to":dst+"."+dstpin,
                           "layer":"F.Cu","width_mm":width,"length_mm":round(length,5),
                           "segments":steps})
    finally:
        router.WIDTH,router.MINCLEAR=old_width,old_clear
    data={"status":"V17_LOCAL_GATE_PILOT_NATIVE_DRC_REQUIRED_NOT_FOR_FAB",
          "source_v15_sha":base.sha(base.NATIVE),
          "source_v17_sha":base.sha(layout.OUT),
          "source_pgnd_sha":base.sha(power.OUT),
          "source_signal_sha":base.sha(router.OUT),
          "source_bcu_sha":base.sha(bridge.OUT),
          "source_gd_sha":base.sha(gd.OUT),
          "route_count":len(routes),
          "excluded_power_and_high_side_blocked_nets":sorted(FORBIDDEN),
          "net_route_preview_only":True,
          "gate_loop_parasitics_extracted":False,
          "physical_emc_qualified":False,
          "native_drc_verified":False,
          "fab_release":False,
          "routes":routes}
    OUT.write_text(json.dumps(data,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"routes":len(routes),"segments":sum(len(r["segments"]) for r in routes),
                     "lengths_mm":{r["from"]+"-"+r["to"]:r["length_mm"] for r in routes}}))
    return data

if __name__=="__main__":
    generate()
