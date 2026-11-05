"""D0 rise/fall time budget: what the measurement already contains, and what it cannot.

Issue #36's P0-3 asks for a rising/falling time budget after the "this channel
is faster" claim was withdrawn.  The trap in building one is double-counting:
``design/v3/stage_f/d0_trip_timing.json`` measures the burden and *both* OC RC
poles on the deck, so that delay already is the detection term.  Summing the
pole list on top of it would turn the 10.21 us fast channel into a 130 us one.

What is left after detection is short and mostly arithmetic:

* the LM393 comparator, whose only published figure is a typical;
* the CD4013 latch, driving its output down from SET;
* the permit rail, discharged by whatever sits between it and ground;
* the driver's own disable time, which both vendored datasheets publish --
  and, for the UCC27524A, the logic table that settles what the output does
  when its enable goes low;
* the gate falling from the driver supply to VGS(th).

The result is a **floor**, not a worst case, and the tool says so in the JSON
rather than leaving a reader to assume otherwise.

Usage:
    python tools/d0_response_budget.py --output design/v3/stage_f/d0_response_budget.json
    python tools/d0_response_budget.py --require-complete   # exit 1 today
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import make_d0_protection_board as board
from d0_analog_preflight import SR_VGS_TH_MIN_V

# PERMIT_RAIL is the drain of a PMOS whose source is V5, so the rail's high
# level is the 5 V rail -- not the 12 V the drivers run from.  Using 12 V here
# would lengthen every EN delay by ln(12/x)/ln(5/x) and mis-state the enable
# margin (VEN max is 2.0 V, so 5 V leaves 3 V).
V5_RAIL_V = 5.0
RAIL_SOURCE_NET = "V5"
# Both driver supplies are the 12 V bench rails: U18 on V12P, the UCC27524As on
# V12S.  The gate sits here before it is discharged.
DRIVER_VDD_V = 12.0

# UCC27282 ENABLE table, SNVSAQ5B, vendored as references/datasheets/ucc27282.txt.
# VDIS is min/max across parts, so the two ends bracket the delay instead of
# one value pretending to be both: the latest a pin can still read enabled is
# 1.21 V, the earliest it must read disabled is 0.70 V.
# Section 7.3.1 also settles the direction this tool used to get wrong by
# omission: EN's 250 k sits between the pin *and VSS*, so the UCC27282 is a
# pull-down and an open EN disables it.  The eight UCC27524A EN pins are the
# opposite -- see UCC27524A_EN_PULLUP below.
UCC27282_VDIS_MAX_V = 1.21
UCC27282_VDIS_MIN_V = 0.70
UCC27282_VEN_MIN_V = 1.54
UCC27282_REN_OHM = 250e3
UCC27282_TDIS_US = 1.5
UCC27282_TEN_US = 18.0
UCC27282_SOURCE = "references/datasheets/ucc27282.txt (SNVSAQ5B, ENABLE table)"

# The eight SR drivers pull the other way.  Each UCC27524A ENA/ENB has an
# internal ~200 k pull-up to its own VDD, i.e. to 12 V, and that is the reason
# the 4.7 k pull-downs exist at all (doc 15 section 0.3).  The new part table
# carries UCC27524ADR, the D package, so the numbers below are that package's
# columns in SLUSBP4C: the DGN part publishes 17/27 ns for the same parameter.
# RENx is given as a single typical -- no min/max -- so the ceiling it produces
# carries the same caveat.
SR_CHANNELS = 8
# The eight EN pull-downs are R36..R43 in the generator's part table.
SR_EN_PULLDOWN_REFS = tuple(f"R{n}" for n in range(36, 36 + SR_CHANNELS))
UCC27524A_PACKAGE = "D (SOIC-8), the UCC27524ADR on this board"
UCC27524A_EN_PULLUP_TYP_OHM = 200e3
UCC27524A_EN_TO_OUT_MAX_NS = 23.0
UCC27524A_EN_TO_OUT_TYP_NS = 13.0
# D-package ENABLE table: VEN_L 0.95/1.15/1.35 V, VEN_H 1.9/2.1/2.3 V, and the
# hysteresis column 0.7/0.95/1.1 V.  A pin still reading enabled at 1.35 V is
# the *latest* it can be, so that is the threshold the rail has to cross for the
# SR branch -- and it is crossed before the UCC27282's 1.21 V, not after.
UCC27524A_VEN_L_MAX_V = 1.35
UCC27524A_VEN_H_MIN_V = 1.90
# Table 6-2 (Device Logic Table): ENA=L, ENB=L gives OUTA=L, OUTB=L, and the
# single-low rows leave the enabled channel following its input -- the disabled
# output is driven low, not tri-stated.  The tD4 test condition says the same
# thing operationally: "VENx_L of the enable fall to 90% of output fall".
UCC27524A_OUTPUT_STATE_ON_DISABLE = "low"
UCC27524A_SOURCE = ("references/datasheets/ucc27524a.txt (SLUSBP4C, revised June 2024; "
                    "ENABLE and Switching Characteristics tables, Device Logic "
                    "Table 6-2)")

# LM393, vendored as references/datasheets/lm393.txt (SLCS005AH, revised April
# 2025).  Section 5.11 is a TYP-only table -- VCC = 5 V, 25 C, 5.1 k to 5 V,
# CL = 15 pF -- and it publishes two numbers: 1.3 us for a 100 mV step with
# 5 mV overdrive and 0.3 us for a TTL-level step.  The non-B part has no
# maximum column at all, so this stage can only make the totals longer than the
# floor, never shorter.  The budget takes the slower published typical.
LM393_RESPONSE_TYP_US = 1.3
LM393_LARGE_OVERDRIVE_TYP_US = 0.3
LM393_SOURCE = ("references/datasheets/lm393.txt (SLCS005AH, revised April 2025; "
                "section 5.11 Switching Characteristics)")

# CD4013B, vendored as references/datasheets/cd4013b.txt (SCHS023E, revised
# September 2016).  FF1 has SET = FLT and its ~Q is the permit term, so the
# fault drives the output *down*: the applicable row is section 6.6's "tPHL,
# Set to Q or reset to Q", 200 typ / 400 max ns at VDD = 5 V.  The clock-to-Q
# row (150/300 ns) would understate a path whose clock and D are tied off.
CD4013B_VDD_V = 5.0
CD4013B_SET_TO_OUTPUT_TYP_NS = 200.0
CD4013B_SET_TO_OUTPUT_MAX_NS = 400.0
CD4013B_SOURCE = ("references/datasheets/cd4013b.txt (SCHS023E, revised September "
                  "2016; section 6.6 Electrical Characteristics: Dynamic, VDD = 5 V)")

# Section 7.2.2.4 splits the two output edges: the rise is R_PULLUP * C_L, the
# fall is R_CE * C_L.  Only the rise can be moved by the resistor to 5 V, so
# the 1.3 us above -- measured through a 5.1 k -- constrains this board's 10 k
# pull-ups only on the channels whose fault makes the output rise.  The two
# comparators the measured detection stops at are among them (their sense node
# is IN+, so a trip lifts the output), which is why the mismatch is priced here
# rather than written off.
LM393_CITED_PULLUP_OHM = 5.1e3
LM393_CITED_LOAD_F = 15e-12
# Which way a fault moves each comparator's sense node.  The three threshold
# comparators read the burden or the gate maximum, so a fault raises the node;
# the three rail supervisors read a healthy-rail divider, so a fault lowers it.
# Named explicitly and checked against the part table for the same reason the
# eight enable pull-downs are: a swapped pin has to break the tool rather than
# be silently re-priced on the old edge.
COMPARATOR_FAULT_DIRECTION = {
    ("U3", 1): ("OC", "rising"),
    ("U3", 2): ("OC_FILT", "rising"),
    ("U4", 1): ("V12P_SNS", "falling"),
    ("U4", 2): ("V12S_SNS", "falling"),
    ("U5", 1): ("V5_SNS", "falling"),
    ("U5", 2): ("GATE_SENSE", "rising"),
}
# The measured detection term ends at these two inputs (design/v3/stage_f/
# d0_trip_timing.json reads V(oc) and V(ocdf)), so their output edge is the one
# the comparator stage pays for.  The other four sit outside this budget.
PRICED_COMPARATORS = (("U3", 1), ("U3", 2))


def _parallel(*resistances: float) -> float:
    return 1.0 / sum(1.0 / r for r in resistances if r)


def _resistors_on(parts, net_a: str, net_b: str) -> list:
    return [p for p in parts.values() if p.lib == "Device:R"
            and set(p.nets.values()) == {net_a, net_b}]


def _capacitor_on(parts, net: str) -> float:
    """The capacitance the part table puts from ``net`` to ground, in farads."""
    total = 0.0
    for part in parts.values():
        if part.lib == "Device:C" and set(part.nets.values()) == {net, "PGND"}:
            total += board.capacitance(part.value)
    return total


def permit_rail_release(parts: dict) -> dict:
    """How long the permit rail takes to cross the driver's disable threshold.

    Every resistor from PERMIT_RAIL to PGND discharges it, and eight resistors
    from it to the 12 V rail charge it back.  The former are the UCC27524A
    ENA/ENB pull-downs, which exist to defeat that chip's internal 200 k
    pull-up to *enable* -- they are 94 % of the discharge conductance here, so
    the rail's fall time is a side effect of a default-off decision made
    elsewhere.  The drawn R44/C28 filter is not the limiting term.

    The pull-ups mean the rail does not decay to zero: it decays to the
    Thevenin ceiling of that divider, ~0.26 V.  That is comfortably under VDIS
    max, so the release still happens -- but the ceiling is what makes the
    corner case readable.  Delete the eight pull-downs and the 200 k pull-ups
    win the divider outright: the node parks near 3.1 V, above both VDIS and
    VEN, and the permit rail stops being a permit rail.
    """
    q2 = parts["Q2"]
    source_net = q2.nets["2"]
    if source_net != RAIL_SOURCE_NET:
        raise SystemExit(f"Q2 source is {source_net}, not {RAIL_SOURCE_NET}: "
                         "the permit rail no longer rides the 5 V rail")
    # The pull-downs are named by reference, not recognised by value: a value
    # filter silently drops a resistor somebody changed, which is exactly the
    # case this function exists to price.  The nets are still checked.
    sr_pull = []
    for ref in SR_EN_PULLDOWN_REFS:
        part = parts.get(ref)
        if part is None or part.lib != "Device:R" or set(part.nets.values()) != {
                "PERMIT_RAIL", "PGND"}:
            raise SystemExit(f"{ref} is no longer a PERMIT_RAIL/PGND resistor; "
                             "the SR enable pull-downs moved")
        sr_pull.append(part)
    r_known = [board.resistance(p.value) for p in sr_pull]
    c_rail = _capacitor_on(parts, "PERMIT_RAIL")
    # Everything on the node, whether or not it is one of the eight.
    r_others = [board.resistance(p.value)
                for p in _resistors_on(parts, "PERMIT_RAIL", "PGND")
                if p.ref not in SR_EN_PULLDOWN_REFS]

    r_down = _parallel(*(r_known + r_others + [UCC27282_REN_OHM]))
    r_down_without = _parallel(*(r_others + [UCC27282_REN_OHM]))
    r_up = UCC27524A_EN_PULLUP_TYP_OHM / SR_CHANNELS

    def ceiling(r_lower: float) -> float:
        return DRIVER_VDD_V * r_lower / (r_lower + r_up)

    ceiling_v = ceiling(r_down)
    ceiling_without = ceiling(r_down_without)
    # The node relaxes toward its ceiling, so the Thevenin resistance -- not the
    # pull-down sum -- sets the time constant.
    r_th = _parallel(r_down, r_up)

    def cross(v_th: float) -> float | None:
        # A rail above its own ceiling does not "take longer" -- it never
        # arrives.  Return nothing rather than a time for an event that cannot
        # happen; build() is where the committed design is held to crossing.
        if v_th <= ceiling_v:
            return None
        return r_th * c_rail * math.log((V5_RAIL_V - ceiling_v) / (v_th - ceiling_v)) * 1e6

    fastest = cross(UCC27282_VDIS_MAX_V)
    guaranteed = cross(UCC27282_VDIS_MIN_V)
    # The rail feeds both driver families, and each one disables on its own pin
    # threshold.  UCC27282's latest-still-enabled point is 1.21 V; the
    # UCC27524A's is 1.35 V (D package).  Both ride the same RC, so the crossing
    # order follows from the thresholds alone: the eight SR drivers stop reading
    # enabled *before* the primary pair does, not after.
    sr_release = cross(UCC27524A_VEN_L_MAX_V)
    conductance_share = sum(1.0 / r for r in r_known) / sum(
        1.0 / r for r in r_known + r_others + [UCC27282_REN_OHM])
    return {
        "enable_rail_v": V5_RAIL_V,
        "rail_source_net": source_net,
        "discharge_ohm": r_down,
        "sr_pullup_ohm": r_up,
        "sr_pullup_is_a_typical_not_a_guarantee": True,
        "thevenin_ohm": r_th,
        "ceiling_v": ceiling_v,
        # Stated both ways because the two questions are asked separately: the
        # release needs the ceiling *below* VDIS max, and a review of a weakened
        # divider wants to see it has climbed *above* it.
        "ceiling_below_vd_is_max": ceiling_v < UCC27282_VDIS_MAX_V,
        "ceiling_above_vd_is_max": ceiling_v > UCC27282_VDIS_MAX_V,
        "ceiling_below_ven_min": ceiling_v < UCC27282_VEN_MIN_V,
        "ven_min_v": UCC27282_VEN_MIN_V,
        "specified_capacitance_f": c_rail,
        "tau_us": r_th * c_rail * 1e6,
        "vd_is_max_v": UCC27282_VDIS_MAX_V,
        "vd_is_min_v": UCC27282_VDIS_MIN_V,
        "fastest_us": fastest,
        "guaranteed_us": guaranteed,
        "fastest_uses_vd_is_max": True,
        "guaranteed_uses_vd_is_min": True,
        "sr_pulldown_count": len(sr_pull),
        "sr_pulldowns_carry_most_of_the_discharge": conductance_share > 0.8,
        "sr_pulldown_conductance_share": conductance_share,
        "without_pulldowns_ceiling_v": ceiling_without,
        "without_pulldowns_never_disables": ceiling_without > UCC27282_VDIS_MAX_V,
        "filter_to_tdis_ratio": (None if fastest is None
                                 else fastest / UCC27282_TDIS_US),
        "pin_capacitance_unknown_so_this_is_a_floor": True,
        "sr_pin_capacitance_known": False,
        "sr_driver_ven_l_max_v": UCC27524A_VEN_L_MAX_V,
        "sr_driver_release_us": sr_release,
        "sr_driver_release_precedes_ucc27282": (
            None if sr_release is None or fastest is None else sr_release < fastest),
        "sr_driver_release_reason": (
            "the UCC27524A's EN pin capacitance is unpublished, so the 1 nF "
            "counted here is C28 only and extra pin capacitance only lengthens "
            "the fall; the eight EN pins do reach this node directly"),
    }


def _detector_branch_resistor(parts, gate_net: str):
    """The 1k from a gate to its BAT54 -- the detector's own path to ground.

    Found by topology, not by reference or value: a resistor from the gate to a
    node that a Schottky ties to GSMAX.  The series element inside this branch
    is *not* the 2.2 ohm gate resistor, which sits between the driver and the
    gate and is not in the gate-to-ground path at all; adding it instead of this
    1k understates the fall by 0.9 %.
    """
    by_net: dict[str, list] = {}
    for part in parts.values():
        for node in part.nets.values():
            by_net.setdefault(node, []).append(part)
    for part in parts.values():
        if part.lib != "Device:R" or gate_net not in part.nets.values():
            continue
        other = next(n for n in part.nets.values() if n != gate_net)
        if any(neighbour.lib == "Device:D_Schottky"
               and "GSMAX" in neighbour.nets.values()
               for neighbour in by_net.get(other, [])):
            return part
    return None


def gate_discharge(parts: dict, gate_net: str) -> dict:
    """Time for one gate to fall below VGS(th) with and without a live driver.

    The point is not the nanoseconds: it is that a gate whose driver is
    unpowered discharges through the 10k pull-down alone, which is three
    orders of magnitude slower.  That is the state the gate-max detector is
    watching for, and it is also why the detector reads a *falling* gate for a
    long time.
    """
    load = 0.0
    for part in parts.values():
        if part.lib == "Device:C" and set(part.nets.values()) == {gate_net, "PGND"}:
            load += board.capacitance(part.value)
    pulldown = [p for p in parts.values() if p.lib == "Device:R"
                and set(p.nets.values()) == {gate_net, "PGND"}]
    series = [p for p in parts.values() if p.lib == "Device:R"
              and gate_net in p.nets.values()
              and "PGND" not in p.nets.values()]
    detector_resistor = _detector_branch_resistor(parts, gate_net)
    if not load or not pulldown or not series or detector_resistor is None:
        raise SystemExit(f"{gate_net}: the part table no longer shows a load, a "
                         "pull-down, a series gate resistor and a detector branch")
    r_pull = board.resistance(pulldown[0].value)
    r_gate = board.resistance(series[0].value)
    detector_branch = (board.resistance(detector_resistor.value)
                       + board.resistance(board.part_value("R76"))
                       + board.resistance(board.part_value("R77")))
    r_effective = _parallel(r_pull, detector_branch)
    log_term = math.log(DRIVER_VDD_V / SR_VGS_TH_MIN_V)
    return {
        "gate_net": gate_net,
        "gate_load_nf": load * 1e9,
        "gate_resistor_ohm": r_gate,
        "detector_branch_ref": detector_resistor.ref,
        "detector_branch_ohm": detector_branch,
        "pulldown_ohm": r_effective,
        "gate_high_v": DRIVER_VDD_V,
        "to_vgs_th_min_v": SR_VGS_TH_MIN_V,
        "with_driver_ns": r_gate * load * log_term * 1e9,
        "with_driver_ns_is_a_floor": True,
        "with_driver_omits": ("the driver's internal sink resistance: the vendored "
                              "UCC27282 text names RHOL/RLOL but publishes no value"),
        "pulldown_only_us": r_effective * load * log_term * 1e6,
        "pulldown_only_omits": ("nothing but the detector branch, which is a DC path "
                                "to ground as well; the diode drop only shortens the "
                                "exponent's effective start"),
    }


def comparator_pull_up(parts: list) -> dict:
    """Which output edge the cited 1.3 us covers, and what this board changes.

    Section 5.11 measured it through a 5.1 k pull-up with 15 pF; every LM393
    output here rides a 10 k.  Section 7.2.2.4 is what makes that a priced
    difference instead of a shrug: the rise is R_PULLUP * C_L and the fall is
    R_CE * C_L, so only a channel that asserts by rising can be slowed by the
    resistor.  Per section 7.2.2.1 the output sinks while IN+ is below IN-, so
    with the sense node on IN+ a rising fault lifts the output.

    The added term is a time constant, not a delay: the interval ends when the
    output crosses 1.4 V, which is a fraction of the way through the rise, so
    quoting the whole constant over-states rather than under-states.  It is
    exact in the datasheet's C_L and linear in the real one, which is not
    measured here.
    """
    channels = {}
    for part in parts:
        if part.lib == "Comparator:LM2903" and ("1" in part.nets or "7" in part.nets):
            channels[(part.ref, part.unit)] = part

    edges = {}
    pull_ups = {}
    for key, (sense_net, direction) in COMPARATOR_FAULT_DIRECTION.items():
        part = channels.get(key)
        if part is None:
            raise SystemExit(f"{key[0]} unit {key[1]} is gone: the comparator "
                             "topology changed and the edge table no longer applies")
        letter = "A" if key[1] == 1 else "B"
        name = f"{key[0]}{letter}"
        out_pin = "1" if "1" in part.nets else "7"
        in_plus = part.nets["3" if out_pin == "1" else "5"]
        if in_plus != sense_net:
            raise SystemExit(
                f"{name}'s non-inverting input is {in_plus}, not the declared sense "
                f"node {sense_net}: the outputs invert, so the fault edge is the "
                "other one and the cited typical does not cover it")
        # Sense on IN+ and the output high when IN+ is higher (7.2.2.1), so the
        # fault's own direction is the output's.
        edges[name] = direction
        out_net = part.nets[out_pin]
        resistors = [p for p in parts if p.lib == "Device:R"
                     and set(p.nets.values()) == {"V5", out_net}]
        if len(resistors) != 1:
            raise SystemExit(f"{out_net} has {len(resistors)} pull-ups to V5, "
                             "expected exactly one")
        pull_ups[name] = board.resistance(resistors[0].value)

    if len(set(pull_ups.values())) != 1:
        raise SystemExit(f"the comparator pull-ups differ ({pull_ups}); price the "
                         "channels this budget covers instead of one average")
    r_pull = next(iter(pull_ups.values()))
    added_tau_s = max(0.0, r_pull - LM393_CITED_PULLUP_OHM) * LM393_CITED_LOAD_F
    priced = [f"{ref}{'A' if unit == 1 else 'B'}" for ref, unit in PRICED_COMPARATORS]
    return {
        "output_pull_up_ohm": r_pull,
        "cited_test_pull_up_ohm": LM393_CITED_PULLUP_OHM,
        "cited_test_load_capacitance_f": LM393_CITED_LOAD_F,
        "pull_up_is_larger_than_the_cited_condition": r_pull > LM393_CITED_PULLUP_OHM,
        "fault_output_edges": edges,
        "priced_channels": priced,
        "priced_channels_all_assert_by_a_rise": all(
            edges[name] == "rising" for name in priced),
        "pull_up_independent_channels": sorted(
            name for name, edge in edges.items() if edge == "falling"),
        "the_cited_figure_covers_the_edge_the_priced_channels_use": all(
            edges[name] == "rising" for name in priced),
        "pull_up_added_time_constant_s": added_tau_s,
        "pull_up_added_time_constant_us": added_tau_s * 1e6,
        "pull_up_added_time_constant_fraction_of_the_cited_typical": (
            added_tau_s * 1e6 / LM393_RESPONSE_TYP_US),
        "added_term_is_proportional_to_load_capacitance": True,
        "added_term_is_a_time_constant_not_a_delay": True,
        "load_capacitance_measured": False,
    }


def build() -> dict:
    part_list = board.parts()
    by_ref = {p.ref: p for p in part_list}
    measured = board.trip_timing_record()
    if measured is None:
        raise SystemExit("design/v3/stage_f/d0_trip_timing.json is missing: the "
                         "detection term is measured, not remembered")
    release = permit_rail_release(by_ref)
    # The board is allowed to be reviewed with a divider that parks the rail
    # above VDIS -- that review is the whole point of the ceiling keys -- but the
    # *committed* design has to actually release.  Downstream totals are times,
    # so a rail that never crosses would quietly become a TypeError instead of a
    # verdict; refuse here instead.
    if release["fastest_us"] is None:
        raise SystemExit(
            f"the released permit rail parks at {release['ceiling_v']:.3f} V, at or "
            f"above VDIS max {release['vd_is_max_v']} V: the drivers never read "
            "disabled and the response budget has no response to budget")
    sr_gate = gate_discharge(by_ref, "GA1")
    primary_gate = gate_discharge(by_ref, "GH1")
    # Both driver branches hang off the same rail and run in parallel, so "all
    # ten gates low" is the slower of the two, never their sum.  Each branch
    # waits for *its own* pin threshold to be crossed, and the primary is slower
    # both at the rail (1.21 V vs 1.35 V) and at TDIS (1.5 us vs 23 ns).
    sr_branch_us = (release["sr_driver_release_us"]
                    + UCC27524A_EN_TO_OUT_MAX_NS / 1e3
                    + sr_gate["with_driver_ns"] / 1e3)
    primary_branch_us = (release["fastest_us"] + UCC27282_TDIS_US
                         + primary_gate["with_driver_ns"] / 1e3)
    driver_branch_us = max(sr_branch_us, primary_branch_us)
    # Detection stops at the comparator input -- the deck's own header says its
    # comparator, logic and driver delays are ideal zero.  So everything after
    # detection is in series: comparator, latch, permit rail, driver, gate.  The
    # two driver branches are the only parallel pair, and they are resolved
    # inside ``driver_branch_us``.
    comparator_us = LM393_RESPONSE_TYP_US
    latch_us = CD4013B_SET_TO_OUTPUT_MAX_NS / 1e3
    shared_us = comparator_us + latch_us + driver_branch_us
    totals = {
        "hard_channel_floor_us": measured["hard_delay_us"] + shared_us,
        "fast_channel_floor_us": measured["fast_delay_us"] + shared_us,
        "shared_after_detection_us": shared_us,
        "driver_branch_us": driver_branch_us,
        "sr_branch_floor_us": sr_branch_us,
        "primary_branch_floor_us": primary_branch_us,
        "slowest_branch": "primary" if primary_branch_us >= sr_branch_us else "sr",
        "detection_advantage_us": measured["hard_delay_us"] - measured["fast_delay_us"],
    }
    return {
        "kind": "D0_RESPONSE_TIME_BUDGET",
        "status": "RESPONSE_BUDGET_INCOMPLETE",
        "is_worst_case": False,
        "not_worst_case_because": [
            "the LM393 publishes no maximum response time at all -- 1.3 us is a "
            "typical at 5 mV overdrive, and the datasheet itself shows the figure "
            "rising as overdrive falls, so a slow part lengthens every total",
            "the CD4013 stage is a max (400 ns), but only at VDD = 5 V and 25 C "
            "with a 20 ns input edge; it is not a max over the full temperature "
            "range at this board's edge rate",
            "the UCC27524A's switching parameters are not tested in production (the "
            "datasheet says so itself), and its 13/23 ns are specified at VDD = 12 V, "
            "CLOAD = 1.8 nF and 125 C, not over the part-to-part spread",
            "the eight 200 k pull-ups that set the permit rail's ceiling are a "
            "typical with no published min or max, so the 0.26 V ceiling is a "
            "nominal figure rather than a guaranteed bound",
            "the gate fall omits the driver's internal sink resistance, which adds time",
            "the comparator's 1.3 us was measured through a 5.1 k pull-up and 15 pF; "
            "this board uses 10 k, and the added time constant scales with the load "
            "capacitance, which is not measured -- the priced 73.5 ns is what the "
            "datasheet's own C_L produces, not what this layout produces",
            "no temperature or device spread is applied: every value is a nominal "
            "part-table arithmetic, not a worst-case-over-temperature figure",
        ],
        "stages": {
            "detection": {
                "hard_us": measured["hard_delay_us"],
                "fast_us": measured["fast_delay_us"],
                "source": "measured",
                "measured_by": "design/v3/stage_f/d0_trip_timing.json",
                "contains_the_rc_poles": True,
                "contains": ["burden", "oc_stage_1", "oc_stage_2", "fast_filter"],
                "note": ("the deck runs the real RC network, so the pole constants are "
                         "already inside these two numbers; adding them again would "
                         "double-count 47 us and 75 us"),
            },
            "comparator": {
                "us": comparator_us,
                "typ_only": True,
                "published_max_us": None,
                "large_overdrive_typ_us": LM393_LARGE_OVERDRIVE_TYP_US,
                "source": LM393_SOURCE,
                "conditions": ("VCC = 5 V, TA = 25 C, RL 5.1 k to 5 V, CL = 15 pF; "
                               "the cited value is the 100 mV step with 5 mV "
                               "overdrive, and the interval ends when the output "
                               "crosses 1.4 V"),
                "overdrive_at_the_threshold_crossing": "unknown",
                "reason_typ_only": ("section 5.11 has a TYP column and no MAX for the "
                                    "non-B part, so a slower comparator makes every "
                                    "total longer than this floor"),
                **comparator_pull_up(part_list),
            },
            "latch": {
                "us": latch_us,
                "typ_us": CD4013B_SET_TO_OUTPUT_TYP_NS / 1e3,
                "vdd_v": CD4013B_VDD_V,
                "edge": "set to ~Q output falling (tPHL)",
                "source": CD4013B_SOURCE,
                "wiring": ("FF1 on this board: SET = FLT, RESET = RST_EFF, clock and D "
                           "tied off, and ~Q is the permit term"),
                "conditions": ("VDD = 5 V, TA = 25 C, CL = 50 pF, RL = 20 k, input "
                               "tr/tf = 20 ns"),
            },
            "permit_release": release,
            "driver_disable": {
                "ucc27282_tdis_us": UCC27282_TDIS_US,
                "ucc27282_ten_us": UCC27282_TEN_US,
                "ucc27282_source": UCC27282_SOURCE,
                "ucc27524a_us": UCC27524A_EN_TO_OUT_MAX_NS / 1000.0,
                "ucc27524a_typ_us": UCC27524A_EN_TO_OUT_TYP_NS / 1000.0,
                "ucc27524a_source": UCC27524A_SOURCE,
                "ucc27524a_package": UCC27524A_PACKAGE,
                "ucc27524a_datasheet_vendored": True,
                "ucc27524a_output_state_on_disable": UCC27524A_OUTPUT_STATE_ON_DISABLE,
                "ucc27524a_output_state_reason": (
                    "Device Logic Table 6-2 drives OUTA/OUTB low whenever the "
                    "matching ENx is low, and the tD4x condition -- VENx_L of the "
                    "enable fall to 90% of output fall -- describes a driven edge, "
                    "not a floating pin; so the SR gate keeps its 2.2 ohm path and "
                    "the 110.9 us dead-driver figure does not apply to a released "
                    "permit rail"),
                "ucc27524a_ven_l_max_v": UCC27524A_VEN_L_MAX_V,
                "ucc27524a_ven_h_min_v": UCC27524A_VEN_H_MIN_V,
                "ucc27524a_switching_params_not_production_tested": True,
            },
            "gate_discharge": {"sr": sr_gate, "primary": primary_gate},
        },
        "totals": totals,
        "hardware_protection_approved": False,
        "power_stage_fabrication_approved": False,
        "requires_bench_measurement": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, help="save the self-contained JSON budget")
    parser.add_argument("--require-complete", action="store_true",
                        help="fail unless the budget has no unknown stages")
    args = parser.parse_args(argv)
    result = build()
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload)
    return 1 if args.require_complete and (
        result["status"] != "RESPONSE_BUDGET_COMPLETE") else 0


if __name__ == "__main__":
    raise SystemExit(main())
