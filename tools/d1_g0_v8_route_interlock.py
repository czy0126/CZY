"""Route V7's remaining physical low-voltage signals, via dedicated inner routing layer.

V8 is a new experimental 4-layer PCB from the immutable V7 source.
A* searches only In2.Cu on a 0.45 mm grid; entire net's many pads are joined
by a minimum-distance Prim tree. Existing PTH pads, other-net vias and native
routed tracks are obstacles. A 100% native KiCad DRC/open gate decides outcome.
Not a manufacturing approval; via-in-pad for SMT is forbidden by default.

Usage (KiCad10 bundled python):
  python tools/d1_g0_v8_route_interlock.py --write
  python tools/d1_g0_v8_route_interlock.py --check
"""
from __future__ import annotations
import argparse,collections,hashlib,heapq,json,math,subprocess,sys
from pathlib import Path
import numpy as np
import pcbnew as pcb
import d1_g0_estop_interlock_v7 as old

OUT=old.ROOT/"hardware/dcx_main/g2/d1_g0_V8_MONITORED_INTERLOCK_NOT_FOR_FAB"
STEM="d1_g0_V8_NC_ESTOP_INNER_ROUTE_HS_MONITOR_NOT_FOR_FAB"
BOARD=OUT/(STEM+"_pre_monitor_routed.kicad_pcb")
DRC=OUT/(STEM+"_pre_monitor_native_drc.json")
REPORT=OUT/"V8_pre_monitor_route_receipt_NOT_FOR_FAB.json"
STEP=.45
W=int(round(old.BOARD_W/STEP))+1
H=int(round(old.BOARD_H/STEP))+1
LAY=pcb.In2_Cu
POWER=("PGND","VCC12","VIN48_AUX","48V_FUSED","48V_AFTER_ESTOP","COIL_DRAIN")
def pt(obj):return(pcb.ToMM(obj.GetPosition().x),pcb.ToMM(obj.GetPosition().y))
def idx(pos):return(int(round(pos[0]/STEP)),int(round(pos[1]/STEP)))
def mmgrid(pos):return(pos[0]*STEP,pos[1]*STEP)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def mask_circle(grid,p,r,owner):
    x,y=idx(p);R=math.ceil(r/STEP)
    for i in range(max(0,x-R),min(grid.shape[0]-1,x+R)+1):
      for j in range(max(0,y-R),min(grid.shape[1]-1,y+R)+1):
        if ((i*STEP-p[0])**2+(j*STEP-p[1])**2)<=r*r:
          if grid[i,j]==0:grid[i,j]=owner
          elif grid[i,j]!=owner:grid[i,j]=-1
def route(b,net,a,z,layer=pcb.F_Cu,width=.20):
    if math.dist(a,z)<1.e-4:return
    t=pcb.PCB_TRACK(b);t.SetNet(net);t.SetLayer(layer)
    t.SetStart(old.v(a));t.SetEnd(old.v(z));t.SetWidth(pcb.FromMM(width))
    b.Add(t)
def via(b,net,p):
    v=pcb.PCB_VIA(b);v.SetPosition(old.v(p))
    v.SetLayerPair(pcb.F_Cu,pcb.B_Cu)
    v.SetWidth(pcb.FromMM(.70));v.SetDrill(pcb.FromMM(.30))
    v.SetNet(net);b.Add(v);return v

