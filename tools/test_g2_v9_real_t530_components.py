"""V9 real KEMET native PCB parts: source-locked readback & one-shot receipts."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
G2 = ROOT / "hardware/dcx_main/g2"
sys.path.insert(0, str(G2))
import g2_v9_real_t530_components as C


def load(path):
    return json.loads(path.read_text(encoding="utf8"))


def test_v9_saved_real_72_pcb_board_and_source_identity():
    r = load(G2 / "g2_v9_72_native_devices_save_evidence.json")
    assert r["native_save"] is True
    assert r["72_real_pcb_footprint_instances"] is True
    assert r["72_schematic_symbols_added"] is False
    assert r["fab_approved"] is False
    # Historical PCB-only save predates the added native Cout schematic page.
    assert r["candidate_sha256"] != C.sha(C.V9)
    assert r["v8_sha256"] == C.sha(C.V8) == C.EXPECTED_V8_SHA
    # The immutable Cout SCH/PCB parity receipt refers to the *pre-feeder*
    # CAD revision. The newest source-locked native feeder receipt owns V9.
    import g2_v9_vout_source_feeder_pilot as FEEDER
    assert FEEDER.CANDIDATE_SHA == load(G2 / "g2_v9_native_72_cout_schematic_pcb_pin_parity_NOT_FOR_FAB.json")["candidate_sha256"]
    assert C.sha(C.V9) == load(FEEDER.VERIFY_RECEIPT)["source_sha256"]
    assert r["candidate_sha256"] != r["v8_sha256"]


def test_g2_72_parts_all_verified_before_save_and_no_unresolved_items():
    r = load(C.CHECKPOINT)
    assert r["native_capacitors_verified"] == 72
    assert r["problems"] == []
    assert r["components"] == 149
    assert r["pads"] == 443
    assert r["lines"] == 403
    assert r["vias"] == 90
    assert r["networks"] == 65
    assert r["100A_main_copper_qualified"] is False
    assert r["native_schematic_symbol_instances_verified"] is False
    assert r["manufacturing_approved"] is False


def test_native_drc_keeps_original_170_connections_without_physical_violations():
    r = load(G2 / "g2_v9_real_t530_72_native_drc.json")
    assert r["status"] == "REAL_NATIVE_DRC_V9_CAP72_NOT_FOR_FAB"
    assert r["native_category"] == {"Connection Error": 170, "Netlist Error": 1}
    # Historic V9 PCB-only DRC: schematic edits subsequently changed file hash.
    assert r["source_hash_after_read"] != C.sha(C.V9)
    assert load(G2 / "g2_v9_schematic_cap72_native_drc.json")["drc_categories"] == r["native_category"]
    assert r["fabrication_approved"] is False


def test_each_native_replacement_one_shot_and_both_pins_net_bound():
    receipts = [
        (2, 9, False), (3, 9, True),
        (10, 21, True), (22, 33, True), (34, 45, True),
        (46, 57, True), (58, 69, True), (70, 72, True)
    ]
    certified = set([1])  # CHB01 placed, net-assigned, original pads removed in pilot.
    for start, end, complete in receipts:
        r = load(G2 / f"g2_v9_chb_{start:02d}_{end:02d}_native_NOT_FOR_FAB.json")
        assert r["range"] == [start, end]
        assert r["gui_left_open"] is True and r["fabrication_approved"] is False
        assert r["reply"]["ok"] is True
        value = r["reply"]["value"]
        assert value["complete"] is complete
        successful = [row for row in value["report"] if row["ok"]]
        assert all(row["pins"] == {"1": "VOUT", "2": "PGND"} for row in successful)
        assert all(row["deleted_bare"] == 2 for row in successful)
        for row in successful:
            certified.add(int(row["ref"].removeprefix("CHB")))
    assert certified == set(range(1, 73))


def test_frozen_geometry_and_recoverable_batch_writer_do_not_shutdown_gui():
    plan = load(C.PLAN)
    assert plan["placement_count"] == 72
    assert len(plan["placement"]) == 72
    text = Path(C.__file__).read_text(encoding="utf8")
    assert "pcb_PrimitiveComponent.create" in text
    assert "pcb_PrimitivePad.modify" in text
    assert "pcb_PrimitivePad.delete" in text
    assert "pcb_Document.save" not in text  # saving is separately acknowledged
    assert "build_close_args" not in text
    assert "['stop']" not in text




def test_exported_device_symbol_and_footprint_are_source_locked():
    r = load(G2 / "t530_x1_real_device_association_NOT_FOR_FAB.json")
    assert r["native_device_uuid"] == C.DEVICE
    assert r["native_footprint_uuid"] == "c9bdf53e779d4dd6a2eee1e6cecd4462"
    assert r["native_symbol_uuid"] == "5652f930fe894ea781b22cdf204e03a9"
    sym = G2 / r["symbol_source"]
    footprint = G2 / r["footprint_source"]
    # Archived native symbol/footprint streams have Git LF byte identity.
    # Windows autocrlf does not constitute a CAD edit; any other edit must fail.
    for source, expected in ((sym, r["symbol_sha256"]),
                             (footprint, r["footprint_sha256"])):
        raw = source.read_bytes()
        assert b"\x00" not in raw
        canonical = raw.replace(b"\r\n", b"\n")
        assert b"\r" not in canonical
        assert hashlib.sha256(canonical).hexdigest() == expected
        assert hashlib.sha256(canonical + b"tamper").hexdigest() != expected
    symbols = []
    for row in sym.read_text(encoding="utf8").splitlines():
        if "||" not in row:
            continue
        a,b = row.split("||",1)
        h = json.loads(a)
        d = json.loads(b.rstrip("|"))
        if h["type"] == "ATTR" and d.get("key") == "Pin Number":
            symbols.append(d.get("value"))
    assert sorted(symbols) == ["1", "2"]
    assert r["actual_72_pcb_components_verified"]
    assert r["72_native_schematic_instances_present"] is False
    assert r["polarized_symbol_graphics_signed_off"] is False
    assert r["manufacturer_land_and_courtyard_approved"] is False
    assert r["fabrication_approved"] is False

def test_cannot_fabricate_source_hash_identity(monkeypatch):
    monkeypatch.setattr(C, "sha", lambda path: "incorrect")
    with pytest.raises(ValueError, match="V8 source changed"):
        C.plan()
