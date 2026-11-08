"""Native KiCad XML netlist export validator does not trust original labels."""
import csv
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree
import pytest
import verify_tps26630_exported_netlist as mod


def fake_netlist(path: Path, incorrect=None, connect_nc=False):
    root = Element("export")
    nets = SubElement(root, "nets")
    entries = {}
    with mod.PINMAP.open(encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f):
            pin = "25" if (r["ref"],r["pad"]) == ("U1","EP") else r["pad"]
            label = r["net"]
            if incorrect == (r["ref"],pin):
                label = "WRONG_NET"
            if label in ("NC","FLOAT"):
                if connect_nc and (r["ref"],pin)==("U1","19"):
                    label = "VDD_SR"
                else:
                    continue
            entries.setdefault(label,[]).append((r["ref"],pin))
    for label,pairs in entries.items():
        net=SubElement(nets,"net",name=label)
        for ref,pin in pairs:
            SubElement(net,"node",ref=ref,pin=pin)
    ElementTree(root).write(path,encoding="utf-8")


def test_all_36_pinmap_assignments_and_ep_alias_checked(tmp_path):
    f=tmp_path/"pass.xml"
    fake_netlist(f)
    d=mod.verify(f)
    assert d["OEM_pin_assignments_checked"]==36
    assert not d["hardware_qualified"] and not d["fabrication_approved"]


def test_actual_wrong_mosfet_pin_cannot_pass_even_if_label_source_ok(tmp_path):
    f=tmp_path/"wrong.xml"
    fake_netlist(f,incorrect=("Q1","5"))
    with pytest.raises(ValueError,match="Q1"):
        mod.verify(f)


def test_no_connect_ended_up_on_power_rail_fails_closed(tmp_path):
    f=tmp_path/"short.xml"
    fake_netlist(f,connect_nc=True)
    with pytest.raises(ValueError,match="U1"):
        mod.verify(f)


def test_invalid_export_no_nets_is_not_valid_evidence(tmp_path):
    f=tmp_path/"empty.xml"
    f.write_text("<export></export>",encoding="utf-8")
    with pytest.raises(ValueError,match="no net"):
        mod.verify(f)
