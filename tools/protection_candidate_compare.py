"""Compare a PROT-02 gate-inhibit candidate with its published fault record.

Both raws share the same saved axis and the same fault branch, so the only
difference is the appended protection block.  The base deck defaults to the
candidate's declared parent: the 48 V eight-SR probe deck, or the 50 V
``cshunt=1 fF`` child, because the 50 V base itself still stalls at 296.929 us.  Every physical number is taken
over the same window (fault engage to the shorter record's end); a candidate
that stops early is reported as a prefix, never silently compared over a
shorter span.

The report separates two questions that are easy to blur:

* did the latch assert and hold every gate low (``results.gates``)?
* did that reduce the measured stress relative to the base (``results.relief``)?

Neither is a hardware safety proof.  The clamp is an ideal 0.05 ohm switch, the
latch is a behavioural integrator, and there is no SOA, thermal, comparator
noise or gate-loop inductance.  Restart order is checked only in a logic-level
sub-circuit (``restart_check``), never in the power stage; that deck is where
the arming latch gains its UVLO reset.

Usage:
    python tools/protection_candidate_compare.py \
        --case prot_b_fast10u_1p8v \
        --base-raw sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.raw \
        --candidate-raw sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe_prot_b_fast10u_1p8v.raw \
        --uvlo-raw sim/v3/prot_latch_uvlo_check.raw \
        --json design/v3/power_priority/protection_candidate_48v_120a_prot_b.json \
        --uvlo-json design/v3/power_priority/protection_uvlo_check.json

    # sub-circuit checks alone (no candidate comparison):
    python tools/protection_candidate_compare.py \
        --restart-raw sim/v3/prot_latch_restart_check.raw \
        --restart-json design/v3/power_priority/protection_restart_check.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

import make_protection_candidates as make
from analyze_v3_transient import first_cross, i2t, low_runs, mean_window
from ascii_raw_window import last_time, read_window
from hot_fault_metrics import saved_fault_window, saved_stop_s

ROOT = Path(__file__).resolve().parent.parent
PAIRS = (1, 2, 3, 4)
SIDES = ("a", "b")
GATE_ON_V = 2.0
GATE_OFF_V = 1.0
GATE_OFF_DEBOUNCE_S = 1e-6
PRE_FAULT_US = 35.0
TRIGGER_LATCH_V = 0.5
PRE_FAULT_MATCH_MV = 1.0
PROT_LINE = re.compile(
    r"^Bprot\s+\S+\s+\S+\s+I=.*?if\((V\([^)]*\))>([0-9.]+),-\(1-V\(prot\)\)",
    re.M,
)


def device_names(pair: int, side: str) -> dict[str, str]:
    suffix = f"{pair}{side.upper()}"
    return {
        "gate": f"V(g{side}{pair})",
        "drain": f"V({side}{pair})",
        "sense": f"I(VS{side}{pair})",
        "key": f"{pair}{side}",
    }


def base_names() -> list[str]:
    names = ["V(oc)", "V(ocd)", "V(out)", "V(ss)", "I(Lr)", "V(sw)", "V(ocm)"]
    for pair in PAIRS:
        for side in SIDES:
            dev = device_names(pair, side)
            names.extend((dev["gate"], dev["drain"], dev["sense"]))
    return names


def candidate_names(trigger_probe: str, arming: bool = True) -> list[str]:
    names = base_names() + ["V(prot)", "V(inhib)", "V(gh)", "V(gl)"]
    if arming:
        names.append("V(arm)")
    if "ocdf" in trigger_probe:
        names.append("V(ocdf)")
    return names


def trigger_from_deck(deck_text: str) -> tuple[str, str, float]:
    """(probe, reference, threshold) parsed from the candidate's Bprot line."""
    hit = PROT_LINE.search(deck_text)
    if not hit:
        raise ValueError("deck has no Bprot trigger with a latch set term")
    inner = hit.group(1)[2:-1]
    parts = [part.strip() for part in inner.split(",")]
    probe = f"V({parts[0]})"
    reference = "0" if len(parts) == 1 else f"V({parts[1]})"
    return probe, reference, float(hit.group(2))


