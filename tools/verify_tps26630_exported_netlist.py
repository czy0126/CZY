"""Compare ACTUAL KiCad-exported XML netlist against 36 OEM pin/net assignments.

The previous offline source parser checks labels at pin tips. This independently
checks the native KiCad export after genuine ERC, not copied label statements.
A pass does not qualify U1/Q1 footprints, reverse-current SOA or fabrication.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
PINMAP = ROOT / "hardware/sr_bias_efuse_proposal/tps26630_pinmap.csv"


def verify(netlist: Path, pinmap: Path = PINMAP) -> dict:
    root = ElementTree.parse(netlist).getroot()
    if root.tag != "export":
        raise ValueError("KiCad XML export root missing")
    nets = root.find("nets")
    if nets is None:
        raise ValueError("KiCad exported no net connections")
    connected = {}
    counts = Counter()
    for net in nets.findall("net"):
        name = (net.get("name") or "").lstrip("/")
        nodes = net.findall("node")
        counts[name] += len(nodes)
        for node in nodes:
            key = (node.get("ref"), node.get("pin"))
            if not all(key) or key in connected:
                raise ValueError(f"missing/duplicate exported pin {key}")
            connected[key] = name
    with pinmap.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 36 or len({(r["ref"],r["pad"]) for r in rows}) != 36:
        raise ValueError("OEM pinmap count/identity changed; explicit re-review required")

    failures = []
    for row in rows:
        pin = "25" if (row["ref"],row["pad"]) == ("U1","EP") else row["pad"]
        key = (row["ref"],pin)
        expected = row["net"]
        observed = connected.get(key)
        if expected in ("NC","FLOAT"):
            # KiCad may omit no-connect pins or emit a unique unconnected net.
            if observed is not None and not (
                observed.lower().startswith("unconnected-") and counts[observed] == 1):
                failures.append((key,expected,observed))
        elif observed != expected:
            failures.append((key,expected,observed))
    if failures:
        raise ValueError(f"actual KiCad netlist vs OEM pinmap mismatch: {failures[:15]}")
    return {
        "status": "KICAD_NATIVE_XML_PINMAP_MATCH_ONLY",
        "OEM_pin_assignments_checked": 36,
        "hardware_qualified": False,
        "fabrication_approved": False,
        "native_footprints_verified": False,
        "comparison_source": "hardware/sr_bias_efuse_proposal/tps26630_pinmap.csv",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--netlist", type=Path, required=True)
    ap.add_argument("--pinmap", type=Path, default=PINMAP)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    data = verify(args.netlist, args.pinmap)
    if args.out:
        args.out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
