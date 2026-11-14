"""Lane C corrected HS prototype, negative tests on unsafe topologies."""
from dataclasses import replace
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import d1_lane_c_hs_candidate as c

def test_hs_is_always_sw_not_pgnd():
    ps=c.candidate_parts()
    c.verify_candidate(ps)
    by={p.ref:p for p in ps}
    assert by["U18"].nets["5"]=="SW"
    assert all(by[r].nets["2"]=="SW" for r in ("C29","R64","C40"))
    assert by["C29"].value=="220nF/25V"
    assert by["R20"].nets["1"]=="V12P_F" and by["R22"].nets["1"]=="V12S_F"
    assert by["R21"].value=="10k" and by["R23"].value=="10k"
    assert by["C14"].value=="1nF/50V" and by["C15"].value=="1nF/50V"
    assert by["R110"].value==by["R111"].value=="1M"
    assert by["C114"].value==by["C115"].value=="22uF/25V"

def test_absolute_floating_gate_detector_must_be_dnp():
    ps=c.candidate_parts()
    by={p.ref:p for p in ps}
    assert by["R74"].dnp and by["D17"].dnp
    assert by["R45"].dnp

@pytest.mark.parametrize("ref,pin,value",[
    ("U18","5","PGND"),("C29","2","PGND"),("R64","2","PGND"),
    ("C40","2","PGND"),("U18","9","SW")])
def test_ground_reference_regression_rejected(ref,pin,value):
    ps=c.candidate_parts()
    modified=[replace(p,nets={**p.nets,pin:value}) if p.ref==ref else p for p in ps]
    with pytest.raises(ValueError):
        c.verify_candidate(modified)

@pytest.mark.parametrize("ref",["D17","R74","R45"])
def test_unsafe_population_rejected(ref):
    ps=c.candidate_parts()
    modified=[replace(p,dnp=False) if p.ref==ref else p for p in ps]
    with pytest.raises(ValueError):
        c.verify_candidate(modified)

def test_actual_native_kicad_export_matches_all_declared_pins():
    parts,_,text=c.expected_text()
    r=c.check_native(parts,text)
    assert r["netlist_pins_checked"]>450
    assert r["native_erc_violations"]==0
    assert r["uvlo_nominal"]["rising_threshold_v"]==11.1
    assert r["uvlo_nominal"]["falling_threshold_v"]==10.6
    assert r["uvlo_nominal"]["hold_up_dc_bias_and_esr_verified"] is False
    assert r["bench_primary_secondary_bias_ground_tied"] is True
    assert r["isolated_production_bias_power_verified"] is False
    assert r["output_bom_sha256"]
    assert r["g0_approved"] is False
    assert r["energization_allowed"] is False
