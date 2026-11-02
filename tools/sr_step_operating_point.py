"""Why the SR body-diode term moves with the timestep: operating point, not quadrature.

``sr_loss_audit`` reports that the SR body-diode forward term swings ~2.3 W
across the 5/2/1/0.5 ns aligned runs and that no plateau appears.  The
suggested next experiment was an edge-aligned fixed-step integration.  This
tool tests the two questions that decide whether that would help:

1. Can a different quadrature rule reproduce the swing from the *same* raw?
   Trapezoid, midpoint and a 10x decimation are compared per period on each
   file.  If they agree to a fraction of a percent while the files differ by
   tens of percent, the difference is in the waveform, and no post-processing
   can remove it.
2. Are the four runs even at the same operating point?  The 100 A deck has a
   resistive load and no output-voltage loop, so the output voltage settles
   wherever the model's own loss balance puts it.  A spread in mean ``V(out)``
   means the four files are four slightly different loads, and a loss term
   that is sensitive to load cannot be compared across them at 0.6 W.

The measure is channel A of pair 1: gate on-time, body-diode forward charge,
peak diode current and diode forward loss, per gate period over the whole
phase-aligned window.

Raws are local only; this tool is a manual diagnostic like ``sr_loss_audit``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import energy_ledger_100a as el
from ascii_raw_window import read_window

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "design/v3/stage_f/sr_step_operating_point.json"
DECKS = {
    "5": "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned.raw",
    "2": "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned2n.raw",
    "1": "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned1n.raw",
    "0.5": "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned0p5n.raw",
}
NAMES = ["V(out)", "V(ga1)", "V(xsa1:di)", "V(xsa1:si)", "I(xsa1:Dbd)"]
T_END_S = 671e-6
# The 100 A mother deck's load; the port sensitivity is dP/dV = 2V/RL.
RLOAD_OHM = 18.9e-3


def periods(t: np.ndarray, gate: np.ndarray) -> list[tuple[int, int]]:
    """Complete gate periods bounded by real rising edges (200 ns debounce)."""
    edges = el.gate_edges(t, gate)
    return [(edges[k], edges[k + 1]) for k in range(len(edges) - 1)]


def _trap(y: np.ndarray, x: np.ndarray) -> float:
    return float(np.trapezoid(y, x))


def _mid(y: np.ndarray, x: np.ndarray) -> float:
    return float(np.trapezoid((y[:-1] + y[1:]) / 2.0, x[:-1]))


def _decimate10(y: np.ndarray, x: np.ndarray) -> float:
    return _trap(y[::10], x[::10])


def period_metrics(t: np.ndarray, d: dict[str, np.ndarray],
                   span: tuple[int, int]) -> dict[str, float]:
    i0, i1 = span
    tt = t[i0:i1]
    vds = d["V(xsa1:di)"][i0:i1] - d["V(xsa1:si)"][i0:i1]
    idbd = np.maximum(d["I(xsa1:Dbd)"][i0:i1], 0.0)
    p_diode = -vds * d["I(xsa1:Dbd)"][i0:i1]
    on = (d["V(ga1)"][i0:i1] > 5.0).astype(float)
    return {
        "period_s": float(tt[-1] - tt[0]),
        "on_time_ns": _trap(on, tt) * 1e9,
        "charge_uc": _trap(idbd, tt) * 1e6,
        "peak_a": float(idbd.max()),
        "diode_loss_w": _trap(p_diode, tt) / (tt[-1] - tt[0]),
        "vout_mean_v": _trap(d["V(out)"][i0:i1], tt) / (tt[-1] - tt[0]),
    }


def quadrature_spread(t: np.ndarray, d: dict[str, np.ndarray],
                      spans: list[tuple[int, int]]) -> dict[str, float]:
    """Worst relative difference between three quadrature rules on one raw."""
    worst = 0.0
    worst_loss = 0.0
    for i0, i1 in spans:
        tt = t[i0:i1]
        idbd = np.maximum(d["I(xsa1:Dbd)"][i0:i1], 0.0)
        p = -((d["V(xsa1:di)"][i0:i1] - d["V(xsa1:si)"][i0:i1])
              * d["I(xsa1:Dbd)"][i0:i1])
        for series, key in ((idbd, "charge"), (p, "loss")):
            base = _trap(series, tt)
            if abs(base) < 1e-12:
                continue
            rel = max(abs(_mid(series, tt) / base - 1.0),
                      abs(_decimate10(series, tt) / base - 1.0))
            if key == "charge":
                worst = max(worst, rel)
            else:
                worst_loss = max(worst_loss, rel)
    return {"max_rel_charge": worst, "max_rel_loss": worst_loss}


def measure(raw: Path) -> tuple[dict[str, object], dict[str, np.ndarray], np.ndarray]:
    t, d = read_window(raw, NAMES, 0.0, T_END_S)
    spans = periods(t, d["V(ga1)"])
    rows = [period_metrics(t, d, s) for s in spans]
    values = {key: [row[key] for row in rows] for key in rows[0]}
    summary = {
        "periods": len(rows),
        "vout_mean_v": float(np.mean(values["vout_mean_v"])),
        "on_time_ns": float(np.mean(values["on_time_ns"])),
        "charge_uc": float(np.mean(values["charge_uc"])),
        "charge_uc_sd": float(np.std(values["charge_uc"])),
        "peak_a": float(np.mean(values["peak_a"])),
        "diode_loss_w": float(np.mean(values["diode_loss_w"])),
    }
    return summary, d, t


def rank(values: list[float]) -> list[int]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0] * len(values)
    for slot, i in enumerate(order):
        out[i] = slot
    return out


def build() -> dict[str, object]:
    cases: dict[str, object] = {}
    quad: dict[str, object] = {}
    for step, rel in DECKS.items():
        raw = ROOT / rel
        summary, d, t = measure(raw)
        spans = periods(t, d["V(ga1)"])
        quad[step] = quadrature_spread(t, d, spans[: min(len(spans), 20)])
        cases[step] = summary

    steps = list(DECKS)
    vout = [cases[s]["vout_mean_v"] for s in steps]
    on = [cases[s]["on_time_ns"] for s in steps]
    charge = [cases[s]["charge_uc"] for s in steps]
    loss = [cases[s]["diode_loss_w"] for s in steps]
    # The charge integrand (a current that ramps smoothly) is the honest
    # quadrature probe.  The loss integrand multiplies it by vds, which swings
    # ~1 V inside one commutation, so a 10x decimation is a crude proxy there
    # and is reported separately rather than used as the gate.
    within = max(quad[s]["max_rel_charge"] for s in steps)
    within_loss = max(quad[s]["max_rel_loss"] for s in steps)
    cross = max(loss) / min(loss) - 1.0
    charge_cross = max(charge) / min(charge) - 1.0
    # Apparent sensitivity: does the 19 mV of Vout spread actually account for
    # the 2.3 W of SR loss spread?  Four points only fix a slope, not a cause,
    # so this is reported as a magnitude comparison against the port's own
    # 2V/RL, not as a fitted law.
    sr_spread_x8 = (max(loss) - min(loss)) * 8.0
    per_volt = sr_spread_x8 / ((max(vout) - min(vout)) if max(vout) != min(vout) else 1.0)
    port_per_volt = 2.0 * float(np.mean(vout)) / RLOAD_OHM
    results = {
        "steps_ns": steps,
        "vout_mean_v": vout,
        "on_time_ns": on,
        "charge_uc": charge,
        "diode_loss_w": loss,
        "vout_spread_mv": (max(vout) - min(vout)) * 1e3,
        "on_time_spread_ns": max(on) - min(on),
        "charge_spread_uc": max(charge) - min(charge),
        "charge_cross_raw_rel": charge_cross,
        "diode_loss_spread_w": max(loss) - min(loss),
        "diode_loss_spread_x8_w": sr_spread_x8,
        "sr_loss_per_volt_w": per_volt,
        "port_w_per_volt_w": port_per_volt,
        "sr_loss_sensitivity_vs_port": per_volt / port_per_volt,
        "quadrature_within_raw_max_rel": within,
        "quadrature_loss_within_raw_max_rel": within_loss,
        "cross_raw_loss_rel": cross,
        "loss_vs_vout_inverse_monotone":
            rank(loss) == [len(vout) - 1 - r for r in rank(vout)],
        "quadrature_by_step": quad,
    }
    checks = {
        "all_four_steps_measured": all(cases[s]["periods"] >= 130 for s in steps),
        "periods_match_across_steps": len({cases[s]["periods"] for s in steps}) == 1,
        "quadrature_is_not_the_explanation": within < 0.02,
        "cross_step_spread_exceeds_quadrature": charge_cross > 10 * within,
    }
    return {
        "tool": "sr_step_operating_point.py",
        "scope": "pair 1 channel A, whole phase-aligned window of each 100 A run",
        "results": results,
        "checks": checks,
    }


def write(path: Path = OUT, value: dict[str, object] | None = None) -> dict[str, object]:
    value = build() if value is None else value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=OUT)
    args = ap.parse_args()
    value = write(args.json)
    r = value["results"]
    print(f"steps {r['steps_ns']}  Vout {r['vout_mean_v']}")
    print(f"diode loss {r['diode_loss_w']} W  spread {r['diode_loss_spread_w']:.3f} W")
    print(f"charge quadrature within raw {100 * r['quadrature_within_raw_max_rel']:.2f} % "
          f"vs cross-raw {100 * r['charge_cross_raw_rel']:.1f} %")
    print(f"loss quadrature (decimated probe) {100 * r['quadrature_loss_within_raw_max_rel']:.2f} %")
    print("checks:", value["checks"])
    return 0 if all(value["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
