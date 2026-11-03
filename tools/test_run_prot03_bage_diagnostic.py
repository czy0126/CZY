"""Bage numerical-experiment runner must fail closed before any external solver."""
import json
from pathlib import Path
import pytest
import run_prot03_bage_diagnostic as r
import generate_prot03_bage_diagnostic as g

def test_no_solver_called_in_default_dry_run(capsys):
    assert r.main([])==0
    output=capsys.readouterr().out
    assert output.count("DRY_RUN")==2
    assert "NOT_APPROVED" in output

def test_generator_is_the_only_allowed_source_of_both_decks():
    assert set(r.validate("shunt_2f"))=={"B_CONTROL","B_CANDIDATE"}
    assert set(r.validate("published"))=={"B_CONTROL","B_CANDIDATE"}
    assert g.NEW.read_text(encoding="utf-8")==g.model_content()

def test_unvalidated_runner_rejects_modified_model(tmp_path,monkeypatch):
    model=tmp_path/"bad_model.lib"
    model.write_text(g.model_content()+"\n* undocumented change",encoding="utf-8")
    monkeypatch.setattr(g,"NEW",model)
    with pytest.raises(ValueError,match="model"):
        r.validate("shunt_2f")

def test_unvalidated_runner_rejects_modified_deck(tmp_path,monkeypatch):
    dest=tmp_path/"wrong.cir"
    dest.write_text("NOT THE SAME CIRCUIT",encoding="utf-8")
    monkeypatch.setattr(g,"deck_path",lambda v,role:dest if role=="B_CONTROL" else
                        g.SIM/f"d1_prot03_agefix_{v}_{role}.cir")
    with pytest.raises(ValueError,match="deck"):
        r.validate("shunt_2f")

def test_manifest_approval_is_hardcoded_false():
    content=(Path(__file__).resolve().parent/"run_prot03_bage_diagnostic.py").read_text(encoding="utf-8")
    assert '"both_320us_qualified":False' in content
    assert '"fabrication_approved":False' in content
    assert 'run.run_case' in content
    assert 'Refuse overwrite Bage diagnostic archive' in content
