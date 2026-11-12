# -*- coding: utf-8 -*-
"""Run an actual 30-pass magnetostatic adaptive study, independent native copy.

Geometry: 2-turn ELP38 concept plus external artificial current terminals.
Material: stock ferrite (NOT OEM N97 100C).
No extracted inductance, L(I), core/eddy loss or manufacturing approval.
This is a real solver mesh-convergence experiment, not an output of pytest.
"""
import json,os,shutil,sys,traceback,hashlib

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC=os.path.join(ROOT,"hardware","dcx_main","maxwell",
   "ELP38_Lr_1A_EXTERNAL_LEADS_10PASS_CONCEPT_NOT_CONVERGED_NOT_FOR_FAB.aedt")
RUN=os.path.join(ROOT,"design","v3","maxwell","local_runs")
DEST=os.path.join(RUN,"ELP38_Lr_1A_EXTERNAL_LEADS_30PASS_NOT_FOR_FAB.aedt")
EVID=os.path.join(RUN,"ELP38_Lr_1A_EXTERNAL_LEADS_30PASS_receipt.json")
r={"schema":"MAXWELL_N97_UNQUALIFIED_1A_30PASS_SOLVER_TRIAL",
   "input":SRC,"destination":DEST,"status":"NOT_RUN",
   "source_material_verified_N97_100C":False,
   "core_gap_manufacturing_verified":False,
   "real_terminal_winding_qualified":False,
   "target_inductance_extracted":False,
   "L_vs_I_qualified":False,
   "ac_loss_or_SOА_qualified":False,
   "mesh_convergence_verified":False,
   "fabrication_approved":False,
   "maximum_passes":30,"percent_error_requested":2.0,
   "requested_refine_percent":25,"minimum_converged_passes":2}
def save():
    with open(EVID,"w") as f:json.dump(r,f,indent=2)
try:
    if not os.path.isfile(SRC):raise RuntimeError("Original real CAD solver source missing")
    if os.path.exists(DEST):raise RuntimeError("Refuse overwrite previous FEM trial")
    if not os.path.isdir(RUN):os.makedirs(RUN)
    shutil.copy2(SRC,DEST)
    r["input_sha256"]=hashlib.sha256(open(SRC,"rb").read()).hexdigest()
    r["status"]="COPIED_UNQUALIFIED_AEDT_PARENT"
    save()
    sys.path.append(r"D:\ANSYS Inc\v252\AnsysEM\PythonFiles\DesktopPlugin")
    import ScriptEnv
    ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
    oDesktop.OpenProject(DEST)
    project=oDesktop.SetActiveProject(os.path.splitext(os.path.basename(DEST))[0])
    design=project.SetActiveDesign("Lr_2turn_geometry_only")
    a=design.GetModule("AnalysisSetup")
    a.EditSetup("Setup1",["NAME:Setup1","MaximumPasses:=",30,
        "MinimumPasses:=",2,"MinimumConvergedPasses:=",2,
        "PercentRefinement:=",25,"SolveFieldOnly:=",False,
        "PercentError:=",2,"SolveMatrixAtLast:=",True])
    project.Save()
    v=design.ValidateDesign()
    r["native_validation_passed"]=bool(v)
    r["validation_messages"]=list(oDesktop.GetMessages("","",0))
    if not v:raise RuntimeError("Actual Maxwell project validation failed")
    r["status"]="ANALYZE_RUNNING"
    save()
    result=design.Analyze("Setup1")
    r["analyze_return"]=str(result)
    messages=list(oDesktop.GetMessages("","",0))
    r["solver_messages"]=messages
    r["solver_success"]=result in (0,None) and any(
         "Normal completion" in m for m in messages)
    r["non_convergence_reported"]=any("did not converge" in m.lower() for m in messages)
    r["mesh_convergence_verified"]=r["solver_success"] and not r["non_convergence_reported"]
    r["status"]=("REAL_SOLVER_RETURNED_MESH_CONVERGED_CONCEPT_ONLY_NOT_FAB"
         if r["mesh_convergence_verified"] else
         "REAL_SOLVER_RETURNED_BUT_NOT_CONVERGED_NOT_FAB" if r["solver_success"]
         else "MAXWELL_ANALYZE_FAILED")
    project.Save()
except:
    r["status"]="MAXWELL_30PASS_TRIAL_FAILED_NOT_FOR_FAB"
    r["error"]=traceback.format_exc()
    try:r["messages"]=list(oDesktop.GetMessages("","",0))
    except:pass
finally:
    try:
        if os.path.isfile(DEST):
            r["output_sha256"]=hashlib.sha256(open(DEST,"rb").read()).hexdigest()
    except:pass
    try:save()
    except:pass
    try:ScriptEnv.Shutdown()
    except:pass
