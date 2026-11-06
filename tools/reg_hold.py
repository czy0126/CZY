"""UCC24624 hold-state thermal bound while the REG crowbar stays latched.

Why this module exists
----------------------
The 2026-11-06 R44 round answered "will the resistor survive a pulse" and left
the next question open: what does the *controller* do while REG is held down
for 10/100/1000 ms?  The board's crowbar is a linear load on the UCC24624
internal linear regulator, so its steady current is set by the regulator, not
by the 4.7 ohm resistor.

Two datasheet anchors bound that current (references/datasheets/ucc24624.txt,
7.5 Electrical Characteristics, page 6):

    IREGLIM  41 / 60 / 95 mA   at VVDD = 12 V, VREG = 8 V
    IREGSC  4.5 / 9.5 / 13 mA  at VVDD = 12 V, VREG = 0 V

The short-circuit current is smaller than the current limit, so the regulator
must fold back somewhere between 8 V and 0 V -- but the curve itself is not
specified.  A crowbar that stays at the 95 mA limit settles at
VREG = 95 mA * 4.748 ohm = 0.45 V and makes the IC dissipate 1.4 W; the same
IC at 13 mA dissipates 0.22 W.  The datasheet says both endpoints exist; it
does not say which one the crowbar lands on, so the worst case is 1.4 W and
that is above the 125 C junction limit.

Thermal numbers (7.4 Thermal Information and 7.1 Absolute Maximum Ratings):

    RthJA = 108.4 C/W (D, 8-pin SOIC, JEDEC board, still air)
    TJ max = 125 C (recommended operating and absolute maximum)

This module does not choose a circuit.  It reports the two anchors, the
bias-current limit each ambient implies, and the design requirements that
follow.  Nothing here is a measurement: ``measured`` stays false until a bench
records I_REG against V_REG at the board's own 15 V bias.
"""
from __future__ import annotations

import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASHEET = "references/datasheets/ucc24624.txt"

# UCC24624 datasheet, page 6 (7.5) and pages 4-5 (7.1/7.4).
RTH_JA_C_PER_W = 108.4
TJ_MAX_C = 125.0
TJ_ABS_MAX_C = 150.0
IREGLIM_MAX_A = 95e-3
IREG_SC_MAX_A = 13e-3
IVDD_RUN_MAX_A = 1.5e-3

# Board parameters that enter the equilibrium (see make_sr_fault_board.py).
VDD_NOM = 15.0
R_CROWBAR = 4.7
RDS_Q41 = 0.048
C_REG = 2.2e-6 + 100e-9

# A deliberate bench choice, not a datasheet value: the fault experiments run
# with the main power off, so the bias only has to carry IVDDRUN plus the gate
# charge of a normally switching pair.  40 mA is below the 50 C allowed current
# and above that idle/run load; the record row has to carry the actual ambient.
BENCH_BIAS_LIMIT_A = 40e-3


def equilibrium_vreg(current_a: float, r_total: float) -> float:
    """REG voltage where the crowbar current equals the regulator current."""
    return current_a * r_total


def controller_power_w(current_a: float, r_total: float, vdd: float) -> float:
    """Regulator pass-element loss plus the VDD quiescent current.

    The linear regulator's input current is its output current, so the pass
    element sees (VDD - VREG) * IREG.  IVDDRUN is the VDD current that does not
    leave through REG and is charged at the full VDD.  Gate drive is zero while
    the crowbar holds REG below UVLO.
    """
    return (vdd - equilibrium_vreg(current_a, r_total)) * current_a + vdd * IVDD_RUN_MAX_A


def thermal(current_a: float, r_total: float, vdd: float, ambient_c: float) -> dict:
    power = controller_power_w(current_a, r_total, vdd)
    rise = power * RTH_JA_C_PER_W
    return {
        "current_a": current_a,
        "vreg_eq_v": equilibrium_vreg(current_a, r_total),
        "controller_w": power,
        "rise_k": rise,
        "tj_c": ambient_c + rise,
        "within_tj_max": ambient_c + rise <= TJ_MAX_C,
        "within_tj_abs_max": ambient_c + rise <= TJ_ABS_MAX_C,
    }


def allowed_current_a(vdd: float, r_total: float, ambient_c: float) -> float:
    """Largest steady crowbar current that keeps TJ <= TJ_MAX at ``ambient_c``.

    Solves (VDD - I*R)*I + VDD*IVDDRUN = (TJ_MAX - Tamb)/Rth for the lower root.
    Returns 0.0 when the quiescent load alone already reaches the limit.
    """
    allowance = (TJ_MAX_C - ambient_c) / RTH_JA_C_PER_W - vdd * IVDD_RUN_MAX_A
    if allowance <= 0:
        return 0.0
    discriminant = vdd * vdd - 4 * r_total * allowance
    if discriminant < 0:
        return 0.0
    return (vdd - math.sqrt(discriminant)) / (2 * r_total)


