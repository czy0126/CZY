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


def height_stack(glue_m: float, label_m: float, clamp_m: float = 0.0,
                 glue_max_m: float | None = None,
                 label_max_m: float | None = None) -> dict[str, float]:
    """Core + glue + label + optional clamp, measured above the PCB top.

    Nominal uses the nominal core height; worst case uses the datasheet maximum
    core height and the *maximum* glue/label thickness, not their nominals.
    """
    g_max = glue_m if glue_max_m is None else glue_max_m
    l_max = label_m if label_max_m is None else label_max_m
    nominal = float(CORE["height_nominal_m"]) + glue_m + label_m + clamp_m
    worst = float(CORE["height_max_m"]) + g_max + l_max + clamp_m
    return {"nominal_m": nominal, "worst_case_m": worst, "margin_m": 10e-3 - worst}


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
            "flat_no_pocket": height_stack(0.05e-3, 0.05e-3, 0.0,
                                          glue_max_m=0.08e-3, label_max_m=0.06e-3),
            "pocket_0.5mm_no_clamp": height_stack(0.05e-3, 0.05e-3, -0.5e-3,
                                                 glue_max_m=0.08e-3, label_max_m=0.06e-3),
            "with_0.5mm_clamp": height_stack(0.05e-3, 0.05e-3, 0.5e-3,
                                            glue_max_m=0.08e-3, label_max_m=0.06e-3),
        },
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
