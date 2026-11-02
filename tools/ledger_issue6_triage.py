"""Read existing issue #6 audit without falsely declaring ledger closure."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "design/v3/stage_f/sr_loss_audit.json"
OUT = ROOT / "design/v3/stage_f/issue6_next_experiment.json"
BUDGET_W = 0.2


def build() -> dict:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    r = data["results"]
    before = [float(v) for v in r["aligned_closure_before_period_averaged_w"]]
    after = [float(v) for v in r["aligned_closure_after_period_averaged_w"]]
    steps = [str(s) for s in r["aligned_steps_ns"]]
    gate = float(r["aligned_gate_drive_sinks_w"])
    # Every aligned step must be carried.  Pinning a fixed count is what let the
    # report describe a 5/2/1 series after the 0.5 ns leg had been appended.
    if len(after) < 3 or not (len(after) == len(before) == len(steps)):
        raise ValueError("aligned series is inconsistent across before/after/steps")
    if not all(abs((a - b) - gate) < 0.003 for a, b in zip(before, after)):
        raise ValueError("aligned accounting correction no longer matches gate sinks")
    legs = [after[i + 1] - after[i] for i in range(len(after) - 1)]
    # A plateau is a last leg that is small against the first one; a series that
    # keeps moving at the finest step is an oscillation being sampled, not a
    # limit being approached.
    plateau = abs(legs[0]) > 0 and abs(legs[-1]) < 0.25 * abs(legs[0])
    # E6-4: four secondary groups are identical in the deck, only pairs 1 and 4
    # carry probes.  Carry the measured ratio and the I2R error it bounds.
    if (r.get("sr_group_symmetry_measured") != [1, 4]
            or r.get("sr_group_symmetry_unmeasured") != [2, 3]):
        raise ValueError("SR group symmetry inventory changed; update the triage record")
    ratios = {name: dict(value) for name, value in
              r["pair4_over_pair1_rms_current"].items()}
    split_error = {name: float(value) for name, value in
                   r["pair4_over_pair1_i2r_error_bound_pct"].items()}
    worst_name = max(split_error, key=split_error.get)
    worst_pct = split_error[worst_name]
    steps_by_case = {case["name"]: f"{float(case['max_step_s']) * 1e9:g}"
                     for case in data["cases"]}
    worst_step = steps_by_case[worst_name]
    deviating = [name for name, value in ratios.items()
                 if any(abs(v - 1.0) > 1e-6 for v in value.values() if v is not None)]
    if deviating:
        detail = (f"{worst_step} ns gives a/b = {ratios[worst_name]['a']:.4f}/"
                  f"{ratios[worst_name]['b']:.4f} (worst I2R error {worst_pct:.2f} %), "
                  "a numerical split of parallel branches, not a current error")
    else:
        detail = "all measured runs give 1.000000"
    # E6-1: the SR movement must name a component.  The diode current is split
    # by sign, so forward conduction and reverse recovery cannot hide inside a
    # single net term.  A non-negative reverse term would invalidate the split.
    aligned_cases = [case for case in data["cases"] if case["family"] == "aligned"]
    if len(aligned_cases) < 3:
        raise ValueError("aligned family is incomplete; E6-1 needs the step series")
    if not all(case["sr_dissipation"]["body_diode_reverse_w"] < 0.0
               for case in aligned_cases):
        raise ValueError("reverse recovery no longer returns energy; E6-1 split is invalid")
    channel_by_step = {steps_by_case[case["name"]]: case["sr_dissipation"]["channel_w"]
                       for case in aligned_cases}
    forward_by_step = {steps_by_case[case["name"]]:
                       case["sr_dissipation"]["body_diode_forward_w"]
                       for case in aligned_cases}
    reverse_by_step = {steps_by_case[case["name"]]:
                       case["sr_dissipation"]["body_diode_reverse_w"]
                       for case in aligned_cases}
    if set(channel_by_step) != set(steps):
        raise ValueError("aligned case names and step labels disagree")
    # E6-2: the correction is the two resistors fed by the ideal Bdrive source.
    # KCL at the gate pin is the measurement that licenses using the sum instead
    # of re-adding the whole driver output.
    sinks_by_step = {steps_by_case[case["name"]]: float(case["closure"]["gate_drive_sinks_w"])
                     for case in aligned_cases}
    for case in aligned_cases:
        if abs(float(case["closure"]["gate_drive_sinks_w"])
               - float(case["gate_drive"]["sinks_x8_w"])) > 1e-9:
            raise ValueError("gate-sink correction is not Rg + Rgs + Cpin")
    sink_spread = max(sinks_by_step.values()) - min(sinks_by_step.values())
    kcl_max = max(abs(case["dimensions"]["gate_pin_kcl_w"]) for case in aligned_cases)
    corrected_label = " / ".join(f"{value:+.3f}" for value in after)
    return {
        "status": "RESIDUAL_LOCUS_UNRESOLVED_NOT_CLOSED",
        "target_w_unchanged": BUDGET_W,
        "basis": SOURCE.relative_to(ROOT).as_posix(),
        "aligned_steps_ns": steps,
        "after_gate_sinks_aligned_w": after,
        "original_aligned_w": before,
        "identified_gate_sink_w_5ns": gate,
        "residual_at_finest_step_w": after[-1],
        "legs_w": legs,
        "first_leg_w": legs[0],
        "last_leg_w": legs[-1],
        "plateau_reached": plateau,
        "improvement_from_external_boundary_identification": True,
        "canonical_ledger_closure_approved": False,
        "numerical_step_convergence_approved": False,
        "efficiency_and_continuous_power_approved": False,
        "important_uncertainty": {
            "body_diode_forward_loss_across_step_w": r["body_diode_forward_step_spread_w"],
            "channel_loss_across_step_w": r["channel_step_spread_w"],
            "short_window_corrected_residual_spread_w": r["sixteen_period_closure_step_spread_after_w"],
            "aligned_corrected_residual_spread_w": r["aligned_closure_step_spread_after_w"],
            "worst_pair_split_i2r_error_pct": worst_pct,
        },
        "group_symmetry": {
            "measured_groups": [1, 4],
            "unmeasured_groups": [2, 3],
            "pair4_over_pair1_rms": ratios,
            "worst_i2r_error_pct": {"case": worst_name, "step_ns": worst_step,
                                    "percent": worst_pct},
            "circulating_difference_rms_a": r["pair_split_circulating_rms_a"],
        },
        "diode_split": {
            "measured_devices": "pair 1 halves a/b, scaled x4; pairs 2 and 3 UNKNOWN",
            "channel_w": channel_by_step,
            "body_diode_forward_w": forward_by_step,
            "body_diode_reverse_w": reverse_by_step,
            "channel_step_spread_w": r["channel_step_spread_w"],
            "body_diode_forward_step_spread_w": r["body_diode_forward_step_spread_w"],
            "body_diode_forward_share_of_sr_move": r["body_diode_forward_share_of_sr_move"],
        },
        "gate_sink_correction": {
            "sinks_w_5ns": sinks_by_step[steps[0]],
            "per_step_w": sinks_by_step,
            "spread_across_steps_w": sink_spread,
            "kcl_residual_max_w": kcl_max,
        },
        "next_discriminating_experiments": [
            {"id":"E6-1","status":"done",
             "result": (f"the channel term moves only "
                        f"{r['channel_step_spread_w']:.3f} W across the four steps while "
                        f"the body-diode forward term moves "
                        f"{r['body_diode_forward_step_spread_w']:.3f} W, "
                        f"{100.0 * r['body_diode_forward_share_of_sr_move']:.1f} % of the "
                        "whole SR movement; reverse recovery is negative on every run "
                        "(it returns energy); pairs 2 and 3 have no probes and stay UNKNOWN"),
             "method": ("Sign-classify the pair-1 body-diode current over the same "
                        "133-cycle aligned window on every timestep; separate forward "
                        "conduction from reverse recovery and compare the channel term"),
             "record": ("per-half VDS and body-diode current (pair 1 a/b), forward/reverse "
                        "charge and power, all four steps; pairs 2/3 UNKNOWN")},
            {"id":"E6-2","status":"done",
             "result": (f"the correction is the measured gate-pin sinks Rg + Rgs = "
                        f"{sinks_by_step[steps[0]]:.4f} W (spread {sink_spread:.4f} W "
                        f"across the four steps), gate-pin KCL residual <= {kcl_max:.1e} W "
                        f"scaled to eight; the period-averaged residual becomes "
                        f"{corrected_label} W, so the ledger stays NOT_CLOSED"),
             "method": ("Rebuild the driver boundary from waveforms: KCL at the gate pin "
                        "(driver output = gate pin + Rgs + Cpin), then count only the Rg "
                        "and Rgs sinks as the correction so the Bdrive output is not "
                        "double counted"),
             "record": ("waveform-based gate-pin KCL, per-half Rg/Rgs I2R and Cpin edge "
                        "energy, all four steps")},
            {"id":"E6-3","status":"done","result":"0.5 ns leg appended to the same 133-cycle aligned window; the series still moves at the finest step, so there is no plateau","method":"Use the exact same 133-cycle phase-aligned window for each timestep, then run one additional <=0.5ns variant if computationally feasible","record":"port, SR channel/diode, CT and magnetic delta-energy terms, each version-tagged"},
            {"id":"E6-4","status":"done","result":f"pairs 1 and 4 measured on every aligned run; {detail}; pairs 2 and 3 have no probes and stay UNKNOWN","method":"Test all symmetry assumptions (SR pair1 x4, secondary copper x4) by direct probes on all eight SR devices","record":"per-group current and I2R; any unavailable probes explicitly UNKNOWN"},
        ],
        "guard": "A post-hoc residual below 0.2 W does not close the canonical 100 A ledger, and the 0.5 ns leg shows the 5/2/1 ns series was not a plateau: no step count may be quoted as convergence while the finest leg still moves the closure by more than the budget.",
    }


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
    print(data["status"], data["residual_at_finest_step_w"])


if __name__ == "__main__":
    main()
