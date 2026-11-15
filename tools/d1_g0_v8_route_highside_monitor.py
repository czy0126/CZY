"""V8 monitor physical routing after verified 24/24 original V7 signal net closure.

Route every new non-plane sensor signal on In2.Cu/In3 fallback. Never bridge
the isolation moat; AMC1311 high/low pins remain separate. Absolute native
KiCad ERC/DRC/Open remains sole electrical CAD acceptance criterion.
"""
from __future__ import annotations
import argparse,collections,hashlib,json,math,subprocess,sys
from pathlib import Path
import pcbnew as pcb
import d1_g0_v8_route_interlock as r
import d1_g0_v8_highside_monitor as hs
OUT=hs.OUT
BOARD=OUT/"d1_g0_V8_HS_GH_HB_NATIVE_MONITOR_ROUTED_TRIAL_NOT_FOR_FAB.kicad_pcb"
DRC=OUT/"d1_g0_V8_HS_GH_HB_NATIVE_MONITOR_ROUTED_TRIAL_DRC.json"
REPORT=OUT/"V8_isolated_HS_analog_routed_evidence_NOT_FOR_FAB.json"
PLANES={"PGND","VCC12","HS_SW","HS_VB","HS5V","PRI5V","VIN48_AUX"}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def padloc(p):return r.pt(p)
def netmap(b):return {str(x):y for x,y in b.GetNetsByName().items()}
def allendpoints(b,svia):
    endpoints=collections.defaultdict(list)
    for fp in b.GetFootprints():
      if fp.GetReference() not in hs.P and fp.GetReference()!="U_AND":
        continue
      for pad in fp.Pads():
        if fp.GetReference()=="U_AND" and pad.GetNumber()!="5":continue
        nm=pad.GetNetname()
        if not nm or nm in PLANES:continue
        key=(fp.GetReference(),pad.GetNumber())
        endpoint=r.pt(svia[key]) if key in svia else padloc(pad)
        endpoints[nm].append((fp.GetReference()+"."+pad.GetNumber(),endpoint))
    return endpoints
def tree(endpoints):
    candidates=[]
    for name,pads in endpoints.items():
      if len(pads)<2:continue
      done={0};todo=set(range(1,len(pads)))
      while todo:
        i,j=min(((i,j) for i in done for j in todo),
                 key=lambda x:math.dist(pads[x[0]][1],pads[x[1]][1]))
        candidates.append((math.dist(pads[i][1],pads[j][1]),name,pads[i],pads[j]))
        done.add(j);todo.remove(j)
    return sorted(candidates,key=lambda x:x[0])
def mask_in3(b,ids):
    g=r.secondary_layer_obstacles(b,ids)
    # Account for actual pre-existing In3.Cu copper including VCC12 main
    # extension; avoid crossing any nonmatching copper.
    for track in b.GetTracks():
      name=track.GetNetname()
      if name not in ids or isinstance(track,pcb.PCB_VIA):continue
      if track.GetLayer()!=pcb.In3_Cu:continue
      a=(pcb.ToMM(track.GetStart().x),pcb.ToMM(track.GetStart().y))
      z=(pcb.ToMM(track.GetEnd().x),pcb.ToMM(track.GetEnd().y))
      count=max(1,math.ceil(math.dist(a,z)/.22))
      half=pcb.ToMM(track.GetWidth())/2+.44
      for n in range(count+1):
        t=n/count
        r.mask_circle(g,(a[0]*(1-t)+z[0]*t,a[1]*(1-t)+z[1]*t),half,ids[name])
    return g
