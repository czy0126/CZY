"""Performance-first component RFQ from committed 48/50V simulation evidence.

No price cap. D1 first-article full assembly target <=16 mm and D2 <=16 mm;
the previous <=10 mm is D3 stretch only. Actual pin-outs, component SOA and
hardware safety gates remain mandatory. Design targets != qualified parts.
Regenerate:
  python tools/performance_first_design.py --write
Verify:
  python tools/performance_first_design.py
"""
from __future__ import annotations
import argparse
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PP = ROOT / "design/v3/power_priority"
HW = ROOT / "hardware/dcx_main"
OUT_JSON = PP / "high_margin_design_gate.json"
OUT_CSV = HW / "performance_first_component_rfq.csv"

# Engineering margins, NOT measured device ratings.
FAULT_PEAK_MARGIN = 1.20
INDUCTANCE_MAX_FACTOR = 1.10
BSAT_USAGE_MAX = 0.80
PREFERRED_AE_MM2 = 200.0
OPTIONAL_FOUR_TURN_AE_MM2 = 150.0
COUT_VRATED_MIN = 4.0
COUT_VRATED_PREFERRED = 6.3
COUT_ESR_TOTAL_MOHM = 0.10
COUT_ESR_RFQ_TARGET_MOHM = 0.07
COUT_PCB_ESR_BUDGET_MOHM = 0.03
COUT_RIPPLE_MARGIN = 1.50
SR_PEAK_MARGIN = 1.25
D1_ASSEMBLY_HEIGHT_LIMIT_MM = 16.0
D2_ASSEMBLY_HEIGHT_LIMIT_MM = 16.0
D3_STRETCH_HEIGHT_LIMIT_MM = 10.0


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _r(x: float) -> float:
    return round(float(x), 6)