def analysis(vdd: float = VDD_NOM, r_total: float = R_CROWBAR + RDS_Q41,
             ambient_c: float = 25.0) -> dict:
    """Both datasheet anchors, the ambient table, and the decision they force."""
    limit_anchor = thermal(IREGLIM_MAX_A, r_total, vdd, ambient_c)
    sc_anchor = thermal(IREG_SC_MAX_A, r_total, vdd, ambient_c)
    ambients = (25.0, 40.0, 50.0, 70.0)
    allowed = {f"{a:.0f}": allowed_current_a(vdd, r_total, a) for a in ambients}
    return {
        "datasheet": {
            "file": DATASHEET,
            "rth_ja_c_per_w": RTH_JA_C_PER_W,
            "tj_max_c": TJ_MAX_C,
            "tj_abs_max_c": TJ_ABS_MAX_C,
            "ireg_lim": {"min_a": 41e-3, "typ_a": 60e-3, "max_a": IREGLIM_MAX_A,
                         "condition": "VVDD = 12 V, VREG = 8 V"},
            "ireg_sc": {"min_a": 4.5e-3, "typ_a": 9.5e-3, "max_a": IREG_SC_MAX_A,
                        "condition": "VVDD = 12 V, VREG = 0 V"},
            "foldback_curve_specified": False,
        },
        "board": {"vdd_v": vdd, "r_total_ohm": r_total, "c_reg_f": C_REG,
                  "tau_s": r_total * C_REG},
        "anchors": {
            "current_limit_95ma": limit_anchor,
            "short_circuit_13ma": sc_anchor,
        },
        "allowed_continuous_current_a": allowed,
        "bench_bias_limit": {
            "chosen_a": BENCH_BIAS_LIMIT_A,
            "margin_at_25_c": allowed["25"] / BENCH_BIAS_LIMIT_A,
            "margin_at_50_c": allowed["50"] / BENCH_BIAS_LIMIT_A,
            "basis": "main power off during the fault experiments; the bias "
                     "carries IVDDRUN (1.5 mA max) plus the gate charge of a "
                     "normally switching pair, not a 100 A load",
            "rule": "record the actual ambient and limit in reg_hold_bench_record.csv; "
                    "if the ambient is above 50 C, lower the limit to the table value",
        },
        "decision": {
            "sustained_crowbar_approved": False,
            "measured": False,
            "worst_case_summary": (
                f"at the 95 mA current-limit anchor the IC dissipates "
                f"{limit_anchor['controller_w']:.3f} W, i.e. {limit_anchor['rise_k']:.0f} K "
                f"above ambient ({limit_anchor['tj_c']:.0f} C at 25 C), above TJ max"),
            "foldback_summary": (
                f"at the 13 mA short-circuit anchor it would dissipate "
                f"{sc_anchor['controller_w']:.3f} W and reach "
                f"{sc_anchor['tj_c']:.0f} C at 25 C, but the datasheet does not "
                "specify the curve between 8 V and 0 V"),
            "required": [
                "measure I_REG against V_REG at the board's 15 V bias before any hold "
                "longer than the bench limit (row H4)",
                "keep the REG crowbar: it is the only path that crosses UVLO in ~12 us",
                "if the foldback is not proven on the bench, add a latched bias cut for "
                "the long hold; the crowbar alone is not a long-hold answer",
                "a bias cut must be latched and reset only deliberately, and the gate "
                "state and re-arm sequence have to be re-checked, not assumed",
            ],
        },
        "open_items": [
            "IREGSC is specified at VVDD = 12 V; the board runs 15 V and the "
            "short-circuit current there is not specified",
            "IVDDRUN is also a 12 V number, so the 22.5 mW quiescent term is "
            "slightly low at 15 V; it is the smallest term in the budget",
            "gate charge during the ~12 us transition is not in the steady-state "
            "sum; it is a single event of order Qg(sync)*VREG per FET",
            "RthJA is a JEDEC-board, still-air number; the validation board is small and "
            "its mounted value is unverified",
            "the die thermal impedance Zth(t) is not in the datasheet, so no transient "
            "hold time can be derived, only the steady-state bound",
            "no hardware was available this round: every number here is a datasheet "
            "bound or arithmetic",
        ],
    }
