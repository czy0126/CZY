"""Price the CT burden resistor through a true cold start (SOURCE-05).

SOURCE-05 left the startup pulse open because the 8 ms cold-start deck does not
save ``V(ocd)``/``V(ocm)``, and re-running it as-is costs 2294 s and 13 GB.  It
does not have to be re-run: the deck saves ``I(Lr)``, and inside this model the
burden voltage is an algebraic function of the resonant current.

``Lct1`` = 2 uH sits in series with the tank, ``Lct2`` = 20 mH is the secondary,
``Kct`` = 0.9999, so the turns ratio is sqrt(20m/2u) = 100 and the ideal
transformer forces ``i_sec = i_pri / 100``.  With ``Rbur`` = 10 ohm the burden
voltage is ``R_b * |i_pri| / N`` = 0.1 V/A, which is why the rectifier never
clips: it is a current source, not a rectified voltage source.

That identity is checked rather than assumed.  The hotfault srprobe raw saves
``V(ocd)``, ``V(ocm)`` *and* ``I(Lr)``, so the transfer is measured there over
2 A to 97 A and the median (about 0.0995, i.e. 0.5 % under nominal) is applied
to the cold record.  The same transfer reproduces the steady 7-8 ms burden to
within a percent of the independently measured 125.7 mW in
``oc_burden_pulse.json``, which is the check that the method is not
self-fulfilling.

What is *not* claimed: this is a derived burden voltage, not a measured one.
A cold-start raw that saved ``V(ocd)``/``V(ocm)`` would be the direct
confirmation.  The rating ladder is read from the recorded R3 candidate screen
(``docs/D1_EXECUTION_KIT/r3_vendor_rating_screen.json``, PR 28: the 0805 is
rejected and a 2512 1.5 W part is the candidate), and the peak is a
microsecond pulse, so every "peak over rating" number here is a screening
ratio, not a pass/fail: the vendor single/repetitive pulse charts still have to
be applied to the real waveform and board temperature.

Usage:
    python tools/startup_burden_pulse.py --json design/v3/bom/startup_burden_pulse.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from ascii_raw_window import read_window

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON = ROOT / "design/v3/bom/startup_burden_pulse.json"
BURDEN_JSON = ROOT / "design/v3/bom/oc_burden_pulse.json"
# The active R3 candidate and its de-rating ladder live in one recorded screen
# (PR 28).  The rejected 0805 stays visible there as ``source_mpn`` so the
# two parts are never conflated.
R3_SCREEN = ROOT / "docs/D1_EXECUTION_KIT/r3_vendor_rating_screen.json"

PAIRED_RAW = ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.raw"
PAIRED_DECK = ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.cir"
COLD_RAW = ROOT / "sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.raw"
COLD_DECK = ROOT / "sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.cir"

# Windows of the paired raw used to calibrate the transfer: one pre-fault
# steady decade and one spanning the fault, so the check covers 2-97 A.
PAIRED_WINDOWS = ((150e-6, 175e-6), (205e-6, 216e-6))
# Below this current the diode drop dominates the ratio and the linear
# identity stops being a good description; the excluded energy is negligible.
LOAD_FLOOR_A = 2.0
COLD_WINDOW = (0.0, 8.0e-3)
PEAK_SLICE = (0.0, 2.0e-3)

LADDER = re.compile(
    r"^\s*Lct(1|2)\s+\S+\s+\S+\s+(\S+)\s*$"
    r"|^\s*Kct\s+\S+\s+\S+\s+(\S+)\s*$"
    r"|^\s*Rbur\s+\S+\s+\S+\s+(\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _round(value: float, digits: int = 6) -> float:
    return float(f"{value:.{digits}g}")


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _si(text: str) -> float:
    """SPICE suffix -> float (10m -> 0.01, 2u -> 2e-6, 0.9999 -> 0.9999)."""
    text = text.strip().lower()
    scale = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3,
             "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
    for suffix in ("meg", "t", "g", "k", "m", "u", "n", "p", "f"):
        if text.endswith(suffix) and len(text) > len(suffix):
            body = text[: -len(suffix)]
            try:
                return float(body) * scale[suffix]
            except ValueError:
                continue
    return float(text)


def ct_ladder(deck_text: str) -> dict:
    """The four elements that decide how the burden sees the tank current."""
    found: dict[str, float] = {}
    for match in LADDER.finditer(deck_text):
        if match.group(1):
            found[f"lct{match.group(1)}_h"] = _si(match.group(2))
        elif match.group(3):
            found["kct"] = _si(match.group(3))
        else:
            found["rbur_ohm"] = _si(match.group(4))
    missing = {"lct1_h", "lct2_h", "kct", "rbur_ohm"} - set(found)
    if missing:
        raise ValueError(f"deck is missing CT elements: {sorted(missing)}")
    found["turns_ratio"] = float(np.sqrt(found["lct2_h"] / found["lct1_h"]))
    found["nominal_v_per_a"] = found["rbur_ohm"] / found["turns_ratio"]
    return found


def transfer_ratio(raw: Path, windows: tuple[tuple[float, float], ...]) -> dict:
    """Measured V(burden)/|I(Lr)| on a record that saves both traces."""
    ratios = []
    for t0, t1 in windows:
        t, data = read_window(raw, ["V(ocd)", "V(ocm)", "I(Lr)"], t0, t1)
        volts = data["V(ocd)"] - data["V(ocm)"]
        amps = np.abs(data["I(Lr)"])
        keep = amps > LOAD_FLOOR_A
        if keep.sum() < 2:
            raise ValueError(f"{raw.name}: {t0:g}-{t1:g} s has no samples above {LOAD_FLOOR_A} A")
        ratios.append(volts[keep] / amps[keep])
    ratio = np.concatenate(ratios)
    return {
        "median_v_per_a": _round(float(np.median(ratio))),
        "p05_v_per_a": _round(float(np.percentile(ratio, 5))),
        "p95_v_per_a": _round(float(np.percentile(ratio, 95))),
        "samples": int(ratio.size),
        "windows_us": [[round(a * 1e6, 1), round(b * 1e6, 1)] for a, b in windows],
    }


def startup(raw: Path, t0: float, t1: float, transfer: float, r_ohm: float) -> dict:
    """Burden power derived from the saved resonant current over [t0, t1]."""
    t, data = read_window(raw, ["I(Lr)", "V(out)", "V(ss)"], t0, t1)
    return stats(t, data, transfer, r_ohm)


def candidate_rating() -> dict:
    """The active R3 candidate and the de-rating ladder, read from the screen."""
    screen = json.loads(R3_SCREEN.read_text(encoding="utf-8"))
    return {
        "mpn": screen["candidate_mpn"],
        "rated_power_w": float(screen["candidate_rating_power_w"]),
        "rated_at_c": 70.0,
        "eia_case": screen["candidate_eia_case"],
        "height_max_mm": float(screen["candidate_height_max_mm"]),
        "rejected_source_mpn": screen["source_mpn"],
        "rejected_source_power_w": float(screen["source_power_w"]),
        "derated_w": {name.replace("derated_power_at_", "").replace("_w", ""): float(value)
                      for name, value in screen.items() if name.startswith("derated_power_at_")},
        "screen": _relative(R3_SCREEN),
    }


def thresholds(rating: dict) -> dict[str, float]:
    """Absolute power levels whose crossing time is reported, in watts."""
    levels = {"quarter_of_p70": 0.25 * rating["rated_power_w"],
              "p70": rating["rated_power_w"],
              "four_times_p70": 4.0 * rating["rated_power_w"]}
    for name, watts in rating["derated_w"].items():
        levels[f"derated_at_{name}"] = watts
    return levels


def stats(t: np.ndarray, data: dict[str, np.ndarray], transfer: float, r_ohm: float,
          t0: float | None = None, t1: float | None = None,
          levels: dict[str, float] | None = None) -> dict:
    """Burden-power statistics over an optional sub-slice of an already-read record."""
    inside = np.ones(t.shape, dtype=bool)
    if t0 is not None:
        inside &= t >= t0
    if t1 is not None:
        inside &= t <= t1
    t = t[inside]
    data = {key: values[inside] for key, values in data.items()}
    t0 = float(t[0])
    t1 = float(t[-1])
    amps = np.abs(data["I(Lr)"])
    power = (transfer * amps) ** 2 / r_ohm
    peak = int(np.argmax(power))
    energy = float(np.trapezoid(power, t))
    dt = np.diff(t, prepend=t[0] - 5e-9)
    levels = levels or {}
    over = {f"above_{name}_us": _round(float(dt[power > watts].sum()) * 1e6, 4)
            for name, watts in levels.items()}
    return {
        "window_ms": [round(t0 * 1e3, 4), round(t1 * 1e3, 4)],
        "samples": int(t.size),
        "peak_w": _round(float(power[peak])),
        "t_peak_ms": _round(float(t[peak]) * 1e3),
        "peak_current_a": _round(float(amps[peak])),
        "vout_at_peak_v": _round(float(data["V(out)"][peak])),
        "energy_mj": _round(energy * 1e3),
        "mean_mw": _round(energy / float(t[-1] - t[0]) * 1e3),
        "duration_us": _round(float(t[-1] - t[0]) * 1e6, 4),
        "time_above": over,
        "end": {
            "vout_v": _round(float(data["V(out)"][-1])),
            "vss_v": _round(float(data["V(ss)"][-1])),
        },
    }


def steady_reference() -> dict:
    """The independently measured 48 V/120 A burden power this record must match."""
    data = json.loads(BURDEN_JSON.read_text(encoding="utf-8"))
    base = next(run for run in data["results"]["runs"] if run["run"] == "48v_base")
    return {"run": base["run"], "mean_w": float(base["pre_fault"]["mean_w"]),
            "source": _relative(BURDEN_JSON)}


def fault_reference() -> dict:
    data = json.loads(BURDEN_JSON.read_text(encoding="utf-8"))
    base = next(run for run in data["results"]["runs"] if run["run"] == "48v_base")["fault"]
    return {"peak_w": float(base["peak_w"]), "energy_mj": float(base["energy_mj"]),
            "equivalent_width_us": float(base["equivalent_width_us"])}


def build() -> dict:
    cold_text = COLD_DECK.read_text(encoding="utf-8")
    paired_text = PAIRED_DECK.read_text(encoding="utf-8")
    cold = ct_ladder(cold_text)
    paired = ct_ladder(paired_text)
    ladder_matches = all(cold[key] == paired[key] for key in
                         ("lct1_h", "lct2_h", "kct", "rbur_ohm"))

    measured = transfer_ratio(PAIRED_RAW, PAIRED_WINDOWS)
    transfer = measured["median_v_per_a"]
    r_ohm = cold["rbur_ohm"]

    rating = candidate_rating()
    levels = thresholds(rating)
    cold_t, cold_d = read_window(COLD_RAW, ["I(Lr)", "V(out)", "V(ss)"], *COLD_WINDOW)
    full = stats(cold_t, cold_d, transfer, r_ohm, levels=levels)
    slice2ms = stats(cold_t, cold_d, transfer, r_ohm, *PEAK_SLICE, levels=levels)
    reference = steady_reference()
    steady_derived = stats(cold_t, cold_d, transfer, r_ohm, 7e-3, 8e-3)["mean_mw"] / 1e3
    fault = fault_reference()

    deviation = abs(steady_derived - reference["mean_w"]) / reference["mean_w"]
    spread = (measured["p95_v_per_a"] - measured["p05_v_per_a"]) / transfer
    checks = {
        "the_ct_ladder_is_identical_in_both_decks": ladder_matches,
        "the_transfer_is_linear_over_the_measured_range": spread < 0.05,
        "the_derived_steady_power_reproduces_the_measured_burden": deviation < 0.03,
        "the_rating_is_the_recorded_candidate_not_the_rejected_0805":
            rating["mpn"] != rating["rejected_source_mpn"],
        "the_peak_is_reported_as_a_selection_input_not_a_rating": True,
    }
    return {
        "kind": "ct_burden_cold_start",
        "evidence_level": "DERIVED_FROM_IDEAL_CT_TRANSFER / BURDEN_VOLTAGE_NOT_SAVED",
        "source": {
            "cold_deck": _relative(COLD_DECK),
            "cold_raw": _relative(COLD_RAW),
            "paired_deck": _relative(PAIRED_DECK),
            "paired_raw": _relative(PAIRED_RAW),
        },
        "results": {
            "ct": {
                **{k: _round(v) for k, v in cold.items()},
                "identity": "i_sec = i_pri / N and V_burden = Rbur * |i_sec|, so the "
                            "rectifier is a current source and never clips",
            },
            "transfer": {**measured, "used_v_per_a": transfer},
            "startup": full,
            "peak_slice": slice2ms,
            "steady_cross_check": {
                "derived_7_to_8ms_w": _round(steady_derived),
                "measured_48v_120a_w": _round(reference["mean_w"]),
                "deviation_pct": _round(deviation * 100.0, 4),
                "reference": reference["source"],
            },
            "rating": {
                **rating,
                "peak_over_p70": _round(full["peak_w"] / rating["rated_power_w"], 5),
                "peak_over_derated": {
                    name: _round(full["peak_w"] / watts, 5)
                    for name, watts in rating["derated_w"].items()},
                "energy_over_p70_seconds": _round(full["energy_mj"] / 1e3 / rating["rated_power_w"]),
                "note": ("the peak is a pulse; dividing it by a continuous or de-rated "
                         "rating is a screening ratio, not a pass/fail"),
            },
            "fault_contrast": {
                "fault_peak_w": fault["peak_w"],
                "fault_energy_mj": fault["energy_mj"],
                "fault_equivalent_width_us": fault["equivalent_width_us"],
                "startup_peak_w": full["peak_w"],
                "startup_energy_mj": full["energy_mj"],
                "energy_ratio_startup_over_fault": _round(full["energy_mj"] / fault["energy_mj"]),
            },
            "limits": [
                "the cold-start deck does not save V(ocd)/V(ocm); the burden voltage here "
                "is derived from the saved I(Lr) through the ideal-transformer identity, "
                "not measured on this deck",
                "the transfer is measured on the hotfault srprobe raw over 2-97 A "
                f"(median {transfer:.4f} V/A against a nominal {cold['nominal_v_per_a']:.4f}); "
                "a cold-start raw that saved the burden nodes would confirm it",
                "below 2 A the diode drop dominates and the identity is not used; the "
                "excluded energy sits in the first ~0.4 ms where the input has not ramped",
                "the CT model is ideal (Kct = 0.9999, no saturation, no magnetising "
                "current), so core loss and saturation are absent from this figure",
                "the rating ladder is the candidate's simple linear ambient de-rating "
                "(Vishay p6, 70 C to 155 C); the ambient is not measured and the curve is "
                "not a junction-temperature measurement",
                "the peak is a microsecond-scale pulse and the time above each level is a "
                "crossing time, not an I^2t or a wave-shape convolution; the vendor "
                "single/repetitive pulse charts must be applied to the real waveform before "
                "any pass/fail",
                "the rejected 0805 (source_mpn) is kept only as the reason the rating "
                "moved; nothing here re-qualifies it",
                "the cold-start deck runs with 10 ns max step; it answers 'does the "
                "converter traverse start-up', not a 1 ns ledger question",
            ],
        },
        "checks": {"ok": all(checks.values()), **checks},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args(argv)
    payload = build()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    run = payload["results"]["startup"]
    print(f"wrote {args.json}")
    print(f"  peak {run['peak_w']:.4f} W at {run['t_peak_ms']:.4f} ms "
          f"(I {run['peak_current_a']:.2f} A, Vout {run['vout_at_peak_v']:.3f} V)")
    print(f"  energy {run['energy_mj']:.6f} mJ over {run['duration_us']:.0f} us, "
          f"mean {run['mean_mw']:.2f} mW")
    print("  above rating: " + ", ".join(f"{k} {v:.1f} us" for k, v in run["time_above"].items()))
    print(f"  checks ok: {payload['checks']['ok']}")
    return 0 if payload["checks"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
