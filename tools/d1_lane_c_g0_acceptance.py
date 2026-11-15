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
V5_DIR = ROOT / "hardware/dcx_main/g2/d1_g0_UCC24624_KELVIN_V5_INTEGRATED_MAINBOARD_NOT_FOR_FAB"
V5_REPORT = V5_DIR / "V5_integrated_KiCad_ERC_DRC_isolation_gate_NOT_FOR_FAB.json"
BIAS_OEM_DIR = ROOT / "hardware/dcx_main/g2/d1_g0_dual_THN30_bias_carrier_NOT_FOR_FAB"
BIAS_OEM_REPORT = BIAS_OEM_DIR / "G0_dual_30W_isolated_bias_CAD_acceptance_NOT_FOR_FAB.json"
BIAS_V6_DIR = ROOT / "hardware/dcx_main/g2/d1_g0_THN30_UVLO_OPTO_V6_NOT_FOR_FAB"
BIAS_V6_REPORT = BIAS_V6_DIR / "V6_30part_native_UVLO_iso_schematic_receipt_NOT_FOR_FAB.json"
INTERLOCK_V7_DIR=ROOT/"hardware/dcx_main/g2/d1_g0_ESTOP_INTERLOCK_V7_NOT_FOR_FAB"
INTERLOCK_V7_REPORT=INTERLOCK_V7_DIR/"V7_KICAD_INTERLOCK_INCOMPLETE_NOT_FOR_FAB_ACCEPTANCE.json"
INTERLOCK_V8_DIR=ROOT/"hardware/dcx_main/g2/d1_g0_V8_MONITORED_INTERLOCK_NOT_FOR_FAB"
INTERLOCK_V8_REPORT=INTERLOCK_V8_DIR/"V8_58part_source_authored_schematic_native_KiCad_receipt_NOT_FOR_FAB.json"

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

def latest_v5_native_mainboard() -> dict:
    if not V5_REPORT.is_file():
        raise ValueError("latest V5 native mainboard not generated")
    data=json.loads(V5_REPORT.read_text("utf-8"))
    required=(
        data.get("PCB_footprints")==161,
        data.get("schematic_independent_ref_pin_net_parity")==441,
        data.get("native_pcb_DRC_violations")==0,
        data.get("native_pcb_unconnected")==0,
        data.get("native_schematic_ERC_violations")==0,
        data.get("primary_secondary_copper_returns_separate") is True,
        data.get("four_controller_VSS_kelvin_separate_from_gate_current_return") is True,
        data.get("R8_default_DNP") is True,
        data.get("G0_approved") is False,
        data.get("energization_allowed") is False,
        data.get("fabrication_approved") is False,
    )
    if not all(required):raise ValueError("unsafe V5 CAD metadata regression")
    files=data.get("sha256",{})
    if len(files)<12:raise ValueError("V5 CAD files incomplete")
    for name,expected in files.items():
        file=V5_DIR/name
        if not file.is_file() or digest(file)!=expected:
            raise ValueError("V5 native CAD SHA stale "+name)
    return data

def latest_oem_dual_bias_carrier() -> dict:
    if not BIAS_OEM_REPORT.is_file():raise ValueError("G0 Traco carrier board missing")
    data=json.loads(BIAS_OEM_REPORT.read_text("utf-8"))
    valid=(data.get("native_board_footprints")==13 and
        data.get("native_schematic_independent_pin_parity")==34 and
        data.get("native_PCB_DRC_violations")==0 and
        data.get("native_PCB_unconnected")==0 and
        data.get("native_ERC_violations")==0 and
        data.get("module_PN")=="THN 30-4812" and
        data.get("THN30_S_plusV12_return")=="SR_SOURCE_RETURN" and
        data.get("Traco_remote_NC_opencircuit_defaults_ON") is True and
        data.get("fuses_recommended_2A_slow_but_MPN_breaking_inrush_QUALIFIED") is False and
        data.get("physical_48v_main_power_contact_ESTOP_present") is False and
        data.get("G0_approved") is False and
        data.get("fabrication_approved") is False and
        data.get("energization_allowed") is False)
    if not valid:raise ValueError("unsafe or stale dual THN30 CAD evidence")
    files=data.get("native_data_SHA256",{})
    if len(files)<10:raise ValueError("THN30 CAD evidence files incomplete")
    for name,expected in files.items():
        file=BIAS_OEM_DIR/name
        if not file.is_file() or digest(file)!=expected:
            raise ValueError("THN30 CAD SHA stale "+name)
    return data

