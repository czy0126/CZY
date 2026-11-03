"""One-line Bage experimental change only; fully paired circuit/topology unchanged."""
import json
import math
import pytest
import generate_prot03_bage_diagnostic as m

def test_exactly_one_semantic_model_change():
    before=m.ORIGINAL.read_text(encoding="utf-8")
    new=m.NEW.read_text(encoding="utf-8")
    assert new==m.model_content()
    assert new[len(m.HEADER):].replace(m.REVISED,m.OLD)==before
    assert new.count(m.REVISED)==1
    assert new.count(m.OLD)==0
    assert "Bton ton" in new and "Btoff toff" in new
    assert "V(age,S)>BON*1e6" in new

@pytest.mark.parametrize("variant",tuple(m.ROLE_FILES))
@pytest.mark.parametrize("role",("B_CONTROL","B_CANDIDATE"))
def test_pair_identical_model_and_unchanged_fault_circuit(variant,role):
    new=m.deck_path(variant,role).read_text(encoding="utf-8")
    before=(m.SIM/m.ROLE_FILES[variant][role]).read_text(encoding="utf-8")
    assert new==m.deck_content(variant,role)
    assert new[len(m.DECK_HEADER):].replace(m.INCLUDE_NEW,m.INCLUDE_OLD)==before
    assert new.count(m.INCLUDE_NEW)==1
    assert ".options plotwinsize=0 method=gear cshunt="+("1e-15" if variant=="published" else "2e-15") in new

def test_railing_smooths_where_hard_discontinuity_was():
    # LTE Jacobian slope switches smoothly over the 9.9..10 range; below
    # 9.9V it is exactly the original -1mA timer drive. Age=0.475V decision.
    def current(a):
        return -1e-3*min(1.,max(0.,(10.-a)/.1))
    for age in (0,.475,3,9.89):
        assert current(age)==pytest.approx(-1e-3)
    assert current(9.95)==pytest.approx(-.0005)
    assert current(10)==0
    assert current(10.05)==0
    assert abs(current(9.999999)-current(10.000001))<1e-8
    assert abs(current(9.899999)-current(9.900001))<1e-8

def test_record_never_claims_the_experiment_was_run():
    report=m.plan()
    assert json.loads(m.OUT.read_text(encoding="utf-8"))==report
    assert len(report["records"])==4
    assert all(x["execution_state"]=="UNRUN" and not x["both_320us_qualified"] for x in report["records"])
    assert not report["fabrication_approved"]
