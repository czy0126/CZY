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
    assert r["final_hardware_permit_interlock"]["external_estop_contact_physically_tested"] is False


def test_final_and_gate_requires_both_external_permissions():
    parts=c.candidate_parts()
    c.verify_candidate(parts)
    units={p.unit:p.nets for p in parts if p.ref=="U20"}
    assert units[1]=={"1":"PERMIT_INTERNAL","2":"ESTOP_OK","3":"PERMIT_ESTOP"}
    assert units[2]=={"4":"PERMIT","5":"PERMIT_ESTOP","6":"HS_MON_OK"}
    for internal in (0,1):
        for estop in (0,1):
            for monitor in (0,1):
                assert (internal & estop & monitor)==(1 if internal and estop and monitor else 0)
    ps={p.ref:p for p in parts}
    for ref in ("R112","R113","R114"):
        assert ps[ref].nets["2"]=="PGND" and ps[ref].value=="10k"


@pytest.mark.parametrize("ref,pin,net",[
    ("U20","2","V5"),("U20","6","V5"),("J11","2","V5"),
    ("J12","2","V5"),("R112","2","V5"),("R113","2","V5"),
    ("R114","2","V5"),("R33","1","PERMIT_INTERNAL")])
def test_external_interlock_bypass_is_rejected(ref,pin,net):
    parts=c.candidate_parts()
    modified=[replace(p,nets={**p.nets,pin:net}) if p.ref==ref and pin in p.nets else p for p in parts]
    with pytest.raises(ValueError):
        c.verify_candidate(modified)


def test_legacy_u8_direct_permit_is_rejected():
    parts=c.candidate_parts()
    modified=[replace(p,nets={**p.nets,"10":"PERMIT"}) if p.ref=="U8" and "10" in p.nets else p for p in parts]
    with pytest.raises(ValueError,match="internal permit"):
        c.verify_candidate(modified)
