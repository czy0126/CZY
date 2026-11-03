"""Compare UCC25600 timing R1/R2 BOM values to the *actual native* netlist.

This intentionally checks functional pin requirements independently from the
SPICE-derived golden subnet: matching the golden netlist is insufficient if
BOM reference designators are assigned to the wrong analog control pins.
Read-only audit; does not approve physical pad footprint or fabricated board.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
HW=ROOT/"hardware/dcx_main"
BOM=ROOT/"design/v3/bom/bom_draft.csv"
REGISTER=HW/"component_decision_register.json"
EXPORT=HW/"gen/netlist_export_raw.json"
ASSIGN=ROOT/"docs/D1_EXECUTION_KIT/vendor_ref_assignments.json"
CATALOG=ROOT/"docs/D1_EXECUTION_KIT/vendor_parts_official.json"
EXPECTED={"DT":{"controller_pin":"1","nominal":"5.36 kohm","part_key":"R5360"},"RT":{"controller_pin":"2","nominal":"976 ohm","part_key":"R976"}}

def compare(native_refs: dict | None=None, register: dict | None=None,
            bom_rows: list[dict] | None=None, assigned: dict | None=None,
            catalog: dict | None=None) -> dict:
    if native_refs is None:
        raw=json.loads(EXPORT.read_text(encoding="utf-8"))
        if not raw.get("ok") or not isinstance(raw.get("value",{}).get("refs"),dict):
            raise ValueError("native netlist export missing")
        native_refs=raw["value"]["refs"]
    if register is None: register=json.loads(REGISTER.read_text(encoding="utf-8"))
    if bom_rows is None:
        with BOM.open(encoding="utf-8",newline="") as fp: bom_rows=list(csv.DictReader(fp))
    if assigned is None: assigned=json.loads(ASSIGN.read_text(encoding="utf-8"))
    if catalog is None: catalog=json.loads(CATALOG.read_text(encoding="utf-8"))
    items={x["ref"]:x for x in register["items"]}
    rows={x["ref"]:x for x in bom_rows}
    problems=[]
    controller=native_refs.get("U1",{})
    for net, spec in EXPECTED.items():
        if controller.get(spec["controller_pin"])!=net:
            problems.append(f"U1 pin {spec['controller_pin']} must be {net}")
        ref_matches=[ref for ref in ("R1","R2") if set(native_refs.get(ref,{}).values())=={net,"PGND"}]
        if len(ref_matches)!=1:
            problems.append(f"expected one native R1/R2 from {net} to PGND; observed {ref_matches}")
            continue
        ref=ref_matches[0]
        row=rows.get(ref)
        reg=items.get(ref)
        part=catalog.get(assigned.get(ref))
        if row is None or not row.get("item","").startswith(net+" resistor") or spec["nominal"] not in row.get("value_or_rating",""):
            problems.append(f"BOM {ref} does not describe {net} {spec['nominal']}")
        if reg is None or not reg.get("part_role","").startswith(net+" resistor") or spec["nominal"] not in reg.get("existing_value_or_rating",""):
            problems.append(f"register {ref} does not describe {net} {spec['nominal']}")
        if assigned.get(ref)!=spec["part_key"] or not part or spec["nominal"].split(" ")[0] not in part.get("nominal",""):
            problems.append(f"candidate MPN assignment for {ref} does not match {net} requirement")
    return {"checked_nets":["DT","RT"],"passed":not problems,"problems":problems,
            "evidence":"native exported netlist plus independent controller pin functional contract",
            "not_a_cad_approval":True}
