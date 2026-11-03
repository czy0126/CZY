"""Detect anything besides a controlled numerical .options change in PROT03 diagnostics."""
from pathlib import Path
import json
import pytest
import generate_prot03_solver_sweep as m
def test_all_twelve_generated_variants_are_current():
    assert len(m.plan()["records"])==12
    assert len({a["generated_deck"] for a in m.plan()["records"]})==12
    for label,val in m.VARIANTS.items():
        for case,src in m.SOURCE.items():
            expected=m.build(label,case)
            actual=m.filename(label,case).read_text(encoding="utf-8")
            assert actual==expected
            original=(m.SIM/src).read_text(encoding="utf-8")
            assert actual[len(m.HEADER):].replace("cshunt="+val,"cshunt=1e-15")==original
            assert original.count(m.ANCHOR)==1
    assert json.loads(m.RESULT.read_text(encoding="utf-8"))==m.plan()
    assert all(x["simulation_state"]=="UNRUN" for x in m.plan()["records"])
    assert m.plan()["not_for_fab"]
@pytest.mark.parametrize("wrong",["NOCASE","A_CONTROLL"])
def test_unknown_cases_fail_fast(wrong):
    with pytest.raises(ValueError):m.build("shunt_2f",wrong)
