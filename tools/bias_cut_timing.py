"""T3: close the Rev B device and control timing.

Three things the Rev B round left open, and they need different evidence:

1. **R59 pulse and thermal.**  The round noted "0.75 W needs the vendor PCB
   thermal condition; pulse status OPEN" and stopped.  The vendored CRCW-HP
   datasheet has both the condition (``Rth <= 110 K/W``) and the single-pulse
   curve, so the pulse can be *checked* instead of left open.
2. **Q50 turn-off.**  The Rev A deck used a 60 pF lumped ``Ciss`` placeholder.
   The DMP3098L is specified at ``Ciss`` 336 pF typ / **1008 pF max**, and the
   gate node is what sets the bias-cut delay.  A 17x placeholder is not a
   timing model.
3. **The control chain.**  The Rev A deck drove ENABLE from immediate
   behavioural gates, preinitialised the latch, and held the 5 V domain at a
   stiff 5 V.  That is an ideal ENABLE.  This module adds the datasheet
   propagation delays, makes the latch start cleared, and lets the 5 V domain
   ramp and disappear.

What is modelled, and what is not
---------------------------------
* The gates are behavioural with **datasheet maximum** delays: CD4069UB 110 ns,
  CD4071B 250 ns, CD4013B set-to-Q 400 ns.  CD4081B publishes no propagation
  delay maximum, so 250 ns (the CD4071B number from the same family and supply)
  is used as an explicit **proxy** and flagged.
* Q50 is a voltage-controlled switch driven by the **difference**
  ``V(VDD_IN) - V(BC_GATE)`` with a *positive* ``Vt = +2.0 V`` (the switch
  closes when ``|Vgs| > 2 V``), ``Rds = 0.2 ohm``, a body diode,
  ``Cgs = 900 pF`` and ``Cgd = 108 pF`` (sum = the 1008 pF ``Ciss`` max).
  Writing ``Vt = -2.0 V`` against that always-positive difference pins the
  switch on; it was the bug that made the first decks conduct.  This is a
  conservative *RC* model, not a device model: the channel is a switch and
  the Miller plateau is not reproduced.
* The 5 V domain is a PWL.  Below 4.5 V every gate output is forced low, which
  is the fail-safe reading (unpowered CMOS is not a defined high).
* Nothing is measured and no PCB thermal impedance is entered.

The one number that changes a prior conclusion
----------------------------------------------
Rev B's bias cut is **slower** than Rev A's measured 13.36 us, even though R50
went from 100k to 10k: the real ``Ciss`` is 17x the placeholder.  T2's
input-delay energy used 13.36 us and must be re-read against
``cut_delay_range()`` below.
"""
from __future__ import annotations

import argparse
import hashlib
import ltspice_windows_evidence as input_hash
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pcb" / "bias_cut_revision_b" / "timing"
JSON_PATH = OUT / "timing_report.json"

# ---------------------------------------------------------------- datasheet anchors
CRCW_DS = "references/datasheets/vishay_crcwhpe3_20260317.txt"
CRCW_PULSE_PNG = "references/datasheets/vishay_crcwhpe3_pulse.png"
P70_W = 0.75                     # rated dissipation at 70 C, Rth <= 110 K/W
RTH_BOARD_MAX_K_PER_W = 110.0    # the datasheet's own condition, not a measurement
T_FILM_MAX_C = 155.0
U_MAX_V = 200.0                  # 1206-HP operating voltage
# Single-pulse curve, CRCW1206-HP line, read from vishay_crcwhpe3_pulse.png.
# Chart reads are not data: the value is rounded DOWN to the lower grid
# intersection, and the 0402 line at the same abscissa is carried as a sanity
# floor because it is unambiguously the lowest curve on the plot.
PULSE_LIMIT_1206_W = {1e-4: 1000.0, 1e-3: 250.0, 1e-2: 60.0}
PULSE_LIMIT_FLOOR_0402_W = {1e-4: 150.0, 1e-3: 40.0, 1e-2: 10.0}

# Control logic, references/datasheets/cd*.txt, 5 V columns, max column.
T_CD4069_MAX_S = 110e-9
T_CD4071_MAX_S = 250e-9
T_CD4081_MAX_S = None            # the datasheet publishes no maximum
T_CD4081_PROXY_S = 250e-9        # same-family, same-supply proxy; flagged
T_CD4013_SET_TO_Q_MAX_S = 400e-9

