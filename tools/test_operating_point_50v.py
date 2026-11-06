"""The 50 V / 110 A and 50 V / 120 A probe runs: what must not drift.

The raws are ~0.4 GB each and stay out of git, so the JSON records *are* the
evidence.  Nothing here re-runs LTspice.  Four separate failure modes are
pinned:

  * reporting the load-resistor *target* (110 A / 120 A) as a result;
  * quoting ``vout_avg**2 / RL`` (which is ~7 ppm low) as Pout;
  * reading ``V(ovl1)`` as the over-current pin, or missing that the real pin
    ``V(oc)`` already sits at 63-68 % of the 1 V trip;
  * collapsing the three closure boundaries into one line, or flipping
    ``NOT_CLOSED`` because one boundary happens to look smaller.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import steady_stress

ROOT = Path(__file__).resolve().parent.parent
PP = ROOT / "design/v3/power_priority"
MOTHER = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.cir"

CASES = {
    "50v_110a": {
        "op": PP / "operating_point_50v_110a.json",
        "stress": PP / "stress_50v_110a.json",
        "ledger": PP / "energy_ledger_50v_110a.json",
        "audit": PP / "sr_loss_audit_50v_110a.json",
        "cr": PP / "cr_stress_50v_110a.json",
        "deck": ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110_cin.cir",
        "rl": 0.0178,
        "iout": 109.64316998910512,
    },
    "50v_120a": {
        "op": PP / "operating_point_50v_120a.json",
        "stress": PP / "stress_50v_120a.json",
        "ledger": PP / "energy_ledger_50v_120a.json",
        "audit": PP / "sr_loss_audit_50v_120a.json",
        "cr": PP / "cr_stress_50v_120a.json",
        "deck": ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.cir",
        "rl": 0.0163,
        "iout": 119.26811423161129,
    },
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", CASES)
def test_the_record_carries_the_measured_current_not_the_target(key: str):
    case = CASES[key]
    d = load(case["op"])
    assert d["rl_ohm"] == pytest.approx(case["rl"])
    assert d["iout_from_v_a"] == pytest.approx(case["iout"])
    # 17.8 mOhm was picked for 110 A from a 1.8586 V linear estimate; 50 V lifts
    # Vout, so the measured current lands *below* the target.  Either direction
    # is allowed, but a record that says exactly 110.0 / 120.0 A is fabricated.
    target = 110.0 if key.endswith("110a") else 120.0
    assert abs(d["iout_from_v_a"] - target) > 0.1
    assert d["iout_from_v_a"] != pytest.approx(target, abs=1e-6)


@pytest.mark.parametrize("key", CASES)
def test_output_power_is_the_true_mean_of_the_square(key: str):
    d = load(CASES[key]["op"])
    assert d["iout_from_v_a"] == pytest.approx(d["vout_avg_v"] / d["rl_ohm"], rel=1e-9)
    assert d["pout_w"] == pytest.approx(d["vout_rms_v"] ** 2 / d["rl_ohm"], rel=1e-6)
    # Using the mean voltage would understate the load power; the true value is
    # strictly larger, and the gap is small enough to hide in a printed table.
    wrong = d["vout_avg_v"] ** 2 / d["rl_ohm"]
    assert d["pout_w"] > wrong
    assert d["pout_w"] - wrong < 0.05


@pytest.mark.parametrize("key", CASES)
def test_the_oc_pin_is_below_the_trip_and_above_zero(key: str):
    s = load(CASES[key]["stress"])
    oc = s["oc"]
    assert 0.0 < oc["max_v"] < oc["trip_level_v"] == pytest.approx(1.0)
    assert oc["latch_level_v"] == pytest.approx(2.0)
    assert oc["margin_to_trip"] == pytest.approx(oc["max_v"] / oc["trip_level_v"])
    # 120 A is the tighter case; if this ever exceeds the trip the deck's OC
    # comparator would fire and the whole operating point is invalid.
    assert oc["max_v"] < 0.8


@pytest.mark.parametrize("key", CASES)
def test_the_cout_ripple_states_how_it_was_obtained(key: str):
    """These two decks save I(Cout); the 100 A deck does not.

    ``Cout`` is one lumped element in the model, so the saved trace *is* the whole
    bank current and the pair-2/3 symmetry assumption drops out of the number.
    The four-SR ×2 reconstruction stays published beside it because the current
    peaks still rest on that assumption -- it reads 1.1-1.2 % high, which is the
    price of the ×2 and not a second measurement.
    """
    c = load(CASES[key]["stress"])["cout_ripple"]
    assert c["ripple_rms_a"] > 0.0
    assert c["ripple_pk_a"] >= c["ripple_rms_a"]
    assert c["reconstruction"] in {steady_stress.MEASURED_COUT,
                                   steady_stress.RECONSTRUCTED_FROM_SR}
    if c["reconstruction"] == steady_stress.MEASURED_COUT:
        # KCL: in steady state the capacitor carries no DC, so its own mean is
        # the check that the probe is on the bank and not on a load branch.
        assert abs(c["cap_mean_a"]) < 0.005 * c["load_mean_a"]
        # The reconstruction is biased high by the ×2, never low; a few percent
        # is the whole expected gap, so a sign error still fails here.
        ratio = c["ripple_rms_reconstructed_a"] / c["ripple_rms_a"]
        assert 1.0 < ratio < 1.03
        assert c["ripple_pk_reconstructed_a"] > c["ripple_pk_a"]
    # ``mean_check_pct`` belongs to the reconstruction branch (the one the current
    # peaks still use): it only carries the four SR currents, so a large error
    # means the sign or the ×2 is wrong, not that the capacitor behaves differently.
    assert abs(c["mean_check_pct"]) < 0.5


def test_the_higher_load_raises_every_stress_column():
    lo = load(CASES["50v_110a"]["op"])
    hi = load(CASES["50v_120a"]["op"])
    # Ripple is deliberately absent: it fell from 45.41 to 41.04 mVpp when the
    # load rose, so it is not monotonic in load and must not be used as one.
    for key in ("iout_from_v_a", "pout_w", "ipri_rms_a", "ipri_pk_a"):
        assert hi[key] > lo[key], key
    for case in (lo, hi):
        assert case["vout_pp_mv"] < 50.0  # the project's self-chosen target
    for pool in ("pair1", "pair4"):
        for key in ("iout_a", "irms_pair_a", "ifwd_pk_a", "irev_pk_a"):
            assert hi[pool][key] > lo[pool][key], f"{pool}.{key}"
    for key in ("ripple_rms_a", "ripple_pk_a"):
        assert (load(CASES["50v_120a"]["stress"])["cout_ripple"][key]
                > load(CASES["50v_110a"]["stress"])["cout_ripple"][key])


@pytest.mark.parametrize("key", CASES)
def test_the_closure_is_reported_as_not_closed_at_every_boundary(key: str):
    ledger = load(CASES[key]["ledger"])
    balance = ledger["balance"]
    assert ledger["port"]["vin_v"] == pytest.approx(50.0)
    assert ledger["diagnostic_integrity"]["status"] == "RECOMPUTED_WITH_REQUESTED_VIN_RL"
    assert balance["closure_status"] == "NOT_CLOSED"
    assert balance["target_w"] == pytest.approx(0.2)  # the target is never moved

    closure = load(CASES[key]["audit"])["cases"][0]["closure"]
    assert closure["matches_published"] is True
    boundaries = {
        "ledger single": closure["rebuilt_single_w"],
        "ledger period-averaged": closure["rebuilt_period_averaged_w"],
        "deck-adjusted single": closure["deck_adjusted_single_w"],
        "deck-adjusted period-averaged": closure["deck_adjusted_period_averaged_w"],
        "after gate drive single": closure["after_gate_drive_single_w"],
        "after gate drive period-averaged": closure["after_gate_drive_period_averaged_w"],
    }
    for name, value in boundaries.items():
        assert abs(value) > 0.2, f"{name} appears inside the budget: {value}"
    assert closure["inside_budget_single"] is False
    assert closure["inside_budget_period_averaged"] is False
    # The deck runs Cout 7.05 mF and LR_TOTAL 1 uH; the tool integrates the
    # mother-deck 4 mF / 0.92 uH.  The correction must actually be applied.
    storage = load(CASES[key]["audit"])["cases"][0]["storage_parameters"]
    assert storage["cout_f_deck"] == pytest.approx(7.05e-3)
    assert storage["lr_h_deck"] == pytest.approx(1e-6)
    assert storage["delta_closure_single_w"] != 0.0


def test_the_loss_residuals_are_not_the_same_story():
    """110 A's element list closes; 120 A's does not.  Reporting only one lies."""
    a = load(CASES["50v_110a"]["ledger"])
    b = load(CASES["50v_120a"]["ledger"])
    assert a["results"]["loss_residual_within_0p2_w"] is True
    assert abs(a["balance"]["loss_residual_w"]) < 0.2
    assert b["results"]["loss_residual_within_0p2_w"] is False
    assert abs(b["balance"]["loss_residual_w"]) > 0.2
    assert b["balance"]["closure_residual_w"] > a["balance"]["closure_residual_w"]


@pytest.mark.parametrize("key", CASES)
def test_the_cr_swing_is_reconstructed_from_the_current_integral(key: str):
    cr = load(CASES[key]["cr"])
    assert cr["v_dc_v"] == pytest.approx(25.0, abs=0.1)  # mean(v_Cr) = VIN/2
    assert cr["rating_margin"] == pytest.approx(cr["v_rated_v"] / cr["v_max_v"])
    assert cr["rating_margin"] > 2.0
    assert cr["v_pp_v"] == pytest.approx(cr["v_max_v"] - cr["v_min_v"])


def test_the_fifty_volt_decks_are_the_mother_deck_plus_vin_and_rl():
    """Only the header, the VIN/RL values and the .save block may differ.

    If a 50 V deck ever picks up a different Cour, tank or gate network, the
    operating point would silently describe another circuit.
    """
    mother = _body(MOTHER.read_text(encoding="utf-8"))
    for key, case in CASES.items():
        deck = _body(case["deck"].read_text(encoding="utf-8"))
        assert deck == mother, key
        text = case["deck"].read_text(encoding="utf-8")
        assert f"VIN=50 RL={case['rl'] * 1e3:g}m" in text, key
        assert "UNRUN, NOT HARDWARE RATED" in text


def test_the_run_records_keep_the_deck_parameter_that_was_run():
    for key, case in CASES.items():
        ledger = load(case["ledger"])
        assert ledger["port"]["rl_ohm"] == pytest.approx(case["rl"])
        assert ledger["raw"]["variables"] == 80  # the _cin save block
        assert ledger["raw"]["max_step_s"] == pytest.approx(5e-9)


def _body(text: str) -> list[str]:
    """Drop the generated header and the .save block, normalise VIN/RL."""
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith(".save"):
            break
        if line.startswith(("* HIGH OUTPUT SENSITIVITY", "* VIN=", "* Source:")):
            continue
        out.append(re.sub(r"^\.param VIN=\S+ RL=\S+", ".param VIN=<v> RL=<r>", line))
    return out
