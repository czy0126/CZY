"""P0 G2 official-density 16x5 native bipolar local copper; NOT 100A rating."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"hardware/dcx_main/g2"))
import connect_t530_oem_16x5_bipolar as G
import route_t530_oem_16x5_columns as B

def _wire(name,a,b,width,net="PGND",layer=1):
    return {"id":name,"net":net,"layer":layer,
      "x1":a[0]/.0254,"y1":-a[1]/.0254,
      "x2":b[0]/.0254,"y2":-b[1]/.0254,
      "width":width/.0254}

def test_previous_copper_remains_contained_after_real_same_net_snap():
    old=_wire("old",(13.4,84.47),(13.4,96.0),1.0)
    left=_wire("old-split",(13.4,84.47),(13.4,94.0),1.0)
    right=_wire("snap",(13.58,94.0),(13.58,96.0),1.6)
    bridge=_wire("bridge",(13.4,94.0),(13.58,94.0),1.6)
    assert G.physical_copper_covers(old,[left,right,bridge],full_original_width=True)
    assert not G.physical_copper_covers(old,[left,bridge],full_original_width=True)
    bad=_wire("wrong-net",(13.58,94.0),(13.58,96.0),1.6,net="VOUT")
    assert not G.physical_copper_covers(old,[left,bad,bridge],full_original_width=True)
    bad2=_wire("gap",(13.58,95.6),(13.58,96.0),1.6)
    assert not G.physical_copper_covers(old,[left,bad2,bridge],full_original_width=True)

def test_real_16x5_bipolar_source_and_72_independent_vias_plan():
    d=G.plan()
    assert d["source_sha256"]==G.sha(B.TARGET)
    assert len(d["tracks"])==134
    assert len(d["vias"])==72
    assert d["problems"]==[]
    assert set(v["net"] for v in d["vias"])=={"VOUT"}
    assert len({tuple(v["xy_mm"]) for v in d["vias"]})==72
    assert all(v["hole_mm"]==.4 and v["diameter_mm"]==1.0 for v in d["vias"])
    assert d["all_72_vout_capacitor_pads_have_independent_via"] is True
    assert d["both_pole_local_collector_connected"] is True
    assert d["actual_oem_component_instances_present"] is False
    assert d["full_100a_busbar_and_terminals_qualified"] is False
    assert d["via_100a_thermal_rated"] is False
    assert d["fabrication_approved"] is False
    assert "pcb_PrimitiveLine.create" in G.js_tracks(d["tracks"][:2])
    assert "pcb_PrimitiveVia.create" in G.js_vias(d["vias"][:2])
    assert "pcb_Document.save" not in G.js_tracks(d["tracks"][:2])

def test_actual_saved_native_candidate_reopen_and_drc():
    assert G.TARGET.is_file(), "real candidate not saved"
    result=json.loads(G.DELTA.read_text(encoding="utf-8"))
    native=json.loads((G.HERE/(G.PREFIX+"_reopen_readback.json")).read_text(encoding="utf-8"))
    drc=json.loads((G.HERE/(G.PREFIX+"_drc_raw.json")).read_text(encoding="utf-8"))
    d=json.loads(G.PLAN.read_text(encoding="utf-8"))
    assert d==G.plan()
    assert result["status"]=="REAL_NATIVE_OEM_16X5_TWO_POLE_LOCAL_COPPER_REOPEN_NOT_FOR_FAB"
    assert result["candidate_sha256"]==G.sha(G.TARGET)
    assert result["parent_sha256"]==G.sha(G.SOURCE)
    assert result["plan_sha256"]==G.sha(G.PLAN)
    assert native["ok"] and drc["ok"]
    assert G.verify(native["value"],d)==result["readback"]
    assert G.A.R.categories(drc)==result["actual_native_drc"]
    assert result["actual_native_drc"]["Connection Error"] < 223
    assert result["actual_native_drc"].get("Physical Error",0)==0
    assert result["actual_native_drc"].get("Netlist Error",0)<=1
    assert result["readback"]["new_134_native_lines_covered"] is True
    assert result["readback"]["new_72_individual_vout_vias_reopened"]==72
    assert result["readback"]["source_lines_native_snap_normalized"]==["869575685fd74bf3"]
    assert result["continuous_100a_copper_or_busbar_qualified"] is False
    assert result["hardware_or_fabrication_approved"] is False
