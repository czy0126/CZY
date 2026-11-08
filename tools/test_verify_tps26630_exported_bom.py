"""Numerical KiCad references and physical BOM scope validated from CSV."""
import csv
from pathlib import Path
import pytest
import verify_tps26630_exported_bom as m


def valid_csv(path: Path):
    refs=["U1","Q1","Q2","R1","R2","R3","R4","R5","R6","C1","C2","J1","J2","J3"]
    with path.open("w",encoding="utf-8",newline="") as f:
        out=csv.DictWriter(f,fieldnames=["Refs","Value","Footprint","Qty","DNP"])
        out.writeheader()
        for ref in refs:
            out.writerow({
                "Refs":ref, "Value":m.EXPECTED_IC.get(ref,"test"),
                "Footprint":"Package_TO_SOT_SMD:SOT-23" if ref=="Q2" else "",
                "Qty":"1","DNP":""
            })


def test_valid_native_bom_is_draft_not_qualified(tmp_path):
    f=tmp_path/"bom.csv"
    valid_csv(f)
    d=m.verify(f)
    assert d["exported_bom_rows"]==14
    assert d["unannotated_refs"]==0
    assert not d["fabrication_approved"] and not d["U1_Q1_physical_footprints_assigned"]


def test_question_mark_reference_fails_closed(tmp_path):
    f=tmp_path/"bom.csv"
    valid_csv(f)
    text=f.read_text().replace("R1,test","R1?,test")
    f.write_text(text)
    with pytest.raises(ValueError,match="unannotated"):
        m.verify(f)


def test_vendor_mpn_swap_cannot_pass_even_when_erc_is_clean(tmp_path):
    f=tmp_path/"bom.csv"
    valid_csv(f)
    text=f.read_text().replace("CSD19537Q3T","SOMETHING_UNVERIFIED")
    f.write_text(text)
    with pytest.raises(ValueError,match="Q1"):
        m.verify(f)


def test_early_physical_footprint_assignment_must_be_independently_reviewed(tmp_path):
    f=tmp_path/"bom.csv"
    valid_csv(f)
    text=f.read_text().replace("U1,TPS26630RGET,,","U1,TPS26630RGET,Package_DFN_QFN:Guess,")
    f.write_text(text)
    with pytest.raises(ValueError,match="footprint"):
        m.verify(f)