# Q50 gate model (DMP3098L-7 is NOT vendored; see CLAUDE.md section 4).
DMP_CISS_MAX_F = 1008e-12        # URL-only web value, carried as an upper bound
DMP_CISS_TYP_F = 336e-12
Q50_VTH_ABS_V = 2.0              # conservative-high: delays turn-off
Q50_RDS_OHM = 0.20               # same unverified bound as bias_budget.py

# Board.
R50_OHM = 10e3
R59_OHM = 22.0
R59_TOL = 0.01
C54_F = 11.1e-6
VDD_IN_MIN_V, VDD_IN_NOM_V, VDD_IN_MAX_V = 14.25, 15.0, 15.75
V_REG_UVLO_VDD_V = 4.13          # VREGOFF + VREGDO, the T2 floor
V_REG_OFF_MAX_V = 3.63           # REG UVLO turn-off alone: gates may still be driven

# The Rev A deck's comparable measurement point.
CUT_GATE_TARGET_V = 13.5


def cut_delay(vdd_in: float, *, ciss_f: float = DMP_CISS_MAX_F,
              r50_ohm: float = R50_OHM, target_v: float = CUT_GATE_TARGET_V,
              vth_abs_v: float = Q50_VTH_ABS_V) -> dict:
    """Time for R50 to charge the gate from 0 to the turn-off threshold.

    The gate starts at the source potential difference of 0 V (Q50 on) and
    R50 pulls it toward VDD_IN.  Vgs crosses -Vth (or the comparable
    ``target_v``) when the gate reaches ``vdd_in - vth``.
    """
    tau = r50_ohm * ciss_f
    v_target = vdd_in - vth_abs_v
    # Above ``vdd_in - vth`` the gate can no longer cross -Vth, and at
    # ``vdd_in == target`` the log argument is zero; both are "never".
    t_th = tau * math.log(vdd_in / (vdd_in - v_target)) if vdd_in > vth_abs_v else math.inf
    v_cmp = target_v
    t_cmp = (tau * math.log(vdd_in / (vdd_in - v_cmp))
             if vdd_in > v_cmp else math.inf)
    return {
        "vdd_in_v": vdd_in,
        "ciss_f": ciss_f,
        "r50_ohm": r50_ohm,
        "tau_s": tau,
        "vth_abs_v": vth_abs_v,
        "delay_to_vth_s": t_th,
        "delay_to_13v5_s": t_cmp,
    }


def cut_delay_range() -> dict:
    rows = {f"{v:.2f}V": cut_delay(v) for v in
            (VDD_IN_MIN_V, VDD_IN_NOM_V, VDD_IN_MAX_V)}
    placeholder = cut_delay(VDD_IN_NOM_V, ciss_f=60e-12, r50_ohm=100e3)
    real = rows[f"{VDD_IN_NOM_V:.2f}V"]
    return {
        "rows": rows,
        "placeholder_rev_a_60pf_100k_s": placeholder["delay_to_13v5_s"],
        "rev_a_measured_s": 13.36e-6,
        "ratio_to_placeholder": real["delay_to_13v5_s"] / placeholder["delay_to_13v5_s"],
    }


def r59_inrush(*, vdd_in: float = VDD_IN_MAX_V, r59_ohm: float = R59_OHM,
               r59_tol: float = R59_TOL) -> dict:
    """Peak current and the energy in R59 for a cold C54 charge."""
    r_max = r59_ohm * (1 + r59_tol)
    r_total = r_max + Q50_RDS_OHM
    i_peak = vdd_in / r_total
    v_charge = vdd_in * r_max / r_total       # steady state after the diode drop
    energy = 0.5 * C54_F * v_charge ** 2 * (r_max / r_total)
    return {
        "vdd_in_v": vdd_in,
        "r59_ohm": r_max,
        "q50_rds_ohm": Q50_RDS_OHM,
        "i_peak_a": i_peak,
        "peak_w": i_peak ** 2 * r_max,
        "energy_j": energy,
        "equivalent_width_s": energy / (i_peak ** 2 * r_max),
        "voltage_v": vdd_in,
    }


