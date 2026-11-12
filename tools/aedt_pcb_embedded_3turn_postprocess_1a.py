# -*- coding: utf-8 -*-
"""Real AEDT 2025R2 field-energy extraction from the completed 3-turn PCB solve.

READ ONLY. The solved Aedt model is an unqualified generic-ferrite,
1A-DC trial with artificial test leads and design-estimated ELP gap.
Do not use energy-equivalent L as approved Lr, or infer 100C N97/200kHz.
"""
import hashlib,json,os,re,sys,traceback

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN=os.path.join(ROOT,"design","v3","maxwell","local_runs")
NAME="ELP38_Lr_PCB_3TURN_6LAYER_REAL_1A_FEM_GENERIC_FERRITE_V2"
SOURCE=os.path.join(RUN,NAME+"_NOT_FOR_FAB.aedt")
CONV=os.path.join(RUN,NAME+".convergence.conv")
SOLVE=os.path.join(RUN,NAME+"_receipt.json")
REPORT=os.path.join(RUN,NAME+"_postprocess.json")
state={"schema":"REAL_6LAYER_PCB_3TURN_MAXWELL_1A_ENERGY_SOURCE_V1",
       "source_project":SOURCE,"energy_j":None,"energy_equivalent_uH":None,
       "status":"STARTING","N97_100C_nonlin_BH_verified":False,
       "actual_magnet_inductance_L_I_verified":False,"AC_200khz_loss_verified":False,
       "fabrication_approved":False}
def digest(path):
    return hashlib.sha256(open(path,"rb").read()).hexdigest()
def write():
    with open(REPORT,"w",encoding="utf-8") as f:
        json.dump(state,f,ensure_ascii=False,indent=2);f.write("\n")
try:
    if os.path.exists(REPORT):raise RuntimeError("REFUSE overwrite existing field calculator receipt")
    receipt=json.load(open(SOLVE,"r",encoding="utf-8"))
    if receipt["status"]!="REAL_MAXWELL_1A_N97_UNQUALIFIED_CONVERGED_CONCEPT":
        raise RuntimeError("Native 1A solve did not pass")
    if not receipt["solver_normal_completion"] or not receipt["native_mesh_converged"]:
        raise RuntimeError("Expected true Ansys magnetostatic convergence")
    state["source_sha256_before"]=digest(SOURCE)
    state["real_convergence_sha256"]=digest(CONV)
    state["native_solve_receipt_sha256"]=digest(SOLVE)
    state["model_source_geometry_sha256"]=receipt["source_sha256"]
    sys.path.append(r"D:\ANSYS Inc\v252\AnsysEM\PythonFiles\DesktopPlugin")
    import ScriptEnv
    ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
    oDesktop.OpenProject(SOURCE)
    project=oDesktop.SetActiveProject(os.path.splitext(os.path.basename(SOURCE))[0])
    design=project.SetActiveDesign("Lr_PCB_3turn_geometry")
    reporter=design.GetModule("FieldsReporter")
    for form in ("Setup1:LastAdaptive","Setup1 : LastAdaptive"):
        try:
            reporter.CalcStack("clear")
            reporter.EnterQty("Energy")
            reporter.EnterVol("AllObjects")
            reporter.CalcOp("Integrate")
            ans=reporter.GetTopEntryValue(form,[])
            vals=list(ans)
            state["ansys_energy_calculator_raw"]=vals
            state["native_solution_name"]=form
            v=[]
            for val in vals:
                found=re.match(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",str(val))
                if found:v.append(float(found.group(1)))
            if len(v)!=1 or not 0<v[0]<.01:
                raise RuntimeError("Unrecognized actual field energy "+repr(vals))
            state["energy_j"]=v[0]
            state["energy_equivalent_uH"]=2*v[0]*1e6/(receipt["excitation_a"]**2)
            state["energy_identity"]="W=0.5 L I_DC^2; artificial external leads included, generic ferrite; not OEM Lr"
            break
        except Exception:
            state["energy_error_"+form]=traceback.format_exc()[-3000:]
    state["status"]="ACTUAL_AEDT_ENERGY_EXTRACTED_UNQUALIFIED_3TURN" if state["energy_j"] else "ACTUAL_AEDT_ENERGY_EXTRACTION_FAILED"
except:
    state["status"]="MAXWELL_FIELD_CALCULATOR_FAILED_NOT_FOR_FAB"
    state["error"]=traceback.format_exc()
finally:
    try:ScriptEnv.Shutdown()
    except:pass
    if os.path.isfile(SOURCE):
        state["source_sha256_after"]=digest(SOURCE)
        state["source_project_unchanged"]=state.get("source_sha256_before")==state["source_sha256_after"]
    write()
    print(state["status"],state.get("energy_j"),state.get("energy_equivalent_uH"))
