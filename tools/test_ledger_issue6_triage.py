from __future__ import annotations
import json
import pytest
import ledger_issue6_triage as t


def test_existing_5_2_1ns_boundary_audit_is_consistently_prioritised():
    d = t.build()
    assert d["target_w_unchanged"] == pytest.approx(0.2)
    assert d["residual_at_finest_step_w"] == pytest.approx(0.091092477096, abs=2e-4)
    assert d["status"].endswith("NOT_CLOSED")
    assert not d["canonical_ledger_closure_approved"]
    assert not d["numerical_step_convergence_approved"]
    assert d["important_uncertainty"]["body_diode_forward_loss_across_step_w"] > 1.0


def test_checked_in_diagnostic_is_reproducible():
    assert json.loads(t.OUT.read_text(encoding="utf-8")) == t.build()
