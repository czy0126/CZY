"""D0 rise/fall time budget: what the measurement already contains, and what it cannot.

Issue #36's P0-3 asks for a rising/falling time budget after the "this channel
is faster" claim was withdrawn.  The trap in building one is double-counting:
``design/v3/stage_f/d0_trip_timing.json`` measures the burden and *both* OC RC
poles on the deck, so that delay already is the detection term.  Summing the
pole list on top of it would turn the 10.21 us fast channel into a 130 us one.

What is left after detection is short and mostly arithmetic:

* the permit rail, discharged by whatever sits between it and ground;
* the driver's own disable time, which the vendored UCC27282 text publishes;
* the gate falling from the driver supply to VGS(th);
* and two stages the repository has no datasheet for -- the LM393 comparator
  and the CD4013 latch -- which stay ``None`` with the reason attached.

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
# the 4.7 k pull-downs exist at all (doc 15 section 0.3).  The figure is a
# *typical* transcribed from that document -- no UCC27524A datasheet is vendored
# here -- so the ceiling it produces carries the same caveat.
SR_CHANNELS = 8
# The eight EN pull-downs are R36..R43 in the generator's part table.
SR_EN_PULLDOWN_REFS = tuple(f"R{n}" for n in range(36, 36 + SR_CHANNELS))
UCC27524A_EN_PULLUP_TYP_OHM = 200e3
UCC27524A_EN_TO_OUT_MAX_NS = 23.0
UCC27524A_EN_TO_OUT_TYP_NS = 13.0
UCC27524A_SOURCE = ("docs/D1_EXECUTION_KIT/15_十路硬件故障关断接口及实施验收.md "
                    "section 0.5, transcribing the UCC27524A D datasheet; that "
                    "datasheet is not vendored in this repository")


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
        "sr_driver_release_us": None,
        "sr_driver_release_reason": (
            "the UCC27524A's EN pin capacitance is unpublished, so the 1 nF "
            "counted here is C28 only and extra pin capacitance only lengthens "
            "the fall; the eight EN pins do reach this node directly"),
    }


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
    if not load or not pulldown or not series:
        raise SystemExit(f"{gate_net}: the part table no longer shows a load, a "
                         "pull-down and a series gate resistor")
    r_pull = board.resistance(pulldown[0].value)
    r_gate = board.resistance(series[0].value)
    detector_branch = r_gate + board.resistance(board.part_value("R76")) + \
        board.resistance(board.part_value("R77"))
    r_effective = _parallel(r_pull, detector_branch)
    log_term = math.log(DRIVER_VDD_V / SR_VGS_TH_MIN_V)
    return {
        "gate_net": gate_net,
        "gate_load_nf": load * 1e9,
        "gate_resistor_ohm": r_gate,
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


def build() -> dict:
    by_ref = {p.ref: p for p in board.parts()}
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
    # ten gates low" is the slower of the two, never their sum.  The primary is
    # slower by three orders of magnitude at the driver and by 1.5 us at TDIS.
    sr_branch_us = (release["fastest_us"] + UCC27524A_EN_TO_OUT_MAX_NS / 1e3
                    + sr_gate["with_driver_ns"] / 1e3)
    primary_branch_us = (release["fastest_us"] + UCC27282_TDIS_US
                         + primary_gate["with_driver_ns"] / 1e3)
    shared_us = max(sr_branch_us, primary_branch_us)
    totals = {
        "hard_channel_floor_us": measured["hard_delay_us"] + shared_us,
        "fast_channel_floor_us": measured["fast_delay_us"] + shared_us,
        "shared_after_detection_us": shared_us,
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
            "the comparator stage is unknown: no LM393 datasheet is vendored, so its "
            "response time is neither cited nor guessed",
            "the latch stage is unknown: no CD4013 datasheet is vendored",
            "the UCC27524A disable delay comes from doc 15's transcription of a "
            "datasheet this repository does not hold, and whether disabling pulls "
            "the output low or tri-states it is unstated -- tri-stating would put "
            "the SR gate on the 10k pull-down alone",
            "the eight 200 k pull-ups that set the permit rail's ceiling are a "
            "typical transcribed from doc 15, not a guaranteed minimum, so the "
            "0.26 V ceiling is a nominal figure",
            "the gate fall omits the driver's internal sink resistance, which adds time",
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
                "us": None,
                "reason": ("no LM393 (LM2903) datasheet is vendored; a response time "
                           "quoted from memory would be a fabrication"),
            },
            "latch": {
                "us": None,
                "reason": "no CD4013 datasheet is vendored; the latch is unmodelled",
            },
            "permit_release": release,
            "driver_disable": {
                "ucc27282_tdis_us": UCC27282_TDIS_US,
                "ucc27282_ten_us": UCC27282_TEN_US,
                "ucc27282_source": UCC27282_SOURCE,
                "ucc27524a_us": UCC27524A_EN_TO_OUT_MAX_NS / 1000.0,
                "ucc27524a_typ_us": UCC27524A_EN_TO_OUT_TYP_NS / 1000.0,
                "ucc27524a_source": UCC27524A_SOURCE,
                "ucc27524a_datasheet_vendored": False,
                "ucc27524a_output_state_on_disable": None,
                "ucc27524a_output_state_reason": (
                    "the transcribed material gives the EN-to-output delay but not "
                    "whether a low EN pulls OUT low or tri-states it; if it "
                    "tri-states, the SR gate falls on the 10k pull-down alone and "
                    "takes the gate_discharge.sr.pulldown_only_us figure instead"),
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