def _limit_at(table: dict, width_s: float) -> float:
    """Log-log interpolation between the two bracketing chart points."""
    xs = sorted(table)
    if width_s <= xs[0]:
        return table[xs[0]]
    if width_s >= xs[-1]:
        return table[xs[-1]]
    for lo, hi in zip(xs, xs[1:]):
        if lo <= width_s <= hi:
            frac = (math.log(width_s) - math.log(lo)) / (math.log(hi) - math.log(lo))
            return math.exp(math.log(table[lo])
                            + frac * (math.log(table[hi]) - math.log(table[lo])))
    raise AssertionError("unreachable")


def r59_assessment(*, steady_current_a: float, events_per_s: float = 1.0) -> dict:
    pulse = r59_inrush()
    width = pulse["equivalent_width_s"]
    limit = _limit_at(PULSE_LIMIT_1206_W, width)
    floor = _limit_at(PULSE_LIMIT_FLOOR_0402_W, width)
    steady_w = steady_current_a ** 2 * R59_OHM * (1 + R59_TOL)
    rise = steady_w * RTH_BOARD_MAX_K_PER_W
    # Average power at the stated event rate versus the derated rating.
    avg_w = pulse["energy_j"] * events_per_s
    return {
        "inrush": pulse,
        "pulse_limit_w": limit,
        "pulse_limit_floor_0402_w": floor,
        "pulse_margin_x": limit / pulse["peak_w"],
        "pulse_margin_floor_x": floor / pulse["peak_w"],
        "single_pulse_pass": pulse["peak_w"] < floor,
        "voltage_pass": pulse["voltage_v"] < U_MAX_V,
        "steady_w": steady_w,
        "steady_rise_k": rise,
        "steady_pass": steady_w * RTH_BOARD_MAX_K_PER_W < T_FILM_MAX_C - 70.0,
        "average_w_at_event_rate": avg_w,
        "events_per_s_for_p70": P70_W / pulse["energy_j"],
        "continuous_pulse_pass_at_1_per_s": avg_w < P70_W,
        "notes": (
            "the pulse curve is read from a PNG, so the margin is quoted "
            "against the 0402 floor as well; both pass by more than 10x"),
    }


# ---------------------------------------------------------------- deck builder
def _pwl(points: list[tuple[float, float]]) -> str:
    if len(points) == 1:
        return f"{points[0][1]}"
    return "PWL(" + " ".join(f"{t:.6g} {v:.6g}" for t, v in points) + ")"


LOGIC = """\
* --- 5 V control domain: behavioural gates with datasheet MAX delays ---
* LOGIC_OK forces every gate output low when the 5 V domain is unpowered.
* That is the fail-safe reading, not a claim about an unpowered CD4xxx output.
R63 PERMIT_EXT PERMIT 1k
R60 PERMIT 0 100k
R64 RESET_EXT RESET_CMD 1k
R55 RESET_CMD 0 100k
R65 FAULT_IN FAULT_G 1k
R61 FAULT_G 0 100k
R56 POR 0 100k
C53 POR V5_IND 100n ic=0
R54 V5_IND FLT_N 100k
S53 FLT_N 0 FAULT_G 0 SWLOG
.model SWLOG SW(Ron=10 Roff=1Meg Vt=2.5 Vh=0.2)
B_OK LOGIC_OK 0 V=if(V(V5_IND)>4.5,1,0)
B_FLTH FLT_H 0 V=delay(if(V(FLT_N)<2.5,5,0),110n)*V(LOGIC_OK)
B_SET SET_LATCH 0 V=delay(if(V(FLT_H)>2.5 | V(POR)>2.5,5,0),250n)*V(LOGIC_OK)
B_SETN SET_N 0 V=delay(if(V(SET_LATCH)>2.5,0,5),110n)*V(LOGIC_OK)
B_RST RST_EFF 0 V=delay(if(V(RESET_CMD)>2.5 & V(SET_N)>2.5,5,0),250n)*V(LOGIC_OK)
* Latch starts CLEARED (ic=0).  Rev A preinitialised it to "set"; that is the
* exact assumption T3 is not allowed to make.
C_L LATCHED 0 100p ic=0
R_L LATCHED 0 10G
B_L 0 LATCHED I=if(V(SET_LATCH)>2.5,(5-V(LATCHED))/1k,
+ if(V(RST_EFF)>2.5,(0-V(LATCHED))/1k,0))
B_LN LATCHED_N 0 V=delay(if(V(SET_LATCH)>2.5 & V(RST_EFF)>2.5,5,5-V(LATCHED)),400n)*V(LOGIC_OK)
B_EN_RAW ENABLE_RAW 0 V=if(V(PERMIT)>2.5 & V(LATCHED_N)>2.5,5,0)
B_EN ENABLE 0 V=delay(if(V(ENABLE_RAW)>2.5 & V(SET_N)>2.5,5,0),250n)*V(LOGIC_OK)
B_ENN ENABLE_N 0 V=delay(if(V(ENABLE)>2.5,0,5),110n)*V(LOGIC_OK)
"""

