"""Conservative real-native V9 screen: can via-only 100 A source connect to bars?

Only identifies potential copper-contact sites on actual *top* pads/tracks and
outside all conflicting native-net pads, tracks and vias on either copper layer.
No EDA writes; placement candidate, thermal model, busbar and fabrication
remains NOT_FOR_FAB. Source is exact saved .eprj2 + independent editor reopen.
Run on Linux CI with standard library only.

  python tools/g2_v9_100a_copper_pillar_screen.py --write
  python tools/g2_v9_100a_copper_pillar_screen.py --check
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
G2=ROOT/"hardware/dcx_main/g2"
sys.path[:0]=[str(G2),str(ROOT/"tools")]
import g2_board_keepout as K
import g2_busbar_cad as BAR
import g2_v9_bipolar_mechanical_gate as G

OUT=G2/"g2_v9_100a_native_contact_via_feasibility_NOT_FOR_FAB.json"
VIA_DIAMETER_MM=1.
VIA_DRILL_MM=.4
VIA_PLATING_MM=.025
PITCH_MM=1.6
CLEAR_MM=.3
RANGE_MM=5.
# Sensitivity scenario only, not a signed IPC/vendor current capacity rule.
HYPOTHETICAL_LOSS_PER_POLE_W=.2
BOARD=[155.,131.]


def xy(x,y):
    return (float(x),float(y))


def distseg(p,a,b):
    return K.segment_distance(p,a,b)


def point_to_bar_edge(p,poly):
    return min(distseg(p,a,b) for a,b in zip(poly,poly[1:]+poly[:1]))


def native():
    rows,origin=G.source()
    if origin["source_sha256"]!=G.V9.sha(G.V9.V9):
        raise ValueError("real saved CAD SHA identity lost")
    return rows,origin


def objects(pcb,net):
    obstacles=[]
    top=[]
    via_centres=[]
    for p in pcb["pads"]:
        bbox=K.pad_bbox(p)
        if p["Net"]==net and int(p["Layer"]) in (1,0,11,12):
            top.append(("pad",bbox))
        elif p["Net"]!=net:
            obstacles.append(("pad",bbox))
    for line in pcb["lines"]:
        a=(line["x1"]*.0254,-line["y1"]*.0254)
        b=(line["x2"]*.0254,-line["y2"]*.0254)
        rad=line["width"]*.0254/2
        if line["net"]==net and int(line["layer"])==1:
            top.append(("line",(a,b,rad)))
        elif line["net"]!=net:
            obstacles.append(("line",(a,b,rad,int(line["layer"]))))
    for v in pcb["vias"]:
        centre=(v["x"]*.0254,-v["y"]*.0254)
        rad=v["diameter"]*.0254/2
        via_centres.append((centre,rad,v["net"]))
        if v["net"]!=net:
            obstacles.append(("via",(centre,rad)))
    return obstacles,top,via_centres


def top_overlap(p,top):
    via_radius=VIA_DIAMETER_MM/2
    for typ,geo in top:
        if typ=="pad":
            if K.distance_to_box(p,geo)<=via_radius: return True
        elif typ=="line":
            a,b,rad=geo
            if distseg(p,a,b)<=via_radius+rad:return True
    return False


def clear_native(p,obstacles,all_vias):
    radius=VIA_DIAMETER_MM/2+CLEAR_MM
    for centre,rad,_ in all_vias:
        if math.dist(p,centre)<radius+rad:return False
    for typ,g in obstacles:
        if typ=="pad":
            if K.distance_to_box(p,g)<radius:return False
        if typ=="via":
            centre,rad=g
            if math.dist(p,centre)<radius+rad:return False
        if typ=="line":
            a,b,rad,_=g
            if distseg(p,a,b)<radius+rad:return False
    return True


def anchors(pcb,net):
    pads=pcb["pads"]
    if net=="VOUT":
        rows=[p for p in pads if p["Net"]=="VOUT" and not p.get("ref")
              and p["PadNumber"]=="CTAP"]
        result=[{"group":f"CTAP{i+1}","xy_mm":[round(p["X"]*.0254,3),
                    round(-p["Y"]*.0254,3)]} for i,p in enumerate(rows)]
        if len(result)!=4:raise ValueError("Expected 4 real CTAP source pad lands")
    else:
        rows=[p for p in pads if p["Net"]=="PGND"
              and (p.get("ref") or "").startswith("SR")
              and p.get("PadNumber")=="3"
              and (p["Pad"][0]=="RECT" and p["Pad"][2]>70)]
        result=[{"group":p["ref"],"xy_mm":[round(p["X"]*.0254,3),
                       round(-p["Y"]*.0254,3)]} for p in rows]
        if len(result)!=8:raise ValueError("Expected 8 SR native power source pads")
    return result


def candidates(pcb,net,bar):
    obs,top,all_vias=objects(pcb,net)
    spots=[]
    report=[]
    range_steps=int(RANGE_MM/PITCH_MM)
    for group in anchors(pcb,net):
        center=group["xy_mm"]
        allowed=[]
        for i in range(-range_steps,range_steps+1):
            for j in range(-range_steps,range_steps+1):
                p=(round(center[0]+i*PITCH_MM,4),
                   round(center[1]+j*PITCH_MM,4))
                if math.dist(p,center)>RANGE_MM+.0001:continue
                if not (.8<=p[0]<=BOARD[0]-.8 and .8<=p[1]<=BOARD[1]-.8):
                    continue
                if not BAR.is_inside(p,bar) or point_to_bar_edge(p,bar)<VIA_DIAMETER_MM/2+CLEAR_MM:
                    continue
                if not clear_native(p,obs,all_vias):
                    continue
                if not top_overlap(p,top):continue
                # Duplicate centers or too-close sources are not independent holes.
                if any(math.dist(p,q)<PITCH_MM-.001 for q in spots):continue
                allowed.append([p[0],p[1]])
                spots.append(p)
        report.append({"source":group["group"],"native_anchor_xy_mm":center,
             "potential_via_centers_mm":allowed,"native_top_copper_contact_screened":True,
             "factory_plated_or_bar_attached":False})
    return report


def report():
    pcb,src=native()
    bars=G.BUS.outlines(G.BUS.load())
    output={}
    for net in ("VOUT","PGND"):
        trials=candidates(pcb,net,bars[net])
        count=sum(len(x["potential_via_centers_mm"]) for x in trials)
        # Equal branch currents and equal loss allowance establish one
        # transparent hypothesis, NOT an ampacity specification or measured
        # current sharing. Temperature is 100 C to screen high resistance.
        groups=len(trials)
        per_source_amps=100./groups
        per_source_loss_budget=HYPOTHETICAL_LOSS_PER_POLE_W/groups
        single_100C=G.via_ohm(1,rho=G.RHO_20*(1+G.ALPHA*80),
                    drill_mm=VIA_DRILL_MM,plating_mm=VIA_PLATING_MM)
        target_per_source=math.ceil(single_100C*per_source_amps**2/per_source_loss_budget)
        required=target_per_source*groups
        output[net]={"anchors":trials,
           "hypothetical_per_source_current_A":per_source_amps,
           "hypothetical_per_source_via_loss_budget_W":per_source_loss_budget,
           "minimum_100C_parallel_vias_per_source_arithmetic":target_per_source,
           "candidate_count":count,
           "target_contact_sites_for_one_hypothetical_via_strategy":required,
           "missing_candidate_sites":max(required-count,0),
           "each_source_has_target_count":all(
               len(a["potential_via_centers_mm"])>=target_per_source for a in trials),
           "feasible_via_only_under_current_top_copper":count>=required and all(
               len(a["potential_via_centers_mm"])>=target_per_source for a in trials),
           "actual_pcb_vias_created":0,
           "actual_bar_to_board_conduction_proven":False}
        for temp in (20,100):
            rho=G.RHO_20*(1+G.ALPHA*(temp-20))
            ideal=G.via_ohm(count,rho=rho,drill_mm=VIA_DRILL_MM,
                            plating_mm=VIA_PLATING_MM) if count else None
            output[net][f"ideal_all_{count}_barrels_at_{temp}C"]={
                "ohm":round(ideal,10) if ideal else None,
                "100a_loss_w":round(ideal*10000,4) if ideal else None,
                "all_sources_share_current_evenly_assumption_only":True}
    return {"schema":"G2_V9_REAL_CAD_100A_ELECTRICAL_CONTACT_FEASIBILITY_V1",
       "status":"NATIVE_VIA_ONLY_REJECTED_REDESIGN_POWER_CONNECTIONS",
       "source_native_sha256":src["source_sha256"],
       "source_counts":src["native_counts"],
       "legacy_bars_2d_only_not_actual_bolted_or_soldered_contacts":True,
       "via_OD_mm":VIA_DIAMETER_MM,"via_drill_mm":VIA_DRILL_MM,
       "assumed_via_plating_mm":VIA_PLATING_MM,
       "source_search_radius_mm":RANGE_MM,"pitch_mm":PITCH_MM,
       "unlike_net_clearance_screen_mm":CLEAR_MM,
       "hypothetical_100C_via_only_loss_budget_per_pole_W":HYPOTHETICAL_LOSS_PER_POLE_W,
       "per_source_required_sites_computed_from_loss_and_equal_currents_not_ampacity_standard":True,
       "screen_assumes_perfect_existing_top_copper_via_contact":True,
       "input_PAD_bbox_screen_conservative_for_rotated_shapes":True,
       "P0_redesign_options":[
           "Vendor-confirmed through-board copper pillar/coin with current-rated solder/weld interface, linked to native magnetic winding terminals",
           "Separate top-side plated copper power plate/straps with independent isolation and adjusted <=16mm core/board/coldplate package",
           "Thick-copper or embedded metal bus with source/output via geometry fully re-architected and validated by native DRC+manufacturer stackup"
       ],
       "requires_vendor_DFM_for_drill_copper_fill_solder_wicking_insulation":True,
       "requires_full_3D_mechanical_and_thermal_FE_analysis":True,
       "rated_100A_measured":False,
       "PCB_changed":False,"fabrication_approved":False,
       "results":output}


def main():
    p=argparse.ArgumentParser()
    x=p.add_mutually_exclusive_group(required=True)
    x.add_argument("--write",action="store_true")
    x.add_argument("--check",action="store_true")
    a=p.parse_args()
    r=report()
    body=json.dumps(r,ensure_ascii=False,indent=2)+"\n"
    if a.write:OUT.write_text(body,encoding="utf8",newline="\n")
    elif not OUT.exists() or OUT.read_text("utf8")!=body:
        raise RuntimeError("100A source CAD-contact feasibility evidence stale")
    print(json.dumps({"status":r["status"],"source":r["source_native_sha256"],
          "counts":{k:{"available":v["candidate_count"],
                  "nominal_target":v["target_contact_sites_for_one_hypothetical_via_strategy"],
                  "feasible":v["feasible_via_only_under_current_top_copper"]}
             for k,v in r["results"].items()}},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
