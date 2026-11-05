"""Independent D0 bench analog safety preflight (NOT hardware qualification).

ERC and a Boolean state machine do not test sub-threshold gate residuals,
comparator common-mode, detector-diode behaviour, propagation delay or CT
front-end dynamics.  This tool recomputes every figure from the *part table* so
that a changed resistor moves the review with it, and it keeps a list of what
the arithmetic cannot settle.

It used to veto two designs that are no longer on the board -- a ten-resistor
gate sum that read 0.150 V for a gate parked at 3 V, and a BZX84C3V0 clamp whose
"3 V" is specified at 5 mA while the node supplied 0.3 mA.  Both are recorded
here as *retired*, with the numbers that retired them, because deleting them
would lose the reason the current circuit looks the way it does.  The
replacement is reviewed, not blessed: ``status`` stays
``ANALOG_SAFETY_NOT_QUALIFIED`` until hardware data exists.

Usage:
    python tools/d0_analog_preflight.py --output design/v3/stage_f/d0_analog_preflight.json
    python tools/d0_analog_preflight.py --require-qualified   # exit 1 today
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import make_d0_protection_board as board

# Manufacturer published conditions.  These are NOT generic guaranteed device
# characteristics at other currents or temperatures.  See the cited source URLs.
BZX84_C3V0_NOMINAL_V = 3.0
BZX84_C3V0_TEST_CURRENT_A = 5e-3
ZENER_SOURCE = "https://www.diodes.com/part/view/BZX84C3V0"
TL431_SOURCE = "https://www.ti.com/lit/ds/symlink/tl431.pdf"
LM393_CM_SOURCE = "https://www.ti.com/lit/ds/symlink/lm393.pdf"
TL431_LP_FOOTPRINT = "Package_TO_SOT_THT:TO-92_Inline"

# The retired ten-resistor sum, kept as the comparison the detector has to beat.
RETIRED_SUM_R_TOP_OHM = 10e3
RETIRED_SUM_R_LOAD_OHM = 1e3
# A Schottky drop is a placeholder for the thermal sweep, not a datasheet number:
# no BAT54 datasheet is vendored in this repository.
ASSERTED_DIODE_DROP_V = 0.3
# VGS(th) minimum of the SR FET (BSC010N04LS6).  No equivalent figure is
# established for the primary FET, so the band is stated for the SR channels.
SR_VGS_TH_MIN_V = 1.3


def reference_package_ok(parts: dict) -> bool:
    """TL431LP symbol, value, footprint and pins all match the vendor part."""
    u2 = parts["U2"]
    return (u2.lib == "Reference_Voltage:TL431LP" and u2.value == "TL431LP"
            and u2.footprint == TL431_LP_FOOTPRINT
            and u2.nets == {"1": "REF_2V5", "2": "PGND", "3": "REF_2V5"})


def gate_max_detector(parts: dict) -> dict:
    """The diode-OR that replaced the sum: what it computes, and what it cannot."""
    threshold_v = board.divider_output("R6", "R7")
    diodes = [p for p in parts.values() if p.lib == "Device:D_Schottky"
              and p.nets.get("1") == "GSMAX"]
    branches = sorted(p.nets["2"] for p in diodes)
    one_three = board.gate_sense_v(3.0, conducting=1)
    one_ten = board.gate_sense_v(10.0, conducting=1)
    all_twelve = board.gate_sense_v(12.0, conducting=10)
    all_fifteen = board.gate_sense_v(15.0, conducting=10)
    # What the retired ten-resistor star did with the same 3 V gate, using its
    # own values.  One branch drives from 3 V through 10k; the other nine are
    # held at 0 V by their drivers, so all ten 10k conductances load the node
    # against the 1k: 3 * (1/10k) / (10/10k + 1/1k) = 0.150 V.
    retired_per_gate = (3.0 * (1 / RETIRED_SUM_R_TOP_OHM)
                        / (10 / RETIRED_SUM_R_TOP_OHM + 1 / RETIRED_SUM_R_LOAD_OHM))
    return {
        "topology": "diode-OR of ten 1k branches into a 22k/6.2k divider",
        "detector_diodes": len(diodes),
        "branches_are_distinct": len(set(branches)) == len(diodes) == 10,
        "comparator_input_reference_v": threshold_v,
        "one_gate_at_10v_sense_v": one_ten,
        "one_gate_at_3v_sense_v": one_three,
        "one_gate_at_3v_multiple_of_reference": one_three / threshold_v,
        "retired_ten_resistor_sum_one_gate_at_3v_v": retired_per_gate,
        "retired_sum_would_report_that_gate_off": retired_per_gate < threshold_v,
        "detection_is_independent_of_the_other_nine_gates": True,
        "trip_gate_voltage_v_ideal_diode": board.gate_trip_v(),
        "trip_gate_voltage_v_at_asserted_drop": board.gate_trip_v(ASSERTED_DIODE_DROP_V),
        "asserted_diode_drop_v": ASSERTED_DIODE_DROP_V,
        "sr_vgs_th_min_v": SR_VGS_TH_MIN_V,
        "headroom_to_sr_vgs_th_min_v": SR_VGS_TH_MIN_V - board.gate_trip_v(
            ASSERTED_DIODE_DROP_V),
        "all_ten_gates_at_12v_sense_v": all_twelve,
        "all_ten_gates_at_15v_sense_v": all_fifteen,
        "lm393_common_mode_upper_v": board.LM393_COMMON_MODE_LIMIT_V,
        "all_ten_inside_common_mode_at_12v": all_twelve < board.LM393_COMMON_MODE_LIMIT_V,
        "all_ten_inside_common_mode_at_15v": all_fifteen < board.LM393_COMMON_MODE_LIMIT_V,
        "gate_rail_at_the_common_mode_bound_v": board.gate_rail_for_common_mode(),
        "bound_is_a_resistor_ratio_not_a_knee_voltage": True,
        "can_name_the_failing_gate": False,
        "per_channel_bring_up_rows": len(board.gate_sense_bring_up()),
        "one_open_channel_is_invisible_to_an_all_high_test": True,
        "residual_vgs_safe_off_threshold_verified_per_fet": False,
        "diode_drop_over_temperature_verified": False,
        "lm393_common_mode_limit_verified": False,
    }


def clamp_retired() -> dict:
    """Why the Zener is gone, with the numbers that removed it.

    The board no longer clamps: the divider's ratio bounds the comparator input
    at any current, which is the property the Zener could not supply.  The
    retired current figure is recomputed from the old resistor values so it
    stays a calculation rather than a sentence.
    """
    old_all_high_v = (12.0 * (10 / RETIRED_SUM_R_TOP_OHM)
                      / (10 / RETIRED_SUM_R_TOP_OHM + 1 / RETIRED_SUM_R_LOAD_OHM))
    available_a = max(0.0, (old_all_high_v - BZX84_C3V0_NOMINAL_V) / 10e3)
    return {
        "part": None,
        "replaced_by": "R76 22k / R77 6.2k divider on GSMAX",
        "retired_part": "BZX84C3V0",
        "reason": ("a Zener knee is specified at a test current; this node spends "
                   "tens of microamps, where the knee voltage is not bounded"),
        "nominal_vz_v_at_published_test_current": BZX84_C3V0_NOMINAL_V,
        "datasheet_zener_test_current_ma": 1000.0 * BZX84_C3V0_TEST_CURRENT_A,
        "retired_node_all_high_v": old_all_high_v,
        "retired_available_current_ma_upper_bound": 1000.0 * available_a,
        "retired_published_test_current_reached": available_a >= BZX84_C3V0_TEST_CURRENT_A,
        "replacement_needs_a_current_to_be_bounded": False,
        "vendor": ZENER_SOURCE,
    }


def ct_fast_path() -> dict:
    """The two overcurrent thresholds, each converted on its own node."""
    slope, hard_a = board.burden_numbers()
    gain = board.burden_gain()
    fast_v = board.divider_output("R4", "R5")
    burden_v_per_a = slope / gain
    fast_a = fast_v / burden_v_per_a
    timing = board.trip_timing_record()
    return {
        "hard_trip_peak_a_design": hard_a,
        "fast_trip_peak_a_design": fast_a,
        "divider_gain_oc": gain,
        "burden_node_v_per_a_peak": burden_v_per_a,
        "fast_threshold_lower_than_hard": fast_a < hard_a,
        "fast_is_earlier_measured": None if timing is None else timing["fast_is_earlier_us"] > 0,
        "fast_delay_us": None if timing is None else timing["fast_delay_us"],
        "hard_delay_us": None if timing is None else timing["hard_delay_us"],
        "fast_path_has_filter_delay": True,
        "maximum_response_time_with_measured_hardware_proven": False,
    }


def build() -> dict:
    parts = {part.ref: part for part in board.parts()}
    detector = gate_max_detector(parts)
    detector["wiring_as_designed"] = (
        parts["D9"].lib == "Device:D_Schottky"
        and parts["D9"].nets == {"1": "GSMAX", "2": "GK1"}
        and parts["R76"].nets == {"1": "GSMAX", "2": "GATE_SENSE"}
        and parts["R77"].nets == {"1": "GATE_SENSE", "2": "PGND"}
        and next(p for p in board.parts() if p.ref == "U5" and p.unit == 2
                 ).nets["5"] == "GATE_SENSE"
    )
    return {
        "kind": "D0_ANALOG_DESIGN_REVIEW",
        "status": "ANALOG_SAFETY_NOT_QUALIFIED",
        "schematic_only": True,
        "hardware_protection_approved": False,
        "power_stage_fabrication_approved": False,
        "vendor_reference_package_currently_consistent": reference_package_ok(parts),
        "gate_max_detector": detector,
        "clamp": clamp_retired(),
        "ct_fast_path": ct_fast_path(),
        "unqualified_prerequisites": [
            "per-gate worst-case VGS at the fault temperature and device spread: the "
            "detector reports that a gate is above ~1 V, not that the FET is off; the "
            "engineer-reviewed safe-off threshold still has to be written down",
            "detector diode drop over -40..+125 C and its spread (no vendored datasheet), "
            "which moves the trip between the ideal %.3f V and VGS(th) min %.1f V"
            % (board.gate_trip_v(), SR_VGS_TH_MIN_V),
            "LM393 common-mode limit as a datasheet number: the %.1f V used here is a "
            "carried-over assumption, not a cited limit" % board.LM393_COMMON_MODE_LIMIT_V,
            "ten-step bring-up sweep plus all-three-rails startup/collapse records; a "
            "sum or a maximum cannot show which channel is open",
            "full analog propagation-delay and CT filtering/phase tolerance budget "
            "with worst-case 48/50-V and 120-A faults",
            "TL431 reference stability with C7 and min/max shunt current",
            "power-on reset/ACK debounce and rail sequencing on actual hardware",
            "real connected VGS probe records for all ten gates; ERC is not that evidence",
        ],
        "source_urls": [TL431_SOURCE, ZENER_SOURCE, LM393_CM_SOURCE],
        "requires_independent_hardware_review": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, help="save self-contained JSON review")
    parser.add_argument("--require-qualified", action="store_true",
                        help="fail unless analog safety is actually qualified")
    args = parser.parse_args(argv)
    result = build()
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload)
    return 1 if args.require_qualified and (
        result["status"] != "ANALOG_SAFETY_QUALIFIED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
