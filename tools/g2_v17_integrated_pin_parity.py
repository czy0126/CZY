"""Audit actual saved V17 KiCad pads against the archived V15 native pad map.

Use KiCad's bundled Python, NOT ordinary Python:
  C:/Users/27792/AppData/Local/Programs/KiCad/10.0/bin/python.exe \
    tools/g2_v17_integrated_pin_parity.py

This verifies ref/pin/net parity for all imported OEM pad identities and the
explicit J_OUT eight-contact expansion. It does NOT establish P1 SCH-PCB
parity or substitute for physical T1..T4/CT coil terminals.
"""
from __future__ import annotations
import collections
import hashlib
import json
from pathlib import Path
import pcbnew as pcb

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
BOARD=G/"dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb"
SOURCE=G/"dcx_main_board_g2_V15_T4_POWER_CELL_UP30MM_WIP_NOT_FOR_FAB.eprj2"
V15=G/"g2_v15_after_T4_move_native_readback_NOT_FOR_FAB.json"
DRC=G/"g2_v17_KICAD_NATIVE_DRC_NOT_FOR_FAB.json"
META=G/"g2_v17_real_kicad_native_build_NOT_FOR_FAB.json"
OUT=G/"g2_v17_integrated_native_pin_parity_NOT_FOR_FAB.json"
SLOTS=G/"g2_five_magnetics_24_logical_pin_native_parity_NOT_FOR_FAB.json"
V15_SHA="02d59c63c747678849466cc62565c1522bc50586a7dadc06b0829016ab601e75"

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def generate():
    if sha(SOURCE)!=V15_SHA:raise ValueError("Frozen V15 binary changed")
    n=json.loads(V15.read_text("utf8"))["native"]
    d=json.loads(DRC.read_text("utf8"))
    m=json.loads(META.read_text("utf8"))
    if sha(BOARD)!=m["saved_board_sha256"]:
        raise ValueError("Saved KiCad PCB SHA does not match build receipt")
    board=pcb.LoadBoard(str(BOARD))
    footprints=list(board.GetFootprints())
    fpmap={fp.GetReference():fp for fp in footprints}
    if len(fpmap)!=len(footprints):raise ValueError("Duplicate component ref")
    old_byref=collections.defaultdict(collections.Counter)
    for pad in n["pads"]:
        if pad["ref"]:
            old_byref[pad["ref"]][(str(pad["PadNumber"]),pad["Net"])]+=1
    new_byref={}
    for fp in footprints:
        refs=collections.Counter((pad.GetNumber(),pad.GetNetname()) for pad in fp.Pads())
        new_byref[fp.GetReference()]=refs
    if len(old_byref)!=149 or len(new_byref)!=149:
        raise ValueError("149 native component references not preserved")
    failures={ref:{"expected":list(old_byref[ref].items()),
                  "actual":list(new_byref[ref].items())}
              for ref in old_byref if ref!="J_OUT" and old_byref[ref]!=new_byref.get(ref)}
    if failures:raise ValueError(f"Old component ref/net/pin drift {str(failures)[:1000]}")
    if old_byref["J_OUT"]!=collections.Counter({("1","VOUT"):1,("2","PGND"):1}):
        raise ValueError("Original schematic output terminal net/pad count unexpected")
    if new_byref["J_OUT"]!=collections.Counter({("1","VOUT"):4,("2","PGND"):4}):
        raise ValueError("Trial J_OUT is not four real contacts per pole")
    native_pads=sum(len(fp.Pads()) for fp in footprints)
    if native_pads!=425:raise ValueError("425 pad count changed")
    j=fpmap["J_OUT"]
    contacts=collections.defaultdict(list)
    for pad in j.Pads():
        position=pad.GetPosition()
        x,y=pcb.ToMM(position.x),pcb.ToMM(position.y)
        contacts[pad.GetNetname()].append((round(x,3),round(y,3)))
        if not isinstance(pad,pcb.PAD) or pad.GetAttribute()!=pcb.PAD_ATTRIB_PTH:
            raise ValueError("Output contact not native PTH")
        drill=pcb.ToMM(pad.GetDrillSize().x)
        if abs(drill-3.2)>.001:raise ValueError("Output PTH hole is not 3.2mm")
    expected_positions={
      "VOUT":{(70.,78.),(70.,87.),(70.,96.),(70.,105.)},
      "PGND":{(82.,78.),(82.,87.),(82.,96.),(82.,105.)}
    }
    if {net:set(positions) for net,positions in contacts.items()}!=expected_positions:
        raise ValueError("Contact XY/SCH pads changed unexpectedly")
    u2=fpmap["U2"]
    for num in range(1,11):
        q=next(p for p in u2.Pads() if p.GetNumber()==str(num))
        y=pcb.ToMM(q.GetPosition().y)
        origin=next(c for c in n["components"] if c["ref"]=="U2")
        # 54,18 mm is the source-locked V17 placement.
        nominal=18+(num-3 if num<=5 else 8-num)*.5
        if abs(y-nominal)>.0001:raise ValueError("U2 OEM 0.5mm pitch drift")
    try:
        coils=json.loads(SLOTS.read_text("utf8"))
        logical=coils.get("devices",{})
        missing_coils=["CT","T1","T2","T3","T4"]
        missing_logic=sum(len(logical[ref]["design_logical_pins"])
                          for ref in missing_coils if ref in logical)
    except (FileNotFoundError,KeyError):
        missing_coils=["CT","T1","T2","T3","T4"]
        missing_logic=None
    if any(ref in fpmap for ref in missing_coils):
        raise ValueError("Unexpected magnetic physical pads; redo netlist parity")
    zones=collections.Counter((zone.GetNetname(),board.GetLayerName(zone.GetLayer()))
                              for zone in board.Zones())
    layers=board.GetCopperLayerCount()
    for pair in [("VOUT","In5.Cu"),("PGND","In6.Cu"),
                 ("VOUT","In7.Cu"),("PGND","In8.Cu")]:
        if zones[pair]!=1:raise ValueError("Missing paired inner copper "+str(pair))
    if (len(d["violations"])!=0 or len(d["unconnected_items"])!=9):
        raise ValueError("Native DRC changed; recheck before parity signoff")
    payload={
       "status":"NATIVE_RECONSTRUCTED_V15_PAD_IDENTITIES_AND_J_OUT_TRIAL_VERIFIED_NOT_FOR_FAB",
       "native_v15_sha256":sha(SOURCE),
       "native_V17_kicad_sha256":sha(BOARD),
       "native_V17_drc_sha256":sha(DRC),
       "kicad_version":pcb.Version(),
       "preserved_source_component_refs":149,
       "all_148_unchanged_footprints_identical_pin_number_and_net_multiset":True,
       "original_archived_pad_count":419,
       "actual_KiCad_pad_count":native_pads,
       "J_OUT_old_per_pole_pads":1,
       "J_OUT_new_per_pole_pads":4,
       "J_OUT_contacts_xy_mm":{net:[list(x) for x in coords]
                               for net,coords in contacts.items()},
       "unlike_net_short_DRC":0,
       "native_DRC_rule_violations":0,
       "native_unconnected_items":9,
       "kicad_real_copper_layer_count":layers,
       "copper_zone_count":len(board.Zones()),
       "critical_paired_power_planes":{f"{net}@{layer}":zones[(net,layer)]
                                        for net,layer in [("VOUT","In5.Cu"),
                                                          ("PGND","In6.Cu"),
                                                          ("VOUT","In7.Cu"),
                                                          ("PGND","In8.Cu")]},
       "missing_real_physical_magnetics":missing_coils,
       "unverified_missing_magnetic_logical_pin_count":missing_logic,
       "source_U2_nominal_pitch_verified":True,
       "real_full_P1_SCH_to_PCB_netlist_parity_verified":False,
       "OEM_manufacturing_footprints_signed":False,
       "8_contact_current_rating_and_coldplate_mount_verified":False,
       "thermal_EMI_3D_and_100A_verified":False,
       "board_release":False
    }
    OUT.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps({k:payload[k] for k in (
        "status","preserved_source_component_refs","actual_KiCad_pad_count",
        "native_DRC_rule_violations","native_unconnected_items",
        "copper_zone_count","missing_real_physical_magnetics")},ensure_ascii=True))
    return payload

if __name__=="__main__":
    generate()
