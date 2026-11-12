# -*- coding: utf-8 -*-
"""Read-only REAL Ansys field energy for independent 3turn PCB mesh studies.

Use after real 1%/0.5% adaptive runs; never fake field values from
convergence text. Save Ansys FieldsReporter integrated W and compare
with last adaptive convergence step. Preserve actual AEDT native SHA.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/"design/v3/maxwell/local_runs"
STEMS={
"1pct":"ELP38_Lr_PCB_3TURN_1A_GENERIC_FERRITE_ADAPTIVE_1PCT_TRIAL_NOT_FOR_FAB",
"0p5pct":"ELP38_Lr_PCB_3TURN_1A_GENERIC_FERRITE_ADAPTIVE_0P5PCT_30REFINE_NOT_FOR_FAB",
}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def audit(tag):
    if tag not in STEMS:raise ValueError("Unknown trial")
    stem=STEMS[tag]
    model=RUN/(stem+".aedt")
    native=RUN/(stem+".receipt.json")
    conv=RUN/(stem+".conv")
    report=RUN/(stem+".field_energy.json")
    if report.exists():raise FileExistsError("Refuse overwriting actual independent Ansys field-energy receipt")
    data={"schema":"D1_INDEPENDENT_MAXWELL_PCB_3TURN_MESH_ENERGY_V1",
        "mesh_trial":tag,"status":"NOT_STARTED","energy_j":None,
        "energy_equivalent_L_uH":None,
        "actual_field_extraction":False,
        "material_oem_n97_100c_verified":False,
        "material_or_fab_approved":False}
    try:
        r=json.loads(native.read_text(encoding="utf-8"))
        if not r["actual_maxwell_solver_finished"] or not r["native_solver_converged"]:
            raise RuntimeError("Maxwell real mesh solver did not converge")
        if not model.is_file() or not conv.is_file():
            raise RuntimeError("Missing true native Ansys field and mesh outputs")
        if r["candidate_sha256"]!=sha(model):
            raise RuntimeError("Real solved AEDT has changed since native solve")
        data["source_aedt_sha256_before"]=sha(model)
        sys.path.insert(0,str(ROOT/"tools"))
        import package_aedt_pcb_embedded_3turn_fem as P
        rows=P.parse_conv(conv.read_text(encoding="utf-8"))
        if len(rows)<3:raise RuntimeError("Not enough native adaptive meshes")
        data["mesh_count"]=len(rows)
        data["latest_mesh_tetrahedra"]=rows[-1]["tetrahedra"]
        data["native_convergence_last_energy_j"]=rows[-1]["energy_j"]
        sys.path.append(r"D:\ANSYS Inc\v252\AnsysEM\PythonFiles\DesktopPlugin")
        import ScriptEnv
        ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
        oDesktop.OpenProject(str(model))
        project=oDesktop.SetActiveProject(model.stem)
        design=project.SetActiveDesign("Lr_PCB_3turn_geometry")
        reporter=design.GetModule("FieldsReporter")
        errors=[]
        for solution in ("Setup1:LastAdaptive","Setup1 : LastAdaptive"):
            try:
                reporter.CalcStack("clear")
                reporter.EnterQty("Energy")
                reporter.EnterVol("AllObjects")
                reporter.CalcOp("Integrate")
                vals=list(reporter.GetTopEntryValue(solution,[]))
                v=[]
                for raw in vals:
                    found=re.match(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",str(raw))
                    if found:v.append(float(found.group(1)))
                if len(v)!=1 or not 0<v[0]<1e-4:
                    raise RuntimeError("Field value unparsable "+repr(vals))
                data["field_reporter_solution_name"]=solution
                data["field_reporter_raw"]=vals
                data["energy_j"]=v[0]
                data["energy_equivalent_L_uH"]=2e6*v[0] # 1A (source locked)
                data["field_vs_conv_relative_error_pct"]=100*abs(
                    v[0]-rows[-1]["energy_j"])/v[0]
                if data["field_vs_conv_relative_error_pct"]>.1:
                    raise RuntimeError("Raw Ansys field energy differs from last convergence row")
                data["actual_field_extraction"]=True
                break
            except Exception:
                errors.append(traceback.format_exc()[-1400:])
        if not data["actual_field_extraction"]:
            raise RuntimeError("Actual Ansys field calculation failed "+repr(errors))
        data["status"]="ACTUAL_NATIVE_1A_FIELD_ENERGY_CONFIRMED_MODEL_ONLY_NOT_FOR_FAB"
    except BaseException:
        data["status"]="ACTUAL_NATIVE_FIELD_EXTRACTION_FAILED_NOT_FOR_FAB"
        data["error"]=traceback.format_exc()
    finally:
        try:ScriptEnv.Shutdown()
        except BaseException:pass
        if model.exists():
            data["source_aedt_sha256_after"]=sha(model)
            data["actual_model_unchanged"]=(
                data.get("source_aedt_sha256_before")==data["source_aedt_sha256_after"])
            if not data["actual_model_unchanged"]:
                data["status"]="FIELD_EXTRACTION_MODIFIED_NATIVE_MODEL_REJECTED"
        report.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",
                          encoding="utf-8",newline="\n")
        print(data["status"],tag,data.get("energy_equivalent_L_uH"),
              data.get("field_vs_conv_relative_error_pct"))
    return 0 if data["status"]=="ACTUAL_NATIVE_1A_FIELD_ENERGY_CONFIRMED_MODEL_ONLY_NOT_FOR_FAB" else 1

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--trial",choices=STEMS,required=True)
    args=parser.parse_args()
    raise SystemExit(audit(args.trial))
