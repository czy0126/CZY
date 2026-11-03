"""Generate a 61-reference native CAD engineering change checklist.

Read-only! Never writes to EasyEDA native .eprj2, creates fabrication evidence,
or pretends the proposed package is an actual accepted footprint.
"""
from __future__ import annotations
import argparse
import csv
import io
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
HW=ROOT/"hardware/dcx_main"
KIT=ROOT/"docs/D1_EXECUTION_KIT"
OUTPUT=KIT/"templates/vendor_native_cad_eco_61.csv"
HEADER=["ref","priority","native_symbol_part","native_footprint","native_pad_net_pair","nominal_placeholder","candidate_mpn","candidate_manufacturer","candidate_eia_case","candidate_nominal","footprint_eia_match","nominal_value_match","required_eda_change","independent_electrical_verification","ecad_status"]

def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def _nominal(text: str) -> str:
    text=text.lower().replace("µ","u").replace("μ","u").replace(" ","")
    # Convert known resistor/capacitor nominal prefixes to SI.
    import re
    m=re.match(r"^([0-9]+(?:\.[0-9]+)?)(kohm|ohm|uf|nf|pf)",text)
    if not m:
        return ""
    value=float(m.group(1))
    multiplier={"kohm":1000,"ohm":1,"uf":1e-6,"nf":1e-9,"pf":1e-12}
    unit="R" if m.group(2).endswith("ohm") else "C"
    return f"{unit}{value*multiplier[m.group(2)]:.12g}"

def generate() -> str:
    reg=_read(HW/"component_decision_register.json")
    placement=_read(HW/"placement_plan.json")["refs"]
    net=_read(HW/"gen/netlist_export_raw.json")
    if not net.get("ok"): raise ValueError("native export is not valid")
    nets=net["value"]["refs"]
    assign=_read(KIT/"vendor_ref_assignments.json")
    catalog=_read(KIT/"vendor_parts_official.json")
    out=io.StringIO(newline="")
    writer=csv.DictWriter(out,fieldnames=HEADER,lineterminator="\n")
    writer.writeheader()
    refs=set()
    for item in reg["items"]:
        ref=item["ref"]
        if ref in refs: raise ValueError("duplicate ref: "+ref)
        refs.add(ref)
        if ref not in placement or ref not in nets:
            raise ValueError("missing native placement or net export for "+ref)
        old=placement[ref]
        part=catalog.get(assign.get(ref),{})
        old_part=old.get("part","")
        if old_part=="R0603_10k": placeholder="10 kohm"
        elif old_part=="C0603_100n": placeholder="100 nF"
        else: placeholder="UNKNOWN_LIB_PART"
        old_fp=old.get("footprint",{}).get("name","")
        old_eia=old_fp[1:5] if old_fp.startswith(("R0603","C0603","R0805","C0805")) else "UNKNOWN"
        new_eia=part.get("eia_case","")
        fp_match="NOT_CHECKED" if not part or old_eia=="UNKNOWN" else ("YES_NOMINAL_EIA_ONLY" if old_eia==new_eia else "NO")
        nom_match="NOT_CHECKED" if not part or placeholder=="UNKNOWN_LIB_PART" else ("YES_NOMINAL_ONLY" if _nominal(placeholder)==_nominal(part["nominal"]) else "NO")
        if not part: change="CUSTOM_OR_POWER_PART_DESIGN_OPEN"
        elif fp_match=="NO": change="REPLACE_NATIVE_FOOTPRINT_AND_PART_AND_CHECK_NETS"
        elif nom_match=="NO": change="REPLACE_NATIVE_PART_VALUE_MPN_AND_VERIFY_PADS"
        else: change="REPLACE_NATIVE_PART_MPN_AND_VERIFY_PADS"
        # Native pad connectivity comes only from the repo's actual exported netlist,
        # not a fabricated physical pad number or manufacturer's footprint approval.
        native=nets[ref]
        net_pair=";".join(f"{pin}:{net}" for pin,net in sorted(native.items()))
        writer.writerow(dict(ref=ref,priority=item["priority"],native_symbol_part=old_part,
            native_footprint=old_fp,native_pad_net_pair=net_pair,
            nominal_placeholder=placeholder,candidate_mpn=part.get("mpn",""),
            candidate_manufacturer=part.get("maker",""),
            candidate_eia_case=new_eia,candidate_nominal=part.get("nominal",""),
            footprint_eia_match=fp_match,nominal_value_match=nom_match,
            required_eda_change=change,
            independent_electrical_verification="PENDING_PIN_AND_THERMAL_REVIEW",
            ecad_status="NOT_APPLIED_NOT_ERC_VERIFIED"))
    if len(refs)!=61 or len(assign)!=51 or set(assign)-refs:
        raise ValueError("expected exactly 61 native placeholders and 51 documented options")
    return out.getvalue()

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--write",action="store_true")
    p.add_argument("--check",action="store_true")
    args=p.parse_args()
    output=generate()
    if args.write: OUTPUT.write_text(output,encoding="utf-8",newline="")
    elif args.check and (not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8")!=output):
        raise SystemExit("ECO plan stale: --write required")
    print(f"native CAD ECO: {output.count(chr(10))-1} refdes, 0 approvals")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
