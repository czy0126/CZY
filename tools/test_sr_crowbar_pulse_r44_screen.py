"""P0 review: replacing the Q41 MOSFET changes the R44 pulse stress.

This is a model-only bounding screen for the *candidate*, not a component
pulse-SOA qualification. The legacy report uses a hypothetical 1.5-ohm
crowbar and therefore understates the potential resistor peak power when
Q41 is replaced with an AO3400A. Actual FET Rds depends on gate drive and
temperature; the REG source may continue supplying current during a trip.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_sr_fault_board as b  # noqa: E402


def test_ao3400a_candidate_increases_r44_peak_vs_legacy_model():
    q41 = next(p for p in b.parts() if p.ref == "Q41")
    r44 = next(p for p in b.parts() if p.ref == "R44")
    assert q41.mpn == "AO3400A"
    assert "0.5W" in r44.value
    # AOS OEM max Rds(on)=48mOhm @ Vgs=2.5V, Id=3A, 25C.
    # This is a conditioned illustrative case, NOT temperature max or SOA.
    candidate_rds_ohm = 0.048
    peak_r44_w = b.VREG_TYP**2 * b.R_CROWBAR / (
        b.R_CROWBAR + candidate_rds_ohm)**2
    legacy_r44_w = b.crowbar_pulse()["r44_peak_power_w"]
    assert 25.0 < peak_r44_w < 26.0
    assert peak_r44_w > 1.65 * legacy_r44_w


def test_near_zero_fet_resistance_is_a_larger_resistor_pulse_envelope():
    # Higher VREG alone may raise R44 peak power above 30W before including
    # capacitor tolerances and any regulator recharging current.
    upper_scenario_peak_w = b.VREG_MAX**2 / b.R_CROWBAR
    assert upper_scenario_peak_w > 30.0
    c_reg_f = b.C_REG_BYPASS + b.C_REG_HF
    released_j = 0.5 * c_reg_f * (
        b.VREG_TYP**2 - b.VREGOFF_MIN**2)
    candidate_r44_energy_j = released_j * b.R_CROWBAR / (
        b.R_CROWBAR + 0.048)
    assert 0.12e-3 < candidate_r44_energy_j < 0.13e-3
    # The old 1.5-ohm scenario is still useful but cannot certify this part.
    assert candidate_r44_energy_j > b.crowbar_pulse()["r44_energy_j"]


def test_candidate_is_not_a_resistor_pulse_rating_or_fab_authorization():
    report = json.loads((b.OUT / "sr_fault_validation.json").read_text("utf-8"))
    assert report["hardware_built"] is False
    assert report["fabrication_approved"] is False
    pulse = report["crowbar_pulse"]
    assert pulse["r44_pulse_rating_j"] is None
    assert pulse["q41_thermal"] is None
    assert "UNVERIFIED" in pulse["temperature_note"]
