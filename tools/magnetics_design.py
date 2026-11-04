"""Reproducible magnetics budget for the 48 V -> ~2 V fixed-ratio DCX.

Datasheet inputs: TDK EILP32 N97, B66287G0000X197 (ELP 32/6/20) plus
B66287K0000X197 (I 32/3/20).  The dimensions below are read from the TDK
datasheet (October 2022, page 4), not guessed:

    31.75 +/- 0.65 mm x 25.4 +/- 0.5 mm overall,
    ELP half 6.35 +/- 0.15 mm, I plate 3.15 +/- 0.15 mm,
    window height 3.2 +/- 0.15 mm, centre leg 20.35 +/- 0.4 mm,
    Ae = 130 mm^2, Amin = 128 mm^2, le = 35.1 mm, Ve = 4560 mm^3,
    ungapped AL = 6300 nH +/- 25 %, N97 Bsat = 310 mT at 100 degC.

The operating point comes from the round-4 1 ms deck
(sim/v2/sr_tank_dual_v33_ss_1ms.raw).  These are design estimates; they are not
measurements and not a sign-off.

Usage:
    python tools/magnetics_design.py --json design/v3/magnetics/magnetics_design.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

MU0 = 4e-7 * math.pi
RHO_CU_100C = 2.227e-8      # ohm m, 1.72e-8 at 20 degC with alpha 3.93e-3/K
ALPHA_CU = 3.93e-3

DESIGN = Path(__file__).resolve().parent.parent / "design" / "v3"

# The four non-core terms of the Z stack.  They are assumptions, not datasheet
# values: this repository holds no adhesive or label specification, the clamp
# is a design choice (five bare cores cannot float), and the 0.5 mm pocket has
# not been cleared with a fabricator.  The maximum glue/label thickness is what
# the worst case must use -- the same trap ``main_board_mechanical.py`` avoids.
GLUE_M, GLUE_MAX_M = 0.05e-3, 0.08e-3
LABEL_M, LABEL_MAX_M = 0.05e-3, 0.06e-3
CLAMP_M = 0.5e-3
POCKET_M = 0.5e-3

CORE: dict[str, float | str] = {
    "name": "TDK EILP32 N97 B66287G0000X197 + B66287K0000X197",
    "Ae_m2": 130e-6,
    "Amin_m2": 128e-6,
    "le_m": 35.1e-3,
    "Ve_m3": 4560e-9,
    "AL_ungapped_nH": 6300.0,
    "height_nominal_m": 9.50e-3,
    "height_max_m": 9.80e-3,
    "window_height_m": 3.2e-3,
    "window_tol_m": 0.15e-3,
    "outer_length_m": 31.75e-3,
    "centre_leg_width_m": 20.35e-3,
    "core_depth_m": 25.4e-3,
    "Bsat_T": 0.310,
    "PV_ref_W_per_set": 2.2,      # 200 mT, 100 kHz, 100 degC
    "B_ref_T": 0.200,
    "f_ref_Hz": 100e3,
}

# 95 A model point (1 ms deck, RL = 20 mohm).  Kept as the reference for the
# regression tests; the 100 A point below is what the hardware target uses.
OP: dict[str, float] = {
    "f_Hz": 200.626e3,
    "Ipri_rms_A": 8.5971,
    "Ipri_pk_A": 13.1229,
    "Isec_rms_A": 18.1182,        # RMS of one secondary half (one SR device)
    "Isec_pair_rms_A": 26.84127,  # RMS of the pair output current (a + b)
    "Iout_A": 94.9317,
    "Vout_V": 1.8919845,
    "Pout_W": 178.9869,
    "Pin_W": 189.7903,
    "P_sr_branch_W": 6.6582,
    "P_other_nonmag_W": 2.4949,   # primary switch + Cr, after removing model Cu
    "P_model_primary_cu_W": 0.8869,
    "P_model_secondary_cu_W": 0.3939,
    "P_model_lr_W": 0.3696,
}

# 100 A model point measured from sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw
# (RL = 18.9 mohm, 22 complete periods, saved window rebased to 0..120 us).
# Ipri/Isec RMS are measured, not scaled: the tank waveform form factor rises
# with load, so an I^2 rescale of the 95 A values is 4-5 % optimistic.
OP_100: dict[str, float] = {
    "f_Hz": 200.6222387725369e3,
    "Ipri_rms_A": 9.45014,
    "Ipri_pk_A": 13.88142,
    "Isec_rms_A": 19.92219,
    "Isec_pair_rms_A": 28.17835,
    "Iout_A": 99.82464,          # avg(V(out)) / RL, RL = 18.9 mohm
    "Vout_V": 1.886686,
    "Pout_W": 188.345331,        # average(V(out)^2 / RL)
    "RL_ohm": 0.0189,
    "window_us": 7.704687,
    "window_us_end": 117.363517,
    "periods": 22.0,
}
OP_100["P_model_lr_W"] = OP["P_model_lr_W"] * (OP_100["Ipri_rms_A"] / OP["Ipri_rms_A"]) ** 2
OP_100["P_other_nonmag_W"] = OP["P_other_nonmag_W"] * (OP_100["Ipri_rms_A"] / OP["Ipri_rms_A"]) ** 2
OP_100["P_sr_branch_W"] = OP["P_sr_branch_W"] * (OP_100["Isec_pair_rms_A"] / OP["Isec_pair_rms_A"]) ** 2

# Output-referred equivalent resistance implied by the measured 100 A point:
# (ideal 2.000 V - 1.886686 V) / 99.82464 A.
R_OUT_EQUIV_OHM = (48.0 / 24.0 - OP_100["Vout_V"]) / OP_100["Iout_A"]


def core_gap_m(inductance_h: float, turns: int, ae_m2: float, al_ungapped_nh: float) -> float:
    """Total gap (m) that turns the ungapped AL into the target inductance."""
    l_ungapped = al_ungapped_nh * 1e-9 * turns * turns
    if inductance_h >= l_ungapped:
        return 0.0
    reluctance_gap = 1.0 / inductance_h - 1.0 / l_ungapped
    return MU0 * turns * turns * ae_m2 * reluctance_gap


def flux_density(v_pri: float, t_on: float, turns: int, ae_m2: float) -> tuple[float, float]:
    """Return (Delta B, B_peak) for a symmetric square-wave drive."""
    delta_b = v_pri * t_on / (turns * ae_m2)
    return delta_b, delta_b / 2.0


def dowell_fr(thickness_m: float, frequency_hz: float, layers: int) -> float:
    """Dowell AC/DC resistance ratio for a foil winding with `layers` layers."""
    delta = math.sqrt(RHO_CU_100C / (math.pi * frequency_hz * MU0))
    ratio = thickness_m / delta
    if ratio < 1e-4:
        return 1.0
    first = ratio * (math.sinh(2.0 * ratio) + math.sin(2.0 * ratio))
    first /= math.cosh(2.0 * ratio) - math.cos(2.0 * ratio)
    second = 0.0
    if layers > 1:
        second = (2.0 / 3.0) * (layers * layers - 1.0) * ratio
        second *= (math.sinh(ratio) - math.sin(ratio)) / (math.cosh(ratio) + math.cos(ratio))
    return first + second


def foil_resistance(length_m: float, width_m: float, thickness_m: float,
                    frequency_hz: float, layers: int) -> float:
    """AC resistance of one foil; divide by N yourself for N parallel foils."""
    r_dc = RHO_CU_100C * length_m / (width_m * thickness_m)
    return r_dc * dowell_fr(thickness_m, frequency_hz, layers)


def core_loss_bound_w_per_set(b_pk_t: float, frequency_hz: float) -> float:
    """Conservative B^2 f^2 upper bound anchored to the N97 datasheet point."""
    p_ref = float(CORE["PV_ref_W_per_set"])
    b_ratio = b_pk_t / float(CORE["B_ref_T"])
    f_ratio = frequency_hz / float(CORE["f_ref_Hz"])
    return p_ref * b_ratio * b_ratio * f_ratio * f_ratio


def winding_stack() -> tuple[list[tuple[str, float]], float]:
    """Interleaved foil stack P1 / S_A / P2 / S_B / P3, bottom to top."""
    layers = [
        ("P1 0.1 mm Cu", 0.1e-3),
        ("Kapton 0.05 mm", 0.05e-3),
        ("S_A 2 x 0.1 mm Cu", 0.2e-3),
        ("Kapton 0.10 mm", 0.10e-3),
        ("P2 0.1 mm Cu", 0.1e-3),
        ("Kapton 0.10 mm", 0.10e-3),
        ("S_B 2 x 0.1 mm Cu", 0.2e-3),
        ("Kapton 0.05 mm", 0.05e-3),
        ("P3 0.1 mm Cu", 0.1e-3),
        ("Outer tape 0.10 mm", 0.10e-3),
    ]
    return layers, sum(thickness for _, thickness in layers)


def transformer_copper_loss(op: dict[str, float] | None = None) -> dict[str, float]:
    """Copper loss of four transformers from a measured operating point."""
    point = OP if op is None else op
    f = point["f_Hz"]
    # Primary: three 3-turn foils in series, 60 mm mean turn, 18 mm wide.
    r_pri_unit = foil_resistance(3 * 0.060, 0.018, 0.1e-3, f, 3)
    p_pri = 4.0 * point["Ipri_rms_A"] ** 2 * r_pri_unit
    # Secondary: each half is two 0.1 mm foils in parallel; 1 turn, 60 mm.
    r_sec_half = foil_resistance(0.060, 0.018, 0.1e-3, f, 2) / 2.0
    p_sec = 8.0 * point["Isec_rms_A"] ** 2 * r_sec_half
    return {
        "primary_unit_ohm": r_pri_unit,
        "secondary_half_ohm": r_sec_half,
        "primary_w": p_pri,
        "secondary_w": p_sec,
        "total_w": p_pri + p_sec,
    }


def _load(rel: str) -> dict:
    return json.loads((DESIGN / rel).read_text(encoding="utf-8"))


def height_stack(glue_m: float, label_m: float, clamp_m: float = 0.0,
                 glue_max_m: float | None = None,
                 label_max_m: float | None = None,
                 core: dict | None = None,
                 limit_m: float = 10e-3) -> dict[str, float]:
    """Core + glue + label + optional clamp, measured above the PCB top.

    Nominal uses the nominal core height; worst case uses the datasheet maximum
    core height and the *maximum* glue/label thickness, not their nominals.

    ``core`` defaults to the EILP32 set this package designs around; passing a
    different ``{"height_nominal_m", "height_max_m"}`` pair re-runs the *same*
    arithmetic for another catalogue set rather than forking the formula.
    ``limit_m`` is the total the stack is measured against -- 10 mm for D3,
    16 mm for D1/D2 -- because a margin against the wrong target is a number
    that looks like an answer.
    """
    c = CORE if core is None else core
    g_max = glue_m if glue_max_m is None else glue_max_m
    l_max = label_m if label_max_m is None else label_max_m
    nominal = float(c["height_nominal_m"]) + glue_m + label_m + clamp_m
    worst = float(c["height_max_m"]) + g_max + l_max + clamp_m
    return {"nominal_m": nominal, "worst_case_m": worst, "margin_m": limit_m - worst}


def catalogue_core_stack() -> dict[str, object]:
    """The Z budget for every core set in the TDK planar catalogue extract.

    ``magnetics_design.json`` answers the Z question for the one core it
    designs (EILP32) against one target (10 mm).  The staged policy adopted on
    2026-11-04 moves D1/D2 to 16 mm and keeps 10 mm as the D3 stretch, and the
    ELP38 route was screened on **bare core height only** -- that screen states
    its remainder is "not a full stack".  This table closes the gap by running
    the same glue/label/clamp/pocket terms through :func:`height_stack` for
    every catalogue set, so the comparison is like for like across cores and
    across the two height targets.

    What it is still not: a stack.  Winding construction, pocket feasibility,
    TIM, cold plate, fastener heads and board bow are absent, so the number it
    prints is the *budget left for them*, not a height anyone can build to.
    ``d1_staged_target_screen.json`` already says the same about its 3.65 mm;
    this only removes the terms that were already modelled.
    """
    src = _load("power_priority/lr_tdk_catalog_core_source.json")
    policy = _load("power_priority/d1_staged_target_policy.json")
    staged = _load("power_priority/d1_staged_target_screen.json")
    screened = _load("power_priority/lr_tdk_catalog_core_screen.json")
    limits = {s["id"]: s.get("height_limit_mm") for s in policy["stages"]}
    d1_mm = float(limits["D1_100A"])
    d3_mm = float(limits["D3_THIN"])
    d1, d3 = d1_mm * 1e-3, d3_mm * 1e-3
    reserve = float(staged["temporary_noncore_package_reserve_mm"])
    bare_rows = {r["id"]: r for r in screened["cores"]}
    screen_rows = {r["core_id"]: r for r in staged["elp_core_candidates"]}

    rows = []
    for c in src["cores"]:
        nom = c["core_height_nom_mm"] + c["plate_height_nom_mm"]
        worst = nom + c["core_height_tolerance_mm"] + c["plate_height_tolerance_mm"]
        geom = {"height_nominal_m": nom * 1e-3, "height_max_m": worst * 1e-3}
        flat = height_stack(GLUE_M, LABEL_M, 0.0, GLUE_MAX_M, LABEL_MAX_M,
                            core=geom, limit_m=d1)
        clamped = height_stack(GLUE_M, LABEL_M, CLAMP_M, GLUE_MAX_M, LABEL_MAX_M,
                               core=geom, limit_m=d1)
        pocketed = height_stack(GLUE_M, LABEL_M, CLAMP_M - POCKET_M,
                                GLUE_MAX_M, LABEL_MAX_M, core=geom, limit_m=d1)
        thin = height_stack(GLUE_M, LABEL_M, 0.0, GLUE_MAX_M, LABEL_MAX_M,
                            core=geom, limit_m=d3)
        bare = bare_rows[c["id"]]
        # Two independent computations of the same bare height must agree: this
        # catalogue extract, and the screen already published from it.
        if abs(worst - bare["core_plus_plate_height_max_mm"]) > 1e-6:
            raise SystemExit(
                f"{c['id']}: catalogue gives {worst} mm bare height but "
                f"lr_tdk_catalog_core_screen.json says "
                f"{bare['core_plus_plate_height_max_mm']} -- one of the two is stale")
        if c["id"] not in screen_rows:
            raise SystemExit(f"{c['id']} is missing from d1_staged_target_screen.json")
        residual = pocketed["margin_m"] * 1e3
        rows.append({
            "id": c["id"], "core": c["core"], "plate": c["plate"],
            "material": c["material"], "tdk_ordering_prefix": c["tdk_ordering_prefix"],
            "Amin_mm2": c["amin_mm2"], "Ae_mm2": c["ae_mm2"],
            "core_pack_nominal_mm": round(nom, 3),
            "core_pack_worst_mm": round(worst, 3),
            "stack_flat_no_clamp_worst_mm": round(flat["worst_case_m"] * 1e3, 3),
            "stack_clamped_worst_mm": round(clamped["worst_case_m"] * 1e3, 3),
            "stack_clamped_pocketed_worst_mm": round(pocketed["worst_case_m"] * 1e3, 3),
            "d1_budget_left_for_tim_cold_plate_fasteners_mm": round(residual, 3),
            "d1_clears_the_non_core_reserve": residual >= reserve - 1e-9,
            "d3_10mm_flat_margin_mm": round(thin["margin_m"] * 1e3, 3),
            "d3_10mm_flat_fits": thin["margin_m"] >= -1e-12,
            "three_turn_fault_flux_t": bare["flux_model_3turn_t"],
            "three_turn_area_screen_pass": bare["three_turn_area_pass"],
            "disposition_as_previously_screened": bare["disposition"],
        })

    # The catalogue's ELP32 (6.35 +- 0.15 half core, 3.15 +- 0.15 plate) must
    # land exactly on the datasheet-derived constant this module designs to.
    elp32 = next(r for r in rows if r["id"] == "ELP32_I32")
    if abs(elp32["core_pack_worst_mm"] - float(CORE["height_max_m"]) * 1e3) > 1e-6:
        raise SystemExit(
            f"catalogue ELP32 bare height {elp32['core_pack_worst_mm']} mm disagrees "
            f"with CORE['height_max_m'] {float(CORE['height_max_m']) * 1e3} mm")

    passing = [r["id"] for r in rows if r["d1_clears_the_non_core_reserve"]]
    optimistic = [
        r["id"] for r in rows
        if screen_rows[r["id"]]["planning_noncore_allowance_2mm_screen_pass"]
        and not r["d1_clears_the_non_core_reserve"]
    ]
    elp38 = next(r for r in rows if r["id"] == "ELP38_I38")
    both = [r["id"] for r in rows
            if r["d1_clears_the_non_core_reserve"] and r["three_turn_area_screen_pass"]]
    return {
        "kind": "STAGED_Z_BUDGET_FOR_EVERY_CATALOGUE_CORE_SET",
        "source": "power_priority/lr_tdk_catalog_core_source.json",
        "limits_mm": {"D1_100A_and_D2_120A": d1_mm, "D3_THIN": d3_mm},
        "non_core_terms": {
            "glue_mm": [round(GLUE_M * 1e3, 3), round(GLUE_MAX_M * 1e3, 3)],
            "label_mm": [round(LABEL_M * 1e3, 3), round(LABEL_MAX_M * 1e3, 3)],
            "clamp_mm": round(CLAMP_M * 1e3, 3),
            "pocket_mm": round(POCKET_M * 1e3, 3),
            "evidence": "ASSUMED/DESIGN -- no adhesive, label, clamp or pocket "
                        "specification exists in this repository",
        },
        "non_core_reserve_mm": reserve,
        "cores": rows,
        "cores_clearing_the_16mm_reserve": passing,
        "screens_the_bare_core_test_passed_but_the_full_stack_does_not": optimistic,
        "finding": (
            f"ELP38 is {elp38['core_pack_worst_mm']:.2f} mm bare (core + I plate, worst "
            f"case); the known stack adds {elp38['stack_clamped_pocketed_worst_mm'] - elp38['core_pack_worst_mm']:.2f} mm "
            f"of glue, label, clamp and pocket, leaving "
            f"{elp38['d1_budget_left_for_tim_cold_plate_fasteners_mm']:.2f} mm of the "
            f"{d1_mm:.0f} mm D1 budget for TIM, cold plate and fastener heads -- "
            f"{elp38['d1_budget_left_for_tim_cold_plate_fasteners_mm'] - reserve:.2f} mm "
            f"beyond the {reserve:.0f} mm policy reserve. "
            + (f"{', '.join(optimistic)} passed the bare-core reserve test but fails it "
               f"once glue and label are counted. " if optimistic else
               "No core set changes side when the non-core terms are added: every set "
               "the bare-core screen passed still clears the reserve. ")
            + f"ELP32 is the only set that fits D3's {d3_mm:.0f} mm flat "
            f"(by {elp32['d3_10mm_flat_margin_mm']:.2f} mm) and it loses that margin the "
            f"moment a clamp is added. "
            f"Height is not the only screen: of the sets that clear the reserve, only "
            f"{', '.join(both) or 'none'} also passes the three-turn area screen at the "
            f"RFQ fault current, so the D1 core choice is still a trade between a core "
            f"that fits and a core that does not saturate -- not a settled answer."
        ),
        "unknowns": [
            "胶、标签、压块的规格与公差（本仓库没有规格书，全部是假设）",
            "0.5 mm 沉槽能否由板厂实现、以及沉槽下 1.1 mm FR-4 的绝缘与回流铜",
            "ELP38 的窗口高度与绕组构造（目录摘录没有窗口尺寸，平面绕组是否放得下未验证）",
            "TIM 厚度与压缩量、冷板离板高度、紧固件头部凸出、板弯",
            "100 degC 的实际 L(I)：面积/磁通筛选用的是 L*I/(N*Amin) 近似，不是厂家 L(I) 曲线",
        ],
        "gate": "NOT_A_STACK：这是已知项的预算，不是可制造高度。D1 的任何高度声明"
                "都必须等厂家给出完整装配高度与 100 degC L(I) 之后才能成立。",
    }


def output_estimate(vin_v: float, iout_a: float,
                    r_out_ohm: float | None = None) -> dict[str, float]:
    """Fixed 24:1 output estimate using the model's output-referred resistance."""
    r = R_OUT_EQUIV_OHM if r_out_ohm is None else r_out_ohm
    v_ideal = vin_v / 24.0
    vout = v_ideal - iout_a * r
    return {
        "vin_v": vin_v,
        "v_ideal_v": v_ideal,
        "vout_v": vout,
        "pout_w": vout * iout_a,
    }


