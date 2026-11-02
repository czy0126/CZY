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
    gate = float(r["aligned_gate_drive_sinks_w"])
    if len(after) != 3 or not all(abs((a - b) - gate) < 0.003
                                   for a, b in zip(before, after)):
        raise ValueError("aligned accounting correction no longer matches gate sinks")
    return {
        "status": "RESIDUAL_LOCUS_UNRESOLVED_NOT_CLOSED",
        "target_w_unchanged": BUDGET_W,
        "basis": SOURCE.relative_to(ROOT).as_posix(),
        "after_gate_sinks_aligned_5_2_1ns_w": after,
        "original_aligned_5_2_1ns_w": before,
        "identified_gate_sink_w_5ns": gate,
        "residual_at_finest_step_w": after[-1],
        "improvement_from_external_boundary_identification": True,
        "canonical_ledger_closure_approved": False,
        "numerical_step_convergence_approved": False,
        "efficiency_and_continuous_power_approved": False,
        "important_uncertainty": {
            "body_diode_forward_loss_across_step_w": r["body_diode_forward_step_spread_w"],
            "channel_loss_across_step_w": r["channel_step_spread_w"],
            "short_window_corrected_residual_spread_w": r["sixteen_period_closure_step_spread_after_w"],
            "aligned_corrected_residual_spread_w": r["aligned_closure_step_spread_after_w"],
        },
        "next_discriminating_experiments": [
            {"id":"E6-1","method":"Inspect SR diode forward power signs at each switching edge; classify conduction and reverse recovery separately","record":"per-device VDS, Ibody and conduction phase, all 5/2/1ns"},
            {"id":"E6-2","method":"Report Rg, Rgs and Cpin dissipated/delta-energy on same 133-cycle boundary and prevent double counting Bdrive output","record":"waveform-based gate-source energy and local resistor I2R per SR"},
            {"id":"E6-3","method":"Use the exact same 133-cycle phase-aligned window for each timestep, then run one additional <=0.5ns variant if computationally feasible","record":"port, SR channel/diode, CT and magnetic delta-energy terms, each version-tagged"},
            {"id":"E6-4","method":"Test all symmetry assumptions (SR pair1 x4, secondary copper x4) by direct probes on all eight SR devices","record":"per-group current and I2R; any unavailable probes explicitly UNKNOWN"},
        ],
        "guard": "A post-hoc residual 0.09W below 0.2W does not close the canonical 100A ledger; the physical missing term and convergence still require identification.",
    }


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
    print(data["status"], data["residual_at_finest_step_w"])


if __name__ == "__main__":
    main()
