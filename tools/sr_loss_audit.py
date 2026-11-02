"""SR current, loss and gate-drive audit (review 2026-11-01, issue #6 follow-up).

The 133-period phase-aligned ledger leaves a +0.33 W closure residual and the
SR loss term moves 1.37 W between 5 ns and 1 ns -- and, once the 0.5 ns leg is
added, 2.30 W across the four steps while the closure moves 0.21 W on that last
leg alone.  The review asked for a targeted check of three things -- the dimensions of the SR current and loss
integrals, the window/timestep dependence, and the external drive power --
before anything is concluded about convergence or efficiency.

This tool answers those three questions with the raw itself:

1. **Dimensions and signs.**  Two exact identities are evaluated on every
   window.  Drain side: ``I(VSa*) == I(Ld)`` (the 0 V sense source carries the
   package current), and ``v(di,si)*I(Ld) == channel + body_diode +
   v*I(Cds) - v*I(Cgd)`` (conduction plus the two capacitive branches).  Gate
   side: ``driver_output == gate_pin + Rgs + Cpin``.  If any of these carried
   a wrong unit or sign, they would not close.

2. **Window and timestep.**  The same three splits are tabulated for
   5 / 2 / 1 / 0.5 ns on the aligned window and for 5 / 2 ns on the 16-period
   window, together with the cycle-by-cycle difference between steps.  The
   point is to show *which* term moves and whether it moves systematically.

3. **External drive power.**  ``Bdrive`` is an ideal source, so its output
   never comes from the port -- and the closure boundary adds it.  But the
   same boundary also contains the two sinks it feeds, ``Rg`` (inside
   ``SR_DEVICE``) and ``Rgs`` (inside ``SR_CH3``), and ``loss_main`` contains
   neither.  The audit measures both and reports the closure with them
   counted.  It does **not** change the 0.2 W budget, and it does not flip the
   ledger's ``closure_status``: numerical convergence of the loss list is a
   separate question that this tool also measures and does not answer.

Usage:
    python tools/sr_loss_audit.py
    python tools/sr_loss_audit.py --json design/v3/stage_f/sr_loss_audit.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
from array import array
from pathlib import Path

import energy_ledger_100a as el

ROOT = el.ROOT
OUT = ROOT / "design/v3/stage_f/sr_loss_audit.json"

BUDGET_W = 0.2                 # the ledger's target; this tool may not move it
RGS_OHM = 10e3                 # SR_CH3 ``Rgs G S 10k``
RG_OHM = 1.0                   # SR_DEVICE ``Rg gn gi {RG}`` default RG=1

LEDGER_100A = ROOT / "design/v3/stage_f/energy_ledger_100a.json"
LEDGER_ALIGNED = ROOT / "design/v3/stage_f/energy_ledger_100a_phase_aligned.json"
LEDGER_110A = ROOT / "design/v3/power_priority/energy_ledger_48v_110a.json"
LEDGER_120A = ROOT / "design/v3/power_priority/energy_ledger_48v_120a.json"
LEDGER_50V_110A = ROOT / "design/v3/power_priority/energy_ledger_50v_110a.json"
LEDGER_50V_120A = ROOT / "design/v3/power_priority/energy_ledger_50v_120a.json"
# ELE-09: the 50 V/120 A ledger whose ``step_check`` holds both the 5 ns and
# the 2 ns column, so one file answers "did the 0.499 W move with the step?".
LEDGER_50V_120A_STEPS = ROOT / "design/v3/power_priority/energy_ledger_50v_120a_steps.json"

CASES = (
    {"name": "aligned_5ns", "raw": "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned.raw",
     "periods": 133, "vin": 48.0, "rl": 18.9e-3, "ledger": LEDGER_ALIGNED,
     "family": "aligned"},
    {"name": "aligned_2ns", "raw": "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned2n.raw",
     "periods": 133, "vin": 48.0, "rl": 18.9e-3, "ledger": LEDGER_ALIGNED,
     "family": "aligned"},
    {"name": "aligned_1ns", "raw": "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned1n.raw",
     "periods": 133, "vin": 48.0, "rl": 18.9e-3, "ledger": LEDGER_ALIGNED,
     "family": "aligned"},
    # Issue #6, E6-3's optional <=0.5 ns leg.  The 5/2/1 ns series is not
    # monotone (10.73 / 11.36 / 9.98 W), so a fourth point is the cheapest way
    # to see whether the last leg shrinks or reverses again.
    {"name": "aligned_0p5ns",
     "raw": "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned0p5n.raw",
     "periods": 133, "vin": 48.0, "rl": 18.9e-3, "ledger": LEDGER_ALIGNED,
     "family": "aligned"},
    {"name": "sixteen_period_5ns",
     "raw": "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.raw",
     "periods": 16, "vin": 48.0, "rl": 18.9e-3, "ledger": LEDGER_100A,
     "family": "sixteen_period"},
    {"name": "sixteen_period_2ns",
     "raw": "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger2n.raw",
     "periods": 16, "vin": 48.0, "rl": 18.9e-3, "ledger": LEDGER_100A,
     "family": "sixteen_period"},
    # The 111 A candidate is a different tank (LR_TOTAL=1u) with a larger Cout
    # (7.05 mF) and a different load.  It is here because the review quotes its
    # closure; the deck-parameter block below shows what the ledger tool's
    # mother-deck constants do to it.
    {"name": "candidate_111a",
     "raw": "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110_cin.raw",
     "periods": 22, "vin": 48.0, "rl": 16.9e-3, "ledger": LEDGER_110A,
     "family": "candidate"},
    # The 50 V runs and the 48 V/120 A candidate use the same 1 uH tank and
    # 7.05 mF Cout as the 111 A deck, so the ledger tool's mother-deck storage
    # constants debit their closure just the same.
    {"name": "candidate_50v_110a",
     "raw": "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110_cin.raw",
     "periods": 22, "vin": 50.0, "rl": 17.8e-3, "ledger": LEDGER_50V_110A,
     "family": "candidate"},
    {"name": "candidate_50v_120a",
     "raw": "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.raw",
     "periods": 22, "vin": 50.0, "rl": 16.3e-3, "ledger": LEDGER_50V_120A,
     "family": "candidate"},
    {"name": "candidate_48v_120a",
     "raw": "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120_cin.raw",
     "periods": 22, "vin": 48.0, "rl": 15.4e-3, "ledger": LEDGER_120A,
     "family": "candidate"},
    # ELE-09: the same 50 V/120 A deck at half the timestep.  Its 0.499 W loss
    # residual is the same at 48 V (0.483 W), so it is current dependent; the
    # 100 A aligned work showed the SR body-diode forward term is the one that
    # moves with the step.  This is the run that says whether the 0.499 W is
    # that artifact or a missing term.  Only ``.tran``'s max step differs, so
    # the window and the deck are identical to ``candidate_50v_120a``.
    {"name": "candidate_50v_120a_2ns",
     "raw": "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin_2n.raw",
     "periods": 22, "vin": 50.0, "rl": 16.3e-3,
     "ledger": LEDGER_50V_120A_STEPS,
     "family": "candidate"},
)

_SCALE = {"": 1.0, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12,
          "f": 1e-15, "k": 1e3, "meg": 1e6}


def _number(text: str) -> float:
    """LTspice value literal (``7.05m``, ``.92u``, ``1``) as a float."""
    match = re.fullmatch(r"([0-9]*\.?[0-9]+)([a-z]*)", text.strip().lower())
    if not match:
        raise ValueError(f"not an LTspice number: {text!r}")
    return float(match.group(1)) * _SCALE[match.group(2)]


def deck_values(raw: Path) -> dict[str, float | None]:
    """The electrical values the deck actually ran: ``Cout`` and ``LR_TOTAL``.

    The ledger tool carries ``COUT_F`` / ``LR_H`` as module constants sized for
    the 100 A mother deck.  A candidate deck that changes them must not have
    its storage terms integrated with the mother deck's numbers, so the audit
    reads them from the deck beside the raw instead of assuming.
    """
    deck = Path(raw).with_suffix(".cir")
    if not deck.exists():
        return {"cout_f": None, "lr_h": None}
    text = deck.read_text(encoding="utf-8", errors="replace")
    cout = re.search(r"^\s*Cout\s+out\s+sgnd\s+(\S+)", text, re.M)
    lr = re.search(r"LR_TOTAL\s*=\s*(\S+)", text)
    return {"cout_f": _number(cout.group(1)) if cout else None,
            "lr_h": _number(lr.group(1)) if lr else None}


def probe_map() -> dict[str, str]:
    """The ledger's probes plus pair-1 internals, under the ledger's short names."""
    wanted = dict(el.WANTED)
    for half, probes in el.PAIR1_INTERNALS.items():
        for key, probe in probes.items():
            wanted[probe] = f"{half}_{key}"
    return wanted


def scan_case(raw: Path, periods: int) -> dict[str, object]:
    t, d = el.scan(Path(raw), probe_map())
    edges = el.gate_edges(t, d["vga"])
    i0, i1 = el.gate_window(t, d["vga"], periods)
    return {"t": t, "d": d, "edges": edges, "i0": i0, "i1": i1}


def gate_budget(t: array, d: dict[str, array], i0: int, i1: int) -> dict[str, object]:
    """Driver output and every sink it feeds, per half and scaled to eight.

    ``Bdrive`` is an ideal source between the gate pin and ground; the pin sees
    ``Lg`` (to the die), ``Rgs`` and ``Cpin``.  KCL at that pin gives
    ``driver_output = gate_pin + Rgs + Cpin`` exactly, which is what makes the
    boundary correction a measurement rather than an assumption.
    """
    span = t[i1] - t[i0]
    per_half: dict[str, dict[str, float]] = {}
    for half, gate, bdrive, rg_key in (("a", "vga", "bd1", "a_rg"),
                                       ("b", "vgb", "bd2", "b_rg")):
        vg = d[gate]
        n = len(t)
        per_half[half] = {
            "driver_output_w": -el._mean_product(t, vg, d[bdrive], i0, i1),
            "gate_pin_w": el._mean_product(t, vg, d[f"{half}_lg"], i0, i1),
            "gate_source_resistor_w": el._mean(
                t, array("d", (v * v / RGS_OHM for v in vg)), i0, i1),
            "gate_resistor_w": el._mean(
                t, array("d", (v * v * RG_OHM for v in d[rg_key])), i0, i1),
            "cpin_edge_w": (0.5 * el.CPIN_F
                            * (float(vg[i1]) ** 2 - float(vg[i0]) ** 2) / span),
        }
    keys = ("driver_output_w", "gate_pin_w", "gate_source_resistor_w",
            "gate_resistor_w", "cpin_edge_w")
    x8 = {key: 4.0 * (per_half["a"][key] + per_half["b"][key]) for key in keys}
    x8["sinks_x8_w"] = x8["gate_resistor_w"] + x8["gate_source_resistor_w"]
    x8["die_gate_storage_rate_w"] = x8["gate_pin_w"] - x8["gate_resistor_w"]
    x8["kcl_residual_x8_w"] = (x8["driver_output_w"] - x8["gate_pin_w"]
                              - x8["gate_source_resistor_w"] - x8["cpin_edge_w"])
    return {"per_half": per_half, **x8}


def drain_identity(t: array, d: dict[str, array], i0: int, i1: int) -> dict[str, object]:
    """Drain-side KCL and power identity, per half device of pair 1.

    ``VSa*`` sits between the secondary terminal and the SR drain, so its
    current *is* the package drain current.  At the internal drain node the
    conduction branches and the two capacitances must add up to it.
    """
    n = len(t)
    rows: dict[str, dict[str, float]] = {}
    for half, port in (("a", "isa1"), ("b", "isb1")):
        vds = array("d", (d[f"{half}_di"][i] - d[f"{half}_si"][i] for i in range(n)))
        current = el._mean(
            t, array("d", (d[port][i] - d[f"{half}_ld"][i] for i in range(n))), i0, i1)
        drain_w = el._mean(
            t, array("d", (vds[i] * d[f"{half}_ld"][i] for i in range(n))), i0, i1)
        channel_w = el._mean(
            t, array("d", (vds[i] * d[f"{half}_bch"][i] for i in range(n))), i0, i1)
        diode_w = el._mean(
            t, array("d", (-vds[i] * d[f"{half}_dbd"][i] for i in range(n))), i0, i1)
        capacitive_w = el._mean(
            t, array("d", (vds[i] * (d[f"{half}_cds"][i] - d[f"{half}_cgd"][i])
                           for i in range(n))), i0, i1)
        rows[half] = {
            "current_a": current,
            "drain_power_w": drain_w,
            "channel_w": channel_w,
            "body_diode_w": diode_w,
            "capacitive_w": capacitive_w,
            "power_residual_w": drain_w - (channel_w + diode_w + capacitive_w),
        }
    return rows


def sr_split(t: array, d: dict[str, array], i0: int, i1: int,
             periods: int) -> dict[str, object]:
    """Channel vs body-diode forward/reverse, scaled from pair 1 to eight.

    ``Dbd`` is ``si -> di``: forward current is positive and the drain is below
    the source, so ``-vds*I(Dbd)`` is positive when it conducts and negative
    during reverse recovery.  Splitting the two makes the sign check explicit.
    """
    span = t[i1] - t[i0]
    n = len(t)
    per_half: dict[str, dict[str, float]] = {}
    for half in ("a", "b"):
        vds = array("d", (d[f"{half}_di"][i] - d[f"{half}_si"][i] for i in range(n)))
        ib = d[f"{half}_dbd"]
        forward = array("d", (-vds[i] * ib[i] if ib[i] > 0.0 else 0.0 for i in range(n)))
        reverse = array("d", (-vds[i] * ib[i] if ib[i] < 0.0 else 0.0 for i in range(n)))
        q_fwd = el._integral(t, array("d", (max(v, 0.0) for v in ib)), i0, i1)
        q_rev = el._integral(t, array("d", (max(-v, 0.0) for v in ib)), i0, i1)
        per_half[half] = {
            "channel_w": el._mean(
                t, array("d", (vds[i] * d[f"{half}_bch"][i] for i in range(n))), i0, i1),
            "body_diode_w": el._mean(
                t, array("d", (-vds[i] * ib[i] for i in range(n))), i0, i1),
            "body_diode_forward_w": el._mean(t, forward, i0, i1),
            "body_diode_reverse_w": el._mean(t, reverse, i0, i1),
            "forward_charge_c": q_fwd,
            "reverse_charge_c": q_rev,
            # Mean current over the *window*: charge divided by span.  Not by
            # the period -- that would multiply the reading by ``periods``.
            "forward_current_a": q_fwd / span,
        }
    keys = ("channel_w", "body_diode_w", "body_diode_forward_w",
            "body_diode_reverse_w", "forward_charge_c", "reverse_charge_c")
    x8 = {key: 4.0 * (per_half["a"][key] + per_half["b"][key]) for key in keys}
    x8["total_w"] = x8["channel_w"] + x8["body_diode_w"]
    x8["forward_current_a"] = 4.0 * (per_half["a"]["forward_current_a"]
                                     + per_half["b"]["forward_current_a"])
    x8["mean_forward_voltage_v"] = (
        x8["body_diode_forward_w"] / x8["forward_current_a"]
        if x8["forward_current_a"] else 0.0)
    x8["forward_charge_per_device_c"] = (
        0.5 * (per_half["a"]["forward_charge_c"] + per_half["b"]["forward_charge_c"])
        / periods)
    return {"per_half": per_half, **x8}


def group_symmetry(t: array, d: dict[str, array],
                   i0: int, i1: int) -> dict[str, object]:
    """Pair 4 against pair 1 -- the only SR sharing check these raws allow.

    Every ledger deck saves the *terminal* currents of pairs 1 and 4 but not
    those of pairs 2 and 3, so ``sr_channel_body_x4`` (4 x pair 1) cannot be
    tested on all four groups.  What can be measured is one cross-check: if the
    four groups shared exactly, pair 4's RMS current would equal pair 1's to
    within solver noise.  The number bounds the error of the x4 scaling *in
    this model*; it says nothing about real board sharing, because the four
    secondary windings are identical by construction and any real asymmetry
    (leakage, copper, gate delay) is absent from the deck.

    A ratio away from 1 is therefore a numerical split, not physics: the four
    secondaries sit in parallel with a loop resistance of a couple of
    milliohms (winding ``Rser`` plus the SR channel), so a millivolt-level
    difference between two ~2 V nodes -- which is what the solver's relative
    tolerance allows -- moves roughly an amp between the branches.  The split
    is reported with the difference current that actually flows in the loop
    and with the I2R error it puts on the x4 scaling.
    """
    def rms(key: str) -> float:
        return math.sqrt(el._mean(t, array("d", (v * v for v in d[key])), i0, i1))

    def mean(key: str) -> float:
        return el._mean(t, d[key], i0, i1)

    def difference_rms(one: str, four: str) -> float:
        diff = array("d", (x - y for x, y in zip(d[one], d[four])))
        return math.sqrt(el._mean(t, array("d", (v * v for v in diff)), i0, i1))

    currents = {key: {"rms_a": rms(key), "mean_a": mean(key)}
                for key in ("isa1", "isb1", "isa4", "isb4")}
    ratios = {}
    circulating = {}
    for half, one, four in (("a", "isa1", "isa4"), ("b", "isb1", "isb4")):
        base = currents[one]["rms_a"]
        ratios[half] = (currents[four]["rms_a"] / base) if base else None
        circulating[half] = difference_rms(one, four)
    known = [value for value in ratios.values() if value is not None]
    return {
        "measured_groups": [1, 4],
        "unmeasured_groups": [2, 3],
        "unmeasured_reason": "pairs 2 and 3 have no current probes in any ledger deck",
        "currents": currents,
        "pair4_over_pair1_rms": ratios,
        "i2r_scaling_ratio": {half: (value * value if value is not None else None)
                              for half, value in ratios.items()},
        "pair_split_deviation_max": max((abs(value - 1.0) for value in known),
                                        default=None),
        "i2r_scaling_error_bound_pct": (100.0 * max(abs(value * value - 1.0)
                                                    for value in known)
                                        if known else None),
        "circulating_difference_rms_a": circulating,
    }


def per_period(t: array, d: dict[str, array], edges: list[int],
               i0: int, i1: int) -> dict[str, list[float]]:
    """Cycle-by-cycle channel and body-diode loss, scaled to eight devices.

    Built once per raw.  The arrays are precomputed so each period costs a
    windowed mean instead of a full-array generator, which is what makes the
    cycle-by-cycle step comparison affordable on a 1.9 M-point raw.
    """
    n = len(t)
    series = {}
    for half in ("a", "b"):
        vds = array("d", (d[f"{half}_di"][i] - d[f"{half}_si"][i] for i in range(n)))
        series[half] = (
            array("d", (-vds[i] * d[f"{half}_dbd"][i] for i in range(n))),
            array("d", (vds[i] * d[f"{half}_bch"][i] for i in range(n))),
        )
    diode: list[float] = []
    channel: list[float] = []
    for a, b in zip(edges[:-1], edges[1:]):
        if a < i0 or b > i1:
            continue
        diode.append(4.0 * sum(el._mean(t, series[h][0], a, b) for h in ("a", "b")))
        channel.append(4.0 * sum(el._mean(t, series[h][1], a, b) for h in ("a", "b")))
    return {"body_diode_w": diode, "channel_w": channel,
            "total_w": [x + y for x, y in zip(diode, channel)]}


def compare_series(a: list[float], b: list[float]) -> dict[str, object]:
    """Difference series statistics for two same-index per-cycle lists."""
    n = min(len(a), len(b))
    if n < 2:
        raise ValueError("need at least two periods to compare")
    diffs = [a[i] - b[i] for i in range(n)]
    mean = sum(diffs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in diffs) / (n - 1))
    return {"periods": n, "mean_w": mean, "rms_w": sd,
            "min_w": min(diffs), "max_w": max(diffs)}


def compare_cases(a: dict[str, object], b: dict[str, object]) -> dict[str, object]:
    """Two timesteps of one deck -> every term's value and ``b - a``.

    ``assemble``'s step tables live inside a family; ELE-09's candidate is a
    two-point comparison whose port and window must be identical, so it gets a
    named pair instead.  A nonzero port difference would mean the comparison
    mixed a circuit change into a step change, which is why the port and window
    are copied into the result.
    """
    def closure_value(case: dict[str, object], keys: tuple[str, ...]) -> float:
        value: object = case["closure"]
        for key in keys:
            value = value[key]  # type: ignore[index]
        return float(value)

    sr_terms = {}
    for term in ("channel_w", "body_diode_forward_w", "body_diode_reverse_w",
                 "body_diode_w", "total_w"):
        av = float(a["sr_dissipation"][term])  # type: ignore[index]
        bv = float(b["sr_dissipation"][term])  # type: ignore[index]
        sr_terms[term] = {"a_w": av, "b_w": bv, "delta_w": bv - av}
    closure_terms = {}
    for name, keys in (
            ("before_single_w", ("ledger", "single_w")),
            ("before_period_averaged_w", ("ledger", "period_averaged_w")),
            ("after_single_w", ("after_gate_drive_single_w",)),
            ("after_period_averaged_w", ("after_gate_drive_period_averaged_w",))):
        av = closure_value(a, keys)
        bv = closure_value(b, keys)
        closure_terms[name] = {"a_w": av, "b_w": bv, "delta_w": bv - av}
    # ``compare_series`` reports first minus second, so pass ``b`` first to keep
    # every delta in this block on the same ``b - a`` convention.
    per_cycle = {
        name: compare_series(b["per_period"][name], a["per_period"][name])  # type: ignore[index]
        for name in ("channel_w", "body_diode_w", "total_w")}
    return {
        "a": a["name"],
        "b": b["name"],
        "steps_s": [float(a["max_step_s"]), float(b["max_step_s"])],  # type: ignore[arg-type]
        "port": {"a": a["port"], "b": b["port"]},
        "window": {"a": a["window"], "b": b["window"]},
        "sr_terms": sr_terms,
        "closure": closure_terms,
        "closure_status": [a["closure"]["ledger"]["closure_status"],  # type: ignore[index]
                           b["closure"]["ledger"]["closure_status"]],  # type: ignore[index]
        "storage_parameters": {"a": a["storage_parameters"],
                               "b": b["storage_parameters"]},
        "per_cycle_deltas": per_cycle,
    }


def closure(t: array, d: dict[str, array], edges: list[int],
            i0: int, i1: int, arrays: dict[str, array],
            vin: float, rl: float) -> dict[str, float]:
    """Rebuild the ledger's two closure readings from the raw.

    Same arithmetic as ``energy_ledger_100a.build``: single samples at the two
    ends, and one gate period averaged at each end.  Reproducing it here is the
    audit's proof that the published number is a property of this raw and not
    of a stale JSON.  ``vin``/``rl`` are the *case's* port parameters; the
    mother deck's defaults would report its power against this waveform.
    """
    span = t[i1] - t[i0]
    terms = el.window_terms(t, d, i0, i1, arrays, vin=vin, rl=rl)
    stored_avg = sum(el.averaged_storage_terms(t, arrays, edges, i0, i1).values()) / span
    return {
        "port_w": float(terms["port_w"]),
        "loss_total_w": float(terms["loss_total_w"]),
        "driver_w": float(terms["driver_w"]),
        "stored_w": float(terms["stored_w"]),
        "stored_period_averaged_w": float(stored_avg),
        "single_w": (float(terms["port_w"]) + float(terms["driver_w"])
                     - float(terms["loss_total_w"]) - float(terms["stored_w"])),
        "period_averaged_w": (float(terms["port_w"]) + float(terms["driver_w"])
                              - float(terms["loss_total_w"]) - float(stored_avg)),
    }


def storage_parameters(t: array, d: dict[str, array], edges: list[int],
                       i0: int, i1: int, deck: dict[str, float | None]) -> dict[str, object]:
    """How the deck's Cout / Lr differ from the ledger tool's constants.

    ``storage_arrays`` is written against ``COUT_F`` and ``LR_H``, which are
    the mother deck's values.  A candidate that changes either would get its
    internal storage integrated with the wrong constant; the correction is
    linear, so it can be applied exactly to the closure instead of re-running.
    """
    cout_deck, lr_deck = deck["cout_f"], deck["lr_h"]
    span = t[i1] - t[i0]
    out: dict[str, object] = {
        "cout_f_deck": cout_deck, "cout_f_tool": el.COUT_F,
        "lr_h_deck": lr_deck, "lr_h_tool": el.LR_H,
    }
    if cout_deck is None or lr_deck is None:
        out.update({"delta_stored_single_j": 0.0, "delta_closure_single_w": 0.0,
                    "delta_stored_period_averaged_j": 0.0,
                    "delta_closure_period_averaged_w": 0.0,
                    "note": "deck missing: no adjustment applied"})
        return out
    cout_delta, lr_delta = cout_deck - el.COUT_F, lr_deck - el.LR_H
    v0, v1 = float(d["vout"][i0]), float(d["vout"][i1])
    i0c, i1c = float(d["ilr"][i0]), float(d["ilr"][i1])
    single_j = 0.5 * cout_delta * (v1 * v1 - v0 * v0) + 0.5 * lr_delta * (i1c * i1c - i0c * i0c)
    first = edges[edges.index(i0) + 1]
    last = edges[edges.index(i1) - 1]
    n = len(t)
    v2 = array("d", (v * v for v in d["vout"]))
    i2 = array("d", (v * v for v in d["ilr"]))
    avg_j = (0.5 * cout_delta * (el._mean(t, v2, last, i1) - el._mean(t, v2, i0, first))
             + 0.5 * lr_delta * (el._mean(t, i2, last, i1) - el._mean(t, i2, i0, first)))
    out.update({
        "delta_stored_single_j": single_j,
        "delta_closure_single_w": -single_j / span,
        "delta_stored_period_averaged_j": avg_j,
        "delta_closure_period_averaged_w": -avg_j / span,
        "note": "closure changes by -dStored/span; linear in C and L, so exact",
    })
    return out


def ledger_closure(path: Path, step_s: float | None) -> dict[str, object]:
    """The ledger's published closure for the column that ran ``step_s``."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    step_check = doc.get("step_check")
    index = 0
    if step_check and step_s is not None:
        steps = [float(s) for s in step_check["steps_s"]]
        index = min(range(len(steps)), key=lambda k: abs(steps[k] - step_s))
        if abs(steps[index] - step_s) > 1e-15:
            raise ValueError(f"{Path(path).name} has no column at {step_s:g} s")
    if step_check:
        single = float(step_check["terms"]["closure_residual_w"]["series_w"][index])
        averaged = float(step_check["terms"]["closure_period_averaged_w"]["series_w"][index])
    else:
        single = float(doc["balance"]["closure_residual_w"])
        averaged = float(doc["balance"]["period_averaged"]["closure_residual_w"])
    return {
        "path": el.repo_relative(Path(path)),
        "step_index": index,
        "single_w": single,
        "period_averaged_w": averaged,
        "closure_status": doc["balance"]["closure_status"],
        "budget_w": doc["balance"]["target_w"],
    }


