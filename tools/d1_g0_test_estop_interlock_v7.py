"""G0 V7 interlock CAD and reset-latch truth tests, not an energized contactor."""
from __future__ import annotations
import ast,sys,json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"tools/d1_g0_estop_interlock_v7.py"
OUTPUT=ROOT/"hardware/dcx_main/g2/d1_g0_ESTOP_INTERLOCK_V7_NOT_FOR_FAB"
REPORT=OUTPUT/"V7_hardware_stop_and_restart_contract_NOT_FOR_FAB.json"
SCH_REPORT=OUTPUT/"V7_source_authored_real_pin_interlock_schematic_NOT_FOR_FAB.json"
def literal(name):
    module=ast.parse(SRC.read_text(encoding="utf-8"))
    for stmt in module.body:
        if isinstance(stmt,ast.Assign) and any(isinstance(x,ast.Name) and x.id==name for x in stmt.targets):
            return ast.literal_eval(stmt.value)
    raise LookupError(name)
PARTS=literal("PARTS")
DS=literal("DS")
def report():return json.loads(REPORT.read_text("utf-8"))
def pins(ref):return PARTS[ref][3]

def logic_step(q,prev_arm,p,s,hs,e_mon,manual_arm,nc_coil_closed=True,coil_48v_present=True):
    """Deterministic functional specification, not dynamic SPICE or safety proof."""
    all_ok=bool(p and s and hs and e_mon)
    if not all_ok:q=False
    elif bool(manual_arm) and not bool(prev_arm):q=True
    coil=bool(all_ok and q and nc_coil_closed and coil_48v_present)
    return (q, bool(manual_arm), coil)

def test_independent_PIN_source_27_refs_81_vendor_indexes():
    assert len(PARTS)==27
    assert json.loads(SCH_REPORT.read_text("utf-8"))["independent_ref_pin_net_parity"]==81
    assert json.loads(SCH_REPORT.read_text("utf-8"))["native_KiCad_ERC_violations"]==0

def test_HARD_NC_power_loop_requires_external_stop_closed_no_bypass():
    assert pins("J_AUX48")=={"1":"VIN48_AUX","2":"PGND"}
    assert pins("F_COIL")=={"1":"VIN48_AUX","2":"48V_FUSED"}
    assert pins("J_ESTOP_PWR")=={"1":"48V_FUSED","2":"48V_AFTER_ESTOP"}
    assert pins("J_GX14COIL")=={"1":"48V_AFTER_ESTOP","2":"COIL_DRAIN"}
    assert pins("Q_COIL")=={"1":"MOS_GATE","2":"COIL_DRAIN","3":"PGND"}
    # Two different net numbers on each side of J_ESTOP_PWR are never
    # automatically tied by PCB; a real NC mechanical series contact is needed.
    assert pins("J_ESTOP_PWR")["1"]!=pins("J_ESTOP_PWR")["2"]

def test_4081_and_4013_REAL_TI_pinouts_and_reset_gate():
    a=pins("U_AND");r=pins("U_LATCH")
    assert a=={"1":"UVLO_P_OK","2":"UVLO_S_PRIMARY_OK","3":"BIAS_BOTH_OK",
      "4":"EXT_BOTH_OK","5":"HS_OK_IN","6":"ESTOP_MON_OK","7":"PGND",
      "8":"BIAS_BOTH_OK","9":"EXT_BOTH_OK","10":"ALL_HEALTHY",
      "11":"COIL_ENABLE","12":"LATCH_Q","13":"ALL_HEALTHY","14":"VCC12"}
    assert r["1"]=="LATCH_Q" and r["3"]=="ARM_CLOCK"
    assert r["4"]=="RESET_ACTIVE" and r["5"]=="VCC12"
    assert r["6"]==r["7"]==r["8"]==r["9"]==r["10"]==r["11"]=="PGND"
    assert r["12"]==r["13"]==""
    assert pins("Q_RESET")=={"1":"RESET_BASE","2":"PGND","3":"RESET_ACTIVE"}
    assert pins("R_RESET_B")=={"1":"ALL_HEALTHY","2":"RESET_BASE"}
    assert pins("R_RESET_PULL")=={"1":"VCC12","2":"RESET_ACTIVE"}
    assert pins("R_GATE")=={"1":"COIL_ENABLE","2":"MOS_GATE"}
    assert pins("R_GATE_OFF")=={"1":"MOS_GATE","2":"PGND"}

@pytest.mark.parametrize("p,s,hs,estop",[
 (p,s,h,e) for p in (False,True) for s in (False,True)
 for h in (False,True) for e in (False,True)])
def test_ALL_false_or_missing_supervisor_or_estop_monitor_defaults_COIL_OFF(p,s,hs,estop):
    # A healthy previously armed coil *must* be turned off immediately on a
    # single lost status. If all healthy the coil may remain energized.
    q,clock,coil=logic_step(True,False,p,s,hs,estop,False)
    assert coil==bool(p and s and hs and estop)
    if not all((p,s,hs,estop)):assert q is False

def test_fault_recovery_NEVER_auto_restarts_even_if_arm_switch_held():
    q,a,coil=logic_step(False,False,True,True,True,True,True)
    assert q and coil
    q,a,coil=logic_step(q,a,True,False,True,True,True)
    assert not q and not coil
    q,a,coil=logic_step(q,a,True,True,True,True,True)
    assert not q and not coil # still held: no new rising START clock
    q,a,coil=logic_step(q,a,True,True,True,True,False)
    assert not coil
    q,a,coil=logic_step(q,a,True,True,True,True,True)
    assert coil

def test_NC_power_break_dominates_stuck_electronics_on():
    q,a,coil=logic_step(True,True,True,True,True,True,True,nc_coil_closed=False)
    assert not coil
    q,a,coil=logic_step(True,True,True,True,True,True,True,coil_48v_present=False)
    assert not coil
    assert DS["GX14"].startswith("https://www.sensata.com/")

def test_optical_uvlo_and_HS_detection_are_EXTERNAL_unverified_blockers():
    report_=report()
    assert report_["native_footprints"]==27
    assert report_["actual_high_side_monitor_installed"] is False
    assert report_["actual_GX14_contactor_and_2NC_emergency_stop_switch_integrated_on_board"] is False
    assert report_["physical_signoff_g0"] is False
    assert report_["energization_allowed"] is False
    assert report_["fabrication_approved"] is False

def test_no_incorrect_external_48V_GX14_coil_suppression_diode():
    assert not any("COIL_DRAIN" in p[3].values() and p[0]=="zener"
                   for p in PARTS.values())
    assert pins("D_GS")=={"1":"MOS_GATE","2":"PGND"}