def trigger_waveform(d: dict[str, np.ndarray], probe: str, reference: str) -> np.ndarray:
    return d[probe] if reference == "0" else d[probe] - d[reference]


def shared_fault_network(deck_text: str) -> list[str]:
    prefixes = ("Vflt", "Sflt", "Rflt", ".model HOTFLT", ".tran", ".ic", ".options")
    return [line.strip() for line in deck_text.splitlines()
            if line.strip().startswith(prefixes)]


def solver_is_cshunt(deck_text: str) -> bool:
    """True when the deck carries the 1 fF convergence option.

    The 50 V candidates inherit it from their parent; the flag has to be read
    from the whole ``.options`` line, not from a fixed prefix, because LTspice
    accepts the options in any order.
    """
    return "cshunt=1e-15" in deck_text


def gate_clamps_present(deck_text: str) -> bool:
    return (deck_text.count("inhib 0 PROT_KILL") == 10
            and all(f"S{node} {node} {ref} inhib 0 PROT_KILL\n" in deck_text
                    for node, ref in make.GATES))


def first_sustained_low(t: np.ndarray, y: np.ndarray, after: float,
                        level: float = GATE_OFF_V,
                        hold: float = GATE_OFF_DEBOUNCE_S) -> float | None:
    for start, end, _ in low_runs(t, y, level, after):
        if end - start >= hold:
            return start
    return None


def last_high_time(t: np.ndarray, y: np.ndarray, after: float,
                   level: float = GATE_OFF_V) -> float | None:
    mask = (t >= after) & (y > level)
    return float(t[mask].max()) if mask.any() else None


def high_side_gate(gh_to_ground: np.ndarray, sw_to_ground: np.ndarray) -> np.ndarray:
    """High-side Vgs from two node-to-ground probes; V(gh) alone is not Vgs."""
    return gh_to_ground - sw_to_ground


def gate_record(t: np.ndarray, gate: np.ndarray, after: float) -> dict[str, object]:
    settled = first_sustained_low(t, gate, after)
    last_high = last_high_time(t, gate, after)
    mask = t >= after
    return {
        "gate_settled_low_s": settled,
        "gate_settled_low_us": None if settled is None else settled * 1e6,
        "last_high_s": last_high,
        "last_high_us": None if last_high is None else last_high * 1e6,
        "high_fraction_after": None if not mask.any() else float((gate[mask] > GATE_ON_V).mean()),
        "end_v": float(gate[-1]),
        "high_at_end": bool(gate[-1] > GATE_ON_V),
    }


def device_record(t: np.ndarray, d: dict[str, np.ndarray], pair: int, side: str,
                  latch_s: float, engage_s: float) -> dict[str, object]:
    dev = device_names(pair, side)
    gate = d[dev["gate"]]
    forward = np.maximum(-d[dev["sense"]], 0.0)
    after = t >= engage_s
    gate_high = gate > GATE_ON_V
    record = gate_record(t, gate, latch_s)
    record.update({
        "forward_peak_a": float(forward[after].max()) if after.any() else None,
        "forward_i2t_a2s": i2t(t, forward, engage_s, float(t[-1])),
        "i2t_while_gate_high_a2s": i2t(t, np.where(gate_high, forward, 0.0), engage_s, float(t[-1])),
        "drain_min_v": float(d[dev["drain"]][after].min()) if after.any() else None,
    })
    return record


def all_gates_low_time(records: dict[str, dict[str, object]], latch_s: float) -> float | None:
    highs = [r["last_high_s"] for r in records.values() if r["last_high_s"] is not None]
    return max(highs) if highs else latch_s


