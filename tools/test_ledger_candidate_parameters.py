"""Candidate VIN/RL must reach *every* derived power-window statistic.

A real 48 V/120 A recording had Pin-Pout = ~13.97 W but windows[0].port_w
~56.19 W because that window reused the 100 A default RL=18.9 mOhm.
These tests use tiny arrays, not a huge .raw, and prevent recurrence.
"""
from __future__ import annotations

from array import array

import pytest

import energy_ledger_100a as ledger


def test_window_terms_uses_candidate_rl_for_the_exact_same_window(monkeypatch):
    t = array("d", [0.0, 1.0, 2.0, 3.0, 4.0])
    seen = []

    def fake_port(t, d, a, b, vin=48.0, rl=0.0189):
        seen.append((vin, rl))
        return {"pin_source_w": vin * 5.0, "pout_w": 2.0 / rl}

    monkeypatch.setattr(ledger, "port_terms", fake_port)
    monkeypatch.setattr(ledger, "loss_terms", lambda *args: {"loss": {"w": 1.0}})
    monkeypatch.setattr(ledger, "main_loss_names", lambda _: ["loss"])
    monkeypatch.setattr(ledger, "storage_terms", lambda *args, **kw: {"test": 0.0})
    monkeypatch.setattr(ledger, "driver_w", lambda *args: 0.0)

    row = ledger.window_terms(t, {}, 0, 4, arrays={}, vin=50.0, rl=0.0154)
    assert seen == [(50.0, 0.0154)]
    assert row["port_w"] == pytest.approx(250 - 2.0 / 0.0154)


def test_both_per_period_stats_use_the_candidates_load_and_input(monkeypatch):
    t = array("d", [0.0, 1.0, 2.0, 3.0, 4.0])
    seen = []

    def fake_port(t, d, a, b, vin=48.0, rl=0.0189):
        seen.append((vin, rl))
        return {"pin_source_w": vin * 5.0, "pout_w": 2.0 / rl}

    monkeypatch.setattr(ledger, "port_terms", fake_port)
    monkeypatch.setattr(ledger, "loss_terms", lambda *args: {"loss": {"w": 1.0}})
    monkeypatch.setattr(ledger, "main_loss_names", lambda _: ["loss"])
    monkeypatch.setattr(ledger, "storage_terms", lambda *args, **kw: {"test": 0.0})
    monkeypatch.setattr(ledger, "driver_w", lambda *args: 0.0)

    one = ledger.residual_noise(t, {}, [0,1,2,3,4], 0, 4, arrays={},
                                vin=50.0, rl=0.0154)
    two = ledger.averaged_residual_noise(
        t, {}, [0,1,2,3,4], 0, 4,
        arrays={"test": array("d", [0,0,0,0,0])},
        vin=50.0, rl=0.0154)
    assert len(seen) == 4 + 3
    assert set(seen) == {(50.0, 0.0154)}
    assert one["mean_w"] == pytest.approx(250 - 2.0/0.0154 - 1)
    assert two["mean_w"] == pytest.approx(one["mean_w"])


def test_saved_candidate_diagnostics_have_explicit_invalidity_notice():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for target, rl in [("110a", 0.0169), ("120a", 0.0154)]:
        d = json.loads((root / f"design/v3/power_priority/energy_ledger_48v_{target}.json").read_text(encoding="utf-8"))
        assert d["port"]["rl_ohm"] == pytest.approx(rl)
        assert d["diagnostic_integrity"]["status"] == "QUARANTINED_PRE_FIX_CANDIDATE_RL"
        assert d["balance"]["closure_status"] == "NOT_CLOSED"
        assert "windows" in d["diagnostic_integrity"]["invalid_fields"]
        # These fields were *not* rebuilt without the ignored large raw files.
        assert not d["diagnostic_integrity"]["recomputed_from_raw"]
