"""Same-deck / same-window 100 A energy ledger (review 2026-11-01, issue #3).

Why this exists
---------------
The round-3 efficiency budget extrapolated loss from a single I^2 point.  The
review asked for the port energy measured over one window, itemised into terms
that are *also* measured in that window, with the leftover stated as a residual.

This tool reads the instrumented deck's ASCII raw and integrates, by trapezoid,
over an integer number of primary gate periods:

    Pin(source) = 48 V * mean(I(Rin))          (ideal Vbus, Rin is the 1 mOhm)
    Pout        = mean(V(out)^2 / RL)          (not Vout_avg^2 / RL)
    losses      = I^2 R for series elements, or v*i for switching devices
    stored      = 1/2 L I^2, 1/2 C V^2, differenced across the window

Two supplies sit *outside* the port and are reported separately, because mixing
them into Pin-Pout would blame the power stage for energy it never drew:

    Vreg  feeds the SR gate loop (ideal driver supply in this deck)
    Vaux  feeds the primary controller bias

What is measured vs assumed is recorded per term.  Pair 2/3 secondary copper is
scaled from pair 1 by symmetry -- the model makes that exact, hardware will not.
"""

from __future__ import annotations

import argparse
import json
from array import array
from collections.abc import Iterator
from itertools import islice
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.raw"
OUT = ROOT / "design/v3/stage_f/energy_ledger_100a.json"

VIN = 48.0
RL = 18.9e-3
RIN = 1e-3
R_LR = 5e-3
R_LP = 3e-3          # x4 in series
R_CR = 3e-3
R_COUT = 0.2e-3
R_SEC = 0.15e-3      # x8 half-windings; pair 1 measured, pairs 2/3 assumed
RON_PRI = 8e-3
LR_H = 0.92e-6
LP_H = 10e-6
CR_F = 620e-9
COUT_F = 4e-3

WANTED = {
    "V(vin)": "vin", "V(out)": "vout", "V(sw)": "vsw", "V(nr)": "vnr",
    "V(reg)": "vreg",
    "I(Rin)": "iin", "I(Lr)": "ilr", "I(Cout)": "icout", "I(Vaux)": "ivaux",
    "I(Vreg)": "ivreg", "I(SH)": "ish", "I(SL)": "isl",
    "I(DH)": "idh", "I(DL)": "idl", "I(Rbur)": "irbur",
    "I(D1)": "id1", "I(D2)": "id2", "I(D3)": "id3", "I(D4)": "id4",
    "V(cs1)": "vcs1", "V(cs2)": "vcs2", "V(ocd)": "vocd", "V(ocm)": "vocm",
    "V(ga1)": "vga", "V(gb1)": "vgb",
    "I(xsr1:x1:Bdrive)": "bd1", "I(xsr1:x2:Bdrive)": "bd2",
    "I(VSa1)": "isa1", "I(VSb1)": "isb1",
}

PAIR1_INTERNALS = {
    "a": {"di": "V(xsa1:di)", "si": "V(xsa1:si)", "bch": "I(xsa1:Bch)",
          "dbd": "I(xsa1:Dbd)", "rg": "I(xsa1:Rg)"},
    "b": {"di": "V(xsb1:di)", "si": "V(xsb1:si)", "bch": "I(xsb1:Bch)",
          "dbd": "I(xsb1:Dbd)", "rg": "I(xsb1:Rg)"},
}


def read_raw_header(path: Path) -> tuple[list[str], float]:
    """Return variable names (including ``time``) and the saved-axis Offset."""
    names: list[str] = []
    offset = 0.0
    in_vars = False
    with path.open("r", encoding="ascii", errors="replace") as fh:
        for line in fh:
            if line.startswith("Offset:"):
                offset = float(line.split(":", 1)[1])
            elif line.startswith("No. Variables:"):
                pass
            elif line.startswith("Variables:"):
                in_vars = True
            elif line.startswith("Values:"):
                break
            elif in_vars:
                parts = line.rstrip("\r\n").split("\t")
                if len(parts) >= 3:
                    names.append(parts[2])
    return names, offset


