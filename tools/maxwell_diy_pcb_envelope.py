"""Export 24+2 design-owned, PROVISIONAL magnet pad coordinates for G1 placement.

These are NOT OEM physical terminals. They are a proposed CAD interface for
an in-house winding, with exact existing native schematic logical nets/DOT.
No edits are made to vendor_terminal_request.json or original EasyEDA CAD.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

import maxwell_diy_geometry as geometry

ROOT = geometry.ROOT
TERMINALS = ROOT/"hardware/dcx_main/vendor_terminal_request.json"
OUT = geometry.OUT
TCOORD = {"PRI_A": (-17.0, -8.0), "PRI_B": (-17.0, 8.0),
          "SEC_A": (17.0, -7.0), "SEC_B": (17.0, 7.0),
          "CTAP": (17.0, 0.0)}
CTCOORD = {"PRI_A": (-12.0, -4.0), "PRI_B": (-12.0, 4.0),
           "SEC_A": (12.0, -4.0), "SEC_B": (12.0, 4.0)}
LRCOORD = {"N1": (-20.0, 0.0), "N2": (20.0, 0.0)}
FIELDS = ["ref", "concept_pad_id", "logical_terminal", "pcb_net",
          "dot_expectation", "x_mm", "y_mm", "pad_width_mm",
          "pad_height_mm", "truth_status"]


def rows():
    src = json.loads(TERMINALS.read_text(encoding="utf-8"))
    entries = {d["ref"]: d for d in src["devices"]}
    if set(entries) != {"CT", "T1", "T2", "T3", "T4"}:
        raise ValueError("Magnetics logical contract changed")
    result = []
    for ref in ["T1", "T2", "T3", "T4", "CT"]:
        mapping = CTCOORD if ref == "CT" else TCOORD
        pins = entries[ref]["pins"]
        if {p["logical_terminal"] for p in pins} != set(mapping):
            raise ValueError("Native symbol physical pad interface changed")
        for i, pin in enumerate(pins, 1):
            logical = pin["logical_terminal"]
            x, y = mapping[logical]
            result.append({
                "ref": ref, "concept_pad_id": f"D1_DESIGN_{ref}_{logical}",
                "logical_terminal": logical,
                "pcb_net": pin["required_circuit_net"],
                "dot_expectation": pin["dot_convention_expected"],
                "x_mm": x, "y_mm": y,
                "pad_width_mm": 2.0, "pad_height_mm": 2.0,
                "truth_status": "DESIGN_OWNED_G1_CONCEPT_NOT_PHYSICAL_PAD",
            })
    for logical, (x,y), net in [
        ("N1", LRCOORD["N1"], "CT_LR"), ("N2", LRCOORD["N2"], "PRI_T1"),
    ]:
        result.append({
            "ref":"Lr", "concept_pad_id":"D1_DESIGN_Lr_"+logical,
            "logical_terminal":logical,"pcb_net":net,
            "dot_expectation":"NOT_POLAR",
            "x_mm":x,"y_mm":y,"pad_width_mm":2.0,"pad_height_mm":2.0,
            "truth_status":"DESIGN_OWNED_G1_CONCEPT_NOT_PHYSICAL_PAD",
        })
    if len(result) != 26 or len({r["concept_pad_id"] for r in result}) != 26:
        raise ValueError("Must maintain four transformer x 5, CT x 4, Lr x 2")
    if any(not r["pcb_net"] for r in result):
        raise ValueError("Actual G1 logical net missing")
    # no pin is actually accepted by a manufacturer or measured device
    if any(r["truth_status"] != "DESIGN_OWNED_G1_CONCEPT_NOT_PHYSICAL_PAD"
           for r in result):
        raise ValueError("Cannot silently upgrade manufacturing evidence")
    return result


def packet():
    r = rows()
    f = io.StringIO(newline="")
    w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    w.writerows(r)
    csv_text = f.getvalue()
    audit = {
        "kind": "DESIGN_OWNED_MAGNETICS_G1_CONCEPT_NOT_FAB",
        "total_concept_pads": len(r),
        "transformer_and_ct_pads": len([x for x in r if x["ref"]!="Lr"]),
        "lr_concept_pads": len([x for x in r if x["ref"]=="Lr"]),
        "original_logical_contract_sha256": hashlib.sha256(TERMINALS.read_bytes()).hexdigest(),
        "geometry_contract_sha256": hashlib.sha256(geometry.CONTRACT.read_bytes()).hexdigest(),
        "status": "PCB_PLACEMENT_ONLY_NO_MAGNETIC_SOLVER_PASS",
        "real_manufacturer_pad_ids_confirmed": False,
        "physical_dot_verified": False,
        "real_cad_modified": False,
        "fabrication_approved": False,
    }
    return csv_text, json.dumps(audit, indent=2)+"\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args()
    txt, audit = packet()
    csvfile = args.out/"design_owned_G1_pads_24plus2.csv"
    jsonfile = args.out/"design_owned_G1_pads_24plus2.json"
    if args.write:
        args.out.mkdir(parents=True, exist_ok=True)
        csvfile.write_text(txt, encoding="utf-8")
        jsonfile.write_text(audit, encoding="utf-8")
    else:
        if (not csvfile.is_file() or not jsonfile.is_file()
                or csvfile.read_text(encoding="utf-8") != txt
                or json.loads(jsonfile.read_text(encoding="utf-8")) != json.loads(audit)):
            raise RuntimeError("Design-owned 24+2 pad proposal missing or source mismatch")
    print("26 DESIGN-OWNED G1 concept pads; never treat as OEM/approved.")


if __name__=="__main__":
    main()
