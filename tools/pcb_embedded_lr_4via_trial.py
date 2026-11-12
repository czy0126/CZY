"""Independent native KiCad multi-via PCB-embedded Lr routing experiment.

Create a NEW, non-overwriting native six-layer PCB with three additional PTH
vias per series transition (4 vias per transition, 8 total). Two tracks on
the preceding turn's layer pair connect the additional via sites, and the
following turn's layer pair already runs under the same sites. This is
a local return-leg modification, not a qualified 100C/200kHz current divider.

    python tools/pcb_embedded_lr_4via_trial.py --write
    python tools/pcb_embedded_lr_4via_trial.py --check
    python tools/pcb_embedded_lr_4via_trial.py --drc

Parent 2-via original remains byte-identical. Each via is THROUGH all six
copper layers; independent geometry rejection of third-turn shorts is crucial.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

import pcb_embedded_lr as native
import pcb_embedded_lr_dfm as dfm

ROOT=native.ROOT
BOARD=native.OUT/"ELP38_Lr_3turn_PCB_EMBEDDED_4VIAS_PER_TRANSITION_TRIAL_NOT_FOR_FAB.kicad_pcb"
REPORT=native.OUT/"ELP38_Lr_3turn_PCB_EMBEDDED_4VIAS_PER_TRANSITION_TRIAL_NOT_FOR_FAB.json"
DRC=native.OUT/"ELP38_Lr_3turn_PCB_EMBEDDED_4VIAS_PER_TRANSITION_TRIAL_NOT_FOR_FAB.drc.txt"
# 4 (one original + 3 added) per transition, 1.5 mm pitch in the
# original following-turn horizontal return-leg axis.
ADDITIONAL=3
PITCH_MM=1.5

def source():
    trial,case,routes,slots,endpoints,report=native.design()
    original=native.PCB.read_text(encoding="utf-8")
    if original!=native.contents()[0]:
        raise ValueError("Original two-via KiCad CAD is stale")
    if len(routes)!=3 or len(endpoints)!=4:
        raise ValueError("Expected full three-series-turn original")
    if original.count("(via (at ")!=2:
        raise ValueError("Expected two series PTH prior to array extension")
    return trial,routes,slots,endpoints,original

def route_sites():
    trial,routes,slots,ends,original=source()
    q=trial["board"]
    width=q["trace_width_mm"]
    radius=q["transition_via_diameter_mm"]/2
    clearance=q["copper_to_copper_clearance_mm"]
    sites=[]
    for bridge_idx in (1,2):
        original_endpoint=ends[bridge_idx]
        added=[(round(original_endpoint[0]-PITCH_MM*k,4),original_endpoint[1])
               for k in range(1,ADDITIONAL+1)]
        preceding=routes[bridge_idx-1]
        following=routes[bridge_idx]
        # New site MUST sit on the following turn's original straight, direct
        # horizontal trace. Otherwise one PTH may be physically unconnected.
        for xy in added:
            assert native.point_distance_to_segment(
                xy,following[0],following[1])<1e-7
            # No barrel may touch any unrelated third turn copper.
            for turn_idx,route in enumerate(routes):
                if turn_idx in (bridge_idx-1,bridge_idx):
                    continue
                closest=min(native.point_distance_to_segment(xy,a,b)
                            for a,b in zip(route,route[1:]))
                if closest+1e-8<radius+width/2+clearance:
                    raise ValueError("New via shorts unrelated 3rd turn")
            for out_port in (ends[0],ends[3]):
                if math.dist(xy,out_port)<radius+q["terminal_pth_diameter_mm"]/2+clearance:
                    raise ValueError("New via touches unrelated external Lr terminal")
            for existing in (ends[1],ends[2]):
                if math.dist(xy,existing)<q["transition_via_diameter_mm"]+clearance:
                    raise ValueError("New PTH overlaps existing transition hole")
            for other_site in (entry["centre_mm"] for entry in sites if "_site_only" in entry):
                if math.dist(xy,other_site)<q["transition_via_diameter_mm"]+clearance:
                    raise ValueError("New via overlaps another via site")
        farthest=added[-1]
        # Added stub follows y=endpoint.y and must be clear of all other
        # nonconsecutive segments of *its own* turn. Same-layer net DRC is
        # blind to a bypass that turns the 3-turn Lr into 2-turn/partial turn.
        for a,b in zip(preceding[:-2],preceding[1:-1]):
            gap=native._same_layer_segment_gap(original_endpoint,farthest,a,b)
            if gap+1e-8<width+clearance:
                raise ValueError("Stub unintentionally shorts own winding turn")
        # All other existing PTH endpoints touch each copper layer; verify
        # the new branch never approaches another series port.
        for i,port in enumerate(ends):
            if i==bridge_idx:
                continue
            need=(q["terminal_pth_diameter_mm"]/2 if i in (0,3)
                  else q["transition_via_diameter_mm"]/2)+width/2+clearance
            if native.point_distance_to_segment(port,original_endpoint,farthest)+1e-8<need:
                raise ValueError("New stub shorts unrelated PTH port")
        sites.append({
            "bridge_index":bridge_idx,
            "original_endpoint_mm":list(original_endpoint),
            "new_vias_mm":[list(p) for p in added],
            "additional_preceding_turn_stubs_on_layers":list(native.GROUPS[bridge_idx-1]),
            "stub_end_mm":list(farthest),
            "clearance_checked":True,
        })
        # Store new vias in a flat vector for spatial checks against the
        # following bridge as well.
        for xy in added:
            sites.append({"centre_mm":xy,"bridge_index":bridge_idx,"_site_only":True})
    plans=[entry for entry in sites if not entry.get("_site_only")]
    assert len(plans)==2
    return trial,plans,original

def contents():
    trial,plans,parent=route_sites()
    q=trial["board"]
    rows=[]
    for bridge in plans:
        k=bridge["bridge_index"]
        start=bridge["original_endpoint_mm"]
        end=bridge["stub_end_mm"]
        for layer in bridge["additional_preceding_turn_stubs_on_layers"]:
            rows.append(
                f'  (segment (start {native.fmt(start[0])} {native.fmt(start[1])}) '
                f'(end {native.fmt(end[0])} {native.fmt(end[1])}) '
                f'(width {native.fmt(q["trace_width_mm"])}) (layer "{layer}") '
                f'(net 1) (uuid "{native._id(f"multi_via_stubs/{k}/{layer}")}"))'
            )
        for vi,xy in enumerate(bridge["new_vias_mm"],1):
            rows.append(
                f'  (via (at {native.fmt(xy[0])} {native.fmt(xy[1])}) '
                f'(size {native.fmt(q["transition_via_diameter_mm"])}) '
                f'(drill {native.fmt(q["transition_via_drill_mm"])}) '
                f'(layers "F.Cu" "B.Cu") (net 1) '
                f'(uuid "{native._id(f"multi_via/{k}/{vi}")}"))'
            )
    assert parent.endswith(")\n")
    child=parent[:-2]+"\n".join(rows)+"\n)\n"
    assert child.count("(via (at ")==8
    assert child.count("(segment (start ")==46
    losses=dfm.evaluate()[0]
    report={
        "schema":"D1_ELP38_NATIVE_MULTIVIA_3TURN_6LAYER_TRIAL_V1",
        "status":"NATIVE_KICAD_ADDITIONAL_VIA_ARRAY_NOT_CURRENT_QUALIFIED_NOT_FOR_FAB",
        "parent_two_via_board_sha256":hashlib.sha256(parent.encode("utf-8")).hexdigest(),
        "result_kicad_board_sha256":hashlib.sha256(child.encode("utf-8")).hexdigest(),
        "source_assumptions_sha256_lf":dfm.sha_lf(dfm.ASSUMPTIONS),
        "bridge_groups":plans,
        "series_via_groups":2,
        "vias_per_transition":4,
        "total_transition_PTH":8,
        "new_tracks":4,
        "new_PTH":6,
        "all_through_holes_on_all_six_copper_layers":True,
        "parent_3turn_kinematic_and_CORE_slots_preserved":True,
        "self_short_and_non_adjacent_through_barrel_screen_passed":True,
        "ideal_100c_single_via_rated_dc_loss_W_at_25um":next(x["single_via_Pdc_rated_W"]
              for x in losses["via_plating_sensitivity"] if x["trial_barrel_thickness_um"]==25),
        "ideal_equal_sharing_four_vias_pdc_series_pair_W_UNQUALIFIED":round(
            next(x["two_vias_series_Pdc_rated_W"] for x in losses["via_plating_sensitivity"]
                 if x["trial_barrel_thickness_um"]==25)/4,6),
        "real_current_distribution_among_vias_verified":False,
        "new_stubs_and_turn_2_effective_path_inductance_verified":False,
        "plated_barrel_min_thickness_and_reliability_verified":False,
        "nonlinear_N97_100C_and_200kHz_AC_loss_verified":False,
        "manufacturable_electric_insulation_and_16mm_height_verified":False,
        "manufacturer_first_article_approved":False,
        "power_board_CAD_integrated":False,
        "fabrication_approved":False,
    }
    return child,json.dumps(report,ensure_ascii=False,indent=2)+"\n"

def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    g.add_argument("--drc",action="store_true")
    a=p.parse_args()
    if a.drc:
        from main_board_mechanical import find_kicad_cli
        cli=find_kicad_cli()
        if not cli:raise SystemExit("NO local KiCad10 CLI; no native DRC")
        proc=subprocess.run([str(cli),"pcb","drc","--all-track-errors","-o",str(DRC),str(BOARD)],
                            capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=130)
        print(proc.stdout[-1500:],proc.stderr[-1000:])
        return proc.returncode
    board,report=contents()
    if a.write:
        BOARD.write_text(board,encoding="utf-8",newline="\n")
        REPORT.write_text(report,encoding="utf-8",newline="\n")
    if a.check:
        if not BOARD.is_file() or BOARD.read_text(encoding="utf-8")!=board:
            raise SystemExit("4-via KiCad native candidate stale/missing")
        if not REPORT.is_file() or REPORT.read_text(encoding="utf-8")!=report:
            raise SystemExit("4-via source-bound report stale/missing")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
