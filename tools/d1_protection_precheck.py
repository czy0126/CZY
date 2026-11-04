"""D1 independent hard-fault protection *interface* verification.

This checks pin functions and the candidate-to-existing-net ECO contract only.
It deliberately MUST NOT claim a hardware protection design is implemented.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
SPEC=ROOT/"hardware/dcx_main/protection_interface_candidate.json"
NATIVE=ROOT/"hardware/dcx_main/gen/netlist_export_raw.json"
REPORT=ROOT/"hardware/dcx_main/protection_precheck_report.json"

def build(spec=None, nets=None) -> dict:
    if spec is None: spec=json.loads(SPEC.read_text(encoding="utf-8"))
    if nets is None:
        exported=json.loads(NATIVE.read_text(encoding="utf-8"))
        if not exported.get("ok"): raise ValueError("native EDA export missing")
        nets=exported["value"]["refs"]
    errors=[]
    primary=spec["native_primary"]
    if nets.get("U2",{}).get("6")!="RUN": errors.append("U2 DRC EN pin6 no longer RUN")
    if nets.get("R7")!={"1":"RUN","2":"PGND"}: errors.append("R7 default-low net changed")
    if nets.get("R8")!={"1":"VCC12","2":"RUN"}: errors.append("R8 always-high hazard changed; re-review ECO")
    if primary["pullup_ohm"]!=1000 or primary["pulldown_ohm"]!=10000:
        errors.append("current RUN divider no longer 1k/10k")
    if primary["shorted_pullup_dissipation_w"]<0.14:
        errors.append("understated R8 short-to-ground dissipation")
    expected={f"SR{i}{ab}" for i in range(1,5) for ab in ("A","B")}
    got={ch["sr"] for ch in spec["proposed_sr_channels"]}
    if len(spec["proposed_sr_channels"])!=8 or got!=expected:
        errors.append("not precisely all eight SRs")
    # A per-channel uniqueness check is insufficient: swapping two complete
    # channels, aliasing both output nets, or using a wrong INA/EN pad can still
    # appear one-to-one. Lock this candidate to the OEM UCC27524A SOIC-8
    # pinout and the *actual* eight controller/gate-resistor identities.
    # A different buffer/footprint requires a new independently reviewed map.
    expected_driver_mpn="UCC27524ADR"
    if any(part!=expected_driver_mpn for part in spec["proposed_sr_drivers"].values()):
        errors.append("proposed buffer MPN changed; OEM pinout must be requalified")
    driver_pins=set()
    used_rg=set()
    for ch in spec["proposed_sr_channels"]:
        sr=ch["sr"]
        if sr not in expected:
            continue
        group=int(sr[2])
        side=sr[-1]
        expected_route={
            "controller":f"U{group+2}",
            "controller_output_pin":"1" if side=="A" else "8",
            "controller_output_net":f"VG{group}_{side}",
            "proposed_buffer":f"U{group+6}",
            "buffer_channel":side,
            "buffer_input_pin":"2" if side=="A" else "4",
            "buffer_output_pin":"7" if side=="A" else "5",
            "buffer_output_net":f"SRBUF{group}_{side}",
            "buffer_enable_pin":"1" if side=="A" else "8",
            "buffer_enable_net":"SR_SAFE_PERMIT",
            "buffer_power_pin":"6",
            "buffer_power_net":"VCC12_S",
            "buffer_ground_pin":"3",
            "buffer_ground_net":"PGND",
            "native_gate_resistor":f"R{18+2*group+(side=='B')}",
            "native_gate_resistor_input_net":f"VG{group}_{side}",
            "native_gate_resistor_output_net":f"G{side}{group}",
            "mos_gate_net":f"G{side}{group}",
            "mos_source_net":"PGND",
        }
        for field, expected_value in expected_route.items():
            if ch.get(field)!=expected_value:
                errors.append(f"{sr}: {field} is {ch.get(field)!r}; expected {expected_value!r}")
        if ch["proposed_buffer"] not in spec["proposed_sr_drivers"]:
            errors.append(sr+": no valid proposed buffer")
        if ch["buffer_enable_net"]!="SR_SAFE_PERMIT" or ch["physical_application_status"]!="NOT_IMPLEMENTED_IN_NATIVE_CAD":
            errors.append(sr+": missing fail-closed physical status")
        if ch["mos_source_net"]!="PGND" or not ch["buffer_output_net"].startswith("SRBUF"):
            errors.append(sr+": invalid referenced gate wiring")
        ctrl=nets.get(ch["controller"],{})
        if ctrl.get(ch["controller_output_pin"])!=ch["controller_output_net"]:
            errors.append(sr+": UCC24624 source pin moved")
        rg=ch["native_gate_resistor"]
        raw_rg=nets.get(rg,{})
        if raw_rg!={"1":ch["native_gate_resistor_input_net"],
                       "2":ch["native_gate_resistor_output_net"]}:
            errors.append(sr+": Rg connection mismatch")
        sr_nets=nets.get(sr,{})
        if sr_nets.get("4")!=ch["mos_gate_net"] or any(sr_nets.get(k)!="PGND" for k in ("1","2","3")):
            errors.append(sr+": MOSFET gate or source mismatch")
        key=(ch["proposed_buffer"],ch["buffer_channel"],ch["buffer_enable_pin"],ch["buffer_output_pin"])
        if key in driver_pins: errors.append(sr+": proposed buffer channel reused")
        driver_pins.add(key)
        if rg in used_rg: errors.append(sr+": Rg reused")
        used_rg.add(rg)
    if len(driver_pins)!=8 or len(used_rg)!=8 or set(spec["proposed_sr_drivers"])!={"U7","U8","U9","U10"}:
        errors.append("four dual drivers not fully one-to-one mapped")
    if any(spec["acceptance_flags"].values()) or spec["fabrication_approved"] or spec["system_status"]!="NOT_IMPLEMENTED_NOT_FOR_FAB":
        errors.append("candidate improperly claims hardware acceptance")
    checks={"native_10_gate_identity_consistent":not errors,
            "r8_permanent_pullup_still_physical_blocker":bool(nets.get("R8") and not primary["native_cad_action_complete"]),
            "four_buffer_drivers_actually_placed":False,
            "all_driver_uvlo_enable_physical_evidence":False,
            "independent_hardware_latch_physically_built":False}
    return {"kind":"PROTECTION_INTERFACE_ENGINEERING_PREFLIGHT",
            "status":"HARDWARE_NOT_IMPLEMENTED" if not errors else "CONTRACT_INVALID",
            "draft_matches_existing_logical_gates":not errors,
            "fabrication_release_approved":False,
            "errors":errors,"checks":checks,
            "warnings":["UCC27282 EN ~1.5us typical disable, not an instant physical kill",
                        "buffer changes UCC24624 proportional analog VG into logic-level gate voltage",
                        "UCC27524A EN has internal pullup and external default-low is still unplaced",
                        "no real CT comparator, latch, physical CAD, vendor SOA, or lab results"]}

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--write",action="store_true")
    p.add_argument("--check",action="store_true")
    opts=p.parse_args()
    r=build()
    body=json.dumps(r,ensure_ascii=False,indent=2)+"\n"
    if opts.write: REPORT.write_text(body,encoding="utf-8",newline="\n")
    elif opts.check and (not REPORT.is_file() or REPORT.read_text(encoding="utf-8")!=body):
        raise SystemExit("protection candidate preflight stale: --write")
    print("D1 protection contract:",r["status"],"proposed 10 gates, 4 dual buffers; hardware not implemented")
    if r["errors"]: raise SystemExit("; ".join(r["errors"]))
    return 0

if __name__=="__main__": raise SystemExit(main())
