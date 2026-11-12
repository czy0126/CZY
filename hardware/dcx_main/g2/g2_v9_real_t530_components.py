"""Convert 72 KEMET T530 X1 bare landing pads into real native EasyEDA devices.

Works ONLY inside the already-visible V9 trial GUI, without opening/closing it.
Each step is idempotent on actual editor state; never assumes a CLI timeout means
no side effects.  Keep attempt/verified receipts and use small 8-unit batches.

Usage:
    python hardware/dcx_main/g2/g2_v9_real_t530_components.py --check
    python hardware/dcx_main/g2/g2_v9_real_t530_components.py --batch 2 9
    python hardware/dcx_main/g2/g2_v9_real_t530_components.py --verify
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "hardware/dcx_main/g1"))
import run_driver_drc as D

V9 = HERE / "dcx_main_board_g2_T530_OEM_DENSITY_B_V9_REAL_72_COMPONENT_TRIAL_NOT_FOR_FAB.eprj2"
V8 = HERE / "dcx_main_board_g2_T530_OEM_DENSITY_B_V8_GUI_REAL_OCM_NOT_FOR_FAB.eprj2"
PLAN = HERE / "t530_72_oem_density_b_16x5_pad_plan_NOT_FOR_FAB.json"
LIB = "G1_R34_REC10K_v3_TEST"
DEVICE = "903d14a6c07f4df992b7da8bfe2d4952"
NAME = "CZY_T530X477M006ATE004_X1_B_20261112_TRIAL_NOT_FOR_FAB"
CHECKPOINT = HERE / "g2_v9_real_t530_72_checkpoint_NOT_FOR_FAB.json"
MILS = 1.0 / 0.0254
EXPECTED_V8_SHA = "058e67293932ab7b6b46efd8200dc3f7642a03166814829f23b2385592123b3d"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan():
    d = json.loads(PLAN.read_text(encoding="utf8"))
    assert d["placement_count"] == 72 and len(d["placement"]) == 72
    assert len({p["ref"] for p in d["placement"]}) == 72
    assert all(p["manufacturer_library_footprint_instantiated"] is False
               for p in d["placement"]), "Do not rewrite frozen source plan"
    if sha(V8) != EXPECTED_V8_SHA:
        raise ValueError("V8 source changed: NOT safe to continue V9")
    if not V9.exists():
        raise FileNotFoundError(V9)
    return d


def active_v9():
    listing = D.call([str(D.LEDA), "session", "list"], timeout_s=20)
    if not listing.get("ok"):
        raise RuntimeError("Session list not available")
    js = """return await (async()=>{const p=await eda.dmt_Project.getCurrentProjectInfo();
      return {name:p?.friendlyName,pcb:p?.data?.find(x=>x?.pcb?.uuid)?.pcb?.uuid};})();"""
    match = []
    for row in listing["value"]:
        if row.get("status") != "alive" or row.get("headless") is not False:
            continue
        sid = row["sessionId"]
        result = D.call(D.build_invoke_args(sid, js, 8000), timeout_s=14)
        if result.get("ok") and (result.get("value") or {}).get("name") == V9.stem:
            match.append((sid, result["value"].get("pcb")))
    if len(match) != 1 or not match[0][1]:
        raise RuntimeError("No unambiguous alive V9 GUI; NEVER start another window")
    return match[0]


def js_convert(items, board_uuid):
    # No script is permitted to delete a pad until BOTH *new* footprint pads
    # are net-assigned AND occupy the same native XY as the original OEM pad.
    frozen = [{
        "ref": p["ref"],
        "x": round(p["centre_mm"][0] * MILS, 5),
        "y": round(-p["centre_mm"][1] * MILS, 5),
        "N": { "x": round(p["pads"][0]["centre_mm"][0] * MILS, 4),
               "y": round(-p["pads"][0]["centre_mm"][1] * MILS, 4),
               "net": "PGND" },
        "P": { "x": round(p["pads"][1]["centre_mm"][0] * MILS, 4),
               "y": round(-p["pads"][1]["centre_mm"][1] * MILS, 4),
               "net": "VOUT" },
    } for p in items]
    # Do not embed remote/custom code, only the frozen geometry input.
    return """return await(async()=>{
 const p=await eda.dmt_Project.getCurrentProjectInfo();
 if(p?.friendlyName!==%s)throw Error("Wrong native GUI project, refusing all edits");
 await eda.dmt_EditorControl.openDocument(%s);
 const d=(await eda.lib_Device.search(%s,%s,[],undefined,10,1))
   .find(x=>x.uuid===%s);
 if(!d || d.footprintUuid!==%s)throw Error("Real linked footprint/device missing");
 const W=%s;
 const report=[];
 for(const spec of W){
  const value={ref:spec.ref};
  try{
   const components=await eda.pcb_PrimitiveComponent.getAll();
   let existing=components.filter(x=>x.getState_Designator()===spec.ref);
   if(existing.length>1)throw Error("Duplicate existing native designators");
   let c;
   if(existing.length===1){c=existing[0];value.resumed=true;}
   else{
     c=await eda.pcb_PrimitiveComponent.create(d,1,spec.x,spec.y,0,false);
     if(!c)throw Error("Native component.create null");
     await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(),{
       designator:spec.ref,name:"T530X477M006ATE004",
       manufacturer:"KEMET",manufacturerId:"T530X477M006ATE004",addIntoBom:true
     });
     value.resumed=false;
   }
   const cp=await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId());
   if(cp.length!==2)throw Error("Native capacitor pins not 2");
   const lookup=Object.fromEntries(cp.map(x=>[x.getState_PadNumber(),x]));
   if(!lookup["1"]||!lookup["2"])throw Error("Native numbered pins missing");
   const pads=await eda.pcb_PrimitivePad.getAll();
   const original=Object.fromEntries(pads.filter(x=>[spec.ref+"_N",spec.ref+"_P"].includes(x.getState_PadNumber()))
      .map(x=>[x.getState_PadNumber().slice(-1),x]));
   // The left pad is KEMET minus 2; right pad is KEMET plus 1.
   for(const [key,pin] of [["P",lookup["1"]],["N",lookup["2"]]]){
     const want=spec[key];
     if(Math.hypot(pin.getState_X()-want.x,pin.getState_Y()-want.y)>.11)
       throw Error("Native pad XY mismatches OEM frozen plan");
     if(pin.getState_Net()!==want.net){
       if(pin.getState_Net()!=="")throw Error("Native pin assigned to wrong net");
       await eda.pcb_PrimitivePad.modify(pin.getState_PrimitiveId(),{net:want.net});
     }
   }
   const confirm=await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId());
   const nets=Object.fromEntries(confirm.map(x=>[x.getState_PadNumber(),x.getState_Net()]));
   if(nets["1"]!=="VOUT"||nets["2"]!=="PGND")throw Error("Native pin net assignment failed");
   for(const [key,orig] of Object.entries(original)){
     const want=spec[key];
     if(orig.getState_Net()!==want.net||Math.hypot(orig.getState_X()-want.x,orig.getState_Y()-want.y)>.11)
       throw Error("Old bare pad not coincident with replacement");
   }
   const ids=Object.values(original).map(x=>x.getState_PrimitiveId());
   if(ids.length && await eda.pcb_PrimitivePad.delete(ids)!==true)
     throw Error("Old bare pad delete not confirmed");
   const again=(await eda.pcb_PrimitivePad.getAll()).filter(x=>x.getState_PadNumber().startsWith(spec.ref+"_"));
   if(again.length)throw Error("Old bare pad not removed");
   value.ok=true;value.pins=nets;value.deleted_bare=ids.length;
  }catch(e){value.ok=false;value.error=String(e);}
  report.push(value);
  if(!value.ok)break;
 }
 return {requested:W.length,report,complete:report.length===W.length&&report.every(x=>x.ok),
   components:(await eda.pcb_PrimitiveComponent.getAll()).length,
   pads:(await eda.pcb_PrimitivePad.getAll()).length};
})();""" % (json.dumps(V9.stem), json.dumps(board_uuid),
           json.dumps(NAME), json.dumps(LIB), json.dumps(DEVICE),
           json.dumps("c9bdf53e779d4dd6a2eee1e6cecd4462"),
           json.dumps(frozen, separators=(",", ":")))


def batch(start: int, end: int):
    d = plan()
    if not (2 <= start <= end <= 72) or end - start > 11:
        raise ValueError("Only CHB02..72, maximum 12 items per invocation")
    receipt = HERE / f"g2_v9_chb_{start:02d}_{end:02d}_native_NOT_FOR_FAB.json"
    if receipt.exists():
        raise FileExistsError("Never replay an already recorded conversion batch")
    sid, board_uuid = active_v9()
    selected = [q for q in d["placement"] if start <= int(q["ref"][-2:]) <= end]
    assert len(selected) == end - start + 1
    before = sha(V9)
    result = D.call(D.build_invoke_args(sid, js_convert(selected, board_uuid), 59000),
                    timeout_s=71)
    payload = {"status":"G2_V9_NATIVE_REAL_COMPONENT_BATCH_NOT_FOR_FAB",
               "gui_session":sid,"board_uuid":board_uuid,
               "source_v8_sha256":sha(V8),"v9_before_disk_sha256":before,
               "range":[start,end],
               "reply":result,"v9_after_disk_sha256":sha(V9),
               "gui_left_open":True,"fabrication_approved":False}
    receipt.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n",
                       encoding="utf8",newline="\n")
    print(json.dumps({"range": [start,end], "ok":result.get("ok"),
                      "value":result.get("value"),"error":result.get("error"),
                      "receipt":str(receipt.relative_to(ROOT))},ensure_ascii=False,indent=2))
    if not result.get("ok") or not (result.get("value") or {}).get("complete"):
        raise RuntimeError("Batch incomplete: inspect live GUI before resuming; do NOT blindly retry")
    return 0


def verify():
    d = plan()
    sid, board_uuid = active_v9()
    expected = json.dumps([{"ref":q["ref"],"P":q["pads"][1],"N":q["pads"][0]}
                           for q in d["placement"]], separators=(",", ":"))
    js = """return await(async()=>{
      const p=await eda.dmt_Project.getCurrentProjectInfo();
      if(p?.friendlyName!==%s)throw Error("Wrong current project");
      await eda.dmt_EditorControl.openDocument(%s);
      const W=%s;
      const comps=await eda.pcb_PrimitiveComponent.getAll();
      const pads=await eda.pcb_PrimitivePad.getAll();
      const data=[];
      for(const q of W){
       const c=comps.filter(x=>x.getState_Designator()===q.ref);
       if(c.length!==1){data.push({ref:q.ref,error:"native component missing or duplicated"});continue}
       const pins=await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(c[0].getState_PrimitiveId());
       const entry={ref:q.ref,component_id:c[0].getState_PrimitiveId(),
          pins:pins.map(x=>({number:x.getState_PadNumber(),net:x.getState_Net(),
                 x:x.getState_X(),y:x.getState_Y()}))};
       const by=Object.fromEntries(entry.pins.map(x=>[x.number,x]));
       if(by["1"]?.net!=="VOUT"||by["2"]?.net!=="PGND"
         ||pins.length!==2)entry.error="pin/net count mismatch";
       if(pads.some(x=>x.getState_PadNumber().startsWith(q.ref+"_")))
         entry.error="bare pad still present";
       data.push(entry);
      }
      return {components:comps.length,pads:pads.length,
        lines:(await eda.pcb_PrimitiveLine.getAll()).length,
        vias:(await eda.pcb_PrimitiveVia.getAll()).length,
        networks:(await eda.pcb_Net.getAllNetsName()).length,
        native_capacitors_verified:data.filter(x=>!x.error).length,
        problems:data.filter(x=>x.error),
        capacitor_records:data};
    })();""" % (json.dumps(V9.stem),json.dumps(board_uuid),expected)
    result = D.call(D.build_invoke_args(sid, js, 59000), timeout_s=71)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error")))
    value = result["value"]
    summary = {k: value[k] for k in ("components","pads","lines","vias","networks",
                                      "native_capacitors_verified","problems")}
    summary.update({"status":"G2_V9_REAL_72_NATIVE_COMPONENTS_NOT_FOR_FAB",
                    "source_sha256":sha(V9),"source_v8_sha256":sha(V8),
                    "native_schematic_symbol_instances_verified":False,
                    "100A_main_copper_qualified":False,
                    "manufacturing_approved":False})
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if value["native_capacitors_verified"] != 72 or value["problems"]:
        raise RuntimeError("Not yet 72 verified native parts")
    if value["components"] != 149 or value["pads"] != 443 or value["lines"] != 403:
        raise RuntimeError("Native geometry count regression")
    CHECKPOINT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",
                          encoding="utf8",newline="\n")
    return 0


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    t = a.add_mutually_exclusive_group(required=True)
    t.add_argument("--check", action="store_true")
    t.add_argument("--batch", nargs=2, type=int)
    t.add_argument("--verify", action="store_true")
    opts = a.parse_args()
    if opts.check:
        d = plan()
        print(json.dumps({"selected":len(d["placement"]),"v8_sha256":sha(V8),
                          "v9_sha256":sha(V9),"fabrication_approved":False},indent=2))
    elif opts.batch:
        raise SystemExit(batch(*opts.batch))
    elif opts.verify:
        raise SystemExit(verify())
