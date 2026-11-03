"""Read-only 61-ref CAD ECO is faithful to native export."""
import csv
import io
import vendor_native_cad_eco as x

def rows(): return list(csv.DictReader(io.StringIO(x.generate())))

def test_native_ecos_cover_all_placeholder_refs_and_keep_everything_unapproved():
    r=rows()
    assert len(r)==61 and len({x["ref"] for x in r})==61
    assert all(v["ecad_status"]=="NOT_APPLIED_NOT_ERC_VERIFIED" for v in r)
    assert sum(bool(v["candidate_mpn"]) for v in r)==51
    assert all(v["native_pad_net_pair"] for v in r)

def test_r3_package_and_control_pin_values_are_not_silently_misapplied():
    r={q["ref"]:q for q in rows()}
    assert r["R3"]["native_footprint"]=="R0603"
    assert r["R3"]["candidate_eia_case"]=="2512"
    assert r["R3"]["required_eda_change"]=="REPLACE_NATIVE_FOOTPRINT_AND_PART_AND_CHECK_NETS"
    assert r["R1"]["native_pad_net_pair"]=="1:DT;2:PGND"
    assert r["R1"]["candidate_nominal"].startswith("5.36 kohm")
    assert r["R2"]["native_pad_net_pair"]=="1:RT;2:PGND"
    assert r["R2"]["candidate_nominal"].startswith("976 ohm")
    assert r["C101"]["nominal_value_match"]=="NO"
    assert r["C7"]["nominal_value_match"]=="NO"
    assert r["C5"]["footprint_eia_match"]=="NO"
    assert not r["CT"]["candidate_mpn"]

def test_record_is_identical_to_regenerated():
    assert x.OUTPUT.read_text(encoding="utf-8")==x.generate()
