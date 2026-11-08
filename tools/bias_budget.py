"""T1: freeze the per-controller SR bias interface.

Why this module exists
----------------------
The 2026-11-07 Rev B round calculated a single-pair gate budget of 34.80 mA
from ``2 * 83 nC * 200.622 kHz + 1.5 mA``.  That used the BSC010N04LS6 gate
charge at **10 V**, but the UCC24624 gate clamp ``VGHI`` is specified up to
**11.68 V** and its internal regulator ``VREG`` up to **11.9 V**.  The gate is
therefore charged above the 10 V test point, and the real worst-case current is
higher.  This module replaces the single number with a per-controller branch
budget that carries every datasheet max it depends on, plus the corners the
datasheet does *not* bound (marked ``unbound``).

It is arithmetic on vendored datasheet values, not a measurement and not a
device qualification.  The P-MOS and series diode are **not** in
``references/datasheets``; their parameters are URL-only web values (see
CLAUDE.md section 4) and are carried as explicit, conservative bounds.

The decision this module exists to make
---------------------------------------
Two different questions hide behind "does 22 ohm work?":

1. **Functional VGS**: can the SR FET still be enhanced?  BSC010N04LS6 is
   characterised at VGS = 4.5 V, so anything above ~4.5 V on the gate works.
2. **Datasheet regulation**: does VDD_SR stay high enough for the UCC24624
   internal regulator to hold REG in its 9.9-11.9 V band (plus load regulation
   and dropout)?  Below that the part runs in pass-through; it still works but
   it is out of spec and the gate clamp is no longer the specified 11.68 V.

They can disagree at the worst-case corner, so the report states both.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pcb" / "bias_cut_revision_b"
JSON_PATH = OUT / "bias_budget.json"

# ---------------------------------------------------------------- datasheet anchors
# UCC24624, references/datasheets/ucc24624.txt (SLUSD48C), section 7.5 / 7.6.
UCC_DS = "references/datasheets/ucc24624.txt"
IVDD_RUN_MAX_A = 1.5e-3          # IVDDRUN, VVDD = 12 V (15 V not specified -> unbound)
IVDBIAS_MAX_A = 0.5e-6           # IVDBIAS, per VD pin
VREG_MIN_V, VREG_TYP_V, VREG_MAX_V = 9.9, 11.0, 11.9
VREGLG_MAX_V = 75e-3             # load regulation, ILOAD_REG 0..30 mA
VREGDO_MAX_V = 0.5               # dropout, VVDD = 5 V passthrough, ILOAD 0..10 mA
VGHI_MAX_V = 11.68               # VG high clamp
VREGOFF_MAX_V = 4.25             # REG UVLO turn-off, max column of 3.63/4/4.25
IREGLIM_MAX_A = 95e-3
IREGSC_MAX_A = 13e-3

# BSC010N04LS6, references/datasheets/bsc010n04ls6.txt, gate charge table.
FET_DS = "references/datasheets/bsc010n04ls6.txt"
QG_10V_MAX_C = 83e-9             # Qg max, VGS 0->10 V, VDD=20 V, ID=50 A
CISS_MAX_F = 6000e-12            # Ciss max, VGS=0, VDS=20 V, 1 MHz
IGSS_MAX_A = 100e-9              # gate-source leakage max, VGS=20 V
VGS_CHARACTERISED_V = 4.5        # lowest RDS(on) gate voltage in the datasheet

# Design point.
F_SW_HZ = 200.622e3
FETS_PER_CONTROLLER = 2
VDD_IN_MIN_V = 14.25             # 15 V - 5 %
VDD_IN_NOM_V = 15.0
VDD_IN_MAX_V = 15.75             # 15 V + 5 %

# Rev B branch (candidate parts; DMP3098L / ES1D are NOT vendored).
R59_OHM = 22.0
R59_TOL = 0.01
R59_MAX_OHM = R59_OHM * (1 + R59_TOL)
Q50_RDS_MAX_OHM = 0.20           # unverified bound; DMP3098L datasheet not in repo
D50_VF_MAX_V = 0.92              # unverified; ES1D max Vf at 1 A, far above 40 mA
D50_VF_TYP_V = 0.60              # unverified typical at ~40 mA
TEMP_GATE_SCENARIO = 1.10        # +10 % unquantified temperature/process scenario

# Bench dummy load R62 (removed on integration) and the required scan.
LOAD_SCAN_A = (0.0, 0.005, 0.010, 0.020, 0.030, 0.040, 0.050)
CONTROLLERS_PER_MACHINE = 4


def qg_at(vgs_v: float) -> float:
    """Conservative gate charge above the 10 V test point.

    ``Qg(V) <= Qg(10 V) + Ciss_max * (V - 10 V)`` for V above the Miller
    plateau, where Ciss is approximately Cgs and constant.  Ciss is specified
    at VDS = 20 V; at the low VDS of an on SR FET Crss is larger, so this is a
    lower bound on the *extra* charge.  The direction (bigger current) is
    conservative, the magnitude is not a hard bound.  Flagged as such.
    """
    if vgs_v <= 10.0:
        return QG_10V_MAX_C
    return QG_10V_MAX_C + CISS_MAX_F * (vgs_v - 10.0)


def gate_current_a(vgs_v: float, scale: float = 1.0) -> float:
    return FETS_PER_CONTROLLER * qg_at(vgs_v) * F_SW_HZ * scale


def fixed_leakage_a() -> float:
    return FETS_PER_CONTROLLER * (IVDBIAS_MAX_A + IGSS_MAX_A)


def branch(vdd_in: float, extra_load_a: float, *, vf_v: float,
           rds_ohm: float = Q50_RDS_MAX_OHM, r59_ohm: float = R59_MAX_OHM,
           gate_scale: float = 1.0) -> dict:
    """Self-consistent branch solve.

    The gate current depends on the gate voltage, the gate voltage depends on
    VDD_SR (through dropout), and VDD_SR depends on the gate current through
    the series resistance.  Iterate to a fixed point instead of assuming
    VGHI = 11.68 V at a corner where the regulator may have dropped out.
    """
    vg = VGHI_MAX_V
    for _ in range(200):
        i_gate = gate_current_a(vg, gate_scale)
        i_total = i_gate + IVDD_RUN_MAX_A + fixed_leakage_a() + extra_load_a
        vdd_sr = vdd_in - vf_v - i_total * (r59_ohm + rds_ohm)
        vg_next = min(VGHI_MAX_V, vdd_sr - VREGDO_MAX_V)
        if abs(vg_next - vg) < 1e-12:
            break
        vg = vg_next
    return {
        "vdd_in_v": vdd_in,
        "extra_load_a": extra_load_a,
        "vf_v": vf_v,
        "r59_ohm": r59_ohm,
        "q50_rds_ohm": rds_ohm,
        "gate_scale": gate_scale,
        "vgh_v": vg,
        "qg_c": qg_at(vg),
        "i_gate_a": i_gate,
        "i_run_a": IVDD_RUN_MAX_A,
        "i_leak_a": fixed_leakage_a(),
        "i_total_a": i_total,
        "vdd_sr_v": vdd_sr,
        "reg_required_v": regulation_required_v(),
        "in_regulation": vdd_sr >= regulation_required_v(),
        "functional_vgs": vg >= VGS_CHARACTERISED_V,
        "uvlo_margin_v": vg - VREGOFF_MAX_V,
    }


def regulation_required_v() -> float:
    """Lowest VDD_SR at which the regulator can still hold REG in spec."""
    return VREG_MAX_V + VREGLG_MAX_V + VREGDO_MAX_V


def scan(*, vf_v: float = D50_VF_MAX_V, gate_scale: float = 1.0,
         r59_ohm: float = R59_MAX_OHM) -> dict:
    rows = {}
    for vdd_in in (VDD_IN_MIN_V, VDD_IN_NOM_V, VDD_IN_MAX_V):
        for load in LOAD_SCAN_A:
            key = f"{vdd_in:.2f}V_{int(round(load * 1e3))}mA"
            rows[key] = branch(vdd_in, load, vf_v=vf_v, gate_scale=gate_scale,
                               r59_ohm=r59_ohm)
    return rows


def shared_bus_branch(vdd_in: float, controllers: int) -> dict:
    """All controllers fed through one series resistor: four times the current."""
    current = branch(VDD_IN_NOM_V, 0.0, vf_v=D50_VF_MAX_V)["i_total_a"] * controllers
    vdd_sr = vdd_in - D50_VF_MAX_V - current * (R59_MAX_OHM + Q50_RDS_MAX_OHM)
    return {"i_total_a": current, "vdd_sr_v": vdd_sr,
            "in_regulation": vdd_sr >= regulation_required_v()}


def break_even_diode_vf_v() -> float:
    """D50 Vf at the branch current that just meets full regulation.

    The empirical case for the branch is that the ES1D's *1 A* max Vf (0.92 V)
    is not the drop at ~39 mA; the question is how much drop the corner can
    still absorb.  Vendor the diode datasheet and compare Vf at the operating
    current against this number.
    """
    worst = branch(VDD_IN_MIN_V, 0.0, vf_v=0.0)
    return VDD_IN_MIN_V - worst["i_total_a"] * (R59_MAX_OHM + Q50_RDS_MAX_OHM) \
        - regulation_required_v()


def summary() -> dict:
    worst = branch(VDD_IN_MIN_V, 0.0, vf_v=D50_VF_MAX_V)
    typical = branch(VDD_IN_MIN_V, 0.0, vf_v=D50_VF_TYP_V)
    hot = branch(VDD_IN_MIN_V, 0.0, vf_v=D50_VF_MAX_V, gate_scale=TEMP_GATE_SCENARIO)
    shared = shared_bus_branch(VDD_IN_MIN_V, CONTROLLERS_PER_MACHINE)
    inputs = sorted(p["vdd_sr_v"] for p in scan().values())
    break_even = break_even_diode_vf_v()
    return {
        "checks": {
            "worst_case_meets_regulation_at_1a_max_vf":
                worst["in_regulation"],
            "operating_point_passes_if_diode_vf_below_break_even":
                D50_VF_TYP_V <= break_even,
            "single_branch_worst_case_keeps_functional_vgs":
                worst["functional_vgs"],
            "typical_corner_meets_full_regulation":
                typical["in_regulation"],
            "worst_case_stays_above_reg_uvlo":
                worst["uvlo_margin_v"] > 0.0,
            "four_groups_shared_22r_fails_regulation":
                not shared["in_regulation"],
        },
        "results": {
            "per_controller_branch_a": worst["i_total_a"],
            "old_flat_10v_budget_a": 2 * QG_10V_MAX_C * F_SW_HZ + IVDD_RUN_MAX_A,
            "gate_current_a": worst["i_gate_a"],
            "gate_current_hot_scenario_a": hot["i_gate_a"],
            "vgh_v": worst["vgh_v"],
            "required_regulation_vdd_v": regulation_required_v(),
            "break_even_diode_vf_v": break_even,
            "d50_vf_at_1a_max_v": D50_VF_MAX_V,
            "d50_vf_operating_typ_v": D50_VF_TYP_V,
            "vdd_sr_worst_v": worst["vdd_sr_v"],
            "vdd_sr_typical_v": typical["vdd_sr_v"],
            "worst_minus_required_v": worst["vdd_sr_v"] - regulation_required_v(),
            "typical_minus_required_v": typical["vdd_sr_v"] - regulation_required_v(),
            "scan_vdd_sr_min_v": inputs[0],
            "scan_vdd_sr_max_v": inputs[-1],
            "four_group_shared_22r_drop_v": (
                shared["i_total_a"] * (R59_MAX_OHM + Q50_RDS_MAX_OHM)),
            "four_group_own_branch_drop_v": (
                worst["i_total_a"] * (R59_MAX_OHM + Q50_RDS_MAX_OHM)),
        },
    }


def report() -> dict:
    s = summary()
    return {
        "task": "T1_BIAS_INTERFACE_FREEZE",
        "evidence": "ARITHMETIC_ON_VENDORED_DATASHEET_VALUES",
        "hardware_qualified": False,
        "measured": False,
        "checks": s["checks"],
        "results": s["results"],
        "datasheet_anchors": {
            "ucc24624": {
                "file": UCC_DS,
                "ivdd_run_max_a": IVDD_RUN_MAX_A,
                "ivdd_run_condition": "VVDD = 12 V; 15 V not specified",
                "ivdbias_max_a": IVDBIAS_MAX_A,
                "vreg_v": {"min": VREG_MIN_V, "typ": VREG_TYP_V, "max": VREG_MAX_V},
                "vreglg_max_v": VREGLG_MAX_V,
                "vregdo_max_v": VREGDO_MAX_V,
                "vghi_max_v": VGHI_MAX_V,
                "vregoff_max_v": VREGOFF_MAX_V,
                "ireglim_max_a": IREGLIM_MAX_A,
                "iregsc_max_a": IREGSC_MAX_A,
            },
            "bsc010n04ls6": {
                "file": FET_DS,
                "qg_10v_max_c": QG_10V_MAX_C,
                "ciss_max_f": CISS_MAX_F,
                "igss_max_a": IGSS_MAX_A,
                "vgs_characterised_v": VGS_CHARACTERISED_V,
                "qg_condition": "VGS 0->10 V, VDD = 20 V, ID = 50 A",
            },
            "not_vendored": {
                "DMP3098L-7": {
                    "source": "https://www.diodes.com/datasheet/download/DMP3098L.pdf",
                    "status": "URL_ONLY_NOT_IN_REPO",
                    "carried_as": "Q50_RDS_MAX_OHM = 0.20 ohm conservative bound",
                },
                "ES1D-E3/61T": {
                    "source": "https://www.vishay.com/docs/88586/es1.pdf",
                    "status": "URL_ONLY_NOT_IN_REPO",
                    "carried_as": "D50_VF_MAX_V = 0.92 V (max at 1 A), TYP = 0.60 V",
                },
            },
        },
        "design_point": {
            "f_sw_hz": F_SW_HZ,
            "fets_per_controller": FETS_PER_CONTROLLER,
            "vdd_in_v": {"min": VDD_IN_MIN_V, "nom": VDD_IN_NOM_V, "max": VDD_IN_MAX_V},
            "r59_ohm": R59_OHM,
            "r59_tol": R59_TOL,
            "load_scan_a": list(LOAD_SCAN_A),
            "controllers_per_machine": CONTROLLERS_PER_MACHINE,
            "temp_gate_scenario": TEMP_GATE_SCENARIO,
        },
        "scan": scan(),
        "decision": {
            "single_controller_branch_required": True,
            "four_groups_may_not_share_one_22r": True,
            "twenty_two_ohm_proven_at_worst_case":
                s["checks"]["worst_case_meets_regulation_at_1a_max_vf"],
            "twenty_two_ohm_meets_functional_vgs_at_worst_case":
                s["checks"]["single_branch_worst_case_keeps_functional_vgs"],
            "closing_action": (
                "vendor the ES1D datasheet and read Vf at the ~39 mA branch current.  "
                f"The corner passes full regulation iff Vf <= "
                f"{s['results']['break_even_diode_vf_v']:.3f} V; the only vendored "
                f"number is the 1 A max of {D50_VF_MAX_V:.2f} V, which fails by "
                f"{-s['results']['worst_minus_required_v'] * 1e3:.0f} mV and is not the "
                "drop at 39 mA."),
            "required_change_if_diode_does_not_close_it": (
                "do not lower the threshold.  Either (a) specify pass-through "
                "operation with a temperature-bounded VGS and re-qualify the FET "
                "at that gate drive, or (b) replace the 22 ohm series resistor with a "
                "controlled current limit (or an external regulated bias) so the "
                "branch current no longer sets the drop."),
            "cannot_share_four_groups": (
                "four controllers on one 22 ohm resistor drop "
                f"{s['results']['four_group_shared_22r_drop_v']:.3f} V, "
                "which is outside any VDD_SR window; each UCC24624 needs its own "
                "series branch from VDD_IN."),
        },
        "unbound": [
            "IVDDRUN at VVDD = 15 V: the datasheet max is at 12 V only",
            "Qg at VGS = 11.68 V: extrapolated with Ciss_max, not a datasheet point",
            "Qg / IVDDRUN temperature and process spread beyond the 25 C max column",
            "DMP3098L Rds_on and SOA: datasheet not vendored",
            "ES1D Vf and reverse leakage at temperature: datasheet not vendored",
            "REG dropout at VVDD around 12 V: VREGDO is specified at 5 V passthrough only",
        ],
        "schematic_increment": {
            "kind": "PER_CONTROLLER_SERIES_BRANCH",
            "topology": "VDD_IN -> Q50 -> R59(22R 1%) -> D50(anode->cathode) -> VDD_SR",
            "per_controller": True,
            "reference_naming": "one Q50/R59/D50 set per UCC24624 (e.g. R59a..R59d, D50a..D50d)",
            "not_a_bus_limit": True,
            "note": "the Rev B bench drawing keeps one branch for the bench board; "
                    "integration must instantiate one branch per controller, not "
                    "one bus resistor for four.",
        },
    }


def main() -> None:
    data = report()
    OUT.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(json.dumps(data["checks"], indent=2))
    print(json.dumps({k: data["results"][k] for k in (
        "per_controller_branch_a", "old_flat_10v_budget_a",
        "vdd_sr_worst_v", "required_regulation_vdd_v", "worst_minus_required_v",
        "break_even_diode_vf_v", "four_group_shared_22r_drop_v")}, indent=2))


if __name__ == "__main__":
    main()