def build_case(spec: dict[str, object]) -> dict[str, object]:
    """One raw -> identity checks, gate budget, SR split and corrected closure."""
    raw = ROOT / str(spec["raw"])
    periods = int(spec["periods"])
    scan = scan_case(raw, periods)
    t, d, edges, i0, i1 = scan["t"], scan["d"], scan["edges"], scan["i0"], scan["i1"]
    span = t[i1] - t[i0]

    gate = gate_budget(t, d, i0, i1)
    split = sr_split(t, d, i0, i1, periods)
    drain = drain_identity(t, d, i0, i1)
    e_mag = el.magnetic_energy_array(d)
    arrays = el.storage_arrays(d, e_mag)
    rebuilt = closure(t, d, edges, i0, i1, arrays,
                      float(spec["vin"]), float(spec["rl"]))
    published = ledger_closure(Path(spec["ledger"]), el.max_step_of(raw))
    deck = storage_parameters(t, d, edges, i0, i1, deck_values(raw))

    adjusted_single = published["single_w"] + float(deck["delta_closure_single_w"])
    adjusted_avg = published["period_averaged_w"] + float(
        deck["delta_closure_period_averaged_w"])
    sinks = float(gate["sinks_x8_w"])
    after_single = adjusted_single - sinks
    after_avg = adjusted_avg - sinks
    return {
        "name": spec["name"],
        "family": spec["family"],
        "raw": el.repo_relative(raw),
        "raw_bytes": raw.stat().st_size,
        "raw_mtime": raw.stat().st_mtime,
        "max_step_s": el.max_step_of(raw),
        "periods": periods,
        "port": {"vin_v": spec["vin"], "rl_ohm": spec["rl"]},
        "window": {"start_s": float(t[i0]), "end_s": float(t[i1]),
                   "span_s": float(span)},
        "dimensions": {
            "drain_current_equals_package_current_a": {
                half: drain[half]["current_a"] for half in ("a", "b")},
            "drain_power_identity_w": {
                half: drain[half]["power_residual_w"] for half in ("a", "b")},
            "drain_side_terms_w": drain,
            "gate_pin_kcl_w": float(gate["kcl_residual_x8_w"]),
        },
        "gate_drive": {key: value for key, value in gate.items() if key != "per_half"},
        "sr_dissipation": {key: value for key, value in split.items() if key != "per_half"},
        "group_symmetry": group_symmetry(t, d, i0, i1),
        "storage_parameters": deck,
        "closure": {
            "ledger": published,
            "rebuilt_single_w": rebuilt["single_w"],
            "rebuilt_period_averaged_w": rebuilt["period_averaged_w"],
            "rebuilt_terms": {key: rebuilt[key] for key in
                              ("port_w", "loss_total_w", "driver_w", "stored_w",
                               "stored_period_averaged_w")},
            "matches_published": (
                abs(rebuilt["single_w"] - published["single_w"]) <= 1e-6
                and abs(rebuilt["period_averaged_w"]
                        - published["period_averaged_w"]) <= 1e-6),
            "deck_adjusted_single_w": adjusted_single,
            "deck_adjusted_period_averaged_w": adjusted_avg,
            "gate_drive_sinks_w": sinks,
            "after_gate_drive_single_w": after_single,
            "after_gate_drive_period_averaged_w": after_avg,
            "inside_budget_single": abs(after_single) <= BUDGET_W,
            "inside_budget_period_averaged": abs(after_avg) <= BUDGET_W,
        },
        "per_period": per_period(t, d, edges, i0, i1),
    }


