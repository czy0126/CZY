"""The 48 V / 120 A true-cold-start and overload-fault target decks.

The raws are ~12 GB each and stay out of git, so the JSON records are the
evidence.  These tests pin the deck-level facts that decide whether a run is
allowed to be called a cold start at all:

  * no ``.ic`` anywhere means Cout really starts at 0 V;
  * the fault deck is the cold deck plus one injection block and its
    measurements -- nothing else may differ;
  * the injection is a 1 mOhm switch in parallel with the load, engaging at
    5.55 ms, not a load step at some value nobody can reproduce.

Values from the runs themselves are locked once the JSON records exist.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import analyze_v3_transient as avt

ROOT = Path(__file__).resolve().parent.parent
COLD = ROOT / "sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.cir"
FAULT = ROOT / "sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.cir"
COLD_JSON = ROOT / "design/v3/power_priority/cold_start_48v_120a_target.json"
FAULT_JSON = ROOT / "design/v3/power_priority/fault_48v_120a_target.json"

INJECTION_ELEMENTS = (
    "Vfltctl ctl 0 PWL(0 0 5.5m 0 5.6m 5 8m 5)",
    "Sflt out flt ctl 0 SFLT",
    "Rflt flt 0 1m",
    ".model SFLT SW(Ron=1m Roff=1G Vt=2.5)",
)

FAULT_MEAS = (
    ".meas tran OC_TRIP WHEN V(oc)=1 CROSS=1",
    ".meas tran OC_AFTER_MAX MAX V(oc) FROM=5.6m TO=8m",
    ".meas tran IPRI_AFTER MAX abs(I(Lr)) FROM=5.6m TO=5.8m",
    ".meas tran VOUT_AFTER_MIN MIN V(out) FROM=5.6m TO=8m",
    ".meas tran OUT_AT_END FIND V(out) AT=8m",
)


def body(path: Path) -> list[str]:
    """Everything from ``.options`` on, so generated headers cannot hide a diff."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(".options"))
    return lines[start:]


@pytest.mark.parametrize("deck", [COLD, FAULT], ids=["cold", "fault"])
def test_the_target_decks_are_true_cold_starts(deck: Path):
    text = deck.read_text(encoding="utf-8")
    assert avt.deck_has_ic(deck) is False
    # The only ``.ic`` in the file must be the comment explaining why there is
    # none; a comment has no effect on the solver.
    for line in text.splitlines():
        if ".ic" in line.lower():
            assert line.lstrip().startswith("*"), line
    # 8 ms from zero, 10 ns cap, uic: the raw covers the whole start-up.
    assert avt.deck_stop_s(deck) == pytest.approx(8e-3)
    assert ".tran 0 8m 0 10n uic" in text


@pytest.mark.parametrize("deck", [COLD, FAULT], ids=["cold", "fault"])
def test_the_load_is_the_120a_target_not_a_result(deck: Path):
    text = deck.read_text(encoding="utf-8")
    assert ".param VIN=48 RL=15.4m" in text
    assert "UNRUN, NO HW RATING" in text
    assert "120A" in text.splitlines()[2]  # says it is the eventual target


def test_the_fault_deck_is_the_cold_deck_plus_one_injection():
    cold, fault = body(COLD), body(FAULT)
    # The injection is the block from its banner comment to the switch model.
    start = next(i for i, line in enumerate(fault) if line.startswith("* ---- OC fault injection"))
    end = fault.index(".model SFLT SW(Ron=1m Roff=1G Vt=2.5)") + 1
    block = fault[start:end]
    assert [line for line in block if line in INJECTION_ELEMENTS] == list(INJECTION_ELEMENTS)
    without = [line for i, line in enumerate(fault) if not start <= i < end]
    without = [line for line in without if line not in FAULT_MEAS]
    assert without == cold


def test_the_fault_engages_after_five_milliseconds():
    assert avt.engage_time(5.5e-3, 5.6e-3) == pytest.approx(5.55e-3)
    text = FAULT.read_text(encoding="utf-8")
    assert "PWL(0 0 5.5m 0 5.6m 5 8m 5)" in text
    # The switch threshold is 2.5 V of a 0..5 V ramp, i.e. the midpoint.
    assert "Vt=2.5" in text
    # 1 mOhm parallel with the 15.4 mOhm load, not a 1 mOhm load alone.
    assert "Rflt flt 0 1m" in text


@pytest.mark.parametrize("deck", [COLD, FAULT], ids=["cold", "fault"])
def test_the_save_block_covers_every_node_the_analysis_reads(deck: Path):
    text = deck.read_text(encoding="utf-8")
    for signal in ("V(out)", "V(oc)", "I(Lr)", "V(a1)", "V(b4)"):
        assert signal in text, signal


def record(path: Path) -> dict:
    """The JSON record is the committed evidence; the raw is not."""
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_cold_record_starts_from_zero_volts_not_a_precharge():
    """``uic`` without ``.ic`` is the only thing that makes this a cold start.

    The deck-level guard is in :func:`avt.deck_has_ic`; the measured proof is
    the very first sample, which the solver must produce near 0 V.  A run
    that opens at ~1.9 V is a warmed-up resume wearing a cold-start label.
    """
    data = record(COLD_JSON)
    assert data["kind"] == "cold"
    assert data["deck_has_ic"] is False
    assert data["vout_at_t_first_v"] < 0.05
    assert data["deck_tstop_s"] == pytest.approx(8e-3)


