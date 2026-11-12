"""Package real AEDT 2025R2 solved three-turn PCB 1A FEM evidence (NOT_FOR_FAB).

--write copies only independently solved native outputs to source control,
        with stable zip ordering and SHA256 provenance. Refuse overwrite.
--check operates OFFLINE on committed contents; no solver/license required.

Do not convert this 1A, generic-ferrite, artificial-external-leads
concept calculation into OEM 100C N97 L(I) or manufacturing approval.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/"design/v3/maxwell/local_runs"
SOURCE_STEM="ELP38_Lr_PCB_3TURN_6LAYER_REAL_1A_FEM_GENERIC_FERRITE_V2"
OUT=ROOT/"hardware/dcx_main/maxwell"
STEM="ELP38_Lr_PCB_3TURN_6LAYER_1A_GENERIC_FERRITE_FEM_NOT_FOR_FAB"
MAP={
    "native_aedt":(RUN/(SOURCE_STEM+"_NOT_FOR_FAB.aedt"), OUT/(STEM+".aedt")),
    "convergence":(RUN/(SOURCE_STEM+".convergence.conv"), OUT/(STEM+".conv")),
    "native_receipt":(RUN/(SOURCE_STEM+"_receipt.json"), OUT/(STEM+".receipt.json")),
    "field_energy":(RUN/(SOURCE_STEM+"_postprocess.json"), OUT/(STEM+".postprocess.json")),
}
RESULTS=RUN/(SOURCE_STEM+"_NOT_FOR_FAB.aedtresults")
ZIP=OUT/(STEM+".results.zip")
EVID=OUT/(STEM+".evidence.json")
GEOM=OUT/"ELP38_Lr_PCB_EMBEDDED_3TURN_6LAYER_4PTH_NATIVE_GEOMETRY_NOT_FOR_FAB.aedt"
SCRIPT1=ROOT/"tools/aedt_pcb_embedded_3turn_solve_1a.py"
SCRIPT2=ROOT/"tools/aedt_pcb_embedded_3turn_postprocess_1a.py"
MIN_MESH=30000
MAX_ENERGY_J=.00001

def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def lf(p):
    return hashlib.sha256(Path(p).read_bytes().replace(b"\r\n",b"\n")).hexdigest()

def hash_retained(name,path):
    # Git normalizes JSON/conv text, so bind the canonical LF digest.
    # Real native .aedt binary is protected -text and always strict bytes.
    return digest(path) if name=="native_aedt" else lf(path)

def parse_conv(body):
    lines=[x.strip() for x in body.splitlines()]
    indices=[i for i,x in enumerate(lines) if x.startswith("Pass|# Tetrahedra")]
    if len(indices)!=1:raise ValueError("Non-native Ansys convergence file header")
    rows=[]
    for line in lines[indices[0]+1:]:
        if not line or "|" not in line:continue
        cols=[x.strip() for x in line.split("|") if x.strip()]
        if len(cols)!=5:raise ValueError("Malformed Ansys convergence row "+line)
        rows.append({"pass":int(cols[0]),"tetrahedra":int(cols[1]),
                     "energy_j":float(cols[2]),"error_pct":float(cols[3]),
                     "delta_energy_pct":None if cols[4]=="N/A" else float(cols[4])})
    if not 2<=len(rows)<=30 or [x["pass"] for x in rows]!=list(range(1,len(rows)+1)):
        raise ValueError("No true sequential mesh convergence")
    if rows[-1]["tetrahedra"]<MIN_MESH or not (0<rows[-1]["energy_j"]<MAX_ENERGY_J):
        raise ValueError("Implausible Ansys 1A mesh energy/tetrahedra")
    return rows

def checked_inputs(solved,energy,conv):
    if solved["status"]!="REAL_MAXWELL_1A_N97_UNQUALIFIED_CONVERGED_CONCEPT":
        raise ValueError("Ansys did not complete the real source")
    if not solved["solver_normal_completion"] or not solved["native_mesh_converged"]:
        raise ValueError("No genuine Ansys solver completion/convergence")
    if not solved["native_validate_design_passed"] or solved["excitation_a"]!=1.0:
        raise ValueError("Wrong native 1A test setup")
    if solved["source_sha256"]!=digest(GEOM):
        raise ValueError("Native FEM is not derived from accepted KiCad 3turn geometry")
    if any(solved[k] for k in (
            "N97_100C_BH_verified","L_I_bias_100A_verified",
            "AC_200khz_skin_fringe_loss_verified","manufacturing_approved")):
        raise ValueError("Unqualified physical/material values falsely approved")
    if energy["status"]!="ACTUAL_AEDT_ENERGY_EXTRACTED_UNQUALIFIED_3TURN":
        raise ValueError("Failed original Ansys field-energy calculation")
    if not energy["source_project_unchanged"] or energy["source_sha256_before"]!=energy["source_sha256_after"]:
        raise ValueError("Read-only field extraction altered native solver data")
    if abs(energy["energy_equivalent_uH"]-2e6*energy["energy_j"])>1e-7:
        raise ValueError("1 A energy identity mismatch")
    if not 0<energy["energy_j"]<MAX_ENERGY_J:
        raise ValueError("Field-reported energy implausible")
    rows=parse_conv(conv)
    if rows[-1]["error_pct"]>7 or rows[-1]["delta_energy_pct"]>7:
        raise ValueError("Real native mesh convergence exceeded trial threshold")
    if abs(rows[-1]["energy_j"]-energy["energy_j"])/energy["energy_j"]>.001:
        raise ValueError("Field calculator disagrees with last Ansys energy row")
    return rows

def extract(zipfile_path):
    with zipfile.ZipFile(zipfile_path) as z:
        names=z.namelist()
        if len(names)!=29 or len(set(names))!=29:
            raise ValueError("Expected exactly 29 native Ansys field/mesh result artifacts")
        if any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise ValueError("Unsafe archive member")
        if not any(name.endswith("current.ngmesh") for name in names):
            raise ValueError("No real native mesh in result archive")
        if not any(name.endswith("fields.blo") for name in names):
            raise ValueError("No real solved magnetic B-field in archive")
        return {"count":len(names),"native_result_members":names,
                "total_uncompressed_bytes":sum(z.getinfo(name).file_size for name in names)}

def summarize(solved,energy,conv,files,archive):
    rows=checked_inputs(solved,energy,conv)
    detail=extract(archive)
    data={
        "schema":"D1_REAL_NATIVE_MAXWELL_3TURN_1A_PROVENANCE_AND_GATES_V1",
        "status":"NATIVE_REAL_6LAYER_3TURN_PCB_1A_FEM_CONVERGED_GENERIC_FERRITE_ONLY_NOT_FOR_FAB",
        "origin":"Ansys Electronics Desktop 2025R2 local actual Maxwell3D Solve",
        "actual_KiCad_derived_native_copper":True,
        "native_3turn_CAD_model_sha256":digest(GEOM),
        "retained_files_sha256":files,
        "results_archive_sha256":digest(archive),
        "results_archive":detail,
        "actual_native_solver_mesh_passes":len(rows),
        "actual_mesh_tetrahedra_last":rows[-1]["tetrahedra"],
        "actual_last_mesh_energy_error_pct":rows[-1]["error_pct"],
        "actual_last_mesh_delta_energy_pct":rows[-1]["delta_energy_pct"],
        "actual_native_solver_energy_rows":rows,
        "Ansys_field_reporter_energy_j":energy["energy_j"],
        "Ansys_field_reporter_energy_equivalent_1A_uH":energy["energy_equivalent_uH"],
        "bias_1A_DC":True,
        "source_script_canonical_lf_sha256":{
            "tools/aedt_pcb_embedded_3turn_solve_1a.py":lf(SCRIPT1),
            "tools/aedt_pcb_embedded_3turn_postprocess_1a.py":lf(SCRIPT2)},
        "model_contains_external_artificial_leads":True,
        "generic_stock_ferrite_not_OEM_N97":True,
        "N97_100C_appropriate_BH_verified":False,
        "full_range_L_I_and_0p92uH_nominal_inductance_verified":False,
        "200kHz_AC_and_100C_core_copper_loss_verified":False,
        "manufacturer_core_machining_and_6layer_barrel_qualified":False,
        "16mm_total_assembly_and_safety_qualified":False,
        "OEM_real_transformer_T1_T4_CT_validated":False,
        "hardware_or_100A_delivery_approved":False,
        "fabrication_approved":False,
        "interpretation":"True 1A nonlinear-unqualified generic-ferrite FEA. Its ~1.785uH energy equivalence includes artificial leads, inaccurate actual vendor B-H/gap and absent PCB laminate; do not compare as OEM component specification."
    }
    return data

def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    a=p.parse_args()
    if a.write:
        if any(path.exists() for _,path in MAP.values()) or ZIP.exists() or EVID.exists():
            raise FileExistsError("Refusing to overwrite existing true-native FEM evidence package")
        if not RESULTS.is_dir() or not all(src.is_file() for src,_ in MAP.values()):
            raise FileNotFoundError("Actual solved native AEDT and its field/mesh data unavailable")
        solved=json.loads(MAP["native_receipt"][0].read_text(encoding="utf-8"))
        energy=json.loads(MAP["field_energy"][0].read_text(encoding="utf-8"))
        conv=MAP["convergence"][0].read_text(encoding="utf-8")
        checked_inputs(solved,energy,conv)
        for src,out in MAP.values():shutil.copy2(src,out)
        files=sorted(x for x in RESULTS.rglob("*") if x.is_file())
        if len(files)!=29:raise ValueError("No real 29-file Ansys FEM result archive")
        with zipfile.ZipFile(ZIP,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for f in files:
                arc=f.relative_to(RESULTS).as_posix()
                info=zipfile.ZipInfo(arc,(1980,1,1,0,0,0))
                info.compress_type=zipfile.ZIP_DEFLATED
                z.writestr(info,f.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
        evidence=summarize(solved,energy,conv,
            {k:hash_retained(k,dst) for k,(src,dst) in MAP.items()},ZIP)
        EVID.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n",
                        encoding="utf-8",newline="\n")
        print("Saved",EVID,"mesh",evidence["actual_mesh_tetrahedra_last"],
              "L concept",evidence["Ansys_field_reporter_energy_equivalent_1A_uH"])
        return 0
    if not EVID.is_file() or not ZIP.is_file() or not all(dst.is_file() for _,dst in MAP.values()):
        raise ValueError("Incomplete archived native FEM evidence")
    saved=json.loads(EVID.read_text(encoding="utf-8"))
    files={k:hash_retained(k,dst) for k,(src,dst) in MAP.items()}
    energy=json.loads(MAP["field_energy"][1].read_text(encoding="utf-8"))
    solved=json.loads(MAP["native_receipt"][1].read_text(encoding="utf-8"))
    conv=MAP["convergence"][1].read_text(encoding="utf-8")
    recalc=summarize(solved,energy,conv,files,ZIP)
    if saved!=recalc:
        raise ValueError("Real FEM package evidence differs from source and saved SHA")
    print("Checked",EVID.name,"true Maxwell passes",saved["actual_native_solver_mesh_passes"])
    return 0

if __name__=="__main__":
    raise SystemExit(main())
