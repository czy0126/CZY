"""P0-C physical-fault test matrix across six independent ten-VGS captures.

The existing d0_evidence_chain verifies one 12-channel capture; one steady-run
trip cannot establish fail-safe across power-loss, startup and stuck ACK.
This module binds one independently reproducible raw scope chain per failure
condition, explicitly distinguishing evidence coverage from hardware
authentication, SOA and 100-A safe-release. Never fabricates lab records.

Usage:
  python tools/d0_p0_fault_matrix.py --manifest evidence/d0/p0_fault_matrix.json
  python tools/d0_p0_fault_matrix.py --manifest ... --report ...json

Input manifest:
  {"schema_version":1,"hardware_revision":"physical PCB revision",
   "cases":[{"mode":"...", "fault_stimulus":"...",
     "manifest":"...", "alignment":"...", "csv":"...", "config":"...",
     "audit":"...", "witness_record":"..."}, ...]}

All referenced files must be real, live, relative paths inside the same
manifest directory. They cannot be a looped synthetic test result, an
unreviewed instrument metadata string, or a report with no raw trace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import d0_evidence_chain as single

SCHEMA = 1
MODES = (
    "COLD_START_HARD_FAULT",
    "STEADY_RUN_HARD_FAULT",
    "PRIMARY_BIAS_LOSS",
    "SECONDARY_BIAS_LOSS",
    "CT_SIGNAL_MISSING",
    "HELD_HIGH_ACK_FAULT_RECOVERY",
)
PATHS = ("manifest", "alignment", "csv", "config", "audit", "witness_record")
# A twelve-column gate capture proves gate waveforms, but CANNOT by itself
# prove that a rail actually went down, a CT wire physically opened, or that
# ACK was continuously high. Require an independent bench witness file.
WITNESS = (
    "mode", "hardware_revision", "stimulus_applied_physically",
    "stimulus_instrument_id", "observer", "observed_at",
    "raw_event_trace_path", "raw_event_trace_sha256",
)
FORBIDDEN = ("SYNTHETIC", "SIMULATION", "MOCK", "PLACEHOLDER", "PENDING")

def _sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _file(base:Path,value)->Path:
    if not isinstance(value,str) or not value.strip():
        raise ValueError("evidence path must be a nonempty string")
    rel=Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("absolute or parent-relative evidence path refused")
    file=(base/rel).resolve()
    if not file.is_relative_to(base.resolve()) or not file.is_file():
        raise ValueError("missing/outside evidence: "+value)
    return file

def _real(v)->bool:
    return (isinstance(v,str) and bool(v.strip())
            and not any(w in v.upper() for w in FORBIDDEN))

def _witness(path:Path,mode:str,revision:str)->tuple[bool,list[str],dict]:
    errors=[]
    try:
        w=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(w,dict):raise ValueError("witness not object")
    except (OSError,UnicodeError,ValueError) as exc:
        return False,["invalid witness: "+str(exc)],{}
    if (w.get("mode"),w.get("hardware_revision"))!=(mode,revision):
        errors.append("witness case/revision mismatch")
    if w.get("stimulus_applied_physically") is not True:
        errors.append("physical fault stimulus not independently affirmed")
    for name in ("stimulus_instrument_id","observer","observed_at"):
        if not _real(w.get(name)):errors.append("unverifiable witness "+name)
    try:
        raw=_file(path.parent,w.get("raw_event_trace_path"))
        if _sha(raw)!=w.get("raw_event_trace_sha256"):
            errors.append("raw event trace SHA256 mismatch")
        if raw.suffix.lower() not in (".csv",".bin",".wfm",".isf"):
            errors.append("raw event trace lacks supported instrument format")
    except (ValueError,OSError) as exc:
        errors.append(str(exc))
    if w.get("power_stage_energy_limited") is not True:
        errors.append("fault test energy limiting not affirmed")
    if w.get("voltage_current_soa_reviewed_before_test") is not True:
        errors.append("prior bench SOA review missing")
    return not errors,errors,{
        "witness_sha256":_sha(path),
        "fault_raw_trace_sha256":w.get("raw_event_trace_sha256"),
    }

def build(path:Path)->dict:
    result={"kind":"D0_P0_SIX_MODE_FAULT_EVIDENCE_MATRIX","schema_version":SCHEMA,
      "status":"MISSING_OR_INVALID_EVIDENCE","matrix_complete":False,
      "physical_gate_protection_approved":False,"fabrication_approved":False,
      "all_ten_gate_hardware_proven":False,
      "origin_authenticated_by_software":False,
      "requires_independent_event_trace_and_fault_injection_review":True,
      "cases":{},"errors":[],"missing_modes":[]}
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError,UnicodeError) as exc:
        result["errors"].append("matrix manifest invalid: "+str(exc))
        return result
    if not isinstance(data,dict) or data.get("schema_version")!=SCHEMA:
        result["errors"].append("unsupported schema/version")
        return result
    rev=data.get("hardware_revision")
    if not _real(rev):
        result["errors"].append("physical hardware_revision required")
    rows=data.get("cases")
    if not isinstance(rows,list):
        result["errors"].append("cases must be an array")
        return result
    modes=[r.get("mode") for r in rows if isinstance(r,dict)]
    if len(rows)!=len(modes) or len(modes)!=len(set(modes)):
        result["errors"].append("malformed/duplicate scenario")
    result["missing_modes"]=sorted(set(MODES)-set(modes))
    result["errors"] += ["unexpected scenario "+str(m) for m in modes if m not in MODES]
    base=path.resolve().parent
    seen_witness=set()
    seen_case_ids=set()
    seen_waveform_hashes=set()
    seen_event_hashes=set()
    for row in rows:
        if not isinstance(row,dict) or row.get("mode") not in MODES:
            continue
        mode=row["mode"]
        errors=[]
        files={}
        try:
            for name in PATHS:files[name]=_file(base,row.get(name))
        except (ValueError,OSError) as exc:
            errors.append(str(exc))
        if mode in result["cases"]:
            errors.append("duplicate mode");continue
        signature={}
        if files:
            try:
                report=single.run(*(files[n] for n in PATHS[:-1]))
                if report.get("status")!="CHAIN_CONSISTENT_CAPTURE_ONLY":
                    errors.append("single-capture chain did not pass: "+str(report.get("status")))
                case_id=report.get("case_id")
                if case_id!=row.get("case_id"):
                    errors.append("single-capture case_id mismatch")
                if case_id in seen_case_ids:
                    errors.append("reused case_id across independent fault scenarios")
                seen_case_ids.add(case_id)
                cfg=json.loads(files["config"].read_text(encoding="utf-8"))
                if cfg.get("hardware_revision")!=rev:
                    errors.append("capture hardware revision mismatch")
                signature={n:_sha(files[n]) for n in PATHS[:-1]}
                witnessed, issues, witness_hash = _witness(files["witness_record"],mode,rev)
                errors.extend(issues)
                signature.update(witness_hash)
                raw_hash=signature["csv"]
                if raw_hash in seen_waveform_hashes:
                    errors.append("reused identical ten-gate waveform for a different fault scenario")
                seen_waveform_hashes.add(raw_hash)
                event_hash=signature["fault_raw_trace_sha256"]
                if event_hash in seen_event_hashes:
                    errors.append("reused identical raw fault-event trace")
                seen_event_hashes.add(event_hash)
                if files["witness_record"] in seen_witness:
                    errors.append("reused the same witness for independent fault scenarios")
                seen_witness.add(files["witness_record"])
                if report.get("power_stage_fabrication_approved") is not False:
                    errors.append("single chain wrongly asserted fabrication approval")
                if witnessed and not errors:
                    signature["chain_reproducible"]=True
            except (OSError,ValueError,TypeError,KeyError) as exc:
                errors.append("cannot recompute chain: "+str(exc))
        result["cases"][mode]={"status":"CAPTURE_CHAIN_VERIFIED_STILL_NEEDS_EXPERT_HARDWARE_REVIEW"
                                if not errors else "REJECTED",
                              "errors":errors,"evidence_sha256":signature}
    for mode in result["missing_modes"]:
        result["cases"][mode]={"status":"MISSING","errors":["no capture for this physical mode"]}
    if result["missing_modes"]:
        result["errors"].append("missing scenarios "+",".join(result["missing_modes"]))
    if any(x["status"]!="CAPTURE_CHAIN_VERIFIED_STILL_NEEDS_EXPERT_HARDWARE_REVIEW"
           for x in result["cases"].values()):
        result["errors"].append("one or more test modes not independently reproducible")
    result["matrix_complete"]=not result["errors"]
    result["status"]=("SIX_CAPTURE_CHAINS_CONSISTENT_NEEDS_PHYSICAL_REVIEW"
                      if result["matrix_complete"] else "MISSING_OR_INVALID_EVIDENCE")
    return result

def main()->int:
    a=argparse.ArgumentParser()
    a.add_argument("--manifest",required=True,type=Path)
    a.add_argument("--report",type=Path)
    v=a.parse_args()
    result=build(v.manifest)
    body=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if v.report:
        v.report.parent.mkdir(parents=True,exist_ok=True)
        v.report.write_text(body,encoding="utf-8",newline="\n")
    print(body)
    return 0 if result["matrix_complete"] else 1

if __name__=="__main__":
    raise SystemExit(main())
