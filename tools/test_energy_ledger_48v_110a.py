"""The 111 A candidate's input power and efficiency, measured on its own raw.

The candidate deck saves the output but not ``I(Rin)``/``I(Cin)``, so before
the probe deck existed this run had a measured output power and no efficiency
at all.  These tests keep the two numbers tied to the raw that produced them:
the parameters must be the candidate's (not the mother deck's), the output
power must agree with the independent operating-point extraction, and the
closure status must stay ``NOT_CLOSED`` -- a 0.2 W residual on a 22-period
window is not evidence that the ledger closes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "design/v3/power_priority/energy_ledger_48v_110a.json"
OP = ROOT / "design/v3/power_priority/operating_point_48v_110a.json"
PROBE_LOG = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110_cin.log"
PLAIN_LOG = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110.log"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_ledger_ran_the_candidates_parameters_not_the_mother_decks():
    """48 V / 18.9 mOhm inherited from the 100 A deck would invent a loss."""
    d = load(LEDGER)
    # ``port`` is the only block that records the pair; the window is the
    # 22 gate periods of a Tstart-rebased axis (display 880 us = raw 0 us).
    assert d["port"]["vin_v"] == pytest.approx(48.0)
    assert d["port"]["rl_ohm"] == pytest.approx(0.0169)
    assert d["raw"]["path"].endswith("ss_1ms_vin48_i110_cin.raw")
    assert d["window"]["periods"] == 22
    assert d["window"]["raw_time_start_s"] == pytest.approx(880e-6)
    assert d["window"]["end_s"] < 120e-6


def test_the_output_power_agrees_with_the_independent_extraction():
    """Two tools, one raw: the window and RL are the only things that can drift."""
    ledger = load(LEDGER)["port"]["pout_w"]
    op = load(OP)["pout_w"]
    assert ledger == pytest.approx(op, rel=1e-4)


def test_efficiency_is_two_measured_ports_and_not_a_budget():
    d = load(LEDGER)
    pin = d["port"]["pin_source_w"]
    pout = d["port"]["pout_w"]
    assert d["efficiency"]["port_pct"] == pytest.approx(100.0 * pout / pin, rel=1e-9)
    # The published 92.33 % is a different quantity (core estimate, 0.15 mOhm
    # output path, bias).  If someone overwrote port_pct with it, the ratio
    # above would no longer hold -- this is the guard that they stay separate.
    assert d["efficiency"]["port_pct"] > 92.33 + 1.0


def test_the_probe_circuit_is_the_candidate_circuit():
    """The two decks differ by a .save block; the .meas results must not move."""
    def measurements(path: Path) -> dict[str, str]:
        found = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if ": " in line and "=" in line and " FROM " in line:
                key = line.split(":", 1)[0]
                found[key] = line.split("=", 1)[1].split(" FROM ")[0].strip()
        return found

    probe = measurements(PROBE_LOG)
    plain = measurements(PLAIN_LOG)
    shared = set(probe) & set(plain)
    assert {"vout_avg", "vout_rip", "ipri_pk", "ifwd_a1", "irev_a1"} <= shared
    for key in shared:
        assert probe[key] == plain[key], key


def test_the_closure_is_reported_as_not_closed():
    """A mean inside 0.2 W on this window is not a demonstration of closure.

    The tool's own resolution block says the window resolves the target only
    to about 2*sem; it must therefore publish NOT_CLOSED rather than a green
    check, and the reason string must name the reading that failed.
    """
    d = load(LEDGER)
    balance = d["balance"]
    assert balance["closure_status"] == "NOT_CLOSED"
    assert abs(balance["closure_residual_w"]) > balance["target_w"]
    # The window has to resolve the target for NOT_CLOSED to mean anything:
    # a window too noisy to see 0.2 W could not report a 0.56 W miss either.
    assert d["results"]["window_resolves_0p2_w_period_averaged"] is True
    averaged = balance["period_averaged"]
    assert averaged["periods"] < d["window"]["periods"]     # one whole period per end
    assert abs(averaged["closure_residual_w"]) > balance["target_w"]
    assert balance["limits"]                                # the miss is published, not hidden
    assert d["checks"]["ok"] is True          # no invariant was bent to get here
    assert d["results"]["closure_including_storage_within_0p2_w"] is False
