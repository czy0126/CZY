"""Real G2 OEM Density-B 16x5 both-polarity LOCAL copper, NOT 100A design.

From saved/reopened 261-line, 144 OEM-dimensioned landing-pad candidate:
 - PGND front/top collector: 16 top drops + 15 horizontal top segments.
 - VOUT bottom collector: 16 vertical bottom + 15 horizontal bottom segments.
 - Every VOUT pad: one independent top dogbone plus one drilled VOUT via.
All source and new geometry scanned against unlike nets, native CAD saved,
closed/reopened and audited. 134 lines + 72 vias are NOT a manufacturer-rated
100A dual-busbar; no 72 actual schematic/footprint component instances.

Apply ONCE on the named fresh native copy, NEVER over a saved candidate.
"""
from __future__ import annotations
import argparse,hashlib,json,math,shutil,sys,time
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import cout_t530_72 as C
import g2_board_keepout as K
import apply_t530_density_b_native as A
import plan_t530_72_oem_density_b as P
import route_t530_oem_16x5_columns as B
from connect_t530_both_poles import coverage

SOURCE=B.TARGET
TARGET=HERE/"dcx_main_board_g2_T530_OEM_DENSITY_B_V2_BIPOLAR_LOCAL_NOT_FOR_FAB.eprj2"
PREFIX="g2_t530_oem_density_b_bipolar"
PLAN=HERE/(PREFIX+"_plan.json")
DELTA=HERE/(PREFIX+"_drc_delta.json")
PGND_Y=94.0
VOUT_Y=94.0
VIA_OFFSET_Y=3.2
TOP=1
BOTTOM=2
WIDTH_MM=1.6
DOGBONE_MM=1.2
VIA_DIA_MM=1.0
VIA_HOLE_MM=0.4
CLEAR_MM=.30
MILS=1/.0254

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def dump(tag,doc):
    (HERE/(PREFIX+"_"+tag+".json")).write_text(
        json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")

def native_source():
    prior=json.loads(B.DELTA.read_text(encoding="utf-8"))
    if sha(SOURCE)!=prior["candidate_sha256"]:
        raise ValueError("261-line OEM local copper source changed")
    r=json.loads((HERE/(B.PREFIX+"_reopen_readback.json")).read_text(encoding="utf-8"))
    if not r.get("ok"):raise ValueError("OEM saved/reopened native readback absent")
    x=r["value"]
    if tuple(len(x[k]) for k in ("components","pads","lines","vias","nets")) !=(77,443,261,18,65):
        raise ValueError("Source real native geometries differ from frozen 261line report")
    if B.review_readback(x,B.generate())!=prior["readback"]:
        raise ValueError("Native OEM local copper source coverage changed")
    return x

def _track(net,layer,a,b,width=WIDTH_MM):
    return {"net":net,"layer":layer,"a_mm":[round(v,4) for v in a],
            "b_mm":[round(v,4) for v in b],"width_mm":width}

def _touch_rect(q):
    (x,y),(u,v)=q["a_mm"],q["b_mm"]
    h=q["width_mm"]/2+CLEAR_MM
    return (min(x,u)-h,min(y,v)-h,max(x,u)+h,max(y,v)+h)

def _conflicts_line(q,d):
    box=_touch_rect(q);hits=[]
    for pad in d["pads"]:
        if pad["Net"]==q["net"]:continue
        if int(pad["Layer"]) not in (q["layer"],11,12,0):continue
        if C.touches(box,K.pad_bbox(pad)):
            hits.append("pad:"+str(pad["PadNumber"]))
    for old in d["lines"]:
        if old["net"]==q["net"] or int(old["layer"])!=q["layer"]:continue
        h=old["width"]*.0254/2
        box2=(box[0]-h,box[1]-h,box[2]+h,box[3]+h)
        if C.segment_hits_rectangle((old["x1"]*.0254,-old["y1"]*.0254),
                                    (old["x2"]*.0254,-old["y2"]*.0254),box2):
            hits.append("trace:"+str(old["id"]))
    for v in d["vias"]:
        if v["net"]==q["net"]:continue
        x,y=v["x"]*.0254,-v["y"]*.0254
        if K.distance_to_box((x,y),box)<v["diameter"]*.0254/2:
            hits.append("via:"+str(v["id"]))
    return hits

def _conflicts_via(v,d):
    x,y=v["xy_mm"]
    radius=v["diameter_mm"]/2+CLEAR_MM
    hits=[]
    for pad in d["pads"]:
        if pad["Net"]!=v["net"] and K.distance_to_box((x,y),K.pad_bbox(pad))<radius:
            hits.append("pad:"+str(pad["PadNumber"]))
    for line in d["lines"]:
        if line["net"]==v["net"]:continue
        a=(line["x1"]*.0254,-line["y1"]*.0254)
        b=(line["x2"]*.0254,-line["y2"]*.0254)
        if K.segment_distance((x,y),a,b)<radius+line["width"]*.0254/2:
            hits.append("trace:"+str(line["id"]))
    for old in d["vias"]:
        if old["net"]==v["net"]:continue
        p=(old["x"]*.0254,-old["y"]*.0254)
        if math.dist((x,y),p)<radius+old["diameter"]*.0254/2:
            hits.append("via:"+str(old["id"]))
    return hits

def plan():
    d=native_source()
    places=P.make()["placement"]
    neg=sorted(set(q["pads"][0]["centre_mm"][0] for q in places))
    pos=sorted(set(q["pads"][1]["centre_mm"][0] for q in places))
    if len(neg)!=16 or len(pos)!=16:
        raise ValueError("Exactly 16 physical columns per pole required")
    tracks=[]
    for x in neg:
        tracks.append(_track("PGND",TOP,(x,99.0),(x,PGND_Y)))
    tracks += [_track("PGND",TOP,(x,PGND_Y),(y,PGND_Y))
               for x,y in zip(neg,neg[1:])]
    for x in pos:
        maxy=max(q["pads"][1]["centre_mm"][1] for q in places
                 if abs(q["pads"][1]["centre_mm"][0]-x)<.001)
        tracks.append(_track("VOUT",BOTTOM,(x,VOUT_Y),(x,maxy+VIA_OFFSET_Y)))
    tracks += [_track("VOUT",BOTTOM,(x,VOUT_Y),(y,VOUT_Y))
               for x,y in zip(pos,pos[1:])]
    vias=[]
    for comp in places:
        x,y=comp["pads"][1]["centre_mm"]
        z=round(y+VIA_OFFSET_Y,4)
        tracks.append(_track("VOUT",TOP,(x,y),(x,z),DOGBONE_MM))
        vias.append({"net":"VOUT","xy_mm":[x,z],
                     "hole_mm":VIA_HOLE_MM,"diameter_mm":VIA_DIA_MM})
    errors=[]
    for i,q in enumerate(tracks):
        for hit in _conflicts_line(q,d):errors.append("track %d %s"%(i,hit))
    for i,v in enumerate(vias):
        for hit in _conflicts_via(v,d):errors.append("via %d %s"%(i,hit))
    # All NEW unlike-net geometries must be mutually clear, not just clear
    # against the old G1 261line source.
    a=[q for q in tracks if q["net"]=="PGND" and q["layer"]==TOP]
    b=[q for q in tracks if q["net"]=="VOUT" and q["layer"]==TOP]
    for i,one in enumerate(a):
        r=_touch_rect(one)
        for j,two in enumerate(b):
            s=_touch_rect(two)
            if C.touches(r,s):
                errors.append("new PGND/VOUT top track collision %d/%d"%(i,j))
        for j,v in enumerate(vias):
            x,y=v["xy_mm"]
            if K.distance_to_box((x,y),r)<v["diameter_mm"]/2:
                errors.append("new PGND/top VOUT via collision %d/%d"%(i,j))
    if len(tracks)!=134 or len(vias)!=72:
        raise ValueError("Expected 134 native copper tracks and 72 actual vias")
    if len(set(tuple(v["xy_mm"]) for v in vias))!=72:
        raise ValueError("New VOUT physical via reused")
    return {"schema":"G2_KEMET_X1_B_16X5_INDEPENDENT_TWO_POLE_LOCAL_COPPER",
            "status":"NOT_100A_QUALIFIED_NATIVE_BIPOLAR_LOCAL_COPPER_ONLY",
            "source_sha256":sha(SOURCE),"oem_land_plan_sha256":sha(P.OUT),
            "tracks":tracks,"vias":vias,"problems":sorted(set(errors)),
            "all_72_vout_capacitor_pads_have_independent_via":True,
            "both_pole_local_collector_connected":True,
            "actual_oem_component_instances_present":False,
            "full_100a_busbar_and_terminals_qualified":False,
            "via_100a_thermal_rated":False,
            "hot_esr_and_16mm_stack_verified":False,
            "fabrication_approved":False}

def _ready_js():
    return """let board;
      for(let i=0;i<20&&!board;i++){
        const info=await eda.dmt_Project.getCurrentProjectInfo();
        board=info?.data?.find(x=>x?.pcb?.uuid);
        if(!board)await new Promise(r=>setTimeout(r,500));
      }
      if(!board)throw new Error("PCB absent after settle");
      await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
      await new Promise(r=>setTimeout(r,1000));
      if((await eda.pcb_PrimitivePad.getAll()).length!==443)
          throw new Error("OEM pad count changed; refuse to write");
      if(await eda.pcb_Layer.getTheNumberOfCopperLayers()<2)
          throw new Error("two copper layers required");
    """

def js_tracks(rows):
    a=[[q["net"],q["layer"],round(q["width_mm"]*MILS,6),
        round(q["a_mm"][0]*MILS,6),round(-q["a_mm"][1]*MILS,6),
        round(q["b_mm"][0]*MILS,6),round(-q["b_mm"][1]*MILS,6)]
       for q in rows]
    return ('return await (async()=>{'+_ready_js()+"""
      const R=%s;const out=[];
      for(const q of R){
        try{
          const l=await eda.pcb_PrimitiveLine.create(
            q[0],q[1],q[3],q[4],q[5],q[6],q[2],false);
          if(!l)throw new Error("null track");
          out.push({ok:true,id:l.getState_PrimitiveId()});
        }catch(e){out.push({ok:false,error:String(e)});break;}
      }
      return {requested:R.length,created:out,
        all_created:out.length===R.length&&out.every(q=>q.ok)};
      })();"""%json.dumps(a,separators=(",",":")))

def js_vias(rows):
    a=[[v["net"],round(v["xy_mm"][0]*MILS,6),
        round(-v["xy_mm"][1]*MILS,6),round(v["hole_mm"]*MILS,6),
        round(v["diameter_mm"]*MILS,6)] for v in rows]
    return ('return await (async()=>{'+_ready_js()+"""
      const R=%s;const out=[];
      for(const q of R){
        try{
          const v=await eda.pcb_PrimitiveVia.create(
              q[0],q[1],q[2],q[3],q[4],0,null);
          if(!v)throw new Error("null via");
          out.push({ok:true,id:v.getState_PrimitiveId()});
        }catch(e){out.push({ok:false,error:String(e)});break;}
      }
      return {requested:R.length,created:out,
        all_created:out.length===R.length&&out.every(q=>q.ok)};
      })();"""%json.dumps(a,separators=(",",":")))

def physical_copper_covers(reference, actual_lines, *, full_original_width:bool)->bool:
    """Sample copper ENVELOPE after real EasyEDA same-net splitting/snapping.

    Original wire centerlines may shift by ~0.18mm when a wider same-net bus
    intersects; a strict primitive ID/centerline identity is too strong.
    This *must* still contain the original wire's entire physical copper area
    on that exact net and layer (including both lateral edges). A newly
    planned link only demands continuous centerline copper coverage here.
    No different-net conductors are admitted; the real DRC is mandatory.
    """
    if "a_mm" in reference:
        a,b=reference["a_mm"],reference["b_mm"]
        rad=reference["width_mm"]/2
    else:
        a=(reference["x1"]*.0254,-reference["y1"]*.0254)
        b=(reference["x2"]*.0254,-reference["y2"]*.0254)
        rad=reference["width"]*.0254/2
    dx=b[0]-a[0];dy=b[1]-a[1];length=math.hypot(dx,dy)
    if length<=.0001:return False
    nx=-dy/length;ny=dx/length
    possibilities=[q for q in actual_lines
                   if q["net"]==reference["net"]
                   and int(q["layer"])==int(reference["layer"])]
    if not possibilities:return False
    intervals=[((
        q["x1"]*.0254,-q["y1"]*.0254),
        (q["x2"]*.0254,-q["y2"]*.0254),
        q["width"]*.0254/2) for q in possibilities]
    offsets=(-rad,0.0,rad) if full_original_width else (0.0,)
    step_count=max(2,int(math.ceil(length/.24)))
    for i in range(step_count+1):
        t=i/step_count
        center=(a[0]+dx*t,a[1]+dy*t)
        for offset in offsets:
            point=(center[0]+nx*offset,center[1]+ny*offset)
            if not any(K.segment_distance(point,u,v)<=(r+.008)
                       for u,v,r in intervals if r>.008):
                return False
    return True

def verify(d,design):
    old=native_source()
    for kind in ("components","pads","nets"):
        if Counter(json.dumps(x,sort_keys=True) for x in d[kind])!=Counter(
                 json.dumps(x,sort_keys=True) for x in old[kind]):
            raise ValueError("existing native element mutated: "+kind)
    normalized=[]
    for oldline in old["lines"]:
        if not coverage(oldline,d["lines"]):
            if not physical_copper_covers(oldline,d["lines"],
                                          full_original_width=True):
                raise ValueError("original OEM copper area lost: "+oldline["id"])
            normalized.append(oldline["id"])
    for q in design["tracks"]:
        if not coverage(q,d["lines"]) and not physical_copper_covers(
                q,d["lines"],full_original_width=False):
            raise ValueError("new bipolar conductor has a geometric gap: "+str(q))
    if len(d["vias"])!=18+len(design["vias"]):
        raise ValueError("native via count not 90")
    oldvias=Counter(json.dumps(x,sort_keys=True) for x in old["vias"])
    newvias=Counter(json.dumps(x,sort_keys=True) for x in d["vias"])
    if oldvias-newvias:raise ValueError("original via changed")
    added=[json.loads(x) for x in (newvias-oldvias).elements()]
    for v in design["vias"]:
        c=[x for x in added if x["net"]==v["net"]
            and math.dist((x["x"]*.0254,-x["y"]*.0254),v["xy_mm"])<.015
            and abs(x["diameter"]*.0254-v["diameter_mm"])<.03
            and abs(x["hole"]*.0254-v["hole_mm"])<.03]
        if len(c)!=1:raise ValueError("new VOUT via absent: "+str(v))
    return {"preserved_77_components_443_pads_65_nets":True,
            "old_261_source_copper_covered":True,
            "source_lines_native_snap_normalized":normalized,
            "new_134_native_lines_covered":True,
            "new_72_individual_vout_vias_reopened":len(added),
            "manufacturer_library_footprint_instantiated":False,
            "manufacturing_approved":False}

def open_board(stage):
    r=A.D.call(A.D.build_open_args(TARGET),timeout_s=120)
    dump(stage+"_open",r)
    sid=(r.get("value") or {}).get("sessionId")
    if not sid:return None
    time.sleep(A.D.SETTLE_S)
    ping=A.D.call(A.D.build_ping_args(sid),timeout_s=35)
    dump(stage+"_ping",ping)
    if not ping.get("ok"):
        dump(stage+"_close",A.D.call(A.D.build_close_args(sid)))
        return None
    return sid

def resume():
    d=plan()
    if d["problems"]:raise ValueError("native plan hits unlike-net copper")
    if not TARGET.is_file() or sha(TARGET)==sha(SOURCE):
        raise ValueError("no distinct saved native candidate; no double apply")
    if not PLAN.is_file() or json.loads(PLAN.read_text(encoding="utf-8"))!=d:
        raise ValueError("saved plan missing/modified")
    saved_sha=sha(TARGET)
    sid=open_board("reopen")
    if not sid:return 1
    try:
        rb=A.invoke(sid,A.READ_JS.read_text(encoding="utf-8"))
        dump("reopen_readback",rb)
        if not rb.get("ok"):return 1
        audit=verify(rb["value"],d)
        drc=A.invoke(sid,A.DRC_JS.read_text(encoding="utf-8"))
        dump("drc_raw",drc)
        if not drc.get("ok"):return 1
    finally:
        dump("reopen_close",A.D.call(A.D.build_close_args(sid)))
    if sha(TARGET)!=saved_sha:raise ValueError("read-only reopen changed native project")
    earlier=json.loads(B.DELTA.read_text(encoding="utf-8"))["actual_native_drc"]
    actual=A.R.categories(drc)
    if actual.get("Connection Error",999)>=earlier["Connection Error"]:
        raise ValueError("native actual connectivity did not improve")
    if actual.get("Physical Error",0)>0 or actual.get("Netlist Error",0)>earlier.get("Netlist Error",0):
        raise ValueError("native bipolar design introduced physical/netlist violation")
    summary={"status":"REAL_NATIVE_OEM_16X5_TWO_POLE_LOCAL_COPPER_REOPEN_NOT_FOR_FAB",
             "parent_sha256":sha(SOURCE),"candidate_sha256":sha(TARGET),
             "plan_sha256":sha(PLAN),
             "previous_native_drc":earlier,"actual_native_drc":actual,
             "readback":audit,"continuous_100a_copper_or_busbar_qualified":False,
             "hardware_or_fabrication_approved":False}
    dump("drc_delta",summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0

def apply():
    d=plan()
    if d["problems"]:raise ValueError("bipolar plan errors: "+str(d["problems"][:6]))
    if TARGET.exists():raise FileExistsError("never overwrite existing bipolar candidate")
    PLAN.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",
                    encoding="utf-8",newline="\n")
    frozen=sha(SOURCE)
    shutil.copy2(SOURCE,TARGET)
    sid=open_board("apply")
    if not sid:return 1
    saved=False
    try:
        for i in range(0,len(d["tracks"]),18):
            receipt=A.invoke(sid,js_tracks(d["tracks"][i:i+18]))
            dump("apply_tracks_"+str(i//18+1),receipt)
            if not receipt.get("ok") or not (receipt.get("value") or {}).get("all_created"):
                print("native tracks failed/partial, do not repeat or save")
                return 1
        for i in range(0,len(d["vias"]),12):
            receipt=A.invoke(sid,js_vias(d["vias"][i:i+12]))
            dump("apply_vias_"+str(i//12+1),receipt)
            if not receipt.get("ok") or not (receipt.get("value") or {}).get("all_created"):
                print("native vias failed/partial; never repeat before inspection")
                return 1
        result=A.invoke(sid,"return await eda.pcb_Document.save();")
        dump("apply_save",result)
        saved=bool(result.get("ok") and result.get("value") is True)
        if saved:time.sleep(30)
    finally:
        dump("apply_close",A.D.call(A.D.build_close_args(sid)))
    if not saved or sha(SOURCE)!=frozen or sha(TARGET)==frozen:
        raise ValueError("native project did not save all 134 tracks and 72 vias")
    return resume()

def main():
    parser=argparse.ArgumentParser()
    a=parser.add_mutually_exclusive_group(required=True)
    a.add_argument("--check",action="store_true")
    a.add_argument("--apply",action="store_true")
    a.add_argument("--resume",action="store_true")
    options=parser.parse_args()
    if options.check:
        d=plan()
        print(json.dumps({k:v for k,v in d.items() if k not in ("tracks","vias")},
                         ensure_ascii=False,indent=2))
        return 0 if not d["problems"] else 1
    return apply() if options.apply else resume()

if __name__=="__main__":
    raise SystemExit(main())
