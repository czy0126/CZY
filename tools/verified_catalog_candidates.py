"""Generate source-backed 0603 component CANDIDATES for 39 native BOM errors.

This is an upstream supplier catalog *identity* mapping, not a validated BOM
or a CAD ECO. Engineering checks for effective capacitance, transient resistor
dissipation, footprint and default-off R8 are still mandatory.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "hardware/dcx_main/native_inventory_bom_gate.json"
OUT = ROOT / "hardware/dcx_main/verified_catalog_candidates_not_for_fab.json"

CATALOG = {
    "C:2.2uF": {
        "mpn": "GRM188C71E225KE11D",
        "maker": "Murata",
        "footprint": "0603",
        "rating": "2.2uF ±10%,25V,X7S",
        "source": "https://www.digikey.com/en/products/detail/murata-electronics/GRM188C71E225KE11D/5797701",
        "critical": "REG capacitor: verify DC-bias effective capacitance at 11V and TI UCC24624 start/hold requirements"
    },
    "C:1uF": {
        "mpn": "C1608X7R1E105K080AB",
        "maker": "TDK",
        "footprint": "0603",
        "rating": "1uF ±10%,25V,X7R",
        "source": "https://www.digikey.com/en/products/detail/tdk-corporation/C1608X7R1E105K080AB/2443434",
        "critical": "VDD decoupling: verify actual voltage rail, surge and DC-bias-effective capacitance"
    },
    "C:47nF": {
        "mpn": "CL10B473KB8NFNC",
        "maker": "Samsung",
        "footprint": "0603",
        "rating": "47nF ±10%,50V,X7R",
        "source": "https://www.digikey.com/en/products/detail/samsung-electro-mechanics/CL10B473KB8NFNC/3887733",
        "critical": "OC filter: assess time constant using tolerance and source impedance"
    },
    "C:10nF": {
        "mpn": "CL10B103KB8NNNC",
        "maker": "Samsung",
        "footprint": "0603",
        "rating": "10nF ±10%,50V,X7R",
        "source": "https://media.digikey.com/pdf/Data%20Sheets/Samsung%20PDFs/CL10B103KB8NNNC_Spec.pdf",
        "critical": "OC hold or SS capacitor: verify protection/soft-start time constant at extremes"
    },
    "C:1nF": {
        "mpn": "CL10B102KB8NNNC",
        "maker": "Samsung",
        "footprint": "0603",
        "rating": "1nF ±10%,50V,X7R",
        "source": "https://www.digikey.com/en/products/detail/samsung-electro-mechanics/CL10B102KB8NNNC/3886676",
        "critical": "EN filter: verify immunity and startup timing"
    },
    "C:220nF": {
        "mpn": "CL10B224KB8NNNC",
        "maker": "Samsung",
        "footprint": "0603",
        "rating": "220nF ±10%,50V,X7R",
        "source": "https://media.digikey.com/pdf/Data%20Sheets/Samsung%20PDFs/CL10B224KB8NNNC_Spec.pdf",
        "critical": "HB bootstrap: verify differential voltage and startup gate charge, ripple and dielectric bias"
    },
    "R:5.36kΩ": {
        "mpn": "CRCW06035K36FKEA",
        "maker": "Vishay",
        "footprint": "0603",
        "rating": "5.36kΩ ±1%,0.125W",
        "source": "https://www.digikey.com/en/products/detail/vishay-dale/CRCW06035K36FKEA/1174751",
        "critical": "dead-time setpoint: verify tolerance and operating frequency dependencies"
    },
    "R:1kΩ": {
        "mpn": "CRCW06031K00FKEA",
        "maker": "Vishay",
        "footprint": "0603",
        "rating": "1kΩ ±1%,0.125W",
        "source": "https://www.digikey.com/en/products/detail/vishay-dale/CRCW06031K00FKEA/1179809",
        "critical": "R8 is an explicit DNP safety item; do not populate regardless of nominal 1k candidate"
    },
    "R:24kΩ": {
        "mpn": "CRCW060324K0FKEA",
        "maker": "Vishay",
        "footprint": "0603",
        "rating": "24kΩ ±1%,0.125W",
        "source": "https://www.digikey.com/en/products/detail/vishay-dale/CRCW060324K0FKEA/1174823",
        "critical": "OC divider ratio must be checked with CT burden and comparator limits"
    },
    "R:976Ω": {
        "mpn": "CRCW0603976RFKEA",
        "maker": "Vishay",
        "footprint": "0603",
        "rating": "976Ω ±1%,0.125W",
        "source": "https://www.digikey.com/en/products/detail/vishay-dale/CRCW0603976RFKEA/1174667",
        "critical": "RT frequency programming: verify tolerance, parasitics and tuning result"
    },
    "R:2.2Ω": {
        "mpn": "CRCW06032R20FKEAHP",
        "maker": "Vishay",
        "footprint": "0603",
        "rating": "2.2Ω ±1%,0.333W pulse-withstanding CRCW-HP",
        "source": "https://www.digikey.com/en/products/detail/vishay-dale/CRCW06032R20FKEAHP/2225881",
        "critical": "Switch gate: vendor catalog pulse-withstanding CRCW0603-HP 0.333W, still verify Rext switching loss, short pulse peak vs rated pulse-duration curves, derating and PCB thermal; not an actual 200kHz gate approval"
    },
    "R:0Ω": {
        "mpn": "CRCW06030000Z0EA",
        "maker": "Vishay",
        "footprint": "0603",
        "rating": "0Ω jumper, 0.125W class",
        "source": "https://www.digikey.com/en/products/detail/vishay-dale/CRCW06030000Z0EA/1179296",
        "critical": "Kelvin sense only: verify SR drain branch net, 0603 jumper rated current; do not route 100A through jumper"
    },
    "R:10Ω": {
        "mpn": "CRCW060310R0FKEA",
        "maker": "Vishay",
        "footprint": "0603",
        "rating": "10Ω ±1%,0.125W",
        "source": "https://www.digikey.com/en/products/detail/vishay-dale/CRCW060310R0FKEA/1179581",
        "critical": "CT burden: verify transient peak and pulse rating, not merely steady-state ohms"
    }
}


def report() -> dict:
    upstream = json.loads(SRC.read_text(encoding="utf-8"))
    if upstream.get("manufacturing_approved") is not False:
        raise ValueError("native inventory source status changed: new independent audit required")
    faults = upstream["conflicts"]
    groups = {}
    records = []
    seen = set()
    for old in faults:
        ref = old["ref"]
        if ref in seen:
            raise ValueError("duplicate original ref "+ref)
        seen.add(ref)
        key = ref[0] + ":" + old["design_target"]
        c = CATALOG.get(key)
        if c is None:
            raise ValueError("unmapped vendor catalog candidate " + key)
        if not old["manufacturer_vs_design_target"]:
            raise ValueError("input source is not a manufacturer conflict "+ref)
        groups[key] = groups.get(key, 0) + 1
        dnp = ref == "R8"
        records.append({
            "ref": ref, "role": old["role"], "design_target": old["design_target"],
            "original_native_mpn": old["native_manufacturer_id"],
            "original_native_supplier_code": old["native_supplier_id"],
            "original_native_value": old["actual_native_display"],
            "catalog_match_mpn": None if dnp else c["mpn"],
            "catalog_match_maker": None if dnp else c["maker"],
            "catalog_match_value": None if dnp else old["design_target"],
            "nominal_package": None if dnp else c["footprint"],
            "catalog_spec": None if dnp else c["rating"],
            "catalog_reference_url": None if dnp else c["source"],
            "assembly_action": ("MUST_DNP_REMOVE_FROM_BOM_AND_PCB" if dnp
                                else "REPLACE_ORIGINAL_DEVICE_AND_VERIFY"),
            "functional_review": c["critical"],
            "candidate_catalog_verified": not dnp,
            "electrical_corner_qualified": False,
            "native_eda_modified": False,
            "actual_bom_reexport_verified": False,
            "manufacturer_landpattern_verified": False,
            "approved_for_procurement": False,
            "approved_for_fab": False,
        })
    return {
        "status": "39_SOURCE_BACKED_CATALOG_CANDIDATES_ONLY_NOT_FOR_FAB",
        "source": "hardware/dcx_main/native_inventory_bom_gate.json",
        "model": "GROUP_BY_COMPONENT_TYPE_AND_DESIGN_TARGET",
        "source_ref_count": len(faults),
        "catalog_group_count": len(CATALOG),
        "catalog_group_counts": groups,
        "candidate_designators": sum(1 for x in records if x["catalog_match_mpn"]),
        "must_dnp_designators": [x["ref"] for x in records
                                 if x["assembly_action"] == "MUST_DNP_REMOVE_FROM_BOM_AND_PCB"],
        "catalog": CATALOG,
        "faults": records,
        "publisher_note": "Third-party catalog identity checked on Nov 8 2026; no factory quotation, electrical corner, OEM footprint, C-bias curve, gate resistor pulse SOA or real native CAD BOM export qualified.",
        "cannot_buy_until": [
            "R8 absent from genuine native BOM and PCB",
            "39 original manufacturer/library part fields replaced or DNP in native CAD",
            "show genuine EDA netlist, BOM and ERC/DRC",
            "C7-C10 REG capacitance under bias and VIN start/stop checks",
            "R20-R27 gate resistor pulse power, Ipk and thermal",
            "R28-R35 Kelvin branch and 0ohm current rating",
            "all active components magnetic terminals SOA and converter safety",
        ],
        "hardware_qualified": False, "can_release_purchase_order": False,
        "can_fabricate": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    result = report()
    if args.write:
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        return 0
    if not OUT.exists() or json.loads(OUT.read_text(encoding="utf-8")) != result:
        print("catalog candidate report drift; rerun --write")
        return 1
    print(f"{result['candidate_designators']} vendor catalog candidates, "
          f"{len(result['must_dnp_designators'])} safety DNP, "
          "0 manufacturer CAD replacements completed, NOT_FOR_FAB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
