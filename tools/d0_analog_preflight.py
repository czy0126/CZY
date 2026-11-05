"""Independent D0 bench analog safety preflight (NOT hardware qualification).

ERC and a Boolean state machine do not test sub-threshold gate residuals,
comparator common-mode, low-current zener knee, propagation delay or CT
front-end dynamics. Compute their current design limitations from the *part
table*, using OEM limits as review inputs. Do not assert success without
real hardware data or substitute a hypothetical clamp characteristic.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import make_d0_protection_board as board

# Manufacturer published conditions. These are NOT generic guaranteed device
# characteristics at other currents or temperatures. See the cited source URLs.
BZX84_C3V0_NOMINAL_V = 3.0
BZX84_C3V0_TEST_CURRENT_A = 5e-3
ZENER_SOURCE = "https://www.diodes.com/part/view/BZX84C3V0"
TL431_SOURCE = "https://www.ti.com/lit/ds/symlink/tl431.pdf"
LM393_CM_SOURCE = "https://www.ti.com/lit/ds/symlink/lm393.pdf"
TL431_LP_FOOTPRINT = "Package_TO_SOT_THT:TO-92_Inline"


def build() -> dict:
    parts = {part.ref: part for part in board.parts()}
    u2, d9 = parts["U2"], parts["D9"]
    threshold_v = board.divider_output("R6", "R7")
    on_coeff = board.gate_sum_per_gate(drivers_low=True)
    float_coeff = board.gate_sum_per_gate(drivers_low=False)

    # All ten gate outputs are at 12 V as an intentionally adverse, sampled
    # corner. R66..R75 = 10k, R76 = 1k (from the actual part table).
    branches = [board.resistance(parts[f"R{i}"].value) for i in range(66, 76)]
    rload = board.resistance(parts["R76"].value)
    raw_all_high_v = (12.0 * sum(1.0 / r for r in branches)
                      / (sum(1.0 / r for r in branches) + 1.0 / rload))
    rseries = board.resistance(parts["R77"].value)
    # An *upper bound* for current when the zener would be nominally at 3 V:
    # R77 feeding the 3V node cannot source more than (6-3)/10k here.
    # This is not a measurement or a prediction of the low-current Vz.
    zener_current_a = max(0.0, (raw_all_high_v - BZX84_C3V0_NOMINAL_V)
                          / rseries)

    slope, hard_trip_peak_a = board.burden_numbers()
    fast_threshold_v = board.divider_output("R4", "R5")
    fast_trip_peak_a = fast_threshold_v / slope

    source_package_matches_vendor = (
        u2.lib == "Reference_Voltage:TL431LP"
        and u2.value == "TL431LP"
        and u2.footprint == TL431_LP_FOOTPRINT
        and u2.nets == {"1": "REF_2V5", "2": "PGND", "3": "REF_2V5"}
    )
    clamp_is_nominal_zener = (
        d9.value == "BZX84C3V0"
        and d9.nets == {"1": "GSUM_SNS", "2": "PGND"}
        and parts["R77"].nets == {"1": "GSUM", "2": "GSUM_SNS"}
    )
    legacy_cm_at_5v = 5.0 - 1.5
    return {
        "kind": "D0_ANALOG_DESIGN_REVIEW",
        "status": "ANALOG_SAFETY_NOT_QUALIFIED",
        "schematic_only": True,
        "hardware_protection_approved": False,
        "power_stage_fabrication_approved": False,
        "vendor_reference_package_currently_consistent": source_package_matches_vendor,
        "gate_sum": {
            "single_gate_high_10v_gsum_v_with_other_drivers_low": 10.0 * on_coeff,
            "single_gate_high_10v_gsum_v_with_other_drivers_unpowered": 10.0 * float_coeff,
            "one_gate_3v_is_reported_off_drivers_low": 3.0 * on_coeff < threshold_v,
            "one_gate_3v_is_reported_off_drivers_unpowered": 3.0 * float_coeff < threshold_v,
            "threshold_at_single_gate_drivers_low_v": threshold_v / on_coeff,
            "threshold_at_single_gate_drivers_unpowered_v": threshold_v / float_coeff,
            "comparator_input_reference_v": threshold_v,
            "all_ten_gates_at_12v_unclamped_gsum_v": raw_all_high_v,
            "legacy_lm393_vcc_5v_common_mode_upper_v": legacy_cm_at_5v,
            "reliable_all_ten_off_proven": False,
        },
        "clamp": {
            "part": d9.value,
            "netlist_wiring_as_proposed": clamp_is_nominal_zener,
            "nominal_vz_v_at_published_test_current": BZX84_C3V0_NOMINAL_V,
            "datasheet_zener_test_current_ma": 1000.0 * BZX84_C3V0_TEST_CURRENT_A,
            "available_current_ma_upper_bound_at_ten_12v_gates":
                1000.0 * zener_current_a,
            "published_test_current_reached": (
                zener_current_a >= BZX84_C3V0_TEST_CURRENT_A),
            "low_current_clamp_voltage_guaranteed": False,
            "comparator_common_mode_under_all_conditions_proven": False,
            "vendor": ZENER_SOURCE,
        },
        "ct_fast_path": {
            "hard_trip_peak_a_design": hard_trip_peak_a,
            "fast_trip_peak_a_design": fast_trip_peak_a,
            "fast_threshold_lower_than_hard": fast_trip_peak_a < hard_trip_peak_a,
            "fast_path_has_filter_delay": True,
            "maximum_response_time_with_measured_hardware_proven": False,
        },
        "unqualified_prerequisites": [
            "per_gate_residual VGS below the engineer-reviewed safe-off threshold; "
            "a sum of 10 gate voltages is not the same as ten independent comparators",
            "worst-case gate-sum clamp voltage at actual maximum delivered current "
            "and minimum LM393 VCC/temperature, including supply startup/collapse",
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
    parser = argparse.ArgumentParser(description=__doc__)
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
