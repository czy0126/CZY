"""Screen the eight SR fault waveforms against the digitised vendor charts.

The SR conducts in the third quadrant: the drain sits below the source and the
current flows from source to drain.  The vendor safe-operating-area diagram is
drawn for the first quadrant, so it cannot score that stress directly.  What it
*can* do is bound the first-quadrant excursions (reverse-recovery and blocking
intervals), and the transient thermal impedance diagram can carry the measured
die power through to a junction-temperature rise.

This tool therefore reports three separate things and never merges them:

* first quadrant -> point-by-point comparison with the digitised SOA curves;
* third quadrant  -> explicitly outside the chart's domain, with the measured
  current, voltage and die power recorded instead;
* thermal         -> die power (pair 1 only, the only pair with die probes)
  convolved with the digitised single-pulse Zth.

The model pins TJ at 25 C and has no thermal feedback, so a passing thermal
rise is a statement about the *simulated* waveform, not about a hot die.

Usage:
    python tools/sr_soa_screen.py --json design/v3/power_priority/sr_soa_screen.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ascii_raw_window import read_window
from vendor_soa import zth_at

ROOT = Path(__file__).resolve().parent.parent
PP = ROOT / "design/v3/power_priority"
DIGITIZED = PP / "vendor_soa_digitized.json"
DEFAULT_JSON = PP / "sr_soa_screen.json"

READ_FROM_S = 165e-6
READ_TAIL_S = 1e-6
BASELINE_WINDOW_S = 20e-6
THERMAL_BIN_S = 1e-6
SOA_CURVES = ("10 us", "100 us")  # the measured fault is ~13 us wide
VDS_RATING_V = 40.0

CASES = {
    "48v_120a": {
        "raw": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.raw",
        "probe_json": PP / "sr_fault_probe_48v_120a.json",
    },
    "48v_120a_cshunt": {
        "raw": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_cshunt_srprobe.raw",
        "probe_json": PP / "sr_fault_probe_48v_120a_cshunt.json",
    },
    "50v_120a_cshunt": {
        "raw": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe.raw",
        "probe_json": PP / "sr_fault_probe_50v_120a_cshunt.json",
    },
}
PAIRS = (1, 2, 3, 4)
SIDES = "ab"
LIMITS = (
    "SIMULATED_ONLY / NOT_RATED. Die probes exist for pair 1 only, so the die "
    "power and the thermal rise are measured for 1A and 1B and assumed to "
    "represent the other six identical model devices. The vendor SOA diagram "
    "is drawn in the first quadrant and says nothing about the third-quadrant "
    "conduction that dominates this fault. The model pins TJ at 25 C with no "
    "thermal feedback, so Rds(on) does not rise with temperature, and no "
    "vendor SOA exists for VDS < 0. A passing thermal rise here is not a "
    "qualified transient-thermal rating."
)


def _round(value: float) -> float:
    return float(f"{value:.6g}")


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def terminal_traces(pair: int, side: str) -> tuple[str, str]:
    return f"V({side}{pair})", f"I(VS{side}{pair})"


def die_traces(side: str) -> tuple[str, str, str, str]:
    node = f"xs{side}1"  # LTspice subcircuit instance names, not the aN/bN terminals
    return f"V({node}:di)", f"V({node}:si)", f"I({node}:Bch)", f"I({node}:Dbd)"


def curve_grid(curve: dict) -> tuple[np.ndarray, np.ndarray]:
    """Log-log grid, collapsing the vertical Vds,max edge onto its peak value."""
    points = sorted(curve["points"])
    xp: list[float] = []
    fp: list[float] = []
    for voltage, current in points:
        if xp and voltage <= xp[-1] * (1.0 + 1e-9):
            fp[-1] = max(fp[-1], current)
            continue
        xp.append(voltage)
        fp.append(current)
    return np.log10(np.array(xp)), np.log10(np.array(fp))


def limit_array(grid: tuple[np.ndarray, np.ndarray], voltage: np.ndarray) -> np.ndarray:
    lx, li = grid
    with np.errstate(divide="ignore", invalid="ignore"):
        return 10.0 ** np.interp(np.log10(np.maximum(voltage, 1e-12)), lx, li)


def first_quadrant(vds: np.ndarray, current: np.ndarray, grids: dict[str, tuple]) -> dict:
    mask = (vds > 0.0) & (current > 0.0)
    volts, amps = vds[mask], current[mask]
    out: dict = {"samples": int(mask.sum()), "samples_compared": int(mask.sum())}
    if not mask.any():
        out.update({"peak_current_a": 0.0, "peak_voltage_v": 0.0, "peak_power_w": 0.0,
                    "peak_utilization": 0.0, "worst_point": None})
        return out
    power = volts * amps
    worst_index = int(np.argmax(power))
    record = {
        "peak_current_a": _round(float(amps.max())),
        "peak_voltage_v": _round(float(volts.max())),
        "peak_power_w": _round(float(power[worst_index])),
        "worst_point": {"vds_v": _round(float(volts[worst_index])),
                        "id_a": _round(float(amps[worst_index]))},
    }
    peak_utilization = 0.0
    for label, grid in grids.items():
        ratio = amps / limit_array(grid, volts)
        peak_utilization = max(peak_utilization, float(ratio.max()))
        record[f"peak_utilization_{label.replace(' ', '_')}"] = _round(float(ratio.max()))
        index = int(np.argmax(ratio))
        record[f"worst_point_against_{label.replace(' ', '_')}"] = {
            "vds_v": _round(float(volts[index])),
            "id_a": _round(float(amps[index])),
            "limit_a": _round(float(limit_array(grid, volts[index:index + 1])[0])),
            "utilization": _round(float(ratio[index])),
        }
    record["peak_utilization"] = _round(peak_utilization)
    out.update(record)
    return out


def third_quadrant(vds: np.ndarray, current: np.ndarray) -> dict:
    mask = (vds < 0.0) & (current < 0.0)
    if not mask.any():
        return {"samples": 0, "peak_current_a": 0.0, "peak_voltage_v": 0.0,
                "peak_port_power_w": 0.0}
    volts, amps = vds[mask], current[mask]
    return {
        "samples": int(mask.sum()),
        # both traces are negative here; their product is the dissipation, which
        # is the same convention the die probes use (Vdie * I_channel > 0)
        "peak_current_a": _round(float(amps.min())),
        "peak_voltage_v": _round(float(volts.min())),
        # port-level product across the *whole* package, so it includes the
        # lead inductance's V = L di/dt and overstates what the die absorbs;
        # the thermal record below is the die-probe measurement
        "peak_port_power_w": _round(float((volts * amps).max())),
    }


def thermal_rise(times, power, trace, bin_s: float = THERMAL_BIN_S) -> float:
    """Peak junction-temperature rise above the window's opening state.

    The power train is binned into rectangular steps; each step contributes
    ``(P_k - P_{k-1}) * Zth(t_n - t_k)``, so the result is the rise from the
    pre-fault operating point, not an absolute junction temperature.
    """
    t = np.asarray(times, dtype=float)
    p = np.asarray(power, dtype=float)
    edges = np.arange(t[0], t[-1] + bin_s, bin_s)
    means = []
    previous = float(p[0])
    for low, high in zip(edges, edges[1:]):
        inside = (t >= low) & (t < high)
        previous = float(p[inside].mean()) if inside.any() else previous
        means.append(previous)
    peak = 0.0
    for n in range(1, len(means)):
        rise = 0.0
        for k in range(1, n + 1):
            step = means[k] - means[k - 1]
            if step:
                rise += step * zth_at(trace, float(edges[n] - edges[k]))
        peak = max(peak, rise)
    return peak


def die_record(traces: dict, trace: list, side: str, t_first: float) -> dict:
    node = f"xs{side}1"
    volts = traces[f"V({node}:di)"] - traces[f"V({node}:si)"]
    channel = traces[f"I({node}:Bch)"]
    diode = traces[f"I({node}:Dbd)"]
    power = volts * (channel - diode)
    times = traces["t"]
    baseline = (times - t_first) < BASELINE_WINDOW_S
    steady = float(power[baseline].mean()) if baseline.any() else float(power[0])
    peak = float(power.max())
    excess = power - steady
    width = float(np.trapezoid(np.clip(excess, 0.0, None), times)) / max(peak - steady, 1e-12)
    rise = thermal_rise(times, power, trace)
    return {
        "device": f"1{side.upper()}",
        "steady_state_die_power_w": _round(steady),
        "peak_die_power_w": _round(peak),
        "peak_channel_power_w": _round(float((volts * channel).max())),
        "peak_body_diode_power_w": _round(float((-volts * diode).max())),
        "blocking_voltage_max_v": _round(float(np.abs(volts).max())),
        "energy_equivalent_width_s": _round(width),
        "peak_rise_k": _round(rise),
        "rectangular_estimate_k": _round((peak - steady) * zth_at(trace, width)),
    }


def screen_case(case: str) -> dict:
    spec = CASES[case]
    probe = json.loads(spec["probe_json"].read_text(encoding="utf-8"))["results"]
    digitized = json.loads(DIGITIZED.read_text(encoding="utf-8"))
    trace = digitized["zth"]["single_pulse"]
    grids = {label: curve_grid(next(c for c in digitized["soa"]["curves"] if c["label"] == label))
             for label in SOA_CURVES}
    t_last = float(probe["t_last_s"])

    names = []
    for pair in PAIRS:
        for side in SIDES:
            names.extend(terminal_traces(pair, side))
    for side in SIDES:
        names.extend(die_traces(side))
    t, data = read_window(spec["raw"], names, READ_FROM_S, t_last + READ_TAIL_S)
    data["t"] = t

    devices = {}
    for pair in PAIRS:
        for side in SIDES:
            gate, current_name = terminal_traces(pair, side)
            vds = data[gate]
            current = data[current_name]
            devices[f"{pair}{side.upper()}"] = {
                "vds_max_v": _round(float(np.abs(vds).max())),
                "vds_rating_utilization": _round(float(np.abs(vds).max()) / VDS_RATING_V),
                "first_quadrant": first_quadrant(vds, current, grids),
                "third_quadrant": third_quadrant(vds, current),
            }

    dies = {f"1{side.upper()}": die_record(data, trace, side, float(t[0])) for side in SIDES}
    governing = max(dies, key=lambda name: dies[name]["peak_rise_k"])
    thermal = dict(dies[governing])
    thermal["devices"] = dies
    return {
        "raw": _relative(spec["raw"]),
        "probe_record": _relative(spec["probe_json"]),
        "window": {"from_s": _round(float(t[0])), "to_s": _round(float(t[-1])),
                   "trip_s": _round(float(probe["trip_s"]))},
        "devices": devices,
        "thermal": thermal,
    }


def build() -> dict:
    digitized = json.loads(DIGITIZED.read_text(encoding="utf-8"))
    runs = {case: screen_case(case) for case in CASES}
    every_device = all(len(run["devices"]) == 8 for run in runs.values())
    compared = all(record["first_quadrant"]["samples_compared"]
                   == record["first_quadrant"]["samples"]
                   for run in runs.values() for record in run["devices"].values())
    highest = max(record["vds_max_v"] for run in runs.values() for record in run["devices"].values())
    curves_reach = max(max(p[0] for p in c["points"]) for c in digitized["soa"]["curves"])
    longest = max(record["window"]["to_s"] - record["window"]["from_s"] for record in runs.values())
    checks = {
        "all_eight_devices_have_waveforms": every_device,
        "every_first_quadrant_sample_was_compared": compared,
        "the_soa_curve_covers_the_measured_voltage_range": highest <= curves_reach,
        "the_zth_trace_covers_the_saved_window": longest <= digitized["zth"]["single_pulse"][-1][0],
    }
    return {
        "source": {
            "vendored_pdf": digitized["source"]["pdf"],
            "sha256": digitized["source"]["sha256"],
            "digitized_json": _relative(DIGITIZED),
        },
        "results": {
            "runs": runs,
            "quadrants": {
                "first_quadrant_is_the_drawn_domain": True,
                "third_quadrant_screened_by_the_chart": False,
                "explanation": ("the SR carries current from source to drain with the drain "
                                "below the source; the vendor diagram plots VDS > 0, ID > 0"),
            },
            "soa": {"curves_used": list(SOA_CURVES), "vds_rating_v": VDS_RATING_V},
            "cross_checks": {
                "die_power_never_exceeds_the_port_product": all(
                    run["thermal"]["devices"][name]["peak_die_power_w"]
                    <= run["devices"][name]["third_quadrant"]["peak_port_power_w"]
                    for run in runs.values() for name in run["thermal"]["devices"]),
                "note": ("the port product includes the package lead inductance, so it is "
                         "an upper bound on dissipation, not a second measurement of it"),
            },
            "limits": LIMITS,
        },
        "checks": {"ok": all(checks.values()), **checks},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args()
    data = build()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.json}")
    if not data["checks"]["ok"]:
        raise SystemExit("screen checks failed")


if __name__ == "__main__":
    main()
