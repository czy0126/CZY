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
UCC27282_VDIS_MAX_V = 1.21
UCC27282_VDIS_MIN_V = 0.70
UCC27282_REN_OHM = 250e3
UCC27282_TDIS_US = 1.5
UCC27282_TEN_US = 18.0
UCC27282_SOURCE = "references/datasheets/ucc27282.txt (SNVSAQ5B, ENABLE table)"


def _parallel(*resistances: float) -> float:
    return 1.0 / sum(1.0 / r for r in resistances if r)


def _resistor_between(parts, net_a: str, net_b: str) -> list:
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

    Every resistor from PERMIT_RAIL to PGND discharges it.  Eight of them are
    the UCC27524A ENA/ENB pull-downs, which exist to defeat that chip's
    internal 200 k pull-up to *enable* -- they are 94 % of the conductance
    here, so the rail's fall time is a side effect of a default-off decision
    made elsewhere.  The drawn R44/C28 filter is not the limiting term.
    """
    q2 = parts["Q2"]
    source_net = q2.nets["2"]
    if source_net != RAIL_SOURCE_NET:
        raise SystemExit(f"Q2 source is {source_net}, not {RAIL_SOURCE_NET}: "
                         "the permit rail no longer rides the 5 V rail")
    sr_pull = _resistor_between(parts, "PERMIT_RAIL", "PGND")
    sr_pull = [p for p in sr_pull if abs(board.resistance(p.value) - 4.7e3) < 1.0]
    r_known = [board.resistance(p.value) for p in sr_pull]
    r44 = board.resistance(board.part_value("R44"))
    r35 = board.resistance(board.part_value("R35"))
    c_rail = _capacitor_on(parts, "PERMIT_RAIL")

    r_all = _parallel(*(r_known + [r44, r35, UCC27282_REN_OHM]))
    r_without = _parallel(r44, r35, UCC27282_REN_OHM)

    def cross(r_ohm: float, v_th: float) -> float:
        return r_ohm * c_rail * math.log(V5_RAIL_V / v_th) * 1e6

    fastest = cross(r_all, UCC27282_VDIS_MAX_V)
    guaranteed = cross(r_all, UCC27282_VDIS_MIN_V)
    without = cross(r_without, UCC27282_VDIS_MAX_V)
    conductance_share = sum(1.0 / r for r in r_known) / sum(
        1.0 / r for r in r_known + [r44, r35, UCC27282_REN_OHM])
    return {
        "enable_rail_v": V5_RAIL_V,
        "rail_source_net": source_net,
        "discharge_ohm": r_all,
        "specified_capacitance_f": c_rail,
        "tau_us": r_all * c_rail * 1e6,
        "vd_is_max_v": UCC27282_VDIS_MAX_V,
        "vd_is_min_v": UCC27282_VDIS_MIN_V,
        "fastest_us": fastest,
        "guaranteed_us": guaranteed,
        "fastest_uses_vd_is_max": True,
        "guaranteed_uses_vd_is_min": True,
        "sr_pulldown_count": len(sr_pull),
        "sr_pulldowns_carry_most_of_the_discharge": conductance_share > 0.8,
        "sr_pulldown_conductance_share": conductance_share,
        "release_without_sr_pulldowns_us": without,
        "filter_to_tdis_ratio": fastest / UCC27282_TDIS_US,
        "pin_capacitance_unknown_so_this_is_a_floor": True,
        "sr_pin_capacitance_known": False,
        "sr_driver_release_us": None,
        "sr_driver_release_reason": (
            "the UCC27524A's EN pin capacitance and thresholds are not in the "
            "repository (no vendored datasheet); PERMIT_RAIL reaches the eight EN "
            "pins directly, so that branch is only bounded by the rail fall above"),
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
    sr_gate = gate_discharge(by_ref, "GA1")
    primary_gate = gate_discharge(by_ref, "GH1")
    shared_us = (release["fastest_us"] + UCC27282_TDIS_US
                 + sr_gate["with_driver_ns"] / 1e3)
    totals = {
        "hard_channel_floor_us": measured["hard_delay_us"] + shared_us,
        "fast_channel_floor_us": measured["fast_delay_us"] + shared_us,
        "shared_after_detection_us": shared_us,
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
            "the UCC27524A disable time is unknown: its datasheet is not vendored, and "
            "the EN pin capacitance behind PERMIT_RAIL is unpublished, so the rail "
            "fall time above is a floor that extra pin capacitance only lengthens",
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
                "ucc27524a_us": None,
                "ucc27524a_reason": ("the UCC27524A datasheet is not vendored; the eight "
                                     "SR drivers' disable time is unknown"),
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
