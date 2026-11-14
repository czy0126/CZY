"""Complete two outstanding VD1_B/VD2_B sense-input tracks locally in V17.

R28..35 are relocated to y=54.5 mm. VD3_B and VD4_B are already
connected by the conservative source router. VD1_B/VD2_B take an
identical checked F.Cu corridor around existing 12-V return caps/vias,
rather than inserting extra through vias beneath the drivers.
This is a native DRC subject candidate, not Kelvin accuracy signoff.
"""
from __future__ import annotations
import json,math
from shapely.geometry import Point,LineString,box
import g2_v16_floorplan_screen as base
import g2_v17_compact_emc_screen as layout
import g2_v17_pgnd_power_route_screen as ground
import g2_v17_route_conservative_signal as signal
import g2_v17_bcu_short_control_bridges as bcu
import g2_v17_u2_fine_escape as fine
import g2_v17_local_primary_gate_routes as gate
import g2_v17_short_sr_drain_kelvin as sr

OUT=base.G/"g2_v17_remaining_VD_B_short_sense_NOT_FOR_FAB.json"
WIDTH=.20
CLEAR=.20

def _pad(pads,ref,pin,net):
    ps=[p for p in pads if p["ref"]==ref and p["number"]==pin
        and p["net"]==net and p["layer"]==1]
    if len(ps)!=1:raise ValueError("Unverified VD_B pad "+ref+"."+pin)
    return tuple(ps[0]["geom"].centroid.coords[0])

def generate():
    native,slot=base.load()
    pad=base.transferred_pad_records(native,layout.layout(native))
    pg=ground.generate()
    model={name:json.loads(path.read_text("utf8")) for name,path in
           (("signal",signal.OUT),("bcu",bcu.OUT),("fine",fine.OUT),
            ("gate",gate.OUT),("sr",sr.OUT))}
    shas={"source_v15_sha":base.sha(base.NATIVE),
          "source_layout_sha":base.sha(layout.OUT),
          "source_pgnd_sha":base.sha(ground.OUT),
          "source_signal_sha":base.sha(signal.OUT),
          "source_bcu_sha":base.sha(bcu.OUT),
          "source_fine_sha":base.sha(fine.OUT),
          "source_gate_sha":base.sha(gate.OUT),
          "source_sr_sha":base.sha(sr.OUT)}
    if model["sr"]["source_gate_sha"]!=shas["source_gate_sha"]:
        raise ValueError("Reloated SR Kelvin owner drift")
    vias=[(v["net"],Point(v["x_mm"],v["y_mm"]),.35)
          for key in ("planned_via_in_pad_sites",
                      "additional_local_driver_reg_pgnd_and_Cout_stitches",
                      "control_U1_U2_PGND_via_sites",
                      "auxiliary_12V_S_and_12V_via_sites",
                      "auxiliary_pgnd_return_via_sites",
                      "control_U1_VCC12_feed_via_sites")
          for v in pg[key]]
    vias += [(v["net"],Point(v["x_mm"],v["y_mm"]),.35)
             for x in model["bcu"]["bridges"] for v in x["via_sites"]]
    vias += [(v["net"],Point(v["x_mm"],v["y_mm"]),.35)
             for v in model["fine"]["via_sites"]]
    obstacles=[(x["net"],x["geom"],x["layer"]) for x in pad]
    for x in slot["slots"]:
        obstacles.append(("",box(x["x_min_mm"],x["y_min_mm"]+13,
                                  x["x_max_mm"],x["y_max_mm"]+13).buffer(.6),1))
    tracks=[(r["net"],LineString(e)) for r in model["signal"]["segments"]
            for e in r["segments"]]
    tracks += [(r["net"],LineString(e)) for r in model["fine"]["routes"]
               if r["layer"]=="F.Cu" for e in r["segments"]]
    tracks += [(r["net"],LineString(e)) for r in model["gate"]["routes"]
               for e in r["segments"]]
    tracks += [(r["net"],LineString(e)) for r in model["sr"]["routes"]
               for e in r["segments"]]
    for k in ("input_pgnd_to_QL_pad_target",
              "control_U2_pgnd9_to_exposed_pgnd11_link"):
        tracks.append(("PGND",LineString(pg[k]["path_mm"])))
    built=[]
    oldwidth,oldclear=signal.WIDTH,signal.MINCLEAR
    try:
        signal.WIDTH,signal.MINCLEAR=WIDTH,CLEAR
        for i in (1,2):
            net=f"VD{i}_B"
            start_ref=f"U{i+2}.6"
            end_ref=f"R{29+2*(i-1)}.2"
            a=_pad(pad,start_ref.split(".")[0],"6",net)
            b=_pad(pad,end_ref.split(".")[0],"2",net)
            path=signal.find_path(a,b,net,obstacles,tracks,vias,allow_grid=True)
            if path is None:raise ValueError("Cannot route existing driver VD_B without violations "+net)
            dist=sum(math.dist(u,v) for u,v in zip(path,path[1:]))
            if not (10.<dist<17.5 and dist<math.dist(a,b)*1.7):
                raise ValueError("VD_B high dv/dt sense loop detour too long "+str((net,dist)))
            for x,y in path:
                if not ((10+38*(i-1))<x<(34+38*(i-1)) and 44.8<y<55.2):
                    raise ValueError("VD_B left its local per-cell corridor "+net)
            segments=[[list(u),list(v)] for u,v in zip(path,path[1:])
                      if not signal.close(u,v)]
            if any(signal.path_collision(seg,net,obstacles,tracks,vias)
                   for seg in segments):
                raise ValueError("VD_B line violates pad/track/via clearances "+net)
            tracks.extend((net,LineString(seg)) for seg in segments)
            built.append({"net":net,"from":start_ref,"to":end_ref,
                          "layer":"F.Cu","width_mm":WIDTH,
                          "length_mm":round(dist,5),
                          "segments":segments})
    finally:
        signal.WIDTH,signal.MINCLEAR=oldwidth,oldclear
    result={"status":"V17_LOCAL_VD_B_SENSE_FCU_NEEDS_DRC_NOT_FOR_FAB",
            **shas,"routes":built,"source_locked":True,
            "kelvin_loop_emc_verified":False,"native_drc_verified":False,
            "fabrication_approved":False}
    OUT.write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"routed":len(built),
                      "lengths_mm":[r["length_mm"] for r in built],
                      "segments":sum(len(r["segments"]) for r in built)}))
    return result

if __name__=="__main__":
    generate()