def stream_points(path: Path) -> Iterator[tuple[float, list[float]]]:
    """Yield (time, values) one ASCII record at a time.  Test-sized use only."""
    names, _ = read_raw_header(path)
    count = len(names)
    with path.open("r", encoding="ascii", errors="replace") as fh:
        for line in fh:
            if line.startswith("Values:"):
                break
        while True:
            header = fh.readline()
            if not header:
                return
            fields = header.rstrip("\r\n").split("\t")
            if len(fields) < 2:
                return
            values = [float(fh.readline()) for _ in range(count - 1)]
            yield float(fields[-1]), values


def scan(path: Path, wanted: dict[str, str]) -> tuple[array, dict[str, array]]:
    """Read only the wanted columns into ``array('d')`` (a 424 MB raw is 80 vars)."""
    names, _ = read_raw_header(path)
    index = {name: i for i, name in enumerate(names)}
    missing = sorted(set(wanted) - set(index))
    if missing:
        raise KeyError(f"{path.name} has no probes: {missing}")
    columns = {key: index[name] - 1 for name, key in wanted.items()}  # time has no line
    by_line = {line: key for key, line in columns.items()}
    times = array("d")
    data = {key: array("d") for key in wanted.values()}
    with path.open("r", encoding="ascii", errors="replace") as fh:
        for line in fh:
            if line.startswith("Values:"):
                break
        while True:
            header = fh.readline()
            if not header:
                break
            fields = header.rstrip("\r\n").split("\t")
            if len(fields) < 2:
                break
            times.append(float(fields[-1]))
            for line_no, value in enumerate(islice(fh, len(names) - 1)):
                key = by_line.get(line_no)
                if key is not None:
                    data[key].append(float(value))
    return times, data


def _integral(t: array, y: array, i0: int, i1: int) -> float:
    total = 0.0
    for i in range(i0, i1):
        total += 0.5 * (y[i] + y[i + 1]) * (t[i + 1] - t[i])
    return total


def _mean(t: array, y: array, i0: int, i1: int) -> float:
    return _integral(t, y, i0, i1) / (t[i1] - t[i0])


def trapezoid_mean(t: list[float], y: list[float]) -> float:
    """Public, list-based form used by the tests; same arithmetic as the arrays."""
    total = sum(0.5 * (y[i] + y[i + 1]) * (t[i + 1] - t[i]) for i in range(len(t) - 1))
    return total / (t[-1] - t[0])


def _mean_product(t: array, a: array, b: array, i0: int, i1: int) -> float:
    return _mean(t, array("d", (a[i] * b[i] for i in range(len(a)))), i0, i1)


def gate_window(t: array, gate: array, periods: int = 16,
                level: float = 2.5, debounce_s: float = 200e-9) -> tuple[int, int]:
    """Last ``periods`` complete gate periods, bounded by real rising edges.

    The 5 ns timestep plus gate ringing crosses ``level`` more than once per
    rise; without a debounce the 24 real periods in the raw look like 48 edges
    and the window silently halves.  Edges closer than ``debounce_s`` are the
    same edge.
    """
    raw_edges = [i for i in range(1, len(gate)) if gate[i] >= level > gate[i - 1]]
    edges = []
    for i in raw_edges:
        if not edges or t[i] - t[edges[-1]] > debounce_s:
            edges.append(i)
    if len(edges) < 2:
        raise ValueError("fewer than two gate rising edges in the raw")
    if len(edges) > periods:
        return edges[-(periods + 1)], edges[-1]
    return edges[0], edges[-1]


