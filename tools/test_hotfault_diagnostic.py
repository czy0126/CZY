"""A solver diagnostic is only comparable if the circuit and window match."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import hotfault_diagnostic as h

ROOT = Path(__file__).resolve().parent.parent
RAW_48 = ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.raw"
DECK_48 = ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.cir"
RECORD_48 = ROOT / "design/v3/power_priority/hotfault_48v_120a.json"


BASE_DECK = """* base
.param VIN=50
.options plotwinsize=0 method=gear
.tran 0 2320u 2000u 5n uic
.meas tran HOT_OC_TRIP WHEN V(oc)=1 RISE=1
.end
"""

DIAG_DECK = """* SOLVER_DIAGNOSTIC
* just a header comment
.param VIN=50
.options plotwinsize=0 method=gear trtol=1 abstol=1e-13
.tran 0 2215u 2000u 5n uic
.meas tran HOT_OC_TRIP WHEN V(oc)=1 RISE=1
.end
"""


def test_only_the_solver_and_stop_may_differ_between_the_two_decks():
    assert h.circuit_differences(BASE_DECK, DIAG_DECK) == []


def test_a_changed_circuit_line_is_reported():
    changed = BASE_DECK.replace("VIN=50", "VIN=60")
    assert h.circuit_differences(changed, DIAG_DECK) == ["line 2: '.param VIN=60' vs '.param VIN=50'"]


def test_a_changed_fault_probe_is_reported():
    changed = DIAG_DECK.replace("RISE=1", "RISE=2")
    diffs = h.circuit_differences(BASE_DECK, changed)
    assert len(diffs) == 1 and "RISE=2" in diffs[0]


def test_relative_deltas_name_the_headline_peaks_and_divide_by_the_base():
    base = {"ipri_peak_a": 101.2626574558339, "sr_forward_peak_a": 303.93,
            "trip_s": 214.9153406335383e-6, "vout_min_after_engage_v": -0.0075642}
    diag = {"ipri_peak_a": 103.0, "sr_forward_peak_a": 300.0,
            "trip_s": 214.9e-6, "vout_min_after_engage_v": -0.0076}
    out = h.relative_deltas(base, diag)
    assert out["ipri_peak_a"] == 103.0 / 101.2626574558339 - 1.0
    assert out["sr_forward_peak_a"] == 300.0 / 303.93 - 1.0
    assert set(out) == set(h.PEAK_KEYS)


def test_a_missing_peak_is_none_not_a_fabricated_zero():
    base = {"ipri_peak_a": 101.0, "sr_forward_peak_a": 0.0}
    diag = {"ipri_peak_a": None, "sr_forward_peak_a": 1.0}
    out = h.relative_deltas(base, diag)
    assert out["ipri_peak_a"] is None
    # base zero cannot be normalised; None, never a division by zero
    assert out["sr_forward_peak_a"] is None


def test_the_comparison_window_is_the_shorter_of_the_two_runs():
    # base stalled at 296.929 us, diagnostic stops at 220 us: the shared
    # window is 220 us, and it must be derived from the records, not typed.
    assert h.shared_window_s(296.9292305726456e-6, 220.0e-6) == 220.0e-6
    assert h.shared_window_s(220.0e-6, 296.9292305726456e-6) == 220.0e-6


def test_the_limits_name_the_window_and_only_the_base_that_stopped_early():
    completed = h._limits(220e-6, {"solver_completed": True})
    stalled = h._limits(220e-6, {"solver_completed": False})
    assert any("220 us" in line for line in completed)
    assert not any("no completion line" in line for line in completed)
    assert any("no completion line" in line for line in stalled)
    # No log at all is not a claim that the base completed.
    assert not any("no completion line" in line for line in h._limits(220e-6, None))


@pytest.mark.skipif(not RAW_48.exists(), reason="the 1.05 GB 48 V raw is not in Git")
def test_the_reader_reproduces_the_published_48v_record():
    """Any delta in a diagnostic comparison must be the solver, not the reader.

    The 48 V peak sits at 209.95 us, inside the 220 us window, so reading the
    raw through this tool must return the published number bit-for-bit.
    """
    record = json.loads(RECORD_48.read_text(encoding="utf-8"))["fault"]
    out = h.window_peaks(RAW_48, DECK_48.read_text(encoding="utf-8"), 220e-6)
    assert out["ipri_peak_a"] == pytest.approx(record["ipri_peak_before_trip_a"], rel=1e-12)
    assert out["sr_forward_peak_a"] == pytest.approx(
        record["sr_forward_peak_whole_record_a"], rel=1e-12)
    assert out["trip_s"] == pytest.approx(record["trip_s"], rel=1e-12)
    assert out["delay_from_engage_us"] == pytest.approx(
        record["delay_from_engage_us"], rel=1e-12)
