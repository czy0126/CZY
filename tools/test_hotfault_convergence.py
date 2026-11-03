"""A convergence aid is only evidence if it finishes and reproduces the prefix."""
from __future__ import annotations

from pathlib import Path

import pytest

import hotfault_convergence as c
import make_hot_fault_decks as m
from hotfault_diagnostic import circuit_differences

ROOT = Path(__file__).resolve().parent.parent
RAW_48 = ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.raw"
DECK_48 = ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.cir"
DIAG_RAW_48 = ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_diag.raw"
DIAG_DECK_48 = ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_diag.cir"


def test_reached_stop_accepts_one_nanosecond_and_rejects_a_stall():
    # The base run stalls at 296.929 us of a 320 us stop: that is not completion.
    assert not c.reached_stop(296.9292305726456e-6, 320e-6)
    # A stop is reached when the last sample is the stop, within one nanosecond.
    assert c.reached_stop(320e-6, 320e-6)
    assert c.reached_stop(320e-6 - 0.5e-9, 320e-6)
    assert not c.reached_stop(320e-6 - 2e-9, 320e-6)


def test_the_cshunt_variant_is_the_same_circuit_for_this_tool_too():
    # The tool's own guard must accept the deck it is meant to compare: only
    # comments and .options differ, so circuit_differences has to be empty.

    name = m.CONVERGENCE_CASE
    base = m.build(m.SOURCE[name].read_text(encoding="utf-8"), name)
    conv = m.convergence(base, name)
    assert circuit_differences(base, conv) == []


def test_a_circuit_change_masquerading_as_a_convergence_aid_is_reported():

    name = m.CONVERGENCE_CASE
    base = m.build(m.SOURCE[name].read_text(encoding="utf-8"), name)
    conv = m.convergence(base, name).replace("Rflt_hot flt_hot 0 1m", "Rflt_hot flt_hot 0 2m")
    assert circuit_differences(base, conv) != []


def test_a_window_beyond_a_deck_stop_is_refused_before_any_raw_is_read():
    # The 48 V decks are tracked, so their stop is known without a raw; 400 us
    # is past both stops and must raise before the (missing) raw is opened.
    with pytest.raises(ValueError):
        c.compare(Path("missing.raw"), DECK_48, Path("missing.raw"), DECK_48,
                  window_us=400.0)


def test_the_default_window_stays_inside_the_stalled_base_record():
    # The 50 V base has data only to 296.929 us; a comparison window past that
    # would silently read a truncated prefix as if it were the whole window.
    assert c.COMPARE_WINDOW_US == 220.0
    assert c.COMPARE_WINDOW_US < 296.929


@pytest.mark.skipif(not (RAW_48.exists() and DIAG_RAW_48.exists()),
                    reason="the 48 V raws are not in Git")
def test_the_48v_control_pair_passes_the_structural_checks():
    """Exercise the whole record on the pair whose deltas are already published.

    The 48 V base completed its 320 us window while the diagnostic stops at
    220 us, so completion is judged against each deck's own stop.  This is the
    control: the tool must say "base completed, variant completed", not
    "stalled", before its verdict on the 50 V cshunt run means anything.
    """
    record = c.compare(RAW_48, DECK_48, DIAG_RAW_48, DIAG_DECK_48, window_us=220.0)
    assert all(record["checks"].values())
    results = record["results"]
    assert results["base_reached_saved_stop"] is True
    assert results["variant_reached_saved_stop"] is True
    # Same prefix window on both sides, and the fault is inside it.
    assert record["window_s"][0] == 0.0
    assert record["window_s"][1] == pytest.approx(220e-6, rel=1e-12)
    assert results["base"]["trip_s"] is not None
    assert results["variant"]["trip_s"] is not None