def test_the_cold_record_keeps_120a_as_the_load_not_the_result():
    """RL=15.4 mOhm was chosen to *aim* at 120 A; the achieved current is Vout/RL.

    Pinning ``iout_final_a == vout_final_v / load`` stops a later edit from
    writing the target into the result column.
    """
    data = record(COLD_JSON)
    assert data["load_ohm_nominal"] == pytest.approx(0.0154)
    assert data["iout_final_a"] == pytest.approx(
        data["vout_final_v"] / data["load_ohm_nominal"], rel=1e-9)
    assert "V(out)^2 / RL" in data["pout_final_basis"]


def test_the_fault_record_takes_its_severity_from_the_deck():
    """1 mOhm switch + 1 mOhm resistor in parallel with 15.4 mOhm is 8.70x.

    The inherited banner's 1.818 mOhm / 11x belongs to the 20 mOhm parent;
    reading it here would overstate the fault by 25 %.
    """
    data = record(FAULT_JSON)
    assert data["fault_branch_ohm"] == pytest.approx(2e-3)
    assert data["load_ohm_after_fault"] == pytest.approx(1.77011e-3, rel=1e-4)
    assert data["fault_severity_x"] == pytest.approx(0.0154 / 1.77011e-3, rel=1e-4)
    assert "RL ||" in data["pout_final_basis"]


def test_the_fault_record_times_the_trip_from_engagement():
    """The OC trip is measured from the 5.55 ms engagement, not from t=0.

    ``fault_to_trip_us`` is the delay the protection has to survive; a trip
    stamped before engagement would be a pre-existing event, not the fault's.
    """
    data = record(FAULT_JSON)
    assert data["fault_engage_ms"] == pytest.approx(5.55)
    if data["oc_trip_ms"] is not None:
        assert data["oc_trip_ms"] >= data["fault_engage_ms"]
        assert data["fault_to_trip_us"] == pytest.approx(
            (data["oc_trip_ms"] - data["fault_engage_ms"]) * 1e3, abs=0.02)
        assert data["ipri_peak_after_engage_a"] >= data["ipri_peak_before_trip_a"]


def test_a_prefix_only_record_says_so():
    """If the solver collapses, the streamed prefix is evidence -- of a prefix.

    ``reached_tstop`` and ``solver_prefix_only`` must stay complementary, and
    a prefix may never be reported as a completed 8 ms run.
    """
    for path in (COLD_JSON, FAULT_JSON):
        data = record(path)
        assert data["reached_tstop"] is not data["solver_prefix_only"]
        if data["solver_prefix_only"]:
            assert data["t_last_s"] < data["deck_tstop_s"]
            assert "prefix" in data["note"]
        else:
            assert data["t_last_s"] >= data["deck_tstop_s"] - 1e-9


def test_the_log_tells_the_same_story_about_completion():
    """A killed solver never writes LTspice's ``Total elapsed time`` line.

    The raw prefix and the log must agree on whether the deck finished; a
    prefix record paired with a finished-looking log would hide the collapse.
    """
    fault = record(FAULT_JSON)
    log = (ROOT / "sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.log").read_text(
        encoding="utf-8", errors="replace")
    if fault["solver_prefix_only"]:
        assert "Total elapsed time" not in log
    else:
        assert "Total elapsed time" in log


def _meas(log: Path, name: str) -> float:
    """The numeric result of LTspice's own ``.meas`` line in the run log."""
    text = log.read_text(encoding="utf-8", errors="replace")
    match = re.search(rf"^{name}:.*?=([0-9.eE+-]+)", text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"{log.name} has no {name}: measurement")
    return float(match.group(1))


def test_the_streamed_records_agree_with_ltspices_own_meas():
    """Two independent readers of the same raw must produce the same peak.

    The JSON is produced by the streaming parser; the log's ``.meas`` block is
    produced by LTspice.  If they disagree, the streamed window or column
    mapping is wrong -- not least because the log is computed before the raw
    is ever touched by this repository.
    """
    cold = record(COLD_JSON)
    cold_log = ROOT / "sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.log"
    assert cold["vout_max_v"] == pytest.approx(_meas(cold_log, "vout_max"), rel=1e-9)
    assert cold["ipri_peak_a"] == pytest.approx(_meas(cold_log, "ipri_pk"), rel=1e-9)

    fault = record(FAULT_JSON)
    fault_log = ROOT / "sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.log"
    if fault["solver_prefix_only"]:
        # LTspice writes its .meas block when the solver exits normally.  This
        # run collapsed at 7.571 ms and was terminated by PID, so there is no
        # independent measurement to compare against; the cold record above
        # remains the parser's cross-check.  Pin the absence rather than skip
        # silently, so a completed run that loses its .meas block is still red.
        assert "ipri_after:" not in fault_log.read_text(encoding="utf-8", errors="replace")
        return
    if fault["ipri_peak_5p6_5p8_a"] is not None:
        assert fault["ipri_peak_5p6_5p8_a"] == pytest.approx(
            _meas(fault_log, "ipri_after"), rel=1e-9)
