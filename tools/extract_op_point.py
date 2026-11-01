"""Extract the measured operating point of a tank deck from its ASCII raw.

This is the reproducible bridge between a simulation and the magnetic loss
table.  It deliberately reuses the project's measurement invariants:

    Pout = average(Vout^2 / RL)      not Vout_avg^2 / RL
    RMS  = sqrt(average(i^2))        with trapezoidal time weighting
    window = the last N complete gate periods, not a fixed byte range

Only the traces the deck actually saved are required; pair 1 is mandatory and
pair 4 is used as a symmetry check when present.

Usage:
    python tools/extract_op_point.py sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw \
        --rl 0.0189 --periods 22 --json design/v3/magnetics/operating_point_100a.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ascii_raw_window import read_window
from tank_metrics import GATE_ON, edges


def _average(t: np.ndarray, x: np.ndarray) -> float:
    return float(np.trapezoid(x, t) / (t[-1] - t[0]))


def _rms(t: np.ndarray, x: np.ndarray) -> float:
    return float(np.sqrt(max(_average(t, x * x), 0.0)))


def operating_point(raw: str | Path, rl_ohm: float, periods: int = 22,
                    pairs: tuple[int, ...] = (1, 4)) -> dict[str, object]:
    """Return the measured point plus the exact window it was measured on."""
    names = ["V(out)", f"V(ga{pairs[0]})", "I(Lr)"]
    for n in pairs:
        names.extend([f"I(VSa{n})", f"I(VSb{n})"])
    t, data = read_window(raw, names, 0.0, None)

    rises = edges(t, data[f"V(ga{pairs[0]})"], GATE_ON)
    if rises.size < periods + 1:
        raise ValueError(f"only {rises.size - 1} complete periods, need {periods}")
    t0, t1 = float(rises[-(periods + 1)]), float(rises[-1])
    mask = (t >= t0) & (t <= t1)
    tw = t[mask]

    vout = data["V(out)"][mask]
    ipri = data["I(Lr)"][mask]
    out: dict[str, object] = {
        "raw": str(raw),
        "rl_ohm": rl_ohm,
        "window_us": [t0 * 1e6, t1 * 1e6],
        "periods": periods,
        "freq_khz": periods / (t1 - t0) / 1e3,
        "vout_avg_v": _average(tw, vout),
        "vout_rms_v": _rms(tw, vout),
        "vout_pp_mv": float(np.ptp(vout) * 1e3),
        "pout_w": _average(tw, vout * vout / rl_ohm),
        "iout_from_v_a": _average(tw, vout) / rl_ohm,
        "ipri_rms_a": _rms(tw, ipri),
        "ipri_pk_a": float(np.max(np.abs(ipri))),
    }

    iouts: list[float] = []
    for n in pairs:
        ia = data[f"I(VSa{n})"][mask]
        ib = data[f"I(VSb{n})"][mask]
        iout = _average(tw, -(ia + ib))
        irms_pair = _rms(tw, ia + ib)
        iouts.append(iout)
        out[f"pair{n}"] = {
            "iout_a": iout,
            "irms_pair_a": irms_pair,
            "irms_a_a": _rms(tw, ia),
            "irms_b_a": _rms(tw, ib),
            "ifwd_pk_a": float(np.max(-ia)),
            "irev_pk_a": float(np.max(ia)),
        }
    out["iout_sum_a"] = float(sum(iouts))
    out["iout_note"] = (
        "iout_sum_a covers the instrumented pairs only; use iout_from_v_a "
        "(average(Vout)/RL) as the total load current."
    )
    out["iout_spread_pct"] = (
        100.0 * (max(iouts) - min(iouts)) / abs(float(np.mean(iouts))) if iouts else float("nan")
    )
    # Both pairs are structurally identical in the model; this is a symmetry
    # check, not evidence of real current sharing.
    if len(iouts) > 1:
        out["pair_symmetry_note"] = "model symmetry only, not a hardware sharing result"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path)
    ap.add_argument("--rl", type=float, required=True, help="load resistance in ohm")
    ap.add_argument("--periods", type=int, default=22)
    ap.add_argument("--pairs", type=int, nargs="+", default=[1, 4])
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    result = operating_point(args.raw, args.rl, args.periods, tuple(args.pairs))
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json is None:
        print(text)
    else:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