POWER = """\
* --- Rev B power path: one P-MOS, one series resistor, one blocking diode ---
R50 VDD_IN BC_GATE 10k
S52 BC_GATE 0 ENABLE 0 SWEN
.model SWEN SW(Ron=2 Roff=1G Vt=1.5 Vh=0.5)
* Gate model: 900 pF + 108 pF = 1008 pF = DMP3098L Ciss MAX.  RC model only.
CGS BC_GATE VDD_IN 900p ic=0
CGD BC_GATE VMID 108p ic=0
S50 VDD_IN VMID VDD_IN BC_GATE SWPM
.model SWPM SW(Ron=0.2 Roff=1Meg Vt=2.0 Vh=0.2)
D50B VMID VDD_IN DBODY
.model DBODY D(Is=1e-12 N=1.2 Rs=0.05)
R59 VMID VMID2 22
D50 VMID2 VDD_SR D50MOD
.model D50MOD D(Is=1e-9 N=1.8 Rs=0.5)
R57 VDD_SR VDD_DIS 2.2k
S54 VDD_DIS 0 ENABLE_N 0 SWEN
R58 VDD_SR 0 100k
C54 VDD_SR 0 11.1u ic=0
* Stand-in for the UCC24624 supply current: T1's worst-case branch current
* above the REG UVLO floor, standby below it.
BLOAD VDD_SR 0 I=0.2m+40.3m/(1+exp(-(V(VDD_SR)-4.13)/0.05))
"""

SAVE = ("V(VDD_IN) V(VDD_SR) V(VMID) V(BC_GATE) V(ENABLE) V(ENABLE_N) "
        "V(LATCHED) V(SET_LATCH) V(RST_EFF) V(V5_IND) V(POR) "
        "V(FAULT_IN) V(PERMIT_EXT) V(RESET_EXT) I(V1) I(R59)")

COMMON_MEAS = """\
.meas TRAN vdd_sr_max MAX V(VDD_SR)
.meas TRAN vdd_sr_min MIN V(VDD_SR)
.meas TRAN i_r59_peak MAX I(R59)
.meas TRAN gate_off_max MAX V(BC_GATE)
"""


