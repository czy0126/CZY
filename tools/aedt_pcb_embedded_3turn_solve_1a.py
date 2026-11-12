# -*- coding: utf-8 -*-
"""ACTUAL Maxwell 3D solver experiment on native 6-layer 3-turn PCB geometry.

This runs on a fresh independent trial COPY of the saved+reopened Ansys
model. It is never a 100 C N97 L(I), 200kHz AC/thermal current or
fabrication qualification. It has artificially extended copper leads,
generic stock ferrite, 25um assumed barrels, approximate PCB dielectric
and a 2.356mm analytically estimated gap outside 2mm TDK example range.

No simulated result (even a real ANSYS solve) may be called "passed P0".
"""
import hashlib,json,os,shutil,sys,time,traceback

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE=os.path.join(ROOT,"hardware","dcx_main","maxwell",
  "ELP38_Lr_PCB_EMBEDDED_3TURN_6LAYER_4PTH_NATIVE_GEOMETRY_NOT_FOR_FAB.aedt")
GEOM_EVID=os.path.join(ROOT,"hardware","dcx_main","maxwell",
  "ELP38_Lr_PCB_EMBEDDED_3TURN_6LAYER_4PTH_NATIVE_GEOMETRY_NOT_FOR_FAB.evidence.json")
RUN=os.path.join(ROOT,"design","v3","maxwell","local_runs")
TARGET=os.path.join(RUN,"ELP38_Lr_PCB_3TURN_6LAYER_REAL_1A_FEM_GENERIC_FERRITE_V2_NOT_FOR_FAB.aedt")
RESULT=os.path.join(RUN,"ELP38_Lr_PCB_3TURN_6LAYER_REAL_1A_FEM_GENERIC_FERRITE_V2_receipt.json")
CONV=os.path.join(RUN,"ELP38_Lr_PCB_3TURN_6LAYER_REAL_1A_FEM_GENERIC_FERRITE_V2.convergence.conv")
CURRENT_A=1.0
MAX_PASSES=3
state={"schema":"REAL_AEDT_PCB_3TURN_CURRENT_EXCITATION_1A_V1",
       "status":"STARTING","source":SOURCE,"target":TARGET,
       "excitation_a":CURRENT_A,"maximum_mesh_passes":MAX_PASSES,
       "solver_normal_completion":False,"native_validate_design_passed":False,
       "native_mesh_converged":False,"nominal_Lr_0p92uH_verified":False,
       "N97_100C_BH_verified":False,"L_I_bias_100A_verified":False,
       "AC_200khz_skin_fringe_loss_verified":False,
       "PCB_25um_PTH_and_70um_inner_copper_vendor_approved":False,
       "whole_16mm_assembly_verified":False,"manufacturing_approved":False}
def digest(path):
    return hashlib.sha256(open(path,"rb").read()).hexdigest()
def save():
    with open(RESULT,"w",encoding="utf-8") as f:
        json.dump(state,f,ensure_ascii=False,indent=2);f.write("\n")
def step(name):
    state.setdefault("steps",[]).append(name)
    save()

