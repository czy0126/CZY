"""Measure the transformer core flux from the saved winding voltages.

The magnetic package has until now quoted the transformer flux from an ideal
symmetric square wave: ``Delta B = V*t_on/(N*Ae)``.  That formula cannot see a
volt-second imbalance, and the roadmap asks for "各绕组实际电压积分及偏磁核算".
The deck saves the two secondary winding voltages of T1 and T4 (``V(a1)``,
``V(b1)``, ``V(a4)``, ``V(b4)`` against ``V(out)``), and each secondary is one
turn on the same core, so

    B(t) = (1/(N_sec*Ae)) * integral v_sec dt,  N_sec = 1

gives the flux directly.  Two secondary halves share a core, so their integrals
are also a consistency check on the method.

What this can and cannot say:

* It measures the flux *swing* and the period-to-period volt-second imbalance
  (the DC-bias drift).  The flux reference is arbitrary -- the raw does not save
  the magnetizing current, so the absolute operating point is unknown.
* The winding voltage includes the leakage and winding-resistance terms.  With
  k = 0.999 that leakage flux is bounded here and reported, not ignored.
* The deck's transformer is linear: no B-H saturation, no core loss.  This is
  the applied volt-seconds, not evidence about a saturating core.

Usage:
    python tools/transformer_flux.py --raw sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw \
        --json design/v3/magnetics/transformer_flux_100a.json
    python tools/transformer_flux.py --fault-raw sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.raw
        # adds the 48 V fault window; only that deck covers its declared end
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ascii_raw_window import read_window
from current_manifest import deck_timing
from magnetics_design import CORE, design_report

ROOT = Path(__file__).resolve().parent.parent
DECK = "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"
# The 48 V fault deck is the only hot-fault run that reaches its declared end
# (the 50 V base collapses at 296.929 us).  It saves T1's two secondary halves
# but not T4's, so the fault window measures T1 only.
FAULT_DECK = "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.cir"
FAULT_PROBED = (1,)
# Only T1 and T4 save their secondary voltages; T2/T3 have identical constants
# in the deck, so they are represented, not measured.
PROBED = (1, 4)


def _trapezoid(y: np.ndarray, x: np.ndarray) -> float:
    return float(np.trapezoid(y, x))


def half_cycles(t: np.ndarray, v: np.ndarray) -> list[dict[str, float]]:
    """Complete half-cycles, each bounded by a sign change on both ends.

    The first and last segments of a window start or end mid-half-cycle, so
    they are dropped: an incomplete half-cycle would be read as a smaller
    flux swing.
    """
    sign = np.sign(v)
    changes = np.where(sign[:-1] * sign[1:] < 0)[0]
    segments: list[dict[str, float]] = []
    for a, b in zip(changes[:-1], changes[1:]):
        volt_seconds = _trapezoid(v[a:b + 1], t[a:b + 1])
        segments.append({
            "t_start_s": float(t[a]),
            "t_end_s": float(t[b]),
            "sign": 1.0 if volt_seconds > 0 else -1.0,
            "volt_seconds": volt_seconds,
        })
    return segments


def flux_report(t: np.ndarray, v: np.ndarray, ae_m2: float) -> dict[str, object]:
    """Flux swing, imbalance and drift for one winding voltage."""
    segments = half_cycles(t, v)
    if len(segments) < 4:
        raise ValueError(f"only {len(segments)} complete half-cycles")
    swings = [s["volt_seconds"] / ae_m2 for s in segments]
    positive = [x for x in swings if x > 0]
    negative = [-x for x in swings if x < 0]
    if not positive or not negative:
        raise ValueError("the winding voltage never changes sign")
    mean_pos = float(np.mean(positive))
    mean_neg = float(np.mean(negative))
    # One half-cycle moves the core across the whole excursion, so the
    # positive and negative halves are two measurements of the *same*
    # peak-to-peak swing, not two halves to be added.
    peak_to_peak = (mean_pos + mean_neg) / 2.0
    nets = [swings[i] + swings[i + 1] for i in range(0, len(swings) - 1, 2)]
    net = float(np.sum(nets))
    return {
        "half_cycles": len(segments),
        "positive_halves": len(positive),
        "negative_halves": len(negative),
        "delta_b_positive_half_t": mean_pos,
        "delta_b_negative_half_t": mean_neg,
        "delta_b_half_min_t": min(min(positive), min(negative)),
        "delta_b_half_max_t": max(max(positive), max(negative)),
        "peak_to_peak_t": peak_to_peak,
        "ac_amplitude_t": peak_to_peak / 2.0,
        "period_net_t": nets,
        "max_abs_period_net_t": max(abs(x) for x in nets),
        "cumulative_net_t": net,
        "cumulative_abs_t": float(np.sum(np.abs(nets))),
        "signs_alternate": all(
            segments[i]["sign"] != segments[i + 1]["sign"] for i in range(len(segments) - 1)),
    }


def deck_constants(deck: Path = ROOT / DECK) -> dict[str, float]:
    """Transformer magnetizing inductance and coupling factor from the deck."""
    text = deck.read_text(encoding="utf-8")
    lp = float(re.search(r"LP=([0-9.]+)u", text).group(1)) * 1e-6
    k = float(re.search(r"^K1\s+Lp1\s+Lsa1\s+Lsb1\s+([0-9.]+)", text, re.M).group(1))
    return {"lp_h": lp, "k": k, "lsa_h": lp / 9.0,
            "leakage_h": lp / 9.0 * (1.0 - k * k)}


def report(raw: str | Path) -> dict[str, object]:
    raw = Path(raw)
    timing = deck_timing(DECK)
    names = ["V(out)"]
    for n in PROBED:
        names.extend([f"V(a{n})", f"V(b{n})"])
    t, data = read_window(raw, names, 0.0, None)

    ae = float(CORE["Ae_m2"])
    bsat = float(CORE["Bsat_T"])
    const = deck_constants()
    windings: dict[str, dict[str, object]] = {}
    for n in PROBED:
        halves = {
            "A": flux_report(t, data["V(out)"] - data[f"V(a{n})"], ae),
            "B": flux_report(t, data[f"V(b{n})"] - data["V(out)"], ae),
        }
        # Compare only the alignment-free quantities.  Each cumulative drift is
        # referenced to that winding's own first sign change, and near the dead
        # time the two halves cross zero a few tens of ns apart, so their
        # cumulative sums are not the same measurement even on one core.
        agree = max(
            abs(halves["A"][key] - halves["B"][key])
            for key in ("peak_to_peak_t", "delta_b_positive_half_t",
                        "delta_b_negative_half_t"))
        windings[f"T{n}"] = {**halves, "winding_agreement_t": agree}

    first = windings[f"T{PROBED[0]}"]["A"]
    # The leakage flux that rides on the winding voltage: lambda_leak = L_leak*i.
    # i is not saved as a direct peak here, so use the measured secondary RMS
    # upper bound from the operating point instead of inventing a current.
    op = json.loads((ROOT / "design/v3/magnetics/operating_point_100a.json")
                    .read_text(encoding="utf-8"))
    i_pair = max(v["irms_pair_a"] for k, v in op.items()
                 if k.startswith("pair") and isinstance(v, dict))
    leakage_flux = const["leakage_h"] * i_pair / ae

    analytic = design_report()["flux"]
    stat = raw.stat()
    return {
        "status": "MEASUREMENT_ON_APPLIED_VOLT_SECONDS_NOT_A_SATURATION_RATING",
        "raw": {"path": str(raw), "bytes": stat.st_size, "mtime": stat.st_mtime},
        "deck": DECK,
        "timing": timing,
        "core": {"ae_m2": ae, "amin_m2": float(CORE["Amin_m2"]), "bsat_t": bsat},
        "method": "B(t) = (1/(N_sec*Ae)) * integral v_sec dt; each secondary half "
                  "is one turn on the same core; complete half-cycles only",
        "windings": windings,
        "results": {
            "ac_amplitude_t": first["ac_amplitude_t"],
            "ac_amplitude_frac_bsat": first["ac_amplitude_t"] / bsat,
            "peak_to_peak_t": first["peak_to_peak_t"],
            "peak_to_peak_frac_bsat": first["peak_to_peak_t"] / bsat,
            "max_abs_period_net_t": first["max_abs_period_net_t"],
            "cumulative_net_t": first["cumulative_net_t"],
            "cumulative_abs_t": first["cumulative_abs_t"],
            "drift_bound_frac_bsat": first["cumulative_abs_t"] / bsat,
            "analytic_delta_b_48v_t": analytic["48v_delta_b_t"],
            "measured_over_analytic": first["peak_to_peak_t"] / analytic["48v_delta_b_t"],
            "leakage_flux_bound_t": leakage_flux,
            "leakage_frac_of_swing": leakage_flux / first["peak_to_peak_t"],
        },
        "caveats": [
            "The flux reference is arbitrary: the raw saves no magnetizing current, "
            "so only the swing and the period-to-period drift are measured.  "
            "cumulative_net_t is the drift accumulated from the start of this 120 us "
            "window, not the converter's absolute flux offset; cumulative_abs_t is "
            "the worst excursion if every period's imbalance had the same sign.",
            f"The winding voltage includes L_leak*i (L_leak = {const['leakage_h'] * 1e9:.2f} nH "
            f"at k = {const['k']}); with the largest measured pair RMS the bound is "
            f"{leakage_flux * 1e3:.2f} mT, which is leakage flux, not core flux.",
            "The deck's transformer is linear (no B-H curve, no core loss), so this is "
            "applied volt-seconds, not evidence about a saturating core.",
            "T2/T3 do not save their secondary voltages; the deck gives all four cores "
            "identical constants, so they are represented by T1/T4, not measured.",
            "The raw is the frozen 1 ms deck (4 mF output bank); the physical build uses "
            "7.05 mF, which does not change the volt-second integral.",
        ],
        "checks": {
            "raw_is_present": raw.is_file(),
            "every_required_probe_is_saved": True,
            "at_least_four_complete_half_cycles": first["half_cycles"] >= 4,
            "the_drive_alternates_every_half_cycle": first["signs_alternate"],
        },
    }


def fault_instant(deck: Path) -> dict[str, float]:
    """Locate the injected fault on the saved time axis, from the deck text.

    The hot-fault deck closes a switch through a PWL control; the fault instant
    is where that ramp crosses the switch threshold, not the first PWL point.
    ``.tran Tstep Tstop Tstart Tmaxstep`` puts the raw's t = 0 at ``Tstart``.
    """
    text = deck.read_text(encoding="utf-8")
    tstart_us = float(re.search(r"^\.tran\s+\S+\s+\S+\s+([0-9.]+)u", text, re.M).group(1))
    pwl = re.search(r"^Vfltctl_hot\s+\S+\s+\S+\s+PWL\(([^)]*)\)", text, re.M).group(1)
    points = [(float(a), float(b)) for a, b in re.findall(r"([0-9.]+)u\s+([0-9.]+)", pwl)]
    vt = float(re.search(r"HOTFLT\s+SW\([^)]*Vt=([0-9.]+)", text).group(1))
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if v1 != v0 and (v0 - vt) * (v1 - vt) <= 0:
            t_abs = t0 + (vt - v0) / (v1 - v0) * (t1 - t0)
            return {"absolute_us": t_abs, "saved_us": t_abs - tstart_us,
                    "tstart_us": tstart_us, "switch_threshold_v": vt}
    raise ValueError("the fault control never crosses the switch threshold")


def fault_window(t: np.ndarray, v: np.ndarray, ae_m2: float,
                 t_fault_s: float) -> dict[str, object]:
    """Flux swing before the fault, and the residual volt-seconds after it.

    Before the fault the drive still alternates, so the existing half-cycle
    arithmetic applies.  After it the controller trips and the bridge stops;
    each secondary half then sits against its SR, so the two integrals are no
    longer two views of the same core flux.  What remains is an *upper bound*
    on any flux change in that segment, not a measurement of it.
    """
    i = int(np.searchsorted(t, t_fault_s))
    if i < 4 or len(t) - i < 4:
        raise ValueError(f"the fault at {t_fault_s * 1e6:.2f} us leaves no room on both sides")
    pre = flux_report(t[:i], v[:i], ae_m2)
    residual = _trapezoid(v[i:], t[i:]) / ae_m2
    # |v| is not reported for the fault segment: it rings around zero there, so
    # its integral would read as hundreds of mT of "flux" that never existed.
    return {"pre_fault": pre, "fault_segment_net_t": residual}


def fault_report(raw: str | Path, deck: str = FAULT_DECK) -> dict[str, object]:
    raw = Path(raw)
    fault = fault_instant(ROOT / deck)
    t, data = read_window(raw, ["V(out)", "V(a1)", "V(b1)"], 0.0, None)
    ae = float(CORE["Ae_m2"])
    bsat = float(CORE["Bsat_T"])
    halves: dict[str, dict[str, object]] = {}
    for n in FAULT_PROBED:
        halves[f"T{n}"] = {
            "A": fault_window(t, data["V(out)"] - data[f"V(a{n})"], ae, fault["saved_us"] * 1e-6),
            "B": fault_window(t, data[f"V(b{n})"] - data["V(out)"], ae, fault["saved_us"] * 1e-6),
        }
    first = halves[f"T{FAULT_PROBED[0]}"]
    agree = max(
        abs(first["A"]["pre_fault"][key] - first["B"]["pre_fault"][key])
        for key in ("peak_to_peak_t", "delta_b_positive_half_t",
                    "delta_b_negative_half_t"))
    bound = max(abs(first[w]["fault_segment_net_t"]) for w in ("A", "B"))
    stat = raw.stat()
    return {
        "status": "APPLIED_VOLT_SECONDS_IN_THE_48V_FAULT_WINDOW_NOT_A_SATURATION_TEST",
        "raw": {"path": str(raw), "bytes": stat.st_size, "mtime": stat.st_mtime},
        "deck": deck,
        "fault": {**fault,
                  "source": "Vfltctl_hot PWL crossing of the HOTFLT Vt, minus the .tran Tstart"},
        "core": {"ae_m2": ae, "amin_m2": float(CORE["Amin_m2"]), "bsat_t": bsat},
        "windings": halves,
        "results": {
            "pre_fault_peak_to_peak_t": first["A"]["pre_fault"]["peak_to_peak_t"],
            "pre_fault_ac_amplitude_t": first["A"]["pre_fault"]["ac_amplitude_t"],
            "pre_fault_peak_to_peak_frac_bsat": (
                first["A"]["pre_fault"]["peak_to_peak_t"] / bsat),
            "pre_fault_ac_amplitude_frac_bsat": (
                first["A"]["pre_fault"]["ac_amplitude_t"] / bsat),
            "pre_fault_max_abs_period_net_t": max(
                first[w]["pre_fault"]["max_abs_period_net_t"] for w in ("A", "B")),
            "winding_agreement_pre_fault_t": agree,
            "fault_segment_net_bound_t": bound,
            "fault_segment_net_bound_frac_bsat": bound / bsat,
        },
        "caveats": [
            "Pre-fault is measured; the fault segment is not.  After the OC trip "
            "the bridge stops and each half sits against its SR, so the two "
            "winding integrals stop agreeing and the reported bound is the "
            "larger of them, not a flux reading.",
            "This is the 48 V / 120 A hot-fault deck, not the 100 A operating "
            "point; the duty differs slightly, so its swing is not the "
            "transformer_flux_100a.json number.",
            "The deck's transformer is linear (no B-H curve), and the raw starts "
            "with an arbitrary flux reference; only the swing and the "
            "window-referenced integral are measured.",
            "T4/T2/T3 are not saved in the fault deck, so the fault window "
            "measures T1; the four cores are identical in the deck.",
            "The 50 V base hot-fault run collapses at 296.929 us, so only the "
            "48 V window covers its declared duration.",
        ],
        "checks": {
            "raw_is_present": raw.is_file(),
            "the_fault_instant_is_inside_the_saved_window": bool(
                0.0 < fault["saved_us"] * 1e-6 < t[-1]),
            "pre_fault_drive_alternates": all(
                first[w]["pre_fault"]["signs_alternate"] for w in ("A", "B")),
            "pre_fault_has_enough_half_cycles": first["A"]["pre_fault"]["half_cycles"] >= 20,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path,
                    default=ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw")
    ap.add_argument("--json", type=Path,
                    default=ROOT / "design/v3/magnetics/transformer_flux_100a.json")
    ap.add_argument("--fault-raw", type=Path, default=None,
                    help="hot-fault raw; when given, also writes --fault-json")
    ap.add_argument("--fault-json", type=Path,
                    default=ROOT / "design/v3/magnetics/transformer_flux_fault_48v.json")
    args = ap.parse_args()
    data = report(args.raw)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    r = data["results"]
    print(args.json)
    print(f"dB pp {r['peak_to_peak_t'] * 1e3:.2f} mT  Bac {r['ac_amplitude_t'] * 1e3:.2f} mT  "
          f"{r['ac_amplitude_frac_bsat'] * 100:.1f} % Bsat")
    print(f"per-period net |max| {r['max_abs_period_net_t'] * 1e3:.3f} mT  "
          f"cumulative {r['cumulative_net_t'] * 1e3:+.3f} mT  "
          f"sum|net| {r['cumulative_abs_t'] * 1e3:.3f} mT")
    print(f"measured/analytic {r['measured_over_analytic']:.4f}  "
          f"leakage bound {r['leakage_flux_bound_t'] * 1e3:.2f} mT")

    if args.fault_raw is not None:
        fault = fault_report(args.fault_raw)
        args.fault_json.write_text(
            json.dumps(fault, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        f = fault["results"]
        print(args.fault_json)
        print(f"fault at {fault['fault']['saved_us']:.2f} us (saved axis); "
              f"pre-fault pp {f['pre_fault_peak_to_peak_t'] * 1e3:.2f} mT "
              f"({f['pre_fault_peak_to_peak_frac_bsat'] * 100:.1f} % Bsat pp), "
              f"amplitude {f['pre_fault_ac_amplitude_t'] * 1e3:.2f} mT "
              f"({f['pre_fault_ac_amplitude_frac_bsat'] * 100:.1f} % Bsat)")
        print(f"fault-segment net bound {f['fault_segment_net_bound_t'] * 1e3:.2f} mT "
              f"({f['fault_segment_net_bound_frac_bsat'] * 100:.2f} % Bsat)")


if __name__ == "__main__":
    main()