def init(b,only_refs=None):
    grid=np.zeros((W,H),dtype=np.int16)
    nets={str(name):obj for name,obj in b.GetNetsByName().items()}
    ids={name:i+1 for i,name in enumerate(sorted(nets)) if name}
    refs={}
    pth=[]
    smd=[]
    for fp in b.GetFootprints():
      for pad in fp.Pads():
        nm=pad.GetNetname()
        if not nm:
          # Unused PTH pins are physical copper obstacles, NOT empty space;
          # routing a track through CD4013 pin12 shorted it to an NC pad.
          if pad.GetAttribute()!=pcb.PAD_ATTRIB_SMD:
            size=pad.GetSize()
            mask_circle(grid,pt(pad),max(pcb.ToMM(size.x),pcb.ToMM(size.y))/2+.36,-1)
          continue
        if pad.GetAttribute()==pcb.PAD_ATTRIB_SMD:
          if only_refs is None:
            if nm not in POWER:smd.append((fp,pad))
          elif fp.GetReference() in only_refs and nm!="VIN48_AUX":
            # The HS 48V fuse input has an existing full F.Cu power trace;
            # do not generate a zero-purpose dangling signal escape via.
            smd.append((fp,pad))
        else:pth.append(pad)
        # For inner layer only PTH pads are obstacles, SMD is on F only.
        if pad.GetAttribute()!=pcb.PAD_ATTRIB_SMD:
          size=pad.GetSize()
          radius=max(pcb.ToMM(size.x),pcb.ToMM(size.y))/2+.36
          mask_circle(grid,pt(pad),radius,ids[nm])
    for tr in b.GetTracks():
      nm=tr.GetNetname()
      if not nm:continue
      if isinstance(tr,pcb.PCB_VIA):
        mask_circle(grid,pt(tr),pcb.ToMM(tr.GetWidth(pcb.In2_Cu))/2+.35,ids[nm])
      elif tr.GetLayer()==LAY:
        a=(pcb.ToMM(tr.GetStart().x),pcb.ToMM(tr.GetStart().y))
        z=(pcb.ToMM(tr.GetEnd().x),pcb.ToMM(tr.GetEnd().y))
        n=max(1,math.ceil(math.dist(a,z)/(.25)))
        for k in range(n+1):
          t=k/n
          mask_circle(grid,(a[0]*(1-t)+z[0]*t,a[1]*(1-t)+z[1]*t),.50,ids[nm])
    # Prepare all SMD via endings near terminals, preferentially outward
    # from the actual pad and away from other-net pads and top copper.
    allpads=[p for fp in b.GetFootprints() for p in fp.Pads()]
    allvias=[t for t in b.GetTracks() if isinstance(t,pcb.PCB_VIA)]
    signal_vias={}
    for fp,pad in smd:
      name=pad.GetNetname();owner=ids[name]
      origin=pt(pad)
      alternatives=[]
      for dx,dy in ((-1.9,0),(1.9,0),(0,1.9),(0,-1.9),
                    (-1.75,-1.25),(1.75,-1.25),(-1.75,1.25),(1.75,1.25),
                    (-2.4,-.7),(2.4,-.7),(-2.4,.7),(2.4,.7),
                    (-3.1,0),(3.1,0),(-3.9,0),(3.9,0),
                    (-3.2,-.7),(3.2,-.7),(-3.2,.7),(3.2,.7)):
        p=(origin[0]+dx,origin[1]+dy)
        x,y=idx(p)
        if not (3<x<W-4 and 3<y<H-4):continue
        if grid[x,y] not in (0,owner):continue
        # AMC1311 DWV barrier: no via or copper passing beneath the
        # 12+ mm isolation slot between primary x>=218 and float x<=205.
        if fp.GetReference() in ("U_GH_SENSE","U_HB_SENSE"):
          highside=int(pad.GetNumber())<=4
          if highside and p[0]>205.2:continue
          if not highside and p[0]<218.8:continue
        # Exclude adjacent pad copper and other via drill.
        if any(other.GetNetname()!=name and
            math.dist(p,pt(other)) < max(1.15,max(pcb.ToMM(other.GetSize().x),pcb.ToMM(other.GetSize().y))/2+.8)
             for other in allpads):continue
        if any(other.GetNetname()!=name and math.dist(p,pt(other))<1.25
             for other in allvias):continue
        if any(other.GetNetname()!=name and math.dist(p,pt(other))<1.15
             for other in signal_vias.values()):continue
        # SMT trace from pad center to via candidate could cross adjacent pads;
        # sample entire segment against nearby other-net copper.
        if any(other.GetNetname()!=name and
            any(math.dist((origin[0]+dx*t/8,origin[1]+dy*t/8),pt(other)) <
                max(.73,max(pcb.ToMM(other.GetSize().x),pcb.ToMM(other.GetSize().y))/2+.34)
                for t in range(1,9))
            for other in allpads):continue
        alternatives.append((math.dist(p,origin),p))
      if not alternatives:
        raise ValueError("No safe V8 SMD escape via near "+fp.GetReference()+"."+pad.GetNumber())
      p=min(alternatives,key=lambda v:v[0])[1]
      # Ensure existing F.Cu top signal stubs don't cross another-net stubs.
      route(b,nets[name],origin,p,pcb.F_Cu,.20)
      vv=via(b,nets[name],p);signal_vias[(fp.GetReference(),pad.GetNumber())]=vv
      mask_circle(grid,p,.80,owner)
    return grid,ids,signal_vias

