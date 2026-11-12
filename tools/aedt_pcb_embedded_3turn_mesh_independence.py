"""Source-locked independent-mesh numerical verification for REAL 3-turn PCB FEM.

Evaluate two genuinely independent, saved Maxwell 2025R2 adaptive solves:
  (1) 1% energy error target, 25% per-pass refinement;
  (2) 0.5% energy error target, 30% per-pass refinement.
Both start from the SAME solved native 6-layer KiCad three-turn model with
the same 1A current boundary. Require real GetTopEntryValue Energy in BOTH,
6+ actual FEM mesh steps, two stable fine-mesh intervals, and inter-run
agreement <=1%. Test GENUINE numerical mesh repeatability, NOT physical
N97 100C L(I), AC loss, artificial leads, hot copper or fab sign-off.

On the equipped workstation:
  python tools/aedt_pcb_embedded_3turn_mesh_independence.py --write
Portable, no Ansys licence:
  python tools/aedt_pcb_embedded_3turn_mesh_independence.py --check
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import shutil
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"design/v3/maxwell/local_runs"
OUT=ROOT/"hardware/dcx_main/maxwell"
BASE=OUT/"ELP38_Lr_PCB_3TURN_6LAYER_1A_GENERIC_FERRITE_FEM_NOT_FOR_FAB.aedt"
BASE_EVID=OUT/"ELP38_Lr_PCB_3TURN_6LAYER_1A_GENERIC_FERRITE_FEM_NOT_FOR_FAB.evidence.json"
EVID=OUT/"ELP38_Lr_PCB_3TURN_TWO_INDEPENDENT_MESH_STUDIES_1A_NOT_FOR_FAB.json"
PRE="ELP38_Lr_PCB_3TURN_MESHINDEP_"
SPECS={
 "1pct":{
   "source":"ELP38_Lr_PCB_3TURN_1A_GENERIC_FERRITE_ADAPTIVE_1PCT_TRIAL_NOT_FOR_FAB",
   "output":PRE+"1PCT_25REFINE_NOT_FOR_FAB",
   "target_pct":1.0,"refine_pct":25,"maxpasses":24,
 },
 "0p5pct":{
   "source":"ELP38_Lr_PCB_3TURN_1A_GENERIC_FERRITE_ADAPTIVE_0P5PCT_30REFINE_NOT_FOR_FAB",
   "output":PRE+"0P5PCT_30REFINE_NOT_FOR_FAB",
   "target_pct":.5,"refine_pct":30,"maxpasses":24,
 },
}
SCRIPT_HASHES={
 "tools/aedt_pcb_embedded_3turn_mesh_1pct.py":
    ROOT/"tools/aedt_pcb_embedded_3turn_mesh_1pct.py",
 "tools/aedt_pcb_embedded_3turn_mesh_0p5pct.py":
    ROOT/"tools/aedt_pcb_embedded_3turn_mesh_0p5pct.py",
 "tools/aedt_pcb_embedded_3turn_mesh_field_energy.py":
    ROOT/"tools/aedt_pcb_embedded_3turn_mesh_field_energy.py",
}
MIN_MESH_FINAL=100000
GRID_INDEPENDENCE_MAX_PCT=1.0
PER_STEP_FINE_MAX_PCT=.5
def digest(path):
 return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(path):
 return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n",b"\n")).hexdigest()
def fmt_paths(tag,local):
 d=SPECS[tag]
 stem=(SRC/d["source"]) if local else (OUT/d["output"])
 return {
  "native":stem.with_suffix(".aedt"),
  "conv":stem.with_suffix(".conv"),
  "receipt":stem.with_suffix(".receipt.json"),
  "field":stem.with_suffix(".field_energy.json"),
  "results":SRC/(d["source"]+".aedtresults") if local else (OUT/(d["output"]+".results.zip")),
 }
def parse_conv(body):
 # Preserve exact Ansys native convergence rows; never fake energies
 h=[x.strip() for x in body.splitlines()]
 starts=[i for i,x in enumerate(h) if x.startswith("Pass|# Tetrahedra")]
 if len(starts)!=1:raise ValueError("No native Ansys convergence table")
 rows=[]
 for line in h[starts[0]+1:]:
  if not line or "|" not in line:continue
  v=[x.strip() for x in line.split("|") if x.strip()]
  if len(v)!=5:raise ValueError("Malformed native Ansys convergence row")
  rows.append({"pass":int(v[0]),"tetrahedra":int(v[1]),
   "energy_j":float(v[2]),"energy_error_pct":float(v[3]),
   "energy_delta_pct":None if v[4]=="N/A" else float(v[4])})
 if len(rows)<5 or [x["pass"] for x in rows]!=list(range(1,len(rows)+1)):
  raise ValueError("Cannot assess independence with fewer than five true meshes")
 if any(b["tetrahedra"]<=a["tetrahedra"] for a,b in zip(rows,rows[1:])):
  raise ValueError("Reported Ansys meshes did not actually increase")
 for prev,row in zip(rows,rows[1:]):
  delta=100*abs(row["energy_j"]-prev["energy_j"])/prev["energy_j"]
  if abs(delta-row["energy_delta_pct"])>.035:
   raise ValueError("Native Ansys reported delta is inconsistent with energy rows")
 return rows
def safe_archive(zpath):
 with zipfile.ZipFile(zpath) as z:
  names=z.namelist()
  if len(names)<20 or len(names)!=len(set(names)):
   raise ValueError("Missing actual Ansys mesh and field data")
  if any(x.startswith("/") or "../" in x or "..\\" in x for x in names):
   raise ValueError("Unsafe solver archive member")
  if not any(x.endswith("current.ngmesh") for x in names):
   raise ValueError("No native Maxwell tetrahedral mesh")
  if not any(x.endswith("fields.blo") for x in names):
   raise ValueError("No native Maxwell solved B-field")
  count=sum(z.getinfo(x).file_size for x in names)
  if count<10_000_000:raise ValueError("Solver field archive suspiciously small")
  return {"file_count":len(names),"uncompressed_bytes":count,
          "has_mesh_and_B_field":True}
def check_one(tag):
 d=SPECS[tag];p=fmt_paths(tag,False)
 a=json.loads(p["receipt"].read_text(encoding="utf-8"))
 e=json.loads(p["field"].read_text(encoding="utf-8"))
 if a["status"]!="REAL_STRICTER_MESH_SOLVER_CONVERGED_REQUIRES_INDEPENDENCE_AUDIT":
  raise ValueError(tag+" Maxwell native solve did not converge")
 if not a["actual_maxwell_solver_finished"] or not a["native_solver_converged"] or not a["native_validate_design_passed"]:
  raise ValueError("Solver did not complete and validate")
 if not a["same_geometry_as_parent"] or a["base_sha256"]!=digest(BASE):
  raise ValueError("Source CAD or native geometry is not the identical 3-turn PCB")
 if a["current_a"]!=1 or a["maximum_adaptive_passes"]!=d["maxpasses"] or a["minimum_converged_passes"]!=2:
  raise ValueError("Changed current, pass count or convergence policy")
 if a["requested_energy_error_pct"]!=d["target_pct"] or a["refinement_percent"]!=d["refine_pct"]:
  raise ValueError("Native solver refinement settings differ")
 if a["candidate_sha256"]!=digest(p["native"]):
  raise ValueError("Native AEDT corrupted from original Ansys solve")
 if not any("PCB_LR_DC_1A_IN" in s for s in a["native_assignments"]) or not any("PCB_LR_DC_1A_OUT" in s for s in a["native_assignments"]):
  raise ValueError("Two actual 1A current boundaries missing")
 if a["real_n97_100c_L_I_or_200khz_loss_qualified"] or a["fabrication_approved"]:
  raise ValueError("Unqualified OEM/hardware falsely approved")
 rows=parse_conv(p["conv"].read_text(encoding="utf-8"))
 final=rows[-1]
 if len(rows)>d["maxpasses"] or final["tetrahedra"]<MIN_MESH_FINAL:
  raise ValueError("Insufficient real tetrahedra or more passes than configured")
 if final["energy_error_pct"]>d["target_pct"] or final["energy_delta_pct"]>d["target_pct"]:
  raise ValueError("Native Maxwell energy convergence threshold exceeded")
 fine=[row["energy_delta_pct"] for row in rows[-2:]]
 if any(v is None or v>PER_STEP_FINE_MAX_PCT for v in fine):
  raise ValueError("Last two native energies continue to drift")
 if e["status"]!="ACTUAL_NATIVE_1A_FIELD_ENERGY_CONFIRMED_MODEL_ONLY_NOT_FOR_FAB" or not e["actual_field_extraction"]:
  raise ValueError("No real independent Ansys field energy integral")
 if not e["actual_model_unchanged"] or e["source_aedt_sha256_before"]!=digest(p["native"]):
  raise ValueError("Energy extraction altered native solver input")
 if e["latest_mesh_tetrahedra"]!=final["tetrahedra"] or e["mesh_count"]!=len(rows):
  raise ValueError("Ansys FieldsReporter solution and convergence mesh differ")
 if e["field_vs_conv_relative_error_pct"]>.1 or not math.isclose(
     e["energy_equivalent_L_uH"],2e6*e["energy_j"],rel_tol=1e-9):
  raise ValueError("Field energy doesn't reproduce independent row or 1A inductance")
 if abs(final["energy_j"]-e["energy_j"])/e["energy_j"]>.001:
  raise ValueError("Mismatch between field calculator and native convergence table")
 if e["material_oem_n97_100c_verified"] or e["material_or_fab_approved"]:
  raise ValueError("No true OEM N97 material / physical approval")
 return {
  "policy":{"target_error_pct":d["target_pct"],"adaptive_refinement_pct":d["refine_pct"],
            "maximum_passes":d["maxpasses"],"minimum_converged_passes":2},
  "files_sha256":{
      "native_aedt":digest(p["native"]),"convergence_canonical_lf":canonical(p["conv"]),
      "solver_receipt_canonical_lf":canonical(p["receipt"]),
      "field_reporter_receipt_canonical_lf":canonical(p["field"]),
      "raw_fem_results_archive":digest(p["results"])},
  "raw_field_and_mesh_archive":safe_archive(p["results"]),
  "adaptive_passes":len(rows),
  "adaptive_mesh_rows":rows,
  "final_tetrahedra":final["tetrahedra"],
  "final_error_pct":final["energy_error_pct"],
  "final_an_sys_delta_pct":final["energy_delta_pct"],
  "last_two_adaptive_energy_deltas_pct":fine,
  "real_field_integral_energy_j":e["energy_j"],
  "model_only_equivalent_L_uH":e["energy_equivalent_L_uH"],
  "valid_native_an_sys_mesh_and_field_data":True,
 }
def report():
 baseline=json.loads(BASE_EVID.read_text(encoding="utf-8"))
 if baseline["fabrication_approved"] or not baseline["generic_stock_ferrite_not_OEM_N97"]:
  raise ValueError("Parent FEM is not allowed as manufacturing evidence")
 x={k:check_one(k) for k in SPECS}
 e1=x["1pct"]["real_field_integral_energy_j"]
 e2=x["0p5pct"]["real_field_integral_energy_j"]
 cross=100*abs(e1-e2)/e2
 if cross>GRID_INDEPENDENCE_MAX_PCT:
  raise ValueError("Two independent native mesh policies disagree by %.6f%%"%cross)
 if x["0p5pct"]["final_tetrahedra"]<=x["1pct"]["final_tetrahedra"]:
  raise ValueError("0.5% final independent mesh is not actually finer than 1%")
 early=baseline["Ansys_field_reporter_energy_equivalent_1A_uH"]
 refined=x["0p5pct"]["model_only_equivalent_L_uH"]
 return {
  "schema":"NATIVE_PCB_3TURN_1A_DUAL_MESH_NUMERICAL_INDEPENDENCE_V1",
  "status":"MESH_INDEPENDENT_WITHIN_1PCT_FOR_FIXED_GENERIC_FERRITE_MODEL_ONLY_NOT_FOR_FAB",
  "actual_solved_an_sys_AEDT_2025R2":True,
  "identical_KiCad_6layer_3turn_source_SHA256":digest(BASE),
  "parent_unreliable_7pct_mesh_equivalent_L_uH":early,
  "mesh_grid_independence_criteria":{
   "independent_refinement_policies_count":2,
   "both_native_energy_error_threshold_met":True,
   "two_final_adaptive_steps_below_pct":PER_STEP_FINE_MAX_PCT,
   "cross_run_relative_inductance_difference_pct_max":GRID_INDEPENDENCE_MAX_PCT,
  },
  "independent_solver_runs":x,
  "between_independent_runs_relative_energy_difference_pct":cross,
  "between_independent_runs_relative_inductance_difference_pct":cross,
  "refined_model_only_L_energy_uH":refined,
  "old_7pct_two_pass_bias_relative_to_refined_pct":100*(early-refined)/refined,
  "fixed_model_numerical_mesh_independence_verified":True,
  "actual_N97_100C_material_and_bias_L_I_verified":False,
  "actual_200kHz_skin_proximity_fringe_and_core_loss_verified":False,
  "true_OEM_gap_hardware_16mm_coldplate_or_PCB_via_ampacity_verified":False,
  "fabrication_approved":False,
  "model_limitations":[
   "Simulation material is generic stock ferrite, not OEM N97 100C nonlinear B-H.",
   "Artificial 120mm-wide-current-injection external leads change the magnetic energy.",
   "Actual PCB dielectric/slot bodies, manufacturing layer stack and via copper remain trial assumptions.",
   "Energy-equivalent L at 1A DC is not hot-biased L(I), 200kHz losses or 0.92uH nominal qualification.",
  ],
  "generator_scripts_canonical_lf_sha256":{
     k:canonical(path) for k,path in SCRIPT_HASHES.items()},
 }
def archive_raw(source,out):
 if out.exists():raise FileExistsError("Refuse overwrite solved Ansys field archive "+str(out))
 if not source.is_dir():raise FileNotFoundError(source)
 files=sorted(x for x in source.rglob("*") if x.is_file())
 if len(files)<20:raise ValueError("Native Ansys result files missing")
 with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for f in files:
   entry=zipfile.ZipInfo(f.relative_to(source).as_posix(),(1980,1,1,0,0,0))
   entry.compress_type=zipfile.ZIP_DEFLATED
   z.writestr(entry,f.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
 return safe_archive(out)
def main():
 p=argparse.ArgumentParser(description=__doc__)
 a=p.add_mutually_exclusive_group(required=True)
 a.add_argument("--write",action="store_true")
 a.add_argument("--check",action="store_true")
 cmd=p.parse_args()
 if cmd.write:
  if EVID.exists() or any(path.exists() for tag in SPECS for name,path in fmt_paths(tag,False).items()):
   raise FileExistsError("Refuse overwrite any native independence evidence; make new version")
  for tag in SPECS:
   original=fmt_paths(tag,True)
   for f in original.values():
    if not f.exists():raise FileNotFoundError("Missing real Ansys solver artifact "+str(f))
  for tag in SPECS:
   src=fmt_paths(tag,True);out=fmt_paths(tag,False)
   for k in ("native","conv","receipt","field"):
    shutil.copy2(src[k],out[k])
   archive_raw(src["results"],out["results"])
  obj=report()
  EVID.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",
                  encoding="utf-8",newline="\n")
  print("NATIVE TWO-RUN GRID INDEPENDENCE:",obj["refined_model_only_L_energy_uH"],
        "uH, delta",obj["between_independent_runs_relative_energy_difference_pct"],"%")
  return 0
 if not EVID.exists():raise FileNotFoundError("No real dual-Maxwell independence evidence")
 obj=report()
 saved=json.loads(EVID.read_text(encoding="utf-8"))
 if saved!=obj:raise ValueError("Saved independent-mesh proof/source SHA is stale or corrupted")
 print("Verified real dual-mesh convergence, diff %.5f%%"%obj[
    "between_independent_runs_relative_energy_difference_pct"])
 return 0
if __name__=="__main__":
 raise SystemExit(main())
