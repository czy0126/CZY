"""R1/R2 false-positive clean-netlist audit: require semantic RT/DT matching."""
import csv
import json
import d1_functional_net_audit as a

def test_native_rt_dt_correct_after_semantic_ref_remap():
    r=a.compare()
    assert r["passed"],r["problems"]
    assert r["checked_nets"]==["DT","RT"]
    native=json.loads(a.EXPORT.read_text(encoding="utf-8"))["value"]["refs"]
    assert native["R1"]=={"1":"DT","2":"PGND"}
    assert native["R2"]=={"1":"RT","2":"PGND"}

def test_wrong_nominal_values_in_bom_fail_even_when_netlist_is_clean():
    with a.BOM.open(encoding="utf-8",newline="") as f:
        bom=list(csv.DictReader(f))
    for row in bom:
        if row["ref"]=="R1": row["value_or_rating"]="976 ohm; 1%"
    result=a.compare(bom_rows=bom)
    assert not result["passed"]
    assert any("BOM R1" in p for p in result["problems"])

def test_swapping_candidate_mpns_triggers_failure():
    assignments=json.loads(a.ASSIGN.read_text(encoding="utf-8"))
    assignments["R1"],assignments["R2"]=assignments["R2"],assignments["R1"]
    r=a.compare(assigned=assignments)
    assert not r["passed"]
    assert any("candidate MPN" in p for p in r["problems"])