def window_metrics(t: np.ndarray, d: dict[str, np.ndarray], engage_s: float,
                   latch_s: float | None, source: str) -> dict[str, object]:
    after = t >= engage_s
    gates = {key: device_record(t, d, int(key[0]), key[1], latch_s or engage_s, engage_s)
             for key in (f"{p}{s}" for p in PAIRS for s in SIDES)}
    forward_peaks = [g["forward_peak_a"] for g in gates.values() if g["forward_peak_a"] is not None]
    forward_i2t = [g["forward_i2t_a2s"] for g in gates.values()]
    all_low = all_gates_low_time(gates, latch_s or engage_s)
    return {
        "source": source,
        "samples": int(t.size),
        "t_last_us": float(t[-1]) * 1e6,
        "ipri_peak_a": float(np.abs(d["I(Lr)"][after]).max()) if after.any() else None,
        "ipri_i2t_a2s": i2t(t, d["I(Lr)"], engage_s, float(t[-1])),
        "sr_forward_peak_a": max(forward_peaks) if forward_peaks else None,
        "sr_forward_i2t_total_a2s": float(sum(forward_i2t)),
        "sr_i2t_while_gate_high_a2s": float(sum(g["i2t_while_gate_high_a2s"] for g in gates.values())),
        "vout_min_after_engage_v": float(d["V(out)"][after].min()) if after.any() else None,
        "vout_end_v": float(d["V(out)"][-1]),
        "oc_max_v": float(d["V(oc)"][after].max()) if after.any() else None,
        "ocd_max_v": float(d["V(ocd)"][after].max()) if after.any() else None,
        "ss_mean_at_engage_v": mean_window(t, d["V(ss)"], engage_s - 5e-6, engage_s),
        "all_gates_last_high_s": all_low,
        "all_gates_last_high_us": None if all_low is None else all_low * 1e6,
        "gates": gates,
    }


def pre_fault(t: np.ndarray, d: dict[str, np.ndarray], engage_s: float,
              names: list[str]) -> dict[str, object]:
    t0 = engage_s - PRE_FAULT_US * 1e-6
    mask = (t >= t0) & (t <= engage_s)
    record = {
        "window_s": [t0, engage_s],
        "vout_mean_v": mean_window(t, d["V(out)"], t0, engage_s),
        "ss_mean_v": mean_window(t, d["V(ss)"], t0, engage_s),
        "oc_max_v": float(d["V(oc)"][mask].max()) if mask.any() else None,
        "ocd_max_v": float(d["V(ocd)"][mask].max()) if mask.any() else None,
    }
    if "V(ocdf)" in names:
        record["ocdf_max_v"] = float(d["V(ocdf)"][mask].max()) if mask.any() else None
        record["ocdf_min_v"] = float(d["V(ocdf)"][mask].min()) if mask.any() else None
    return record


def relative(base: float | None, candidate: float | None) -> float | None:
    if base in (None, 0.0) or candidate is None:
        return None
    return candidate / base - 1.0


