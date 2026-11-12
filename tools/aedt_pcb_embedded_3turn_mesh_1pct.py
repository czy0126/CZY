# -*- coding: utf-8 -*-
"""Independent REAL Ansys Maxwell 2025R2 3-turn PCB mesh refinement.

Based on the already solved / committed 1A physical six-layer PCB CAD.
Do NOT conflate mesh independence with material/model accuracy. Generic
ferrite, assumed 25um barrels and artificial current extension leads
remain NOT_FOR_FAB. Never overwrite earlier 7% 2-pass result.

Main criterion: 1% energy error, 2 consecutively converged passes, 25%
adaptive tetra refinement, max 24 passes. Full real native convergence
table and field energies must be independently assessed after completion.
"""
import os,json,hashlib,shutil,sys,traceback,time
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE=os.path.join(ROOT,"hardware","dcx_main","maxwell")
SOURCE=os.path.join(BASE,"ELP38_Lr_PCB_3TURN_6LAYER_1A_GENERIC_FERRITE_FEM_NOT_FOR_FAB.aedt")
RUN=os.path.join(ROOT,"design","v3","maxwell","local_runs")
STEM="ELP38_Lr_PCB_3TURN_1A_GENERIC_FERRITE_ADAPTIVE_1PCT_TRIAL_NOT_FOR_FAB"
TARGET=os.path.join(RUN,STEM+".aedt")
EVID=os.path.join(RUN,STEM+".receipt.json")
CONV=os.path.join(RUN,STEM+".conv")
MAX_PASSES=24
TARGET_ENERGY_PCT=1.0
MIN_CONVERGED=2
REFINE_PCT=25
state={"schema":"REAL_NATIVE_KICAD_THREE_TURN_MAXWELL_MESH_INDEPENDENCE_V1",
 "status":"NOT_STARTED", "base":SOURCE,"candidate":TARGET,
 "requested_energy_error_pct":TARGET_ENERGY_PCT,
 "maximum_adaptive_passes":MAX_PASSES,
 "minimum_converged_passes":MIN_CONVERGED,
 "refinement_percent":REFINE_PCT,
 "same_geometry_as_parent":False,
 "material_stock_ferrite_not_n97":True,
 "current_a":1.0,"actual_maxwell_solver_finished":False,
 "native_solver_converged":False,"numerical_grid_independence_accepted":False,
 "real_n97_100c_L_I_or_200khz_loss_qualified":False,
 "fabrication_approved":False}
def sha(path):
 h=hashlib.sha256()
 with open(path,"rb") as f:
  for b in iter(lambda:f.read(1048576),b""):h.update(b)
 return h.hexdigest()
def save():
 with open(EVID,"w",encoding="utf-8") as f:
  json.dump(state,f,ensure_ascii=False,indent=2);f.write("\n")
def log(mark):
 state.setdefault("steps",[]).append(mark);save()
try:
 if not os.path.isfile(SOURCE):raise RuntimeError("No committed genuine native solved AEDT source")
 if os.path.exists(TARGET) or os.path.exists(EVID):
  raise RuntimeError("REFUSE to overwrite existing stricter Ansys run")
 os.makedirs(RUN,exist_ok=True)
 state["base_sha256"]=sha(SOURCE)
 if not os.path.isfile(os.path.join(BASE,"ELP38_Lr_PCB_3TURN_6LAYER_1A_GENERIC_FERRITE_FEM_NOT_FOR_FAB.evidence.json")):
  raise RuntimeError("Missing original Ansys source / convergence evidence")
 shutil.copy2(SOURCE,TARGET)
 log("SOURCE_LOCKED_COPIED_INDEPENDENTLY")
 sys.path.append(r"D:\ANSYS Inc\v252\AnsysEM\PythonFiles\DesktopPlugin")
 import ScriptEnv
 ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
 oDesktop.OpenProject(TARGET)
 pr=oDesktop.SetActiveProject(os.path.splitext(os.path.basename(TARGET))[0])
 design=pr.SetActiveDesign("Lr_PCB_3turn_geometry")
 ed=design.SetActiveEditor("3D Modeler")
 solids=set(ed.GetObjectsInGroup("Solids"))
 if solids!={"I38_GENERIC_FERRITE","E_BACK","PCB_LR_CU_000","Region"}:
  raise RuntimeError("Unexpected real six-layer 3-turn native geometry!")
 state["actual_native_solids"]=sorted(solids)
 # Confirm current excitation persists before editing only mesh parameters.
 bs=design.GetModule("BoundarySetup")
 state["native_assignments"]=list(bs.GetExcitations())
 if not any("PCB_LR_DC_1A_IN" in x for x in state["native_assignments"]) or not any(
    "PCB_LR_DC_1A_OUT" in x for x in state["native_assignments"]):
  raise RuntimeError("Parent actual current excitation not retained")
 state["same_geometry_as_parent"]=True
 log("SAME_NATIVE_KICAD_COPPER_AND_1A_CURRENT_EXCITATION")
 mod=design.GetModule("AnalysisSetup")
 mod.EditSetup("Setup1",[
   "NAME:Setup1",
   "MaximumPasses:=",MAX_PASSES,
   "MinimumPasses:=",3,
   "MinimumConvergedPasses:=",MIN_CONVERGED,
   "PercentRefinement:=",REFINE_PCT,
   "SolveFieldOnly:=",False,
   "PercentError:=",TARGET_ENERGY_PCT,
   "SolveMatrixAtLast:=",True])
 pr.Save()
 log("STRICTER_1PCT_SETUP_SAVED")
 validate=design.ValidateDesign()
 state["native_validate_design_passed"]=bool(validate)
 state["native_validation_messages"]=list(oDesktop.GetMessages("","",0))[-15:]
 if not validate:raise RuntimeError("Actual Maxwell ValidateDesign failed")
 state["status"]="RUNNING_REAL_MAXWELL_ADAPTIVE"
 save()
 start=time.time()
 ret=design.Analyze("Setup1")
 state["seconds"]=round(time.time()-start,1)
 state["analyze_return"]=str(ret)
 msgs=list(oDesktop.GetMessages("","",0))
 state["last_native_messages"]=msgs[-65:]
 state["actual_maxwell_solver_finished"]=ret in (0,None) and any(
     "Normal completion" in x for x in msgs)
 state["native_solver_converged"]=state["actual_maxwell_solver_finished"] and not any(
    "did not converge" in x.lower() or "not converged" in x.lower() for x in msgs)
 pr.Save()
 try:
  design.ExportConvergence("Setup1","",CONV)
  if os.path.isfile(CONV):
   state["convergence_sha256"]=sha(CONV)
   state["convergence_bytes"]=os.path.getsize(CONV)
 except Exception as e:state["convergence_export_error"]=repr(e)
 state["status"]=("REAL_STRICTER_MESH_SOLVER_CONVERGED_REQUIRES_INDEPENDENCE_AUDIT"
    if state["native_solver_converged"] else
    "REAL_STRICTER_MESH_SOLVER_NOT_CONVERGED_NOT_FOR_FAB")
except BaseException:
 state["status"]="REAL_STRICTER_MESH_RUN_FAILED_NOT_FOR_FAB"
 state["error"]=traceback.format_exc()
 try:state["on_failure_messages"]=list(oDesktop.GetMessages("","",0))[-40:]
 except BaseException:pass
finally:
 try:
  if os.path.isfile(TARGET):
   state["candidate_sha256"]=sha(TARGET)
   state["candidate_size_bytes"]=os.path.getsize(TARGET)
  save()
 except BaseException:pass
 try:ScriptEnv.Shutdown()
 except BaseException:pass
