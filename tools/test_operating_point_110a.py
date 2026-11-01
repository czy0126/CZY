"""The 48 V/110 A candidate was run once; these tests keep the record honest.

The deck header still says UNRUN because `make_high_output_decks.py` regenerates
it from the 100 A mother deck and a test locks that text.  The evidence therefore
lives in `operating_point_48v_110a.json` (extracted from the raw by
`tools/extract_op_point.py`) and in the document that quotes it.  Nothing here
re-runs LTspice: the 359 MB raw is git-ignored, so the JSON *is* the record.

What must not drift:

  * "110 A" is a load-resistor target, not a result.  16.9 mOhm was chosen from a
    linear estimate that assumed 1.8586 V; the deck delivered 1.8786 V, so the
    measured load current is 111.2 A.  Reporting 110.0 A as measured would be
    inventing the answer the target already contained.
  * the instrumented pairs cover 2 of 4 groups, so the load current is
    `iout_from_v_a`, not `2 * iout_sum_a` -- unless the symmetry factor is checked
    against it, which is what test_two does.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HIGH = ROOT / "design/v3/power_priority/operating_point_48v_110a.json"
BASE = ROOT / "design/v3/magnetics/operating_point_100a_phys.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_record_carries_the_target_and_not_just_a_round_number():
    d = load(HIGH)
    assert d["rl_ohm"] == pytest.approx(0.0169)
    # 16.9 mOhm was picked for 110 A from a linear estimate; the run is not 110.0 A.
    assert 110.0 < d["iout_from_v_a"] < 112.0
    assert d["iout_from_v_a"] - 110.0 > 0.5


def test_the_two_measured_pairs_scale_to_the_whole_load():
    d = load(HIGH)
    # Pairs 2 and 3 are not instrumented; x2 is a model-symmetry assumption, so it
    # has to be validated against an independent measurement (avg(Vout)/RL).
    reconstructed = 2.0 * d["iout_sum_a"]
    assert reconstructed == pytest.approx(d["iout_from_v_a"], rel=5e-3)
    assert d["iout_spread_pct"] < 1e-6  # symmetry, not a sharing result


def test_output_power_is_the_true_mean_of_the_square():
    d = load(HIGH)
    assert d["iout_from_v_a"] == pytest.approx(d["vout_avg_v"] / d["rl_ohm"], rel=1e-9)
    assert d["pout_w"] == pytest.approx(d["vout_rms_v"] ** 2 / d["rl_ohm"], rel=1e-6)
    assert d["vout_rms_v"] >= d["vout_avg_v"]


def test_raising_the_load_current_raises_every_stress_column():
    hi, base = load(HIGH), load(BASE)
    assert hi["iout_from_v_a"] / base["iout_from_v_a"] == pytest.approx(1.115, abs=0.01)
    for key in ("ipri_rms_a", "ipri_pk_a", "vout_pp_mv", "pout_w"):
        assert hi[key] > base[key], key
    for pool in ("pair1", "pair4"):
        for key in ("iout_a", "irms_pair_a", "ifwd_pk_a", "irev_pk_a"):
            assert hi[pool][key] > base[pool][key], f"{pool}.{key}"


def test_the_record_does_not_claim_a_rating():
    """Neither deck nor JSON may present 110 A as rated hardware output."""
    deck = (ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110.cir").read_text(encoding="utf-8")
    assert "HIGH OUTPUT SENSITIVITY ONLY - UNRUN, NOT HARDWARE RATED" in deck
    d = load(HIGH)
    assert "rating" not in d and "efficiency" not in d
