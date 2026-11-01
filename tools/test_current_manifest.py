"""Tests for tools/current_manifest.py.

The manifest's job is to make the delivery reproducible, so what matters is that
the numbers it publishes are derived rather than hand-copied.  `deck_timing` is
checked against LTspice's own log, which is an independent statement of the same
window.
"""

from __future__ import annotations

from current_manifest import ROOT, deck_timing, log_saved_end_s, spice_seconds

DECK_100A = "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"
LOG_100A = "sim/v3/sr_tank_dual_v33_ss_1ms_100a.log"


def test_spice_seconds_handles_the_suffixes_decks_use():
    # literals and mantissa*scale differ in the last ulp, so compare relatively
    assert abs(spice_seconds("880u") - 880e-6) < 1e-12
    assert abs(spice_seconds("5n") - 5e-9) < 1e-15
    assert abs(spice_seconds("8m") - 8e-3) < 1e-12
    assert spice_seconds("0") == 0.0
    assert abs(spice_seconds("1meg") - 1e6) < 1e-9


def test_tstart_becomes_the_display_offset_not_the_raw_start(tmp_path):
    deck = tmp_path / "d.cir"
    deck.write_text(".tran 0 500u 440u 5n uic\n", encoding="utf-8")
    row = deck_timing("d.cir", root=tmp_path)
    assert row["raw_time_start_s"] == 0.0
    assert abs(row["raw_time_end_s"] - 60e-6) < 1e-15
    assert row["display_offset_us"] == 440.0
    assert abs(row["max_step_s"] - 5e-9) < 1e-18


def test_no_tstart_means_no_offset(tmp_path):
    deck = tmp_path / "d.cir"
    deck.write_text(".tran 0 8m 0 5n uic\n", encoding="utf-8")
    assert deck_timing("d.cir", root=tmp_path)["display_offset_us"] == 0.0


def test_an_ic_line_defeats_uic_for_cold_start(tmp_path):
    """Same rule as tools/task_package1_summary.py:cold_start()."""
    cold = tmp_path / "cold.cir"
    cold.write_text(".tran 0 8m 0 5n uic\n", encoding="utf-8")
    warm = tmp_path / "warm.cir"
    warm.write_text(".tran 0 8m 0 5n uic\n.ic V(out)=1.89 V(ss)=4\n", encoding="utf-8")
    assert deck_timing("cold.cir", root=tmp_path)["cold_start"] is True
    assert deck_timing("warm.cir", root=tmp_path)["cold_start"] is False
    assert deck_timing("warm.cir", root=tmp_path)["has_ic"] is True


def test_missing_deck_is_reported_not_raised(tmp_path):
    assert deck_timing("nope.cir", root=tmp_path)["status"] == "missing"


def test_the_100a_deck_metadata_matches_ltspice_own_log():
    row = deck_timing(DECK_100A)
    assert row["display_offset_us"] == 880.0
    assert abs(row["raw_time_end_s"] - 120e-6) < 1e-15
    # LTspice prints the saved window in the log; the deck must agree with it.
    assert abs(row["raw_time_end_s"] - log_saved_end_s(ROOT / LOG_100A)) < 1e-12
    # This deck carries .ic, so despite `uic` it is not a cold start.
    assert row["cold_start"] is False
