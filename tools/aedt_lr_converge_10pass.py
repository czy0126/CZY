# -*- coding: utf-8 -*-
"""Ansys Maxwell 2025R2: independent 10-pass convergence check, 1A concept.

Copies previously validated external-lead 1A model. Never treats copper leads,
stock ferrite or a returned adaptive solution as OEM, true 0.92 uH, AC loss or
high-current hardware qualification. This is only a convergence capability test.
"""
import os,sys,shutil,json,hashlib,traceback
ROOT=r"D:\workshop\design_48v-2v"
OUT=os.path.join(ROOT,"design","v3","maxwell","local_runs")
SRC=os.path.join(OUT,"ELP38_Lr_1A_EXTERNAL_LEADS_MAGNETOSTATIC_NOT_FOR_FAB.aedt")
DEST=os.path.join(OUT,"ELP38_Lr_1A_EXTERNAL_LEADS_10PASS_NOT_FOR_FAB.aedt")
RECEIPT=os.path.join(OUT,"ELP38_Lr_1A_EXTERNAL_LEADS_10PASS_result.json")
d={"kind":"REAL_AEDT_MAGNETOSTATIC_MESH_CONVERGENCE_TRIAL","status":"STARTING",
   "geometry":"CONNECTED_TWO_TURN_PLUS_TWO_ARTIFICIAL_EXTERNAL_LEADS",
   "core_material":"STOCK_FERRITE_NOT_N97_100C",
   "requested_maximum_passes":10,"current_a":1,
   "solver_returned":False,"mesh_converged":False,
   "saturation_and_L_I_verified":False,"ac_loss_verified":False,
   "manufacturing_approved":False}
def store():
    with open(RECEIPT,"w") as f:json.dump(d,f,indent=2)
try:
    if os.path.exists(DEST):raise RuntimeError("Never overwrite prior solver candidate")
    if not os.path.isfile(SRC):raise RuntimeError("No exact verified connected coil case")
    shutil.copy2(SRC,DEST)
    sys.path.append(r"D:\ANSYS Inc\v252\AnsysEM\PythonFiles\DesktopPlugin")
    import ScriptEnv
    ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
    oDesktop.OpenProject(DEST)
    project=oDesktop.SetActiveProject(os.path.splitext(os.path.basename(DEST))[0])
    design=project.SetActiveDesign("Lr_2turn_geometry_only")
    a=design.GetModule("AnalysisSetup")
    a.EditSetup("Setup1",["NAME:Setup1",
            "MaximumPasses:=",10,"MinimumPasses:=",2,
            "MinimumConvergedPasses:=",2,
            "PercentRefinement:=",25,"SolveFieldOnly:=",False,
            "PercentError:=",3,"SolveMatrixAtLast:=",True])
    project.Save()
    val=design.ValidateDesign()
    d["validated"]=bool(val)
    d["validation_messages"]=list(oDesktop.GetMessages("","",0))
    if not val:raise RuntimeError("10pass native design validation failed")
    result=design.Analyze("Setup1")
    d["return_value"]=str(result)
    messages=list(oDesktop.GetMessages("","",0))
    d["solver_messages"]=messages
    if result not in (0,None):
        raise RuntimeError("Ansys Analyze failure "+repr(result))
    d["solver_returned"]=True
    nonconverged=any("did not converge" in m.lower() for m in messages)
    d["mesh_converged"]=not nonconverged
    d["status"]=("SOLVER_RETURNED_AND_NO_NONCONVERGENCE_WARNING_CONCEPT_ONLY"
                if not nonconverged else
                "SOLVER_RETURNED_BUT_MESH_NOT_CONVERGED_CONCEPT_ONLY")
    project.Save()
except:
    d["status"]="TEN_PASS_CONVERGENCE_TRIAL_FAILED_NOT_FOR_FAB"
    d["error"]=traceback.format_exc()
    try:d["messages"]=list(oDesktop.GetMessages("","",0))
    except:pass
finally:
    try:store()
    except:pass
    try:ScriptEnv.Shutdown()
    except:pass
