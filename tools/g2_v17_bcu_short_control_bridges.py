"""Short low-current B.Cu trial bridges on V17, never a fabrication signoff.

Each bridge is mapped by (real ref, real pad number, real native net).
Only RUN-independent low-voltage control nodes are allowed; no gate-driver
fine-pitch pins, switch node, primary hot loop or SR commutating copper.
Anaconda/Shapely generates; KiCad bundled Python consumes the locked JSON.
"""
from __future__ import annotations
import json, math
from pathlib import Path
from shapely.geometry import Point, LineString
import g2_v16_floorplan_screen as base
import g2_v17_compact_emc_screen as layout
import g2_v17_pgnd_power_route_screen as ground
import g2_v17_route_conservative_signal as router

G=base.G
OUT=G/"g2_v17_bcu_short_control_bridges_NOT_FOR_FAB.json"
SIGNAL=router.OUT
# Long OC (>57 mm), safety shutdown, and 0.5-mm-pitch GD1/GD2
# deliberately remain excluded pending local relayout or OEM engineering.
PAIRS=(("RT","U1","2","R2","1"),
       ("CS2","D_CT2","1","D_CT4","3"),
       ("OCM","R17","2","C11","2"))
VIA_R=.35
DRILL=.30
CLEAR=.20

def generate():
    native,slots=base.load()
    pads=base.transferred_pad_records(native,layout.layout(native))
    signal=json.loads(SIGNAL.read_text("utf8"))
    if signal["source_V15_sha"]!=base.sha(base.NATIVE) or signal["source_V17_sha"]!=base.sha(layout.OUT):
        raise ValueError("Signal/Floorplan source drift")
    copper=ground.generate()
    via_index=[(v["net"],Point(v["x_mm"],v["y_mm"]),VIA_R)
       for field in ("planned_via_in_pad_sites",
                     "additional_local_driver_reg_pgnd_and_Cout_stitches",
                     "control_U1_U2_PGND_via_sites",
                     "auxiliary_12V_S_and_12V_via_sites",
                     "auxiliary_pgnd_return_via_sites")
       for v in copper[field]]
    # B.Cu only: back-side pads and through-hole pads are physical blockers.
    obstacles=[(q["net"],q["geom"],1) for q in pads if q["layer"] in (2,12)]
    front_paths=[(r["net"],LineString(edge))
        for r in signal["segments"] for edge in r["segments"]]
    for name in ("input_pgnd_to_QL_pad_target",
                 "control_U2_pgnd9_to_exposed_pgnd11_link"):
        link=copper[name]
        front_paths.append(("PGND",LineString(link["path_mm"])))
    committed=[]
    out=[]
    for net,r1,p1,r2,p2 in PAIRS:
        ends=[]
        for ref,pin in ((r1,p1),(r2,p2)):
            matches=[q for q in pads if q["ref"]==ref and q["number"]==pin and q["net"]==net and q["layer"]==1]
            if len(matches)!=1:raise ValueError(f"nonunique projected pad {net} {ref}.{pin}")
            x,y=matches[0]["geom"].centroid.coords[0]
            if not (1.5<x<153.5 and 1.5<y<25):
                raise ValueError(f"B.Cu control bridge left top-control zone {net}")
            centre=Point(x,y)
            # The 0.70-mm through-via copper annulus must clear *both*
            # F.Cu/B.Cu native other-net pads, native PGND power vias and
            # every existing thin F.Cu signal trace, not only its own pad.
            aperture=centre.buffer(VIA_R+CLEAR+.01)
            forbidden=[q["ref"]+"."+str(q["number"]) for q in pads
                       if q["net"]!=net and q["layer"] in (1,2,12)
                       and aperture.intersects(q["geom"])]
            forbidden +=["existing via: "+other for other,pt,r in via_index
                         if other!=net and centre.distance(pt)<VIA_R+r+CLEAR+.01]
            forbidden +=["F.Cu trace: "+other for other,line in front_paths
                         if other!=net and aperture.intersects(line.buffer(.11))]
            if forbidden:
                raise ValueError(f"Bridge via fails real-pad screening {net} {ref}.{pin}: {forbidden[:5]}")
            ends.append({"ref":ref,"pad":pin,"net":net,"x_mm":round(x,6),"y_mm":round(y,6),
                         "radius_mm":VIA_R,"drill_mm":DRILL})
        a=(ends[0]["x_mm"],ends[0]["y_mm"])
        b=(ends[1]["x_mm"],ends[1]["y_mm"])
        path=router.find_path(a,b,net,obstacles,committed,via_index,allow_grid=True)
        if path is None:raise ValueError("No legal B.Cu route "+net)
        length=sum(math.dist(u,v) for u,v in zip(path,path[1:]))
        if length>20 or length>1.5*math.dist(a,b)+2:
            raise ValueError(f"Excessive sensitive B.Cu path {net} {length:.2f} mm")
        edges=[[list(u),list(v)] for u,v in zip(path,path[1:]) if not router.close(u,v)]
        if any(router.path_collision(edge,net,obstacles,committed,via_index) for edge in edges):
            raise ValueError("Fast layer screen and exact clearance disagree "+net)
        out.append({"net":net,"via_sites":ends,"segments":edges,
                    "length_mm":round(length,4),"width_mm":router.WIDTH,
                    "layer":"B.Cu"})
        committed.extend((net,LineString(edge)) for edge in edges)
        via_index.extend((net,Point(e["x_mm"],e["y_mm"]),VIA_R) for e in ends)
    result={"status":"3_SHORT_BCU_CONTROL_TRIAL_REQUIRES_NATIVE_DRC_NOT_FOR_FAB",
            "source_v15_sha":base.sha(base.NATIVE),
            "source_v17_sha":base.sha(layout.OUT),
            "source_signal_sha":base.sha(SIGNAL),
            "via_in_pad_vendor_approved":False,
            "emc_approved":False,"fab_release":False,
            "critical_long_oc_and_gd1_gd2_excluded":True,
            "bridges":out}
    OUT.write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"bridges":len(out),"via_count":sum(len(b["via_sites"]) for b in out),
       "edges":sum(len(b["segments"]) for b in out),
       "lengths_mm":{b["net"]:b["length_mm"] for b in out}}))
    return result

if __name__=="__main__":
    generate()
