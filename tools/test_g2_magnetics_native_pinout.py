"""Source-bound genuine EasyEDA PCB/SCH 24-terminal net parity and stopline tests."""
from __future__ import annotations
from pathlib import Path
import json
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import g2_magnetics_native_pinout as P
import g2_magnetics_netlist_gap as G


def native_pads(path):
    data=path.read_text("utf8")
    found=[]
    for line in data.splitlines():
        head,other=line.split("||",1)
        info=json.loads(head)
        payload=json.loads(other.split("|",1)[0])
        if info.get("type")=="PAD":
            found.append(payload)
    return found


def test_24_real_native_sch_to_pcb_electrical_connections_not_vendor_pinout():
    doc=P.make()
    assert doc["real_electrical_pin_count"]==24
    assert doc["real_PCB_unassociated_magnetic_landing_pads"]==24
    assert doc["vendor_mechanical_pin_numbers_confirmed"]==0
    assert doc["vendor_winding_DOT_confirmed"]==0
    assert doc["not_a_supplier_signed_pinout"] is True
    assert doc["fabrication_approved"] is False
    assert doc["status"]=="24_OF_24_NATIVE_SCHEMATIC_AND_RAW_PCB_LANDING_NETS_MATCH_VENDOR_REQUEST_NOT_FOR_FAB"
    assert len(doc["pin_rows"])==24
    assert {x["reference"] for x in doc["pin_rows"]}=={"T1","T2","T3","T4","CT"}
    assert all(x["native_schematic_net"]==x["native_PCB_raw_pad_net"] for x in doc["pin_rows"])
    assert all(x["vendor_physical_pin_number"] is None and x["manufacturer_pinout_signed"] is False for x in doc["pin_rows"])
    assert all(x["winding_first_article_polarity_passed"] is False for x in doc["pin_rows"])
    for ref in ("T1","T2","T3","T4"):
        p=[x for x in doc["pin_rows"] if x["reference"]==ref]
        assert len(p)==5
        assert set(x["logical_terminal"] for x in p)==set(P.T_ORDER)
        assert next(x for x in p if x["logical_terminal"]=="CTAP")["native_schematic_net"]=="VOUT"
    assert len([x for x in doc["pin_rows"] if x["reference"]=="CT"])==4


def test_generated_native_efoo_footprints_are_real_pad_format_not_vendor_mechanicals():
    content=P.deliverables()
    assert set(content)=={P.MANIFEST,P.TABLE,P.T_FOOT,P.CT_FOOT}
    for file,b in content.items():
        assert file.read_text("utf8")==b
    t=native_pads(P.T_FOOT)
    ct=native_pads(P.CT_FOOT)
    assert len(t)==5 and len(ct)==4
    assert {x["num"] for x in t}==set(P.T_ORDER)
    assert {x["num"] for x in ct}==set(P.CT_ORDER)
    for pad in t+ct:
        assert pad["layerId"]==1
        assert pad["netName"]==""
        assert pad["defaultPad"]=={"padType":"ELLIPSE","width":78.7,"height":78.7,"radius":0}
    assert P.T_FOOT.name.endswith("_NOT_FOR_FAB.efoo")
    assert P.CT_FOOT.name.endswith("_NOT_FOR_FAB.efoo")


def test_four_transformers_share_same_measured_native_pad_pattern():
    d=P.make()
    for ref in ("T2","T3","T4"):
        a=d["devices"]["T1"]["design_logical_pins"]
        b=d["devices"][ref]["design_logical_pins"]
        for x,y in zip(a,b):
            assert x["logical_terminal"]==y["logical_terminal"]
            assert abs(x["trial_pad_local_center_mm"][0]-y["trial_pad_local_center_mm"][0])<.002
            assert abs(x["trial_pad_local_center_mm"][1]-y["trial_pad_local_center_mm"][1])<.002


def test_netlist_real_P1_83_plus_COUT72_minus_R6_DNP_and_five_missing_magnetics_is_149():
    d=G.build()
    assert d==json.loads(G.EVIDENCE.read_text("utf8"))
    assert d["schematic_P1_component_count"]==83
    assert d["schematic_COUT_T530_72_component_count"]==72
    assert d["schematic_combined_component_count"]==155
    assert d["intentional_R6_DNP"]==1
    assert d["missing_native_magnetic_device_count"]==5
    assert d["actual_saved_native_PCB_component_count"]==149
    assert d["actual_EDA_PCB_netlist_component_count"]==149
    assert set(d["absent_from_native_PCB_relative_to_P1"])=={"CT","R6","T1","T2","T3","T4"}
    assert set(d["missing_real_magnetics_sch_footprint_associations"])=={"CT","T1","T2","T3","T4"}
    assert d["native_netlist_Error_existing"]==1
    assert d["native_netlist_Error_clearance_proven"] is False
    assert d["fabrication_approved"] is False


def test_tampered_vendor_request_physical_id_must_fail_closed(monkeypatch,tmp_path):
    v=json.loads(P.VENDOR.read_text("utf8"))
    v["devices"][0]["pins"][0]["vendor_physical_terminal_id"]="1"
    f=tmp_path/"fake_vendor_id.json"
    f.write_text(json.dumps(v),encoding="utf8")
    monkeypatch.setattr(P,"VENDOR",f)
    with pytest.raises(ValueError,match="newly vendor-numbered drawing"):
        P.make()


def test_tampered_native_board_inventory_fails_closed(monkeypatch,tmp_path):
    b=json.loads(G.PCB.read_text("utf8"))
    b["real_native_data"]["components"].pop()
    f=tmp_path/"fake_board.json"
    f.write_text(json.dumps(b),encoding="utf8")
    monkeypatch.setattr(G,"PCB",f)
    with pytest.raises(ValueError,match="readback not source bound"):
        G.build()


def test_reexport_is_deterministic_and_supplier_unverified():
    for path,content in P.deliverables().items():
        assert path.read_text("utf8")==content
    assert G.EVIDENCE.read_text("utf8")==json.dumps(G.build(),ensure_ascii=False,indent=2)+"\n"
