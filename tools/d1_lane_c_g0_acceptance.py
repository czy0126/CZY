"""Issue #133: fail-closed G0 integration acceptance and raw-capture handoff.

This is a *documentation and evidence intake gate*, NEVER a software permit to
energize a physical 48V power stage. Structural ERC and simulation are not G0.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import d1_lane_c_g0_gate as g0
import d1_lane_c_hs_candidate as cad
import d1_lane_c_uvlo_evidence as uvlo
import d1_lane_c_sim_evidence as gate_sim
import d1_lane_c_bias_supply_candidate as bias

OUT = ROOT / "design/v3/stage_f/d1_lane_c_g0"
REPORT = OUT / "g0_integration_acceptance_NOT_FOR_FAB.json"
CAPTURES = OUT / "g0_gate_fault_capture_matrix_NOT_FOR_FAB.csv"
TEMPLATE = OUT / "g0_witness_template_NOT_FOR_FAB.json"
SUBMISSION = OUT / "g0_external_witnesses.json"
V4_DIR = ROOT / "hardware/dcx_main/g2/d1_g0_INDEPENDENT_SOURCE_V4_MAINBOARD_NOT_FOR_FAB"
V4_REPORT = V4_DIR / "V4_mainboard_acceptance_NOT_FOR_FAB.json"

# Source of truth for scope and ownership: these obligations describe G0 only.
# They do not turn G1 load testing or G3 coldplate requirements into blockers.
OBLIGATIONS = (
    ("G0-01", "Lane A / electrical integrator", "Actual primary input, half-bridge, Lr/Cr and SW/Kelvin closed on ONE native board; native ERC/DRC and source-net parity", "native_board_and_pin_parity"),
    ("G0-02", "Lane B / magnetics integrator", "Lr, CT and the 3:1:1 transformer winding(s) actually required by the selected FIRST low-power circuit, with physical pin/DOT, insulation, continuity, Lm/leakage and saturation evidence; T1-T4 24-terminal/12-layer scope only if used in this G0 circuit", "magnetics_pin_dot_and_inspection"),
    ("G0-03", "Lane C / electrical integrator", "Independent primary and secondary 12V bias sources with correct different ground domains, UVLO, initial start and hold-up measurements", "bias_isolation_uvlo"),
    ("G0-04", "Lane C / hardware integrator", "External NC E-stop + independent 48V input power interruption including cable loss and welded contact fault tests", "estop_power_disconnection"),
    ("G0-05", "Lane C / hardware integrator", "Isolated high-side GH1-SW monitor and HB-SW bootstrap voltage validity; sensor absent or unpowered must inhibit enable", "floating_vgs_monitor"),
    ("G0-06", "Lane C / bench test operator", "Ten source-referenced VGS captures for six listed fault modes; bias collapse and permit/relay state, off-time and overlap", "all_gate_fault_waveforms"),
    ("G0-07", "Lane C / electrical integrator", "Worst-case driver/supervisor delay, effective 12V hold-up at VDDmin, MOSFET gate charge, shorted bias and SOA review", "gate_safety_timing_and_soa"),
    ("G0-08", "A/B/C integrator", "Physical low-energy bench: pre-power polarity/short/insulation checks, temporary cooling, independent current limit, instrument serials", "unpowered_preflight_and_cooling"),
    ("G0-09", "A/B integrator", "Zero open connections on the selected complete G0 power circuit and no ignored safety-critical native ERC/DRC checks; optional G2/G3 hardware is not required for G0", "final_native_erc_drc"),
)

CHANNELS = tuple(f"GA{i}" for i in range(1, 9)) + ("GH1", "GL1")
CAPTURE_COLUMNS = (
    "fault_mode", "gate", "vgs_positive_probe", "vgs_negative_probe",
    "capture_required", "raw_scope_artifact", "sample_interval_s",
    "measured_off_time_s", "review_status",
)

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def safe_file(relative: str, root: Path) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("witness artifact must use a nonempty project-relative path")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("witness artifact escapes repository") from exc
    if not path.is_file():
        raise ValueError("witness artifact is not a regular file: " + relative)
    return path

def validate_witness(item_id: str, submission: dict, root: Path) -> dict:
    """Record evidence provenance only, not electronic/hardware approval."""
    if not isinstance(submission, dict):
        raise ValueError(f"{item_id}: witness entry must be a mapping")
    if submission.get("result") != "SUBMITTED_FOR_REVIEW":
        raise ValueError(f"{item_id}: witness must not assert PASS or hardware approval")
    fields = ("board_serial", "operator", "reviewer", "date", "test_procedure", "measurement_summary")
    if any(not isinstance(submission.get(k), str) or not submission[k].strip() for k in fields):
        raise ValueError(f"{item_id}: missing traceable witness metadata")
    if submission["operator"].strip() == submission["reviewer"].strip():
        raise ValueError(f"{item_id}: independent reviewer required")
    artifacts = submission.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError(f"{item_id}: at least one original physical artifact required")
    receipts = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError(f"{item_id}: invalid artifact")
        name, expected = artifact.get("path"), artifact.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError(f"{item_id}: missing SHA256")
        path = safe_file(name, root)
        if digest(path) != expected.lower():
            raise ValueError(f"{item_id}: artifact checksum mismatch")
        receipts.append({"path": name, "sha256": expected.lower()})
    # User-supplied spreadsheets/claims cannot be electronically equated with
    # a physically signed safety review, even when all SHA256 values match.
    return {"status": "SUBMITTED_UNVERIFIED_HARDWARE",
            "board_serial": submission["board_serial"].strip(),
            "reviewer": submission["reviewer"].strip(),
            "artifact_hashes": receipts}

def capture_csv(faults: tuple[str, ...]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CAPTURE_COLUMNS)
    for mode in faults:
        for gate in CHANNELS:
            ret = "SW" if gate == "GH1" else ("PGND" if gate == "GL1" else "SR_SOURCE_RETURN")
            writer.writerow((mode, gate, gate, ret, "YES", "PENDING", "PENDING",
                             "PENDING", "PENDING"))
    return buffer.getvalue()

def template() -> dict:
    return {"kind": "D1_G0_PHYSICAL_WITNESS_TEMPLATE_NOT_A_RELEASE",
            "never_use_as_hardware_permit": True,
            "instructions": "Copy to g0_external_witnesses.json only after actual bench work; status SUBMITTED_FOR_REVIEW with raw files and SHA256; independent physical approval remains external.",
            "items": {ident: {"result": "PENDING", "board_serial": None,
                "operator": None, "reviewer": None, "date": None,
                "test_procedure": None, "measurement_summary": None,
                "artifacts": []} for ident, _, _, _ in OBLIGATIONS}}

def current_v4_mainboard_evidence() -> dict:
    """Hash-verify native CAD receipts without equating them to G0 approval."""
    if not V4_REPORT.is_file():
        raise ValueError("latest integrated V4 motherboard acceptance missing")
    data = json.loads(V4_REPORT.read_text("utf-8"))
    if not isinstance(data, dict) or data.get("PCB_footprints") != 157 or (
        data.get("independent_schematic_ref_pin_net_parity") != 433 or
        data.get("native_PCB_DRC_violations") != 0 or
        data.get("native_PCB_unconnected") != 0 or
        data.get("native_PCB_ERC_violations") != 0 or
        data.get("secondary_physically_reassigned_pads") != 129 or
        data.get("external_isolated_12v_input_ports") != 2 or
        data.get("independent_SCH_generated_from_PCB") is not False or
        data.get("fab_release") is not False or
        data.get("energization_allowed") is not False):
        raise ValueError("V4 native CAD metadata drift or unsafe release flag")
    for name, expected in data.get("package_sha256", {}).items():
        path=V4_DIR / name
        if not path.is_file() or digest(path) != expected:
            raise ValueError("V4 source-hashed native CAD file mismatch: " + name)
    if len(data.get("package_sha256", {})) < 12:
        raise ValueError("V4 evidence package incomplete")
    return data

def build(witness_data: dict | None = None, evidence_root: Path = ROOT) -> dict:
    base = g0.build()  # Re-check locked source SHA and D0 structural wiring.
    parts, _, sch_text = cad.expected_text()
    native = cad.check_native(parts, sch_text)  # exported netlist, BOM, ERC
    bp, _, bs = bias.expected()
    v4 = current_v4_mainboard_evidence()
    independent_bias = bias.check(bp, bs)  # separate physical return domains, NOT integrated
    if independent_bias["native_erc_violations"] != 0:
        raise ValueError("native two-domain bias candidate ERC regressed")
    if not independent_bias["secondary_supply_ground_separate_in_native_netlist"]:
        raise ValueError("secondary bias must be physically isolated")
    model = uvlo.build()  # raw/log from *old* model, not latest AND stage
    passive = gate_sim.build()
    if native["native_erc_violations"] != 0 or native["netlist_pins_checked"] < 560:
        raise ValueError("candidate native CAD check regressed")
    if not native["bench_primary_secondary_bias_ground_tied"]:
        raise ValueError("expected bench-only ground caveat disappeared: review domain split")
    if base["gate_0_approved"] or base["energization_allowed"]:
        raise ValueError("unsafe upstream G0 approval detected")
    if model["candidate_matches_original_simulation_snapshot"]:
        raise ValueError("model snapshot changed: independent re-review required")
    if model["model_includes_new_external_estop_and_hs_monitor_gate"]:
        raise ValueError("simulation scope unexpectedly enlarged: independent re-review required")
    if passive["physical_sr_gate_safe_off_proven"]:
        raise ValueError("illustrative passive decay masquerades as physical proof")
    if witness_data is None:
        witness_data = json.loads(SUBMISSION.read_text("utf-8")) if SUBMISSION.exists() else {}
    if not isinstance(witness_data, dict):
        raise ValueError("witness data must be an object")
    items = witness_data.get("items", {})
    if not isinstance(items, dict):
        raise ValueError("witness items must be an object")
    expected_ids = {item[0] for item in OBLIGATIONS}
    if set(items) - expected_ids:
        raise ValueError("unknown G0 witness ID cannot bypass release obligations")
    obligations = []
    for ident, owner, need, artifact_class in OBLIGATIONS:
        entry = {"id": ident, "owner_role": owner, "required": need,
                 "artifact_class": artifact_class, "status": "PENDING",
                 "raw_hardware_witness": None}
        if ident in items and items[ident].get("result") == "SUBMITTED_FOR_REVIEW":
            receipt = validate_witness(ident, items[ident], evidence_root)
            entry["status"] = receipt["status"]
            entry["raw_hardware_witness"] = receipt
        elif ident in items and items[ident].get("result") != "PENDING":
            raise ValueError(f"{ident}: invalid witness state")
        obligations.append(entry)
    mode_names = tuple(x["mode"] for x in base["fault_injections"])
    if len(mode_names) != 6 or len(CHANNELS) != 10:
        raise ValueError("fault-mode or gate coverage changed; reject silently stale plan")
    return {
        "kind": "D1_G0_PHYSICAL_ACCEPTANCE_STOPLINE",
        "status": "NOT_FOR_FAB_G0_BLOCKED_PHYSICAL_WITNESS_REQUIRED",
        "issue": 133, "scope": "G0 first safe 48V->2V low-power startup only; G2/G3 excluded",
        "baseline_pcb_sha256": base["input_pcb_sha256"],
        "baseline_unconnected": base["native_drc_before_after"]["baseline_unconnected_reported"],
        "baseline_ignored_drc_checks": base["native_drc_before_after"]["baseline_ignored_native_drc_checks"],
        "native_bench_erc_violations": native["native_erc_violations"],
        "native_bench_netlist_pins_checked": native["netlist_pins_checked"],
        "native_bench_schematic_sha256": native["output_schematic_sha256"],
        "native_bench_bom_sha256": native["output_bom_sha256"],
        "native_bench_not_production_isolated": native["bench_primary_secondary_bias_ground_tied"],
        "independent_dual_bias_candidate_erc_violations": independent_bias["native_erc_violations"],
        "independent_dual_bias_candidate_pins_checked": independent_bias["native_pin_parity"],
        "independent_dual_bias_candidate_schematic_sha256": independent_bias["sch_sha256"],
        "independent_dual_bias_candidate_secondary_ground_separate": independent_bias["secondary_supply_ground_separate_in_native_netlist"],
        "dual_bias_candidate_is_not_integrated_or_fab_ready": True,
        "latest_native_mainboard_G0_V4": {
           "pcb_footprints": v4["PCB_footprints"],
           "independent_ref_pin_net_parity": v4["independent_schematic_ref_pin_net_parity"],
           "pcb_drc_violations": v4["native_PCB_DRC_violations"],
           "pcb_unconnected": v4["native_PCB_unconnected"],
           "schematic_erc_violations": v4["native_PCB_ERC_violations"],
           "secondary_return_pads_reassigned": v4["secondary_physically_reassigned_pads"],
           "two_external_bias_input_ports": v4["external_isolated_12v_input_ports"],
           "independent_design_schematic_not_reverse_pcb": True,
           "actual_bias_regulation_and_uvlo_not_integrated": True,
           "physical_magnetics_not_vendor_approved": True,
           "g0_remains_blocked": True,
        },
        "prior_uvlo_simulation_is_not_current_interlock_proof":
            model["simulation_must_not_be_claimed_for_latest_full_enable_chain"],
        "illustrative_passive_gate_decay_is_not_hardware_proof":
            not passive["physical_sr_gate_safe_off_proven"],
        "fault_modes": list(mode_names), "gate_channels": list(CHANNELS),
        "required_scope_captures": len(mode_names) * len(CHANNELS),
        "obligations": obligations,
        "all_evidence_submitted_for_independent_review":
            all(x["status"] == "SUBMITTED_UNVERIFIED_HARDWARE" for x in obligations),
        "independent_hardware_signoff": "NOT_OBTAINED",
        "energization_allowed": False,
        "gate_0_approved": False,
        "gate_1_measured_success": False,
        "fabrication_approved": False,
        "approval_never_inferred_from_cad_sim_or_witness_json": True,
        "next_action": "Integrate final A/B/C board then collect original bench traces/physical inspections and independent human G0 signoff",
    }

def serialize(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--require-g0", action="store_true")
    args = ap.parse_args()
    receipt = build()
    modes = tuple(receipt["fault_modes"])
    expected = ((REPORT, serialize(receipt)),
                (TEMPLATE, serialize(template())),
                (CAPTURES, capture_csv(modes)))
    if args.write:
        OUT.mkdir(parents=True, exist_ok=True)
        for target, content in expected:
            target.write_text(content, encoding="utf-8", newline="")
    elif args.check:
        for target, content in expected:
            if not target.is_file() or target.read_text("utf-8") != content:
                print("G0 evidence artifact stale/missing: " + str(target), file=sys.stderr)
                return 1
    elif args.require_g0:
        print("G0 BLOCKED: physical signoff missing; do not energize 48V power stage",
              file=sys.stderr)
        return 1
    print(receipt["status"], "pending",
          sum(x["status"] == "PENDING" for x in receipt["obligations"]),
          "fault_captures_required", receipt["required_scope_captures"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
