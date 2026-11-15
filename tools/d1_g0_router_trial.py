"""Native KiCad G0 27-pair route trial on 154-item logical board.

Source must be real native board (DRC=0 physical, 27 opens).
This is a routing feasibility experiment, NOT manufacturing qualified copper.
No fab/48V energized claim, even if final DRC comes back clean.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
import pcbnew as pcb
import d1_g0_integrated_native_board as base

OUT=base.OUT
STEM="d1_g0_27_open_route_TRIAL_NOT_FOR_FAB"
BOARD=OUT/(STEM+".kicad_pcb")
DRC=OUT/(STEM+"_native_drc.json")
RECEIPT=OUT/(STEM+"_receipt.json")

# net,start,end, waypoint sequence, copper width mm, optional start-via,
# optional end-via. The primary 3:1:1 winding terminals are LOGICAL, not OEM.
# If waypoints are needed across Edge.Cuts slots (y22..44), choose a corridor
# between slots; all other secondary runs stay y>44.
SPECS=[
 ("VOUT",(36.7195,74.54904),(34.,46.75),(),.6,None,None),
 ("VOUT",(72.,46.75),(75.30023,72.00016),(),.6,None,None),
 ("VOUT",(110.,46.75),(106.08122,74.55096),(),.6,None,None),
 ("VOUT",(133.679039,74.55096),(148.,46.75),(),.6,None,None),
 ("CT_LR",(29.500321,6.999138),(87.,37.),((29.500321,2.5),(85.5,2.5),(85.5,37.)),.6,None,None),
 ("PRI_T1",(3.,46.75),(20.501101,6.999138),((3.,45.2),(12.,45.2),(12.,19.5)),.6,None,None),
 ("HB",(44.299620,17.999880),(52.499258,18.0),((45.0,16.7),(50.1,16.7)),.20,None,(50.1,18.0)),
 ("SW",(43.753518,12.001160),(52.499258,19.0),((42.,20.5),(49.,21.2)),.20,None,(51.5,20.6)),
 ("SW",(55.097692,4.249078),(47.363374,9.750718),(),.65,None,None),
 ("VIN_P",(50.799086,13.499659),(48.000914,6.354738),(),.65,None,None),
 ("SEC3_B",(100.769915,54.500838),(113.,46.75),(),.25,None,None),
 ("SEC4_A",(128.770379,54.500898),(145.,46.75),((128.770379,45.5),(145.,45.5)),.25,None,None),
 ("SEC2_A",(52.768499,54.500838),(69.,46.75),((52.768499,45.5),(69.,45.5)),.25,None,None),
 ("GH_DRV",(46.246889,14.000507),(52.499258,18.5),((46.246889,15.2),(53.,15.2)),.20,None,(51.25,19.5)),
 ("GH",(42.247298,12.001160),(47.753109,14.000507),((42.,13.),(48.5,13.)),.20,None,None),
 ("CS1",(103.,33.),(95.999010,19.77484),((101.5,33.),(101.5,19.5)),.25,None,None),
 ("SEC2_B",(75.,46.75),(62.768975,54.500838),(),.25,None,None),
 ("SEC3_A",(90.769440,54.500838),(107.,46.75),((90.769440,45.5),(107.,45.5)),.25,None,None),
 ("SEC1_A",(14.770100,54.500838),(31.,46.75),((14.770100,45.5),(31.,45.5)),.25,None,None),
 ("OC",(76.633755,13.706281),(134.247880,17.000180),(),.20,(76.633755,13.0),None),
 ("CS2",(103.001039,18.949820),(103.,37.),((104.5,19.5),(104.5,37.)),.25,None,None),
 ("PRI_34",(82.,46.75),(117.,46.75),((82.,45.2),(117.,45.2)),.5,None,None),
 ("SEC4_B",(138.770855,54.500898),(151.,46.75),(),.25,None,None),
 ("CR_CT",(40.699871,6.998882),(87.,33.),((40.699871,2.5),(88.5,2.5),(88.5,33.)),.5,None,None),
 ("PRI_12",(6.,46.75),(41.,46.75),((6.,45.2),(41.,45.2)),.5,None,None),
 ("SEC1_B",(37.,46.75),(24.770575,54.500838),(),.25,None,None),
 ("PRI_23",(44.,46.75),(79.,46.75),((44.,45.2),(79.,45.2)),.5,None,None),
]
# Every mechanical through-via spans 12 layers; vias in SMD pads are prototype
# ONLY and need plugged/capped manufacturer validation or moved off pad.
LAYERS=(pcb.In1_Cu,pcb.In2_Cu,pcb.In3_Cu,pcb.In4_Cu,pcb.In5_Cu,
        pcb.In6_Cu,pcb.In7_Cu,pcb.In8_Cu,pcb.In9_Cu,pcb.In10_Cu,pcb.B_Cu)

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def v(pt):return pcb.VECTOR2I(pcb.FromMM(pt[0]),pcb.FromMM(pt[1]))
def distance(p,q):return math.dist(p,q)

def track(board,net,layer,a,b,width):
    if distance(a,b)<1e-5:return
    t=pcb.PCB_TRACK(board)
    t.SetNet(net);t.SetLayer(layer);t.SetWidth(pcb.FromMM(width))
    t.SetStart(v(a));t.SetEnd(v(b));board.Add(t)

def via(board,net,pt,width):
    obj=pcb.PCB_VIA(board)
    obj.SetPosition(v(pt))
    obj.SetLayerPair(pcb.F_Cu,pcb.B_Cu)
    obj.SetNet(net)
    obj.SetWidth(pcb.FromMM(1.0 if width>.4 else .70))
    obj.SetDrill(pcb.FromMM(.4 if width>.4 else .30))
    board.Add(obj)

def choose_layers():
    # Avoid multiple crossing polylines on the same inner layer by assigning
    # a deterministic round-robin. Native DRC independently judges geometry.
    return [LAYERS[i%len(LAYERS)] for i in range(len(SPECS))]

def build():
    if not base.BOARD.is_file():raise ValueError("native base PCB not generated")
    prior=json.loads(base.RECEIPT.read_text("utf-8"))
    if prior["native_drc"]["physical_rule_violations"]!=0 or prior["native_drc"]["unconnected_items"]!=27:
        raise ValueError("base integration changed, regenerate route contract")
    b=pcb.LoadBoard(str(base.BOARD))
    bynet={o.GetNetname():o for o in b.GetNetInfo().NetsByNetcode().values()}
    if len(SPECS)!=27 or len(b.GetFootprints())!=154:
        raise ValueError("must start from source-lock 154/27 baseline")
    added=[]; viapoints={}
    for i,(net,a,z,waypoints,width,sv,ev) in enumerate(SPECS):
        layer=LAYERS[i%len(LAYERS)]
        item=bynet[net]
        aa=sv if sv is not None else a
        zz=ev if ev is not None else z
        for pad,loc in ((a,aa),(z,zz)):
            if distance(pad,loc)>.002:
                if net=="GH_DRV" and abs(pad[0]-52.499258)<.01 and abs(pad[1]-18.5)<.01:
                    mid=(51.55,18.5)
                    track(b,item,pcb.F_Cu,pad,mid,.2)
                    track(b,item,pcb.F_Cu,mid,loc,.2)
                else:
                    track(b,item,pcb.F_Cu,pad,loc,min(width,.2))
            # A connection can already end on an existing through-via; do not
            # place a duplicate via on top of an identical native plated hole.
            key=(round(loc[0],3),round(loc[1],3))
            if key not in viapoints:
                existing=any(isinstance(t,pcb.PCB_VIA) and
                    distance((pcb.ToMM(t.GetPosition().x),pcb.ToMM(t.GetPosition().y)),loc)<.02
                    and t.GetNetname()==net for t in b.GetTracks())
                if not existing:via(b,item,loc,width)
                viapoints[key]=net
            elif viapoints[key]!=net:
                raise ValueError("two different net vias colliding")
        pts=[aa,*waypoints,zz]
        for p,q in zip(pts,pts[1:]):
            track(b,item,layer,p,q,width)
        added.append({"net":net,"inner_layer":pcb.LayerName(layer),
            "pads_mm":[list(a),list(z)],"via_mm":[list(aa),list(zz)],
            "waypoints_mm":[list(x) for x in waypoints],"track_width_mm":width})
    pcb.ZONE_FILLER(b).Fill(b.Zones())
    pcb.SaveBoard(str(BOARD),b)
    reopened=pcb.LoadBoard(str(BOARD))
    if len(reopened.GetFootprints())!=154:raise ValueError("lost magnetic test footprints")
    cmd=[str(Path(sys.executable).with_name("kicad-cli.exe")),"pcb","drc","--format","json",
         "--severity-all","-o",str(DRC),str(BOARD)]
    run=subprocess.run(cmd,capture_output=True,text=True,errors="replace")
    if not DRC.is_file():raise ValueError("KiCad DRC did not export")
    drc=json.loads(DRC.read_text("utf-8"))
    record={"status":"FULL_BOARD_ROUTE_TRIAL_NOT_FOR_FAB","source_sha256":sha(base.BOARD),
      "route_count":len(SPECS),"routes":added,
      "new_board_sha256":sha(BOARD),"native_drc_sha256":sha(DRC),
      "violations":len(drc.get("violations",[])),
      "unconnected":len(drc.get("unconnected_items",[])),
      "native_drc_exit_code":run.returncode,
      "via_in_pad_or_component_collision_review_pending":True,
      "rated_power_copper_and_kelvin_not_verified":True,
      "manufacturer_magnetics_unverified":True,
      "full_functional_circuit_and_isolated_bias_not_integrated":True,
      "gate_0_approved":False,"manufacture":False,"energization":False}
    RECEIPT.write_text(json.dumps(record,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return record

def check():
    if not all(x.is_file() for x in (BOARD,DRC,RECEIPT)):raise ValueError("Missing route trial")
    r=json.loads(RECEIPT.read_text("utf-8"))
    d=json.loads(DRC.read_text("utf-8"))
    if r["new_board_sha256"]!=sha(BOARD) or r["source_sha256"]!=sha(base.BOARD) or \
       r["native_drc_sha256"]!=sha(DRC) or r["violations"]!=len(d.get("violations",[])) or \
       r["unconnected"]!=len(d.get("unconnected_items",[])):
        raise ValueError("Route evidence drift")
    return r

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    args=ap.parse_args()
    rec=build() if args.write else check()
    print(json.dumps({k:rec[k] for k in ("status","route_count","violations","unconnected")}))
if __name__=="__main__":main()
