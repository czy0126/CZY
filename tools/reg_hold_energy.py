"""T2: REG hold energy and backfeed closure for the Rev B bias cut.

The 2026-11-07 Rev B round bounded "11.1 uF at 15.75 V is ~1.38 mJ" and left
three separate questions open.  They are not one question and must not share
one answer:

1. **Finite capacitor.**  The bias is cut, no external source feeds VDD_SR.
    The energy is fixed by the capacitor; what changes is how fast it leaves
    and therefore the *power* in the UCC24624.  A repeat-rate limit follows.
2. **Input switch delay.**  The bias cut is not instant.  Rev A measured
   13.36 us through a 60 pF placeholder gate; Rev B's real 1008 pF ``Ciss``
   makes it longer even with R50 at 10 k.  The delay is therefore imported
   from ``bias_cut_timing.cut_delay`` at the same supply as the energy, not
   carried as a constant here.  During that window the input still feeds the
   regulator.
3. **Continuous external injection.**  Something holds VDD_SR up.  The series
   diode blocks it from the input but cannot remove it.  The regulator then
   feeds the REG crowbar forever; the energy is unbounded and the only
   question is the foldback current.

Everything here is a time-domain ODE on ``reg_hold``'s datasheet anchors.  The
current versus REG curve between 8 V and 0 V is **not specified**, so each
scenario is reported at both specified endpoints (IREGLIM 95 mA and IREGSC
13 mA) instead of picking one.  Nothing is measured.

A note on why the two anchors are scenarios and not operating points: the
crowbar is a 4.748 ohm load, so a current of 95 mA would put REG at 0.45 V and
13 mA at 0.06 V.  Neither matches the datasheet's test point (8 V for IREGLIM,
0 V for IREGSC).  The regulator foldback between those points is unknown; the
two endpoints bracket the answer and the report never claims which one the
crowbar lands on.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import bias_cut_timing
import reg_hold

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pcb" / "bias_cut_revision_b"
JSON_PATH = OUT / "reg_hold_energy.json"

# Board / Rev B values.
C_SR_F = 11.1e-6
R57_OHM = 2200.0                 # Rev B slow discharge
Q54_RDS_OHM = 0.05               # AO3400A at VGS = 5 V, conservative
R58_OHM = 100e3
R_CROWBAR_TOTAL_OHM = reg_hold.R_CROWBAR + reg_hold.RDS_Q41
VREGDO_MAX_V = 0.5               # UCC24624 passthrough dropout, max column
VREGOFF_MAX_V = 3.63             # REG UVLO turn-off, min column of 3.63/4/4.25
IVDD_RUN_MAX_A = reg_hold.IVDD_RUN_MAX_A
IVDD_STBY_MAX_A = 200e-6
IREG_ANCHORS_A = {"short_circuit_13ma": 13e-3, "current_limit_95ma": 95e-3}
REV_A_MEASURED_CUT_S = 13.36e-6  # Rev A ECO; superseded, kept for comparison only
VDD_IN_MAX_V = 15.75
VDD_IN_NOM_V = 15.0
BACKFEED_V = 24.0                # the case in the report; 18 V is the milder one
BACKFEED_MILD_V = 18.0

# The regulator can hold REG above UVLO only while VDD exceeds this.
V_UVLO_VDD_V = VREGOFF_MAX_V + VREGDO_MAX_V


def _reg_current(v, anchor_a: float) -> float:
    """Crowbar/regulator current while the regulator is active."""
    return anchor_a if v > V_UVLO_VDD_V else 0.0


def _run_current(v) -> float:
    return IVDD_RUN_MAX_A if v > V_UVLO_VDD_V else IVDD_STBY_MAX_A


def finite_capacitor(v0: float = VDD_IN_MAX_V, anchor_a: float = IREG_ANCHORS_A[
        "current_limit_95ma"], dt: float = 1e-7, t_max: float = 5.0) -> dict:
    """Discharge the 11.1 uF through the crowbar, R57 and R58, no input.

    RK4 on VDD_SR only; the regulator's foldback current is held at one
    datasheet anchor until REG crosses UVLO, after which the part goes to
    standby and the capacitor drains only through the passive resistors.
    """
    v = v0
    t = 0.0
    e_r44 = e_ucc = e_r57 = e_r58 = 0.0
    samples: list[tuple[float, float, float, float]] = []

    def rhs(state: float) -> float:
        i_cb = _reg_current(state, anchor_a)
        i_run = _run_current(state)
        i_dis = state / (R57_OHM + Q54_RDS_OHM) + state / R58_OHM
        return -(i_cb + i_run + i_dis) / C_SR_F

    next_sample = 0.0
    while v > V_UVLO_VDD_V and t < t_max:
        i_cb = _reg_current(v, anchor_a)
        i_run = _run_current(v)
        v_reg = i_cb * R_CROWBAR_TOTAL_OHM
        e_r44 += i_cb * i_cb * R_CROWBAR_TOTAL_OHM * dt
        e_ucc += (max(v - v_reg, 0.0) * i_cb + v * i_run) * dt
        e_r57 += v * v / (R57_OHM + Q54_RDS_OHM) * dt
        e_r58 += v * v / R58_OHM * dt
        if t >= next_sample:
            samples.append((t, v, v_reg, i_cb))
            next_sample += 2e-4
        k1 = rhs(v)
        k2 = rhs(v + 0.5 * dt * k1)
        k3 = rhs(v + 0.5 * dt * k2)
        k4 = rhs(v + dt * k3)
        v += dt * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0
        t += dt
    v_final = max(v, 0.0)
    e_cap = 0.5 * C_SR_F * (v0 * v0 - v_final * v_final)
    return {
        "v0_v": v0,
        "anchor_a": anchor_a,
        "hold_s": t,
        "v_final_v": v_final,
        "v_uvlo_vdd_v": V_UVLO_VDD_V,
        "energy": {
            "cap_released_j": e_cap,
            "q41_r44_j": e_r44,
            "ucc24624_j": e_ucc,
            "r57_discharge_j": e_r57,
            "r58_bleed_j": e_r58,
            "sum_check_j": e_r44 + e_ucc + e_r57 + e_r58,
            "closure_ratio": (e_r44 + e_ucc + e_r57 + e_r58) / e_cap if e_cap else 0.0,
        },
        "ucc_average_w": e_ucc / t if t else 0.0,
        "q41_r44_average_w": e_r44 / t if t else 0.0,
        "samples": {
            "t_s": [s[0] for s in samples],
            "i_reg_a": [s[3] for s in samples],
            "v_reg_v": [s[2] for s in samples],
            "vdd_sr_v": [s[1] for s in samples],
        },
    }


def vdd_cut_delay_s(supply_v: float = VDD_IN_MAX_V) -> float:
    """Rev B bias-cut delay, evaluated at the same supply as the energy.

    The delay and the power must come from one operating point: a longer delay
    at a lower input voltage is not the same event as a shorter one at 15.75 V.
    T3 owns this number (``bias_cut_timing.cut_delay``); 13.36 us was Rev A's
    measured value with a 60 pF placeholder gate, which the real part loses to.
    """
    return bias_cut_timing.cut_delay(supply_v)["delay_to_13v5_s"]


def input_delay(delay_s: float | None = None, anchor_a: float = IREG_ANCHORS_A[
        "current_limit_95ma"], supply_v: float = VDD_IN_MAX_V) -> dict:
    """Energy delivered by the still-connected input before the cut lands."""
    if delay_s is None:
        delay_s = vdd_cut_delay_s(supply_v)
    v_reg = anchor_a * R_CROWBAR_TOTAL_OHM
    p_ucc = (supply_v - v_reg) * anchor_a + supply_v * IVDD_RUN_MAX_A
    p_r44 = anchor_a * anchor_a * R_CROWBAR_TOTAL_OHM
    return {
        "delay_s": delay_s,
        "supply_v": supply_v,
        "anchor_a": anchor_a,
        "v_reg_v": v_reg,
        "ucc_w": p_ucc,
        "q41_r44_w": p_r44,
        "ucc_j": p_ucc * delay_s,
        "q41_r44_j": p_r44 * delay_s,
        "cap_energy_untouched": True,
    }


def continuous_injection(vdd_sr: float, anchor_a: float, ambient_c: float = 25.0) -> dict:
    """Steady state: an external source holds VDD_SR up, REG crowbar stays on."""
    v_reg = anchor_a * R_CROWBAR_TOTAL_OHM
    p_ucc = (vdd_sr - v_reg) * anchor_a + vdd_sr * IVDD_RUN_MAX_A
    p_r44 = anchor_a * anchor_a * R_CROWBAR_TOTAL_OHM
    rise = p_ucc * reg_hold.RTH_JA_C_PER_W
    return {
        "vdd_sr_v": vdd_sr,
        "anchor_a": anchor_a,
        "v_reg_eq_v": v_reg,
        "ucc_w": p_ucc,
        "q41_r44_w": p_r44,
        "rise_k": rise,
        "tj_c": ambient_c + rise,
        "within_tj_max": ambient_c + rise <= reg_hold.TJ_MAX_C,
        "energy_unbounded": True,
    }


def repetition_limit_ms(energy_j: float, ambient_c: float = 25.0) -> float:
    """Shortest period that keeps the average UCC power at the steady bound.

    Uses reg_hold's steady-state allowed current as the average-power budget.
    It has no Zth(t), so this is an average-power equivalence, not a transient
    thermal proof.
    """
    allowed = reg_hold.allowed_current_a(reg_hold.VDD_NOM, R_CROWBAR_TOTAL_OHM, ambient_c)
    if allowed <= 0:
        return math.inf
    p_allowed = reg_hold.controller_power_w(allowed, R_CROWBAR_TOTAL_OHM, reg_hold.VDD_NOM)
    return energy_j / p_allowed * 1e3


def report() -> dict:
    finite = {name: finite_capacitor(anchor_a=a) for name, a in IREG_ANCHORS_A.items()}
    delay = {name: input_delay(anchor_a=a) for name, a in IREG_ANCHORS_A.items()}
    injection = {
        f"{V}_at_{name}": continuous_injection(V, a)
        for V in (BACKFEED_MILD_V, BACKFEED_V)
        for name, a in IREG_ANCHORS_A.items()
    }
    rep = {
        name: repetition_limit_ms(row["energy"]["ucc24624_j"])
        for name, row in finite.items()
    }
    worst_injection = injection[f"{BACKFEED_V}_at_current_limit_95ma"]
    best_injection = injection[f"{BACKFEED_V}_at_short_circuit_13ma"]
    return {
        "task": "T2_REG_HOLD_ENERGY_AND_BACKFEED",
        "evidence": "TIME_DOMAIN_ODE_ON_VENDORED_DATASHEET_ANCHORS",
        "measured": False,
        "hardware_qualified": False,
        "checks": {
            "finite_source_energy_is_bounded": all(
                row["energy"]["cap_released_j"] < 2e-3 for row in finite.values()),
            "finite_source_energy_split_is_consistent": all(
                0.95 < row["energy"]["closure_ratio"] < 1.05 for row in finite.values()),
            "input_delay_energy_is_smaller_than_cap_energy": all(
                delay[name]["ucc_j"] < finite[name]["energy"]["ucc24624_j"]
                for name in delay),
            "continuous_13ma_anchor_stays_below_tj": best_injection["within_tj_max"],
            "continuous_95ma_anchor_exceeds_tj": not worst_injection["within_tj_max"],
            "continuous_source_requires_circuit_change": True,
            "old_95ma_number_is_not_a_15v_guarantee": True,
            "cut_delay_is_the_t3_delay_at_the_same_supply": all(
                row["delay_s"] == vdd_cut_delay_s(row["supply_v"])
                for row in delay.values()),
        },
        "results": {
            "finite_capacitor": finite,
            "input_switch_delay": delay,
            "continuous_injection": injection,
            "repetition_limit_ms": rep,
            "summary": {
                "cap_energy_mj": finite["current_limit_95ma"]["energy"]["cap_released_j"] * 1e3,
                "hold_ms_95ma": finite["current_limit_95ma"]["hold_s"] * 1e3,
                "hold_ms_13ma": finite["short_circuit_13ma"]["hold_s"] * 1e3,
                "ucc_energy_mj": finite["current_limit_95ma"]["energy"]["ucc24624_j"] * 1e3,
                "cut_delay_us_15v75": vdd_cut_delay_s() * 1e6,
                "cut_delay_us_14v25": vdd_cut_delay_s(14.25) * 1e6,
                "rev_a_measured_cut_us": REV_A_MEASURED_CUT_S * 1e6,
                "delay_energy_uj_95ma": delay["current_limit_95ma"]["ucc_j"] * 1e6,
                "continuous_24v_13ma_w": best_injection["ucc_w"],
                "continuous_24v_95ma_w": worst_injection["ucc_w"],
                "continuous_24v_95ma_tj_c": worst_injection["tj_c"],
                "repetition_limit_ms_25c": rep["current_limit_95ma"],
            },
        },
        "decision": {
            "finite_source_conclusion": (
                "bounded: the 11.1 uF releases ~1.29 mJ, independent of the "
                "foldback anchor.  The UCC24624 absorbs 0.95-1.16 mJ of it; at the "
                "13 mA anchor R57 competes for more of the energy and shortens the "
                "hold.  The anchor sets the duration (1.3 ms at 95 mA, 6.8 ms at "
                "13 mA) and therefore the power.  A single event is energy-bounded, "
                "not thermally proven (no Zth(t) in the datasheet)."),
            "input_delay_conclusion": (
                "still negligible, but no longer quoted at Rev A's measured "
                f"{REV_A_MEASURED_CUT_S * 1e6:.2f} us: Rev B's cut is slower because "
                "the DMP3098L gate capacitance beats the 10x smaller R50.  The delay "
                "is now taken from ``bias_cut_timing.cut_delay`` at the same supply "
                f"the energy is evaluated at ({vdd_cut_delay_s() * 1e6:.1f} us at "
                f"{VDD_IN_MAX_V} V), giving ~"
                f"{delay['current_limit_95ma']['ucc_j'] * 1e6:.0f} uJ at the 95 mA "
                "anchor: still well below the capacitor energy, because the input "
                "current during that window is ~40 mA."),
            "cut_delay_source": (
                "T3 owns the number (tools/bias_cut_timing.py).  Rev A's 13.36 us "
                "was measured through a 60 pF placeholder gate; the real Ciss max "
                "is 1008 pF, and R50 shrank 100k -> 10k, so the delay grew.  Any "
                "report that still quotes 13.36 us for Rev B is quoting Rev A."),
            "continuous_source_conclusion": (
                "NOT closed and NOT closable by analysis.  At 24 V the 13 mA anchor "
                f"gives {best_injection['ucc_w']:.2f} W (Tj "
                f"{best_injection['tj_c']:.0f} C) but the 95 mA anchor gives "
                f"{worst_injection['ucc_w']:.2f} W (Tj {worst_injection['tj_c']:.0f} C); "
                "the datasheet does not specify the foldback curve, so neither is "
                "the answer."),
            "required_change": (
                "do not increase R57.  R57 only drains the local capacitor and "
                "cannot reduce a source that keeps injecting.  Either (a) measure "
                "IREG versus VREG at the board's own bias (row H4) and accept the "
                "measured operating point, or (b) remove the dependence on holding "
                "REG low: add a gate-source clamp on each SR FET driven by the 5 V "
                "latch domain so the gates are off regardless of REG."),
            "old_95ma_is_an_anchor": (
                "IREGLIM (95 mA) and IREGSC (13 mA) are specified at VVDD = 12 V.  "
                "The board runs 15 V and the 24 V backfeed is a third condition; "
                "neither current is a 15 V or 24 V guarantee."),
            "r57_is_not_a_fix_for_continuing_injection": (
                "R57 drains the local 11.1 uF and, at the 13 mA anchor, is already "
                "~7 mA of the discharge at 15 V, so it shortens the finite-source "
                "hold.  It cannot reduce a source that keeps VDD_SR up."),
        },
        "datasheet_anchors": {
            "file": reg_hold.DATASHEET,
            "ireglim_max_a": reg_hold.IREGLIM_MAX_A,
            "iregsc_max_a": reg_hold.IREG_SC_MAX_A,
            "ireg_condition": "VVDD = 12 V",
            "rth_ja_c_per_w": reg_hold.RTH_JA_C_PER_W,
            "tj_max_c": reg_hold.TJ_MAX_C,
            "vregdo_max_v": VREGDO_MAX_V,
            "vregoff_v": VREGOFF_MAX_V,
            "foldback_curve_specified": False,
        },
        "board": {
            "c_sr_f": C_SR_F,
            "r57_ohm": R57_OHM,
            "q54_rds_ohm": Q54_RDS_OHM,
            "r58_ohm": R58_OHM,
            "r_crowbar_total_ohm": R_CROWBAR_TOTAL_OHM,
        },
        "open": [
            "the regulator's IREG versus VREG curve between 8 V and 0 V",
            "IVDDRUN at VVDD = 15 V (datasheet max is the 12 V condition)",
            "IREGSC and IREGLIM at 15 V and at 24 V",
            "the die thermal impedance Zth(t): only a steady-state bound exists",
            "the actual source impedance and energy of the H5 external backfeed",
            "no hardware: every number is an ODE on datasheet anchors",
        ],
    }


def main() -> None:
    data = report()
    OUT.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(json.dumps(data["checks"], indent=2))
    print(json.dumps(data["results"]["summary"], indent=2))


if __name__ == "__main__":
    main()
