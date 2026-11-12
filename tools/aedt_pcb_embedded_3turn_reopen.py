# -*- coding: utf-8 -*-
"""Read-only Ansys AEDT re-open of exact embedded-PCB three-turn native model.

Checks the *real* three CAD solids survived saving, and bytes are unchanged.
NOT a magnetostatic solve, 100C B-H assignment, 100A or fab approval.
"""
import hashlib,json,os,sys,traceback

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET=os.path.join(ROOT,"hardware","dcx_main","maxwell",
  "ELP38_Lr_PCB_EMBEDDED_3TURN_6LAYER_4PTH_NATIVE_GEOMETRY_NOT_FOR_FAB.aedt")
EVIDENCE=os.path.join(ROOT,"hardware","dcx_main","maxwell",
  "ELP38_Lr_PCB_EMBEDDED_3TURN_6LAYER_4PTH_NATIVE_REOPEN_NOT_FOR_FAB.json")
def hashbytes(p):
    return hashlib.sha256(open(p,"rb").read()).hexdigest()
data={"status":"STARTING","native_project_sha256_before":hashbytes(TARGET),
 "source":"ELP38_Lr_PCB_EMBEDDED_3TURN_6LAYER_4PTH_NATIVE_GEOMETRY_NOT_FOR_FAB.aedt",
 "real_n97_100c_model_verified":False,"L_I_solved":False,
 "200khz_AC_loss_verified":False,"fabrication_approved":False}
try:
    sys.path.append(r"D:\ANSYS Inc\v252\AnsysEM\PythonFiles\DesktopPlugin")
    import ScriptEnv
    ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
    oDesktop.OpenProject(TARGET)
    proj=oDesktop.SetActiveProject(os.path.splitext(os.path.basename(TARGET))[0])
    design=proj.SetActiveDesign("Lr_PCB_3turn_geometry")
    ed=design.SetActiveEditor("3D Modeler")
    solids=list(ed.GetObjectsInGroup("Solids"))
    data["native_reopened_solids"]=solids
    required={"I38_GENERIC_FERRITE","E_BACK","PCB_LR_CU_000","Region"}
    if set(solids)!=required:
        raise ValueError("Native 3-turn CAD solids mismatch "+str(solids))
    if not len(ed.GetFaceIDs("PCB_LR_CU_000"))>12:
        raise ValueError("Single copper solid missing detailed PCB track/via faces")
    data["single_multilayer_copper_solid_face_count"]=len(ed.GetFaceIDs("PCB_LR_CU_000"))
    data["native_3turn_one_copper_body_reopened"]=True
    data["status"]="REAL_NATIVE_3TURN_PCB_MAXWELL_CAD_REOPENED_GEOMETRY_ONLY_NOT_FOR_FAB"
except:
    data["error"]=traceback.format_exc()
    data["status"]="NATIVE_MAXWELL_PCB_REOPEN_FAILED_NOT_FOR_FAB"
finally:
    try:ScriptEnv.Shutdown()
    except:pass
    data["native_project_sha256_after"]=hashbytes(TARGET)
    data["read_only_file_preserved"]=data["native_project_sha256_before"]==data["native_project_sha256_after"]
    if not data["read_only_file_preserved"]:
        data["status"]="NATIVE_MAXWELL_READ_ONLY_CHANGED_CAD_FAILED"
    with open(EVIDENCE,"w",encoding="utf-8") as f:
        json.dump(data,f,ensure_ascii=False,indent=2);f.write("\n")
    print(data["status"],data.get("single_multilayer_copper_solid_face_count"),data["read_only_file_preserved"])
