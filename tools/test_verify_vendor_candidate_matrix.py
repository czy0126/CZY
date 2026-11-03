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
    assert parts[links["R1"]]["mpn"]=="ERJ3EKF9760V"
    assert parts[links["R2"]]["mpn"]=="ERJ3EKF5361V"
    assert parts[links["R3"]]["eia_case"]=="0805"
    assert parts[links["C5"]]["eia_case"]=="0805"
    assert parts[links["C101"]]["nominal"].startswith("1 uF")
    assert parts[links["C102"]]["nominal"].startswith("100 nF")
    assert parts[links["C7"]]["voltage_v"]>=25