def build() -> tuple[dict, list[dict[str, str]]]:
    hot50 = _load(PP / "hotfault_50v_120a.json")
    probe48 = _load(PP / "sr_fault_probe_48v_120a.json")
    passive = _load(ROOT / "design/v3/bom/passive_requirements.json")
    lr = _load(ROOT / "design/v3/bom/lr_design.json")
    capbank = _load(ROOT / "design/v3/bom/cout_bank.json")
    cinbank = _load(ROOT / "design/v3/bom/cin_bank.json")
    crbank = _load(ROOT / "design/v3/bom/cr_bank.json")
    cad = _load(HW / "d1_fabrication_gate.json")
    connection = _load(HW / "output_joint_reduction_cases.json")
    if (connection.get("status") != "UNVERIFIED_INTERFACE_TOPOLOGY_REDESIGN_NOT_FOR_FAB"
            or connection.get("fabrication_approved") is not False
            or connection.get("hardware_qualified") is not False):
        raise ValueError("output interface design provenance changed")
    by_connection = {c["id"]: c for c in connection["candidates"]}
    compact_two = by_connection["reduced_2_contacts_50x2x15"]
    compact_four = by_connection["wide_4_contacts_50x2x15"]
    two_50 = compact_two["joint_scenarios_uohm"]["50"]
    four_50 = compact_four["joint_scenarios_uohm"]["50"]
    if (compact_two["total_counted_separable_contacts"] != 2
            or compact_four["total_counted_separable_contacts"] != 4
            or two_50["passes_resistance_arithmetic_only"] is not True
            or four_50["passes_resistance_arithmetic_only"] is not False):
        raise ValueError("100A output topology screen changed; requalify RFQ")
    if hot50["solver_prefix_only"] is not True:
        raise ValueError("fault evidence regime changed: revalidate high-current margin")
    peak = float(hot50["fault"]["ipri_peak_before_trip_a"])
    sr_peak = float(hot50["fault"]["sr_forward_peak_whole_record_a"])
    bsat = (float(lr["candidates"][1]["worst_flux_t"]) /
            float(lr["candidates"][1]["worst_flux_frac_bsat"]))
    inductance_max_h = float(lr["inductance_h"]) * INDUCTANCE_MAX_FACTOR
    design_current = peak * FAULT_PEAK_MARGIN
    limit_t = bsat * BSAT_USAGE_MAX
    core_min_ae_mm2 = float(128)  # ELP32 existing Amin, from validated TDK geometry
    def b_at(turns: int, ae_mm2: float) -> float:
        return inductance_max_h * design_current / (turns * ae_mm2 * 1e-6)
    def min_ae(turns: int) -> float:
        return inductance_max_h * design_current / (turns * limit_t) * 1e6
    # The ripple requirement is the worst measured load, not the rated one: the
    # 120 A overload points save I(Cout) directly, the 100 A deck only carries the
    # four-SR reconstruction.  cout_bank.json already states which point won, so
    # read its answer rather than re-deriving it from the rated-point JSON.
    r_ripple_rated = float(passive["cout_ripple"]["ripple_rms_a"])
    r_ripple = float(capbank["requirements"]["irms_a"])
    if r_ripple <= r_ripple_rated:
        raise ValueError("cout_bank no longer sizes the ripple above the rated point")
    r_target = r_ripple * COUT_RIPPLE_MARGIN
    # Same rule for the two banks sized in the previous stage.  Asking a supplier
    # for the rated-point number is what put Cout 6.8 % low; Cin and Cr would be
    # 19.6 % and 18.8 % low, so the evidence column quotes the overload point and
    # keeps the rated figure only as context.
    cin_ripple = float(cinbank["requirements"]["bridge_ac_rms_a_at_worst_measured_load"])
    cin_ripple_rated = float(cinbank["requirements"]["bridge_ac_rms_a_at_100a"])
    cr_ripple = float(crbank["requirements"]["irms_a"])
    cr_ripple_rated = float(crbank["requirements"]["sizing_points"]["rated_100a"]["i_rms_a"])
    if cin_ripple <= cin_ripple_rated:
        raise ValueError("cin_bank no longer sizes the ripple above the rated point")
    if cr_ripple <= cr_ripple_rated:
        raise ValueError("cr_bank no longer sizes the ripple above the rated point")
    baseline = next(row for row in capbank["banks"]
                    if row["part"] == "KEMET A720V477M2R5APE003")
    high_at_end = probe48["results"]["devices_high_at_end"]
    late_max = float(probe48["results"]["final_latch_max_current_a"])
    if sorted(high_at_end) != ["1A", "2A", "3A", "4A"]:
        raise ValueError("new SR fault observation: re-evaluate interlock RFQ")
    envelope = {
        "status": "UNVERIFIED_RFQ_TARGETS_NOT_RATED_NOT_FOR_FAB",
        "cost_policy": "NO_COST_CEILING_PER_USER_DIRECTION",
        "constraints": {
            # Historical 10mm high-margin / TDK catalog screen is an
            # immutable D3 reference used by lr_core_geometry_screen and
            # d1_staged_rebaseline. It must NOT dictate D1/D2 supplier RFQ.
            "maximum_assembly_height_mm": D3_STRETCH_HEIGHT_LIMIT_MM,
            "d1_100a_first_article_total_height_mm": D1_ASSEMBLY_HEIGHT_LIMIT_MM,
            "d2_120a_total_height_mm": D2_ASSEMBLY_HEIGHT_LIMIT_MM,
            "d3_stretch_total_height_mm": D3_STRETCH_HEIGHT_LIMIT_MM,
            "thermal_detail": "DEFERRED_BUT_DEVICE_SOA_AND_PROTECTION_MANDATORY",
            "no_invented_mpn": True,
        },
        "magnetics": {
            "observed_50v_fault_peak_a": _r(peak),
            "observed_peak_is_solver_prefix": True,
            "design_multiplier": FAULT_PEAK_MARGIN,
            "rfq_current_a": _r(design_current),
            "l_max_envelope_uh": _r(inductance_max_h * 1e6),
            "bsat_reference_100c_t": _r(bsat),
            "max_bsat_usage": BSAT_USAGE_MAX,
            "design_flux_limit_t": _r(limit_t),
            "existing_core_amin_mm2": core_min_ae_mm2,
            "existing_three_turn_worst_b_t": _r(b_at(3, core_min_ae_mm2)),
            "three_turn_min_ae_mm2": _r(min_ae(3)),
            "preferred_three_turn_amin_mm2": PREFERRED_AE_MM2,
            "preferred_three_turn_worst_b_t": _r(b_at(3, PREFERRED_AE_MM2)),
            "four_turn_min_ae_mm2": _r(min_ae(4)),
            "optional_four_turn_amin_mm2": OPTIONAL_FOUR_TURN_AE_MM2,
            "optional_four_turn_worst_b_t": _r(b_at(4, OPTIONAL_FOUR_TURN_AE_MM2)),
            "status": "REDESIGN_OR_VENDOR_FIRST_ARTICLE_REQUIRED",
            "limitation": (
                "1.10x L and 1.20x peak are design scenarios; flux uses constant L, "
                "not a validated nonlinear BH curve. Prefer custom low-profile larger-Ae "
                "or distributed-gap assembly, not a blind multi-mm single gap."
            ),
        },
        "capacitors": {
            "existing_nominal_bank_count": baseline["n"],
            "existing_nominal_v_rating_v": baseline["v_rated"],
            "output_vrating_min_v": COUT_VRATED_MIN,
            "output_vrating_preferred_v": COUT_VRATED_PREFERRED,
            "output_bank_c_min_mf": _r(float(baseline["bank_capacitance_f"]) * 1e3),
            "output_model_ripple_rms_a": _r(r_ripple),
            "output_model_ripple_rms_rated_a": _r(r_ripple_rated),
            "output_ripple_target_rms_a": _r(r_target),
            "output_esr_including_copper_target_mohm": COUT_ESR_TOTAL_MOHM,
            "output_copper_and_joint_budget_mohm": COUT_PCB_ESR_BUDGET_MOHM,
            "output_cap_bank_esr_budget_mohm": _r(
                COUT_ESR_TOTAL_MOHM - COUT_PCB_ESR_BUDGET_MOHM),
            "status": "PENDING_DATASHEETS_AND_3D_LAYOUT",
            "limitation": (
                "Current 2.5V/15-part bank is a model equivalence, not qualified "
                "for startup overshoot, voltage derating or connection resistance. "
                "C/ESR/RMS must be met at DC bias, temperature, frequency and lifetime."
            ),
        },
        "sr_protection": {
            "observed_single_device_forward_peak_50v_a": _r(sr_peak),
            "observed_peak_is_solver_prefix": True,
            "sensitivity_factor": SR_PEAK_MARGIN,
            "screening_current_a": _r(sr_peak * SR_PEAK_MARGIN),
            "48v_A_gates_high_at_end": high_at_end,
            "48v_final_high_interval_max_current_a": _r(late_max),
            "48v_final_high_interval_i2t_total_a2s": _r(
                probe48["results"]["final_latch_i2t_abs_total_a2s"]),
            "status": "HARD_FAULT_INTERLOCK_DESIGN_REQUIRED_NOT_TESTED",
            "limitation": (
                "High gate voltage at final sample does not mean hundreds of amps "
                "persist: late high-gate interval only <=1.41A in the 48V model. "
                "No real UCC24624 standby/SOA model. Evaluate a latched hardware "
                "inhibit for primary+all 8 SR; verify actual Vgs/Id/Vds after OC."
            ),
        },
        "output_interface": {
            "source": "hardware/dcx_main/output_joint_reduction_cases.json",
            "status": connection["status"],
            "both_pole_resistance_budget_uohm": connection["design_basis_uohm_both_rails"],
            "four_joint_wide_50u_case_total_uohm": four_50["total_uohm"],
            "two_joint_wide_50u_case_total_uohm": two_50["total_uohm"],
            "two_joint_wide_50u_case_margin_uohm": two_50["margin_to_150uohm"],
            "joint_resistance_is_unverified": True,
            "physical_2joint_topology_verified": False,
            "physical_interconnect_height_verified": False,
            "required_exit": "two-pole native CAD net and mechanical DFM; count every physical contact; Kelvin 4-wire resistance at assembled temperature and torque",
        },
        "cad": {
            "fabrication_gate": cad["status"],
            "unverified_physical_magnetics": cad["counts"]["magnetics_missing_physical_pads"],
            "placeholder_count": len(cad["counts"]["refs_with_placeholders"]),
        },
        "hardware_continuous_rating_approved": False,
        "next_priority": [
            "SR all-gate fault inhibit and complete 50V simulation",
            "larger-Ae/custom-gapped Lr supplier quote + L(I) test",
            "high-voltage low-ESR output bank RFQ and PCB spreading model",
            "real magnetic terminals, MPNs, GUI ERC and netted main PCB",
            "full device SOA and electrical stress verification",
        ],
    }
    def row(group: str, evidence: str, request: str, gate: str) -> dict[str, str]:
        return {
            "priority": "P0", "group": group, "evidence": evidence,
            "unlimited_cost_request": request,
            "acceptance_evidence": gate,
            "supplier_mpn_or_custom_drawing": "",
            "manufacturer_datasheet_or_signed_drawing": "",
            "owner": "", "reviewer": "", "decision": "PENDING",
        }
    rfqs = [
        row("Lr_custom_flat_magnetic",
            f"50V early-fault peak {peak:.2f}A; 3T/Amin128mm2 fails tolerance budget",
            f"3T; Amin>=200mm2 preferred; >= {min_ae(3):.1f}mm2 mathematical floor; "
            f"Lmax={inductance_max_h*1e6:.2f}uH; I_design={design_current:.1f}A; "
            "max B <= 0.80*Bsat at 100C; D1 full assembly <=16mm; D3 stretch <=10mm",
            "Actual L(I), gap/distributed gap, B-H at temperature, winding AC loss, winding terminals/DOT, physical 3D"),
        row("Lr_4turn_alternative",
            f"existing ELP32 3T gives B~{b_at(3,128):.3f}T with margins",
            f"4T; Amin>=150mm2 preferred; >= {min_ae(4):.1f}mm2 floor; "
            "avoid unverified single large gap; width/area may grow not height",
            "Independent distributed-gap/low-fringing vendor electromagnetic model and first-article L(I)"),
        row("Cout_bank_high_voltage",
            f"baseline 15x470uF/2.5V nominal; {r_ripple:.2f}A RMS at the 50V/120A overload "
            f"({r_ripple_rated:.2f}A at the rated 100A, a four-SR reconstruction), "
            "7.05mF, ideal 0.2mOhm",
            f">=4V rated, 6.3V preferred within D1 <=16mm full stack; >=7.05mF; "
            f"bank ripple >={r_target:.2f}Arms; "
            f"ESR bank <={COUT_ESR_RFQ_TARGET_MOHM:g}mOhm at operating frequency/temperature",
            "Original datasheets; actual PCB copper/joints <=0.03mOhm; overshoot/ripple/reliability and envelope"),
        row("Cin_high_ripple",
            f"{cin_ripple:.2f}A bridge AC ripple at the 120A overload "
            f"({cin_ripple_rated:.2f}A at the rated 100A); ideal 1mOhm source distorts capacitor current",
            "RFQ >=8A RMS at ~200kHz with sufficient DC-bus transient voltage derating",
            "Manufacturer ripple/impedance at operating frequency and temperature; realistic source impedance deck"),
        row("Cr_resonant_low_loss",
            f"{cr_ripple:.2f}A RMS at the 120A overload ({cr_ripple_rated:.2f}A at the rated 100A), "
            f"reconstructed Vpk {float(crbank['requirements']['v_max_v']):.2f}V",
            "RFQ >15A RMS and >=100V rated film or equivalent; prioritize low ESR/ESL and flatter profile",
            "Temperature/frequency ESR, self resonance, actual 50V/120A stress and physical mounting"),
        row("SR_MOSFET_and_drive",
            f"50V fault model {sr_peak:.2f}A instantaneous single SR forward peak (prefix)",
            f"SOA screening at {sr_peak*SR_PEAK_MARGIN:.0f}A transient design target, "
            "prefer additional current-sharing/parallel options only after charge/loop analysis",
            "Pulsed SOA vs pulse duration/Vds/Tj, Kelvin source, real UCC24624 gate drive and reverse current"),
        row("Independent_hardware_fault_latch",
            "4 A-side SR gates reassert 10.89V, 1.41A late model current; 50V fault solver incomplete",
            "Independent latched fault inhibit covering primary AND all eight SR, default-off at undervoltage; "
            "fast transient comparator path independent of 47us RC where appropriate",
            "Physical comparator/level-shift/logic power-up/down schematic; no shoot-through; all-waveform validation"),
        row("J_OUT_high_current_interconnect",
            f"100A VOUT+PGND loop 150uOhm internal target; "
            f"four×50uOhm contacts alone use 200uOhm; "
            f"modeled four-contact total {four_50['total_uohm']:.3f}uOhm",
            f"Quote CAD/DFM A: four separable contacts each verified <=28.30uOhm "
            f"or B: integrated both-pole 2-contact 50x2x15mm concept "
            f"{two_50['total_uohm']:.3f}uOhm at 50uOhm/contact "
            f"with remaining bonds included in PCB budget; D1 full stack <=16mm",
            "Provide full VOUT/PGND nets and numbered joints; vendor DFM/height; "
            "Kelvin 4-wire hot resistance and pulse temperature at 100A; "
            "unmeasured contacts do NOT qualify fab"),
        row("Main_board_vendor_signoff",
            "5 magnetics no physical pads, 61 placeholder refs, GUI ERC/PCB absent",
            "No price ceiling for real footprint, via-in-pad fill, copper inlay or heavy copper if manufacturable",
            "Signed 24 magnetic terminals, BOM/footprints, real GUI ERC, netted PCB/DRC and fab drawings"),
    ]
    return envelope, rfqs


FIELDS = (
    "priority", "group", "evidence", "unlimited_cost_request",
    "acceptance_evidence", "supplier_mpn_or_custom_drawing",
    "manufacturer_datasheet_or_signed_drawing", "owner", "reviewer", "decision",
)


def to_csv(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    data, rows = build()
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    csv_text = to_csv(rows)
    if args.write:
        OUT_JSON.write_text(content, encoding="utf-8", newline="\n")
        OUT_CSV.write_text(csv_text, encoding="utf-8", newline="\n")
    else:
        if json.loads(OUT_JSON.read_text(encoding="utf-8")) != data:
            raise SystemExit("performance-first design JSON stale")
        if OUT_CSV.read_text(encoding="utf-8") != csv_text:
            raise SystemExit("performance-first RFQ CSV stale")
    print("Performance-first RFQ only: NOT RATED / NOT FOR FAB.")


if __name__ == "__main__":
    main()
