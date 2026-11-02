"""Risk gates synthesized from the *latest committed simulation evidence*.

This is NOT an actual hardware SOA sign-off: magnetics and device data still
need vendor proof, actual board routing, thermal design, and raw confirmation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PP = ROOT / "design/v3/power_priority"
OUT = PP / "unclosed_risk_register.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build() -> dict:
    fault = _load(PP / "fault_48v_120a_target.json")
    cold = _load(PP / "cold_start_48v_120a_target.json")
    hot48 = _load(PP / "hotfault_48v_120a.json")
    hot50 = _load(PP / "hotfault_50v_120a.json")
    ledger50 = _load(PP / "energy_ledger_50v_120a.json")
    # ELE-09's decisive leg: the same 50 V/120 A circuit over one phase-aligned
    # window (133 gate periods).  It separates a short-window artifact from a
    # real gap, so the register must carry both readings rather than the short
    # one alone.
    aligned50 = _load(PP / "energy_ledger_50v_120a_aligned.json")
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
    # ELE-08: the settled-state fault reaches a higher primary peak than the
    # cold-start fault did (97.44 A vs 84.83 A).  Same deck inductance and the
    # same recovered Ae, so the flux is directly comparable.
    hot_peak = float(hot48["fault"]["ipri_peak_before_trip_a"])
    hot50_peak = float(hot50["fault"]["ipri_peak_before_trip_a"])
    hot_flux2 = inductance * hot_peak / (2 * area)
    hot_flux3 = inductance * hot_peak / (3 * area)
    hot50_flux2 = inductance * hot50_peak / (2 * area)
    hot50_flux3 = inductance * hot50_peak / (3 * area)
    before_fault_ss = float(fault["ss_at_engage_v"])
    loss_gap = float(ledger50["balance"]["loss_residual_w"])
    closure = float(ledger50["balance"]["closure_residual_w"])
    target = float(ledger50["balance"]["target_w"])
    aligned_loss_gap = float(aligned50["balance"]["loss_residual_w"])
    aligned_closure_avg = float(
        aligned50["balance"]["period_averaged"]["closure_residual_w"])
    aligned_sem = float(aligned50["balance"]["resolution"]["sem_w"])
    # ELE-09 inventory audit: every dissipative element in the deck is either
    # measured by a loss term or bounded here.  The only un-inventoried
    # resistor that carries current is Cin's 5 mOhm ESR; I(Cin) was measured
    # on the same aligned raw (saved axis 0-110 us).  Keep the two inputs so
    # the comparison stays reproducible rather than a remembered ratio.
    cin_ac_rms_a = 0.3493
    cin_esr_w = 5e-3 * cin_ac_rms_a ** 2
    evidence = {
        "manufacturing_gate": gate["status"],
        "48v_120a_fault_oc_trip_us": fault["fault_to_trip_us"],
        "48v_120a_fault_peak_primary_a": fault_peak,
        "48v_120a_fault_vss_at_engage_v": before_fault_ss,
        "48v_120a_fault_solver_prefix_only": fault["solver_prefix_only"],
        "48v_120a_cold_reached_full_tstop": cold["reached_tstop"],
        "50v_120a_model_loss_residual_w": loss_gap,
        "50v_120a_model_closure_residual_w": closure,
        "50v_120a_model_closure_status": ledger50["balance"]["closure_status"],
        # ELE-09: 133 periods = one phase-aligned window.  If the gap were a
        # short-window artifact, this number would collapse toward zero.
        "50v_120a_aligned_window_periods": aligned50["window"]["periods"],
        "50v_120a_aligned_loss_residual_w": aligned_loss_gap,
        "50v_120a_aligned_closure_period_averaged_w": aligned_closure_avg,
        "50v_120a_aligned_resolution_sem_w": aligned_sem,
        "50v_120a_aligned_resolves_0p2_w": aligned_sem <= target,
        "50v_120a_cin_ac_rms_a": cin_ac_rms_a,
        "50v_120a_cin_esr_loss_w": cin_esr_w,
        "50v_120a_loss_residual_moves_between_windows_w": aligned_loss_gap - loss_gap,
        "target_residual_w": target,
        "lr_core_ae_m2_from_existing_design": area,
        "lr_bsat_ref_t": bsat,
        "lr_0p9_bsat_limit_t": soft_limit,
        "lr_2turn_flux_at_fault_peak_t": flux2,
        "lr_3turn_flux_at_fault_peak_t": flux3,
        # ELE-08, 48 V: fault lands on a settled operating point instead of the
        # soft-start ramp.  The stability flags are measurements, not settings.
        "hotfault_48v_120a_stable_at_design_point":
            hot48["pre_fault"]["stable_at_design_point"],
        "hotfault_48v_120a_pre_fault_vss_v": hot48["pre_fault"]["ss"]["mean"],
        "hotfault_48v_120a_pre_fault_vout_v": hot48["pre_fault"]["vout"]["mean"],
        "hotfault_48v_120a_pre_fault_vout_pp_v": hot48["pre_fault"]["vout"]["pp"],
        "hotfault_48v_120a_trip_delay_us": hot48["fault"]["delay_from_engage_us"],
        "hotfault_48v_120a_lr_peak_before_trip_a": hot_peak,
        "hotfault_48v_120a_sr_forward_peak_a":
            hot48["fault"]["sr_forward_peak_whole_record_a"],
        "hotfault_48v_120a_solver_completed": hot48["log"]["solver_completed"],
        # Both decks latch one SR gate ~30 us after trip (48 V: A at 247.07 us,
        # 50 V: B at 244.47 us).  The latch alone does not stall the solver --
        # 48 V finishes 320 us -- so the record must keep the flag per deck.
        "hotfault_48v_120a_sr_gate_latched_at_end":
            hot48["fault"]["sr_gate_latched_at_end"],
        "hotfault_50v_120a_sr_gate_latched_at_end":
            hot50["fault"]["sr_gate_latched_at_end"],
        "hotfault_48v_120a_2turn_flux_at_fault_peak_t": hot_flux2,
        "hotfault_48v_120a_3turn_flux_at_fault_peak_t": hot_flux3,
        # ELE-08, 50 V: same definition, 9.15x overload instead of 8.7x because
        # the nominal load is 16.3 mOhm.  The peak is the worst recorded one.
        "hotfault_50v_120a_stable_at_design_point":
            hot50["pre_fault"]["stable_at_design_point"],
        "hotfault_50v_120a_pre_fault_vss_v": hot50["pre_fault"]["ss"]["mean"],
        "hotfault_50v_120a_pre_fault_vout_v": hot50["pre_fault"]["vout"]["mean"],
        "hotfault_50v_120a_pre_fault_vout_pp_v": hot50["pre_fault"]["vout"]["pp"],
        "hotfault_50v_120a_severity_x": hot50["fault"]["severity_x"],
        "hotfault_50v_120a_trip_delay_us": hot50["fault"]["delay_from_engage_us"],
        "hotfault_50v_120a_lr_peak_before_trip_a": hot50_peak,
        "hotfault_50v_120a_sr_forward_peak_a":
            hot50["fault"]["sr_forward_peak_whole_record_a"],
        "hotfault_50v_120a_solver_completed": hot50["log"]["solver_completed"],
        # The 50 V run stalled at 296.929 us of the 320 us window: saved time
        # moved 1 ns in 62 min.  The raw prefix is readable but the .log has no
        # completion line, so this is prefix evidence, not a finished run.
        "hotfault_50v_120a_solver_prefix_only": hot50["solver_prefix_only"],
        "hotfault_50v_120a_2turn_flux_at_fault_peak_t": hot50_flux2,
        "hotfault_50v_120a_3turn_flux_at_fault_peak_t": hot50_flux3,
    }
    risks = [
        {
            "id": "F01",
            "priority": "P0",
            "blocker": "settled-state fault evidence is simulation only and the 50V run "
                       "stopped at 296.93us of 320us (solver collapse, no completion line); "
                       "OC timing, SR SOA and Lr saturation at ~101A are unconfirmed on hardware",
            "blocked": True,
            "next_evidence": "bench-verify OC delay and SR/Lr peaks on a physical sample; "
                             "confirm real Lr saturation at the 101A fault peak; the 50V "
                             "296.928us stall is numerical (smooth 3 V/us dead state, LTE-driven) -- "
                             "standby cannot close it because tSTBY_DET is 7.5 ms; either accept the "
                             "prefix or run a documented SOLVER_DIAGNOSTIC and compare 175-215us peaks",
            "file": "design/v3/power_priority/hotfault_48v_120a.json",
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
            "next_evidence": f"the settled-state 48V fault raises the peak to {hot_peak:.2f} A "
                             f"(2-turn {hot_flux2:.3f} T); retain 3-turn as candidate only and verify "
                             "L(I), gap and physical Bsat at this worst case / tolerance",
            "file": "design/v3/bom/lr_design.json",
        },
        {
            "id": "E01",
            "priority": "P0",
            "blocker": "50V 120A model loss inventory gap exceeds 0.2W",
            "blocked": abs(loss_gap) > target,
            "next_evidence": "ELE-09 ruled out a short-window artifact (22 periods 0.4986 W vs "
                             "133 aligned 0.4921 W, sem 0.050 W) and the deck is now exhausted: "
                             "no un-inventoried dissipative element can hold 0.49 W (Cin ESR "
                             "0.61 mW measured, Cbt carries no charge).  Remaining candidates are "
                             "the port reading (~2 mV of mean Vout) and the behavioral-SR "
                             "integration error; do not relax 0.2 W",
            "file": "design/v3/power_priority/energy_ledger_50v_120a_aligned.json",
        },
        {
            "id": "E02",
            "priority": "P0",
            "blocker": "50V 120A full energy closure not approved",
            "blocked": ledger50["balance"]["closure_status"] != "CLOSED" or abs(closure) > target,
            "next_evidence": "the aligned 133-period window confirms the 0.698 W closure is "
                             "stable (sem 0.050 W); ELE-09's inventory audit leaves only port "
                             "and numerical candidates, so settle it with an edge-aligned "
                             "fixed-step integration rather than more step reduction; "
                             "do not relax 0.2 W",
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
