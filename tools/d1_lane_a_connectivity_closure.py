"""G0 Lane-A physically connected WIP trial (KiCad 10 PCB Python).

Uses immutable 0b9e3d V17 OEM72+VIN+SW saved PCB. Connects specified
real physical pads by native F.Cu/B.Cu tracks and through vias. It is
an experimental routing candidate, NOT a 100A- or EMI-qualified board.

Important: DRC of the *saved output*, not this script, is authoritative.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import pcbnew as k

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
IN=G/"dcx_main_board_g2_V17_OEM_T530_72_VIN_SW_CANDIDATE_NOT_FOR_FAB.kicad_pcb"
OUTDIR=G/"d1_lane_a_connectivity"
EXPECTED="4bdb3492959aa08e70716a0f6ca020fe8cf98da66f08c795b72f8172b5ab50f9"
M=k.FromMM

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def V(q):return k.VECTOR2I(M(q[0]),M(q[1]))
def P(obj):return (k.ToMM(obj.GetPosition().x),k.ToMM(obj.GetPosition().y))
class Router:
    def __init__(self,b):
        self.b=b
        self.footprints={f.GetReference():f for f in b.GetFootprints()}
        self.nets={n.GetNetname():n for n in b.GetNetInfo().NetsByNetcode().values() if n.GetNetname()}
        self.added={}
    def pad(self,ref,pin,net):
        z=[x for x in self.footprints[ref].Pads() if x.GetNumber()==str(pin)]
        if len(z)!=1 or z[0].GetNetname()!=net:raise ValueError((ref,pin,net))
        return P(z[0])
    def seg(self,net,layer,points,width):
        if net not in self.nets:raise ValueError("Net missing: "+net)
        for a,c in zip(points,points[1:]):
            if a==c:continue
            t=k.PCB_TRACK(self.b);t.SetNet(self.nets[net])
            t.SetLayer(k.F_Cu if layer=="F" else k.B_Cu)
            t.SetWidth(M(width));t.SetStart(V(a));t.SetEnd(V(c))
            self.b.Add(t)
            self.added[net]=self.added.get(net,0)+1
    def via(self,net,point,dia=.7,drill=.3):
        v=k.PCB_VIA(self.b);v.SetViaType(k.VIATYPE_THROUGH);v.SetLayerPair(k.F_Cu,k.B_Cu)
        v.SetNet(self.nets[net]);v.SetWidth(M(dia));v.SetDrill(M(drill))
        v.SetPosition(V(point));self.b.Add(v)
        self.added[net]=self.added.get(net,0)+1
    def bridge(self,net,head,via0,back,via1,tail,dia=.7,drill=.3,width=.2):
        self.seg(net,"F",[head,via0],width)
        self.via(net,via0,dia,drill)
        self.seg(net,"B",[via0]+back+[via1],width)
        self.via(net,via1,dia,drill)
        self.seg(net,"F",[via1,tail],width)
    def build(self,nets):
        if "VIN_P" in nets:
            # Cin positive return to QH thermal VIN pad; all FCu, short hot-loop.
            self.seg("VIN_P","F",[self.pad("Cin",1,"VIN_P"),(50.8,12.8)],.8)
            self.seg("VIN_P","F",[(50.8,12.8),(51.4,12.0),(51.4,8.5),(50.05,7.6)],1.2)
        if "GH" in nets:
            self.seg("GH","F",[self.pad("R18",1,"GH"),(40.8,12.0),(40.8,15.5)],.2)
            self.via("GH",(40.8,15.5))
            self.seg("GH","B",[(40.8,15.5),(40.8,13.6),(48.0,13.6),(48.8,14.8)],.2)
            self.via("GH",(48.8,14.8))
            self.seg("GH","F",[(48.8,14.8),self.pad("R4",2,"GH")],.2)
        if "GH_DRV" in nets:
            self.bridge("GH_DRV",self.pad("R4",1,"GH_DRV"),(45.9,15.4),
                        [],(50.3,18.5),self.pad("U2",4,"GH_DRV"))
        if "HB" in nets:
            self.seg("HB","F",[self.pad("C5",1,"HB"),(43.5,14.65)],.2)
            self.via("HB",(43.5,14.65))
            # Stay north of GH_DRV B.Cu, south of GH B.Cu at y=13.6,
            # and leave >0.2mm clearance around the GH through via.
            self.seg("HB","B",[(43.5,14.65),(44.8,14.55),(46.5,14.7),
                                (50.5,16.5),(50.5,17.4)],.2)
            self.via("HB",(50.5,17.4))
            self.seg("HB","F",[(50.5,17.4),(51.1,18.0),self.pad("U2",3,"HB")],.2)
        if "SW" in nets:
            # Pair of 0.5mm through drills for the QH/QL switching connection
            # (current & switching overshoot not qualified). Separate SW sense.
            for a,b in [((46.0,11.15),(53.5,7.5)),
                        ((47.4,11.15),(53.5,6.35))]:
                self.seg("SW","F",[(46.089682,9.750718) if a[0]<47 else (47.363374,9.750718),a],.9)
                self.via("SW",a,.95,.5)
                self.seg("SW","B",[a,b],1.0)
                self.via("SW",b,.95,.5)
                self.seg("SW","F",[b,(55.0,b[1]),self.pad("QL",9,"SW")],1.1)
            self.seg("SW","F",[self.pad("C5",2,"SW"),(46.1,18.8)],.2)
            self.via("SW",(46.1,18.8),.7,.3)
            # Avoid C101 PGND plated via and the FCu VCC12 decoupler wire.
            # NPTH magnetic slots start at y=21.98, so keep BCu y<=20.9.
            self.seg("SW","B",[(46.1,18.8),(46.1,20.9),(51.2,20.9),(51.2,20.3)],.2)
            self.via("SW",(51.2,20.3),.7,.3)
            self.seg("SW","F",[(51.2,20.3),(51.2,19.0),self.pad("U2",5,"SW")],.2)
        if "OC" in nets:
            # The 0.57x1.95mm-pitch U1 pins and existing DT FCu line
            # leave NO legal external escape channel. Use a provisional
            # 0.7/0.3 through via centered in U1.3 (other U1 pins in the
            # baseline also use via-in-pad). FILL/CAP OEM signoff REQUIRED.
            oc_pad=self.pad("U1",3,"OC")
            self.via("OC",oc_pad,.7,.3)
            # A current RT diagonal comes 0.157mm from the new OC via;
            # reroute the EXISTING low-current RT BCu below U1.2. Preserve
            # its exact source and destination vias and pin/net identity.
            rt_start=self.pad("U1",2,"RT")
            rt_end=self.pad("R2",1,"RT")
            matches=[]
            for t in list(self.b.GetTracks()):
                if not isinstance(t,k.PCB_TRACK) or t.GetLayer()!=k.B_Cu or t.GetNetname()!="RT":
                    continue
                a,c=(k.ToMM(t.GetStart().x),k.ToMM(t.GetStart().y)),\
                    (k.ToMM(t.GetEnd().x),k.ToMM(t.GetEnd().y))
                if max(abs(a[0]-rt_start[0]),abs(a[1]-rt_start[1]),
                       abs(c[0]-rt_end[0]),abs(c[1]-rt_end[1]))<.01:
                    matches.append(t)
            if len(matches)!=1:
                raise ValueError("Cannot safely replace the exact RT backside segment")
            self.b.Remove(matches[0])
            self.seg("RT","B",[rt_start,(rt_start[0],14.65),rt_end],.2)
            # OC is in an existing U1 pad/via-in-pad flow: OEM filled/capped
            # through-hole process still needs DFM signoff before fab.
            self.seg("OC","B",[oc_pad,(131.0,13.706281),(131.0,17.0)],.2)
            self.via("OC",(131.0,17.0),.7,.3)
            # via lands on an existing OC FCu track spanning 129.75..134.25, y17.

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--nets",default="VIN_P,GH,GH_DRV,HB,SW,OC")
    parser.add_argument("--name",required=True)
    q=parser.parse_args()
    selected=[x.strip() for x in q.nets.split(",") if x.strip()]
    if any(x not in ("VIN_P","GH","GH_DRV","HB","SW","OC") for x in selected):
        raise ValueError("Unknown route set")
    if sha(IN)!=EXPECTED:raise ValueError("Locked source PCB has changed")
    OUTDIR.mkdir(parents=True,exist_ok=True)
    path=OUTDIR/(q.name+"_NOT_FOR_FAB.kicad_pcb")
    if path.exists():raise ValueError("Output candidate already exists: "+str(path))
    board=k.LoadBoard(str(IN))
    basepad={f.GetReference():sorted((x.GetNumber(),x.GetNetname()) for x in f.Pads()) for f in board.GetFootprints()}
    r=Router(board);r.build(selected)
    if basepad!={f.GetReference():sorted((x.GetNumber(),x.GetNetname()) for x in f.Pads()) for f in board.GetFootprints()}:
        raise ValueError("Pad net drift")
    k.ZONE_FILLER(board).Fill(board.Zones())
    k.SaveBoard(str(path),board)
    new=k.LoadBoard(str(path))
    assert len(list(new.GetFootprints()))==149
    manifest={
        "source":str(IN.relative_to(ROOT)).replace("\\","/"),
        "source_sha256":EXPECTED,"output":str(path.relative_to(ROOT)).replace("\\","/"),
        "output_sha256":sha(path),"nets":selected,"added_copper":r.added,
        "kicad_version":k.Version(),"reopened":True,
        "original_pin_nets_preserved":True,
        "current_rated":False,"fabrication_approved":False,
    }
    report=path.with_suffix(".receipt.json")
    report.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"board":str(path),"sha":manifest["output_sha256"],
                      "added":r.added}))
if __name__=="__main__":
    try:main()
    except (RuntimeError,ValueError,OSError) as e:
        print("ROUTE FAILED",e,file=sys.stderr);sys.exit(1)
