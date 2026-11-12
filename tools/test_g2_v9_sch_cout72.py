"""Check 72 native schematic/PCB devices really exist in one saved V9 CAD."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
G2=ROOT/"hardware/dcx_main/g2"
sys.path.insert(0,str(G2))
import g2_v9_real_t530_components as PCB
import g2_v9_sch_cout72 as SCH


def receipt(name):
    return json.loads((G2/name).read_text(encoding="utf8"))


def test_native_schematic_COUT72_has_all_72_linked_components_and_144_net_wires():
    d=receipt("g2_v9_sch_cout72_native_checkpoint_NOT_FOR_FAB.json")
    assert d["native_schematic_cap_count"]==72
    assert d["native_named_chb_count"]==72
    assert d["native_schematic_wire_count"]==144
    assert d["native_page"]=="4de189e79beba629"
    assert d["issues"]==[]
    assert d["fabrication_approved"] is False


def test_six_native_batch_receipts_and_frozen_bounded_layout():
    ranges=[(2,13),(14,25),(26,37),(38,49),(50,61),(62,72)]
    covered={1}
    for start,end in ranges:
        data=receipt(f"g2_v9_sch_chb_{start:02d}_{end:02d}_NOT_FOR_FAB.json")
        assert [data["first"],data["last"]]==[start,end]
        assert data["gui_kept_open"] is True
        assert data["fabrication_approved"] is False
        assert data["reply"]["ok"] is True
        value=data["reply"]["value"]
        assert value["complete"] and value["requested"]==end-start+1
        assert all(r["ok"] for r in value["report"])
        covered.update(int(v["ref"][-2:]) for v in value["report"])
    assert covered==set(range(1,73))
    coords=SCH.rows()
    assert len(coords)==72
    assert len(set((r["x"],r["y"]) for r in coords))==72


def test_final_native_cap_symbol_pcb_parity_is_source_bound():
    p=receipt("g2_v9_native_72_cout_schematic_pcb_pin_parity_NOT_FOR_FAB.json")
    assert p["candidate_sha256"]==PCB.sha(PCB.V9)
    assert p["schematic_sheet"]=="COUT_T530_72"
    assert p["schematic_72_parts"]==p["pcb_72_parts"]==72
    assert p["schematic_pin_number_pair_per_part"]==["1","2"]
    assert p["pcb_1_vout_2_pgnd_verified"]
    assert p["schematic_wires_144_names"]
    assert p["no_other_devices_certified"]
    assert p["fabrication_approved"] is False


def test_final_PCB_native_DRC_still_has_real_open_connections():
    r=receipt("g2_v9_schematic_cap72_native_drc.json")
    assert r["drc_categories"]=={"Connection Error":170,"Netlist Error":1}
    assert r["physical_error_count"]==0
    assert r["pcb_release"] is False


def test_saved_page_evidence_and_prior_V9_stage_are_not_conflated():
    d=receipt("g2_v9_schematic_cout72_save_evidence.json")
    assert d["native_save_sch_p1"]
    assert d["native_save_sch_cout72"]
    assert d["native_save_pcb"]
    assert d["actual_72_schematic_parts_with_144_named_net_wires"]
    assert d["actual_72_pcb_parts_and_144_linked_pads"]
    assert d["gui_remains_visible"]
    assert d["fab_approved"] is False
    # The disk source can be re-serialized after native save; final parity
    # binds the current exact eprj2 sha, while this receipt is historical.
    assert d["source_v8_sha256"]==PCB.sha(PCB.V8)


def test_schematic_automation_never_manages_GUI_lifecycle():
    src=Path(SCH.__file__).read_text(encoding="utf8")
    assert "build_open_args" not in src
    assert "build_close_args" not in src
    assert "session\", \"close" not in src
    assert "pcb_PrimitivePad.delete" not in src