def current_v6_dual_uvlo_evidence() -> dict:
    """Read source-hashed UVLO voltage-valid CAD, never release 48V."""
    if not BIAS_V6_REPORT.is_file():
        raise ValueError("V6 actual dual rail UVLO daughterboard missing")
    data=json.loads(BIAS_V6_REPORT.read_text("utf-8"))
    if not (
        data.get("device_count")==30 and
        data.get("unique_ref_pin_net_parity")==80 and
        data.get("native_KiCad_ERC_violations")==0 and
        data.get("native_KiCad_DRC_violations")==0 and
        data.get("native_KiCad_unconnected")==0 and
        data.get("secondary_to_primary_status_opto_isolated") is True and
        data.get("status_3pin_is_a_power_stage_enable") is False and
        data.get("UVLO_status_to_physical_ESTOP_and_RUN_closed_loop") is False and
        data.get("g0_approved") is False and
        data.get("energization_allowed") is False and
        data.get("fabrication_approved") is False):
        raise ValueError("unsafe V6 UVLO status or native EDA regression")
    sha=data.get("sha256",{})
    if len(sha)<11:
        raise ValueError("V6 dual UVLO source receipt incomplete")
    for fname,expected in sha.items():
        path=BIAS_V6_DIR/fname
        if not path.is_file() or digest(path)!=expected:
            raise ValueError("V6 dual UVLO native SHA drift "+fname)
    return data

def latest_v7_estop_interlock_candidate() -> dict:
    """V7 is vendor-pin-source CAD with a real NC coil-path but OPEN signal copper."""
    if not INTERLOCK_V7_REPORT.is_file():
        raise ValueError("V7 external NC interlock CAD package missing")
    data=json.loads(INTERLOCK_V7_REPORT.read_text("utf-8"))
    if not (data.get("native_physical_footprint_count")==27 and
       data.get("native_schematic_independent_pin_parity")==81 and
       data.get("native_KiCad_ERC_violations")==0 and
       data.get("native_KiCad_DRC_violations")==0 and
       data.get("native_KiCad_unconnected",0)>0 and
       data.get("manual_rearm_copper_closed") is False and
       data.get("actual_GX14_contactor_and_2NC_emergency_stop_switch_integrated_on_board",False) is False and
       data.get("physical_48v_main_bus_contact_opening_proven") is False and
       data.get("G0_04_physical_approved") is False and
       data.get("fabrication_approved") is False and
       data.get("energization_allowed") is False):
       raise ValueError("unsafe V7 interlock status; manual independent re-review required")
    files=data.get("native_source_files_sha256",{})
    if len(files)<10:raise ValueError("V7 native CAD evidence incomplete")
    for file,digest_value in files.items():
        path=INTERLOCK_V7_DIR/file
        if not path.is_file() or digest(path)!=digest_value:
            raise ValueError("V7 native source file SHA mismatch: "+file)
    return data

def latest_v8_native_GH_HB_monitored_interlock() -> dict:
    """Read exact SHA-hashed V8 full routed PCB/SCH; never physical safety PASS."""
    if not INTERLOCK_V8_REPORT.is_file():
        raise ValueError("V8 native isolated high-side interlock CAD missing")
    data=json.loads(INTERLOCK_V8_REPORT.read_text("utf-8"))
    if not (data.get("native_footprints")==58 and
       data.get("independent_ref_pin_net_parity")==171 and
       data.get("native_ERC_errors")==0 and
       data.get("native_DRC_errors")==0 and
       data.get("native_unconnected")==0 and
       data.get("V7_original_control_connections_physically_routed")==24 and
       data.get("extra_float_isolated_analog_frontend_footprints")==31 and
       data.get("true_AMC1311B_highside_analog_measurement_connected_in_native_CAD") is True and
       data.get("HS_OK_gate_connection_is_DNP_and_NOT_power_permission") is True and
       data.get("independent_phase_aware_HS_watchdog_present") is False and
       data.get("g0_physical_signoff") is False and
       data.get("fabrication_approved") is False and
       data.get("energization_allowed") is False):
        raise ValueError("unsafe/stale V8 CAD success being misused as physical G0 PASS")
    files=data.get("data_files_sha256",{})
    if len(files)<12:raise ValueError("V8 source SHA receipts incomplete")
    for name,expected in files.items():
        p=INTERLOCK_V8_DIR/name
        if not p.is_file() or digest(p)!=expected:
            raise ValueError("V8 independent schematic/PCB receipt SHA drift "+name)
    return data