def compare(case: str, base_raw: Path, candidate_raw: Path, *,
            base_deck: Path | None = None,
            candidate_deck: Path | None = None) -> dict[str, object]:
    base_deck = base_deck or make.parent_deck(case)
    candidate_deck = candidate_deck or make.destination(case)
    base_text = base_deck.read_text(encoding="utf-8")
    candidate_text = candidate_deck.read_text(encoding="utf-8")
    # Structural checks always run against the *declared parent*, never against
    # whichever deck was passed as the comparison base: a control deck that
    # carries the protection block cannot be regenerated by ``build()``.
    declared_text = make.parent_deck(case).read_text(encoding="utf-8")
    expected = make.build(declared_text, case)
    timing = saved_fault_window(candidate_text)
    engage_s = float(timing["engage_rebased_s"])
    declared_stop_s = saved_stop_s(candidate_text)
    base_stop_s = saved_stop_s(base_text)
    base_tail = last_time(base_raw)
    candidate_tail = last_time(candidate_raw)
    end_s = min(declared_stop_s, base_stop_s, base_tail, candidate_tail)
    if end_s <= engage_s:
        raise ValueError("the two raws share no post-fault samples")

    trigger_probe, trigger_ref, threshold = trigger_from_deck(candidate_text)
    arming = "Carm arm" in candidate_text
    base_probes = base_names()
    candidate_probes = candidate_names(trigger_probe, arming)
    t, db = read_window(base_raw, base_probes, engage_s - PRE_FAULT_US * 1e-6, end_s)
    tc, dc = read_window(candidate_raw, candidate_probes, engage_s - PRE_FAULT_US * 1e-6, end_s)

    base_trip = first_cross(t, db["V(oc)"], 1.0, engage_s)
    trigger_s = first_cross(tc, trigger_waveform(dc, trigger_probe, trigger_ref), threshold, engage_s)
    latch_s = first_cross(tc, dc["V(prot)"], TRIGGER_LATCH_V, engage_s)
    inhib_s = first_cross(tc, dc["V(inhib)"], TRIGGER_LATCH_V, engage_s)
    actuation_s = latch_s or trigger_s or engage_s

    base = window_metrics(t, db, engage_s, None, "base")
    candidate = window_metrics(tc, dc, engage_s, actuation_s, "candidate")
    base_pre = pre_fault(t, db, engage_s, base_probes)
    candidate_pre = pre_fault(tc, dc, engage_s, candidate_probes)
    pre_match_mv = abs(candidate_pre["vout_mean_v"] - base_pre["vout_mean_v"]) * 1e3

    # V(gh) is a floating node: the high-side gate-source voltage is
    # V(gh) - V(sw).  Measuring V(gh) to ground would keep reading "high"
    # whenever the switch node parks above 1 V after the bridge stops.
    primary = {
        "gh": gate_record(tc, high_side_gate(dc["V(gh)"], dc["V(sw)"]), actuation_s),
        "gl": gate_record(tc, dc["V(gl)"], actuation_s),
    }
    primary_high = [r["last_high_s"] for r in primary.values() if r["last_high_s"] is not None]
    primary_off_s = max(primary_high) if primary_high else None

    gate_rows = {f"{p}{s}": candidate["gates"][f"{p}{s}"] for p in PAIRS for s in SIDES}
    base_rows = {f"{p}{s}": base["gates"][f"{p}{s}"] for p in PAIRS for s in SIDES}
    latencies = {key: None if row["gate_settled_low_s"] is None or latch_s is None
                 else (row["gate_settled_low_s"] - latch_s) * 1e6
                 for key, row in gate_rows.items()}
    base_high_at_end = {key: row["high_at_end"] for key, row in base_rows.items()}

    covered = end_s >= declared_stop_s - 1e-9
    base_done = base_tail >= base_stop_s - 1e-9
    candidate_done = candidate_tail >= declared_stop_s - 1e-9
    rail = "50 V (cshunt=1 fF convergence child)" if "50v" in candidate_deck.name else "48 V"
    limits = [
        "a behavioural latch and ideal 0.05 ohm clamps are not a hardware protection design",
        "no SOA, thermal, comparator noise, gate-loop inductance or restart sequencing is modelled",
        "the trigger level is a chosen threshold, not a qualified comparator specification",
        "a candidate that stops early is a prefix; it does not cover the declared window",
        f"the {rail} record is a hot start from .ic V(out)=1.89 V, not a cold start",
        "the arming latch closes inside the unsaved 2 ms pre-history; the saved axis can only show that it is already high",
        "the base's SR gates re-assert after trip (the phase and count differ between runs); "
        "the candidate clamps are the comparison, not a safety claim",
    ]
    if "cshunt" in candidate_deck.name:
        limits.append(
            "the parent carries '.options cshunt=1e-15'; the 50 V base without it still "
            "stalls at 296.929 us, so this 50 V record is a convergence-child record")
    if not covered:
        limits.append(
            f"the common slice ends at {end_s * 1e6:.3f} us, not {declared_stop_s * 1e6:.0f} us: "
            "the shorter record stops there")
    if not candidate_done:
        limits.append("the candidate did not reach its saved stop; post-stall samples are not evidence")
    return {
        "kind": "protection_candidate_comparison",
        "evidence_level": "SIMULATED_ONLY / NOT_HARDWARE / NOT_A_SAFETY_PROOF",
        "case": case,
        "decks": {
            "base": str(base_deck.relative_to(ROOT)) if base_deck.is_relative_to(ROOT) else str(base_deck),
            "candidate": str(candidate_deck.relative_to(ROOT)) if candidate_deck.is_relative_to(ROOT) else str(candidate_deck),
            "declared_parent": str(make.parent_deck(case).relative_to(ROOT)),
            "solver_cshunt": solver_is_cshunt(candidate_text),
        },
        "window_s": [engage_s, end_s],
        "declared_window_s": [engage_s, declared_stop_s],
        "window_basis": "fault engage to the shorter record's tail; pre-fault is the preceding 35 us",
        "results": {
            "trigger": {
                "node": trigger_probe,
                "reference": trigger_ref,
                "threshold_v": threshold,
                "trigger_s": trigger_s,
                "trigger_us": None if trigger_s is None else trigger_s * 1e6,
                "base_trip_s": base_trip,
                "base_trip_us": None if base_trip is None else base_trip * 1e6,
                "trigger_lead_vs_base_us": None if trigger_s is None or base_trip is None
                else (base_trip - trigger_s) * 1e6,
                "latch_s": latch_s,
                "latch_us": None if latch_s is None else latch_s * 1e6,
                "latch_delay_us": None if latch_s is None or trigger_s is None
                else (latch_s - trigger_s) * 1e6,
                "inhibit_s": inhib_s,
                "protection_asserted": bool(latch_s is not None and inhib_s is not None),
                # The arm latch closes during the 2 ms pre-history, outside the
                # saved axis, so the only readable evidence is that it is high
                # at the first saved sample.  An unarmed deck is dead from t=0.
                "arming_present": arming,
                "arm_v_at_window_start": float(dc["V(arm)"][0]) if arming else None,
                "armed_before_the_window": bool((dc["V(arm)"] > 0.5).all()) if arming else False,
            },
            "pre_fault": {
                "base": base_pre,
                "candidate": candidate_pre,
                "vout_mean_delta_mv": (candidate_pre["vout_mean_v"] - base_pre["vout_mean_v"]) * 1e3,
            },
            "base": base,
            "candidate": candidate,
            "gates": gate_rows,
            "gate_latency_from_latch_us": latencies,
            "primary_gates": primary,
            "primary_gate_off_s": primary_off_s,
            "primary_gate_off_latency_us": None if primary_off_s is None or latch_s is None
            else (primary_off_s - latch_s) * 1e6,
            "relief": {
                "ipri_peak_rel": relative(base["ipri_peak_a"], candidate["ipri_peak_a"]),
                "sr_forward_peak_rel": relative(base["sr_forward_peak_a"], candidate["sr_forward_peak_a"]),
                "sr_forward_i2t_total_rel": relative(base["sr_forward_i2t_total_a2s"],
                                                     candidate["sr_forward_i2t_total_a2s"]),
                "vout_min_delta_mv": None if base["vout_min_after_engage_v"] is None
                or candidate["vout_min_after_engage_v"] is None
                else (candidate["vout_min_after_engage_v"] - base["vout_min_after_engage_v"]) * 1e3,
            },
            "base_gate_high_at_end": base_high_at_end,
            "all_candidate_gates_low_at_end": all(not row["high_at_end"] for row in gate_rows.values()),
            "hardware_continuous_rating_approved": False,
            "safety_proof": False,
        },
        "coverage": {
            "base_t_last_us": base_tail * 1e6,
            "candidate_t_last_us": candidate_tail * 1e6,
            "base_saved_stop_us": base_stop_s * 1e6,
            "candidate_saved_stop_us": declared_stop_s * 1e6,
            "base_reached_saved_stop": bool(base_done),
            "candidate_reached_saved_stop": bool(candidate_done),
            "declared_window_fully_covered": bool(covered),
        },
        "checks": {
            "the_candidate_matches_its_generator": bool(expected == candidate_text),
            "the_parent_fault_network_is_unchanged": shared_fault_network(declared_text) == shared_fault_network(candidate_text),
            "all_ten_gate_clamps_are_present": gate_clamps_present(candidate_text),
            "the_pre_fault_operating_points_match_within_1_mv": bool(pre_match_mv <= PRE_FAULT_MATCH_MV),
            "the_candidate_raw_reaches_the_saved_stop": bool(candidate_done),
            "the_declared_window_is_fully_covered": bool(covered),
            "the_candidate_was_armed_before_the_fault":
                bool(arming and (dc["V(arm)"] > 0.5).all()),
        },
        "limits": limits,
    }


