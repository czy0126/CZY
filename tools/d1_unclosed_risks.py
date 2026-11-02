"""Risk gates synthesized from the *latest committed simulation evidence*.

This is NOT an actual hardware SOA sign-off: magnetics and device data still
need vendor proof, actual board routing, thermal design, and raw confirmation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_hotfault_log import SS_RT_ONLY_THRESHOLD_V
import hotfault_engineering_gate as hotgate

ROOT = Path(__file__).resolve().parent.parent
PP = ROOT / "design/v3/power_priority"
OUT = PP / "unclosed_risk_register.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build() -> dict:
    fault = _load(PP / "fault_48v_120a_target.json")
    cold = _load(PP / "cold_start_48v_120a_target.json")
    ledger50 = _load(PP / "energy_ledger_50v_120a.json")
    lr = _load(ROOT / "design/v3/bom/lr_design.json")
    gate = _load(ROOT / "hardware/dcx_main/d1_fabrication_gate.json")
    fault_peak = float(fault["ipri_peak_before_trip_a"])
    inductance = float(lr["inductance_h"])
    two = next(c for c in lr["candidates"] if c["turns"] == 2)
    three = next(c for c in lr["candidates"] if c["turns"] == 3)
    # Invert the existing flux formula (L * I)/(N * Ae) to recover its
    # core Ae, instead of inventing an unrelated area for this new analysis.
    area = inductance * float(lr["peaks_a"]["steady"]) / (
        2 * float(two["flux_t"]["steady"]))
    bsat = float(two["worst_flux_t"]) / float(two["worst_flux_frac_bsat"])
    soft_limit = 0.9 * bsat
    flux2 = inductance * fault_peak / (2 * area)
    flux3 = inductance * fault_peak / (3 * area)
    before_fault_ss = float(fault["ss_at_engage_v"])
    independent_hotfault = hotgate.build()
    loss_gap = float(ledger50["balance"]["loss_residual_w"])
    closure = float(ledger50["balance"]["closure_residual_w"])
    target = float(ledger50["balance"]["target_w"])
    evidence = {
        "manufacturing_gate": gate["status"],
        "48v_120a_fault_oc_trip_us": fault["fault_to_trip_us"],
        "48v_120a_fault_peak_primary_a": fault_peak,
        "48v_120a_fault_vss_at_engage_v": before_fault_ss,
        "ss_rt_only_threshold_v": SS_RT_ONLY_THRESHOLD_V,
        "independent_hotfault_simulation_accepted": independent_hotfault["all_independent_hotfault_cases_accepted"],
        "independent_hotfault_evidence": independent_hotfault["cases"],
        "48v_120a_fault_solver_prefix_only": fault["solver_prefix_only"],
        "48v_120a_cold_reached_full_tstop": cold["reached_tstop"],
        "50v_120a_model_loss_residual_w": loss_gap,
        "50v_120a_model_closure_residual_w": closure,
        "50v_120a_model_closure_status": ledger50["balance"]["closure_status"],
        "target_residual_w": target,
        "lr_core_ae_m2_from_existing_design": area,
        "lr_bsat_ref_t": bsat,
        "lr_0p9_bsat_limit_t": soft_limit,
        "lr_2turn_flux_at_fault_peak_t": flux2,
        "lr_3turn_flux_at_fault_peak_t": flux3,
    }
    risks = [
        {
            "id": "F01",
            "priority": "P0",
            "blocker": "fully settled independent 48/50V hot faults lack completed log and waveform engineering review",
            "blocked": not independent_hotfault["all_independent_hotfault_cases_accepted"],
            "next_evidence": "run both independent hot faults, verify their LOG precheck, gate turn-off, full RAW waveform and reviewed evidence hashes",
            "file": "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.cir",
        },
        {
            "id": "F02",
            "priority": "P0",
            "blocker": "original 120A overload transient did not reach 8ms",
            "blocked": bool(fault["solver_prefix_only"]),
            "next_evidence": "complete one independently logged fault run; inspect nonlinear model/solver near collapse",
            "file": "design/v3/power_priority/fault_48v_120a_target.json",
        },
        {
            "id": "M01",
            "priority": "P0",
            "blocker": "2-turn Lr fails 0.9 Bsat margin at measured fault peak",
            "blocked": flux2 > soft_limit,
            "next_evidence": "retain 3-turn as candidate only; verify L(I), gap and physical Bsat at worst-case fault / tolerance",
            "file": "design/v3/bom/lr_design.json",
        },
        {
            "id": "E01",
            "priority": "P0",
            "blocker": "50V 120A model loss inventory gap exceeds 0.2W",
            "blocked": abs(loss_gap) > target,
            "next_evidence": "recompute same-window 50V/120A component losses, gate boundary, storage and compare timesteps",
            "file": "design/v3/power_priority/energy_ledger_50v_120a.json",
        },
        {
            "id": "E02",
            "priority": "P0",
            "blocker": "50V 120A full energy closure not approved",
            "blocked": ledger50["balance"]["closure_status"] != "CLOSED" or abs(closure) > target,
            "next_evidence": "trace residual physical source and numerical convergence, do not relax 0.2W",
            "file": "design/v3/power_priority/sr_loss_audit_50v_120a.json",
        },
        {
            "id": "C01",
            "priority": "P0",
            "blocker": "D1 actual native CAD lacks verified magnetic pads, MPN, ERC and routed PCB",
            "blocked": gate["status"] != "APPROVED_WITH_DOCUMENTED_EVIDENCE",
            "next_evidence": "signed vendor pinouts + native footprint persistence + full ERC/PCB/DRC",
            "file": "hardware/dcx_main/d1_fabrication_gate.json",
        },
    ]
    return {
        "status": "ENGINEERING_GATES_BLOCKED_NOT_RATED",
        "data_quality": "All facts are from committed LTspice-model JSON, never hardware",
        "evidence": evidence,
        "risks": risks,
        "next_priority": ["F01", "F02", "M01", "C01", "E01", "E02"],
        "continuous_power_approved": False,
        "detailed_thermal_design": "DEFERRED, no continuous current qualification",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    value = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    if args.write:
        OUT.write_text(value, encoding="utf-8", newline="\n")
    elif OUT.read_text(encoding="utf-8") != value:
        raise SystemExit("risk register stale; run --write")
    print("unclosed engineering risk gates; NOT_FOR_FAB / NOT_RATED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
