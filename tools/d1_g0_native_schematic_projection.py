"""Reconstruct KiCad editable G0 net-labelled schematic from native PCB pad data.

Important: this is a *reverse projection* of the PCB, NOT independent native
schematic/PCB authority, vendor symbols, a functioning protection circuit, or
manufacturer-qualified footprints. Its purpose is a single editable reference
for a 154-device low-power integration review.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import make_d0_protection_board as k
import d1_g0_integrated_native_board as board_mod
import d1_g0_router_trial as router
import pcbnew as pcb

OUT=board_mod.OUT
FINAL_STEM="d1_g0_integrated_mainboard_ELECTRICAL_NOT_FOR_FAB"
SCHEM=OUT/(FINAL_STEM+".kicad_sch")
SYMLIB=OUT/"G0LogicalMainboard.kicad_sym"
LIBTABLE=OUT/"sym-lib-table"
REPORT=OUT/"g0_full_schematic_pin_parity_NOT_FOR_FAB.json"

def pin_name(ref, pad):
    name=pad.GetNumber()
    return name

def state_parts(source_board=None, expected_parts=154):
    path=router.BOARD if source_board is None else Path(source_board)
    if not path.is_file():raise ValueError("G0 native trial PCB missing")
    if source_board is None:
        r=router.check()
        if r["violations"]!=0 or r["unconnected"]!=0:
            raise ValueError("Native full G0 trial must have zero DRC and zero open nets before projection")
    b=pcb.LoadBoard(str(path))
    original={f.GetReference():f for f in b.GetFootprints()}
    if len(original)!=expected_parts or len(original)!=len(b.GetFootprints()):
        raise ValueError(f"expected {expected_parts} unique PCB footprint references")
    ordered=sorted(original, key=lambda x:(0 if x in ("J_IN","Cin","QH","QL","Cr","Lr","CT","T1","T2","T3","T4",
                                                  "U1","U2","U3","U4","U5","U6","J_OUT","Cout") else 1,x))
    parts=[]; symbols={}; native={}
    for i,ref in enumerate(ordered):
        fp=original[ref]
        pins={}
        for pad in fp.Pads():
            num=pin_name(ref,pad)
            net=pad.GetNetname()
            if num in pins and pins[num]!=net:
                raise ValueError("Multiple pads with same package number on different nets "+ref+"."+num)
            pins[num]=net if net else k.NC
        if not pins:raise ValueError("footprint has no pads "+ref)
        native[ref]=pins
        n=len(pins); per=(n+1)//2
        pin_defs=[]
        # The symbol pin NUMBER, including alphanumeric magnetic logical pins,
        # stays exactly equal to original native PCB pad.GetNumber().
        for j,num in enumerate(sorted(pins)):
            side_left=j<per
            sub=j if side_left else j-per
            y=7.62-2.54*sub
            if sub>6:raise ValueError("symbol pin capacity exceeded "+ref)
            pin_defs.append(k.Pin(num,num,-13.97 if side_left else 13.97,
                                  y,0 if side_left else 180,"passive"))
        lib="G0LogicalMainboard:"+ref
        symbols[lib]=k.custom_symbol(lib,pin_defs,22.86,25.4,"U" if ref.startswith("U") else "J" if ref.startswith("J") else "T" if ref.startswith("T") else "R",
                                      "")
        col=i%12;row=i//12
        parts.append(k.snap(k.Part(ref,lib,
                            "LOGICAL_PAD_PROJECTION_NOT_REAL_SYMBOL", "", 25+46*col,35+27*row,
                            pins,source="PCB_SOURCE_PADS_ONLY",note="PCB PAD->SHEET MIRROR; NO independent design signoff")))
    return parts,symbols,native

# k.instance expects decimal pin numbers; magnetic logical pins are PRI_A/CTAP.
# Keep them literal in the KiCad symbol and UUID so we never assign arbitrary
# vendor terminal numbers.
def instance_any(part, symbols, labels, no_connects):
    positions=k.pin_tip_positions(part,symbols)
    x,y=k.origin(part)
    on_board="yes"
    esc=lambda t:t.replace("\\","\\\\").replace('"','\\"')
    lines=[
      "\t(symbol",
      f'\t\t(lib_id "{part.lib}")',
      f"\t\t(at {x:g} {y:g} 0)",
      f"\t\t(unit {part.unit}) (body_style 1)",
      ("\t\t(exclude_from_sim no) (in_bom no) (dnp yes) (on_board yes) (in_pos_files no)"
        if part.ref=="R8" else
        "\t\t(exclude_from_sim no) (in_bom yes) (on_board yes) (in_pos_files yes)"),
      f'\t\t(uuid "{k.uid(part.ref,str(part.unit),"symbol")}")',
      f'\t\t(property "Reference" "{part.ref}" (at {x:g} {y-12:g} 0) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
      f'\t\t(property "Value" "{esc(part.value)}" (at {x:g} {y+12:g} 0) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
      f'\t\t(property "Footprint" "" (at {x:g} {y:g} 0) (hide yes) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
      f'\t\t(property "Datasheet" "" (at {x:g} {y:g} 0) (hide yes) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
      f'\t\t(property "Description" "{esc(part.note)}" (at {x:g} {y:g} 0) (hide yes) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))'
    ]
    for num in sorted(part.nets):
        lines.append(f'\t\t(pin "{num}" (uuid "{k.uid(part.ref,str(part.unit),num)}"))')
    lines.append("\t)")
    for num,net in part.nets.items():
        ax,ay=positions[num]
        u=k.uid(part.ref,str(part.unit),num,"label")
        if net==k.NC:
            no_connects.append(f'\t(no_connect (at {ax:g} {ay:g}) (uuid "{u}"))')
        else:
            labels.append(f'\t(label "{esc(net)}" (at {ax:g} {ay:g} 0) (effects (font (size 1.016 1.016))) (uuid "{u}"))')
    return "\n".join(lines)

def expected(parts,symbols):
    k.validate(parts,symbols)
    previous=k.instance
    try:
        k.instance=instance_any
        sch=k.schematic(symbols,parts)
    finally:k.instance=previous
    return sch.replace("D0 ten-gate protection logic bench board",
                       "G0 154-package netlist projection NOT FOR FAB").replace(
      "Bench logic board. NOT for fabrication. Not a power stage, not thermal, not timing.",
      "DERIVED FROM PCB ONLY; no independent circuit authority or magnetics OEM footprint")

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def write():
    parts,symbols,pins=state_parts()
    schem=expected(parts,symbols)
    SCHEM.write_text(schem,encoding="utf-8")
    library=['(kicad_symbol_lib (version 20241209) (generator "g0_logical_projection")']
    for symbol in symbols.values():
        library.append(symbol.replace('(symbol "G0LogicalMainboard:', '(symbol "',1))
    library.append(")")
    SYMLIB.write_text("\n".join(library)+"\n",encoding="utf-8")
    uri="$"+"{KIPRJMOD}"+"/"+SYMLIB.name
    LIBTABLE.write_text('(sym_lib_table\n\t(version 7)\n\t(lib (name "G0LogicalMainboard")(type "KiCad")(uri "'+uri+'")(options "")(descr ""))\n)\n',encoding="utf-8")
    return parts,pins

def report(parts,pins):
    native_sha=sha(router.BOARD)
    return {
      "kind":"G0_COMPLETE_PCB_PAD_NET_PROJECTION_KICAD_SCH",
      "status":"SOURCE_NET_MIRROR_NOT_REAL_ELECTRICAL_SCHEMATIC",
      "device_count":len(parts),"native_board_sha256":native_sha,
      "original_mainboard_devices":149,"magnetics_logical_trial_devices":5,
      "by_reference_pad_net":pins,
      "pin_count":sum(len(x) for x in pins.values()),
      "sch_sha256":sha(SCHEM),
      "local_symbol_lib_sha256":sha(SYMLIB),
      "is_independently_authored_functional_schematic":False,
      "is_schematic_footprint_vendor_authorized":False,
      "is_48v_12v_bias_integrated":False,
      "pcb_full_drc_clean":False,
      "hardware_approved":False,
      "fabrication_approved":False,
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    opts=ap.parse_args()
    if opts.write:
        parts,pins=write()
        REPORT.write_text(json.dumps(report(parts,pins),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    else:
        if any(not x.is_file() for x in (SCHEM,REPORT,SYMLIB,LIBTABLE)):
            raise ValueError("Missing native projected schematic/symbol library")
        parts,symbols,pins=state_parts()
        if SCHEM.read_text("utf-8")!=expected(parts,symbols):
            raise ValueError("schematic is not the exact PCB-pad mirror")
        if json.loads(REPORT.read_text("utf-8"))!=report(parts,pins):
            raise ValueError("native schematic parity stale")
    print(json.dumps({"status":"NOT_FOR_FAB_154_DEVICE_KICAD_PAD_PROJECTION",
          "devices":len(pins),"package_pins":sum(map(len,pins.values()))},ensure_ascii=False))
if __name__=="__main__":main()