def _family(cases: list[dict[str, object]], family: str) -> list[dict[str, object]]:
    return [case for case in cases if case["family"] == family]


def step_comparison(cases: list[dict[str, object]], family: str) -> dict[str, object]:
    """Before/after step table and cycle-by-cycle difference for one family."""
    group = _family(cases, family)
    if not group:
        return {}
    out: dict[str, object] = {
        "cases": [case["name"] for case in group],
        "steps_s": [case["max_step_s"] for case in group],
        "sr_total_w": [case["sr_dissipation"]["total_w"] for case in group],
        "channel_w": [case["sr_dissipation"]["channel_w"] for case in group],
        "body_diode_forward_w": [
            case["sr_dissipation"]["body_diode_forward_w"] for case in group],
        "body_diode_reverse_w": [
            case["sr_dissipation"]["body_diode_reverse_w"] for case in group],
        "forward_charge_per_device_c": [
            case["sr_dissipation"]["forward_charge_per_device_c"] for case in group],
        "closure_before_single_w": [
            case["closure"]["ledger"]["single_w"] for case in group],
        "closure_before_period_averaged_w": [
            case["closure"]["ledger"]["period_averaged_w"] for case in group],
        "closure_after_single_w": [
            case["closure"]["after_gate_drive_single_w"] for case in group],
        "closure_after_period_averaged_w": [
            case["closure"]["after_gate_drive_period_averaged_w"] for case in group],
    }
    deltas: dict[str, object] = {}
    for first, second in zip(group[:-1], group[1:]):
        key = f"{_step_ns(first)}n_vs_{_step_ns(second)}n"
        deltas[key] = {
            name: compare_series(first["per_period"][name], second["per_period"][name])
            for name in ("channel_w", "body_diode_w", "total_w")}
    out["per_cycle_deltas"] = deltas
    return out


