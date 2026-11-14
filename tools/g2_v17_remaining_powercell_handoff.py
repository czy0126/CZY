"""Source-hashed V17 native DRC blocker handoff for real power-cell design.

No proposed clearance relaxations, no fabricated release and no assignment
to imaginary agents. A new DRC cannot be silently mistaken for the accepted
baseline: mismatched count/net roster requires a new engineering review.
"""
from __future__ import annotations
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
PCB=G/"dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb"
DRC=G/"g2_v17_KICAD_NATIVE_DRC_NOT_FOR_FAB.json"
META=G/"g2_v17_real_kicad_native_build_NOT_FOR_FAB.json"
OUT=G/"g2_v17_remaining_powercell_drc_handoff_NOT_FOR_FAB.json"
EXPECTED={"SW":7,"VIN_P":2,"GH":1,"GH_DRV":1,"HB":1,"OC":1}

GROUPS=(
    {"group":"primary_switch_node","nets":["SW"],
     "priority":"P0_before_board_release",
     "proposed_action":"Review 48V half-bridge QH/QL, Cr, C5, R18 and U2 switch-node geometry. Draw SHORT, current-qualified local F.Cu shapes and dedicated low-current SW sense pickup; preserve limited SW copper area and creepage.",
     "must_validate":["Native QH/Q L copper and actual OEM drain/source pin mapping",
                      "Hot-loop geometry and commutation inductance / gate return",
                      "Actual 48V input/ripple current, copper thickness, copper temperature",
                      "KiCad native DRC after zone refill and full current-path continuity"],
     "do_not":"Do not join 7 SW ratsnest items with 0.2mm signal traces."},
    {"group":"primary_input_path","nets":["VIN_P"],
     "priority":"P0_before_board_release",
     "proposed_action":"Review J_IN.1 to QH high-side input pins and Cin.1 bypass loop. Use a current-qualified short copper polygon/plane with verified input connector pad geometry and input return.",
     "must_validate":["Actual connector current/contact ratings",
                      "Cin-to-QH/QL high-frequency current-loop impedance",
                      "VIN_P-to-SW/PGND copper clearances and creepage",
                      "Return-path connectivity and thermal/copper cross-section"],
     "do_not":"Do not declare VIN_P complete based on a thin scenic trace."},
    {"group":"high_side_gate_bootstrap","nets":["GH","GH_DRV","HB"],
     "priority":"P0_before_power_up",
     "proposed_action":"Jointly optimize local U2, R4, R18, C5, D_BT, QH placements. Keep GH_DRV and HB bootstrap loops compact and pair their SW return; evaluate a physical relayout before routing across other nets.",
     "must_validate":["Real U2 OEM 0.5mm pitch pad/courtyard before moving",
                      "Gate-loop inductance and turn-off loop overshoot",
                      "Bootstrap charging/return current and nearest physical switch-node pickup",
                      "No fine-pitch via-in-pad, no uncontrolled through-layer gate path"],
     "do_not":"Do not consume a B.Cu multi-via detour to make DRC green without parasitic verification."},
    {"group":"fault_sense_control","nets":["OC"],
     "priority":"P0_before_power_up",
     "proposed_action":"Source and pickup are approximately 58mm apart. Re-evaluate physical OC comparator/control placement, controlled return and shielding, noise immunity and propagation delay rather than auto-connecting a long unguarded switching-adjacent signal.",
     "must_validate":["Protection latency and open-circuit fault behavior",
                      "Kelvin/PGND reference, false-trigger immunity",
                      "Measurement-filter/time-constant and loss-of-signal safe response"],
     "do_not":"Do not substitute a long unverified digital/analog OC trace for a local fault chain."}
)

def sha(p:Path)->str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def generate():
    meta=json.loads(META.read_text("utf8"))
    drc=json.loads(DRC.read_text("utf8"))
    if sha(PCB)!=meta["saved_board_sha256"]:
        raise ValueError("Handoff blocked: meta hash differs from native KiCad PCB")
    count=Counter()
    details={}
    for row in drc["unconnected_items"]:
        names=[re.findall(r"\[([^\]]+)\]",it["description"])
               for it in row["items"]]
        nets=sorted(set(x for xs in names for x in xs if x!="<no net>"))
        if len(nets)!=1:
            raise ValueError("DRC ratsnest row has ambiguous cross-net identity "+str(nets))
        net=nets[0]
        count[net]+=1
        details.setdefault(net,[]).append([
            {"description":x["description"],"position_mm":x.get("pos")}
            for x in row["items"]])
    if dict(count)!=EXPECTED:
        raise ValueError("Native DRC remaining nets drift: "+str(dict(count)))
    if Counter(v["type"] for v in drc["violations"])!=Counter({"clearance":2}):
        raise ValueError("Native DRC has new unscreened violations")
    if any(not any("U2" in item["description"] for item in v["items"])
           for v in drc["violations"]):
        raise ValueError("Native violations no longer confined to U2")
    if meta["real_fabrication_release"]:
        raise ValueError("Cannot generate provisional blockers for released PCB")
    result={
        "status":"SOURCE_LOCKED_NATIVE_DRC_REMAINING_ISSUES_NOT_FOR_FAB",
        "audit_local_date":"2026-11-14",
        "owner_assignment":"UNASSIGNED_REQUIRES_USER_COORDINATION",
        "project_branch":"feat/d1-v17-agent-a-signals-20261113",
        "board_relative_path":PCB.relative_to(ROOT).as_posix(),
        "native_board_sha256":sha(PCB),
        "native_drc_sha256":sha(DRC),
        "native_meta_sha256":sha(META),
        "kicad_version":drc["kicad_version"],
        "unconnected_total":sum(count.values()),
        "by_net":dict(sorted(count.items())),
        "net_endpoints":details,
        "remaining_violation_types":dict(Counter(v["type"] for v in drc["violations"])),
        "remaining_native_U2_violations":[{"description":v["description"],
            "items":[it["description"] for it in v["items"]]} for v in drc["violations"]],
        "groups":list(GROUPS),
        "additional_hard_gates":[
            "T1-T4/CT 3:1:1 real PCB windings and OEM DOTs, not placeholder rectangles",
            "100A paired copper busbar, output multi-contact terminal and parasitic thermal verification",
            "Schematic-to-native-pad parity (empty reported parity != authenticated parity)",
            "Actual 12-layer stackup and via-in-pad filled/capped vendor process",
            "Maxwell extraction/mesh independence, SR recovery/current sharing and real EMI/thermal validation"],
        "fab_release":False,
        "whole_board_drc_green":False,
        "simulated_power_electronics_verified":False
    }
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"remaining":result["unconnected_total"],
        "net_count":len(result["by_net"]),
        "violations":sum(result["remaining_violation_types"].values()),
        "groups":[x["group"] for x in result["groups"]]},ensure_ascii=False))
    return result

if __name__=="__main__":
    generate()
