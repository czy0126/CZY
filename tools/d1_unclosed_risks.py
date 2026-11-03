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
    # F02 follow-up: the same 1 fF aid that completed the 50 V hot-fault does
    # not complete this deck -- it stalls 1.96 ms earlier.  That is a negative
    # result, so the register must carry it rather than leave the aid as an
    # untried prescription.
    cold_conv = _load(PP / "cold_oc_vin48_i120_cshunt.json")
    hot48 = _load(PP / "hotfault_48v_120a.json")
    hot50 = _load(PP / "hotfault_50v_120a.json")
    ledger50 = _load(PP / "energy_ledger_50v_120a.json")
    # ELE-09's decisive leg: the same 50 V/120 A circuit over one phase-aligned
    # window (133 gate periods).  It separates a short-window artifact from a
    # real gap, so the register must carry both readings rather than the short
    # one alone.
    aligned50 = _load(PP / "energy_ledger_50v_120a_aligned.json")
    # ELE-09 follow-up: the four 100 A step lengths are compared at fixed
    # quadrature rules and fixed operating point, which decides what the next
    # experiment has to change.  Raw-only, so it is a local diagnostic record.
    step_op = _load(ROOT / "design/v3/stage_f/sr_step_operating_point.json")
    # ELE-09 follow-up, second leg: the same two step lengths with the
    # resistive load replaced by a ramped constant-current sink, so both draw
    # the same I(out) and only V(out) can move.  The register needs it because
    # it decides whether "pin the current" is still an open prescription.
    csink = _load(ROOT / "design/v3/stage_f/sr_step_operating_point_csink.json")
    # PR #20's alternative to accepting the 50 V prefix: a documented
    # SOLVER_DIAGNOSTIC solve over the same window, with only trtol/abstol and
    # the stop time changed.  It bounds the numerical error of the peaks that
    # the prefix publishes, without pretending the stall itself was fixed.
    diag = _load(PP / "hotfault_50v_120a_diag.json")
    # The convergence aid: the same 50 V circuit with only cshunt=1 fF added.
    # It is the one 50 V solve that reaches 320 us, so the register must record
    # the complete axis *and* the prefix deltas against the stalled base.
    conv50 = _load(PP / "hotfault_50v_120a_cshunt.json")
    # ELE-10's first half: the 48 V probe deck saves all eight SR gates,
    # drain-source voltages and sense currents.  It localises the end-of-record
    # high gate to a side and quantifies what that gate conducts.
    probe48 = _load(PP / "sr_fault_probe_48v_120a.json")
    # ELE-10's 50 V half exists only on the cshunt child (the base solve stalls
    # at 296.929 us and cannot carry the 319 us measurements).  Its end state
    # disagrees qualitatively with the stalled base prefix, so both sources have
    # to be recorded; neither is a safe-shutdown proof.
    probe50 = _load(PP / "sr_fault_probe_50v_120a_cshunt.json")
    # The 48 V robustness control: the same 1 fF perturbation on the deck whose
    # base run completes.  If the latched phase changes here, the end-of-record
    # gate state is selected by the numerical trajectory, not by the circuit.
    conv48 = _load(PP / "hotfault_48v_120a_cshunt.json")
    probe48c = _load(PP / "sr_fault_probe_48v_120a_cshunt.json")
    # The control: the 48 V base run passed the strict log pre-check, so the
    # same comparison on it measures the method rather than the 50 V prefix.
    diag48 = _load(PP / "hotfault_48v_120a_diag.json")
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
    independent_hotfault = hotgate.build()
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
    step_r = step_op["results"]
    csink_r = csink["results"]
    diag_r = diag["results"]
    diag48_r = diag48["results"]
    conv_r = conv50["results"]
    probe_r = probe48["results"]
    probe50_r = probe50["results"]
    conv48_r = conv48["results"]
    probe48c_r = probe48c["results"]
    latches = [row["final_latch"] for row in probe_r["devices"].values()
               if row["final_latch"] is not None]
    latch_max_i = max((row["i_abs_max_a"] for row in latches), default=0.0)
    latch_max_i2t = max((row["i2t_abs_a2s"] for row in latches), default=0.0)
    latch_total_i2t = sum(row["i2t_abs_a2s"] for row in latches)
    latch_start_us = max((row["start_us"] for row in latches), default=0.0)
    latch_duration_us = max((row["duration_us"] for row in latches), default=0.0)
    rep_a = probe_r["devices"]["1A"]
    rep_b = probe_r["devices"]["1B"]
    evidence = {
        "manufacturing_gate": gate["status"],
        "48v_120a_fault_oc_trip_us": fault["fault_to_trip_us"],
        "48v_120a_fault_peak_primary_a": fault_peak,
        "48v_120a_fault_vss_at_engage_v": before_fault_ss,
        "ss_rt_only_threshold_v": SS_RT_ONLY_THRESHOLD_V,
        "independent_hotfault_simulation_accepted": independent_hotfault["all_independent_hotfault_cases_accepted"],
        "hotfault_48v_full_duration_sr_gate_high": bool(
            hot48["reached_tstop"] and hot48["fault"]["sr_gate_latched_at_end"]),
        "hotfault_50v_prefix_and_sr_gate_high": bool(
            hot50["solver_prefix_only"] and hot50["fault"]["sr_gate_latched_at_end"]),
        "hotfault_48v_sr_a_gate_final_v": float(
            hot48["fault"]["sr_a_gate_after_trip"]["final_v"]),
        "hotfault_50v_solver_prefix": bool(hot50["solver_prefix_only"]),
        "independent_hotfault_evidence": independent_hotfault["cases"],
        "48v_120a_fault_solver_prefix_only": fault["solver_prefix_only"],
        "cold_oc_cshunt_variant_completed": cold_conv["results"]["variant_reached_saved_stop"],
        "cold_oc_cshunt_base_t_last_us": cold_conv["results"]["base_t_last_us"],
        "cold_oc_cshunt_variant_t_last_us": cold_conv["results"]["variant_t_last_us"],
        "cold_oc_cshunt_declared_window_covered": cold_conv["results"]["declared_window_fully_covered"],
        "cold_oc_cshunt_ipri_peak_rel": cold_conv["results"]["relative"]["ipri_peak_a"],
        "cold_oc_cshunt_sr_forward_peak_rel": cold_conv["results"]["relative"]["sr_forward_peak_a"],
        "cold_oc_cshunt_trip_delta_s": cold_conv["results"]["delta"]["trip_s"],
        "cold_oc_cshunt_circuit_differences": len(cold_conv["circuit_differences"]),
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
        # The four 100 A step lengths are four operating points, not four
        # discretisations of one: V(out) and the SR on-time both move across
        # them, and the quadrature rule cannot reproduce the difference.
        "sr_step_vout_spread_mv": step_r["vout_spread_mv"],
        "sr_step_on_time_spread_ns": step_r["on_time_spread_ns"],
        "sr_step_charge_quadrature_rel": step_r["quadrature_within_raw_max_rel"],
        "sr_step_charge_cross_raw_rel": step_r["charge_cross_raw_rel"],
        "sr_step_checks_ok": all(step_op["checks"].values()),
        # The SR body-diode loss is not a passive readout: measured across the
        # same four runs it moves 118 W/V of V(out), versus the port's own
        # 2V/RL of 200 W/V.  A mV of V(out) is worth ~0.1 W of SR loss, so the
        # 50 V/120 A gap (2.1 mV) is the same order as the term meant to
        # explain it.
        "sr_step_loss_per_volt_w": step_r["sr_loss_per_volt_w"],
        "sr_step_port_per_volt_w": step_r["port_w_per_volt_w"],
        "sr_step_loss_sensitivity_vs_port": step_r["sr_loss_sensitivity_vs_port"],
        # Pinning I(out) at 100 A does not remove the spread: the 0.5 ns leg
        # still settles higher with ~99 % of the resistive loss difference.
        # The sink itself is faithful -- its 5 ns leg reproduces the resistive
        # 5 ns leg to a fraction of a percent -- so the cause is the model's
        # operating point moving with the step, not the 1 A of load.
        "sr_csink_vout_delta_mv": csink_r["endpoint_pair"]["vout_delta_mv"],
        "sr_csink_diode_loss_spread_x8_w": csink_r["diode_loss_spread_x8_w"],
        "sr_csink_spread_ratio_vs_resistive":
            csink_r["endpoint_spread_ratio_vs_resistive"]["diode_loss_rel"],
        "sr_csink_loss_per_volt_w": csink_r["sr_loss_per_volt_w"],
        "sr_csink_vout_drift_worst_mv": csink_r["vout_drift_worst_mv"],
        "sr_csink_checks_ok": all(csink["checks"].values()),
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
        # The base JSON only saw pair 1/4 gates.  The probe run saves all eight
        # and separates the final latch from the tail of the normal on-time:
        # the latch itself carries ~1.4 A, while the 285 A forward peak lands
        # in the release window right after trip.
        "hotfault_48v_120a_first_sustained_drive_stop_us":
            hot48["fault"]["first_sustained_drive_stop_ms"] * 1e3,
        "sr_fault_probe_48v_checks_ok": all(probe48["checks"].values()),
        "sr_fault_probe_48v_reached_tstop": probe_r["reached_tstop"],
        "sr_fault_probe_48v_solver_prefix_only": probe_r["solver_prefix_only"],
        "sr_fault_probe_48v_devices_high_at_end": probe_r["devices_high_at_end"],
        "sr_fault_probe_48v_latch_start_us": latch_start_us,
        "sr_fault_probe_48v_latch_duration_us": latch_duration_us,
        "sr_fault_probe_48v_latch_max_current_a": latch_max_i,
        "sr_fault_probe_48v_latch_max_i2t_abs_a2s": latch_max_i2t,
        "sr_fault_probe_48v_latch_total_i2t_abs_a2s": latch_total_i2t,
        "sr_fault_probe_48v_a_drive_release_us": rep_a["drive_release_us"],
        "sr_fault_probe_48v_b_drive_release_us": rep_b["drive_release_us"],
        "sr_fault_probe_48v_a_forward_peak_post_a": rep_a["i_forward_peak_post_a"],
        "sr_fault_probe_48v_a_forward_i2t_post_a2s": rep_a["i2t_forward_post_a2s"],
        "sr_fault_probe_48v_a_gate_high_i2t_a2s": rep_a["i2t_while_gate_high_a2s"],
        "hotfault_50v_120a_sr_gate_latched_at_end":
            hot50["fault"]["sr_gate_latched_at_end"],
        # The cshunt child's own eight-device record reaches 320 us and has no
        # gate high at the end -- the opposite of the stalled base prefix.  A
        # 1 fF node capacitance is electrically negligible here, so the two end
        # states cannot both be properties of the circuit: the post-trip gate
        # level is solver-sensitive and must not be quoted as a design fact.
        "sr_fault_probe_50v_cshunt_checks_ok": all(probe50["checks"].values()),
        "sr_fault_probe_50v_cshunt_reached_tstop": probe50_r["reached_tstop"],
        "sr_fault_probe_50v_cshunt_solver_prefix_only": probe50_r["solver_prefix_only"],
        "sr_fault_probe_50v_cshunt_devices_high_at_end":
            probe50_r["devices_high_at_end"],
        "sr_fault_probe_50v_cshunt_final_latch_devices":
            probe50_r["final_latch_devices"],
        # ROBUSTNESS control, 48 V: the base latches A, the 1 fF variant latches
        # B.  The stress barely moves, so the flip is not a different fault --
        # it is the dead-state trajectory choosing the phase.  Record the whole
        # pair: the base latch is still a real model observation, but its phase
        # identity is not a property of the circuit.
        "hotfault_48v_120a_cshunt_checks_ok": all(conv48["checks"].values()),
        "hotfault_48v_120a_cshunt_base_completed": conv48_r["base_reached_saved_stop"],
        "hotfault_48v_120a_cshunt_variant_completed": conv48_r["variant_reached_saved_stop"],
        "hotfault_48v_120a_cshunt_window_us": conv48["window_s"][1] * 1e6,
        "hotfault_48v_120a_cshunt_ipri_peak_rel": conv48_r["relative"]["ipri_peak_a"],
        "hotfault_48v_120a_cshunt_sr_forward_peak_rel":
            conv48_r["relative"]["sr_forward_peak_a"],
        "hotfault_48v_120a_cshunt_trip_delta_ns": conv48_r["delta"]["trip_s"] * 1e9,
        "hotfault_48v_120a_cshunt_circuit_differences": len(conv48["circuit_differences"]),
        "sr_fault_probe_48v_cshunt_checks_ok": all(probe48c["checks"].values()),
        "sr_fault_probe_48v_cshunt_reached_tstop": probe48c_r["reached_tstop"],
        "sr_fault_probe_48v_cshunt_solver_prefix_only": probe48c_r["solver_prefix_only"],
        "sr_fault_probe_48v_cshunt_devices_high_at_end":
            probe48c_r["devices_high_at_end"],
        "sr_fault_probe_48v_cshunt_final_latch_devices":
            probe48c_r["final_latch_devices"],
        "sr_fault_probe_48v_cshunt_latch_max_current_a":
            probe48c_r["final_latch_max_current_a"],
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
        # The diagnostic re-solves 0..220 us with trtol 7->1 and abstol
        # 1e-12->1e-13 (same circuit, same probes).  It is the measured
        # numerical error of the published peaks, not a second opinion.
        "hotfault_50v_120a_diag_checks_ok": all(diag["checks"].values()),
        "hotfault_50v_120a_diag_window_us": diag["window_s"][1] * 1e6,
        "hotfault_50v_120a_diag_ipri_peak_a": diag_r["diagnostic"]["ipri_peak_a"],
        "hotfault_50v_120a_diag_ipri_peak_rel": diag_r["relative"]["ipri_peak_a"],
        "hotfault_50v_120a_diag_sr_forward_peak_rel":
            diag_r["relative"]["sr_forward_peak_a"],
        "hotfault_50v_120a_diag_trip_delta_ns": diag_r["delta"]["trip_s"] * 1e9,
        "hotfault_50v_120a_diag_solver_completed":
            diag["logs"]["diagnostic"]["solver_completed"],
        # CONVERGENCE_DIAGNOSTIC: the base still stalls, the cshunt child runs
        # to the stop.  Both flags are recorded so neither half can be dropped.
        "hotfault_50v_120a_cshunt_checks_ok": all(conv50["checks"].values()),
        "hotfault_50v_120a_cshunt_base_completed": conv_r["base_reached_saved_stop"],
        "hotfault_50v_120a_cshunt_variant_completed": conv_r["variant_reached_saved_stop"],
        "hotfault_50v_120a_cshunt_window_us": conv50["window_s"][1] * 1e6,
        "hotfault_50v_120a_cshunt_ipri_peak_rel": conv_r["relative"]["ipri_peak_a"],
        "hotfault_50v_120a_cshunt_sr_forward_peak_rel":
            conv_r["relative"]["sr_forward_peak_a"],
        "hotfault_50v_120a_cshunt_trip_delta_ns": conv_r["delta"]["trip_s"] * 1e9,
        "hotfault_50v_120a_cshunt_circuit_differences": len(conv50["circuit_differences"]),
        # The 48 V control, whose base run passed the strict log pre-check,
        # moves the same way (and a little more) under the same tightening.
        "hotfault_48v_120a_diag_checks_ok": all(diag48["checks"].values()),
        "hotfault_48v_120a_diag_ipri_peak_rel": diag48_r["relative"]["ipri_peak_a"],
        "hotfault_48v_120a_diag_sr_forward_peak_rel":
            diag48_r["relative"]["sr_forward_peak_a"],
        "hotfault_48v_120a_diag_trip_delta_ns": diag48_r["delta"]["trip_s"] * 1e9,
        "hotfault_50v_120a_2turn_flux_at_fault_peak_t": hot50_flux2,
        "hotfault_50v_120a_3turn_flux_at_fault_peak_t": hot50_flux3,
    }
    risks = [
        {
            "id": "F03",
            "priority": "P0",
            "blocker": (
                "The 48 V eight-device probe localises the end-of-record high gate: "
                f"all four A-side SRs ({', '.join(probe_r['devices_high_at_end'])}) "
                f"stay at {rep_a['gate_end_v']:.3f} V from "
                f"{latch_start_us:.2f} us to the 320 us end, while the final latch "
                f"conducts only {latch_max_i:.2f} A "
                f"({latch_max_i2t:.2e} A2s per device). The "
                f"{rep_a['i_forward_peak_post_a']:.1f} A forward peak lands in the "
                "release window right after trip, not in the latch. 50 V now has a "
                "complete eight-device record only on the cshunt child, and it ends "
                "with no gate high, while the stalled base prefix kept B high from "
                "244.47 us. A 1 fF node capacitance is electrically negligible here, "
                "so the post-trip gate level is solver-sensitive: neither end state "
                "may be quoted as the circuit's behaviour. The 48 V control settles "
                "it: its base latches all four A-side gates, while the same 1 fF "
                "perturbation latches all four B-side gates (249.38 us, 1.20 A) and "
                "leaves A low, with the fault stress moving <0.5 %. The *phase* that "
                "holds a gate high in the dead zone is therefore chosen by the "
                "numerical trajectory; only the low-current character of the latch "
                "(1.2-1.4 A, ~1e-4 A2s per device) survives. The model also "
                "implements neither UCC24624 standby turn-off nor thermal/SOA "
                "limits, so no side may be declared safely shut down."),
            "blocked": bool(hot48["fault"]["sr_gate_latched_at_end"] or
                            hot50["fault"]["sr_gate_latched_at_end"] or
                            hot50["solver_prefix_only"] or
                            probe_r["solver_prefix_only"]),
            "next_evidence": (
                "Do NOT claim complete shutdown from OC=1V alone. The 48 V eight-SR "
                f"window is now measured: A-side drive is released at "
                f"{rep_a['drive_release_us']:.2f} us (trip + "
                f"{rep_a['drive_release_us'] - hot48['fault']['trip_s'] * 1e6:.2f} us) and the "
                f"four A gates re-assert at {latch_start_us:.2f} us; the latch carries "
                f"{latch_max_i:.2f} A / {latch_total_i2t:.2e} A2s total, three orders "
                f"below the {rep_a['i2t_forward_post_a2s']:.4f} A2s forward I2t. "
                "Remaining: (a) a solver-independent determination of the dead-state "
                "gate state, which the 48 V control shows the model cannot supply "
                "(A latches in the base, B in the 1 fF variant; 50 V's prefix and "
                "cshunt child disagree as well), and a 50 V eight-device record on a "
                "solve that completes without a solver-only aid (the base still "
                "stalls at 296.929 us), (b) bench verification of "
                "UCC24624 turn-off in the same ~0.1 ms dead state, because the model "
                "lacks standby and the gate is reset only by drain reverse bias, and "
                "(c) a device SOA/thermal check for the 1.4 A latch and the 285 A "
                "release-window peak -- the model has neither. Files: "
                "design/v3/power_priority/sr_fault_probe_48v_120a.json, "
                "sr_fault_probe_50v_120a_cshunt.json, "
                "sr_fault_probe_48v_120a_cshunt.json and "
                "hotfault_48v_120a.json."),
            "file": "design/v3/power_priority/hotfault_48v_120a.json",
        },
        {
            "id": "F01",
            "priority": "P0",
            # PR #21 corrected the soft-start question: the fault must be injected
            # after V(ss) reaches the UCC25600 RT-only level (3.982 V), not during
            # the 0.5 mV/us ramp.  The hot-start decks do that (V(ss)=5.04/5.05 V),
            # so that half is answered; what remains is the prefix and hardware.
            # PR #22 adds a separate gate: the log pre-check is necessary but not
            # sufficient, and F01 stays blocked until an engineering waveform
            # review is signed and digest-matched to the current evidence.
            "blocker": "fully settled independent 48/50V hot faults lack completed log and waveform engineering review",
            "blocked": not independent_hotfault["all_independent_hotfault_cases_accepted"],
            "next_evidence": "bench-verify OC delay and SR/Lr peaks on a physical sample; "
                             "confirm real Lr saturation at the 101A fault peak.  The PR #21 "
                             "soft-start question is closed: the fault is now injected after "
                             f"V(ss) reaches {SS_RT_ONLY_THRESHOLD_V:.3f} V "
                             f"({hot48['pre_fault']['ss']['mean']:.3f} V at 48 V, "
                             f"{hot50['pre_fault']['ss']['mean']:.3f} V at 50 V), not during the "
                             "0.5 mV/us ramp.  The 50V "
                             "296.928us stall is numerical (smooth 3 V/us dead state, LTE-driven) -- "
                             "standby cannot close it because tSTBY_DET is 7.5 ms -- and the prefix "
                             "can support a bounded pre-trip peak discussion but is NOT accepted as full-duration protection validation.  PR #20's "
                             "documented SOLVER_DIAGNOSTIC is now run: same circuit, trtol 7->1 and "
                             "abstol 1e-12->1e-13 over 0..220us moves the I(Lr) peak by "
                             f"{diag_r['relative']['ipri_peak_a'] * 100:+.2f} % "
                             f"({diag_r['delta']['ipri_peak_a']:+.3f} A), the SR forward peak by "
                             f"{diag_r['relative']['sr_forward_peak_a'] * 100:+.3f} % and the trip by "
                             f"{diag_r['delta']['trip_s'] * 1e9:+.0f} ns, so the prefix peaks are not a "
                             "single-solver artifact.  "
                             f"The 48 V control (base run passed the strict log pre-check) moves the "
                             f"same peaks by "
                             f"{diag48_r['relative']['ipri_peak_a'] * 100:+.3f} % and "
                             f"{diag48_r['relative']['sr_forward_peak_a'] * 100:+.3f} %: both cases move "
                             "down under tightening, so the direction is conservative, but the magnitude "
                             "is sub-percent, not 0.1 %.  "
                             "The stall now has a solver-aid answer: the cshunt=1 fF child "
                             f"({len(conv50['circuit_differences'])} circuit differences) reaches "
                             "the 320 us stop and moves the same-window peaks by "
                             f"{conv_r['relative']['ipri_peak_a'] * 100:+.3f} % (I(Lr)) / "
                             f"{conv_r['relative']['sr_forward_peak_a'] * 100:+.3f} % (SR forward) "
                             f"with trip {conv_r['delta']['trip_s'] * 1e9:+.0f} ns; the base "
                             "itself still stalls, so no number here is hardware evidence.  "
                             "Closing F01 now "
                             "also requires an independent engineering waveform "
                             "review: hotfault_engineering_gate accepts a case only "
                             "when hotfault_<case>_engineering_review.json is signed "
                             "and digest-matched to the current deck, log and "
                             "waveform data, not when the log pre-check passes",
            "file": "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.cir",
        },
        {
            "id": "F02",
            "priority": "P0",
            "blocker": (
                f"the 120A overload record still stops at "
                f"{cold_conv['results']['base_t_last_us'] / 1e3:.4f} ms; the 1 fF cshunt "
                f"child stalls even earlier at {cold_conv['results']['variant_t_last_us'] / 1e3:.4f} ms"),
            "blocked": bool(fault["solver_prefix_only"]),
            "next_evidence": (
                "the cshunt aid is ruled out for this deck: it stalls "
                f"{abs(cold_conv['results']['base_t_last_us'] - cold_conv['results']['variant_t_last_us']) / 1e3:.2f} ms "
                "earlier while moving the pre-stall peaks by "
                f"{abs(cold_conv['results']['relative']['ipri_peak_a']) * 100:.3f} % (I(Lr)) and "
                f"{abs(cold_conv['results']['relative']['sr_forward_peak_a']) * 100:.3f} % (SR forward) "
                f"over the common slice; trip moves "
                f"{cold_conv['results']['delta']['trip_s'] * 1e9:.2f} ns.  Completion needs a "
                "different numerical strategy or an independently logged run; the published "
                "peaks stay prefix-bounded"),
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
            "next_evidence": (
                "ELE-09 ruled out a short-window artifact (22 periods 0.4986 W vs "
                "133 aligned 0.4921 W, sem 0.050 W) and the deck is now exhausted: "
                "no un-inventoried dissipative element can hold 0.49 W (Cin ESR "
                "0.61 mW measured, Cbt carries no charge).  Remaining candidates are "
                "the port reading (~2 mV of mean Vout) and the behavioral-SR "
                "channel/diode split; measured across the four 100 A steps the SR "
                f"body-diode term moves {step_r['sr_loss_per_volt_w']:.0f} W/V against the "
                f"port's {step_r['port_w_per_volt_w']:.0f} W/V, so 1 mV of Vout is worth "
                f"{step_r['sr_loss_per_volt_w'] * 1e-3:.2f} W -- the 0.49 W gap is 2.1 mV, "
                "the same order.  The fixed-current legs give "
                f"{csink_r['sr_loss_per_volt_w']:.0f} W/V as well, so the coupling is to Vout "
                "and not to the load current.  Do not relax 0.2 W"),
            "file": "design/v3/power_priority/energy_ledger_50v_120a_aligned.json",
        },
        {
            "id": "E02",
            "priority": "P0",
            "blocker": "50V 120A full energy closure not approved",
            "blocked": ledger50["balance"]["closure_status"] != "CLOSED" or abs(closure) > target,
            "next_evidence": (
                "the aligned 133-period window confirms the 0.698 W closure is stable "
                "(sem 0.050 W); ELE-09's inventory audit leaves only port and numerical "
                "candidates, and re-integrating the same samples is falsified (0.80 % within "
                "a raw against 86 % across steps).  More step reduction is falsified as well: "
                "with the load replaced by a constant-current sink the 0.5 ns leg still "
                f"settles {csink_r['endpoint_pair']['vout_delta_mv']:.1f} mV above 5 ns and keeps "
                f"{100 * csink_r['endpoint_spread_ratio_vs_resistive']['diode_loss_rel']:.1f} % of "
                "the resistive 5->0.5 ns endpoint difference, so the four runs sit at different "
                "operating points and the model's own V(out) moves with the step.  The sink is "
                "faithful (its 5 ns leg matches the resistive one to 0.3 %) but pins the "
                "current, not V(out) -- its own window drift is "
                f"{csink_r['vout_drift_worst_mv']:.1f} mV.  Only a closed V(out) loop can pin "
                "the operating point, and that is a different deck; do not relax 0.2 W"),
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
        "next_priority": ["F03", "F01", "F02", "M01", "C01", "E01", "E02"],
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
