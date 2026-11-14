"""Two-domain 48V to 12V isolated bias concept cannot silently share PGND."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import d1_lane_c_bias_supply_candidate as b

def test_secondary_return_and_pin_map():
    ps=b.parts()
    b.verify(ps)
    by={x.ref:x for x in ps if not x.ref.startswith("#")}
    assert by["U2"].nets["5"]=="SR_SOURCE_RETURN"
    assert by["U2"].nets["5"]!=by["U2"].nets["2"]
    assert by["U1"].nets["5"]=="PGND"
    assert b.PINS["3"]=="+Vout" and b.PINS["5"]=="-Vout"

@pytest.mark.parametrize("ref,pin,bad",[
  ("U2","5","PGND"),("J3","2","PGND"),("C3","2","PGND"),
  ("U1","5","SR_SOURCE_RETURN"),("U2","2","SR_SOURCE_RETURN"),
  ("U1","1","VIN48_RAW"),("U2","1","VIN48_RAW"),
  ("F1","2","VIN48S_F"),("F2","2","VIN48P_F"),
  ("U2","3","V12P_IN"),
])
def test_wiring_mutation_rejected(ref,pin,bad):
    ps=[replace(x,nets={**x.nets,pin:bad}) if x.ref==ref else x for x in b.parts()]
    with pytest.raises(ValueError):
        b.verify(ps)

def test_generated_native_kicad_and_bom():
    ps,_,text=b.expected()
    report=b.check(ps,text)
    assert report["native_pin_parity"]>20
    assert report["native_erc_violations"]==0
    assert report["secondary_supply_ground_separate_in_native_netlist"] is True
    assert report["module_footprint_qualified"] is False
    assert report["48v_power_disconnect_integrated"] is False
    assert report["g0_approved"] is False and report["energization_allowed"] is False
