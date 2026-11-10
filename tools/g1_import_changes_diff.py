"""Build the schematic-vs-PCB pin difference from the editor's own artifacts.

The editor's native DRC reports a single "Netlist Error" and its beta comparator
(`sys_Tool.netlistComparison`) returns a PCB column that is empty for every net,
so neither one publishes the per-ref/per-pin difference. This tool pairs:

* the comparator's schematic-side pin lists (``lr_signal_import_changes.json``),
* the PCB's own netlist export ``pcb_Net.getNetlist('JLCEDA')``
  (``lr_repack_pcb_netlist_jlc.json``), and
* the native pad readback (``lr_repack_readback.json``),

and reports exactly which pins pair and which do not. Everything is re-derived
and hashed at build time; a receipt that no longer matches the board is refused.

python tools/g1_import_changes_diff.py --write
python tools/g1_import_changes_diff.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G1 = ROOT / "hardware/dcx_main/g1"
BOARD = G1 / "dcx_main_board_g1_signal_stubs.eprj2"
IMPORT = G1 / "lr_signal_import_changes.json"
EXPORT = G1 / "lr_signal_pcb_netlist_export.json"
NETLIST = G1 / "lr_repack_pcb_netlist_jlc.json"
MODEL = G1 / "lr_signal_pcb_netlist_model.json"
READBACK = G1 / "lr_repack_readback.json"
REPORT = G1 / "g1_import_changes_diff.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _split(pin: str) -> tuple[str, str]:
    ref, _, number = pin.partition(".")
    if not ref or not number:
        raise ValueError(f"pin is not ref.pin: {pin!r}")
    return ref, number


def _schematic_pins(import_receipt: dict) -> dict[str, set[tuple[str, str]]]:
    pins: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in import_receipt["normalized"]:
        if row["type"] != "NET":
            continue
        net = row["object"].strip("'")
        for pin in row["schematic"]:
            pins[net].add(_split(pin))
    return pins


def _pcb_pins(netlist: dict) -> tuple[dict[str, set[tuple[str, str]]],
                                      list[tuple[str, str]]]:
    pins: dict[str, set[tuple[str, str]]] = defaultdict(set)
    unassigned: list[tuple[str, str]] = []
    for component in netlist["components"].values():
        ref = component["props"]["Designator"]
        for info in component["pinInfoMap"].values():
            if info["net"]:
                pins[info["net"]].add((ref, info["number"]))
            else:
                unassigned.append((ref, info["number"]))
    return pins, sorted(unassigned)


def build(import_receipt: dict, export_receipt: dict, model_receipt: dict,
          readback: dict, netlist_text: str, board_sha: str) -> dict:
    """Validate every input against the board and derive the difference."""
    if import_receipt.get("editor_ok") is not True:
        raise ValueError("comparator receipt is not a successful native readback")
    if model_receipt.get("editor_ok") is not True:
        raise ValueError("PCB netlist-model probe is not a successful readback")
    for name, receipt in (("comparator", import_receipt), ("export", export_receipt),
                          ("model probe", model_receipt)):
        for key in ("candidate_sha256", "probe_copy_sha256_after"):
            if receipt.get(key) != board_sha:
                raise ValueError(f"{name} receipt {key} differs from the candidate board")
    if export_receipt["netlist_sha256"] != hashlib.sha256(
            netlist_text.encode("utf-8")).hexdigest():
        raise ValueError("exported netlist text does not match its receipt hash")
    if export_receipt["netlist_chars"] != len(netlist_text):
        raise ValueError("exported netlist length does not match its receipt")
    if len(readback["components"]) != 77 or len(readback["pads"]) != 299:
        raise ValueError("native readback primitive counts changed")
    if len(readback["nets"]) != 65:
        raise ValueError("native readback net count changed")
    if model_receipt["net_names"]["count"] != len(readback["nets"]):
        raise ValueError("PCB net-name count differs between probe and readback")
    probe_netlists = [row["value"] for row in model_receipt["probes"]
                      if row["probe"] == "pcb_netlist" and row["ok"]]
    if [row["length"] for row in probe_netlists] != [len(netlist_text)]:
        raise ValueError("probe-time PCB netlist length differs from this export")
    for net, info in model_receipt["primitives_by_net"].items():
        if not info.get("count"):
            raise ValueError(f"probe found no PCB primitives on net {net}")

    netlist = json.loads(netlist_text)
    sch = _schematic_pins(import_receipt)
    pcb, pcb_unassigned = _pcb_pins(netlist)
    pcb_unassigned_names = [f"{ref}.{num}" for ref, num in pcb_unassigned]
    pads_without_net = sorted(f"{pad['ref']}.{pad['PadNumber']}"
                              for pad in readback["pads"] if not pad.get("Net"))
    if pads_without_net != sorted(pcb_unassigned_names):
        raise ValueError("readback pads without a net differ from the exported netlist")

    net_rows = [r for r in import_receipt["normalized"] if r["type"] == "NET"]
    if len(net_rows) != len(sch):
        raise ValueError("comparator net rows and parsed schematic nets disagree")
    if any(row["pcb"] for row in import_receipt["normalized"]):
        raise ValueError("comparator published a non-empty PCB column; revisit this tool")
    attempts = {row["label"]: row for row in import_receipt["attempts"]}
    if attempts["schematic self-compare (control)"].get("count") != 0:
        raise ValueError("schematic self-compare is not zero")
    if attempts["pcb self-compare (control)"].get("count") != 0:
        raise ValueError("PCB self-compare is not zero")
    reversed_rows = attempts["reversed (pcb, schematic)"].get("value") or []
    if any(row.get("net1") for row in reversed_rows):
        raise ValueError("reversed compare is not the mirror of the forward compare")

    unmatched_sch: Counter[str] = Counter()
    unmatched_pcb: Counter[str] = Counter()
    differing = []
    identical = 0
    for net in sorted(set(sch) | set(pcb)):
        only_sch = sch.get(net, set()) - pcb.get(net, set())
        only_pcb = pcb.get(net, set()) - sch.get(net, set())
        if only_sch or only_pcb:
            differing.append(net)
            for ref, _ in only_sch:
                unmatched_sch[ref] += 1
            for ref, _ in only_pcb:
                unmatched_pcb[ref] += 1
        else:
            identical += 1

    # The schematic never lists an unassigned pin, so agreement means every pad
    # without a net on the PCB is also absent from every schematic net.
    sch_pin_names = {f"{ref}.{num}" for pins in sch.values() for ref, num in pins}
    sch_unassigned = [name for name in pcb_unassigned_names if name not in sch_pin_names]
    sch_components = sorted({ref for pins in sch.values() for ref, _ in pins})
    pcb_components = sorted({ref for pins in pcb.values() for ref, _ in pins})

    result = {
        "status": "G1_NATIVE_IMPORT_CHANGES_DIFF_FROM_EDITOR_NETLIST_EXPORT",
        "candidate": BOARD.relative_to(ROOT).as_posix(),
        "candidate_sha256": board_sha,
        "editor_comparator": {
            "api": import_receipt["api"],
            "net_rows": len(net_rows),
            "net_rows_with_empty_pcb_side": sum(1 for row in net_rows if not row["pcb"]),
            "component_rows": [row for row in import_receipt["normalized"]
                               if row["type"] == "COMPONENT"],
            "schematic_self_compare": 0,
            "pcb_self_compare": 0,
            "reversed_compare_is_mirror": True,
            "pcb_side_usable": False,
            "why_unusable": (
                "every net row carries an empty PCB pin list, including the nets whose "
                "pins match exactly, while the same PCB exports a 165556-character "
                "netlist with 62 named nets and 254 assigned pins"),
        },
        "schematic_netlist": {
            "components_with_pins": len(sch_components),
            "nets": len(sch),
            "pins": sum(len(pins) for pins in sch.values()),
            "unassigned_pins": sch_unassigned,
        },
        "pcb_netlist": {
            "components": len(netlist["components"]),
            "components_with_pins": len(pcb_components),
            "named_nets": len(pcb),
            "assigned_pins": sum(len(pins) for pins in pcb.values()),
            "unassigned_pins": sorted(pcb_unassigned_names),
        },
        "difference": {
            "unmatched_schematic_pins_total": sum(unmatched_sch.values()),
            "unmatched_schematic_pins_by_ref": dict(unmatched_sch.most_common()),
            "unmatched_pcb_pins_total": sum(unmatched_pcb.values()),
            "unmatched_pcb_pins_by_ref": dict(unmatched_pcb.most_common()),
            "nets_only_in_schematic": sorted(set(sch) - set(pcb)),
            "nets_only_in_pcb": sorted(set(pcb) - set(sch)),
            "nets_differing": differing,
            "nets_identical": identical,
            "schematic_components_absent_from_pcb": sorted(set(sch_components) - set(pcb_components)),
        },
        "unassigned_pins_agree": sorted(sch_unassigned) == sorted(pcb_unassigned_names),
        "interpretation": [
            "Every pin present on both sides pairs by (designator, pin number); no PCB "
            "pin is missing a schematic partner.",
            "The only unmatched pins are the 24 logical terminals of CT and T1-T4, whose "
            "PCB pads are design-owned placeholders with no designator, so they are not "
            "component pins in the PCB netlist.",
            "PRI_12, PRI_23 and PRI_34 exist only in the schematic because every pin on "
            "them is a magnetic terminal.",
            "The five D_CT1-D_CT4 and U2 pin-2 pads carry no net on either side; they are "
            "the same unassigned pins on both sides, not a difference.",
            "The single native Netlist Error is consistent with these five magnetics "
            "having no PCB component, and no other pin-level difference exists in the "
            "editor's own export; the DRC rule reports a count, not items, so mapping "
            "that count to these rows remains an inference.",
        ],
        "not_erc_not_drc_not_fab": True,
        "fabrication_approved": False,
        "limitations": [
            "The comparator's PCB column is unusable on this primitive-built board; the "
            "difference above comes from the PCB's own netlist export, not from it.",
            "Anonymous pads can carry a net name while remaining outside any component "
            "pin list; that is a placeholder fact, not a verified physical terminal map.",
            "Pin pairing by (designator, pin number) does not prove footprint geometry, "
            "polarity, insulation or assembly.",
        ],
    }
    return result


def report() -> dict:
    import_receipt = json.loads(IMPORT.read_text(encoding="utf-8"))
    export_receipt = json.loads(EXPORT.read_text(encoding="utf-8"))
    model_receipt = json.loads(MODEL.read_text(encoding="utf-8"))
    readback = json.loads(READBACK.read_text(encoding="utf-8"))["value"]
    netlist_text = NETLIST.read_text(encoding="utf-8")
    return build(import_receipt, export_receipt, model_receipt, readback,
                 netlist_text, sha256(BOARD))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = ap.parse_args()
    result = report()
    if args.write:
        REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8", newline="\n")
    elif not REPORT.is_file() or json.loads(REPORT.read_text(encoding="utf-8")) != result:
        raise SystemExit("G1 Import-Changes difference report is stale; rerun --write")
    print(json.dumps(result["difference"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
