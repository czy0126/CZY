"""Read-only G0 physical evidence readiness and 60 scope-file integrity audit.

This tool NEVER accepts/certifies live hardware. It checks what is provably
present, validates raw evidence file names/checksums, and reports per-obligation
physical witness gaps. A zero-DRC KiCad board is CAD progress, NOT a signed
G0 physical sign-off.

  python tools/d1_g0_physical_readiness.py --write
  python tools/d1_g0_physical_readiness.py --check
  python tools/d1_g0_physical_readiness.py --require-g0  # exit nonzero by design
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,sys
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import d1_lane_c_g0_acceptance as g0

BASE=g0.OUT
AUDIT=BASE/"g0_physical_readiness_independent_audit_NOT_FOR_FAB.json"
EVIDENCE_CLASS={
"G0-01":("native_mainboard_netlist_and_assembled_serial","CAD source checks exist; assembled closed power loop, signed native schematic/PCB and board identity still require inspection"),
"G0-02":("physical_transformer_CTs_windings_AND_verified_DOT","Obtain actual T/CT winding pad numbers, dot polarity, insulation and signed physical magnetics test sheet"),
"G0-03":("built_dual_bias_uvlo_startup_AND_holdup_scope","Bench measure both domains' rail rise, UVLO action, hold-up and return isolation"),
"G0-04":("NC_ESTOP_and_independent_48V_break_with_weld_check","Bench test NC E-stop, external DC-rated contactor, de-energized state and welded-contact diagnostic"),
"G0-05":("true_high_side_HO_SW_and_HB_SW_monitored","Independent floating high-side VGS and bootstrap sensor, sensor-lost default-off"),
"G0-06":("60_original_scope_waveforms_AND_independent_review","Acquire all 6 faults x 10 source-referenced gate VGS traces and raw timing captures"),
"G0-07":("worst_case_safety_timing_SOA_AND_actual_caps","Verify actual coil, gate, supply hold-up, supervisor and turn-off timing plus MOSFET SOA"),
"G0-08":("unpowered_preflight_insulation_cooling_instruments","Signed pre-power polarity, shorts, insulation, cooling, independent current limit and instrument serials"),
"G0-09":("complete_assembled_G0_board_AND_no_ignored_safety_DRC","Physical G0 selection, full CAD, all nets closed, all safety-critical ignored DRC cases reviewed")
}
ACCEPTED_FORMATS={".csv",".tsv",".wfm",".isf",".trc",".bin",".tdms",".mat",".h5",".hdf5",".npy",".npz",".raw"}
EMPTY={"","PENDING","NOT_CAPTURED","MISSING","NONE"}
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()

def captures(path:Path,root:Path,expected_faults:list[str],expected_gates:list[str])->dict[str,Any]:
    with path.open("r",newline="",encoding="utf-8-sig") as f:
        r=csv.DictReader(f)
        if r.fieldnames!=list(g0.CAPTURE_COLUMNS):
            raise ValueError("scope capture matrix header changed; unsafe to interpret")
        rows=list(r)
    expected={(f,g) for f in expected_faults for g in expected_gates}
    if len(rows)!=60 or len(expected)!=60:
        raise ValueError("scope matrix must contain six modes x ten gates")
    found=set()
    file_receipts=[]
    rejected=[]
    missing=[]
    for row in rows:
        fault,gate=row["fault_mode"],row["gate"]
        key=(fault,gate)
        if key not in expected or key in found:
            raise ValueError(f"invalid/duplicate G0 capture pair {key!r}")
        found.add(key)
        ref="SW" if gate=="GH1" else ("PGND" if gate=="GL1" else "SR_SOURCE_RETURN")
        if (row["vgs_positive_probe"]!=gate or row["vgs_negative_probe"]!=ref
                or row["capture_required"]!="YES"):
            raise ValueError(f"unsafe VGS source-reference pin mapping {key!r}")
        name=row["raw_scope_artifact"].strip()
        if name.upper() in EMPTY:
            missing.append({"fault_mode":fault,"gate":gate,"negative_probe":ref})
            continue
        # Read raw capture path but NEVER treat it as a physical signoff.
        if Path(name).suffix.lower() not in ACCEPTED_FORMATS:
            rejected.append({"fault_mode":fault,"gate":gate,"reason":"unsupported raw waveform extension"})
            continue
        try:
            file=g0.safe_file(name,root)
        except ValueError:
            rejected.append({"fault_mode":fault,"gate":gate,"reason":"waveform file unavailable or outside project"})
            continue
        if file.stat().st_size==0:
            rejected.append({"fault_mode":fault,"gate":gate,"reason":"empty purported instrument file"})
            continue
        sample=row["sample_interval_s"].strip()
        turnoff=row["measured_off_time_s"].strip()
        try:
            # These are *reported* values, not actual measured data validation.
            if float(sample)<=0 or float(turnoff)<0:
                raise ValueError
        except (TypeError,ValueError):
            rejected.append({"fault_mode":fault,"gate":gate,"reason":"missing or invalid timebase/off-time metadata"})
            continue
        if row["review_status"] not in ("SUBMITTED_FOR_REVIEW","PENDING"):
            rejected.append({"fault_mode":fault,"gate":gate,"reason":"claims automatic PASS / unsupported review state"})
            continue
        file_receipts.append({"fault_mode":fault,"gate":gate,"raw_file":name,
          "byte_size":file.stat().st_size,"sha256":sha(file),
          "status":"RAW_PRESENT_UNVERIFIED_NEEDS_SCOPE_AND_PHYSICAL_REVIEW"})
    if found!=expected:raise ValueError("G0 capture combinations incomplete")
    return {"required":60,"raw_present_unverified":len(file_receipts),
            "missing_raw":len(missing),"rejected":len(rejected),
            "original_raw_files":file_receipts,
            "missing_pairs":missing,"rejected_pairs":rejected,
            "physical_waveform_approval":"NOT_OBTAINED"}

def build(matrix:Path=g0.CAPTURES, evidence_root:Path=ROOT, submitted:dict|None=None)->dict[str,Any]:
    doc=g0.build(witness_data=submitted,evidence_root=evidence_root) if submitted is not None else g0.build()
    if doc["gate_0_approved"] or doc["energization_allowed"] or doc["fabrication_approved"]:
        raise ValueError("upstream G0 unexpectedly claims physical approval")
    if len(doc["obligations"])!=9 or set(EVIDENCE_CLASS)!={r["id"] for r in doc["obligations"]}:
        raise ValueError("G0 nine-item acceptance contract changed")
    wave=captures(matrix,evidence_root,doc["fault_modes"],doc["gate_channels"])
    # A physical witness can be *submitted*, never machine-approved. Distinguish.
    physical=[]
    for item in doc["obligations"]:
        task_id=item["id"]
        code,next_step=EVIDENCE_CLASS[task_id]
        physical.append({"id":task_id,"status":item["status"],
           "claimed_or_signed_physical_PASS":False,
           "evidence_class":code,
           "next_verifiable_hardware_requirement":next_step,
           "requires_human_and_actual_hardware":True})
    return {
       "kind":"D1_G0_NINE_PHYSICAL_WITNESS_READINESS_NOT_A_POWER_PERMIT",
       "source_g0_integration_sha256":sha(g0.REPORT),
       "source_capture_matrix_sha256":sha(matrix),
       "physical_signoff_obligations_total":9,
       "physical_signed_approved":0,
       "not_signed_and_still_requires_hardware":9,
       "status":"PHYSICAL_SIGNOFF_NOT_OBTAINED_DO_NOT_POWER",
       "central_gate_approval":False,
       "V5_mainboard_CAD":{"footprints":doc["latest_native_mainboard_G0_V5"]["pcb_footprints"],
          "pin_parity":doc["latest_native_mainboard_G0_V5"]["independent_schematic_pins"],
          "drc":doc["latest_native_mainboard_G0_V5"]["native_drc"],
          "erc":doc["latest_native_mainboard_G0_V5"]["native_erc"],
          "opens":doc["latest_native_mainboard_G0_V5"]["native_unconnected"],
          "not_an_assembled_G0":True},
       "V6_bias_CAD":{"footprints":doc["new_V6_dual_rail_UVLO_real_KiCad_bias_carrier"]["native_pcb_devices"],
          "pin_parity":doc["new_V6_dual_rail_UVLO_real_KiCad_bias_carrier"]["independently_exported_pin_parity"],
          "drc":doc["new_V6_dual_rail_UVLO_real_KiCad_bias_carrier"]["native_drc"],
          "erc":doc["new_V6_dual_rail_UVLO_real_KiCad_bias_carrier"]["native_erc"],
          "opens":doc["new_V6_dual_rail_UVLO_real_KiCad_bias_carrier"]["native_open"],
          "uvlo_not_wired_to_actual_estop_or_RUN":True},
       "V8_control_and_HS_CAD":{
          "native_parts":doc["new_V8_58part_zero_open_AMC1311_GH_HB_MONITOR_CAD"]["actual_native_footprints"],
          "source_pin_parity":doc["new_V8_58part_zero_open_AMC1311_GH_HB_MONITOR_CAD"]["independent_schematic_pin_parity"],
          "native_DRC":doc["new_V8_58part_zero_open_AMC1311_GH_HB_MONITOR_CAD"]["native_PCB_DRC"],
          "native_ERC":doc["new_V8_58part_zero_open_AMC1311_GH_HB_MONITOR_CAD"]["native_ERC_errors"],
          "native_open":doc["new_V8_58part_zero_open_AMC1311_GH_HB_MONITOR_CAD"]["native_PCB_unconnected"],
          "HS_runtime_phase_aware_protection_installed":False,
          "diagnostic_to_safety_enable_resistor_DNP":True,
          "physical_hardware_assembled_or_signed":False,
       },
       "unreviewed_power_mainboard_drc_categories":doc["baseline_ignored_drc_checks"],
       "capture_matrix":wave,
       "physical_obligations":physical,
       "instrumentation_note":"Physical bench instruments and power interruption are never operated by this script",
       "G0_approved":False,"energization_allowed":False,"fabrication_approved":False
    }

def encode(r:dict)->str:return json.dumps(r,ensure_ascii=False,indent=2)+"\n"

def main()->int:
    arg=argparse.ArgumentParser(description=__doc__)
    group=arg.add_mutually_exclusive_group(required=True)
    group.add_argument("--write",action="store_true")
    group.add_argument("--check",action="store_true")
    group.add_argument("--require-g0",action="store_true")
    opts=arg.parse_args()
    result=build()
    if opts.write:
        AUDIT.write_text(encode(result),encoding="utf-8",newline="")
    elif opts.check:
        if not AUDIT.is_file() or AUDIT.read_text("utf-8")!=encode(result):
            print("G0 independent physical evidence audit stale/missing",file=sys.stderr)
            return 1
    else:
        print("G0 physical witness acceptance not independently signed: 0 / 9; 48V power blocked",file=sys.stderr)
        return 1
    print(result["status"],"signed",result["physical_signed_approved"],
          "of",result["physical_signoff_obligations_total"],
          "scope files",result["capture_matrix"]["raw_present_unverified"],
          "of",result["capture_matrix"]["required"])
    return 0
if __name__=="__main__":
    raise SystemExit(main())
