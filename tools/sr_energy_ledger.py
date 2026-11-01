"""Branch energy ledger for the SR device in the joint tank bench.

The port-only tool (tools/tank_metrics.py) can say how much energy enters the
two external terminals, and it can split that by gate state, but it cannot say
how much was dissipated in the channel vs the body diode vs stored in Coss.
The round-2 review (P1) rejected the inference "gate low => the reverse charge
went through the body diode => 0.78 V * Qrev is the loss": with Cds, Cgd, a TT
body diode and package inductance all in the model, port current is a mixture.

This tool closes that gap by reading the device internals that
sim/v2/sr_tank_dual_v33_internal.cir saves:

    channel          V(di,si) * I(Bch)
    body diode       V(si,di) * I(Dbd)
    Cds / Cgd / Cgs  V * I   (reactive: the integral IS the stored-energy change)
    Ld / Ls / Lg     V * I   (reactive: same)
    Rg               V(gn,gi) * I(Rg)   (gate resistor, dissipative)
    gate pin         V(ga1) * I(Lg)     (energy delivered to the device gate)
    gate supply      V(ga1) * I(Bdrive) (driver output, includes the 100 pF CPIN
                                         regularisation pad and Rgs)
    drain-source     V(a1) * I(VSa1)    (the port proxy tank_metrics reports)

Identity checked by the tool (device + its own package):
    e_port_ds + e_gate_pin = e_channel + e_bodydiode + e_rg
                             + dE(Cds) + dE(Cgd) + dE(Cgs)
                             + dE(Ld) + dE(Ls) + dE(Lg) + residual
A small residual validates the signs.  A non-steady window keeps a nonzero
reactive term: the port net input is then NOT heat, which is exactly the
round-2 correction.

Usage:
    python tools/sr_energy_ledger.py sim/v2/sr_tank_dual_v33_internal.raw
    python tools/sr_energy_ledger.py RAW --periods 8 --json out.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from tank_metrics import integrate, load, periods, window

# Device parameters copied from models/sr_device_v3.lib.  They are only used to
# label the stored-energy columns; the integrals themselves come from the raw.
LG = 2.5e-9
LD = 0.3e-9
LS = 0.8e-9


def find(data: dict[str, np.ndarray], prefix: str) -> str:
    """Case-insensitive trace lookup: LTspice capitalises device names."""
    lowered = prefix.lower()
    for name in data:
        if name.lower() == lowered:
            return name
    for name in data:
        if name.lower().startswith(lowered):
            return name
    raise KeyError(prefix)


def branch_energy(t: np.ndarray, v: np.ndarray, i: np.ndarray) -> float:
    """Integral of v*i over t, in microjoules."""
    return 1e6 * integrate(t, v, i)


def ledger_period(t: np.ndarray, data: dict[str, np.ndarray], pair: int, t0: float, t1: float) -> dict[str, float]:
    """Branch energies for one SR device over one complete period [t0, t1].

    Only pair 1 is instrumented: the decks save ``xsa1:*`` / ``xsr1:*`` internals
    and nothing for pairs 2..4.  Accepting another ``pair`` here used to be a
    silent trap -- the argument changed no trace name, so a caller asking for
    pair 3 would get pair 1's numbers under the wrong label.  Fail instead.
    """
    if pair != 1:
        raise ValueError(f"only pair 1 is instrumented; got pair={pair}")
    w = window(t, t0, t1)
    tw = t[w]
    d = data
    v_a, i_a = d["V(a1)"][w], d["I(VSa1)"][w]  # drain-source port
    v_g = d["V(ga1)"][w]
    i_gate_pin = d[find(d, "I(xsa1:Lg)")][w]
    i_gate_drv = d[find(d, "I(xsr1:x1:Bdrive)")][w]
    vdi, vsi = d[find(d, "V(xsa1:di)")][w], d[find(d, "V(xsa1:si)")][w]
    vgi, vgn = d[find(d, "V(xsa1:gi)")][w], d[find(d, "V(xsa1:gn)")][w]
    i_ch = d[find(d, "I(xsa1:Bch)")][w]
    i_diode = d[find(d, "I(xsa1:Dbd)")][w]
    i_cds, i_cgd, i_cgs = (d[find(d, f"I(xsa1:{n})")][w] for n in ("Cds", "Cgd", "Cgs"))
    i_ld, i_ls, i_lg = (d[find(d, f"I(xsa1:{n})")][w] for n in ("Ld", "Ls", "Lg"))
    i_rg = d[find(d, "I(xsa1:Rg)")][w]
    e_channel = branch_energy(tw, vdi - vsi, i_ch)
    e_diode = branch_energy(tw, vsi - vdi, i_diode)
    out = {
        "e_port_ds_uj": branch_energy(tw, v_a, i_a),
        "e_gate_pin_uj": branch_energy(tw, v_g, i_gate_pin),
        # Bdrive G S I=...: positive current flows G -> S, i.e. OUT of the driver,
        # so the energy delivered to the gate node is -V(G,S) * I(Bdrive).
        # NAME: this is the DRIVER OUTPUT energy (what the SR_TIMING model's
        # push-pull stage delivers into G-S), not the 12 V bias supply input.
        # It already contains the Rg loss and the gate-pin charge, so adding
        # e_rg to it would double count.  The bias input is measured at V(aux).
        "e_gate_driver_output_uj": -branch_energy(tw, v_g, i_gate_drv),
        "e_channel_uj": e_channel,
        "e_bodydiode_uj": e_diode,
        # split the diode integral by current direction.  The I<0 (recovery)
        # segment is normally NEGATIVE in this model: the stored charge returns
        # energy instead of dissipating it.  The old draft multiplied Vf by the
        # reverse port charge; that is not any branch's dissipation.
        "e_bodydiode_fwd_uj": branch_energy(tw, vsi - vdi, i_diode * (i_diode > 0.0)),
        "e_bodydiode_rev_uj": branch_energy(tw, vsi - vdi, i_diode * (i_diode < 0.0)),
        "e_rg_uj": branch_energy(tw, vgn - vgi, i_rg),
        "e_cds_delta_uj": branch_energy(tw, vdi - vsi, i_cds),
        "e_cgd_delta_uj": branch_energy(tw, vgi - vdi, i_cgd),
        "e_cgs_delta_uj": branch_energy(tw, vgi - vsi, i_cgs),
        "e_ld_delta_uj": branch_energy(tw, v_a - vdi, i_ld),
        "e_ls_delta_uj": branch_energy(tw, -vsi, i_ls),
        "e_lg_delta_uj": branch_energy(tw, v_g - vgn, i_lg),
        "q_channel_fwd_nc": 1e9 * integrate(tw, np.maximum(-i_ch, 0.0)),
        "q_channel_rev_nc": 1e9 * integrate(tw, np.maximum(i_ch, 0.0)),
        "q_diode_fwd_nc": 1e9 * integrate(tw, np.maximum(i_diode, 0.0)),
        "q_diode_rev_nc": 1e9 * integrate(tw, np.maximum(-i_diode, 0.0)),
        "vgs_min_v": float((vgi - vsi).min()),
        "vgs_max_v": float((vgi - vsi).max()),
        "vds_int_min_v": float((vdi - vsi).min()),
        "vds_int_max_v": float((vdi - vsi).max()),
        "i_ch_max_a": float(i_ch.max()),
        "i_ch_min_a": float(i_ch.min()),
        "i_diode_max_a": float(i_diode.max()),
        "i_diode_min_a": float(i_diode.min()),
    }
    out["e_dissipated_uj"] = out["e_channel_uj"] + out["e_bodydiode_uj"] + out["e_rg_uj"]
    out["e_stored_delta_uj"] = (
        out["e_cds_delta_uj"] + out["e_cgd_delta_uj"] + out["e_cgs_delta_uj"]
        + out["e_ld_delta_uj"] + out["e_ls_delta_uj"] + out["e_lg_delta_uj"]
    )
    out["e_residual_uj"] = (
        out["e_port_ds_uj"] + out["e_gate_pin_uj"] - out["e_dissipated_uj"] - out["e_stored_delta_uj"]
    )
    return out


def aggregate(runs: list[dict[str, float]], freq_hz: float) -> dict[str, float]:
    """Mean/min/max of each per-period quantity plus the window total and power."""
    keys = list(runs[0])
    out: dict[str, float] = {"periods": float(len(runs)), "freq_hz": freq_hz}
    for key in keys:
        values = np.array([run[key] for run in runs], dtype=float)
        out[f"{key}_mean"] = float(values.mean())
        out[f"{key}_min"] = float(values.min())
        out[f"{key}_max"] = float(values.max())
        out[f"{key}_spread_pct"] = 100.0 * float(values.max() - values.min()) / abs(values.mean()) if values.mean() else float("nan")
    # A window total is a sum of per-period energies only for the dissipative
    # terms; reactive terms must be taken as one integral from window edge to
    # edge, which ledger_total() does.  Here we expose the conversion to watts.
    for key in ("e_channel_uj", "e_bodydiode_uj", "e_rg_uj", "e_dissipated_uj",
                "e_port_ds_uj", "e_gate_pin_uj", "e_gate_driver_output_uj"):
        out[key[:-3] + "_w"] = out[f"{key}_mean"] * 1e-6 * freq_hz
    return out


def ledger_total(t: np.ndarray, data: dict[str, np.ndarray], pair: int, t0: float, t1: float) -> dict[str, float]:
    """One integral from t0 to t1: the only correct way to price a reactive term."""
    out = ledger_period(t, data, pair, t0, t1)
    out["span_us"] = (t1 - t0) * 1e6
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path)
    ap.add_argument("--pair", type=int, default=1, help="only pair 1 is instrumented")
    ap.add_argument("--periods", type=int, default=8)
    ap.add_argument("--t-offset-us", type=float, default=0.0,
                    help="add this to display times (the internal deck rebases Tstart=450us to 0)")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    t, data = load(args.raw)
    gate = data[f"V(ga{args.pair})"]
    wins = periods(t, gate, args.periods)

    runs = [ledger_period(t, data, args.pair, t0, t1) for t0, t1 in wins]
    lengths = np.array([t1 - t0 for t0, t1 in wins])
    freq = 1.0 / float(lengths.mean())
    summary = aggregate(runs, freq)
    total = ledger_total(t, data, args.pair, wins[0][0], wins[-1][1])

    off = args.t_offset_us * 1e-6
    print(f"{args.raw}  pair {args.pair}  {len(wins)} periods")
    print(f"window {(wins[0][0] + off) * 1e6:.4f} .. {(wins[-1][1] + off) * 1e6:.4f} us   "
          f"period {lengths.mean() * 1e6:.4f} us  f {freq / 1e3:.1f} kHz")
    print("  --- per-period mean [min .. max] (uJ unless noted) ---")
    show = (
        "e_port_ds_uj", "e_gate_pin_uj", "e_gate_driver_output_uj", "e_channel_uj",
        "e_bodydiode_uj", "e_bodydiode_fwd_uj", "e_bodydiode_rev_uj",
        "e_rg_uj", "e_dissipated_uj", "e_cds_delta_uj", "e_cgd_delta_uj", "e_cgs_delta_uj",
        "e_ld_delta_uj", "e_ls_delta_uj", "e_lg_delta_uj", "e_stored_delta_uj", "e_residual_uj",
        "q_channel_fwd_nc", "q_channel_rev_nc", "q_diode_fwd_nc", "q_diode_rev_nc",
    )
    for key in show:
        print(f"  {key:<22} {summary[key + '_mean']:>10.5f}  "
              f"[{summary[key + '_min']:.5f} .. {summary[key + '_max']:.5f}]")
    print("  --- window total (one integral edge to edge) ---")
    for key in ("e_port_ds_uj", "e_gate_pin_uj", "e_gate_driver_output_uj", "e_channel_uj",
                "e_bodydiode_uj", "e_bodydiode_fwd_uj", "e_bodydiode_rev_uj",
                "e_rg_uj", "e_dissipated_uj", "e_stored_delta_uj", "e_residual_uj"):
        print(f"  {key:<22} {total[key]:>10.5f}")
    print(f"  dissipation at {freq / 1e3:.1f} kHz: channel {summary['e_channel_w'] * 1e3:.1f} mW, "
          f"body diode {summary['e_bodydiode_w'] * 1e3:.1f} mW, gate Rg {summary['e_rg_w'] * 1e3:.1f} mW, "
          f"total {summary['e_dissipated_w'] * 1e3:.1f} mW")
    print(f"  driver output {summary['e_gate_driver_output_w'] * 1e3:.1f} mW (pin {summary['e_gate_pin_w'] * 1e3:.1f} mW)")
    print(f"  residual / port = {100.0 * total['e_residual_uj'] / abs(total['e_port_ds_uj']):.3f} %")
    print("  NOTE: e_port_ds and the e_port_* split from tank_metrics.py are PROXIES; "
          "only the branch columns are internal.")

    if args.json:
        payload = {
            "raw": str(args.raw),
            "pair": args.pair,
            "periods_us": [[(a + off) * 1e6, (b + off) * 1e6] for a, b in wins],
            "freq_hz": freq,
            "per_period": runs,
            "summary": summary,
            "window_total": total,
            "device_params": {"LD_H": LD, "LS_H": LS, "LG_H": LG},
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