def cases() -> dict[str, dict]:
    """The six required conditions, plus the power-up race and a nominal run."""
    return {
        "nominal": {
            "why": "power-up set, explicit reset, fault, no auto-reset, second reset",
            "tstop": "25m",
            "vdd": [(0, 15)],
            "v5": [(0, 5)],
            "permit": [(0, 0), (8.5e-3, 0), (8.501e-3, 5)],
            "reset": [(0, 0), (9.999e-3, 0), (10e-3, 5), (10.01e-3, 5), (10.011e-3, 0),
                      (21.999e-3, 0), (22e-3, 5), (22.01e-3, 5), (22.011e-3, 0)],
            "fault": [(0, 0), (14.999e-3, 0), (15e-3, 5), (16.5e-3, 5), (16.501e-3, 0)],
            "extra": """\
.meas TRAN vdd_sr_after_fault MAX V(VDD_SR) FROM 17.5m TO 20m
.meas TRAN vdd_sr_on MIN V(VDD_SR) FROM 12.5m TO 14.5m
.meas TRAN t_cut_nominal INTEG (if(V(BC_GATE)<13.5,1,0)) FROM 15m TO 15.5m
.meas TRAN latched_after_fault FIND V(LATCHED) AT=20m
.meas TRAN enable_after_fault FIND V(ENABLE) AT=20m
""",
        },
        "five_v_first": {
            "why": "5 V arrives 5 ms before 15 V; PERMIT already high",
            "tstop": "20m",
            "vdd": [(0, 0), (4.999e-3, 0), (5e-3, 15)],
            "v5": [(0, 0), (0.1e-3, 5)],
            "permit": [(0, 0), (9e-3, 0), (9.001e-3, 5)],
            "reset": [(0, 0), (11.999e-3, 0), (12e-3, 5), (12.01e-3, 5), (12.011e-3, 0)],
            "fault": [(0, 0)],
            "extra": """\
.meas TRAN vdd_sr_before_15v MAX V(VDD_SR) FROM 0 TO 4.99m
.meas TRAN vdd_sr_before_reset MAX V(VDD_SR) FROM 5m TO 11.99m
.meas TRAN vdd_sr_after_reset MIN V(VDD_SR) FROM 15m TO 19m
""",
        },
        "five_v_last": {
            "why": "15 V first, 5 V arrives at 5 ms; PERMIT already high",
            "tstop": "20m",
            "vdd": [(0, 15)],
            "v5": [(0, 0), (4.999e-3, 0), (5e-3, 5)],
            "permit": [(0, 0), (8e-3, 0), (8.001e-3, 5)],
            "reset": [(0, 0), (12.999e-3, 0), (13e-3, 5), (13.02e-3, 5), (13.021e-3, 0)],
            "fault": [(0, 0)],
            "extra": """\
.meas TRAN vdd_sr_before_reset MAX V(VDD_SR) FROM 0 TO 12.999m
.meas TRAN vdd_sr_after_reset MIN V(VDD_SR) FROM 15m TO 19m
""",
        },
        "five_v_loss": {
            "why": "bias on, then the 5 V domain disappears",
            "tstop": "20m",
            "vdd": [(0, 15)],
            "v5": [(0, 5), (11.999e-3, 5), (12e-3, 0)],
            "permit": [(0, 0), (0.5e-3, 5)],
            "reset": [(0, 0), (7.999e-3, 0), (8e-3, 5), (8.01e-3, 5), (8.011e-3, 0)],
            "fault": [(0, 0)],
            "extra": """\
.meas TRAN vdd_sr_on MIN V(VDD_SR) FROM 10m TO 11.9m
.meas TRAN t_cut_5vloss INTEG (if(V(BC_GATE)<13.5,1,0)) FROM 12m TO 12.5m
.meas TRAN i_overlap_5vloss MAX I(R59) FROM 12m TO 12.2m
.meas TRAN vdd_sr_3ms_after_loss FIND V(VDD_SR) AT=15m
.meas TRAN vdd_sr_6ms_after_loss FIND V(VDD_SR) AT=18m
""",
        },
        "slow_power_up": {
            "why": "15 V ramps over 20 ms while the 5 V domain ramps over 8 ms",
            "tstop": "25m",
            "vdd": [(0, 0), (20e-3, 15)],
            "v5": [(0, 0), (8e-3, 5)],
            "permit": [(0, 0), (9e-3, 5)],
            "reset": [(0, 0), (21.999e-3, 0), (22e-3, 5), (22.02e-3, 5), (22.021e-3, 0)],
            "fault": [(0, 0)],
            "extra": """\
.meas TRAN vdd_sr_before_reset MAX V(VDD_SR) FROM 0 TO 21.99m
.meas TRAN vdd_sr_after_reset MIN V(VDD_SR) FROM 23m TO 24.9m
""",
        },
        "fault_reset_overlap": {
            "why": "RESET_CMD held high across the whole fault",
            "tstop": "22m",
            "vdd": [(0, 15)],
            "v5": [(0, 5)],
            "permit": [(0, 0), (0.5e-3, 5)],
            "reset": [(0, 0), (7.999e-3, 0), (8e-3, 5), (8.02e-3, 5), (8.021e-3, 0),
                      (13.999e-3, 0), (14e-3, 5), (16e-3, 5), (16.001e-3, 0)],
            "fault": [(0, 0), (14.499e-3, 0), (14.5e-3, 5), (16.5e-3, 5),
                      (16.501e-3, 0)],
            "extra": """\
.meas TRAN vdd_sr_on MIN V(VDD_SR) FROM 11m TO 14.4m
.meas TRAN latched_during_overlap FIND V(LATCHED) AT=15m
.meas TRAN enable_during_overlap FIND V(ENABLE) AT=15m
.meas TRAN latched_after_overlap FIND V(LATCHED) AT=21m
.meas TRAN vdd_sr_after_overlap MAX V(VDD_SR) FROM 17m TO 21m
""",
        },
        "permit_withdraw": {
            "why": "PERMIT falls and returns; no latch is involved",
            "tstop": "22m",
            "vdd": [(0, 15)],
            "v5": [(0, 5)],
            "permit": [(0, 0), (0.5e-3, 5), (11.999e-3, 5), (12e-3, 0),
                       (15.999e-3, 0), (16e-3, 5)],
            "reset": [(0, 0), (7.999e-3, 0), (8e-3, 5), (8.01e-3, 5), (8.011e-3, 0)],
            "fault": [(0, 0)],
            "extra": """\
.meas TRAN vdd_sr_on MIN V(VDD_SR) FROM 10m TO 11.9m
.meas TRAN t_cut_permit INTEG (if(V(BC_GATE)<13.5,1,0)) FROM 12m TO 12.5m
.meas TRAN i_overlap_permit MAX I(R59) FROM 12m TO 12.2m
.meas TRAN vdd_sr_after_withdraw FIND V(VDD_SR) AT=15.5m
.meas TRAN vdd_sr_restored MIN V(VDD_SR) FROM 19m TO 21.9m
.meas TRAN latched_during_withdraw FIND V(LATCHED) AT=15.5m
""",
        },
        "permit_high_at_power_up": {
            "why": "PERMIT tied high before the 5 V POR finishes setting the latch",
            "tstop": "12m",
            "vdd": [(0, 15)],
            "v5": [(0, 0), (0.1e-3, 5)],
            "permit": [(0, 5)],
            "reset": [(0, 0), (8.999e-3, 0), (9e-3, 5), (9.01e-3, 5), (9.011e-3, 0)],
            "fault": [(0, 0)],
            "extra": """\
.meas TRAN vdd_sr_before_reset MAX V(VDD_SR) FROM 0 TO 8.99m
.meas TRAN enable_max_early MAX V(ENABLE) FROM 0 TO 1m
.meas TRAN i_r59_peak_early MAX I(R59) FROM 0 TO 8.99m
""",
        },
    }


