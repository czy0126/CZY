"""Size the 48 V input capacitor bank from the measured half-bridge input current.

The trap is the trace.  The deck's source is an ideal 48 V battery behind 1 mohm,
so `I(Cin)` is 0.227 A while the half-bridge is drawing 5.3 A of ripple: the model
sends the ripple through the source, not through the capacitor.  What an input
filter has to supply is the bridge current, `I(Rin) - I(Cin)`, and that trace only
exists in the `_cin` probe decks.

Two more traps are handled here instead of in prose:

* the model has no package inductance, so the switch-node capacitance dumps its
  charge in about a nanosecond.  That sample reaches 366 A while carrying 3.5 % of
  the I^2 t at 120 A, so the RMS requirement uses the whole waveform (conservative)
  and the repetitive-peak requirement uses `I(Lr)` PEAK in the same run.
* parallel parts split ripple in proportion to capacitance, not evenly, so a bank of
  unequal parts puts most of the current in the largest one (same rule as
  `tools/cr_bank.py`).

There is no input-ripple limit anywhere in this repository, so the capacitance table
reports consequences instead of passing judgement.  No capacitor datasheet exists
either, so every per-part figure is a *requirement* and nothing here names a part.

Usage:
    python tools/cin_bank.py --json design/v3/bom/cin_bank.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ascii_raw_window import read_window

REPO = Path(__file__).resolve().parent.parent
DECK = REPO / "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"
PASSIVE = REPO / "design/v3/bom/passive_requirements.json"
LR_DESIGN = REPO / "design/v3/bom/lr_design.json"

# Every raw here saves I(Cin), I(Rin) and I(Lr).  The windows are the ones the
# ledger family already uses for the same runs, so the bridge current is measured on
# exactly the window whose other numbers are published.
WINDOWS = {
    "sr_tank_dual_v33_ss_1ms_100a_cin.raw": (7.704687, 117.363517),
    "sr_tank_dual_v33_ss_1ms_vin48_i120_cin.raw": (7.6445, 117.3105),
    "sr_tank_dual_v33_ss_1ms_vin50_i120_cin.raw": (7.631583516341496, 117.2982368985085),
}

CAPACITANCE_TABLE_F = (4.7e-6, 10e-6, 20e-6, 22e-6, 47e-6, 100e-6)
PART_EXAMPLES_F = ((20e-6,), (10e-6, 10e-6), (22e-6, 4.7e-6), (4.7e-6,) * 4, (22e-6, 22e-6))

# The same self-chosen dissipation budget the Cout bank uses, so the two banks are
# read on one rule.  It is a reference number, not a specification.
ESR_BUDGET_W = 1.0

# Above this instantaneous deviation the model is switching capacitance, not
# conducting: 1.12 nF of switch-node capacitance has no series inductance here.
SPIKE_A = 20.0

_SI = {"n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "": 1.0}


def _si(text: str) -> float:
    match = re.fullmatch(r"([+-]?[.\d]+)([numk]?)", text.strip())
    if not match:
        raise ValueError(f"not a SPICE value: {text!r}")
    return float(match.group(1)) * _SI[match.group(2)]


def deck_cin(path: Path = DECK) -> dict[str, object]:
    """The input capacitor the 100 A deck actually runs, read from its own line."""
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^Cin\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+Rser=(\S+))?\s*$", line)
        if match:
            return {
                "element": line.strip(),
                "positive_node": match.group(1),
                "negative_node": match.group(2),
                "capacitance_f": _si(match.group(3)),
                "esr_ohm": _si(match.group(4)) if match.group(4) else 0.0,
            }
    raise SystemExit(f"{path}: no Cin element")


def _ac_rms(t: np.ndarray, y: np.ndarray, span: float) -> float:
    """Time-weighted RMS of the deviation from the mean, which is what a cap heats on."""
    mean = float(np.trapezoid(y, t) / span)
    ac = y - mean
    return float(np.sqrt(np.trapezoid(ac * ac, t) / span))


def measure(raw: Path, window_us: tuple[float, float]) -> dict[str, object]:
    """Bridge current = I(Rin) - I(Cin); the capacitor is only one branch of that node."""
    t, v = read_window(raw, ["I(Cin)", "I(Rin)", "I(Lr)"], window_us[0] * 1e-6, window_us[1] * 1e-6)
    bridge = v["I(Rin)"] - v["I(Cin)"]
    span = float(t[-1] - t[0])
    mean = float(np.trapezoid(bridge, t) / span)
    ac = bridge - mean
    squares = ac * ac
    total_i2t = float(np.trapezoid(squares, t))
    spiky = np.abs(ac) > SPIKE_A
    clipped = np.clip(ac, -SPIKE_A, SPIKE_A)
    return {
        "raw": raw.name,
        "window_us": [window_us[0], window_us[1]],
        "bridge_mean_a": mean,
        "bridge_rms_a": float(np.sqrt(np.trapezoid(bridge * bridge, t) / span)),
        "bridge_ac_rms_a": float(np.sqrt(total_i2t / span)),
        "bridge_ac_rms_without_switching_spikes_a": float(np.sqrt(np.trapezoid(clipped * clipped, t) / span)),
        "bridge_ac_peak_model_a": float(np.abs(ac).max()),
        "spike_sample_share": float(spiky.mean()),
        "i2t_in_spike_samples_pct": 100.0 * float(np.trapezoid(squares * spiky, t)) / total_i2t,
        "ipri_peak_a": float(np.abs(v["I(Lr)"]).max()),
        "cin_ac_rms_a": _ac_rms(t, v["I(Cin)"], span),
    }


def ripple_row(capacitance_f: float, current_a: float, esr_ohm: float,
               freq_hz: float, vin_v: float) -> dict[str, float]:
    """First-harmonic estimate at the switching frequency, with and without ESR."""
    xc = 1.0 / (2.0 * math.pi * freq_hz * capacitance_f)
    z = math.hypot(esr_ohm, xc)
    dv_rms = current_a * z
    dv_pp = 2.0 * math.sqrt(2.0) * dv_rms
    return {
        "capacitance_f": capacitance_f,
        "xc_ohm": xc,
        "z_ohm": z,
        "dv_rms_v": dv_rms,
        "dv_pp_sinusoidal_v": dv_pp,
        "dv_pp_percent_of_vin": 100.0 * dv_pp / vin_v,
        "dv_pp_without_esr_v": 2.0 * math.sqrt(2.0) * current_a * xc,
        "esr_loss_w": current_a * current_a * esr_ohm,
    }


def source_share(zs_ohm: float, capacitance_f: float, esr_ohm: float, freq_hz: float) -> float:
    """Fraction of the bridge ripple the capacitor takes, as a magnitude divider."""
    z = math.hypot(esr_ohm, 1.0 / (2.0 * math.pi * freq_hz * capacitance_f))
    return zs_ohm / (zs_ohm + z) if zs_ohm + z > 0 else 1.0


def per_part(values_f: tuple[float, ...], current_a: float, esr_ceiling_ohm: float) -> dict[str, object]:
    """Unequal parts split the ripple by capacitance; the ESR ceiling is per part."""
    total = sum(values_f)
    return {
        "values_f": list(values_f),
        "n_parts": len(values_f),
        "total_f": total,
        "per_part": [
            {
                "c_f": c,
                "share_frac": c / total,
                "irms_a": current_a * c / total,
                "esr_max_ohm": esr_ceiling_ohm * len(values_f),
            }
            for c in values_f
        ],
        "max_part_irms_a": max(current_a * c / total for c in values_f),
    }


def build(measurements: list[dict], deck: dict, tank: dict, published: dict,
          vin_v: float = 48.0) -> dict[str, object]:
    """Pure report assembly.  Measurements come from `measure()`, or from a test."""
    if not measurements:
        raise SystemExit("no measurements: pass at least one _cin raw")
    design = next((m for m in measurements if "100a" in str(m["raw"])), None)
    if design is None:
        raise SystemExit("the 100 A probe raw is missing, so the published number cannot be reproduced")
    worst = max(measurements, key=lambda m: m["bridge_ac_rms_a"])
    freq = tank["clock_khz"] * 1e3
    current = worst["bridge_ac_rms_a"]

    table = [ripple_row(c, current, deck["esr_ohm"], freq, vin_v) for c in CAPACITANCE_TABLE_F]
    ceiling = ESR_BUDGET_W / (current * current)
    examples = [per_part(values, current, ceiling) for values in PART_EXAMPLES_F]
    at_design_point = ripple_row(deck["capacitance_f"], current, deck["esr_ohm"], freq, vin_v)

    results = {
        "bridge_ac_rms_a_at_100a": design["bridge_ac_rms_a"],
        "bridge_ac_rms_a_at_worst_measured_load": current,
        "worst_measured_load_raw": worst["raw"],
        "requirement_rise_from_100a_pct": 100.0 * (current / design["bridge_ac_rms_a"] - 1.0),
        "ipri_peak_a_at_100a": design["ipri_peak_a"],
        "ipri_peak_a_at_worst_measured_load": worst["ipri_peak_a"],
        "current_through_the_modelled_capacitor_a": design["cin_ac_rms_a"],
        "share_of_the_bridge_ripple_the_model_puts_in_the_capacitor_pct":
            100.0 * design["cin_ac_rms_a"] / design["bridge_ac_rms_a"],
        "peak_sample_a": worst["bridge_ac_peak_model_a"],
        "spike_sample_share": worst["spike_sample_share"],
        "i2t_in_spike_samples_pct": worst["i2t_in_spike_samples_pct"],
        "ac_rms_with_spikes_clipped_to_20a_a": worst["bridge_ac_rms_without_switching_spikes_a"],
        "capacitance_at_the_simulated_point_f": deck["capacitance_f"],
        "ripple_at_the_simulated_point_pp_v": at_design_point["dv_pp_sinusoidal_v"],
        "ripple_at_the_simulated_point_percent_of_vin": at_design_point["dv_pp_percent_of_vin"],
        "ripple_with_esr_removed_pp_v": at_design_point["dv_pp_without_esr_v"],
        "esr_for_a_1w_budget_ohm": ceiling,
        "esr_of_the_simulated_bank_ohm": deck["esr_ohm"],
        "esr_loss_of_the_simulated_bank_w": at_design_point["esr_loss_w"],
        "capacitance_is_not_the_binding_constraint": at_design_point["dv_pp_percent_of_vin"] < 2.0,
        "the_repetitive_peak_is_ipri_not_the_model_spike": True,
        "fault_window_input_current_is_not_measured": True,
        "inrush_is_not_modelled": True,
        "the_capacitor_share_depends_on_the_source_impedance": {
            f"{zs:g}_ohm": source_share(zs, deck["capacitance_f"], deck["esr_ohm"], freq)
            for zs in (0.01, 0.1, 1.0)
        },
    }
    checks = {
        # The 20 uF / 5 mohm the probe raws were taken on.  If the deck's Cin line moves,
        # the published requirement and the raw it came from no longer describe one circuit.
        "the_deck_runs_the_capacitor_the_probe_raws_were_taken_on": (
            abs(deck["capacitance_f"] - 20e-6) < 1e-12 and abs(deck["esr_ohm"] - 5e-3) < 1e-12
        ),
        "the_published_100a_requirement_is_reproduced": (
            abs(design["bridge_ac_rms_a"] - published["bridge_ac_rms_a"]) < 1e-9 * published["bridge_ac_rms_a"]
        ),
        "the_worst_case_is_not_below_the_design_load": current >= design["bridge_ac_rms_a"],
        "every_table_row_is_computed_from_the_same_current": all(
            abs(row["dv_rms_v"] - current * row["z_ohm"]) < 1e-15 for row in table
        ),
        "no_part_is_named": not any(
            word in json.dumps([table, examples]).lower() for word in ("mpn", "lcsc", "part_number")
        ),
    }
    return {
        "status": "sizing only; no capacitor datasheet exists in the repository, so every per-part figure "
                  "is a requirement, not a selected part",
        "sources": {
            "deck": str(DECK.relative_to(REPO)).replace("\\", "/"),
            "published_100a": str(PASSIVE.relative_to(REPO)).replace("\\", "/"),
            "tank": str(LR_DESIGN.relative_to(REPO)).replace("\\", "/"),
        },
        "deck": deck,
        "frequency_hz": freq,
        "vin_v": vin_v,
        "measurements": measurements,
        "requirements": {
            "bridge_ac_rms_a_at_100a": design["bridge_ac_rms_a"],
            "bridge_ac_rms_a_at_worst_measured_load": current,
            "ipri_peak_a": worst["ipri_peak_a"],
            "note": "size the bank at the worst measured load; the 100 A figure is the rated point and the "
                    "120 A runs are the over-load candidates that are already in the evidence set",
        },
        "esr_budget": {
            "dissipation_w": ESR_BUDGET_W,
            "bank_esr_ceiling_ohm": ceiling,
            "note": "self-chosen, same 1 W rule as the Cout bank; the repository defines no input-ripple or "
                    "input-capacitor ESR limit",
        },
        "ripple_table": table,
        "per_part_examples": examples,
        "checks": checks,
        "results": results,
        "no_capacitor_datasheet_in_repository": True,
        "caveats": [
            "first-harmonic estimate at the 200.622 kHz clock: the real waveform is a duty-cycle pulse plus "
            "the switch-node capacitance charge, so the table is a magnitude, not a waveform",
            "the model has no package inductance, so the switch-node capacitance discharges in about a "
            "nanosecond; the peak sample is an artifact and the honest repetitive peak is I(Lr) PEAK",
            "ESR is the model's Rser, not a part specification; ESR at 200 kHz differs from the 120 Hz value",
            "parallel resonance between a bulk electrolytic and ceramics is not modelled",
            "the fault windows do not save I(Cin)/I(Rin), so fault-window input current is unknown",
            "cold-start inrush is not modelled either: the 8 ms cold deck saves other probes",
        ],
    }


def default_raws() -> list[Path]:
    return [REPO / "sim/v3" / name for name in WINDOWS]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=Path("design/v3/bom/cin_bank.json"))
    ap.add_argument("--raw", type=Path, action="append", default=None,
                    help="a _cin probe raw; the window is looked up by file name")
    args = ap.parse_args()
    raws = [Path(p) for p in args.raw] if args.raw else default_raws()
    measurements = []
    for raw in raws:
        if raw.name not in WINDOWS:
            raise SystemExit(f"{raw.name}: no window on record; add it to WINDOWS first")
        if not raw.is_file():
            raise SystemExit(f"{raw}: missing (the JSON is committed evidence and is not regenerated without it)")
        measurements.append(measure(raw, WINDOWS[raw.name]))
    published = json.loads(PASSIVE.read_text(encoding="utf-8"))["cin"]
    tank = json.loads(LR_DESIGN.read_text(encoding="utf-8"))["tank"]
    data = build(measurements, deck_cin(), tank, published)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    worst = data["results"]["bridge_ac_rms_a_at_worst_measured_load"]
    print(f"{args.json}")
    print(f"bridge AC RMS: {data['results']['bridge_ac_rms_a_at_100a']:.4f} A at 100 A, "
          f"{worst:.4f} A at the worst measured load")
    print(f"ripple at {data['deck']['capacitance_f'] * 1e6:.1f} uF, {data['deck']['esr_ohm'] * 1e3:.1f} mohm: "
          f"{data['results']['ripple_at_the_simulated_point_pp_v']:.3f} V pp "
          f"({data['results']['ripple_at_the_simulated_point_percent_of_vin']:.2f} % of {data['vin_v']:.0f} V)")
    print(f"bank ESR for a {ESR_BUDGET_W:.1f} W budget: {data['esr_budget']['bank_esr_ceiling_ohm'] * 1e3:.2f} mohm")


if __name__ == "__main__":
    main()
