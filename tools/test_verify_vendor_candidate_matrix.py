"""Ensure manufacturer-candidate overlay cannot become a fake signed BOM."""
import csv
import io
import json
import verify_vendor_candidate_matrix as x

def test_all_refdes_covered_exactly_once_and_no_approvals():
    rows=list(csv.DictReader(io.StringIO(x.render())))
    assert len(rows)==61
    assert len({row["ref"] for row in rows})==61
    assert all(row["candidate_only"]=="YES" and row["native_eda_verified"]=="NO" and row["application_approved"]=="NO" for row in rows)
    assert all(row["official_source_url"] and row["candidate_mpn"] for row in rows if row["part_exists"]=="YES_OFFICIAL_MPN")
    assert not any(row["candidate_mpn"] for row in rows if row["ref"] in {"T1","T2","T3","T4","CT","Lr","D_BT","Cin","Cout","Cr"})

def test_committed_matrix_is_current():
    assert x.MATRIX.read_text(encoding="utf-8")==x.render()

def test_known_critical_values_and_native_approval_is_absent():
    parts=json.loads(x.CATALOG.read_text(encoding="utf-8"))
    links=json.loads(x.ASSIGN.read_text(encoding="utf-8"))
    assert parts[links["R1"]]["mpn"]=="ERJ3EKF5361V"
    assert parts[links["R2"]]["mpn"]=="ERJ3EKF9760V"
    assert parts[links["R3"]]["eia_case"]=="2512"
    assert parts[links["R3"]]["mpn"]=="CRCW251210R0FKEHHP"
    assert x.r3_minimum_rating(parts,links,json.loads(x.BURDEN.read_text(encoding="utf-8")))["pulse_validation"]=="OPEN"
    assert parts["R10_0805"]["design_status"].startswith("REJECTED")
    assert parts[links["C5"]]["eia_case"]=="0805"
    assert parts[links["C101"]]["nominal"].startswith("1 uF")
    assert parts[links["C102"]]["nominal"].startswith("100 nF")
    assert parts[links["C7"]]["voltage_v"]>=25


def test_r3_rejects_old_0805_and_no_regression_to_limited_power():
    from copy import deepcopy
    parts=json.loads(x.CATALOG.read_text(encoding="utf-8"))
    assign=json.loads(x.ASSIGN.read_text(encoding="utf-8"))
    burden=json.loads(x.BURDEN.read_text(encoding="utf-8"))
    assign["R3"]="R10_0805"
    import pytest
    with pytest.raises(ValueError,match="unsafe"):
        x.r3_minimum_rating(parts,assign,burden)
    assign["R3"]="R10_2512_HP"
    low=deepcopy(parts)
    low["R10_2512_HP"]["rated_power_w"]=0.1
    with pytest.raises(ValueError,match="unsafe"):
        x.r3_minimum_rating(low,assign,burden)


def test_r3_screen_record_cannot_forge_a_fab_approval():
    report=json.loads(x.R3_SCREEN.read_text(encoding="utf-8"))
    assert report["candidate_mpn"]=="CRCW251210R0FKEHHP"
    assert report["source_rating_status"]=="REJECTED_120A"
    assert report["max_model_pre_fault_w"]>0.125
    assert report["candidate_rating_power_w"]/report["max_model_pre_fault_w"]>10
    assert not report["pcb_footprint_verified"]
    assert not report["hardware_approved"]
    assert not report["fabrication_release_approved"]
