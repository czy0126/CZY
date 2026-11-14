"""Issue #133 Lane C: fail-closed G0/G1 protection/wiring handoff.

This is an audit of a *bench* D0 schematic and a read-only V17 board. It does
not merge or approve either design, generate a safe-to-power PCB, or fabricate
instrument evidence. No G0/G1 pass can be obtained from structural checks alone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import make_d0_protection_board as d0
import d0_analog_preflight as analog
import d0_response_budget as timing
import d0_p0_fault_matrix as fault_matrix
import d1_v17_oem_copper_gate as v17_gate

BASELINE = ROOT / "hardware/dcx_main/g2/dcx_main_board_g2_V17_OEM_T530_72_VIN_SW_CANDIDATE_NOT_FOR_FAB.kicad_pcb"
BASELINE_SHA = "4bdb3492959aa08e70716a0f6ca020fe8cf98da66f08c795b72f8172b5ab50f9"
D0_SCH = ROOT / "pcb/d0_protection/d0_protection.kicad_sch"
D0_NET = ROOT / "pcb/d0_protection/d0_protection.net"
OUTPUT = ROOT / "design/v3/stage_f/d1_lane_c_g0/g0_wiring_and_fault_gate_NOT_FOR_FAB.json"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(want: str, observed: object, message: str) -> None:
    if observed != want:
        raise ValueError(f"{message}: expected {want!r}, got {observed!r}")

def exactly(parts: dict, ref: str, pins: dict[str, str], value: str | None = None, dnp: bool | None = None):
    if ref not in parts:
        raise ValueError(f"missing device {ref}")
    part = parts[ref]
    if part.nets != pins:
        raise ValueError(f"{ref} pin/net mismatch: {part.nets!r} != {pins!r}")
    if value is not None and part.value != value:
        raise ValueError(f"{ref}: expected {value}, got {part.value}")
    if dnp is not None and part.dnp is not dnp:
        raise ValueError(f"{ref} DNP mismatch")
    return part

def inspect_wiring(part_instances=None):
    part_instances = d0.parts() if part_instances is None else part_instances
    parts = {p.ref: p for p in part_instances}
    # Each eight-way enable is physically pulled LOW, despite the UCC27524A
    # EN internal pull-up. The DNP R45 must not be stuffed: it defeats OFF.
    for k in range(4):
        ref = f"U{14 + k}"
        pins = {"1": "PERMIT_RAIL", "2": "TG_SR", "3": "PGND",
                "4": "TG_SR", "5": f"SOB{k}", "6": "V12S",
                "7": f"SOA{k}", "8": "PERMIT_RAIL"}
        exactly(parts, ref, pins, "UCC27524ADR", False)
    exactly(parts, "U18", {"1": "V12P", "2": "#NC", "3": "HB",
                            "4": "HO", "5": "PGND", "6": "PERMIT_RAIL",
                            "7": "TG_HI", "8": "TG_LO", "9": "PGND",
                            "10": "LO", "11": "PGND"},
            "UCC27282DRCR", False)
    exactly(parts, "Q2", {"1": "PCOLL", "2": "V5", "3": "PERMIT_RAIL"},
            "BSS84", False)
    exactly(parts, "R35", {"1": "PERMIT_RAIL", "2": "PGND"}, "100k", False)
    exactly(parts, "R44", {"1": "PERMIT_RAIL", "2": "PGND"}, "10k", False)
    exactly(parts, "R45", {"1": "V12P", "2": "PERMIT_RAIL"}, "1k", True)
    exactly(parts, "C28", {"1": "PERMIT_RAIL", "2": "PGND"}, "1nF/50V", False)
    for i in range(8):
        exactly(parts, f"R{36+i}", {"1": "PERMIT_RAIL", "2": "PGND"}, "4.7k", False)
    channels = []
    for i in range(1, 11):
        sr = i <= 8
        gate = f"GA{i}" if sr else ("GH1" if i == 9 else "GL1")
        sense = f"GK{i}"
        gate_res = f"R{47+i}" if sr else ("R46" if i == 9 else "R47")
        driver_out = (
            f"{'SOA' if i % 2 else 'SOB'}{(i-1)//2}" if sr
            else ("HO" if i == 9 else "LO")
        )
        bleed = f"R{55+i}" if sr else ("R64" if i == 9 else "R65")
        detector = f"R{65+i}" if sr else ("R74" if i == 9 else "R75")
        diode = f"D{8+i}"
        exactly(parts, gate_res, {"1": driver_out, "2": gate}, "2.2R", False)
        exactly(parts, bleed, {"1": gate, "2": "PGND"}, "10k", False)
        exactly(parts, detector, {"1": gate, "2": sense}, "1k", False)
        # The diode-OR senses only. Detecting VG != forcing VG safely OFF.
        dp = exactly(parts, diode, {"1": "GSMAX", "2": sense}, "BAT54ZFILM", False)
        channels.append({"index": i, "kind": "SR" if sr else "PRIMARY",
                         "driver_ref": f"U{14+(i-1)//2}" if sr else "U18",
                         "driver_output": driver_out, "gate_net": gate,
                         "series_resistor": gate_res, "bleed_resistor": bleed,
                         "bleed_ohm": 10000, "sense_resistor": detector,
                         "sense_diode": diode, "measurement": "PENDING",
                         "off_time_max_verified": False})
    if len(channels) != 10 or len({x["gate_net"] for x in channels}) != 10:
        raise ValueError("ten independent gate channels required")
    # A bootstrap-to-PGND bench approximation is NOT a validated high-side
    # bootstrap between HB and switching HS; flag rather than approve.
    exactly(parts, "C29", {"1": "HB", "2": "PGND"}, "100nF/25V", False)
    return channels


def audit_high_side_reference(part_instances) -> dict:
    """DRC-package pin/domain audit, separate from bench netlist self-consistency.

    TI UCC27282 SNVSAQ5B Fig. 5-1/Table 5-1: pin 5=HS, pin 9=VSS.
    Matching the bench's own exported netlist is NOT sufficient to validate
    high-side source-referenced drive, bootstrap or VGS measurement.
    """
    parts = {p.ref: p for p in part_instances}
    u18, c29, r64 = (parts[ref] for ref in ("U18", "C29", "R64"))
    hs, vss = u18.nets["5"], u18.nets["9"]
    checks = {
        "ucc27282_hs_pin5_not_short_to_vss_pin9": hs != vss,
        "c29_bootstrap_negative_to_hs_not_vss":
            c29.nets["2"] == hs and c29.nets["2"] != vss,
        "r64_high_side_gate_bleed_to_hs_not_vss":
            r64.nets["2"] == hs and r64.nets["2"] != vss,
        # The bench detector D17/GSMAX only observes a PGND-referred
        # gate node, NOT the actual high-side V(GH1)-V(HS).
        "high_side_actual_source_referenced_vgs_capture_proven": False,
    }
    return {
        "status": "PHYSICAL_HIGH_SIDE_REFERENCE_NOT_QUALIFIED",
        "datasheet": "https://www.ti.com/lit/ds/symlink/ucc27282.pdf",
        "package": "DRC VSON-10", "hs_pin": "5", "vss_pin": "9",
        "observed_hs_net": hs, "observed_vss_net": vss,
        "c29_negative_net": c29.nets["2"],
        "r64_return_net": r64.nets["2"],
        "checks": checks,
        "failed_checks": [key for key, passed in checks.items() if not passed],
        "physical_high_side_approved": False,
        "remediation": [
            "Connect U18 pin 5 HS to the real half-bridge switch/source Kelvin node, NEVER VSS",
            "Connect C29 negative and high-side gate-to-source bleed to U18 HS, not PGND",
            "Provide a differential/source-referenced GH1-HS measurement; do not use GSMAX as VGS proof",
            "Re-export actual KiCad netlist, check DRC/ERC and compare against the assembled device footprint",
            "Verify bootstrap HB-HS startup/UVLO and turn-off on the unenergized bench before G0 signoff",
        ],
    }


def verify_exported_netlist(part_instances, refs: set[str], netlist_text: str) -> int:
    """Cross-check selected D0 table pins against exported KiCad netlist.

    Cached export parity is not a new live ERC or physical pin validation.
    """
    nodes: dict[tuple[str, str], str] = {}
    pos = netlist_text.find("(nets")
    if pos < 0:
        raise ValueError("KiCad netlist has no nets")
    region = netlist_text[pos:]
    for match in re.finditer(r"(?m)^\s*\(net\s*$", region):
        i = region.find("(net", match.start(), match.end())
        block = region[i:d0.block_end(region, i)]
        name_match = re.search(r'\(name "(/?[^"]+)"\)', block)
        if not name_match:
            raise ValueError("KiCad net has no name")
        net = name_match.group(1).lstrip("/")
        for nm in re.finditer(r"(?m)^\s*\(node\s*$", block):
            j = block.find("(node", nm.start(), nm.end())
            node = block[j:d0.block_end(block, j)]
            rm = re.search(r'\(ref "([^"]+)"\)', node)
            pm = re.search(r'\(pin "([^"]+)"\)', node)
            if rm is None or pm is None:
                raise ValueError("KiCad net node lacks ref/pin")
            key = (rm.group(1), pm.group(1))
            if key in nodes and nodes[key] != net:
                raise ValueError(f"KiCad pin on two nets: {key}")
            nodes[key] = net
    count = 0
    for part in part_instances:
        if part.ref not in refs:
            continue
        for pin, net in part.nets.items():
            if net == "#NC":
                nc = nodes.get((part.ref, pin))
                if nc is not None and not nc.startswith("unconnected-"):
                    raise ValueError(f"no-connect connected to active net: {part.ref}.{pin} -> {nc}")
            elif nodes.get((part.ref, pin)) != net:
                raise ValueError(
                    f"KiCad exported netlist disagrees with {part.ref}.{pin}: "
                    f"table={net}, export={nodes.get((part.ref,pin))}")
            count += 1
    return count

def build(part_instances=None) -> dict:
    if sha(BASELINE) != BASELINE_SHA:
        raise ValueError("shared immutable V17 PCB SHA mismatch")
    channels = inspect_wiring(part_instances)
    physical_reference = audit_high_side_reference(d0.parts() if part_instances is None else part_instances)
    selected = {"Q2", "R35", "R44", "R45", "C28", "C29", "U18"}
    selected.update(f"U{i}" for i in range(14, 18))
    selected.update(f"R{i}" for i in range(36, 44))
    for ch in channels:
        selected.update((ch["series_resistor"], ch["bleed_resistor"],
                         ch["sense_resistor"], ch["sense_diode"]))
    net_pins = verify_exported_netlist(
        d0.parts() if part_instances is None else part_instances,
        selected, D0_NET.read_text(encoding="utf-8"))
    v17 = v17_gate.audit()
    saved_v17 = json.loads((v17_gate.ROOT / v17_gate.REPORT).read_text("utf-8"))
    v17_receipt_fresh = v17 == saved_v17
    a = analog.build()
    t = timing.build()
    if a["status"] != "ANALOG_SAFETY_NOT_QUALIFIED":
        raise ValueError("D0 analog review semantics changed; independent review required")
    if t["is_worst_case"] is not False or t["hardware_protection_approved"] is not False:
        raise ValueError("D0 timing/approval assumptions changed; independent review required")
    # Checks of CAD connectivity and reports cannot authorize energized hardware.
    return {
        "kind": "D1_LANE_C_ISSUE_133_G0_G1",
        "status": "NOT_FOR_FAB_G0_BLOCKED_G1_PENDING",
        "base_commit": "27b101c1e7e4135f0fd6e2f016ca5a4ae32dc018",
        "input_pcb_sha256": BASELINE_SHA,
        "input_schematic_sha256": sha(D0_SCH),
        "input_netlist_sha256": sha(D0_NET),
        "output_pcb_sha256": None,
        "pcb_modified": False,
        "changed_nets": [],
        "native_drc_before_after": {"baseline_unconnected_reported": v17["stages"][-1]["unconnected"],
                                    "baseline_ignored_native_drc_checks": v17["stages"][-1]["ignored_drc_checks"],
                                    "original_aggregate_receipt_fresh": v17_receipt_fresh,
                                    "lane_c_after": None,
                                    "native_drc_rerun": "PENDING"},
        "copper_thickness_and_RMS_assumptions": "UNKNOWN; no 100 A thermal qualification",
        "structure_audit": {"ten_gate_channels_present": True,
                            "sr_driver_channels": 8, "primary_driver_channels": 2,
                            "individual_gate_wiring_checked": True,
                            "selected_pins_exported_kicad_netlist_checked": net_pins,
                            "cached_export_is_live_erc": False,
                            "enable_pulldowns": 8,
                            "r45_v12p_to_permit": "DNP_REQUIRED",
                            "bench_bootstrap_c29_to_pgnd": "NOT_VALIDATED_FOR_REAL_HS",
                            "main_board_pin_parity_proven": False,
                            "d0_original_sr_controller_parity_proven": False},
        "channels": channels,
        "physical_high_side_reference_audit": physical_reference,
        "existing_evidence": {
            "analog_review": a["status"],
            "timing_review": t["status"],
            "timing_worst_case": t["is_worst_case"],
            "timing_lm393_max": t["stages"]["comparator"]["published_max_us"],
            "hardware_protection_approved": False,
        },
        "fault_injections": [
            {"mode": mode, "status": "PENDING", "raw_waveforms": None,
             "actual_vgs_all_10_verified": False}
            for mode in fault_matrix.MODES
        ],
        "g0_blockers": [
            "Complete A-Lane primary nets and true physical CT/T1-T4 pin/DOT mapping not integrated",
            "Real 48V-to-12V primary/secondary driver bias supply, isolation and startup/UVLO limits not established",
            "D0 is a bench replacement with eight UCC27524ADR outputs, not pin-equivalent to original UCC24624 SR system",
            "U18 DRC pin 5 HS is physically tied to pin 9 VSS/PGND in the D0 bench; C29 negative and R64 return also use PGND. Correct the real floating-high-side source reference before power-on",
            "Loss of V12S leaves ten-kilohm passive SR gate discharge; no worst-case safe-off time/overlap proof",
            "Independent hardware supply-loss AND E-stop interlock and power-stage disconnection not demonstrated",
            "LM393 and logic response have unbounded timing corners; per-gate safe-off limits and device SOA unqualified",
            "D17/GSMAX is ground-referred indication, not a differential GH1-to-HS VGS safety measurement",
            "Board source still has seven unconnected items and five ignored DRC checks; no independent native parity/DRC closure",
            "Original V17 consolidated receipt freshness must be restored by integrator (Lane C does not rewrite shared evidence)",
            "No signed BOM, ERC, real hardware inspection, raw fault captures, or effective temporary cooling verification",
        ],
        "g1_blockers": [
            "G0 not accepted",
            "No measured cold startup/steady output polarity, voltage, current, primary and secondary VGS",
            "No ten-channel bias-loss and fault-injection records",
            "No temperature/supply current/overcurrent and emergency-stop oscilloscope evidence",
        ],
        "gate_0_approved": False,
        "gate_1_measured_success": False,
        "fab_approved": False,
        "energization_allowed": False,
        "incomplete_claims_must_remain_pending": True,
        "validation_commands": [
            "python tools/d1_lane_c_g0_gate.py --check",
            "python -m pytest tools/d1_lane_c_test_g0_gate.py -q",
            "python tools/d1_v17_oem_copper_gate.py --check",
            "python -m pytest tools/test_d1_v17_oem_copper_gate.py -q",
        ],
        "commit": "PENDING",
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--require-g0", action="store_true")
    args = parser.parse_args()
    report = build()
    serialized = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(serialized, encoding="utf-8")
    elif args.check and (not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != serialized):
        print("Lane C G0 audit missing or stale", file=sys.stderr)
        return 1
    elif args.require_g0:
        print("G0 BLOCKED: structural audit cannot authorize hardware energization", file=sys.stderr)
        return 1
    print(report["status"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