def routed():
    b=pcb.LoadBoard(str(hs.BOARD))
    if b.GetCopperLayerCount()!=6:raise ValueError("non 6-layer V8 monitor source")
    r.W=int(round(hs.WIDTH/r.STEP))+1
    r.H=int(round(hs.HEIGHT/r.STEP))+1
    grid,ids,svia=r.init(b,only_refs=set(hs.P))
    bynet=allendpoints(b,svia)
    todo=tree(bynet)
    print("V8 new signal MST",len(todo),"SMD escape via",len(svia),flush=True)
    successes=[];retries=[]
    nmap=netmap(b)
    for dist,name,source,target in todo:
      if name not in ids:raise ValueError("missing real net "+name)
      path,expanded=r.astar(grid,ids[name],source[1],target[1],cap=150000)
      if path:
        r.add_grid_path(b,nmap[name],grid,path,ids[name],source[1],target[1])
        successes.append({"name":name,"from":source[0],"to":target[0],"layer":"In2.Cu"})
        print("OK",name,source[0],target[0],expanded,flush=True)
      else:
        retries.append((dist,name,source,target))
        print("RETRY",name,source[0],target[0],expanded,flush=True)
    g3=mask_in3(b,ids)
    failed=[]
    for dist,name,source,target in retries:
      path,expanded=r.astar(g3,ids[name],source[1],target[1],cap=160000)
      if path:
        r.add_grid_path(b,nmap[name],g3,path,ids[name],source[1],target[1],layer=pcb.In3_Cu)
        successes.append({"name":name,"from":source[0],"to":target[0],"layer":"In3.Cu"})
        print("OK_IN3",name,source[0],target[0],expanded,flush=True)
      else:
        failed.append({"name":name,"from":source[0],"to":target[0],"expanded":expanded})
        print("FAILED",name,source[0],target[0],expanded,flush=True)
    # Explicitly bond the three new supply stubs to their actual copper
    # source instead of leaving electrically disconnected "supply" vias.
    r.route(b,nmap["PGND"],(151.475,25.9),(151.475,18.5),pcb.B_Cu,.32)
    # Both LM393B open-collector diagnostic pullups are from *PRI5V*
    # plane rather than uncontrolled VCC12. When its 5V LDO fails,
    # there is no 12V pullup capable of falsely asserting a diagnostic.
    # Their F.Cu-to-In1 vias land inside the native PRI5V zone.
    pcb.ZONE_FILLER(b).Fill(b.Zones())
    return b,successes,failed,len(svia)
def write():
    b,ok,bad,nvia=routed()
    pcb.SaveBoard(str(BOARD),b)
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    q=subprocess.run([str(cli),"pcb","drc","--severity-all","--format","json",
        "-o",str(DRC),str(BOARD)],capture_output=True,text=True,errors="replace")
    if not DRC.is_file():raise ValueError("KiCad native DRC missing "+q.stderr)
    d=json.loads(DRC.read_text("utf-8"))
    obj={"kind":"V8_58_FOOTPRINT_HIGH_SIDE_ISOLATED_MONITOR_ROUTED_CANDIDATE",
      "native_board_sha256":sha(BOARD),"native_drc_sha256":sha(DRC),
      "previous_24_signal_connections_preserved":True,
      "new_SMD_escaped_vias":nvia,"new_routed_links":len(ok),
      "router_failed_links":bad,
      "native_drc":len(d.get("violations",[])),
      "native_unconnected":len(d.get("unconnected_items",[])),
      "violation_types":collections.Counter(x.get("type") for x in d.get("violations",[])),
      "physical_amplifier_or_safety_system_installed":False,
      "R_HS_RELEASE_DNP":True,
      "g0_approved":False,"energization_allowed":False,"fabrication_approved":False}
    REPORT.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("FINAL",json.dumps({x:obj[x] for x in
      ("new_SMD_escaped_vias","new_routed_links","native_drc","native_unconnected")}),flush=True)
    return obj
def check():
    obj=json.loads(REPORT.read_text("utf8"))
    if obj["native_board_sha256"]!=sha(BOARD) or obj["native_drc_sha256"]!=sha(DRC):
      raise ValueError("routed V8 files drift")
    return obj
if __name__=="__main__":
    a=argparse.ArgumentParser()
    g=a.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true");g.add_argument("--check",action="store_true")
    opts=a.parse_args()
    write() if opts.write else check()