def uvlo_check(uvlo_raw: Path, uvlo_deck: Path) -> dict[str, object]:
    text = uvlo_deck.read_text(encoding="utf-8")
    t, d = read_window(uvlo_raw,
                       ["V(vddp)", "V(ss)", "V(uvlo)", "V(arm)", "V(prot)", "V(inhib)", "V(g)"],
                       0.0, 200e-6)
    gate_before = mean_window(t, d["V(g)"], 90e-6, 99e-6)
    gate_after = mean_window(t, d["V(g)"], 150e-6, 199e-6)
    tail = t >= 150e-6
    results = {
        "gate_before_v": gate_before,
        "gate_after_v": gate_after,
        "arm_before_v": mean_window(t, d["V(arm)"], 90e-6, 99e-6),
        "arm_after_v": mean_window(t, d["V(arm)"], 150e-6, 199e-6),
        "inhib_after": float(d["V(inhib)"][tail].mean()) if tail.any() else None,
        "prot_after": float(d["V(prot)"][tail].mean()) if tail.any() else None,
        "vddp_after_min_v": float(d["V(vddp)"][tail].min()) if tail.any() else None,
        "gate_fell_below_1v": bool(gate_after < 1.0),
        "default_off_asserted": bool(tail.any() and (d["V(inhib)"][tail] > 0.5).all()),
    }
    results["uvlo_forced_gate_low"] = bool(results["gate_fell_below_1v"]
                                           and results["default_off_asserted"])
    return {
        "kind": "protection_uvlo_sub_circuit_check",
        "evidence_level": "SIMULATED_SUB_CIRCUIT_ONLY / NOT_HARDWARE",
        "deck": str(uvlo_deck.relative_to(ROOT)) if uvlo_deck.is_relative_to(ROOT) else str(uvlo_deck),
        "results": results,
        "checks": {
            "the_deck_has_no_fault_trigger": "Vflt" not in text,
            "the_dummy_gate_is_driven_through_3p2_ohm": "Rdrv drv g 3.2" in text,
            "the_raw_covers_the_200us_window": bool(t[-1] >= 199e-6),
            "the_arming_latch_is_closed_before_the_uvlo_drop":
                bool(results["arm_before_v"] > 0.5),
            "the_fault_latch_is_not_set_without_a_trigger":
                bool(results["prot_after"] < 0.5),
        },
        "limits": [
            "this checks the latch and one clamp on a dummy gate, not the power stage",
            "Vddp is an ideal PWL source; no real UVLO divider, hysteresis or startup delay",
            "the gate residual is set by the 0.05 ohm clamp against the 3.2 ohm driver",
        ],
    }