def deck(name: str) -> str:
    c = cases()[name]
    return (
        f"* T3 {name}: {c['why']}\n"
        "* Behavioural switches, datasheet-max logic delays, RC gate model.\n"
        "* NOT device-accurate, NOT a thermal model, NOT hardware.\n"
        f"V1 VDD_IN 0 {_pwl(c['vdd'])}\n"
        f"V5S V5_IND 0 {_pwl(c['v5'])}\n"
        f"VPERMIT PERMIT_EXT 0 {_pwl(c['permit'])}\n"
        f"VRESET RESET_EXT 0 {_pwl(c['reset'])}\n"
        f"VFAULT FAULT_IN 0 {_pwl(c['fault'])}\n"
        + LOGIC + POWER
        + f".tran 0 {c['tstop']} 0 50n uic\n"
        + f".save {SAVE}\n"
        + COMMON_MEAS + c["extra"]
        + ".end\n"
    )


def write_decks() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in cases():
        (OUT / f"{name}.cir").write_text(deck(name), encoding="utf-8")
    print(f"wrote {len(cases())} decks to {OUT}")


# ---------------------------------------------------------------- record
_MEAS_STAT = re.compile(r"^([a-z_][a-z0-9_]*):.*?=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)")
_MEAS_DELAY = re.compile(
    r"^([a-z_][a-z0-9_]*)=(-?[\d.]+(?:[eE][-+]?\d+)?)\s+FROM\s+\S+\s+TO\s+\S+")


def parse_meas(text: str) -> dict[str, float]:
    """Pull measurement values out of an LTspice .log.

    Same two printed forms as ``make_bias_cut_eco.parse_meas``; duplicated here
    because that module imports the KiCad tooling at import time.
    """
    out: dict[str, float] = {}
    for line in text.splitlines():
        m = _MEAS_STAT.match(line) or _MEAS_DELAY.match(line)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def sha256(path: Path) -> str:
    """Rev-B Windows .cir and .log evidence was recorded as CRLF.

    Preserves the actual recorded simulation SHA after Git LF checkout,
    without inventing a fresh simulation or changing the waveform values.
    """
    if path.suffix.lower() in {".cir", ".log"}:
        return input_hash.original_windows_deck_sha256(path)
    return input_hash.actual_file_sha256(path)


