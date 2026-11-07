"""Source-backed *concept* sizing for a TPS26630 15 V SR-bias eFuse.

TI TPS2663 Rev G, Eq.1/2/8/9/10 and figures 5-1, 8-7, 9-2.
TI TPS26630-33EVM Rev A supports Q1 CSD19537Q3 and Q2 BSS138.
This is NOT a behavioral model of the IC and NOT a native CAD/ERC release.
Run: python tools/tps26630_bias_design.py --check
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "hardware/sr_bias_efuse_proposal"
PINMAP = FOLDER / "tps26630_pinmap.csv"
BOM = FOLDER / "component_candidates.csv"
SOURCE = "https://www.ti.com/lit/ds/symlink/tps2663.pdf"

# Nominal concept values, NOT customer- or vendor-qualified corner limits.
VIN_NOM_V = 15.0
VIN_LOW_V = 14.25
VIN_HIGH_V = 15.75
CAP_NOM_F = 11.1e-6  # existing UCC24624 board equivalent C1+C2+C3
CAP_STRESS_F = 15e-6  # deliberate what-if only; MLCC bias unknown
C_DVDT_F = 22e-9
C_DVDT_STRESS_MIN_F = 19.8e-9  # illustrative 10% capacitor tolerance
R_ILIM_OHM = 30_000.0
R_UVLO_TOP = 909_000.0
R_UVLO_MID = 35_700.0
R_OVP_BOTTOM = 64_900.0
# 1.2 V is the typical UVLO-rising/OVP threshold in Rev G Eq.9/10.
# These tolerance perturbations are EXPLORATORY, not guaranteed device limits.
THRESH_NOM_V = 1.2
R_TOL_FRACTION = 0.01
THRESH_SCREEN_FRACTION = 0.02
FET_RDS_MAX_OHM = .0145  # Q1 at 10V gate, 25C; separate from temperature
EFUSE_RDS_TYP_OHM = .031  # TI typ; do not add as all-corner maximum


def resistance_divider_thresholds(
    top: float, middle: float, bottom: float,
    uvlo_ref: float = THRESH_NOM_V, ovp_ref: float = THRESH_NOM_V
) -> dict[str, float]:
    if any(x <= 0 or not math.isfinite(x)
           for x in (top, middle, bottom, uvlo_ref, ovp_ref)):
        raise ValueError("positive finite divider and threshold values required")
    total = top + middle + bottom
    return {
        "uvlo_rising_v": uvlo_ref * total / (middle + bottom),
        "ovp_rising_v": ovp_ref * total / bottom,
        "divider_current_at_15v_a": VIN_NOM_V / total,
    }


def divider_sensitivity() -> dict:
    values = [resistance_divider_thresholds(
        R_UVLO_TOP * t, R_UVLO_MID * m, R_OVP_BOTTOM * b,
        THRESH_NOM_V * v, THRESH_NOM_V * v)
        for t, m, b in itertools.product((.99, 1.01), repeat=3)
        for v in (.98, 1.02)]
    return {
        "engineering_screen_only": True,
        "resistance_tolerance_fraction": R_TOL_FRACTION,
        "reference_variation_assumed_fraction": THRESH_SCREEN_FRACTION,
        "uvlo_rising_range_v": [
            min(x["uvlo_rising_v"] for x in values),
            max(x["uvlo_rising_v"] for x in values)],
        "ovp_rising_range_v": [
            min(x["ovp_rising_v"] for x in values),
            max(x["ovp_rising_v"] for x in values)],
        "not_a_vendor_guaranteed_corner": True,
    }


def ramp(*, cap_f: float, dvd_cap_f: float, vin_v: float) -> dict:
    if any(x <= 0 or not math.isfinite(x)
           for x in (cap_f, dvd_cap_f, vin_v)):
        raise ValueError("positive finite cap and input voltage required")
    # Rev G Eq.2: t_dVdT = 20.8e3 * Vin * C_dVdT (seconds).
    ramp_s = 20_800.0 * vin_v * dvd_cap_f
    # Eq.1: approximate capacitive charging current, not absolute peak current
    # nor short-circuit / hot-plug transient limit.
    cap_current_a = cap_f * vin_v / ramp_s
    return {
        "ramp_time_s": ramp_s,
        "ideal_cap_charge_current_a": cap_current_a,
        "energy_stored_in_bank_j": 0.5 * cap_f * vin_v ** 2,
        "efuse_avg_inrush_fet_dissipation_w":
            0.5 * vin_v * cap_current_a,
        "assumption": "datasheet Eq1/2/3 nominal linear ramp only, no inrush peak/SOA guarantee",
    }


def report() -> dict:
    divider = resistance_divider_thresholds(
        R_UVLO_TOP, R_UVLO_MID, R_OVP_BOTTOM)
    nominal = ramp(cap_f=CAP_NOM_F, dvd_cap_f=C_DVDT_F, vin_v=VIN_NOM_V)
    stress = ramp(cap_f=CAP_STRESS_F,
                  dvd_cap_f=C_DVDT_STRESS_MIN_F, vin_v=VIN_HIGH_V)
    # Rev G Eq.8: R_ILIM(kOhm) = 18 / I_LIMIT(A); 30k -> 0.6 A.
    ilim_a = 18_000.0 / R_ILIM_OHM
    result = {
        "status": "OEM_BASED_PINMAP_AND_SIZING_CONCEPT_NOT_FOR_FAB",
        "source": {"datasheet": SOURCE, "revision": "SLVSE94G June 2024",
                   "evm": "https://www.ti.com/lit/ug/slvubi8.pdf"},
        "device": {
            "u1": "TPS26630RGET", "q1": "CSD19537Q3T",
            "q2": "BSS138IXTSA1", "package": "RGE24 + thermal pad",
            "configuration": "external reverse-block FET and Q2, MODE open, "
                             "SHDN externally pulled low for default off",
        },
        "nominal": {
            "vin_v": VIN_NOM_V, "output_bank_f": CAP_NOM_F,
            "cdnf_dvdt_f": C_DVDT_F, "rilim_ohm": R_ILIM_OHM,
            "ilim_nominal_a": ilim_a,
            "r_uvlo_top_ohm": R_UVLO_TOP,
            "r_uvlo_mid_ohm": R_UVLO_MID,
            "r_ovp_bottom_ohm": R_OVP_BOTTOM,
            **divider, **nominal,
        },
        "sensitivity": {
            **divider_sensitivity(),
            "cap_total_assumed_max_f": CAP_STRESS_F,
            "c_dvdt_assumed_min_f": C_DVDT_STRESS_MIN_F,
            **stress,
            "illustrative_load_a": .05,
            "charging_plus_load_a": stress["ideal_cap_charge_current_a"] + .05,
        },
        "readiness": {
            "native_kicad_erc_passed": False,
            "pin_mapping_source_checked_against_ti": True,
            "oem_model_simulated": False,
            "blocking_fet_soa_at_15v_verified": False,
            "reverse_current_oem_corner_tested": False,
            "discharge_redesign_completed": False,
            "load_15v_qualified": False,
            "h1_h5_scope_complete": False,
            "fab_release": False,
            "no_main_power_stage_release": True,
        },
        "blocking_decisions": [
            "TPS26630 default internal UVLO ~=15.6V is unsuitable for 15V input; external divider is mandatory",
            "TPS26630 nominal 0.6A current limit does NOT bound sub-microsecond spikes by 0.6A",
            "MODE open latches overload; external hardware fault latch must still control SHDN for no auto-restart",
            "CDvdt 22nF sets approximate 6.864ms startup ramp; load and C-bias tolerance need validation",
            "old Q54/R57 continuous 18V-backfeed dissipation remains physically unacceptable; eFuse is not a discharge switch",
            "manufacturer Q1/Q2 reference pin and thermal land must be mapped to tested footprint and native ERC/DRC",
        ],
    }
    return result


# Rev G Figure 5-1, Figure 8-7; Q1 TI SLPS549B Figure 3-1;
# Q2 Infineon BSS138I 2025-09-30 Figure / Table 1.
EXPECTED = {
    ("U1", "1"): "EFUSE_IN", ("U1", "2"): "EFUSE_IN",
    ("U1", "3"): "BGATE", ("U1", "4"): "DRV",
    ("U1", "5"): "VIN_SYS", ("U1", "6"): "UVLO",
    ("U1", "7"): "OVP", ("U1", "8"): "PGND",
    ("U1", "9"): "DVDT", ("U1", "10"): "ILIM",
    ("U1", "11"): "FLOAT", ("U1", "12"): "SHDN",
    ("U1", "13"): "FLOAT", ("U1", "14"): "FLT_OC",
    ("U1", "15"): "PGND", ("U1", "16"): "FLOAT",
    ("U1", "17"): "VDD_SR", ("U1", "18"): "VDD_SR",
    **{("U1", str(i)): "NC" for i in range(19, 25)},
    ("U1", "EP"): "PGND",
    **{("Q1", str(i)): "VIN_SYS" for i in (1, 2, 3)},
    ("Q1", "4"): "BGATE",
    **{("Q1", str(i)): "EFUSE_IN" for i in (5, 6, 7, 8)},
    ("Q2", "1"): "DRV", ("Q2", "2"): "VIN_SYS",
    ("Q2", "3"): "BGATE",
}


def check_files() -> dict:
    with PINMAP.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    seen = {}
    for row in rows:
        key = (row["ref"], row["pad"])
        if key in seen:
            raise ValueError(f"duplicate pin: {key}")
        seen[key] = row["net"]
    if seen != EXPECTED:
        raise ValueError(f"pinmap diverges from OEM source: "
                         f"missing={sorted(EXPECTED.items()-seen.items())} "
                         f"unexpected={sorted(seen.items()-EXPECTED.items())}")
    with BOM.open(encoding="utf-8", newline="") as f:
        parts = {row["ref"]: row for row in csv.DictReader(f)}
    for ref, mpn in (("U1", "TPS26630RGET"),
                     ("Q1", "CSD19537Q3T"), ("Q2", "BSS138IXTSA1")):
        if parts.get(ref, {}).get("mpn") != mpn:
            raise ValueError(f"{ref}: OEM MPN not matching schematic source")
        if not parts[ref].get("source_url", "").startswith("https://"):
            raise ValueError(f"{ref}: lacks manufacturer evidence URL")
        if parts[ref].get("fab_qualified") != "false":
            raise ValueError(f"{ref}: candidate cannot claim fab qualified")
    return {"status": "INPUT_TABLES_CHECKED_NOT_FAB", "pins": len(seen),
            "parts": len(parts), "fabrication_approved": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = report()
        if args.check:
            result["source_tables"] = check_files()
    except (ValueError, KeyError, OSError) as e:
        print(json.dumps({"status": "INVALID_SOURCE", "fabrication_approved": False,
                          "error": str(e)}, indent=2))
        return 2
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
