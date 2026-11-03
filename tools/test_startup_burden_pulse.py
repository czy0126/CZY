"""The cold-start CT burden must be derived from a checked transfer, not assumed.

The cold-start deck does not save ``V(ocd)``/``V(ocm)``, so the burden power is
obtained from the saved ``I(Lr)`` through the ideal-transformer identity.  That
makes three things load-bearing and therefore pinned here:

* the transfer is *measured* on a record that saves both traces, and the
  linearity of that transfer is what licenses applying it elsewhere;
* the CT ladder (Lct1, Lct2, Kct, Rbur) is identical in the two decks, so the
  transfer is not being carried between different circuits;
* the derived steady 7-8 ms power lands on the independently measured 125.7 mW,
  which is the check that the method is not self-fulfilling.

The rating ladder is read from the recorded R3 candidate screen (PR 28), so a
future part change cannot leave this tool quietly rating against the rejected
0805.

The RAW-derived test skips when the gigabyte-scale cold record is absent, and
only re-reads the first 2 ms so the suite does not pay for the whole 8 ms.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import startup_burden_pulse as sbp

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "design/v3/bom/startup_burden_pulse.json"


def record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def test_the_transfer_is_measured_and_close_to_the_winding_ratio():
    results = record()["results"]
    transfer = results["transfer"]
    # The value used must be the measured median, not the nominal R_b/N.
    assert transfer["used_v_per_a"] == transfer["median_v_per_a"]
    assert transfer["used_v_per_a"] != results["ct"]["nominal_v_per_a"]
    assert abs(transfer["used_v_per_a"] / results["ct"]["nominal_v_per_a"] - 1.0) < 0.02
    assert transfer["p05_v_per_a"] < transfer["used_v_per_a"] < transfer["p95_v_per_a"]


def test_the_ct_ladder_is_identical_in_the_two_decks():
    cold = sbp.ct_ladder(sbp.COLD_DECK.read_text(encoding="utf-8"))
    paired = sbp.ct_ladder(sbp.PAIRED_DECK.read_text(encoding="utf-8"))
    for key in ("lct1_h", "lct2_h", "kct", "rbur_ohm", "turns_ratio"):
        assert cold[key] == paired[key], key
    assert cold["turns_ratio"] == pytest.approx(100.0)


def test_the_derived_steady_power_reproduces_the_measured_burden():
    check = record()["results"]["steady_cross_check"]
    assert check["deviation_pct"] < 3.0, check
    # Both numbers exist and are of the same size; the derived one is not a copy.
    assert 0.1 < check["measured_48v_120a_w"] < 0.2
    assert 0.1 < check["derived_7_to_8ms_w"] < 0.2


def test_the_rating_is_read_from_the_candidate_screen_not_the_rejected_0805():
    results = record()["results"]
    rating = results["rating"]
    screen = json.loads(sbp.R3_SCREEN.read_text(encoding="utf-8"))
    assert rating["mpn"] == screen["candidate_mpn"]
    assert rating["rated_power_w"] == screen["candidate_rating_power_w"]
    assert rating["rejected_source_mpn"] == screen["source_mpn"]
    assert screen["source_rating_status"] == "REJECTED_120A"
    assert rating["mpn"] != rating["rejected_source_mpn"]
    assert {"125c", "140c", "150c"} <= set(rating["derated_w"])
    assert rating["derated_w"]["125c"] > rating["derated_w"]["150c"]


def test_every_reported_ratio_is_internally_consistent():
    results = record()["results"]
    rating, startup = results["rating"], results["startup"]
    assert rating["peak_over_p70"] == pytest.approx(startup["peak_w"] / rating["rated_power_w"],
                                                    rel=1e-4)
    for name, watts in rating["derated_w"].items():
        assert rating["peak_over_derated"][name] == pytest.approx(startup["peak_w"] / watts,
                                                                 rel=1e-4)
    levels = sbp.thresholds(sbp.candidate_rating())
    assert set(levels) == {"quarter_of_p70", "p70", "four_times_p70",
                           "derated_at_125c", "derated_at_140c", "derated_at_150c"}
    assert set(startup["time_above"]) == {f"above_{name}_us" for name in levels}


def test_the_energy_split_is_reported_and_ordered():
    results = record()["results"]
    full, slice2ms = results["startup"], results["peak_slice"]
    assert 0.0 < slice2ms["energy_mj"] < full["energy_mj"]
    # mJ / us = 1e3 W, so the mW mean is the ratio times 1e6.
    assert full["mean_mw"] == pytest.approx(full["energy_mj"] / full["duration_us"] * 1e6,
                                            rel=1e-3)
    assert results["fault_contrast"]["energy_ratio_startup_over_fault"] == pytest.approx(
        full["energy_mj"] / results["fault_contrast"]["fault_energy_mj"], rel=1e-4)


@pytest.mark.skipif(not sbp.COLD_RAW.is_file(), reason="cold-start raw is gitignored")
def test_the_first_two_milliseconds_can_be_reproduced_from_the_raw():
    from ascii_raw_window import read_window

    recorded = record()["results"]["peak_slice"]
    t, data = read_window(sbp.COLD_RAW, ["I(Lr)", "V(out)", "V(ss)"], *sbp.PEAK_SLICE)
    regenerated = sbp.stats(t, data, record()["results"]["transfer"]["used_v_per_a"],
                            record()["results"]["ct"]["rbur_ohm"],
                            levels=sbp.thresholds(sbp.candidate_rating()))
    assert regenerated["samples"] == recorded["samples"]
    assert regenerated["peak_w"] == recorded["peak_w"]
    assert regenerated["t_peak_ms"] == recorded["t_peak_ms"]
    assert regenerated["energy_mj"] == recorded["energy_mj"]
    assert regenerated["time_above"] == recorded["time_above"]
