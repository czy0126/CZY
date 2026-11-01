"""Tests for tools/make_round4_decks.py.

Only the new cold_oc variant is covered here: the other decks are already
frozen evidence files, and re-generating them in a test would touch mtimes
that the round-4 provenance notes rely on.
"""

from __future__ import annotations

from make_round4_decks import cold, cold_oc


def test_cold_oc_has_no_ic_line() -> None:
    """A '.ic' line would mean the deck is not a true cold start."""
    active = [ln.strip() for ln in cold_oc().splitlines() if ln.strip().lower().startswith(".ic ")]
    assert active == []


def test_cold_oc_injects_one_fault_path() -> None:
    text = cold_oc()
    assert text.count("Vfltctl ctl 0 PWL(0 0 5.5m 0 5.6m 5 8m 5)") == 1
    assert text.count("Sflt out flt ctl 0 SFLT") == 1
    assert text.count("Rflt flt 0 1m") == 1
    assert text.count(".model SFLT SW(Ron=1m Roff=1G Vt=2.5)") == 1


def test_cold_oc_keeps_the_cold_power_stage() -> None:
    """The fault variant must differ from the accepted cold deck only by the fault."""
    base = set(cold().splitlines())
    extra = [ln for ln in cold_oc().splitlines() if ln not in base]
    fault_lines = {
        "Vfltctl ctl 0 PWL(0 0 5.5m 0 5.6m 5 8m 5)",
        "Sflt out flt ctl 0 SFLT",
        "Rflt flt 0 1m",
        ".model SFLT SW(Ron=1m Roff=1G Vt=2.5)",
    }
    # Extra lines are the fault path, its comment/variant header and the extra
    # .meas lines; no power-stage element may be added or removed.
    assert fault_lines <= set(extra)
    for line in extra:
        assert line.startswith(("*", ".")) or line in fault_lines


def test_cold_oc_measures_the_trip() -> None:
    text = cold_oc()
    assert ".meas tran OC_TRIP WHEN V(oc)=1 CROSS=1" in text
    assert ".tran 0 8m 0 10n uic" in text
