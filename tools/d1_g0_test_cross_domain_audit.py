"""G0 independent source netlist and fail-closed isolation audit."""
from __future__ import annotations
import sys
import json
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import d1_g0_cross_domain_audit as a

def test_actual_native_board_witnesses_fundamentally_common_ground():
    report=json.loads(a.REPORT.read_text("utf-8"))
    rows=list(__import__("csv").DictReader(a.MIGRATE.open(encoding="utf-8",newline="")))
    domains=report["physical_return_domains"]
    assert domains["shared_primary_secondary_return_nets"]==["PGND"]
    assert domains["isolation_domain_split_complete"] is False
    assert any(z["copper_layer"]=="In1.Cu" and z["net"]=="PGND" for z in report["shared_pgnd_plane_evidence"])
    assert report["SR_driver_supply_bonded_to_primary_pgnd"] is True
    assert report["hardware_48v_powerup_allowed"] is False
    assert len(rows)>=100

def test_independent_design_source_found_missing_run_enable():
    report=json.loads(a.REPORT.read_text("utf-8"))
    c=report["independent_circuit"]
    assert c["missing_required_peripheral"]==["R8"]
    assert c["R8_intended_nets"]=={"1":"VCC12","2":"RUN"}
    assert c["R8_must_be_DNP_until_hardware_permit_validated"] is True
    assert c["intentionally_extra_output_bulk_capacitors"]==72

def test_independent_domain_manifest_has_audit_passport_sha():
    report=json.loads(a.REPORT.read_text("utf-8"))
    assert report["secondary_eco_csv_sha256"]==a.sha(a.MIGRATE)
    assert report["board_sha256"]==a.sha(a.BOARD)

def test_unsafe_shared_ground_or_missed_t4_ground_is_negative():
    a_report=json.loads(a.REPORT.read_text("utf-8"))
    assert a_report["primary_T4_PRI_B_must_STAY_primary_return"] is True
    refs={
      **{ref:{pin:"PGND" for pin in pins} for ref,pins in a.PRIMARY_GROUND_WITNESS.items()},
      **{ref:{pin:"PGND" for pin in pins} for ref,pins in a.SECONDARY_RET_REFS.items()}
    }
    r=a.audited_domains(refs)
    assert not r["isolation_domain_split_complete"]
    for ref,pin,bad in (("U3","2","VIN_P"),("J_OUT","2","VIN_P"),("T4","PRI_B",a.SRET)):
        mutated={k:dict(v) for k,v in refs.items()}
        mutated[ref][pin]=bad
        with pytest.raises(ValueError):
            a.audited_domains(mutated)

def test_hypothetically_separate_nets_require_the_correct_renaming():
    refs={
      **{ref:{pin:"PRIMARY_RETURN" for pin in pins} for ref,pins in a.PRIMARY_GROUND_WITNESS.items()},
      **{ref:{pin:a.SRET for pin in pins} for ref,pins in a.SECONDARY_RET_REFS.items()}
    }
    assert a.audited_domains(refs)["isolation_domain_split_complete"] is True
    refs["Cout"]["2"]="PRIMARY_RETURN"
    with pytest.raises(ValueError):
        a.audited_domains(refs)