def restart_check(restart_raw: Path, restart_deck: Path) -> dict[str, object]:
    """Logic-level restart order: latch, power cycle, blanked ramp, re-arm.

    Every quantity here is a *result*, not a check: the checks only assert that
    the deck is the generator output and covers the declared window.
    """
    text = restart_deck.read_text(encoding="utf-8")
    names = ["V(vddp)", "V(ss)", "V(uvlo)", "V(arm)", "V(prot)", "V(inhib)", "V(g)", "V(oc)"]
    t, d = read_window(restart_raw, names, 0.0, make.RESTART_STOP_S)
    guard = 0.2e-6
    latch_w = (70e-6, 99e-6)
    cycle_w = (make.POWER_CYCLE_S + guard, make.POWER_RETURN_S - guard)
    ramp_w = (make.POWER_RETURN_S + guard, make.RESTART_PULSE_S - 0.1e-3)
    pulse_w = (make.RESTART_PULSE_S + guard, make.RESTART_PULSE_S + 0.1e-3)
    arm_s = make.POWER_RETURN_S + make.ARM_SS_V / make.SS_RAMP_V_PER_S
    armed_w = (arm_s + 0.03e-3, make.REARM_PULSE_S - 0.01e-3)
    rearm_w = (make.REARM_PULSE_S + 0.02e-3, make.RESTART_STOP_S - 0.01e-3)

    def window_max(name: str, w: tuple[float, float]) -> float | None:
        mask = (t >= w[0]) & (t <= w[1])
        return float(d[name][mask].max()) if mask.any() else None

    def window_min(name: str, w: tuple[float, float]) -> float | None:
        mask = (t >= w[0]) & (t <= w[1])
        return float(d[name][mask].min()) if mask.any() else None

    def window_mean(name: str, w: tuple[float, float]) -> float:
        return mean_window(t, d[name], *w)

    cleared_w = (make.POWER_RETURN_S - 0.9e-6, make.POWER_RETURN_S - 0.1e-6)
    arm_closed = first_cross(t, d["V(arm)"], 0.5, make.POWER_RETURN_S)
    ss_cross = first_cross(t, d["V(ss)"], make.ARM_SS_V, make.POWER_RETURN_S)
    sequence = {
        "latch_set_before_power_cycle": bool(window_mean("V(prot)", latch_w) > 0.5),
        "gate_low_while_latched": bool(window_mean("V(g)", latch_w) < 1.0),
        "power_cycle_inhibits": bool((window_min("V(inhib)", cycle_w) or 0.0) > 0.5),
        "gate_low_during_power_cycle": bool((window_max("V(g)", cycle_w) or 0.0) < 1.0),
        "latch_cleared_by_power_cycle": bool(window_max("V(prot)", cleared_w) < 0.05),
        "arming_latch_cleared_by_power_cycle": bool(window_max("V(arm)", cleared_w) < 0.05),
        "fast_path_blanked_during_restart_ramp":
            bool(window_max("V(prot)", pulse_w) < 0.05),
        "arming_latch_reclosed_after_soft_start":
            bool((window_max("V(arm)", armed_w) or 0.0) > 0.5),
        "latch_sets_again_after_rearm":
            bool((window_max("V(prot)", rearm_w) or 0.0) > 0.5),
        "gate_low_after_rearm_latch": bool(window_mean("V(g)", rearm_w) < 1.0),
    }
    results = {
        "armed_before_fault_v": window_mean("V(arm)", latch_w),
        "latch_before_power_cycle_v": window_mean("V(prot)", latch_w),
        "gate_latched_low_v": window_mean("V(g)", latch_w),
        "vddp_min_during_power_cycle_v": window_min("V(vddp)", cycle_w),
        "inhibit_min_during_power_cycle": window_min("V(inhib)", cycle_w),
        "gate_max_during_power_cycle_v": window_max("V(g)", cycle_w),
        "latch_after_power_cycle_v": window_max("V(prot)", cleared_w),
        "arming_latch_after_power_cycle_v": window_max("V(arm)", cleared_w),
        "restart_ramp_s": arm_s,
        "arming_latch_closed_s": arm_closed,
        "arming_latch_closed_ms": None if arm_closed is None else arm_closed * 1e3,
        "soft_start_crossed_arm_level_s": ss_cross,
        "soft_start_crossed_arm_level_ms": None if ss_cross is None else ss_cross * 1e3,
        "restart_pulse_peak_v": window_max("V(prot)", pulse_w),
        "gate_during_restart_ramp_v": window_mean("V(g)", ramp_w),
        "rearm_pulse_peak_v": window_max("V(prot)", rearm_w),
        "gate_after_rearm_latch_v": window_mean("V(g)", rearm_w),
        "sequence": sequence,
        "restart_sequence_verified": all(sequence.values()),
    }
    return {
        "kind": "protection_restart_sub_circuit_check",
        "evidence_level": "SIMULATED_SUB_CIRCUIT_ONLY / NOT_HARDWARE",
        "deck": str(restart_deck.relative_to(ROOT)) if restart_deck.is_relative_to(ROOT)
        else str(restart_deck),
        "results": results,
        "checks": {
            "the_deck_is_the_generator_output": bool(text == make.restart_deck()),
            "the_deck_resets_both_latches_on_uvlo":
                bool("V(prot)*(1n/100n)" in text and "V(arm)*(1n/100n)" in text),
            "the_dummy_gate_is_driven_through_3p2_ohm": "Rdrv drv g 3.2" in text,
            # LTspice stops at the last internal step, so the saved axis can
            # end up to one 10 ns max step short of the declared 10.6 ms.
            "the_raw_covers_the_restart_window": bool(t[-1] >= make.RESTART_STOP_S - 10e-9),
        },
        "limits": [
            "logic-only sub-circuit: ideal PWL sources, no power stage, no controller "
            "Level-1 OC and no real gate driver",
            "the gate is still driven during the blanked restart ramp; protection in that "
            "window relies on the controller's own OC, which this deck does not model",
            "the arming-latch UVLO reset is an addition carried only by this deck; the "
            "frozen comparison decks hold Vddp at 12 V, where the branch is never selected",
            "TAU_PROT = 100 ns is a modelling choice, not a datasheet reset time",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", choices=sorted(make.CANDIDATES))
    ap.add_argument("--base-raw", type=Path)
    ap.add_argument("--candidate-raw", type=Path)
    # Default is the candidate's declared parent, not a hard-coded deck: the
    # 50 V candidates hang off the cshunt child.
    ap.add_argument("--base-deck", type=Path)
    ap.add_argument("--candidate-deck", type=Path)
    ap.add_argument("--uvlo-raw", type=Path)
    ap.add_argument("--uvlo-deck", type=Path, default=make.uvlo_destination())
    ap.add_argument("--restart-raw", type=Path)
    ap.add_argument("--restart-deck", type=Path, default=make.restart_destination())
    ap.add_argument("--json", type=Path)
    ap.add_argument("--uvlo-json", type=Path)
    ap.add_argument("--restart-json", type=Path)
    args = ap.parse_args()
    comparison = (args.case is not None or args.base_raw is not None
                  or args.candidate_raw is not None or args.json is not None)
    if comparison:
        missing = [name for name, value in (("--case", args.case), ("--base-raw", args.base_raw),
                                            ("--candidate-raw", args.candidate_raw),
                                            ("--json", args.json)) if value is None]
        if missing:
            ap.error(f"{', '.join(missing)} required for a candidate comparison")
        record = compare(args.case, args.base_raw, args.candidate_raw,
                         base_deck=args.base_deck, candidate_deck=args.candidate_deck)
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        print(f"wrote {args.json}")
        print(f"base trip {record['results']['trigger']['base_trip_us']} us / "
              f"latch {record['results']['trigger']['latch_us']} us")
    if args.uvlo_raw:
        uvlo = uvlo_check(args.uvlo_raw, args.uvlo_deck)
        if args.uvlo_json:
            args.uvlo_json.parent.mkdir(parents=True, exist_ok=True)
            args.uvlo_json.write_text(json.dumps(uvlo, indent=1, ensure_ascii=False) + "\n",
                                      encoding="utf-8")
            print(f"wrote {args.uvlo_json}")
        print(f"uvlo gate {uvlo['results']['gate_after_v']:.3f} V, "
              f"default off {uvlo['results']['default_off_asserted']}")
    if args.restart_raw:
        restart = restart_check(args.restart_raw, args.restart_deck)
        if args.restart_json:
            args.restart_json.parent.mkdir(parents=True, exist_ok=True)
            args.restart_json.write_text(json.dumps(restart, indent=1, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
            print(f"wrote {args.restart_json}")
        print(f"restart sequence verified {restart['results']['restart_sequence_verified']}, "
              f"re-arm at {restart['results']['arming_latch_closed_ms']} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
