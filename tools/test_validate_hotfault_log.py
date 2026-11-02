"""Synthetic log-format tests; no simulations or hardware data are created."""
from __future__ import annotations

from pathlib import Path

import pytest

import validate_hotfault_log as v


def _log(deck: Path, ss: float = 4.25, trip: float = 0.000210,
         vout: float = 1.8737, oc_after: float = 1.3) -> str:
    return (
        "LTspice 26.0.2 for Windows\n"
        f"Circuit: D:\\\\project\\\\{deck.name}\n"
        "Total elapsed time: 244.8 seconds.\n"
        f"hot_vout_early: AVG(V(out) )={vout} FROM 0.00012 TO 0.000145\n"
        f"hot_vout_late: AVG(V(out) )={vout} FROM 0.000145 TO 0.00017\n"
        "hot_ctrl_before: AVG(V(ctl_hot) )=0 FROM 0.00012 TO 0.00017\n"
        "hot_ctrl_after: AVG(V(ctl_hot) )=5 FROM 0.00019 TO 0.00030\n"
        "hot_iflt_after: MAX(I(Rflt_hot) )=212 FROM 0.000175 TO 0.00032\n"
        f"hot_ss_before: AVG(V(ss) )={ss} FROM 0.00012 TO 0.00017\n"
        f"hot_vout_before: AVG(V(out) )={vout} FROM 0.00012 TO 0.00017\n"
        "hot_oc_before: MAX(V(oc) )=0.68 FROM 0.00012 TO 0.00017\n"
        "hot_ipri_after: MAX(abs(I(Lr)) )=88.4 FROM 0.000175 TO 0.00032\n"
        f"hot_oc_after: MAX(V(oc) )={oc_after} FROM 0.000175 TO 0.00032\n"
        "hot_vout_min: MIN(V(out) )=-0.01 FROM 0.000175 TO 0.00032\n"
        f"hot_oc_trip: V(oc)=1  AT {trip}\n"
    )


def _input(tmp_path: Path, **kwargs) -> tuple[Path, Path]:
    log = tmp_path / "model.log"
    raw = tmp_path / "model.raw"
    log.write_text(_log(v.CASES["48v_120a"]["deck"], **kwargs), encoding="utf-8")
    raw.write_bytes(b"Title: synthetic\nPlotname: Transient Analysis\n"
                    b"No. Variables: 1\nNo. Points: 2\nVariables:\n"
                    b"\t0 time time\nValues:\n0 0\n1 1\n")
    return log, raw


def test_accepts_a_complete_post_fault_trip_but_never_grants_hw_rating(tmp_path: Path):
    log, raw = _input(tmp_path)
    result = v.build("48v_120a", log, raw)
    assert result["blockers"] == []
    assert result["status"].startswith("LOG_PRECHECK_PASS")
    assert result["not_rated"]
    assert result["probes"]["hot_oc_trip"] >= v.FAULT_AT_S


def test_rejects_ss_below_rt_only_threshold(tmp_path: Path):
    log, raw = _input(tmp_path, ss=3.7815)
    assert any("outside RT-only regime" in b for b in v.build("48v_120a", log, raw)["blockers"])


def test_rejects_pre_fault_trip_even_if_the_max_oc_exceeds_one(tmp_path: Path):
    log, raw = _input(tmp_path, trip=0.000155)
    assert any("not within post-fault" in b for b in v.build("48v_120a", log, raw)["blockers"])


def test_rejects_missing_oc_action_and_no_tripped_measure(tmp_path: Path):
    log, raw = _input(tmp_path, oc_after=0.8)
    assert any("never reached" in b for b in v.build("48v_120a", log, raw)["blockers"])
    s = log.read_text(encoding="utf-8").replace("hot_oc_trip:", "hot_oc_trip_old:")
    log.write_text(s, encoding="utf-8")
    assert any("hot_oc_trip is absent" in b for b in v.build("48v_120a", log, raw)["blockers"])


def test_rejects_solver_prefix_and_spurious_raw_file(tmp_path: Path):
    log, raw = _input(tmp_path)
    log.write_text(log.read_text(encoding="utf-8").replace(
        "Total elapsed time: 244.8 seconds.\n", ""), encoding="utf-8")
    assert any("solver" in b for b in v.build("48v_120a", log, raw)["blockers"])
    log.write_text(_log(v.CASES["48v_120a"]["deck"]), encoding="utf-8")
    raw.write_text("NOT AN LTSPICE RAW", encoding="utf-8")
    assert any("header" in b for b in v.build("48v_120a", log, raw)["blockers"])


def test_rejects_the_other_deck_and_vout_not_settled(tmp_path: Path):
    log, raw = _input(tmp_path)
    s = log.read_text(encoding="utf-8").replace(
        v.CASES["48v_120a"]["deck"].name, v.CASES["50v_120a"]["deck"].name)
    log.write_text(s, encoding="utf-8")
    assert any("Circuit" in b for b in v.build("48v_120a", log, raw)["blockers"])
    log.write_text(_log(v.CASES["48v_120a"]["deck"], vout=1.5), encoding="utf-8")
    assert any("Vout" in b for b in v.build("48v_120a", log, raw)["blockers"])


def test_real_existing_50v_120a_log_is_not_a_hot_fault_log():
    path = v.ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.log"
    values, errors = v.parse_log(path.read_text(encoding="utf-8"))
    assert values == {}
    assert any("hot_oc_trip" in err for err in errors)


def test_fault_switch_off_or_no_injected_current_fails_even_if_oc_claims_a_trip(tmp_path: Path):
    log, raw = _input(tmp_path)
    value = log.read_text(encoding="utf-8").replace(
        "hot_iflt_after: MAX(I(Rflt_hot) )=212",
        "hot_iflt_after: MAX(I(Rflt_hot) )=0")
    log.write_text(value, encoding="utf-8")
    assert any("injected fault" in b for b in v.build("48v_120a", log, raw)["blockers"])
    log.write_text(_log(v.CASES["48v_120a"]["deck"]).replace(
        "hot_ctrl_after: AVG(V(ctl_hot) )=5",
        "hot_ctrl_after: AVG(V(ctl_hot) )=0"), encoding="utf-8")
    assert any("did not reach" in b for b in v.build("48v_120a", log, raw)["blockers"])


def test_4p2v_ss_is_expected_rt_only_frequency_model_not_4p8v(tmp_path: Path):
    log, raw = _input(tmp_path, ss=4.2)
    obj = v.build("48v_120a", log, raw)
    assert obj["blockers"] == []
    assert obj["ss_rt_only_threshold_v"] == pytest.approx(3.982)


def test_early_late_vout_drift_blocks_even_if_average_matches(tmp_path: Path):
    log, raw = _input(tmp_path)
    content = log.read_text(encoding="utf-8").replace(
        "hot_vout_early: AVG(V(out) )=1.8737",
        "hot_vout_early: AVG(V(out) )=1.80")
    log.write_text(content, encoding="utf-8")
    assert any("adjacent windows" in msg
               for msg in v.build("48v_120a", log, raw)["blockers"])