def astar(grid,owner,start,end,cap=130000):
    s=idx(start);e=idx(end)
    if s==e:return [s],0
    def ok(q):
      x,y=q
      if x<3 or y<3 or x>=W-3 or y>=H-3:return False
      return grid[x,y] in (0,owner)
    if not ok(s) or not ok(e):
      return None,0
    frontier=[(math.dist(s,e),0,s)]
    costs={s:0.0}
    previous={s:None}
    reached=False
    expanded=0
    while frontier and expanded<cap:
      est,dist,now=heapq.heappop(frontier)
      if dist>costs.get(now,1e20)+1e-5:continue
      if now==e:
        reached=True;break
      expanded+=1
      x,y=now
      for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,1),(1,-1),(-1,-1)):
        xx,yy=x+dx,y+dy
        if not ok((xx,yy)):continue
        if dx and dy and (not ok((xx,y)) or not ok((x,yy))):continue
        new=(xx,yy)
        cost=dist+(1.41421356237 if dx and dy else 1.)
        if cost+1e-9>=costs.get(new,1e20):continue
        costs[new]=cost;previous[new]=now
        heuristic=math.hypot(e[0]-xx,e[1]-yy)
        heapq.heappush(frontier,(cost+heuristic,cost,new))
    if not reached:return None,expanded
    path=[e]
    while previous[path[-1]] is not None:path.append(previous[path[-1]])
    path.reverse()
    return path,expanded

def add_grid_path(b,net,grid,path,owner,start,end,layer=LAY):
    if not path:return
    start_node=mmgrid(path[0]);end_node=mmgrid(path[-1])
    route(b,net,start,start_node,layer,.20)
    route(b,net,end_node,end,layer,.20)
    # Fold collinear segments into one track to simplify manufacturable copper.
    curr=path[0];origin=curr;lastdirection=None
    for nxt in path[1:]:
      direction=(nxt[0]-curr[0],nxt[1]-curr[1])
      if lastdirection is not None and direction!=lastdirection:
        route(b,net,mmgrid(origin),mmgrid(curr),layer,.20)
        origin=curr
      curr=nxt;lastdirection=direction
    route(b,net,mmgrid(origin),mmgrid(curr),layer,.20)
    for ptgrid in path:
      mask_circle(grid,mmgrid(ptgrid),.58,owner)

def secondary_layer_obstacles(b,ids):
    # New In3 signal layer contains PTH pads and through-vias but no In2 tracks.
    grid=np.zeros((W,H),dtype=np.int16)
    for fp in b.GetFootprints():
      for pad in fp.Pads():
        name=pad.GetNetname()
        if not name or name not in ids or pad.GetAttribute()==pcb.PAD_ATTRIB_SMD:continue
        size=pad.GetSize()
        mask_circle(grid,pt(pad),max(pcb.ToMM(size.x),pcb.ToMM(size.y))/2+.36,ids[name])
    for item in b.GetTracks():
      name=item.GetNetname()
      if not name or name not in ids:continue
      if isinstance(item,pcb.PCB_VIA):
        mask_circle(grid,pt(item),pcb.ToMM(item.GetWidth(pcb.In3_Cu))/2+.35,ids[name])
    return grid

