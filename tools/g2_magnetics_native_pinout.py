"""Build *native-format* magnetics landing-pattern footprints and exact 24-pin net passport.

This does NOT claim manufacturer-signed terminal numbering or wound core pinout.
Derive every electrical pad location/net from independently reopened native V11
PCB and actual native P1 83-component/280-wire readback, then cross-check vendor
terminal-request (which explicitly records UNKNOWN physical ids and CT DOT).
Native efoo footprints are legitimate EasyEDA format but *engineering-trial
landing patterns*, NOT certified ELP32 assembled magnetics packages.

python tools/g2_magnetics_native_pinout.py --write
python tools/g2_magnetics_native_pinout.py --check
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
G2=ROOT/"hardware/dcx_main/g2"
PCB=G2/"g2_v11_independent_native_full_readback_NOT_FOR_FAB.json"
P1=G2/"g2_v12_P1_magnetics_native_wires_24pin_readonly_NOT_FOR_FAB.json"
VENDOR=ROOT/"hardware/dcx_main/vendor_terminal_request.json"
TEMPLATE=G2/"T530X477M006ATE004_X1_DENSITY_B_NATIVE_FOOTPRINT_NOT_FOR_FAB.efoo"
SOURCE_V11_SHA="d90ca22079ad7245e8c3904eb8369da58c705ae39b56574bf7843dad34cad89b"
SOURCE_V12_SHA="527280764de6121b3a6f3eb5bbc1bac7ee72f8714e0c4be4f7a7a1f8087d1a4e"
BOARD_V11=G2/"dcx_main_board_g2_V11_NATIVE_SR_GATE_ESCAPE_NOT_FOR_FAB.eprj2"
BOARD_V12=G2/"dcx_main_board_g2_V12_NATIVE_PRIMARY_RESONANT_LINKS_NOT_FOR_FAB.eprj2"
MANIFEST=G2/"g2_five_magnetics_24_logical_pin_native_parity_NOT_FOR_FAB.json"
TABLE=G2/"g2_five_magnetics_24_terminal_vendor_signoff_PENDING.csv"
T_FOOT=G2/"DCX_T1_T4_ELP32_FIVE_LANDING_PAD_ENGINEERING_TRIAL_NOT_FOR_FAB.efoo"
CT_FOOT=G2/"DCX_CT_FOUR_LANDING_PAD_ENGINEERING_TRIAL_NOT_FOR_FAB.efoo"
T_ORDER=("PRI_A","PRI_B","SEC_A","CTAP","SEC_B")
CT_ORDER=("PRI_A","PRI_B","SEC_A","SEC_B")
REFS=("T1","T2","T3","T4","CT")
M=.0254


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_inputs():
    if sha(BOARD_V11)!=SOURCE_V11_SHA or sha(BOARD_V12)!=SOURCE_V12_SHA:
        raise ValueError("Actual native V11/V12 source SHA drift")
    a=json.loads(PCB.read_text("utf8"))
    b=json.loads(P1.read_text("utf8"))
    v=json.loads(VENDOR.read_text("utf8"))
    if (a["source_native_sha256"]!=SOURCE_V11_SHA or
        a["native_counts"]!={"components":149,"pads":443,"lines":465,"vias":93,"nets":65} or
        b["V12_saved_source_sha256"]!=SOURCE_V12_SHA or
        len(b["readback"]["devices"])!=5 or
        len(b["readback"]["wires"])!=280 or
        v["status"]!="REQUEST_FOR_VENDOR_DRAWING_AND_FIRST_ARTICLE_NOT_VERIFIED"):
        raise ValueError("Stale V11 native or live P1 schematic/vendor identity")
    return a["real_native_data"],b["readback"],v


def net_at_pin(pin,wires):
    seen=[]
    for w in wires:
        line=w["line"]
        if not isinstance(line,list) or len(line)!=4:
            continue
        if (abs(line[0]-pin["x"])<1e-5 and abs(line[1]-pin["y"])<1e-5) or (
                abs(line[2]-pin["x"])<1e-5 and abs(line[3]-pin["y"])<1e-5):
            seen.append(w["net"])
    if len(seen)!=1 or not seen[0]:
        raise ValueError("Live native P1 schematic pin has ambiguous/absent net "+str(pin)+": "+str(seen))
    return seen[0]


def make():
    board,sch,vendor=read_inputs()
    vendor_by_ref={d["ref"]:d for d in vendor["devices"]}
    sch_by_ref={d["ref"]:d for d in sch["devices"]}
    if set(vendor_by_ref)!=set(REFS) or set(sch_by_ref)!=set(REFS):
        raise ValueError("Five unique vendor/schematic magnetics expected")
    orig=[p for p in board["pads"] if not p.get("ref")]
    if len(orig)!=24:
        raise ValueError("Expected precisely 24 true native unassigned magnetic PCB pads")
    row=[];per={}
    for ref in REFS:
        dev=vendor_by_ref[ref]
        sc=sch_by_ref[ref]
        expected=CT_ORDER if ref=="CT" else T_ORDER
        if sc["footprint"]!={"uuid":""}:
            raise ValueError("Schematic already has a real native footprint: audit design first "+ref)
        if dev["vendor_name"] is not None or dev["drawing_revision"] is not None or (
           dev["real_mechanical_footprint"] is not None or dev["accepted_by_engineer"] is not False):
            raise ValueError("Vendor data changed; do not blindly keep unverified trial status")
        wanted={x["logical_terminal"]:x for x in dev["pins"]}
        actual={x["number"]:x for x in sc["pins"]}
        if set(wanted)!=set(expected) or set(actual)!=set(expected):
            raise ValueError("Native schematic/vendor terminal numbers differ for "+ref)
        # Physical trial origin is a *design landing pattern* in existing G2;
        # no claim that an OEM transformer or CT has this manufacturer drawing.
        cx,cy=((92.,52.) if ref=="CT" else
               ((20.,20.) if ref=="T1" else (58.,20.) if ref=="T2"
                else (96.,20.) if ref=="T3" else (134.,20.)))
        pins=[]
        for logical in expected:
            request=wanted[logical]
            schematic_net=net_at_pin(actual[logical],sch["wires"])
            if request["required_circuit_net"]!=schematic_net:
                raise ValueError("Schematic/OEM expected net mismatch: "+ref+"."+logical)
            # Center-tap VOUT is shared by four transformers, so a bounding-box
            # radius alone can contain TWO pads (the adjacent transformer's).
            # Select the nearest actual native pad, and insist on a distinct
            # second-place margin instead of silently declaring a wrong source.
            nearby=sorted(((math.hypot(p["X"]*M-cx,-p["Y"]*M-cy),p)
                for p in orig if str(p["PadNumber"])==logical and
                p["Net"]==schematic_net),key=lambda item:item[0])
            if not nearby or nearby[0][0]>22. or (
                    len(nearby)>1 and nearby[1][0]-nearby[0][0]<.5):
                raise ValueError("Missing/ambiguous original true PCB raw magnetic land "+ref+"."+logical)
            pad=nearby[0][1]
            x=round(pad["X"]*M,4); y=round(-pad["Y"]*M,4)
            local=[round(x-cx,4),round(y-cy,4)]
            if logical=="CTAP" and schematic_net!="VOUT":
                raise ValueError("Center tap must land at VOUT")
            if request["vendor_physical_terminal_id"] is not None or request["terminal_drawing_ref"] is not None:
                raise ValueError("Cannot treat newly vendor-numbered drawing as unverified")
            if request["test_polarity_result"] is not None or request["test_result_status"]!="NOT_TESTED":
                raise ValueError("Unknown supplier polarity evidence has changed")
            new={
                "reference":ref, "logical_terminal":logical,
                "schematic_pin_number":actual[logical]["number"],
                "native_schematic_net":schematic_net,
                "native_PCB_raw_pad_number":str(pad["PadNumber"]),
                "native_PCB_raw_pad_net":pad["Net"],
                "PCB_global_center_mm":[x,y],
                "trial_footprint_origin_mm":[cx,cy],
                "trial_pad_local_center_mm":local,
                "trial_pad_diameter_mm":round(pad["Pad"][1]*M,4),
                "design_DOT_convention":request["dot_convention_expected"],
                "vendor_physical_pin_number":None,
                "vendor_terminal_drawing_revision":None,
                "manufacturer_pinout_signed":False,
                "winding_first_article_polarity_passed":False,
            }
            pins.append(new);row.append(new)
        per[ref]={"footprint_origin_mm":[cx,cy],"design_logical_pins":pins,
            "schematic_symbol_uuid":sc["symbol"]["uuid"],
            "native_schematic_has_no_footprint_association":True}
    if len(row)!=24 or len({(x["reference"],x["logical_terminal"]) for x in row})!=24:
        raise ValueError("Not exactly 24 distinct verified logic terminals")
    occupied={(round(x["PCB_global_center_mm"][0],3),
               round(x["PCB_global_center_mm"][1],3)) for x in row}
    if len(occupied)!=24:
        raise ValueError("Two manufacturer physical lands collide")
    return {
        "schema":"G2_D1_24PIN_VENDOR_NET_AND_DOT_AUTHORITY_SPLIT_V1",
        "status":"24_OF_24_NATIVE_SCHEMATIC_AND_RAW_PCB_LANDING_NETS_MATCH_VENDOR_REQUEST_NOT_FOR_FAB",
        "source_sha256":{
            "native_V11_saved_eprj2":SOURCE_V11_SHA,
            "native_V11_independent_full_readback":sha(PCB),
            "native_V12_saved_eprj2":SOURCE_V12_SHA,
            "native_V12_actual_P1_280wire_readback":sha(P1),
            "vendor_terminal_request":sha(VENDOR),
            "native_capacitor_footprint_template":sha(TEMPLATE),
        },
        "native_schematic_page":"P1",
        "schematic_component_count":83,
        "schematic_wire_count":280,
        "real_electrical_pin_count":24,
        "real_PCB_unassociated_magnetic_landing_pads":24,
        "logical_polarity_defined_by_electrical_designer_only":True,
        "vendor_mechanical_pin_numbers_confirmed":0,
        "vendor_winding_DOT_confirmed":0,
        "prototype_footprint_and_pad_numbering_are_LOGICAL_not_manufacturer_PINs":True,
        "devices":per,
        "pin_rows":row,
        "next_hard_dependencies":[
            "OEM manufacturer mechanical terminal drawing & unique numbered physical terminal plan for T1..T4 and CT",
            "Engineer-approved physical pin number ↔ PRI_A/PRI_B/SEC_A/CTAP/SEC_B or CT PRI/SEC mapping",
            "First-article transformer turns ratio 3:1:1 and independently verified winding DOT",
            "CT selected physical core, 1:100 orientation, burden/secondary phase and galvanic isolation",
            "Use approved physical footprints to replace twenty-four raw native PCB pads with five linked native devices",
            "Native P1 schematic↔PCB netlist reconciliation, then independent PCB DRC with physical+connection+netlist errors zero",
        ],
        "fabrication_approved":False,
        "not_a_supplier_signed_pinout":True,
    }


def native_format(pattern,part_name):
    original=TEMPLATE.read_text("utf8")
    keep=[];native_pad=None
    for line in original.splitlines():
        h,p=line.split("||",1)
        head=json.loads(h)
        obj=json.loads(p.split("|")[0])
        if head["type"]=="PAD":
            native_pad=obj
            continue
        if head["type"]=="DOCHEAD":
            obj["uuid"]=hashlib.sha256(part_name.encode()).hexdigest()[:32]
            obj["version"]="ENGINEERING_TRIAL_NOT_FOR_FAB"
            obj["updateTime"]=0
            headval=head
            keep.append(json.dumps(headval,ensure_ascii=False,separators=(",",":"))+"||"+json.dumps(obj,ensure_ascii=False,separators=(",",":"))+"|")
            continue
        if head["type"]=="ATTR" and obj.get("key")=="Footprint":
            obj["value"]=part_name
            keep.append(json.dumps(head,ensure_ascii=False,separators=(",",":"))+"||"+json.dumps(obj,ensure_ascii=False,separators=(",",":"))+"|")
            continue
        keep.append(line)
    if native_pad is None:
        raise ValueError("Native EasyEDA source template has no Pad records")
    for index,(pin,x,y) in enumerate(pattern,1):
        if not pin or not isinstance(pin,str):
            raise ValueError("Missing unique logical pad name")
        h={"type":"PAD","ticket":150+index,
           "id":hashlib.sha256((part_name+"/"+pin).encode()).hexdigest()[:16]}
        obj=dict(native_pad)
        obj["num"]=pin
        obj["centerX"]=round(x/M,4)
        obj["centerY"]=round(-y/M,4)
        obj["netName"]=""
        obj["defaultPad"]={"padType":"ELLIPSE","width":78.7,"height":78.7,"radius":0}
        keep.append(json.dumps(h,ensure_ascii=False,separators=(",",":"))+"||"+json.dumps(obj,ensure_ascii=False,separators=(",",":"))+"|")
    return "\n".join(keep)+"\n"


def deliverables():
    doc=make()
    t=doc["devices"]["T1"]["design_logical_pins"]
    ct=doc["devices"]["CT"]["design_logical_pins"]
    tpat=[(r["logical_terminal"],*r["trial_pad_local_center_mm"]) for r in t]
    ctpat=[(r["logical_terminal"],*r["trial_pad_local_center_mm"]) for r in ct]
    # All four transformer footprints must share a common real-electrical
    # geometry. Any coordinate drift demands separate footprint, not a lie.
    for ref in ("T2","T3","T4"):
        got=[(r["logical_terminal"],*r["trial_pad_local_center_mm"])
             for r in doc["devices"][ref]["design_logical_pins"]]
        if any((a[0]!=b[0] or abs(a[1]-b[1])>.002 or abs(a[2]-b[2])>.002)
               for a,b in zip(tpat,got)):
            raise ValueError("T1..T4 5-pad physical geometry is not identical: "+ref)
    fp1=native_format(tpat,"CZY_D1_T1_T4_ELP32_5LOGICALPAD_ENGINEERING_TRIAL_NOT_FOR_FAB")
    fp2=native_format(ctpat,"CZY_D1_CT_4LOGICALPAD_ENGINEERING_TRIAL_NOT_FOR_FAB")
    output=io.StringIO(newline="")
    fields=["reference","logical_terminal","schematic_pin_number","native_schematic_net",
       "native_PCB_raw_pad_number","native_PCB_raw_pad_net","PCB_global_center_x_mm",
       "PCB_global_center_y_mm","design_DOT_convention",
       "vendor_physical_pin_number","vendor_terminal_drawing_revision",
       "manufacturer_pinout_signed","winding_first_article_polarity_passed"]
    writer=csv.DictWriter(output,fieldnames=fields,lineterminator="\n")
    writer.writeheader()
    for row in doc["pin_rows"]:
        val={k:row.get(k) for k in fields}
        val["PCB_global_center_x_mm"]=row["PCB_global_center_mm"][0]
        val["PCB_global_center_y_mm"]=row["PCB_global_center_mm"][1]
        writer.writerow(val)
    return {
      MANIFEST:json.dumps(doc,ensure_ascii=False,indent=2)+"\n",
      TABLE:output.getvalue(),
      T_FOOT:fp1,
      CT_FOOT:fp2,
    }


def main():
    p=argparse.ArgumentParser()
    z=p.add_mutually_exclusive_group(required=True)
    z.add_argument("--write",action="store_true")
    z.add_argument("--check",action="store_true")
    arg=p.parse_args()
    out=deliverables()
    for dest,body in out.items():
        if arg.check:
            if not dest.exists() or dest.read_text("utf8")!=body:
                raise ValueError("Native magnetic pinout/footprint artifact missing or stale: "+str(dest))
        else:
            if dest.exists() and dest.read_text("utf8")!=body:
                raise ValueError("Do not overwrite existing vendor or native footprint artifact: "+str(dest))
            dest.write_text(body,encoding="utf8",newline="\n")
    d=make()
    print(json.dumps({"status":d["status"],"native_pin_count":24,
        "native_trial_footprint_sources":2,"real_vendor_signed_terminal_count":0,
        "source_eprj2_sha256":SOURCE_V11_SHA,
        "source_actual_P1_wire_count":280,
        "fabrication_approved":False},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
