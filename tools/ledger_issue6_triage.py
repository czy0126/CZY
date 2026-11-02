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
        "next_discriminating_experiments": [
            {"id":"E6-1","status":"open","method":"Inspect SR diode forward power signs at each switching edge; classify conduction and reverse recovery separately","record":"per-device VDS, Ibody and conduction phase, all 5/2/1ns"},
            {"id":"E6-2","status":"open","method":"Report Rg, Rgs and Cpin dissipated/delta-energy on same 133-cycle boundary and prevent double counting Bdrive output","record":"waveform-based gate-source energy and local resistor I2R per SR"},
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