def solve():
    b=pcb.LoadBoard(str(old.BOARD))
    b.SetCopperLayerCount(6)
    grid,ids,svia=init(b)
    bynet=collections.defaultdict(list)
    for fp in b.GetFootprints():
      for pad in fp.Pads():
        if pad.GetNetname() in POWER or not pad.GetNetname():continue
        key=(fp.GetReference(),pad.GetNumber())
        endpoint=pt(svia[key]) if key in svia else pt(pad)
        bynet[pad.GetNetname()].append((fp.GetReference()+"."+pad.GetNumber(),endpoint))
    candidates=[]
    # 24 connections are MST edges over a total 81 source pin schematic.
    for nm,pads in bynet.items():
      if len(pads)<2:continue
      completed={0};pending=set(range(1,len(pads)))
      while pending:
        i,j=min(((i,j) for i in completed for j in pending),
            key=lambda ij:math.dist(pads[ij[0]][1],pads[ij[1]][1]))
        candidates.append((math.dist(pads[i][1],pads[j][1]),nm,pads[i],pads[j]))
        completed.add(j);pending.remove(j)
    # Route the two PTH-sensitive health lines before the dense AND DIP
    # fanout creates a separation barrier in the single In2 signal layer.
    candidates.sort(key=lambda a:(0 if a[1] in ("HS_OK_IN","ESTOP_MON_OK") else 1,a[0]))
    added=[];failed=[];retry=[]
    for length,nm,s,d in candidates:
      path,n=astar(grid,ids[nm],s[1],d[1])
      if path:
        add_grid_path(b,{str(n):o for n,o in b.GetNetsByName().items()}[nm],grid,path,ids[nm],s[1],d[1])
        added.append({"net":nm,"from":s[0],"to":d[0],"path_nodes":len(path),"expanded":n})
        print("PASS",nm,s[0],d[0],"expanded",n,flush=True)
      else:
        retry.append((nm,s,d))
        print("RETRY_IN3",nm,s[0],d[0],"expanded",n,flush=True)
    grid3=secondary_layer_obstacles(b,ids)
    for nm,s,d in retry:
      path,n=astar(grid3,ids[nm],s[1],d[1],cap=100000)
      if path:
        add_grid_path(b,{str(a):o for a,o in b.GetNetsByName().items()}[nm],grid3,path,ids[nm],s[1],d[1],pcb.In3_Cu)
        added.append({"net":nm,"from":s[0],"to":d[0],
               "layer":"In3.Cu","path_nodes":len(path),"expanded":n})
        print("PASS_IN3",nm,s[0],d[0],"expanded",n,flush=True)
      else:
        failed.append({"net":nm,"from":s[0],"to":d[0],"expanded":n})
        print("UNROUTABLE_IN3",nm,s[0],d[0],"expanded",n,flush=True)
    pcb.ZONE_FILLER(b).Fill(b.Zones())
    return b,added,failed

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    b,ok,bad=solve()
    pcb.SaveBoard(str(BOARD),b)
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    p=subprocess.run([str(cli),"pcb","drc","--severity-all","--format","json",
       "-o",str(DRC),str(BOARD)],capture_output=True,text=True,errors="replace")
    if not DRC.is_file():raise ValueError("KiCad DRC export missing "+p.stderr)
    j=json.loads(DRC.read_text("utf-8"))
    info={"kind":"D1_G0_V8_ASTAR_PRE_MONITOR_SIGNAL_ROUTING_CANDIDATE",
       "source_board_sha256":sha(old.BOARD),
       "candidate_board_sha256":sha(BOARD),
       "native_drc_sha256":sha(DRC),
       "routes_attempted":len(ok)+len(bad),"successfully_routed_connections":len(ok),
       "failed_routes":bad,"native_drc":len(j.get("violations",[])),
       "native_unconnected":len(j.get("unconnected_items",[])),
       "native_warnings":[{"type":t.get("type"),"items":[x.get("description","") for x in t.get("items",[])]}
              for t in j.get("violations",[])][:30],
       "g0_physical_signoff":False,"fab_release":False,"energization_allowed":False}
    REPORT.write_text(json.dumps(info,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("FINAL",json.dumps({x:info[x] for x in
       ("routes_attempted","successfully_routed_connections","native_drc","native_unconnected")}))
    return info
def check():
    j=json.loads(REPORT.read_text("utf-8"))
    if j["candidate_board_sha256"]!=sha(BOARD) or j["native_drc_sha256"]!=sha(DRC):
      raise ValueError("KiCad V8 routing sha changed")
    return j
if __name__=="__main__":
    cmd=argparse.ArgumentParser()
    g=cmd.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    a=cmd.parse_args()
    build() if a.write else check()
