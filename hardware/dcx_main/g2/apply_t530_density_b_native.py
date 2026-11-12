"""Real native EasyEDA G2 design-owned KEMET Density-B pad geometries, 16x5.

Pad dimensions/courtyard come from KEMET T52x/T530 2026 X1/7343-43
manufacturer Table2, validated against original 149-line board.
BUT: these are PCB pad primitives, not native component footprint instances,
not 72 schematic symbols, not ampacity/thermal/manufacturing approval.

python hardware/dcx_main/g2/apply_t530_density_b_native.py --check
python hardware/dcx_main/g2/apply_t530_density_b_native.py --apply
python hardware/dcx_main/g2/apply_t530_density_b_native.py --resume

If apply was already attempted on saved candidate NEVER run apply again.
"""
from __future__ import annotations
import argparse,hashlib,json,shutil,sys,time
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
G1=ROOT/"hardware/dcx_main/g1"
sys.path.insert(0,str(G1))
import run_driver_drc as D
import route_open_connections as R
import plan_t530_72_oem_density_b as P

PREFIX="g2_t530_oem_density_b"
TARGET=HERE/"dcx_main_board_g2_T530_OEM_DENSITY_B_PROVISIONAL_144_LANDS_NOT_FOR_FAB.eprj2"
PLAN=P.OUT
DELTA=HERE/(PREFIX+"_drc_delta.json")
PADS=HERE/(PREFIX+"_reopen_readback.json")
READ_JS=G1/"read_driver_route.js"
DRC_JS=G1/"driver_drc.js"
MIL=1/.0254

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def dump(name, obj):
    (HERE/(PREFIX+"_"+name+".json")).write_text(json.dumps(
      obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")

def checkplan():
    d=P.make()
    if d["preflight_problems"]:raise ValueError(d["preflight_problems"])
    if not PLAN.is_file() or json.loads(PLAN.read_text(encoding="utf-8"))!=d:
        raise ValueError("Frozen manufacturer-derived pad plan not in source control")
    if sha(P.SOURCE)!=d["source_149line_sha256"]:
        raise ValueError("Frozen 149 native CAD source hash mismatch")
    return d

def pad_rows(plan):
    return [pad for part in plan["placement"] for pad in part["pads"]]

def js(rows):
    v=[{"num":p["number"],"net":p["net"],
        "x":round(p["centre_mm"][0]*MIL,7),
        "y":round(-p["centre_mm"][1]*MIL,7),
        "w":round(p["size_mm"][0]*MIL,7),
        "h":round(p["size_mm"][1]*MIL,7)} for p in rows]
    return """return await (async()=>{
      const p=await eda.dmt_Project.getCurrentProjectInfo();
      const board=p?.data?.find(x=>x?.pcb?.uuid);
      if(!board)throw new Error("native PCB document missing");
      await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
      const old=await eda.pcb_PrimitivePad.getAll();
      const names=new Set(old.map(p=>p.getState_PadNumber()));
      const S=%s;
      if(S.some(p=>names.has(p.num)))
          throw new Error("an OEM trial pad exists; refusing double apply");
      let created=[];
      for(const pad of S){
        try{
          const p=await eda.pcb_PrimitivePad.create(
             1,pad.num,pad.x,pad.y,0,['RECT',pad.w,pad.h],pad.net,null);
          if(!p || p.getState_Net()!==pad.net ||
                    p.getState_PadNumber()!==pad.num)
            throw new Error("new native OEM land readback mismatch");
          created.push({ok:true,num:pad.num,net:pad.net});
        }catch(e){created.push({ok:false,num:pad.num,error:String(e)});break;}
      }
      return {requested:S.length,created,all_created:
        created.length===S.length && created.every(p=>p.ok)};
    })();""" % json.dumps(v,separators=(",",":"))

def invoke(s,script):
    return D.call(D.build_invoke_args(s,script),timeout_s=160)

def open_board(label):
    v=D.call(D.build_open_args(TARGET),timeout_s=110)
    dump(label+"_open",v)
    sid=(v.get("value") or {}).get("sessionId")
    if not sid:return None
    time.sleep(D.SETTLE_S)
    ping=D.call(D.build_ping_args(sid),timeout_s=45)
    dump(label+"_ping",ping)
    if not ping.get("ok"):
        dump(label+"_close",D.call(D.build_close_args(sid)))
        return None
    return sid

def review(actual,plan):
    old=json.loads((G1/"g1_control_direct_reopen_readback.json").read_text(encoding="utf-8"))
    if not old.get("ok"):raise ValueError("149-line old native readback absent")
    old=old["value"]
    for name,n in (("components",77),("lines",149),("vias",18),("nets",65)):
        if len(actual[name])!=n or Counter(
              json.dumps(x,sort_keys=True) for x in actual[name])!=Counter(
              json.dumps(x,sort_keys=True) for x in old[name]):
            raise ValueError("Existing native G1 "+name+" geometry modified")
    target={p["number"]:p for p in pad_rows(plan)}
    original=[];new={}
    for pad in actual["pads"]:
        num=str(pad["PadNumber"])
        if num not in target:
            original.append(pad);continue
        if num in new or pad.get("ref"):
            raise ValueError("New OEM-pad-only trial duplicate/component mismatch")
        want=target[num]
        if (pad["Net"]!=want["net"] or int(pad["Layer"])!=1
            or abs(pad["X"]*.0254-want["centre_mm"][0])>.006
            or abs(-pad["Y"]*.0254-want["centre_mm"][1])>.006):
            raise ValueError("Native manufacturer nominal landing net/layer/XY mismatch "+num)
        shape=pad.get("Pad") or []
        if (len(shape)<3 or shape[0]!="RECT"
            or abs(shape[1]*.0254-want["size_mm"][0])>.006
            or abs(shape[2]*.0254-want["size_mm"][1])>.006):
            raise ValueError("Native manufacturer landing pad dimensions mismatch "+num)
        new[num]=pad
    if set(new)!=set(target) or len(actual["pads"])!=443:
        raise ValueError("Required 144 OEM nominal native lands missing or duplicate")
    if Counter(json.dumps(x,sort_keys=True) for x in original)!=Counter(
           json.dumps(x,sort_keys=True) for x in old["pads"]):
        raise ValueError("Existing G1 old 299 native pads changed")
    return {"original_77_components_149_lines_18_vias_65_nets_299_pads_preserved":True,
            "new_144_netted_manufacturer_nominal_lands":len(new),
            "true_72_component_instances_added":0,
            "real_schematic_parity_qualified":False,
            "manufacturer_nominal_courtyard_grid_screened":True,
            "fabrication_approved":False}

def resume():
    plan=checkplan()
    if not TARGET.is_file() or sha(TARGET)==sha(P.SOURCE):
        raise RuntimeError("No saved distinct native candidate; no double-apply")
    digest=sha(TARGET)
    sid=open_board("reopen")
    if not sid:return 1
    try:
        rb=invoke(sid,READ_JS.read_text(encoding="utf-8"))
        dump("reopen_readback",rb)
        if not rb.get("ok"):return 1
        audit=review(rb["value"],plan)
        drc=invoke(sid,DRC_JS.read_text(encoding="utf-8"))
        dump("drc_raw",drc)
        if not drc.get("ok"):return 1
    finally:
        dump("reopen_close",D.call(D.build_close_args(sid)))
    if digest!=sha(TARGET):raise ValueError("Read-only native reopen changed source bytes")
    cat=R.categories(drc)
    if cat.get("Physical Error",0)>0:
        raise RuntimeError("Native OEM trial has physical DRC errors")
    report={"status":"REAL_144_OEM_DIMENSIONED_PROVISIONAL_NATIVE_PAD_CAD_NOT_FOR_FAB",
            "source_sha256":sha(P.SOURCE),"candidate_sha256":sha(TARGET),
            "plan_sha256":sha(PLAN),"native_drc":cat,
            "readback":audit,
            "real_72_schematic_component_instances":False,
            "manufacturer_official_land_dimensions_met":True,
            "real_100A_both_pole_copper_qualified":False,
            "fabrication_approved":False}
    dump("drc_delta",report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0

def apply():
    plan=checkplan()
    if TARGET.exists():raise FileExistsError("OEM trial board exists; ONLY --resume")
    before=sha(P.SOURCE)
    shutil.copy2(P.SOURCE,TARGET)
    sid=open_board("apply")
    if not sid:return 1
    saved=False
    try:
        rows=pad_rows(plan)
        for i in range(0,len(rows),24):
            result=invoke(sid,js(rows[i:i+24]))
            dump("apply_batch_"+str(i//24+1),result)
            if not result.get("ok") or not (result.get("value") or {}).get("all_created"):
                print("Native OEM trial batch failed or partial; don't repeat")
                return 1
        result=invoke(sid,"return await eda.pcb_Document.save();")
        dump("apply_save",result)
        saved=bool(result.get("ok") and result.get("value") is True)
        if saved:time.sleep(30)
    finally:
        dump("apply_close",D.call(D.build_close_args(sid)))
    if not saved or sha(P.SOURCE)!=before or sha(TARGET)==before:
        raise RuntimeError("Native save/source identity failure")
    return resume()

def main():
    p=argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    g.add_argument("--resume",action="store_true")
    opts=p.parse_args()
    if opts.check:
        r=checkplan()
        print(json.dumps({"source":r["source_149line_PCB"],
          "sha":r["source_149line_sha256"],
          "nominal_land_derived":r["nominal_land_geometry_derived_from_manufacturer"],
          "part_count":r["placement_count"],"pads":r["trial_pad_count"],
          "problems":r["preflight_problems"],"fab":r["fabrication_approved"]},indent=2))
        return 0
    return apply() if opts.apply else resume()

if __name__=="__main__":raise SystemExit(main())
