"""Build 72 real linked T530 native schematic symbols on dedicated COUT_T530_72 page.

Uses the ALREADY VISIBLE V9 GUI, no open/close/stop CLI commands. Two native
wire primitives per symbol carry VOUT/PGND, with pin number alignment to the
genuine PCB Device footprint. Batch receipts prevent unverified replay.

  python hardware/dcx_main/g2/g2_v9_sch_cout72.py --batch 2 13
  python hardware/dcx_main/g2/g2_v9_sch_cout72.py --verify
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import g2_v9_real_t530_components as PCB

D = PCB.D
NAME = PCB.NAME
DEVICE = PCB.DEVICE
LIB = PCB.LIB
PAGE = "COUT_T530_72"
REPORT = HERE / "g2_v9_sch_cout72_native_checkpoint_NOT_FOR_FAB.json"


def rows():
    return [{
        "ref": f"CHB{i:02d}",
        "x": 260 + (i-1) % 12 * 140,
        "y": 340 + (i-1) // 12 * 160,
    } for i in range(1, 73)]


def get_page_id(sid):
    js = """return await (async()=>{
      const p=await eda.dmt_Project.getCurrentProjectInfo();
      const schematic=p?.data?.find(x=>x?.schematic?.uuid)?.schematic;
      return {project:p?.friendlyName, pages:schematic?.page?.map(x=>({name:x.name,uuid:x.uuid}))};
    })();"""
    v = D.call(D.build_invoke_args(sid, js, 15000), timeout_s=25)
    if not v.get("ok") or v["value"].get("project") != PCB.V9.stem:
        raise RuntimeError("Wrong GUI or no active native V9 project")
    matching = [x for x in (v["value"].get("pages") or []) if x["name"] == PAGE]
    if len(matching) != 1:
        raise RuntimeError("Dedicated 72-unit schematic sheet not present exactly once")
    return matching[0]["uuid"]


def js_batch(new_rows, page):
    return """return await (async()=>{
      const p=await eda.dmt_Project.getCurrentProjectInfo();
      if(p?.friendlyName!==%s)throw Error("Wrong V9 target");
      await eda.dmt_EditorControl.openDocument(%s);
      const library=await eda.lib_Device.search(%s,%s,[],undefined,15,1);
      const dev=library.find(x=>x.uuid===%s);
      if(!dev || dev.footprintUuid!==%s)throw Error("Linked KEMET device not found");
      const R=%s;
      const report=[];
      for(const q of R){
       const one={ref:q.ref};
       try{
        let found=(await eda.sch_PrimitiveComponent.getAll())
             .filter(x=>x.getState_Designator()===q.ref);
        if(found.length>1)throw Error("Duplicate schematic ref");
        let c;
        if(found.length){c=found[0];one.resumed=true;}
        else{
         c=await eda.sch_PrimitiveComponent.create(dev,q.x,q.y,undefined,0,false,true,true);
         if(!c)throw Error("Native SCH create null");
         const prop=(await eda.sch_PrimitiveComponent.get(c.getState_PrimitiveId())).getState_OtherProperty();
         const mod=await eda.sch_PrimitiveComponent.modify(c.getState_PrimitiveId(),{
            designator:q.ref,name:"T530 470uF 6.3V",otherProperty:prop});
         if(!mod)throw Error("SCH modification returned false");
         one.resumed=false;
        }
        const pins=await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId());
        if(pins.length!==2)throw Error("SCH pin count not 2");
        const by=Object.fromEntries(pins.map(x=>[x.getState_PinNumber(),x]));
        if(!by["1"]||!by["2"])throw Error("SCH numbered pins missing");
        if(Math.abs(by["1"].x-(q.x-20))>.01||Math.abs(by["2"].x-(q.x+20))>.01
            ||Math.abs(by["1"].y-q.y)>.01||Math.abs(by["2"].y-q.y)>.01)
          throw Error("Native schematic pin geometry shifted");
        const old=await eda.sch_PrimitiveWire.getAll();
        for(const [n,net,side] of [["1","VOUT",-1],["2","PGND",1]]){
         const pin=by[n],x2=pin.x+side*20,y2=pin.y;
         const hit=old.filter(w=>{
           if(w.getState_Net()!==net)return false;
           const line=w.line||[];
           if(line.length!==4)return false;
           return (Math.abs(line[0]-pin.x)<.01&&Math.abs(line[1]-pin.y)<.01
                   &&Math.abs(line[2]-x2)<.01&&Math.abs(line[3]-y2)<.01)
                || (Math.abs(line[2]-pin.x)<.01&&Math.abs(line[3]-pin.y)<.01
                   &&Math.abs(line[0]-x2)<.01&&Math.abs(line[1]-y2)<.01);
         });
         if(hit.length>1)throw Error("Duplicate schematic wire on pin");
         if(hit.length===0){
           const w=await eda.sch_PrimitiveWire.create([pin.x,pin.y,x2,y2],net);
           if(!w||w.getState_Net()!==net)throw Error("Wire create/net mismatch");
         }
        }
        one.ok=true;
       }catch(e){one.ok=false;one.error=String(e);}
       report.push(one);
       if(!one.ok)break;
      }
      return {requested:R.length,report,
        complete:report.length===R.length&&report.every(x=>x.ok)};
    })();""" % (json.dumps(PCB.V9.stem),json.dumps(page),json.dumps(NAME),
                  json.dumps(LIB),json.dumps(DEVICE),
                  json.dumps("c9bdf53e779d4dd6a2eee1e6cecd4462"),
                  json.dumps(new_rows,separators=(",",":")))


def batch(first, last):
    if not (2 <= first <= last <= 72) or last-first > 11:
        raise ValueError("Only CHB02...72, up to 12 per batch")
    if PCB.sha(PCB.V8) != PCB.EXPECTED_V8_SHA:
        raise ValueError("Frozen V8 PCB source changed")
    receipt=HERE/f"g2_v9_sch_chb_{first:02d}_{last:02d}_NOT_FOR_FAB.json"
    if receipt.exists():
        raise FileExistsError("Native SCH one-shot batch already attempted")
    sid,_=PCB.active_v9()
    page=get_page_id(sid)
    selected=rows()[first-1:last]
    assert len(selected)==last-first+1
    reply=D.call(D.build_invoke_args(sid,js_batch(selected,page),59000),timeout_s=71)
    outcome={"schema":"G2_NATIVE_SCHEMATIC_CAP72_BATCH_V1","status":"TRIAL_NOT_FOR_FAB",
       "first":first,"last":last,"native_page":page,"gui_session":sid,
       "reply":reply,"gui_kept_open":True,
       "pcb_v8_source_sha256":PCB.sha(PCB.V8),"fabrication_approved":False}
    receipt.write_text(json.dumps(outcome,ensure_ascii=False,indent=2)+"\n",encoding="utf8",newline="\n")
    print(json.dumps({"range":[first,last],"reply":reply,"receipt":str(receipt.name)},
          ensure_ascii=False,indent=2))
    if not reply.get("ok") or not (reply.get("value") or {}).get("complete"):
        raise RuntimeError("Schematic batch not verified; inspect GUI before further edits")
    return 0


def js_verify(page):
    expected=json.dumps(rows(),separators=(",",":"))
    return """return await (async()=>{
     const info=await eda.dmt_Project.getCurrentProjectInfo();
     if(info?.friendlyName!==%s)throw Error("Wrong native GUI");
     await eda.dmt_EditorControl.openDocument(%s);
     const caps=await eda.sch_PrimitiveComponent.getAll(),wires=await eda.sch_PrimitiveWire.getAll();
     const W=%s,issues=[],results=[];
     for(const q of W){
      const found=caps.filter(c=>c.getState_Designator()===q.ref);
      if(found.length!==1){issues.push(q.ref+" native SCH device absent/duplicate");continue}
      const pins=await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(found[0].getState_PrimitiveId());
      const by=Object.fromEntries(pins.map(x=>[x.getState_PinNumber(),x]));
      if(pins.length!==2||!by["1"]||!by["2"]){issues.push(q.ref+" PIN1/PIN2 missing");continue}
      for(const [n,net,side] of [["1","VOUT",-1],["2","PGND",1]]){
       const pin=by[n],endX=pin.x+side*20,endY=pin.y;
       const count=wires.filter(w=>{
        if(w.getState_Net()!==net)return false;
        const l=w.line||[];
        if(l.length!==4)return false;
        return (Math.abs(l[0]-pin.x)<.01&&Math.abs(l[1]-pin.y)<.01
             &&Math.abs(l[2]-endX)<.01&&Math.abs(l[3]-endY)<.01)
            || (Math.abs(l[2]-pin.x)<.01&&Math.abs(l[3]-pin.y)<.01
             &&Math.abs(l[0]-endX)<.01&&Math.abs(l[1]-endY)<.01);
       }).length;
       if(count!==1)issues.push(q.ref+" "+n+" "+net+" wire count "+count);
      }
      results.push({ref:q.ref,pin1:"VOUT",pin2:"PGND",
           id:found[0].getState_PrimitiveId()});
     }
     return {source_document:"COUT_T530_72",count:results.length,
       total_components:caps.length,wires:wires.length,
       physical_component_ref_count:caps.filter(c=>(c.getState_Designator()||"").startsWith("CHB")).length,
       issues};
    })();""" %(json.dumps(PCB.V9.stem),json.dumps(page),expected)


def verify():
    sid,_=PCB.active_v9()
    page=get_page_id(sid)
    reply=D.call(D.build_invoke_args(sid,js_verify(page),59000),timeout_s=72)
    if not reply.get("ok"):
        raise RuntimeError(str(reply.get("error")))
    v=reply["value"]
    report={"status":"G2_V9_REAL_NATIVE_COUT72_SCHEMATIC_NOT_FOR_FAB",
            "native_page":page,"native_schematic_cap_count":v["count"],
            "native_schematic_component_count":v["total_components"],
            "native_schematic_wire_count":v["wires"],
            "native_named_chb_count":v["physical_component_ref_count"],
            "issues":v["issues"],"pcb_72_components_real":True,
            "magnetic_physical_pads_verified":False,
            "100a_rails_qualified":False,"fabrication_approved":False}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if v["count"] != 72 or v["wires"] != 144 or v["physical_component_ref_count"] != 72 or v["issues"]:
        raise RuntimeError("Schematic 72 component/pin/net parity not yet achieved")
    if REPORT.exists():
        raise FileExistsError("Do not overwrite previous verification")
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8",newline="\n")
    return 0


if __name__=="__main__":
    a=argparse.ArgumentParser()
    g=a.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--batch",nargs=2,type=int)
    g.add_argument("--verify",action="store_true")
    args=a.parse_args()
    if args.check:
        PCB.plan()
        print(json.dumps({"schema":"G2_SCH_CAP72_PLAN","rows":len(rows()),
                          "page":PAGE,"source_v8_sha256":PCB.sha(PCB.V8)},indent=2))
    elif args.batch:
        raise SystemExit(batch(*args.batch))
    else:
        raise SystemExit(verify())
