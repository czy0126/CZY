"""Read-only local EasyEDA native C-number/footprint probe; never uses SSH.

From the existing Windows repository root:
  python tools/g2_local_native_capacitor_inventory.py --dry-run
  python tools/g2_local_native_capacitor_inventory.py --probe

No new EasyEDA windows, no extra processes, no component changes, no saves.
Requires the *already-running* EasyEDA run-api-gateway/bridge extension.
This does not constitute successful native device replacement.
"""
from __future__ import annotations
import argparse
import datetime
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
G = ROOT / "hardware/dcx_main/g2"
PARTS = G / "g2_v15_JLCPCB_EasyEDA_capacitor_native_part_priority_NOT_FOR_FAB.json"
EXPECTED_PROJECT = "dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB"

def request(url: str, payload: dict | None = None, timeout: int = 8) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type":"application/json"} if data is not None else {},
        method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def existing_bridge() -> str:
    for port in range(49620,49630):
        base = f"http://127.0.0.1:{port}"
        try:
            status = request(base+"/health",timeout=2)
            if status.get("service")=="easyeda-bridge" and status.get("edaConnected") is True:
                return base
        except (OSError,ValueError):
            continue
    raise RuntimeError(
        "No existing local EasyEDA API bridge+GUI found on 49620-49629. "
        "Leave existing EasyEDA open and check its run-api-gateway extension. "
        "Do NOT start more EDA windows and do NOT use SSH; SSH -b is for LTspice.")

def catalog_map() -> dict:
    record = json.loads(PARTS.read_text("utf-8"))
    rows = record["proposed_local_library_parts"]
    if len(rows)!=21 or record["already_swapped_in_native_CAD"] is not False:
        raise ValueError("Catalog evidence changed; refuse stale probe")
    unique = {}
    for row in rows:
        unique.setdefault(row["proposed_LCSC_part_number"],[]).append(row["ref"])
    if len(unique)!=7:
        raise ValueError("Expected seven exact JLC catalog variants")
    return unique

def probe():
    source = catalog_map()
    base = existing_bridge()
    js = r"""return await(async()=>{
      const project = await eda.dmt_Project.getCurrentProjectInfo();
      if(project?.friendlyName!==__PROJECT__)
        throw Error("Wrong active native project; no modification attempted");
      const comps = await eda.pcb_PrimitiveComponent.getAll();
      if(!Array.isArray(comps)||comps.length!==149)
        throw Error("Wrong active board; expected 149 native components");
      const refs=__REFS__, codes=__CODES__;
      const items=comps.filter(c=>refs.includes(c.getState_Designator()));
      if(items.length!==21)throw Error("Cap ref inventory changed");
      const seen=[];
      for(const c of items){
        const pads=await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(
          c.getState_PrimitiveId());
        seen.push({ref:c.getState_Designator(),primitiveId:c.getState_PrimitiveId(),
          name:c.getState_Name?.(),footprint:c.getState_Footprint?.(),
          supplierId:c.getState_SupplierId?.(),
          manufacturer:c.getState_Manufacturer?.(),
          manufacturerId:c.getState_ManufacturerId?.(),
          layer:c.getState_Layer(),rotation:c.getState_Rotation(),
          pads:(pads||[]).map(x=>({padNumber:x.getState_PadNumber(),
            net:x.getState_Net(),layer:x.getState_Layer(),
            x:x.getState_X(),y:x.getState_Y()}))});
      }
      const libraryUuid=await eda.lib_LibrariesList.getSystemLibraryUuid();
      const found=[];
      for(const code of codes){
        try{
          const entries=await eda.lib_Device.getByLcscIds(
            [code],libraryUuid,true);
          found.push({code,items:(entries||[]).map(x=>({
            uuid:x.uuid,libraryUuid:x.libraryUuid||libraryUuid,
            name:x.name,supplierId:x.supplierId,
            manufacturer:x.manufacturer,manufacturerId:x.manufacturerId,
            footprintName:x.footprintName,
            footprintUuid:x.footprintUuid,symbolUuid:x.symbolUuid}))});
        }catch(e){found.push({code,error:String(e)})}
      }
      return{project:project.friendlyName,parts:seen,
        systemLibraryUuid:libraryUuid,catalog:found,
        originalPCBchanged:false,componentsReplaced:0,saved:false};
    })();"""
    js = js.replace("__PROJECT__",json.dumps(EXPECTED_PROJECT))
    js = js.replace("__REFS__",json.dumps(sorted(
        {ref for refs in source.values() for ref in refs})))
    js = js.replace("__CODES__",json.dumps(sorted(source)))
    result = request(base+"/execute",{"code":js},timeout=115)
    record = {
        "schema":"D1_NATIVE_JLC_LIBRARY_PROBE_ONLY_V1",
        "bridge":"existing local EasyEDA bridge",
        "21_ref_to_official_C_numbers":source,
        "result":result,
        "board_altered":False,
        "device_replacement_claimed":False,
        "fabrication_approved":False,
    }
    path=G/("g2_JLC_NATIVE_READONLY_PROBE_"+
        datetime.datetime.now().strftime("%Y%m%d_%H%M%S")+
        "_NOT_FOR_FAB.json")
    with path.open("x",encoding="utf-8") as f:
        json.dump(record,f,ensure_ascii=False,indent=2)
        f.write("\n")
    print("Saved read-only native part/footprint evidence:",path)
    print("Do not swap devices until manufacturer+footprint matches are reviewed.")

def main():
    p=argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe",action="store_true")
    g.add_argument("--dry-run",action="store_true")
    args=p.parse_args()
    if args.dry_run:
        for code,refs in catalog_map().items():
            print(code,", ".join(refs))
        print("No GUI/SSH used.")
    else:
        probe()
if __name__=="__main__":
    main()