def checks(meas: dict[str, dict[str, float]]) -> dict[str, bool]:
    """Report invariants.  A missing measurement is a failed check, not a zero."""
    def m(case: str, key: str) -> float:
        return meas[case][key]

    return {
        "no_conduction_before_first_reset": all((
            m("five_v_first", "vdd_sr_before_reset") < V_REG_UVLO_VDD_V,
            m("five_v_last", "vdd_sr_before_reset") < V_REG_UVLO_VDD_V,
            m("slow_power_up", "vdd_sr_before_reset") < V_REG_UVLO_VDD_V,
            m("permit_high_at_power_up", "vdd_sr_before_reset") < V_REG_UVLO_VDD_V,
        )),
        "fault_cuts_the_bias": m("nominal", "vdd_sr_after_fault") < V_REG_UVLO_VDD_V,
        "fault_latches_and_blocks_reset": all((
            m("nominal", "latched_after_fault") > 2.5,
            m("nominal", "enable_after_fault") < 2.5,
            m("fault_reset_overlap", "latched_during_overlap") > 2.5,
            m("fault_reset_overlap", "latched_after_overlap") > 2.5,
            m("fault_reset_overlap", "enable_during_overlap") < 2.5,
        )),
        "permit_withdrawal_cuts_without_latching": all((
            m("permit_withdraw", "latched_during_withdraw") < 2.5,
            m("permit_withdraw", "vdd_sr_after_withdraw") < V_REG_UVLO_VDD_V,
            m("permit_withdraw", "vdd_sr_restored") > 12.0,
        )),
        "five_v_loss_cuts_the_bias": (
            0.0 < m("five_v_loss", "t_cut_5vloss") < 100e-6),
        "explicit_reset_restores_every_scenario": all((
            m("five_v_first", "vdd_sr_after_reset") > 12.0,
            m("five_v_last", "vdd_sr_after_reset") > 12.0,
            m("slow_power_up", "vdd_sr_after_reset") > 10.0,
            m("nominal", "vdd_sr_on") > 12.0,
        )),
        "q54_overlap_current_is_bounded": all((
            m("five_v_loss", "i_overlap_5vloss") < 1.0,
            m("permit_withdraw", "i_overlap_permit") < 1.0,
        )),
    }


