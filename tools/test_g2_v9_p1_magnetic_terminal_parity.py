"""Real native V9 vs source-validated P1 pad-parity safety regression."""
from __future__ import annotations

import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
G2=ROOT/"hardware/dcx_main/g2"
sys.path.insert(0,str(G2))
import audit_v9_p1_terminal_parity as P


def test_report_stable_with_saved_cad_and_independent_gui_reopen():
    r=P.report()
    assert r==json.loads(P.OUT.read_text("utf8"))
    assert P.sha(P.PCB)==r["v9_source_native_sha256"]==P.NATIVE_SHA
    assert r["p1_schematic_refs"]==83
    assert r["p1_schematic_wires"]==280
    assert r["p1_refs_with_matching_real_pcb_component"]==77
    assert r["p1_connected_pin_net_matches"]==259
    assert r["p1_connected_pin_net_disagreements"]==[]
    assert r["p1_reference_missing_native_components"]==["CT","R6","T1","T2","T3","T4"]
    assert r["native_drc_connection_errors"]==168
    assert r["native_drc_netlist_errors"]==1


def test_magnetic_physical_pad_24_is_not_native_device_or_factory_release():
    r=P.report()
    rows=r["magnetics_bare_pad_to_component_assignments"]
    assert len(rows)==24
    assert {(x["ref"],x["terminal"]) for x in rows}=={
        (ref,pin) for ref,nets in r["magnetics_required_pin_nets"].items()
        for pin in nets
    }
    assert all(x["net"]==r["magnetics_required_pin_nets"][x["ref"]][x["terminal"]]
               for x in rows)
    assert all(x["component_owned"] is False for x in rows)
    assert all(x["terminal_dot_signed"] is False for x in rows)
    assert r["magnetics_native_component_instances"]==0
    assert r["magnetic_vendor_terminal_geometry_and_dot_approved"] is False
    assert r["native_new_component_save_and_independent_reopen_verified"] is False
    assert r["fabrication_approved"] is False


def test_r6_is_real_design_reference_but_missing_native_component():
    r=P.report()
    assert r["r6_required_pin_nets"]=={"2":"RUN","1":"VCC12"}
    assert r["r6_native_component_present"] is False
    assert r["r6_real_mpn_footprint_and_position_approved"] is False


def test_native_cout72_all_144_pcb_pin_net_assignments_are_real():
    native,_,_=P.source()
    seen={}
    for p in native["pads"]:
        if p.get("ref") in P.CHB:
            seen.setdefault(p["ref"],{})[str(p["PadNumber"])]=p["Net"]
    assert len(seen)==72
    assert all(pins=={"1":"VOUT","2":"PGND"} for pins in seen.values())


def test_wrong_source_sha_or_unsupported_pcb_component_rejected(tmp_path,monkeypatch):
    bogus=tmp_path/"synthetic.eprj2"
    bogus.write_bytes(b"none of this is a real native CAD")
    monkeypatch.setattr(P,"PCB",bogus)
    with pytest.raises(ValueError,match="saved V9 PCB bytes changed"):
        P.source()


def test_bad_terminal_net_rejected(tmp_path,monkeypatch):
    native=json.loads(P.NATIVE.read_text("utf8"))
    q=next(x for x in native["value"]["pads"] if not x.get("ref"))
    assert q["Net"]=="PRI_T1"
    q["Net"]="PGND"
    bad=tmp_path/"bad_readback.json"
    bad.write_text(json.dumps(native),encoding="utf8")
    monkeypatch.setattr(P,"NATIVE",bad)
    with pytest.raises(ValueError,match="Bare magnetic pad cannot be matched"):
        P.report()