try:
    if not os.path.isfile(SOURCE):
        raise RuntimeError("No real saved original 3turn KiCad-derived native AEDT")
    if os.path.exists(TARGET) or os.path.exists(RESULT):
        raise RuntimeError("Refuse to repeat/overwrite any existing solver trial")
    evidence=json.load(open(GEOM_EVID,"r",encoding="utf-8"))
    state["source_sha256"]=digest(SOURCE)
    if evidence["native_project_sha256"]!=state["source_sha256"]:
        raise RuntimeError("Source native AEDT drifted from real reopened geometry")
    if evidence["three_series_turns_one_copper_solid"] is not True:
        raise RuntimeError("Missing native 3turn copper continuity")
    if evidence["real_N97_100c_nonlinear_BH_applied"] is not False:
        raise RuntimeError("Model material provenance changed; review first")
    os.makedirs(RUN,exist_ok=True)
    shutil.copy2(SOURCE,TARGET)
    step("COPY_AND_SHA_LOCK_REAL_KICAD_GENERATED_3TURN_SOURCE")
    sys.path.append(r"D:\ANSYS Inc\v252\AnsysEM\PythonFiles\DesktopPlugin")
    import ScriptEnv
    ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
    oDesktop.OpenProject(TARGET)
    project=oDesktop.SetActiveProject(os.path.splitext(os.path.basename(TARGET))[0])
    design=project.SetActiveDesign("Lr_PCB_3turn_geometry")
    ed=design.SetActiveEditor("3D Modeler")
    required={"I38_GENERIC_FERRITE","E_BACK","PCB_LR_CU_000","Region"}
    solids=set(ed.GetObjectsInGroup("Solids"))
    if solids!=required:raise RuntimeError("Native CAD different from 4 solids: "+str(solids))
    state["solids_verified"]=sorted(solids)
    step("REOPENED_REAL_PCB_SPIRAL_FOR_1A_DC_EXCITATION")
    # GetFaceCenter on the 10 cylindrical via barrels terminates COM 0x80020009.
    # Use exact UNIQUE end-face positions; see official 2025R2 Ansys
    # Maxwell Scripting GetFaceByPosition, not a planar-face enumeration.
    ends={}
    for name,x,y,z in (("IN",-60.,-19.,5.965),
                       ("OUT",60.,-28.,4.435)):
        fid=ed.GetFaceByPosition([
            "NAME:FaceParameters","BodyName:=","PCB_LR_CU_000",
            "XPosition:=",str(x)+"mm","YPosition:=",str(y)+"mm",
            "ZPosition:=",str(z)+"mm"])
        if not fid:raise RuntimeError("Ansys did not select actual "+name+" end face")
        ends[name]=(int(fid),[x,y,z])
    if ends["IN"][0]==ends["OUT"][0]:
        raise RuntimeError("Both 1A terminal face IDs identical")
    state["actual_end_terminal_faces"]=ends
    if set(ends)!={"IN","OUT"}:
        raise RuntimeError("No two real conductor terminal boundary faces: "+repr(ends))
    step("IDENTIFIED_TWO_EXTERNAL_CONDUCTOR_BOUNDARY_FACES")
    bs=design.GetModule("BoundarySetup")
    for name,(fid,_) in ends.items():
        bs.AssignCurrent(["NAME:PCB_LR_DC_1A_"+name,
            "Faces:=",[fid],"Current:=","1A",
            "IsSolid:=",True,"Point out of terminal:=",name=="OUT"])
    step("ASSIGNED_REAL_CURRENT_TO_NATIVE_3D_MODEL_TERMINALS")
    solver=design.GetModule("AnalysisSetup")
    solver.InsertSetup("Magnetostatic",
       ["NAME:Setup1","MaximumPasses:=",MAX_PASSES,
        "MinimumPasses:=",1,"MinimumConvergedPasses:=",1,
        "PercentRefinement:=",20,"SolveFieldOnly:=",False,
        "PercentError:=",7,"SolveMatrixAtLast:=",True])
    project.Save()
    step("ACTUAL_NATIVE_MAXWELL_MAGNETOSTATIC_SETUP_SAVED")
    validation=design.ValidateDesign()
    state["native_validate_design_passed"]=bool(validation)
    state["native_validation_messages"]=list(oDesktop.GetMessages("","",0))[-50:]
    if not validation:raise RuntimeError("REAL native Ansys ValidateDesign failed")
    step("MAXWELL_NATIVE_DESIGN_VALIDATE_PASSED")
    state["status"]="ANALYZE_RUNNING"
    save()
    started=time.time()
    ans=design.Analyze("Setup1")
    state["analyze_elapsed_s"]=round(time.time()-started,2)
    state["native_analyze_return"]=str(ans)
    messages=list(oDesktop.GetMessages("","",0))
    state["native_solver_messages"]=messages[-90:]
    normal=any("Normal completion" in m for m in messages)
    state["solver_normal_completion"]=ans in (None,0) and normal
    state["native_mesh_converged"]=state["solver_normal_completion"] and not any(
        "did not converge" in m.lower() or "not converged" in m.lower()
        for m in messages)
    project.Save()
    state["status"]=("REAL_MAXWELL_1A_N97_UNQUALIFIED_CONVERGED_CONCEPT" if
                     state["native_mesh_converged"] else
                     "REAL_MAXWELL_1A_SOLVER_NONCONVERGED_OR_FAILED_CONCEPT")
    try:
        design.ExportConvergence("Setup1","",CONV)
        if os.path.isfile(CONV):
            state["native_convergence_file_sha256"]=digest(CONV)
            state["native_convergence_file_bytes"]=os.path.getsize(CONV)
    except Exception as e:state["convergence_export_error"]=str(e)
except:
    state["status"]="MAXWELL_NATIVE_3TURN_SOLVE_FAILED_NOT_FOR_FAB"
    state["error"]=traceback.format_exc()
    try:state["native_messages_on_failure"]=list(oDesktop.GetMessages("","",0))[-50:]
    except:pass
finally:
    try:
        if os.path.isfile(TARGET):
            state["target_size_bytes"]=os.path.getsize(TARGET)
            state["target_sha256"]=digest(TARGET)
        save()
    except:pass
    try:ScriptEnv.Shutdown()
    except:pass