def required_vin_for_pout(iout_a: float, pout_w: float,
                          r_out_ohm: float | None = None) -> float:
    """Input voltage needed to reach pout_w at iout_a with the model's drop."""
    r = R_OUT_EQUIV_OHM if r_out_ohm is None else r_out_ohm
    vout = pout_w / iout_a
    return 24.0 * (vout + iout_a * r)


def loss_budget(op: dict[str, float], aux_w: float = 0.75,
                output_path_ohm: float = 0.15e-3) -> dict[str, float]:
    """Whole-machine estimate for one measured operating point.

    The model Pout is measured across its load resistor.  `output_path_ohm`
    is the extra busbar/connector/sense resistance that the model does not
    contain, so it is added as a loss and subtracted from the load-side Pout.
    """
    cu = transformer_copper_loss(op)
    p_mag = cu["total_w"]
    t_on = 1.0 / (2.0 * op["f_Hz"])
    # Half-bridge square wave: +/- VIN/2 across the series primary string of
    # four units, so each unit sees VIN/8.
    _, b_pk = flux_density(50.0 / 8.0, t_on, 3, float(CORE["Ae_m2"]))
    p_core = 4.0 * core_loss_bound_w_per_set(b_pk, op["f_Hz"])
    p_lr = op["P_model_lr_W"]
    p_sr = op["P_sr_branch_W"]
    p_other = op["P_other_nonmag_W"]
    p_path = op["Iout_A"] * op["Iout_A"] * output_path_ohm
    p_loss_converter = p_mag + p_core + p_lr + p_sr + p_other + aux_w
    p_loss_system = p_loss_converter + p_path
    pout_conv = op["Pout_W"]
    pout_load = pout_conv - p_path
    return {
        "iout_a": op["Iout_A"],
        "pout_at_converter_w": pout_conv,
        "pout_at_load_w": pout_load,
        "p_magnetic_copper_w": p_mag,
        "p_core_w": p_core,
        "p_lr_w": p_lr,
        "p_sr_w": p_sr,
        "p_other_model_w": p_other,
        "p_output_path_w": p_path,
        "p_aux_w": aux_w,
        "total_loss_w": p_loss_system,
        "converter_loss_w": p_loss_converter,
        "efficiency_at_converter_pct": 100.0 * pout_conv / (pout_conv + p_loss_converter),
        "efficiency_pct": 100.0 * pout_load / (pout_load + p_loss_system),
    }