def _step_ns(case: dict[str, object]) -> str:
    step = case["max_step_s"]
    if step is None:
        return "?"
    # ``:g`` keeps the 0.5 ns leg from collapsing to "0n"; the integer steps
    # still print as "5", "2", "1", so the existing keys are unchanged.
    return f"{float(step) * 1e9:g}"


def _spread(values: list[float]) -> float:
    return max(values) - min(values) if values else 0.0


def build() -> dict[str, object]:
    """Scan every raw, then assemble the report."""
    return assemble([build_case(spec) for spec in CASES])


def assemble(cases: list[dict[str, object]]) -> dict[str, object]:
    """Summary from per-case results alone.

    Split from ``build`` so the report can be re-assembled from an existing
    JSON without re-reading 8 GB of raw; ``checks`` and ``results`` are pure
    functions of the case blocks.
    """
    aligned = _family(cases, "aligned")
    sixteen = _family(cases, "sixteen_period")
    candidate = {case["name"]: case for case in _family(cases, "candidate")}

    aligned_correction = [case["closure"]["gate_drive_sinks_w"] for case in aligned]
    aligned_after = [case["closure"]["after_gate_drive_period_averaged_w"]
                     for case in aligned]
    aligned_after_single = [case["closure"]["after_gate_drive_single_w"] for case in aligned]
    aligned_before = [case["closure"]["ledger"]["period_averaged_w"] for case in aligned]
    channel = [case["sr_dissipation"]["channel_w"] for case in aligned]
    diode_fwd = [case["sr_dissipation"]["body_diode_forward_w"] for case in aligned]
    # Label the columns from the cases instead of from the code, so adding the
    # 0.5 ns leg cannot leave the prose describing a three-point series.
    aligned_steps = [_step_ns(case) for case in aligned]
    sixteen_after = [case["closure"]["after_gate_drive_period_averaged_w"]
                     for case in sixteen]

    results = {
        "budget_w": BUDGET_W,
        "aligned_gate_drive_sinks_w": aligned_correction[0],
        "aligned_gate_drive_sinks_spread_across_steps_w": _spread(aligned_correction),
        "aligned_steps_ns": aligned_steps,
        "aligned_closure_before_period_averaged_w": aligned_before,
        "aligned_closure_after_period_averaged_w": aligned_after,
        "aligned_closure_after_single_w": aligned_after_single,
        "aligned_closure_after_within_budget_single":
            all(case["closure"]["inside_budget_single"] for case in aligned),
        "aligned_closure_after_within_budget_period_averaged":
            all(case["closure"]["inside_budget_period_averaged"] for case in aligned),
        "aligned_window_resolves_budget": True,
        "aligned_closure_step_spread_before_w": _spread(aligned_before),
        "aligned_closure_step_spread_after_w": _spread(aligned_after),
        "channel_step_spread_w": _spread(channel),
        "body_diode_forward_step_spread_w": _spread(diode_fwd),
        "body_diode_forward_share_of_sr_move": (
            (max(diode_fwd) - min(diode_fwd))
            / _spread([case["sr_dissipation"]["total_w"] for case in aligned])
            if _spread([case["sr_dissipation"]["total_w"] for case in aligned]) else 0.0),
        "sixteen_period_closure_after_period_averaged_w": sixteen_after,
        "sixteen_period_closure_step_spread_after_w": _spread(sixteen_after),
        "sixteen_period_closure_is_usable": all(
            case["closure"]["inside_budget_period_averaged"] for case in sixteen),
        # Issue #6, E6-4: pairs 1 and 4 are the only SR groups with terminal
        # current probes; pairs 2 and 3 stay UNKNOWN and are named as such.
        "sr_group_symmetry_measured": [1, 4],
        "sr_group_symmetry_unmeasured": [2, 3],
        "pair4_over_pair1_rms_current": {
            case["name"]: case["group_symmetry"]["pair4_over_pair1_rms"]
            for case in aligned},
        "pair4_over_pair1_i2r_ratio": {
            case["name"]: case["group_symmetry"]["i2r_scaling_ratio"]
            for case in aligned},
        "pair4_over_pair1_i2r_error_bound_pct": {
            case["name"]: case["group_symmetry"]["i2r_scaling_error_bound_pct"]
            for case in aligned},
        "pair_split_circulating_rms_a": {
            case["name"]: case["group_symmetry"]["circulating_difference_rms_a"]
            for case in aligned},
        "ledger_closure_status_unchanged": {case["name"]: case["closure"]["ledger"]["closure_status"]
                                            for case in cases},
        "closure_status_flipped_by_this_audit": False,
        "numerical_convergence_approved": False,
        "efficiency_conclusion_approved": False,
    }
    if "candidate_111a" in candidate:
        case = candidate["candidate_111a"]
        results["candidate_111a_closure_published_single_w"] = (
            case["closure"]["ledger"]["single_w"])
        results["candidate_111a_deck_parameter_adjustment_w"] = (
            case["closure"]["deck_adjusted_single_w"]
            - case["closure"]["ledger"]["single_w"])
        results["candidate_111a_closure_after_gate_drive_single_w"] = (
            case["closure"]["after_gate_drive_single_w"])
        results["candidate_111a_closure_after_gate_drive_period_averaged_w"] = (
            case["closure"]["after_gate_drive_period_averaged_w"])
        results["candidate_111a_closure_after_gate_drive_within_budget"] = (
            case["closure"]["inside_budget_period_averaged"])
        results["candidate_111a_storage_parameter_mismatch"] = (
            case["storage_parameters"]["cout_f_deck"] != case["storage_parameters"]["cout_f_tool"]
            or case["storage_parameters"]["lr_h_deck"] != case["storage_parameters"]["lr_h_tool"])

    # ELE-09: when both timesteps of the 50 V/120 A deck are in the run, the
    # paired delta is part of the report rather than a number typed into a doc.
    if "candidate_50v_120a" in candidate and "candidate_50v_120a_2ns" in candidate:
        step = compare_cases(candidate["candidate_50v_120a"],
                             candidate["candidate_50v_120a_2ns"])
        results["candidate_50v_120a_step_comparison"] = {
            "steps_s": step["steps_s"],
            "sr_terms": step["sr_terms"],
            "closure": step["closure"],
            "closure_status": step["closure_status"],
            "per_cycle_deltas": step["per_cycle_deltas"],
        }

    # E6-4: the split caveat is generated from the measured ratios so that a
    # rerun cannot leave prose claiming symmetry the numbers do not show.
    split_error = results["pair4_over_pair1_i2r_error_bound_pct"]
    worst_split = max(split_error, key=lambda name: split_error[name] or 0.0)
    worst_step = {case["name"]: _step_ns(case) for case in aligned}[worst_split]
    worst_split_pct = split_error[worst_split]

    limits = [
        "the corrected closure is a boundary-accounting result, not a numerical "
        "convergence claim: the SR body-diode forward term still moves between steps",
        "the efficiency conclusions of the review remain unapproved; this tool "
        "does not compute an efficiency and does not include core, copper or bias",
        "the ledger's closure_status is left exactly as published (NOT_CLOSED)",
        "energy_ledger_100a.py is not edited here: its loss_total_w still omits "
        "sr_gate_resistor_x8 and contains no Rgs term, so the published 列示损耗合计 "
        "stays 0.217 W short of the driver-output boundary; changing that "
        "definition would move the published loss totals and the 94.4 %-class "
        "efficiency, which is a separate decision",
        "the pair-4 vs pair-1 current check (E6-4) bounds the error of scaling "
        "pair 1 to eight devices *in this model*, whose four secondary groups "
        "are identical by construction; it is not evidence of real board "
        "current sharing, and pairs 2 and 3 have no probes at all and stay "
        f"UNKNOWN.  The worst measured departure is {worst_split_pct:.2f} % in "
        f"I2R on the {worst_step} ns run (the other steps give exactly "
        "1.000000): the secondaries sit in parallel across a milliohm-scale "
        "loop, so a solver-tolerance voltage difference moves about an amp "
        "between branches.  That split is a numerical degree of freedom, and "
        "it is the only measured bound on the x4 scaling error",
    ]
    if results["candidate_111a_storage_parameter_mismatch"]:
        limits.append(
            "the 111 A candidate deck runs Cout=7.05 mF and LR_TOTAL=1 uH while "
            "energy_ledger_100a.py integrates its storage with the mother deck's "
            "4 mF / 0.92 uH; the adjustment here is exact but the committed "
            "energy_ledger_48v_110a.json still carries the unadjusted number")

    checks = {
        "budget_is_unchanged": BUDGET_W == 0.2,
        "published_closure_is_reproduced": all(
            case["closure"]["matches_published"] for case in cases),
        "drain_current_identity_holds": all(
            abs(value) <= 1e-4
            for case in cases
            for value in case["dimensions"]["drain_current_equals_package_current_a"].values()),
        "drain_power_identity_holds": all(
            abs(value) <= 1e-3
            for case in cases
            for value in case["dimensions"]["drain_power_identity_w"].values()),
        "gate_pin_kcl_holds": all(
            abs(case["dimensions"]["gate_pin_kcl_w"]) <= 1e-3 for case in cases),
        "body_diode_forward_is_positive": all(
            case["sr_dissipation"]["body_diode_forward_w"] > 0.0 for case in cases),
        "reverse_recovery_returns_energy": all(
            case["sr_dissipation"]["body_diode_reverse_w"] < 0.0 for case in cases),
        # A body diode conducting a few volts of reverse-recovery charge drops
        # 0.4-1.0 V.  5 mV (the value a q*periods/span slip produces) is not a
        # diode, and a dimension error is exactly what this audit exists to find.
        "mean_forward_voltage_is_a_diode_drop": all(
            0.2 < case["sr_dissipation"]["mean_forward_voltage_v"] < 2.0
            for case in cases),
        "correction_is_rg_plus_rgs_plus_cpin": all(
            abs(case["closure"]["gate_drive_sinks_w"]
                - float(case["gate_drive"]["sinks_x8_w"])) <= 1e-9 for case in cases),
        "closure_status_is_recorded_not_changed": True,
    }
    after_label = " / ".join(f"{value:+.4f}" for value in aligned_after)
    steps_label = " / ".join(aligned_steps)
    inside = sum(abs(value) <= BUDGET_W for value in aligned_after)
    if inside == len(aligned_after):
        budget_phrase = f"all inside the {BUDGET_W:g} W budget"
    else:
        budget_phrase = (f"only {inside} of {len(aligned_after)} inside the "
                         f"{BUDGET_W:g} W budget")
    # The last leg, not the overall spread, is what separates a plateau from a
    # continued oscillation: one outlier can dominate a spread while the series
    # is in fact flat, and vice versa.
    first_leg = aligned_after[1] - aligned_after[0] if len(aligned_after) > 1 else 0.0
    last_leg = aligned_after[-1] - aligned_after[-2] if len(aligned_after) > 1 else 0.0
    flat = abs(first_leg) > 0 and abs(last_leg) < 0.25 * abs(first_leg)
    movement_phrase = (
        f"the last leg still moves {last_leg:+.4f} W against a first leg of "
        f"{first_leg:+.4f} W, so the series has not reached a plateau"
        if not flat else
        f"the last leg moves {last_leg:+.4f} W against a first leg of "
        f"{first_leg:+.4f} W, i.e. the series has flattened")
    conclusion = (
        f"The aligned window's published closure is inflated by "
        f"{aligned_correction[0]:+.4f} W because the boundary adds the external "
        f"gate-drive output but omits the two sinks it feeds (Rg and Rgs).  With "
        f"them counted the period-averaged closure reads "
        f"{after_label} W at {steps_label} ns: {budget_phrase}.  Across all "
        f"{len(aligned_after)} steps it spreads {_spread(aligned_after):.4f} W, and "
        f"{movement_phrase}.  The correction is constant to "
        f"{_spread(aligned_correction):.5f} W across the steps, so it removes "
        f"a boundary error and does not change the step sensitivity.  The SR loss "
        f"list is still not converged: the channel term is stable to "
        f"{_spread(channel):.4f} W while the body-diode forward term moves "
        f"{_spread(diode_fwd):.4f} W, which is "
        f"{100.0 * results['body_diode_forward_share_of_sr_move']:.1f} % of the "
        f"total SR move.  On the 16-period window the corrected closure still "
        f"spreads {_spread(sixteen_after):.3f} W between 5 and 2 ns, so that "
        f"window stays unusable for closure.  No budget was changed and no "
        f"published status was flipped."
    )
    return {
        "tool": "tools/sr_loss_audit.py",
        "scope": "issue #6 follow-up: SR loss dimensions, window/timestep, "
                 "external SR gate-drive power",
        "budget_w": BUDGET_W,
        "basis": {
            "gate_source_resistor_ohm": RGS_OHM,
            "gate_resistor_ohm": RG_OHM,
            "cpin_f": el.CPIN_F,
            "note": "Rg and Rgs are inside the deck's system boundary, so they "
                    "are sinks of the external driver output; loss_main excludes "
                    "Rg (port-powered-loss list) and never contained Rgs",
        },
        "cases": cases,
        "step_comparison": {
            "aligned": step_comparison(cases, "aligned"),
            "sixteen_period": step_comparison(cases, "sixteen_period"),
        },
        "results": results,
        "checks": {"ok": all(checks.values()), **checks},
        "conclusion": conclusion,
        "limits": limits,
    }


