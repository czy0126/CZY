"""Measure the CT burden through the true cold start (SOURCE-05).

The parent cold-start deck does not save the burden nodes, so
``tools/startup_burden_pulse.py`` derives P(t) from ``I(Lr)`` through the
ideal-transformer identity and validates that derivation against a steady-state
measurement.  This record replaces the derivation, for the same 8 ms window,
with the measured waveform from the probe deck -- which differs from its parent
only by three ``.save`` additions.

The value of the record is the *comparison*: if the two disagree by more than a
few percent, the derived record (and the transfer it rests on) is not what it
claims to be.  Agreement does not upgrade either file into a hardware rating;
the rating ladder is still a screening ratio.

Usage:
    python tools/startup_burden_direct.py --json design/v3/bom/startup_burden_direct.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import make_startup_burden_probe as probe
import startup_burden_pulse as derived
from ascii_raw_window import read_window

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON = ROOT / "design/v3/bom/startup_burden_direct.json"
DERIVED_JSON = ROOT / "design/v3/bom/startup_burden_pulse.json"
RAW = ROOT / "sim/v3/sr_tank_dual_v33_cold_vin48_i120_target_burden.raw"
DECK = ROOT / "sim/v3/sr_tank_dual_v33_cold_vin48_i120_target_burden.cir"
PARENT_DECK = probe.SOURCE
WINDOW = (0.0, 8.0e-3)
HEAD_SLICE_S = 0.2e-3
COLUMNS = ["V(ocd)", "V(ocm)", "I(Rbur)", "I(Lr)", "V(out)", "V(ss)"]
DECLARED_STOP_S = 8.0e-3


def _round(value: float, digits: int = 6) -> float:
    return float(f"{value:.{digits}g}")


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def waveform_stats(t: np.ndarray, data: dict[str, np.ndarray], r_ohm: float,
                   levels: dict[str, float]) -> dict:
    """Burden statistics from the measured burden voltage.

    The burden voltage is not strictly non-negative: the deck's bridge is four
    ``DSCH`` diodes with ``Cjo=20p``, so at each secondary-current zero crossing
    their junction charge briefly pulls the resistor the other way.  The
    excursion is recorded with its energy share, because what matters is that
    it carries no meaningful energy -- a negative *voltage* on a resistor still
    dissipates.
    """
    volts = data["V(ocd)"] - data["V(ocm)"]
    power = volts * volts / r_ohm
    peak = int(np.argmax(power))
    energy = float(np.trapezoid(power, t))
    negative_energy = float(np.trapezoid(np.where(volts < 0.0, power, 0.0), t))
    dt = np.diff(t, prepend=t[0] - 5e-9)
    duration = float(t[-1] - t[0])
    return {
        "window_ms": [round(float(t[0]) * 1e3, 4), round(float(t[-1]) * 1e3, 4)],
        "samples": int(t.size),
        "peak_w": _round(float(power[peak])),
        "t_peak_ms": _round(float(t[peak]) * 1e3),
        "peak_voltage_v": _round(float(volts[peak])),
        "peak_current_a": _round(float(data["I(Rbur)"][peak])),
        "vout_at_peak_v": _round(float(data["V(out)"][peak])),
        "energy_mj": _round(energy * 1e3),
        "mean_mw": _round(energy / duration * 1e3),
        "duration_us": _round(duration * 1e6, 4),
        "voltage_min_v": _round(float(volts.min())),
        "voltage_min_time_ms": _round(float(t[int(np.argmin(volts))]) * 1e3),
        "negative_energy_share": _round(negative_energy / energy if energy else 0.0, 10),
        "negative_samples": int((volts < 0.0).sum()),
        "time_above": {f"above_{name}_us": _round(float(dt[power > watts].sum()) * 1e6, 4)
                       for name, watts in levels.items()},
        "end": {"vout_v": _round(float(data["V(out)"][-1])),
                "vss_v": _round(float(data["V(ss)"][-1]))},
    }


def masked(t: np.ndarray, data: dict[str, np.ndarray], t0: float,
           t1: float) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    keep = (t >= t0) & (t <= t1)
    return t[keep], {key: values[keep] for key, values in data.items()}


def derived_reference() -> dict:
    data = json.loads(DERIVED_JSON.read_text(encoding="utf-8"))
    startup = data["results"]["startup"]
    return {"peak_w": float(startup["peak_w"]), "t_peak_ms": float(startup["t_peak_ms"]),
            "energy_mj": float(startup["energy_mj"]), "source": _relative(DERIVED_JSON)}


def comparison(direct: dict, reference: dict) -> dict:
    """How far the measured waveform is from the derived one, element by element."""
    return {
        "peak_w": reference["peak_w"],
        "peak_deviation_pct": _round((direct["peak_w"] - reference["peak_w"])
                                     / reference["peak_w"] * 100.0, 4),
        "t_peak_shift_ms": _round(direct["t_peak_ms"] - reference["t_peak_ms"], 6),
        "energy_mj": reference["energy_mj"],
        "energy_deviation_pct": _round((direct["energy_mj"] - reference["energy_mj"])
                                       / reference["energy_mj"] * 100.0, 4),
        "reference": reference["source"],
    }


def build(raw: Path = RAW) -> dict:
    deck_text = DECK.read_text(encoding="utf-8")
    parent_text = PARENT_DECK.read_text(encoding="utf-8")
    ladder = derived.ct_ladder(deck_text)
    r_ohm = ladder["rbur_ohm"]
    rating = derived.candidate_rating()
    levels = derived.thresholds(rating)

    t, data = read_window(raw, COLUMNS, *WINDOW)
    if t.size < 2:
        raise ValueError(f"{raw.name}: window contains too few points")
    direct = waveform_stats(t, data, r_ohm, levels)
    head = waveform_stats(*masked(t, data, 0.0, HEAD_SLICE_S), r_ohm, levels)
    reference = derived_reference()
    diff = comparison(direct, reference)

    # The model forces i = v/R across the burden; a mismatch would mean the
    # saved node pair is not the resistor the power is priced across.
    current = data["I(Rbur)"]
    volts = data["V(ocd)"] - data["V(ocm)"]
    keep = np.abs(volts) > 1e-9
    current_dev = float(np.max(np.abs(current[keep] - volts[keep] / r_ohm) / np.abs(current[keep])))

    reached = float(t[-1]) >= DECLARED_STOP_S - 1e-9
    checks = {
        "the_raw_reached_the_declared_saved_stop": reached,
        # Not "the voltage never reverses": the deck's bridge has Cjo=20p per
        # diode, so a millivolt-scale reversal at current zero is the model, not
        # a defect.  The invariant is that the reversed intervals carry no
        # meaningful share of the energy -- 0.1 %, the same order as the
        # derived-vs-measured energy agreement, so a reversed interval can never
        # be what makes the two records agree.
        "the_reversed_excursion_carries_no_meaningful_energy":
            direct["negative_energy_share"] < 1e-3,
        "the_saved_current_is_the_saved_voltage_over_rbur": current_dev < 5e-3,
        "the_probe_deck_differs_from_its_parent_only_by_the_saved_probes":
            deck_text == probe.build(parent_text),
        "the_direct_peak_reproduces_the_derived_peak":
            abs(diff["peak_deviation_pct"]) < 3.0,
        "the_direct_energy_reproduces_the_derived_energy":
            abs(diff["energy_deviation_pct"]) < 3.0,
    }
    return {
        "kind": "ct_burden_cold_start_measured",
        "evidence_level": "SIMULATED_ONLY / BURDEN_MEASURED_NOT_RATED",
        "source": {"deck": _relative(DECK), "parent_deck": _relative(PARENT_DECK),
                   "raw": _relative(raw)},
        "results": {
            "burden_ohm": _round(r_ohm),
            "measured": direct,
            "head_slice": head,
            "direct_vs_derived": diff,
            "current_identity_max_deviation": _round(current_dev, 8),
            "rating": {
                "mpn": rating["mpn"],
                "rated_power_w": rating["rated_power_w"],
                "peak_over_p70": _round(direct["peak_w"] / rating["rated_power_w"], 5),
                "peak_over_derated": {name: _round(direct["peak_w"] / watts, 5)
                                      for name, watts in rating["derated_w"].items()},
                "note": "screening ratios against a continuous/de-rated rating, not a pulse rating",
            },
            "limits": [
                "the deck runs the ideal CT model (Kct = 0.9999, no saturation, no core "
                "loss); the burden voltage is measured, the transformer behind it is not",
                "the probe deck is the parent plus three .save entries; adding probes does "
                "not change the solution, but it is a derived deck, not the frozen parent",
                "the raw is a local artefact and is not in Git; regenerate it with "
                "tools/make_startup_burden_probe.py and an LTspice run",
                "agreement between derived and measured does not make either record a "
                "pulse rating: the vendor single/repetitive pulse charts still apply",
                "the burden voltage reverses by roughly a millivolt at each current zero "
                "crossing because the deck's bridge diodes carry Cjo=20 pF; the record "
                "reports the excursion and its energy share instead of pretending the "
                "bridge is a perfect rectifier",
            ],
        },
        "checks": {"ok": all(checks.values()), **checks},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--raw", type=Path, default=RAW)
    args = parser.parse_args(argv)
    if not args.raw.is_file():
        raise SystemExit(f"{args.raw} not found: run the probe deck first")
    payload = build(args.raw)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    measured = payload["results"]["measured"]
    diff = payload["results"]["direct_vs_derived"]
    print(f"wrote {args.json}")
    print(f"  measured peak {measured['peak_w']:.4f} W at {measured['t_peak_ms']:.4f} ms "
          f"(derived {diff['peak_w']:.4f} W, {diff['peak_deviation_pct']:+.3f} %)")
    print(f"  measured energy {measured['energy_mj']:.6f} mJ "
          f"(derived {diff['energy_mj']:.6f} mJ, {diff['energy_deviation_pct']:+.3f} %)")
    print(f"  checks ok: {payload['checks']['ok']}")
    return 0 if payload["checks"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