def build(witness_data: dict | None = None, evidence_root: Path = ROOT) -> dict:
    base = g0.build()  # Re-check locked source SHA and D0 structural wiring.
    parts, _, sch_text = cad.expected_text()
    native = cad.check_native(parts, sch_text)  # exported netlist, BOM, ERC
    bp, _, bs = bias.expected()
    v4 = current_v4_mainboard_evidence()
    v5 = latest_v5_native_mainboard()
    oem_bias = latest_oem_dual_bias_carrier()
    uvlo_v6 = current_v6_dual_uvlo_evidence()
    estop_v7 = latest_v7_estop_interlock_candidate()
    interlock_v8 = latest_v8_native_GH_HB_monitored_interlock()
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
        "latest_native_mainboard_G0_V5": {
           "pcb_footprints":v5["PCB_footprints"],
           "independent_schematic_pins":v5["schematic_independent_ref_pin_net_parity"],
           "native_drc":v5["native_pcb_DRC_violations"],
           "native_unconnected":v5["native_pcb_unconnected"],
           "native_erc":v5["native_schematic_ERC_violations"],
           "source_kelvin_four_UCC24624_pin5_nets":True,
           "C7_C10_nominal_2u2_25v_vendor_selected":True,
           "effective_REG_c_and_SR_noise_not_signed":True,
           "real_power_safety_not_completed":True,
        },
        "new_dual_Traco_48v_12v_bias_carrier_CAD": {
           "modules_30w_each":2,
           "native_pcb_parts":oem_bias["native_board_footprints"],
           "native_schematic_pins":oem_bias["native_schematic_independent_pin_parity"],
           "native_erc":oem_bias["native_ERC_violations"],
           "native_pcb_drc":oem_bias["native_PCB_DRC_violations"],
           "native_pcb_unconnected":oem_bias["native_PCB_unconnected"],
           "real_oem_6pin_thn30_footprint":True,
           "single_second_output_return_separate":True,
           "physically_assembled_and_verified":False,
           "real_main_48v_estop_and_UVLO_not_completed":True,
           "g0_still_blocked":True,
        },
        "new_V6_dual_rail_UVLO_real_KiCad_bias_carrier": {
           "native_pcb_devices": uvlo_v6["device_count"],
           "independently_exported_pin_parity": uvlo_v6["unique_ref_pin_net_parity"],
           "native_drc": uvlo_v6["native_KiCad_DRC_violations"],
           "native_open": uvlo_v6["native_KiCad_unconnected"],
           "native_erc": uvlo_v6["native_KiCad_ERC_violations"],
           "nominal_UVLO_trip_rising_v": uvlo_v6["12v_rising_threshold_typical"],
           "nominal_UVLO_trip_falling_v": uvlo_v6["12v_falling_threshold_typical"],
           "separate_primary_secondary_rail_sense": True,
           "secondary_to_primary_status_opto_isolated": True,
           "physical_hardware_assembled_or_measured": False,
           "UVLO_status_closes_actual_primary_power_contactor_or_RUN": False,
           "main_G0_still_blocked": True,
        },
        "new_V7_external_NC_ESTOP_and_manual_rearm_CAD_NOT_CONNECTED": {
           "native_pcb_footprints":estop_v7["native_physical_footprint_count"],
           "source_authored_pin_parity":estop_v7["native_schematic_independent_pin_parity"],
           "native_schematic_erc":estop_v7["native_KiCad_ERC_violations"],
           "native_pcb_drc":estop_v7["native_KiCad_DRC_violations"],
           "native_pcb_unconnected":estop_v7["native_KiCad_unconnected"],
           "true_series_NC_stop_48V_coil_copper_present":True,
           "CD4013_manual_rearm_only_source_logic":True,
           "actual_signal_copper_all_routed":False,
           "real_HS_GH_SW_sensor_present":False,
           "real_GX14_main_contactor_and_2NC_switch_wired":False,
           "G0_04_physical_approved":False,
           "G0_continues_BLOCKED":True,
        },
        "new_V8_58part_zero_open_AMC1311_GH_HB_MONITOR_CAD": {
           "actual_native_footprints":interlock_v8["native_footprints"],
           "independent_schematic_pin_parity":interlock_v8["independent_ref_pin_net_parity"],
           "native_ERC_errors":interlock_v8["native_ERC_errors"],
           "native_PCB_DRC":interlock_v8["native_DRC_errors"],
           "native_PCB_unconnected":interlock_v8["native_unconnected"],
           "prior_24_V7_copper_connections_closed":True,
           "AMC1311B_GH_minus_SW_HB_minus_SW_native_analog_copper_present":True,
           "separate_floating_HS_12V_power_module_candidate":True,
           "GH_gate_off_is_diagnostic_not_runtime_comparator":True,
           "native_R_HS_RELEASE_0R_is_DNP":True,
           "actual_phase_aware_self_check_watchdog_present":False,
           "real_DUT_physical_G0_05_witness":False,
           "G0_power_permission":False,
           "NOT_FOR_FAB":True,
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