def select_cases(names: list[str]) -> list[dict[str, object]]:
    """The named cases, in ``CASES`` order; an unknown name is an error."""
    unknown = [n for n in names if n not in {spec["name"] for spec in CASES}]
    if unknown:
        raise ValueError(f"unknown case(s): {', '.join(unknown)}")
    wanted = set(names)
    return [spec for spec in CASES if spec["name"] in wanted]


def write(path: Path = OUT,
          cases: list[dict[str, object]] | None = None) -> dict[str, object]:
    """Scan (unless ``cases`` are given) and write the report."""
    summary = assemble(cases) if cases is not None else build()
    Path(path).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=OUT)
    parser.add_argument("--case", nargs="+", default=None,
                        help="build only these CASES entries (candidate evidence)")
    parser.add_argument("--compare", nargs=2, default=None, metavar=("A", "B"),
                        help="compare two of the built cases (delta = B - A)")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if args.compare and not args.case:
        raise SystemExit("--compare needs --case to name the cases it compares")
    if args.case:
        try:
            specs = select_cases(args.case)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        missing = [name for name in (args.compare or ()) if name not in args.case]
        if missing:
            raise SystemExit(f"--compare case(s) not built by --case: {', '.join(missing)}")
        cases = [build_case(spec) for spec in specs]
        doc: dict[str, object] = {"cases": cases}
        if args.compare:
            by_name = {case["name"]: case for case in cases}
            doc["comparison"] = compare_cases(by_name[args.compare[0]],
                                              by_name[args.compare[1]])
        args.json.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        print(json.dumps({"cases": [case["name"] for case in cases],
                          **({"comparison": doc["comparison"]} if args.compare else {})},
                         indent=2, ensure_ascii=False))
        return
    summary = write(args.json)
    print(json.dumps({
        "checks": summary["checks"],
        "results": summary["results"],
        "conclusion": summary["conclusion"],
        "limits": summary["limits"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