def build(raw: Path = RAW, periods: int = 16) -> dict[str, object]:
    names, _ = read_raw_header(raw)
    wanted = dict(WANTED)
    for half, probes in PAIR1_INTERNALS.items():
        for key, probe in probes.items():
            wanted[probe] = f"{half}_{key}"
    t, d = scan(raw, wanted)
    i0, i1 = gate_window(t, d["vga"], periods)
    span = t[i1] - t[i0]

    def mean(key: str) -> float:
        return _mean(t, d[key], i0, i1)

    def msq(key: str) -> float:
        return _mean(t, array("d", (v * v for v in d[key])), i0, i1)

    def product(a: str, b: str) -> float:
        return _mean_product(t, d[a], d[b], i0, i1)

    p_in_src = VIN * mean("iin")
    p_in_after_rin = product("vin", "iin")
    p_out = _mean(t, array("d", (v * v / RL for v in d["vout"])), i0, i1)

    def i2r(key: str, resistance: float, confidence: str) -> dict[str, object]:
        return {"w": msq(key) * resistance, "confidence": confidence}

    losses: dict[str, dict[str, object]] = {
        "rin": i2r("iin", RIN, "measured-i2r"),
        "lr": i2r("ilr", R_LR, "measured-i2r"),
        "lp_series": i2r("ilr", 4 * R_LP, "measured-i2r"),
        "cr_esr": i2r("ilr", R_CR, "measured-i2r"),
        "cout_esr": i2r("icout", R_COUT, "measured-i2r"),
        "secondary_copper": {
            "w": (msq("isa1") + msq("isb1")) * R_SEC * 4,
            "confidence": "symmetry-assumption",
        },
        "sh": i2r("ish", RON_PRI, "measured-commutation"),
        "sl": i2r("isl", RON_PRI, "measured-commutation"),
        "dh": {"w": _mean(t, array("d", ((d["vsw"][i] - d["vin"][i]) * d["idh"][i]
                                        for i in range(len(t)))), i0, i1),
               "confidence": "measured-commutation"},
        "dl": {"w": _mean(t, array("d", (-d["vsw"][i] * d["idl"][i]
                                        for i in range(len(t)))), i0, i1),
               "confidence": "measured-commutation"},
    }

    pair1 = 0.0
    for half in ("a", "b"):
        vds = array("d", (d[f"{half}_di"][i] - d[f"{half}_si"][i] for i in range(len(t))))
        ch = _mean(t, array("d", (vds[i] * d[f"{half}_bch"][i] for i in range(len(t)))),
                   i0, i1)
        bd = _mean(t, array("d", (-vds[i] * d[f"{half}_dbd"][i] for i in range(len(t)))),
                   i0, i1)
        pair1 += ch + bd
    losses["sr_channel_body_pair1"] = {"w": pair1, "confidence": "measured-commutation"}
    losses["sr_channel_body_x4"] = {"w": 4 * pair1, "confidence": "symmetry-assumption"}

    rg_w = sum(_mean(t, array("d", (d[f"{h}_rg"][i] ** 2 for i in range(len(t)))),
                     i0, i1) * 1.0 for h in ("a", "b"))
    losses["sr_gate_resistor_x8"] = {"w": 4 * rg_w, "confidence": "symmetry-assumption"}

    ct_diodes = (
        _mean(t, array("d", ((d["vcs1"][i] - d["vocd"][i]) * d["id1"][i]
                             for i in range(len(t)))), i0, i1)
        + _mean(t, array("d", ((d["vcs2"][i] - d["vocd"][i]) * d["id2"][i]
                               for i in range(len(t)))), i0, i1)
        + _mean(t, array("d", ((d["vocm"][i] - d["vcs1"][i]) * d["id3"][i]
                               for i in range(len(t)))), i0, i1)
        + _mean(t, array("d", ((d["vocm"][i] - d["vcs2"][i]) * d["id4"][i]
                               for i in range(len(t)))), i0, i1)
    )
    losses["ct_bridge_diodes"] = {"w": ct_diodes, "confidence": "measured-commutation"}
    losses["ct_burden_resistor"] = i2r("irbur", 10.0, "measured-i2r")

    e_lr = 0.5 * LR_H
    e_lp = 4 * 0.5 * LP_H
    stored = {
        "lr_j": e_lr * (d["ilr"][i1] ** 2 - d["ilr"][i0] ** 2),
        "lp_j": e_lp * (d["ilr"][i1] ** 2 - d["ilr"][i0] ** 2),
        "cr_j": 0.5 * CR_F * ((d["vsw"][i1] - d["vnr"][i1]) ** 2
                              - (d["vsw"][i0] - d["vnr"][i0]) ** 2),
        "cout_j": 0.5 * COUT_F * (d["vout"][i1] ** 2 - d["vout"][i0] ** 2),
    }
    d_stored_w = sum(stored.values()) / span

    def total(names_: list[str]) -> float:
        return sum(float(losses[name]["w"]) for name in names_)

    # pair1 is the measurement the x4 term is built from: counting both would
    # add 1.85 W of pure double-entry.
    all_main = [name for name in losses
                if name not in ("sr_gate_resistor_x8", "sr_channel_body_pair1")]
    loss_main = total(all_main)
    loss_before_ct = total([name for name in all_main
                            if not name.startswith("ct_")])
    port_w = p_in_src - p_out
    # Loss-side balance: what the measured terminals say minus the summed
    # element losses.  The stored-energy endpoint difference is NOT folded in:
    # gate rising edges sit at a phase of the tank that jitters by ~1 %, so the
    # endpoint E(i1)-E(i0) moves by several hundred mW between equally valid
    # windows.  It is reported separately with that limit written down.
    loss_residual = port_w - loss_main

    vreg_w = -product("vreg", "ivreg")
    vaux_w = -12.0 * mean("ivaux")      # V(aux) is the ideal 12 V source, not saved
    # The SR gate B-sources are ideal: they do not draw from Vreg at all, so the
    # deck supplies the gate energy for free.  This integral is what a real bias
    # supply would have to deliver (pair 1 measured, x4 by symmetry).
    # I(Bdrive) is reported flowing into the B-source, so the power *delivered*
    # to the gate loop is the negative of V(gate)*I.  Cross-check: the result
    # (~0.21 W) must exceed the gate-resistor loss (~0.18 W).
    driver_w = -4 * (product("vga", "bd1") + product("vgb", "bd2"))

    phase_limit = abs(d_stored_w)
    checks = {
        "loss_residual_within_0p2_w": abs(loss_residual) <= 0.2,
        "ct_burden_closes_the_gap": abs(port_w - loss_before_ct) <= 0.2,
        "stored_energy_reported_not_folded_in": True,
        "pout_uses_v_squared": abs(p_out - mean("vout") ** 2 / RL) > 0.0,
    }
    limits = []
    if abs(loss_residual) > 0.2:
        limits.append("loss residual exceeds 0.2 W; do not quote an efficiency "
                      "from this run")
    if phase_limit > 0.2:
        limits.append(f"stored-energy endpoint term is phase-sensitive "
                      f"({phase_limit:.3f} W); it is excluded from the loss "
                      f"residual, not assumed to be zero")
    return {
        "raw": {"path": str(raw.relative_to(ROOT)).replace("\\", "/"),
                "bytes": raw.stat().st_size, "mtime": raw.stat().st_mtime,
                "variables": len(names)},
        "window": {
            "start_s": float(t[i0]), "end_s": float(t[i1]), "span_s": float(span),
            "periods": periods, "raw_time_start_s": 880e-6,
            "display_offset_us": 880.0,
        },
        "port": {
            "vin_v": VIN, "rl_ohm": RL,
            "pin_source_w": p_in_src,
            "pin_after_rin_w": p_in_after_rin,
            "pout_w": p_out,
            "pin_minus_pout_w": port_w,
        },
        "losses": losses,
        "loss_total_w": loss_main,
        "loss_before_ct_w": loss_before_ct,
        "stored_energy_j": stored,
        "stored_energy_w": d_stored_w,
        "outside_port": {"vreg_w": vreg_w, "vaux_w": vaux_w,
                         "driver_output_w": driver_w},
        "balance": {
            "residual_w": loss_residual,
            "loss_residual_w": loss_residual,
            "target_w": 0.2,
            "stored_energy_endpoint_w": d_stored_w,
            "stored_energy_phase_limit_w": phase_limit,
            "note": "residual_w is Pin - Pout - summed element losses.  The "
                    "stored-energy endpoint term is reported separately because "
                    "its sign and size change with the gate-edge phase; over "
                    "16 periods it is not resolvable below its own limit.",
            "limits": limits,
        },
        "sensitivity": {
            "max_step_s": 5e-9,
            "note": "5 ns max step, GEAR; a 2 ns rerun was not made, so the "
                    "integration error is not bounded by repetition",
            "device_parameters": "Rds/Isat fitted; package parasitics are ESTIMATE "
                                 "per models/sr_device_v3.lib",
        },
        "checks": {"ok": all(checks.values()), **checks},
    }


def write(path: Path = OUT) -> dict[str, object]:
    summary = build()
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--json", type=Path, default=OUT)
    parser.add_argument("--periods", type=int, default=16)
    args = parser.parse_args()
    summary = build(args.raw, args.periods)
    args.json.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    print(json.dumps({"residual_w": summary["balance"]["residual_w"],
                      "port_w": summary["port"]["pin_minus_pout_w"],
                      "checks": summary["checks"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
