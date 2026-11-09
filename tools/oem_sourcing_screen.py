"""Read OEM part-level sourcing data; perform conservative arithmetic screens.

No EDA edit, web scrape, simulation, vendor reply, physical measurement, or
fabrication approval. Each ripple value is valid at its OWN listed frequency
and temperature; ESR and ripple at different temperatures cannot be combined
as one physically guaranteed operating point.

  python tools/oem_sourcing_screen.py --write
  python tools/oem_sourcing_screen.py --check
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "hardware/dcx_main"
SRC = HW / "oem_sourcing_inputs_2026-11-09.json"
OUT = HW / "oem_sourcing_screen_2026-11-09.json"
PERF = ROOT / "design/v3/power_priority/high_margin_design_gate.json"
POLICY = ROOT / "design/v3/power_priority/d1_staged_target_policy.json"
OUTPUT = HW / "output_joint_reduction_cases.json"

SAFE_OEM_HOSTS = {
    "search.kemet.com", "industrial.panasonic.com",
    "www.tdk-electronics.tdk.com", "www.we-online.com", "www.ti.com",
}


def read(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def ceil_for(target: float, per_part: float) -> int:
    if not (math.isfinite(target) and math.isfinite(per_part)
            and target > 0 and per_part > 0):
        raise ValueError("part and target numbers must be positive finite")
    # A small float tolerance prevents e.g. 15.0000000002 turning into 16;
    # all OEM inputs here carry only a few quoted significant digits.
    return math.ceil(target / per_part - 1e-10)


def _positive_finite(x: object) -> bool:
    return type(x) in (int, float) and math.isfinite(x) and x > 0


def validate_inputs(source: dict) -> None:
    if source.get("classification") != "OEM_LINKS_AND_PARAMETER_SCREEN_ONLY_NOT_FOR_FAB":
        raise ValueError("source classification must not authorize hardware")
    sources = source["sources"]
    ids = [x["id"] for x in sources]
    if len(ids) != len(set(ids)) or len(sources) < 9:
        raise ValueError("source registry missing evidence or has duplicate IDs")
    for s in sources:
        u = urlparse(s["official_url"])
        if (u.scheme != "https" or u.hostname not in SAFE_OEM_HOSTS
                or u.username or u.password or not s.get("grade")
                or not s.get("evidence")):
            raise ValueError("missing official manufacturer evidence URL/grade")
    caps = source["capacitor_candidates"]
    if len(caps) < 2 or len({c["mpn"] for c in caps}) != len(caps):
        raise ValueError("duplicated or missing capacitor alternatives")
    for cap in caps:
        if cap["source_id"] not in ids:
            raise ValueError("orphan capacitor spec")
        for key in ("cap_uF", "min_cap_fraction",
                    "nominal_voltage_v_at_or_below_105c",
                    "esr_mohm_at_100khz"):
            if not _positive_finite(cap[key]):
                raise ValueError("invalid capacitor " + key)
        if cap["min_cap_fraction"] > 1:
            raise ValueError("tolerance fraction cannot exceed nominal")
        for t, ripple in cap["ripple_rms_a_at_100khz_by_temp_c"].items():
            if not t.isdigit() or not _positive_finite(ripple):
                raise ValueError("ripple point not physically sourced")
        if cap.get("layout_footprint_approved") is not False:
            raise ValueError("manufacturer body dimensions are NOT PCB signoff")
    conn = source["connector_family"]
    if (conn["source_id"] not in ids or conn["actual_interface_approved"] is not False
            or not 0 < conn["contact_zone_resistance_uohm_low"]
            <= conn["contact_zone_resistance_uohm_high"]):
        raise ValueError("connector family grade/assumption invalid")
    magnetics = source["magnetic_core_sources"]
    if (magnetics["raw_product_is_finished_magnetic"] is not False
            or magnetics["core_sheet_Bs_100c_mT_at_H250"] >=
            magnetics["generic_n97_Bs_100c_mT_at_H1200"]):
        raise ValueError("must retain distinct OEM Bsat measurement H fields")


def capacitor_row(part: dict, targets: dict) -> dict:
    cap_per = part["cap_uF"]
    nominal = ceil_for(targets["capacitance_min_mf"] * 1000, cap_per)
    tol = ceil_for(targets["capacitance_min_mf"] * 1000,
                   cap_per * part["min_cap_fraction"])
    esr = ceil_for(part["esr_mohm_at_100khz"],
                   targets["bank_cap_esr_budget_mohm"])
    ripple = {}
    for temp_c, amps in sorted(part["ripple_rms_a_at_100khz_by_temp_c"].items(),
                               key=lambda p: int(p[0])):
        needed = ceil_for(targets["bank_ripple_required_arms"], amps)
        ripple[temp_c] = {
            "ripple_per_part_a_at_100khz_oem": amps,
            "min_units_ripple_only": needed,
            "min_units_all_simple_arithmetic_targets": max(tol, esr, needed),
            "does_not_interpolate_other_temperatures": True,
        }
    reference_units = 15
    return {
        "mpn": part["mpn"],
        "source_id": part["source_id"],
        "voltage_v_nominal_until_105c_oem": part[
            "nominal_voltage_v_at_or_below_105c"],
        "voltage_v_at_125c_oem_or_unknown": part["voltage_v_at_125c"],
        "cap_nominal_uF_each": cap_per,
        "cap_worst_tolerance_uF_each": round(
            cap_per * part["min_cap_fraction"], 6),
        "esr_mohm_each_oem_at_100khz": part["esr_mohm_at_100khz"],
        "esr_temperature_c_from_oem_or_unspecified": part["esr_test_temp_c"],
        "min_units_by_nominal_cap_only": nominal,
        "min_units_by_low_tolerance_cap": tol,
        "min_units_by_ideal_equal_esr_only": esr,
        "min_units_by_ripple_at_listed_oem_temperatures": ripple,
        "current_nominal_15units_cap_mf": round(reference_units * cap_per / 1000, 5),
        "current_15units_low_tolerance_cap_mf": round(
            reference_units * cap_per * part["min_cap_fraction"] / 1000, 5),
        "current_15units_ideal_equal_esr_mohm": round(
            part["esr_mohm_at_100khz"] / reference_units, 6),
        "current_15units_under_cap_bank_esr_budget": (
            part["esr_mohm_at_100khz"] / reference_units
            <= targets["bank_cap_esr_budget_mohm"]),
        "case_body_size_mm": {
            "L": part["body_length_mm"],
            "W": part.get("body_width_mm"),
            "manufacturer_height_max_or_unknown": part["body_height_max_mm"],
            "diameter_or_unknown": part.get("body_diameter_mm"),
        },
        "physical_layout_and_mixed_bank_qualified": False,
        "only_equal_current_and_equal_impedance_arithmetic": True,
        "esr_and_ripple_specs_not_same_operating_point": True,
        "thermal_ac_and_dcbias_models_still_needed": True,
    }


def build() -> dict:
    inp = read(SRC)
    validate_inputs(inp)
    high = read(PERF)
    policy = read(POLICY)
    output = read(OUTPUT)
    h = high["capacitors"]
    stages = {s["id"]: s for s in policy["stages"]}
    if (high["status"] != "UNVERIFIED_RFQ_TARGETS_NOT_RATED_NOT_FOR_FAB"
            or h["status"] != "PENDING_DATASHEETS_AND_3D_LAYOUT"):
        raise ValueError("historical capacitor design evidence changed")
    if (stages["D1_100A"]["height_limit_mm"] != 16
            or stages["D2_120A"]["height_limit_mm"] != 16
            or stages["D3_THIN"]["height_limit_mm"] != 10
            or high["constraints"]["maximum_assembly_height_mm"] != 10):
        raise ValueError("D1 16mm/D3 legacy 10mm stage contract changed")
    if (high["constraints"]["d1_100a_first_article_total_height_mm"] != 16
            or high["constraints"]["d3_stretch_total_height_mm"] != 10):
        raise ValueError("supplier RFQ stage mismatch")
    if (output["status"] != "UNVERIFIED_INTERFACE_TOPOLOGY_REDESIGN_NOT_FOR_FAB"
            or output["fabrication_approved"] is not False):
        raise ValueError("current 2-pole connector model changed")
    targets = {
        "capacitance_min_mf": h["output_bank_c_min_mf"],
        "bank_ripple_required_arms": h["output_ripple_target_rms_a"],
        "bank_cap_esr_budget_mohm": h["output_cap_bank_esr_budget_mohm"],
        "bank_copper_and_joint_separate_budget_mohm": h[
            "output_copper_and_joint_budget_mohm"],
        "max_d1_full_assembly_height_mm": 16,
        "max_d3_stretch_full_assembly_height_mm": 10,
        "nominal_existing_model_bank_count": h["existing_nominal_bank_count"],
        "preferred_vrating_v": h["output_vrating_preferred_v"],
    }
    for name in ("capacitance_min_mf", "bank_ripple_required_arms",
                 "bank_cap_esr_budget_mohm"):
        if not _positive_finite(targets[name]):
            raise ValueError("invalid cap bank target")
    options = {row["id"]: row for row in output["candidates"]}
    base = options["reduced_2_contacts_50x2x15"]
    if (base["total_counted_separable_contacts"] != 2
            or not _positive_finite(base["bar_pair_uohm_at_100c"])
            or output["design_basis_uohm_both_rails"] != 150):
        raise ValueError("output contact model changed")
    connector = inp["connector_family"]
    contact_cases = {}
    for kind, per in (
        ("manufacturer_family_low_uohm_not_exact_part",
         connector["contact_zone_resistance_uohm_low"]),
        ("manufacturer_family_high_uohm_not_exact_part",
         connector["contact_zone_resistance_uohm_high"]),
    ):
        contact_only = base["total_counted_separable_contacts"] * per
        total = (contact_only + base["bar_pair_uohm_at_100c"]
                 + output["reserved_pcb_uohm_unverified"])
        contact_cases[kind] = {
            "per_contact_zone_uohm_family_note_not_exact_part": per,
            "both_poles_total_contact_uohm": contact_only,
            "full_two_pole_arithmetic_uohm": round(total, 3),
            "passes_150uohm_arithmetic_only": total <= 150,
        }
    return {
        "classification": "OEM_SOURCING_SCREEN_NOT_VENDOR_SIGNOFF_NOT_FOR_FAB",
        "source_data": SRC.relative_to(ROOT).as_posix(),
        "source_count_oem_links": len(inp["sources"]),
        "source_specification_temperature_caveat": (
            "Part resistance measured at its quoted OEM temperature and "
            "ripple rating at another quoted temperature are independent "
            "parameter screens, NOT a guaranteed joint operating point. "
            "At 200.62kHz and in the actual 16mm assembly re-measure."
        ),
        "targets": targets,
        "capacitor_options": [capacitor_row(c, targets)
                              for c in inp["capacitor_candidates"]],
        "connector_risk": {
            "source_id": connector["source_id"],
            "basis": "Wurth REDCUBE PRESS-FIT family app note, NOT a part-specific spec",
            "loop_resistance_budget_uohm_both_poles": 150,
            "assumed_counted_contacts_total_both_poles": 2,
            "bar_pair_uohm_100c_from_existing_concept": base["bar_pair_uohm_at_100c"],
            "reserved_pcb_uohm_unverified": output[
                "reserved_pcb_uohm_unverified"],
            "family_pressfit_contact_zone_range_cases": contact_cases,
            "manufacturer_rated_current_does_not_certify_low_loop_resistance": True,
            "mechanical_cad_and_kelvin_evidence_required": True,
            "physical_approval": False,
        },
        "magnetics": {
            **inp["magnetic_core_sources"],
            "core_material_Bs_measurement_conditions_not_interchangeable": True,
            "actual_100c_L_I_gap_and_24_real_physical_pads_verified": False,
            "full_16mm_height_and_coldplate_verified": False,
        },
        "safety": {
            "oem_urls_are_independent_references_not_reproduced_datasheets": True,
            "series_cap_bank_esr_budget_is_not_output_150uohm_loop_budget": True,
            "actual_bom_updated": False,
            "vendor_quotes_received": False,
            "assembly_height_qualified": False,
            "original_easyeda_project_modified": False,
            "full_hardware_fault_shutdown_qualified": False,
            "fabrication_approved": False,
        },
        "next_action": [
            "Request exact 100/200kHz ESR-versus-temperature and per-part ripple derating for shortlisted capacitor banks, plus PCB/current-sharing layout and worst-case C tolerance",
            "Ask 2+ magnetics vendors for T1-T4, CT, Lr finished pads/DOT/100C L(I), AC-loss and <=16mm total board/thermal stack drawing",
            "Ask high-current interconnect vendor for exact assembled hot Kelvin R(VOUT+PGND), not pressfit family ampacity; prefer physically countable continuous bars/inlays",
            "Validate TI UCC24624 REG/DC-bias cap, VDS Kelvin and default-off fault path on physical D0; this document is not D0 signoff",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    result = build()
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.write:
        OUT.write_text(payload, encoding="utf-8", newline="\n")
    elif args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != payload:
            print("OEM sourcing screen not source-reproducible; regenerate --write")
            return 2
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
