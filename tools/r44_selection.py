"""R44 procurement and conditional pulse screen; no hardware qualification."""
from pathlib import Path
import json
import math

ROOT = Path(__file__).resolve().parents[1]
MPN = "CRCW12064R70FKEAHP"
SOURCE = "references/datasheets/vishay_crcwhpe3_20260317.pdf"
P70_W = 0.75


def screen(*, r=4.7, v=11.9, c=2.3e-6, injection=0.095, rds=0.1, vdd=15.0):
    if r != 4.7:
        raise ValueError("R44 MPN is 4.7 ohm; a value change requires a new procurement selection")
    if min(v, c, vdd) <= 0 or min(injection, rds) < 0:
        raise ValueError("positive voltages/capacitance and nonnegative injection/Rds required")
    if injection * (r * 1.01 + rds) >= v:
        raise ValueError("discharge envelope requires equilibrium below initial REG voltage")
    evidence = json.loads((ROOT / "references/datasheets/r44_curve_evidence.json").read_text())
    rmin, rmax, cmax = r * .99, r * 1.01, c * 1.2
    duration = evidence["duration_s"]
    tau_max = (rmax + rds) * cmax
    peak = v * v / rmin
    tail_i = injection + v / rmin * math.exp(-duration / tau_max)
    tail_w = tail_i * tail_i * rmax
    rt = r + rds
    tau = rt * cmax
    amplitude = v / rt - injection

    def resistor_energy(t):
        # Exact integral of R*(Iinj + (V0/Rtotal-Iinj)*exp(-t/tau))**2.
        return r * (injection**2 * t
                    + 2 * injection * amplitude * tau * (-math.expm1(-t/tau))
                    + amplitude**2 * tau / 2 * (-math.expm1(-2*t/tau)))

    return {
        "mpn": MPN, "source": SOURCE, "source_evidence": evidence,
        "selection_status": "SELECTED_CONDITIONAL_SCREEN_ONLY", "qualified": False,
        "footprint": "Resistor_SMD:R_1206_3216Metric",
        "continuous_p70_w": P70_W,
        "continuous_rating_condition": "Rth <= 110 K/W; mounted PCB thermal resistance unverified",
        "land_comparison_mm": {"vendor_reflow_gap": 1.5, "vendor_pad_xy": [1.05, 1.8],
                               "stock_gap": 1.8, "stock_pad_xy": [1.125, 1.75],
                               "status": "compatible overlap, not identical to vendor land; assembly check open"},
        "assumptions": {"r_tolerance": .01, "c_upper_multiplier": 1.2,
                        "rds_ohm": rds, "injection_a": injection, "initial_reg_v": v,
                        "note": "C tolerance, Rds and constant injection are screening assumptions, not full-temperature guarantees"},
        "pulse_envelope": {"duration_s": duration, "peak_w": peak,
                           "curve_screen_w": evidence["conservative_screen_w"],
                           "margin": evidence["conservative_screen_w"] / peak,
                           "passes_assumed_envelope": peak < evidence["conservative_screen_w"],
                           "tau_max_s": tau_max, "tail_power_w": tail_w,
                           "not_energy_equivalent_width": True},
        "energy": {"capacitor_full_discharge_j": .5 * cmax * v*v,
                   "capacitor_r44_share_j_without_injection": .5*cmax*v*v*r/rt,
                   "r44_with_injection_j_by_hold_ms": {
                       str(ms): resistor_energy(ms / 1000) for ms in (10, 100, 1000)},
                   "integration_scope": "entire hold, not stopped at REG UVLO"},
        "hold_sensitivity": {"r44_dc_w": injection**2*r,
                             "reg_equilibrium_v": injection*rt,
                             "controller_regulator_w": max(vdd-injection*rt, 0)*injection,
                             "note": "95 mA is the VREG=8 V current-limit anchor; the "
                                     "VREG=0 short-circuit anchor and the allowed-current "
                                     "table are in tools/reg_hold.py; no indefinite "
                                     "crowbar approval"},
        "open_items": ["actual REG current and controller dissipation throughout latched fault",
                       "mounted thermal resistance, temperature derating and repetition profile",
                       "Q41 transient SOA and measured shutdown waveforms"],
    }
