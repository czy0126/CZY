"""Device and protection-pin stress over one steady-state candidate window.

`extract_op_point.py` answers "what is the operating point"; this tool answers
"what does each device pin actually see" on the same traces.  The numbers are
simulation-model stresses, not a safe-operating-area or thermal sign-off.

The SR drain node (`a*`/`b*`) is saved against ground.  In these candidates the
SR source is the shared `sgnd` node (`Xsa1 da1 ga1 sgnd SR_DEVICE`), so the
saved node voltage *is* the drain-to-source voltage; the record says so instead
of subtracting `V(out)`, which would be the reference for a high-side SR.

Usage:
    python tools/steady_stress.py \
        --raw sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110_cin.raw \
        --from-us 7.629195812563637 --to-us 117.2912676221502 --vin 50 --rl 0.0178 \
        --json design/v3/power_priority/stress_50v_110a.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ascii_raw_window import read_header, read_window

OC_TRIP_V = 1.0
OC_LATCH_V = 2.0
NODES = ("a1", "b1", "a4", "b4")
GATES = ("ga1", "gb1", "ga4", "gb4")
BRANCHES = (1, 4)


def _mean(t: np.ndarray, x: np.ndarray) -> float:
    return float(np.trapezoid(x, t) / (t[-1] - t[0]))


def _rms(t: np.ndarray, x: np.ndarray) -> float:
    return float(np.sqrt(max(_mean(t, x * x), 0.0)))


def stress_block(t: np.ndarray, data: dict[str, np.ndarray], rl: float) -> dict[str, object]:
    vout = data["V(out)"]
    ipri = data["I(Lr)"]
    oc = data["V(oc)"]

    drain_max = max(float(data[f"V({n})"].max()) for n in NODES)
    drain_min = min(float(data[f"V({n})"].min()) for n in NODES)
    gate_max = max(float(data[f"V({g})"].max()) for g in GATES)
    gate_min = min(float(data[f"V({g})"].min()) for g in GATES)

    fwd = max(float((-data[f"I(VSa{n})"]).max()) for n in BRANCHES)
    rev = max(float(data[f"I(VSa{n})"].max()) for n in BRANCHES)
    oc_max = float(oc.max())

    # Pairs 2/3 are not instrumented; the ×2 is the model-symmetry assumption.
    secondary = 2.0 * -(data["I(VSa1)"] + data["I(VSb1)"] + data["I(VSa4)"] + data["I(VSb4)"])
    idc = _mean(t, secondary)
    icap = secondary - idc
    iout_v = _mean(t, vout) / rl

    out: dict[str, object] = {
        "vout_avg_v": _mean(t, vout),
        "vout_pp_mv": float(np.ptp(vout) * 1e3),
        "pout_w": _mean(t, vout * vout / rl),
        "iout_from_v_a": iout_v,
        "ipri_rms_a": _rms(t, ipri),
        "ipri_pk_a": float(np.max(np.abs(ipri))),
        "oc": {
            "mean_v": _mean(t, oc),
            "max_v": oc_max,
            "trip_level_v": OC_TRIP_V,
            "latch_level_v": OC_LATCH_V,
            "margin_to_trip": oc_max / OC_TRIP_V,
        },
        "sr_gate": {"min_v": gate_min, "max_v": gate_max},
        "sr_vds": {
            "max_v": drain_max,
            "min_v": drain_min,
            "reference": "drain against sgnd; the SR source in these decks is sgnd",
        },
        "sr_current": {"forward_peak_a": fwd, "reverse_peak_a": rev},
        "cout_ripple": {
            "load_mean_a": idc,
            "ripple_rms_a": float(np.sqrt(max(_mean(t, icap * icap), 0.0))),
            "ripple_pk_a": float(np.abs(icap).max()),
            "mean_check_pct": 100.0 * (idc - iout_v) / iout_v,
            "reconstruction": "four SR currents, pairs 2/3 assumed symmetric (×2)",
        },
        "note": "sr_vds is the saved drain-node voltage because every SR source "
                "is the shared sgnd node.  Only pairs 1 and 4 are instrumented, "
                "so current peaks and the Cout ripple carry the symmetry "
                "assumption, not a sharing result.",
    }
    if "I(Rin)" in data and "I(Cin)" in data:
        bridge = data["I(Rin)"] - data["I(Cin)"]
        cin = data["I(Cin)"]
        bridge_mean = _mean(t, bridge)
        cin_mean = _mean(t, cin)
        out["input"] = {
            "source_mean_a": _mean(t, data["I(Rin)"]),
            "bridge_mean_a": bridge_mean,
            "bridge_ac_rms_a": float(np.sqrt(max(
                _mean(t, bridge * bridge) - bridge_mean ** 2, 0.0))),
            "cin_mean_a": cin_mean,
            "cin_ac_rms_a": float(np.sqrt(max(_mean(t, cin * cin) - cin_mean ** 2, 0.0))),
            "note": "KCL bridge current = I(Rin) - I(Cin); the AC RMS has the "
                    "window mean removed.  The 20 uF capacitor sees only "
                    "cin_ac_rms, and that depends on the modelled source impedance.",
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--from-us", type=float, required=True)
    ap.add_argument("--to-us", type=float, required=True)
    ap.add_argument("--vin", type=float, required=True)
    ap.add_argument("--rl", type=float, required=True)
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()

    names = ["V(out)", "V(oc)", "I(Lr)"]
    names += [f"V({n})" for n in NODES]
    names += [f"V({g})" for g in GATES]
    names += [f"I(VSa{n})" for n in BRANCHES]
    names += [f"I(VSb{n})" for n in BRANCHES]
    with args.raw.open("rb") as handle:
        available, _ = read_header(handle)
    if "I(Rin)" in available and "I(Cin)" in available:
        names += ["I(Rin)", "I(Cin)"]
    t, data = read_window(args.raw, names, args.from_us * 1e-6, args.to_us * 1e-6)
    if t.size < 3:
        raise SystemExit("window contains too few points")

    result: dict[str, object] = {
        "raw": str(args.raw),
        "window_us": [args.from_us, args.to_us],
        "vin_v": args.vin,
        "rl_ohm": args.rl,
        "evidence_level": "SIMULATED_ONLY / NOT_RATED",
    }
    result.update(stress_block(t, data, args.rl))
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
