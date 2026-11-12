# -*- coding: utf-8 -*-
"""Read-only 2025R2 Maxwell 30-pass postprocess: convergence/energy evidence.

This exports actual solver data, not synthesized tables. Energy -> trial L is
per Ansys's magnetostatic energy formula only if native calculator returns
a valid numeric result; the stock-ferrite/external-lead 1 A model is NOT a
validated actual Lr winding or a manufacturing release.
"""
import os,sys,json,traceback,hashlib,re

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN=os.path.join(ROOT,"design","v3","maxwell","local_runs")
SRC=os.path.join(RUN,"ELP38_Lr_1A_EXTERNAL_LEADS_30PASS_NOT_FOR_FAB.aedt")
CONV=os.path.join(RUN,"ELP38_Lr_1A_EXTERNAL_LEADS_30PASS.convergence.conv")
REPORT=os.path.join(RUN,"ELP38_Lr_1A_EXTERNAL_LEADS_30PASS_postprocess.json")
state={"status":"STARTING","project":SRC,"convergence_export":CONV,
       "energy_j":None,"static_dc_energy_equivalent_inductance_uH":None,
       "material_N97_100C_verified":False,"actual_Lr_qualified":False,
       "100a_qualified":False,"manufacturing_approved":False}
def save():
    with open(REPORT,"w") as f:json.dump(state,f,indent=2)
try:
    if not os.path.isfile(SRC):raise RuntimeError("30pass native FEM not found")
    if os.path.exists(CONV):raise RuntimeError("REFUSE overwrite existing original convergence export")
    state["source_sha256"]=hashlib.sha256(open(SRC,"rb").read()).hexdigest()
    sys.path.append(r"D:\ANSYS Inc\v252\AnsysEM\PythonFiles\DesktopPlugin")
    import ScriptEnv
    ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
    oDesktop.OpenProject(SRC)
    proj=oDesktop.SetActiveProject(os.path.splitext(os.path.basename(SRC))[0])
    design=proj.SetActiveDesign("Lr_2turn_geometry_only")
    state["native_model_opened"]=True
    try:
        design.ExportConvergence("Setup1","",CONV)
        state["convergence_file_exists"]=os.path.isfile(CONV)
        if state["convergence_file_exists"]:
            state["convergence_size"]=os.path.getsize(CONV)
            state["convergence_sha256"]=hashlib.sha256(open(CONV,"rb").read()).hexdigest()
    except:
        state["export_convergence_error"]=traceback.format_exc()
    fr=design.GetModule("FieldsReporter")
    for form in ("Setup1:LastAdaptive","Setup1 : LastAdaptive"):
        try:
            fr.CalcStack("clear")
            fr.EnterQty("Energy")
            fr.EnterVol("AllObjects")
            fr.CalcOp("Integrate")
            ans=fr.GetTopEntryValue(form,[])
            state["energy_solver_expression_raw"]=list(ans)
            state["energy_solver_solution_context"]=form
            numbers=[]
            for item in ans:
                n=re.match(r"^[\s]*([+-]?(?:[0-9]+[.]?[0-9]*|[.][0-9]+)(?:[eE][+-]?[0-9]+)?)",str(item))
                if n:numbers.append(float(n.group(1)))
            if len(numbers)==1 and numbers[0]>0:
                state["energy_j"]=numbers[0]
                # True magnetostatic 1A DC energy convention W=0.5*L*I^2.
                # The Ansys AC peak-current tutorial uses 4W/Ipeak^2; it does
                # not apply to this DC source. This number is NOT the qualified
                # inductance of the real Lr component or actual N97.
                state["static_dc_energy_equivalent_inductance_uH"]=2*numbers[0]*1e6
                state["inductance_energy_identity"]="W=0.5*L*I_DC^2 at 1A DC; ignores all lead/material invalidity"
            break
        except:
            state["energy_attempt_error_"+form]=traceback.format_exc()
    state["postprocess_messages"]=list(oDesktop.GetMessages("","",0))
    state["status"]=("REAL_CONVERGENCE_AND_ENERGY_EXPORTED_CONCEPT_ONLY" if
        state["energy_j"] is not None and state.get("convergence_file_exists")
        else "REAL_NATIVE_POSTPROCESS_PARTIAL_NOT_FOR_FAB")
except:
    state["status"]="MAXWELL_NATIVE_POSTPROCESS_FAILED"
    state["error"]=traceback.format_exc()
finally:
    try:save()
    except:pass
    try:ScriptEnv.Shutdown()
    except:pass