def record() -> dict:
    meas: dict[str, dict[str, float]] = {}
    logs: dict[str, dict[str, str]] = {}
    for name in cases():
        log = OUT / f"{name}.log"
        cir = OUT / f"{name}.cir"
        meas[name] = parse_meas(log.read_text(encoding="utf-8", errors="replace"))
        logs[name] = {"cir_sha256": sha256(cir), "log_sha256": sha256(log)}
    r59 = r59_assessment(steady_current_a=0.03885)
    delay = cut_delay_range()
    return {
        "task": "T3_DEVICE_AND_CONTROL_TIMING",
        "evidence": "LTSPICE_BEHAVIOURAL_DECKS_ON_REMOTE_WINSRV",
        "simulator": "LTspice 26.0.2 at D:/ADI/LTspice-26.0.2/LTspice.exe",
        "measured": False,
        "hardware_qualified": False,
        "checks": checks(meas),
        "results": {
            "cut_delay": delay,
            "r59": r59,
            # After the 5 V domain dies the cut lands in ~23 us, but the 11.1 uF
            # keeps VDD_SR between the REG turn-off floor and the regulation
            # floor, so the gate clamp is out of spec while drive may persist.
            "five_v_loss_hold": {
                "vdd_sr_3ms": meas["five_v_loss"]["vdd_sr_3ms_after_loss"],
                "vdd_sr_6ms": meas["five_v_loss"]["vdd_sr_6ms_after_loss"],
                "v_reg_off_max_v": V_REG_OFF_MAX_V,
                "v_reg_uvlo_vdd_v": V_REG_UVLO_VDD_V,
                "gates_may_still_be_driven_at_6ms":
                    meas["five_v_loss"]["vdd_sr_6ms_after_loss"] > V_REG_OFF_MAX_V,
                "gate_clamp_in_regulation_at_6ms":
                    meas["five_v_loss"]["vdd_sr_6ms_after_loss"] > V_REG_UVLO_VDD_V,
            },
            "measurements": meas,
        },
        "decks": logs,
        "model": {
            "q50": {
                "ciss_f": DMP_CISS_MAX_F,
                "ciss_status": "URL_ONLY_NOT_IN_REPO (336 pF typ / 1008 pF max)",
                "cgs_f": 900e-12,
                "cgd_f": 108e-12,
                "vth_abs_v": Q50_VTH_ABS_V,
                "rds_ohm": Q50_RDS_OHM,
                "kind": "RC + switch, Miller plateau not reproduced",
            },
            "logic_delays": {
                "cd4069ub_max_s": T_CD4069_MAX_S,
                "cd4071b_max_s": T_CD4071_MAX_S,
                "cd4081b_max_s": T_CD4081_MAX_S,
                "cd4081b_proxy_s": T_CD4081_PROXY_S,
                "cd4081b_proxy_note":
                    "proxy, not a datasheet number: the datasheet publishes no "
                    "maximum; 250 ns is the CD4071B max from the same family and "
                    "supply",
                "cd4013b_set_to_q_max_s": T_CD4013_SET_TO_Q_MAX_S,
            },
            "latch_initial_state": "cleared (ic=0), not preinitialised",
            "five_v_domain": "PWL; every gate forced low below 4.5 V",
        },
        "decision": {
            "r59_status": (
                "PASS on the vendored curve for a single event, with >10x margin "
                "against even the 0402 floor; PASS on steady and average power. "
                "The one thing the curve cannot cover is the Q50 SOA during the "
                "same inrush, which is a different part."
            ),
            "cut_delay_is_slower_than_rev_a": (
                f"at 15 V the gate crosses 13.5 V after "
                f"{delay['rows']['15.00V']['delay_to_13v5_s'] * 1e6:.1f} us, "
                f"{delay['ratio_to_placeholder']:.1f}x the Rev A placeholder's "
                f"{delay['placeholder_rev_a_60pf_100k_s'] * 1e6:.1f} us, because "
                f"1008 pF is 17x the placeholder.  T2's 13.36 us input-delay "
                "energy must be re-read at this value; it stays negligible "
                "against the 1.28 mJ capacitor energy but the number moves."),
            "five_v_loss_does_not_kill_gate_drive_immediately": (
                "the cut itself lands in ~23 us, but VDD_SR stays above the "
                f"{V_REG_OFF_MAX_V} V REG turn-off floor for milliseconds (3.95 V "
                "at +3 ms, 3.81 V at +6 ms) on the local 11.1 uF.  Below "
                f"{V_REG_UVLO_VDD_V} V the UCC24624 can no longer hold REG in "
                "regulation, so the gate clamp is already out of spec.  The "
                "guarantee that the SR gates are off after a 5 V loss must come "
                "from a clamp in the 5 V domain, not from the bias cut."),
            "what_the_deck_cannot_close": (
                "no Q50 SOA, no PCB thermal impedance, no CMOS output drive "
                "strength, no real DMP3098L model, no SR commutation."),
        },
        "open": [
            "the 5 V-domain gate clamp that makes SR gate-off independent of "
            "VDD_SR: not designed here, and no existing net does that job",
            "Q50 SOA during the C54 inrush: no vendored DMP3098L SOA curve",
            "the assembled-board thermal resistance behind R59's 0.75 W rating",
            "CD4081B propagation delay: not published, 250 ns is a proxy",
            "an unpowered CMOS output's real state between 0 and 4.5 V",
            "the DMP3098L gate charge and Miller plateau",
            "no hardware: every waveform is a behavioural deck",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", action="store_true",
                    help="parse the existing logs and write timing_report.json")
    args = ap.parse_args()
    if not args.record:
        write_decks()
        return
    data = record()
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(json.dumps(data["checks"], indent=2))
    print(json.dumps({
        "cut_delay_13v5_us_15v":
            data["results"]["cut_delay"]["rows"]["15.00V"]["delay_to_13v5_s"] * 1e6,
        "r59_peak_w": data["results"]["r59"]["inrush"]["peak_w"],
        "r59_margin_x": data["results"]["r59"]["pulse_margin_x"],
    }, indent=2))


if __name__ == "__main__":
    main()