def design_report() -> dict[str, object]:
    """Collect every number quoted by the magnetic package."""
    f = OP["f_Hz"]
    t_on = 1.0 / (2.0 * f)
    b48 = flux_density(48.0 / 8.0, t_on, 3, float(CORE["Ae_m2"]))
    b50 = flux_density(50.0 / 8.0, t_on, 3, float(CORE["Ae_m2"]))
    b46 = flux_density(46.0 / 8.0, t_on, 3, float(CORE["Ae_m2"]))
    gap = core_gap_m(10e-6, 3, float(CORE["Ae_m2"]), float(CORE["AL_ungapped_nH"]))
    cu = transformer_copper_loss()
    layers, stack = winding_stack()
    return {
        "core": CORE,
        "operating_point_95a": OP,
        "operating_point_100a": OP_100,
        "gap_m": gap,
        "gap_mm": gap * 1e3,
        "flux": {
            "48v_delta_b_t": b48[0], "48v_b_pk_t": b48[1],
            "50v_b_pk_t": b50[1], "46v_b_pk_t": b46[1],
        },
        "core_loss_w_per_set_50v": core_loss_bound_w_per_set(b50[1], f),
        "core_loss_w_total_50v": 4.0 * core_loss_bound_w_per_set(b50[1], f),
        "copper_95a": cu,
        "copper_100a": transformer_copper_loss(OP_100),
        "winding_stack": [{"layer": name, "thickness_mm": t * 1e3} for name, t in layers],
        "winding_stack_mm": stack * 1e3,
        "window_height_mm": float(CORE["window_height_m"]) * 1e3,
        "window_width_mm": (float(CORE["outer_length_m"]) - float(CORE["centre_leg_width_m"])) / 2 * 1e3,
        "copper_width_max_mm": float(CORE["core_depth_m"]) * 1e3 - 2 * 1.5,
        "height": {
            "flat_no_pocket": height_stack(GLUE_M, LABEL_M, 0.0,
                                          glue_max_m=GLUE_MAX_M, label_max_m=LABEL_MAX_M),
            "pocket_0.5mm_no_clamp": height_stack(GLUE_M, LABEL_M, -POCKET_M,
                                                 glue_max_m=GLUE_MAX_M, label_max_m=LABEL_MAX_M),
            "with_0.5mm_clamp": height_stack(GLUE_M, LABEL_M, CLAMP_M,
                                            glue_max_m=GLUE_MAX_M, label_max_m=LABEL_MAX_M),
        },
        "catalogue_core_stack": catalogue_core_stack(),
        "loss_at_95a": loss_budget(OP),
        "loss_at_100a": loss_budget(OP_100),
        "output_100a": {
            "46v": output_estimate(46.0, 100.0),
            "48v": output_estimate(48.0, 100.0),
            "50v": output_estimate(50.0, 100.0),
            "vin_for_200w": required_vin_for_pout(100.0, 200.0),
        },
        "r_out_equiv_ohm": R_OUT_EQUIV_OHM,
        "notes": [
            "Design estimates, not measurements; currents come from the model bench.",
            "100 A RMS currents are measured on the 18.9 mohm deck, not scaled by I^2.",
            "Core loss is a B^2 f^2 bound anchored to the N97 200 mT/100 kHz/100 degC point.",
            "Dowell F_R is a 1-D foil estimate; fringing flux at the 0.121 mm gap is not modelled.",
            "The 18 mm copper width is a choice inside the 22.4 mm mechanical maximum.",
            "200 W at 100 A needs ~50.7 V input with the measured 1.135 mohm output drop.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    report = design_report()
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json is None:
        print(text)
    else:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
