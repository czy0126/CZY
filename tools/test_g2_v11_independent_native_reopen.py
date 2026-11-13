"""V11 is actual saved/reopened native PCB, not a geometry-only suggestion."""
from __future__ import annotations
from pathlib import Path
import json
import sys
import pytest
G2=Path(__file__).resolve().parents[1]/"hardware/dcx_main/g2"
sys.path.insert(0,str(G2))
import g2_v11_eight_sr_gate_escape as V
import g2_v11_independent_native_reopen as AUDIT


def report():
    return json.loads(AUDIT.RECEIPT.read_text("utf8"))


def test_real_V11_saved_native_sha_and_independent_gui_proof():
    r=report()
    assert r["status"]=="V11_INDEPENDENT_NATIVE_GUI_REOPEN_AND_DRC_PASSED_NOT_FOR_FAB"
    assert r["saved_V11_native_sha256"]==V.sha(V.TARGET)
    assert V.sha(V.TARGET)!=V.SOURCE_SHA
    assert V.sha(V.SOURCE)==r["source_V10_native_sha256"]==V.SOURCE_SHA
    assert r["all_original_gui_sessions_preserved"] is True
    assert r["own_verification_GUI_closed"] is True
    assert r["V11_original_source_unchanged"] is True
    assert r["V10_parent_source_unchanged"] is True
    assert r["V11_clone_source_unchanged"] is True
    assert r["fabrication_approved"] is False
    assert r["100A_qualified"] is False


def test_native_DRC_must_be_149_connections_1_netlist_no_physical_errors():
    r=report()
    assert r["real_native_DRC"]=={"Connection Error":149,"Netlist Error":1}
    raw=json.loads(AUDIT.DRC_RAW.read_text("utf8"))
    assert raw["source_native_sha256"]==r["saved_V11_native_sha256"]
    assert raw["categories"]==r["real_native_DRC"]


def test_native_pcb_devices_and_real_72_cout_144_schematic_wire_parity():
    r=report()
    assert r["native_counts"]=={"components":149,"pads":443,"lines":465,"vias":93,"nets":65}
    assert r["COUT72_native_144_pinwire_parity"] is True
    d=json.loads(AUDIT.READBACK.read_text("utf8"))
    assert d["source_native_sha256"]==V.sha(V.TARGET)
    assert d["native_counts"]==r["native_counts"]
    assert d["all_32_new_native_trace_ids_present"] is True
    assert d["all_8_old_PGND_trace_ids_absent"] is True
    native=d["real_native_data"]
    assert len(native["components"])==149 and len(native["pads"])==443
    for c in range(1,73):
        ref=f"CHB{c:02d}"
        assert {str(p["PadNumber"]):p["Net"] for p in native["pads"] if p.get("ref")==ref}=={
            "1":"VOUT","2":"PGND"}


def test_8_actual_SR_gate_nets_not_just_offline_proposed_and_PGND_unworsened():
    r=report()
    assert r["gate_nets_closed"]==[f"G{c}{i}" for c in "AB" for i in range(1,5)]
    assert r["ground_islands_before_and_after"]==[37,37]
    d=json.loads(AUDIT.READBACK.read_text("utf8"))
    for net in r["gate_nets_closed"]:
        assert d["physical_islands_before"][net]==2
        assert d["physical_islands_after"][net]==1
    assert d["physical_islands_before"]["PGND"]==37
    assert d["physical_islands_after"]["PGND"]==37


def test_actual_autosplit_is_proven_and_original_spines_do_not_survive():
    plan=V.plan()
    old=json.loads(V.NATIVE.read_text("utf8"))["native_readback"]
    saved=json.loads(AUDIT.READBACK.read_text("utf8"))["real_native_data"]
    old_ids={x["id"] for x in old["lines"]}
    new_ids={x["id"] for x in saved["lines"]}
    assert len(old_ids)==435 and len(new_ids)==465
    gone=old_ids-new_ids
    generated=new_ids-old_ids
    inserted={x["id"] for x in json.loads(V.APPLIED.read_text("utf8"))["edit_receipt"]["wrote"]}
    assert len(gone)==17 and len(generated)==47
    assert len(plan["real_old_ground_spine_to_delete_ids"])==8
    assert set(plan["real_old_ground_spine_to_delete_ids"]).issubset(gone)
    assert len(inserted)==32 and inserted.issubset(generated)
    extra=[x for x in saved["lines"] if x["id"] in generated-inserted]
    assert len(extra)==15 and all(x["net"]=="PGND" for x in extra)


def test_tampered_parent_native_binary_rejected(tmp_path,monkeypatch):
    fake=tmp_path/"bogus.eprj2"
    fake.write_bytes(b"not a native saved source")
    monkeypatch.setattr(V,"SOURCE",fake)
    with pytest.raises(ValueError,match="SHA drift"):
        AUDIT.inputs()
