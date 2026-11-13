"""Write an actual *KiCad 10* editable V17 engineering board from frozen V15 data.

Execute with KiCad bundled Python 3.11, not Anaconda:
    C:/Users/.../KiCad/10.0/bin/python.exe tools/g2_v17_generate_kicad.py

This script takes the 149 genuine EasyEDA V15 source component PAD locations,
nets and pad numbers, places them at tested V17 XY, and gives real KiCad
footprints, Edges, native 12 copper layer setup, actual PGND/VOUT via objects,
and filled native copper zones. It does not have OEM footprints/3:1:1 windings
and cannot substitute for their manufacture or any EMC testing. NO GERBER.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

import pcbnew as pcb

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
SOURCE=G/"dcx_main_board_g2_V15_T4_POWER_CELL_UP30MM_WIP_NOT_FOR_FAB.eprj2"
READ=G/"g2_v15_after_T4_move_native_readback_NOT_FOR_FAB.json"
SLOTS=G/"g2_v14_through_board_three_leg_slot_DFM_screen_NOT_FOR_FAB.json"
LAYOUT=G/"g2_v17_compact_emc_first_screen_LOCKED_NOT_FOR_FAB.json"
COPPER=G/"g2_v17_integrated_pgnd_vout_review_LOCKED_NOT_FOR_FAB.json"
SIGNAL=G/"g2_v17_signal_legal_route_plan_NOT_FOR_FAB.json"
BRIDGE=G/"g2_v17_bcu_short_control_bridges_NOT_FOR_FAB.json"
GD_ESCAPE=G/"g2_v17_u2_gd1_gd2_layer_escape_NOT_FOR_FAB.json"
LOCAL_GATE=G/"g2_v17_local_primary_gate_routes_NOT_FOR_FAB.json"
SOURCE_SHA="02d59c63c747678849466cc62565c1522bc50586a7dadc06b0829016ab601e75"
CORE_X=(20.,58.,96.,134.)

def sha(file):return hashlib.sha256(file.read_bytes()).hexdigest()
def loadjson(file):return json.loads(file.read_text("utf8"))
def initial_xy(c):return (c["X"]*.0254,-c["Y"]*.0254)

OUTPUT=ROOT/"hardware/dcx_main/g2/dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb"
META=ROOT/"hardware/dcx_main/g2/g2_v17_real_kicad_native_build_NOT_FOR_FAB.json"
VERSION_TAG="2026-11-13-V17"
PU=pcb.FromMM

def xy(x,y):
    return pcb.VECTOR2I(PU(x),PU(y))

def addnet(board,name):
    n=pcb.NETINFO_ITEM(board,name)
    board.Add(n)
    return n

def native_pad(ref,rec,original,xynew):
    x0,y0=original
    tx,ty=xynew
    x=tx+rec["X"]*.0254-x0
    y=ty-rec["Y"]*.0254-y0
    if ref.startswith("CHB") and tx>86:
        x=tx-(rec["X"]*.0254-x0)
        y=ty-(-rec["Y"]*.0254-y0)
    return x,y

def add_native_footprint(board,comp,rec,site,net_objs):
    ref=comp["ref"]
    old=initial_xy(comp)
    f=pcb.FOOTPRINT(board)
    f.SetReference(ref)
    f.SetValue("V15_PROVISIONAL_CAD_ONLY")
    # Library reference intentionally provisional: user's real OEM footprint
    # is not supplied. All measured source PAD dimensions and numbers retained.
    f.SetPosition(xy(*site))
    backside=rec and all(p["Layer"]==2 for p in rec)
    f.SetLayer(pcb.B_Cu if backside else pcb.F_Cu)
    f.Reference().SetVisible(False)
    f.Value().SetVisible(False)
    local_shapes=[]
    for q in rec:
        pad=pcb.PAD(f)
        pad.SetNumber(str(q["PadNumber"]))
        shape=q["Pad"][0]
        if shape=="RECT" or shape=="POLYGON":
            pad.SetShape(pcb.PAD_SHAPE_RECT)
        elif shape=="OVAL":
            pad.SetShape(pcb.PAD_SHAPE_OVAL)
        elif shape=="ELLIPSE":
            pad.SetShape(pcb.PAD_SHAPE_CIRCLE if abs(q["Pad"][1]-q["Pad"][2])<1e-6 else pcb.PAD_SHAPE_OVAL)
        else:
            raise ValueError(("Unsupported real pad shape",ref,shape))
        if shape=="POLYGON":
            data=[a for a in q["Pad"][1] if isinstance(a,(int,float))]
            xs=[data[i]*.0254-old[0]+site[0] for i in range(0,len(data)-1,2)]
            ys=[-data[i]*.0254-old[1]+site[1] for i in range(1,len(data),2)]
            x,y=(min(xs)+max(xs))/2,(min(ys)+max(ys))/2
            w,h=max(xs)-min(xs),max(ys)-min(ys)
        else:
            x,y=native_pad(ref,q,old,site)
            w=q["Pad"][1]*.0254
            h=(q["Pad"][2]*.0254 if len(q["Pad"])>2 else w)
        pad.SetPosition(xy(x,y))
        pad.SetSize(xy(w,h))
        if shape!="POLYGON":pad.SetOrientationDegrees(float(q.get("Rotation",0)))
        if q["Layer"]==12:
            pad.SetAttribute(pcb.PAD_ATTRIB_PTH)
            drill=.70 if ref=="J_OUT" else 1.0
            pad.SetDrillSize(xy(drill,drill))
            layer_set=pcb.LSET.AllCuMask()
            layer_set.AddLayer(pcb.F_Mask)
            layer_set.AddLayer(pcb.B_Mask)
        else:
            pad.SetAttribute(pcb.PAD_ATTRIB_SMD)
            layer_set=pcb.LSET()
            if q["Layer"]==2:
                for layer in (pcb.B_Cu,pcb.B_Mask,pcb.B_Paste): layer_set.AddLayer(layer)
            else:
                for layer in (pcb.F_Cu,pcb.F_Mask,pcb.F_Paste): layer_set.AddLayer(layer)
        pad.SetLayerSet(layer_set)
        net=q["Net"]
        if net:
            pad.SetNet(net_objs[net])
        # With the revised narrow signal channels, two local low-current
        # PGND reference resistors have only one viable F.Cu thermal spoke.
        # Join THESE pads solidly to their existing PGND zone instead of
        # weakening the DRC thermal-spoke rule for the whole board. Assembly
        # solderability and thermal wicking still require OEM review.
        if net=="PGND" and (ref,str(q["PadNumber"])) in {("R1","2"),("R10","2")}:
            pad.SetLocalZoneConnection(pcb.ZONE_CONNECTION_FULL)
        f.Add(pad)
        local_shapes.append((x,y,w,h))
    # Trial courtyard from PAD envelope plus .45mm; not 3D/OEM.
    # 72 CHB parts have OEM trial 7.7x4.7 mm and mirror.
    if ref.startswith("CHB"):
        halfx,halfy=3.85,2.35
        ax,ay,bx,by=site[0]-halfx,site[1]-halfy,site[0]+halfx,site[1]+halfy
    else:
        ax=min(x-w/2 for x,y,w,h in local_shapes)-.45
        bx=max(x+w/2 for x,y,w,h in local_shapes)+.45
        ay=min(y-h/2 for x,y,w,h in local_shapes)-.45
        by=max(y+h/2 for x,y,w,h in local_shapes)+.45
    edge=pcb.PCB_SHAPE(f)
    edge.SetShape(pcb.SHAPE_T_RECT)
    edge.SetStart(xy(ax,ay))
    edge.SetEnd(xy(bx,by))
    edge.SetLayer(pcb.B_CrtYd if backside else pcb.F_CrtYd)
    edge.SetWidth(PU(.05))
    f.Add(edge)
    board.Add(f)
    return f

def rect(board,layer,a,b,width=.05):
    e=pcb.PCB_SHAPE(board)
    e.SetShape(pcb.SHAPE_T_RECT)
    e.SetStart(xy(*a));e.SetEnd(xy(*b))
    e.SetLayer(layer);e.SetWidth(PU(width))
    board.Add(e)
    return e

def message(board,text,loc,size=1.2,layer=pcb.Dwgs_User):
    t=pcb.PCB_TEXT(board)
    t.SetText(text)
    t.SetPosition(xy(*loc))
    t.SetLayer(layer)
    t.SetTextSize(xy(size,size))
    t.SetTextThickness(PU(.16))
    board.Add(t)
    return t

def via(board,v,net_obj,annulus=.70,drill=.30):
    q=pcb.PCB_VIA(board)
    q.SetPosition(xy(v["x_mm"],v["y_mm"]))
    q.SetWidth(PU(annulus))
    q.SetDrill(PU(drill))
    q.SetLayerPair(pcb.F_Cu,pcb.B_Cu)
    q.SetNet(net_obj)
    board.Add(q)
    return q

def zone(board,net,layer,region,clearance=.19):
    z=pcb.ZONE(board)
    z.SetNet(net)
    z.SetLayer(layer)
    z.SetLocalClearance(PU(clearance))
    z.SetThermalReliefGap(PU(.28))
    z.SetThermalReliefSpokeWidth(PU(.26))
    points=z.Outline()
    points.NewOutline()
    x0,y0,x1,y1=region
    for x,y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1)):
        points.Append(PU(x),PU(y))
    board.Add(z)
    return z

def segment(board,net,layer,loc1,loc2,width=.5):
    q=pcb.PCB_TRACK(board)
    q.SetStart(xy(*loc1))
    q.SetEnd(xy(*loc2))
    q.SetLayer(layer)
    q.SetWidth(PU(width))
    q.SetNet(net)
    board.Add(q)
    return q

def build():
    if sha(SOURCE)!=SOURCE_SHA:raise ValueError("Frozen native V15 source changed")
    layout_model=loadjson(LAYOUT)
    ground_model=loadjson(COPPER)
    if layout_model["cross_net_pad_clearance_fail_count"] or layout_model["trial_nonbank_courtyard_pad_envelope_conflicts"]:
        raise ValueError("Layout hard failures")
    if ground_model["via_to_unlike_net_pad_conflict_count"] or ground_model["via_to_named_plane_fail_count"]:
        raise ValueError("Power via hard failures")
    native=loadjson(READ)["native"]
    slot_model=loadjson(SLOTS)
    placement={ref:tuple(v) for ref,v in layout_model["placements_mm"].items()}
    part_by_ref={x["ref"]:x for x in native["components"]}
    grouped={}
    for row in native["pads"]:
        if row["ref"]:grouped.setdefault(row["ref"],[]).append(row)
    board=pcb.BOARD()
    board.SetCopperLayerCount(12)
    design=board.GetDesignSettings()
    design.SetBoardThickness(PU(2.0))  # UNSIGNED trial; ELP32 window gate remains red
    design.m_MinClearance=PU(.19)
    nets=sorted({r["Net"] for r in native["pads"] if r["Net"]})
    net_obj={n:addnet(board,n) for n in nets}
    for ref in sorted(part_by_ref):
        add_native_footprint(board,part_by_ref[ref],grouped[ref],placement[ref],net_obj)
    rect(board,pcb.Edge_Cuts,(0,0),(155,113),.05)
    for s in slot_model["slots"]:
        rect(board,pcb.Edge_Cuts,
             (s["x_min_mm"],s["y_min_mm"]+13),
             (s["x_max_mm"],s["y_max_mm"]+13),.05)
    for ref,x in zip(["T1","T2","T3","T4"],CORE_X):
        rect(board,pcb.Dwgs_User,(x-16.525,33-10.575),(x+16.525,33+10.575),.1)
        message(board,ref+" - WINDING NOT DESIGNED",(x,33),.95)
    message(board,"V17 PROVISIONAL PAD RECONSTRUCTION - NOT FOR FAB",(81,2),1.12)
    message(board,"PGND/VOUT INNER HF PLANES ONLY; 100A COPPER BAR NOT DESIGNED",(85,110),.83)
    # Native KiCad copper layers - front/inner plane/back. No fabricated
    # T1-T4 3:1:1 windings, no false mapping of OEM DOT.
    all_critical=(ground_model["planned_via_in_pad_sites"]+
                  ground_model["additional_local_driver_reg_pgnd_and_Cout_stitches"]+
                  ground_model["control_U1_U2_PGND_via_sites"]+
                  ground_model["auxiliary_12V_S_and_12V_via_sites"]+
                  ground_model["auxiliary_pgnd_return_via_sites"]+
                  ground_model["control_U1_VCC12_feed_via_sites"])
    for v in all_critical:
        via(board,v,net_obj[v["net"]])
    # Trial isolated primary decoupling PGND to QL: actually routed segment.
    primary=ground_model["input_pgnd_to_QL_pad_target"]
    segment(board,net_obj["PGND"],pcb.F_Cu,
            primary["path_mm"][0],primary["path_mm"][1],primary["width_mm"])
    u2_ground_link=ground_model["control_U2_pgnd9_to_exposed_pgnd11_link"]
    segment(board,net_obj["PGND"],pcb.F_Cu,
            u2_ground_link["path_mm"][0],u2_ground_link["path_mm"][1],
            u2_ground_link["width_mm"])
    signal_model=loadjson(SIGNAL)
    if signal_model["source_V15_sha"]!=sha(SOURCE) or signal_model["source_V17_sha"]!=sha(LAYOUT):
        raise ValueError("Signal route generated from stale source PCB")
    if signal_model["routed_signal_edge_count"]>70:
        raise ValueError("Unexpected signal route overgeneration")
    for route in signal_model["segments"]:
        if route["net"] not in net_obj:raise ValueError("unknown routed network")
        for points in route["segments"]:
            segment(board,net_obj[route["net"]],pcb.F_Cu,points[0],points[1],route["width_mm"])
    # Three source-locked short low-current bridges, reserved exclusively
    # for B.Cu and screened independently against both sides' real pads,
    # front signal tracks, and already reserved PGND/VOUT vias. This does
    # NOT authorize long OC/fast-GD control routes or bypass native DRC.
    bridge_model=loadjson(BRIDGE)
    if (bridge_model["source_v15_sha"]!=sha(SOURCE)
        or bridge_model["source_v17_sha"]!=sha(LAYOUT)
        or bridge_model["source_signal_sha"]!=sha(SIGNAL)):
        raise ValueError("B.Cu bridge source/signal drift")
    for bridge in bridge_model["bridges"]:
        net=bridge["net"]
        if net not in ("RT","CS2","OCM"):
            raise ValueError("Unauthorized B.Cu bridge net "+net)
        for v in bridge["via_sites"]:
            found=[pad for footprint in board.GetFootprints()
                   if footprint.GetReference()==v["ref"]
                   for pad in footprint.Pads()
                   if pad.GetNumber()==v["pad"] and pad.GetNetname()==net]
            if len(found)!=1:
                raise ValueError("Ambiguous real pad for B.Cu via "+v["ref"]+"."+v["pad"])
            real=found[0].GetPosition()
            if math.dist((pcb.ToMM(real.x),pcb.ToMM(real.y)),
                         (v["x_mm"],v["y_mm"]))>.015:
                raise ValueError("B.Cu via site drifted off native pad "+v["ref"])
            via(board,v,net_obj[net],annulus=.70,drill=.30)
        for points in bridge["segments"]:
            segment(board,net_obj[net],pcb.B_Cu,points[0],points[1],
                    bridge["width_mm"])
    # Complete real U2 GD1/GD2 fine-pitch escape on separate F/B layers.
    # U2.8 has 0.5-mm pin pitch; NO 0.70-mm drill in its pad. The GD2
    # via is away from U2, and a separate thru-via returns at R10.1.
    # Source-locked geometry preflight independently checks both-net copper.
    gd_model=loadjson(GD_ESCAPE)
    required_sha={"source_native_sha":sha(SOURCE),
                  "source_layout_sha":sha(LAYOUT),
                  "source_signal_sha":sha(SIGNAL),
                  "source_bcu_sha":sha(BRIDGE),
                  "source_pgnd_sha":sha(COPPER)}
    if any(gd_model.get(k)!=v for k,v in required_sha.items()):
        raise ValueError("U2 GD1/GD2 source projection is outdated")
    if [r["net"] for r in gd_model["routes"]] != ["GD1","GD2","GD2"]:
        raise ValueError("Unexpected U2 breakout net inventory")
    for v in gd_model["via_sites"]:
        if v["ref"]!="U2_ESC_GD2":
            matched=[pad for footprint in board.GetFootprints()
                     if footprint.GetReference()==v["ref"]
                     for pad in footprint.Pads()
                     if pad.GetNumber()==v["pad"] and pad.GetNetname()==v["net"]]
            if len(matched)!=1 or math.dist(
                (pcb.ToMM(matched[0].GetPosition().x),
                 pcb.ToMM(matched[0].GetPosition().y)),
                (v["x_mm"],v["y_mm"]))>.015:
                raise ValueError("GD2 via is not attached to real terminal "+v["ref"])
        via(board,v,net_obj[v["net"]],annulus=.70,drill=.30)
    for route in gd_model["routes"]:
        layer={"F.Cu":pcb.F_Cu,"B.Cu":pcb.B_Cu}[route["layer"]]
        for a,b in route["segments"]:
            segment(board,net_obj[route["net"]],layer,a,b,route["width_mm"])
    # Five short, independent source-locked local primary driver/FET
    # links. The remaining high-side drive and 48-V SW/VIN power loop
    # are deliberately *unconnected*, never faked by skinny traces.
    gate_model=loadjson(LOCAL_GATE)
    gate_shas={"source_v15_sha":sha(SOURCE),
               "source_v17_sha":sha(LAYOUT),
               "source_pgnd_sha":sha(COPPER),
               "source_signal_sha":sha(SIGNAL),
               "source_bcu_sha":sha(BRIDGE),
               "source_gd_sha":sha(GD_ESCAPE)}
    if any(gate_model.get(k)!=v for k,v in gate_shas.items()):
        raise ValueError("Local gate candidate stale relative to native PAD or GD escape")
    expected_gate_routes=[("GL_DRV","U2.10","R5.1"),
                          ("GH","R4.2","QH.4"),
                          ("GL","R5.2","QL.4"),
                          ("GL","R5.2","R19.1"),
                          ("HB","C5.1","D_BT.1")]
    if [(r["net"],r["from"],r["to"]) for r in gate_model["routes"]] != expected_gate_routes:
        raise ValueError("Local primary gate route identity drift")
    def actual_pad_xy(spec,net):
        ref,num=spec.rsplit(".",1)
        pads=[pad for fp in board.GetFootprints() if fp.GetReference()==ref
              for pad in fp.Pads()
              if pad.GetNumber()==num and pad.GetNetname()==net]
        if len(pads)!=1:raise ValueError("Missing gate terminal "+spec)
        point=pads[0].GetPosition()
        return (pcb.ToMM(point.x),pcb.ToMM(point.y))
    for route in gate_model["routes"]:
        if route["layer"]!="F.Cu" or route["length_mm"]>8:
            raise ValueError("Unqualified long/multilayer primary gate path")
        a=route["segments"][0][0]
        b=route["segments"][-1][1]
        if (math.dist(actual_pad_xy(route["from"],route["net"]),a)>.015
            or math.dist(actual_pad_xy(route["to"],route["net"]),b)>.015):
            raise ValueError("Primary gate track lost real PAD attachment")
        for start,end in route["segments"]:
            segment(board,net_obj[route["net"]],pcb.F_Cu,start,end,route["width_mm"])
    # Keep gate drive and CS/OC Kelvin trunks out of main return copper:
    # ground high frequency plane pair for Cout+SR, local primary input,
    # and discrete top/bottom PGND overlay islands. Zones are real KiCad.
    zone(board,net_obj["PGND"],pcb.In1_Cu,(1.,1.,154.,112.))
    zone(board,net_obj["VOUT"],pcb.In2_Cu,(1.,51.,154.,112.))
    # Low-current +12V copper on separate INNER layers, paired with the
    # adjacent PGND return rather than sharing a broad noisy switch copper.
    zone(board,net_obj["VCC12_S"],pcb.In3_Cu,(2.,44.,153.,64.))
    zone(board,net_obj["VCC12"],pcb.In4_Cu,(2.,2.,153.,24.))
    zone(board,net_obj["PGND"],pcb.F_Cu,(1.,44.,154.,112.))
    zone(board,net_obj["PGND"],pcb.F_Cu,(1.,1.,154.,25.))
    zone(board,net_obj["PGND"],pcb.B_Cu,(1.,44.,154.,112.))
    # Four bottom REG/PGND pairs and the local Cout PGND/VOUT each have
    # source-locked short stitching; never fake these as all of the 100A bus.
    existing={(v["net"],round(v["x_mm"],2),round(v["y_mm"],2)) for v in all_critical}
    # Additional fine-pitch PGND breakouts need their own
    # pad-to-signal-net clearance screen in Python 3.13 (Shapely).
    # Do not guess vias here; 312 already source-locked candidates.
    extra_ground_sites=[]
    for v in extra_ground_sites:
        via(board,v,net_obj["PGND"])
    board.BuildConnectivity()
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    pcb.SaveBoard(str(OUTPUT),board)
    filled=False
    fill_error=None
    try:
        pcb.ZONE_FILLER(board).Fill(board.Zones())
        pcb.SaveBoard(str(OUTPUT),board)
        filled=True
    except Exception as e:
        fill_error=f"{type(e).__name__}: {e}"
    reopened=pcb.LoadBoard(str(OUTPUT))
    real={
        "status":"ACTUAL_KICAD_EDITABLE_BUT_NOT_FOR_FAB",
        "pcb_source_native_Sha256":sha(SOURCE),
        "source_U2_GD_escape_sha256":sha(GD_ESCAPE),
        "source_local_primary_gate_sha256":sha(LOCAL_GATE),
        "kicad_version":pcb.Version(),
        "saved_board":OUTPUT.name,
        "saved_board_sha256":hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
        "board_mm":[155,113],"declared_nominal_board_thickness_mm":2,
        "board_12_layers_real":reopened.GetCopperLayerCount()==12,
        "native_actual_footprints":len(reopened.GetFootprints()),
        "native_actual_footprint_pads":sum(len(fp.Pads()) for fp in reopened.GetFootprints()),
        "native_actual_vias":sum(isinstance(q,pcb.PCB_VIA) for q in reopened.GetTracks()),
        "native_actual_tracks":sum(isinstance(q,pcb.PCB_TRACK) and not isinstance(q,pcb.PCB_VIA) for q in reopened.GetTracks()),
        "native_actual_copper_zones":len(reopened.Zones()),
        "saved_zones_filled":filled,"zone_fill_error":fill_error,
        "native_edge_cut_shapes":sum(q.GetLayer()==pcb.Edge_Cuts for q in reopened.GetDrawings()),
        "native_net_count_including_zero":reopened.GetNetCount(),
        "synchronized_model_pgnd_vias":168,
        "synchronized_model_vout_vias":144,
        "native_extra_pgnd_via_candidate_count":len(extra_ground_sites),
        "conservative_signal_route_count":signal_model["routed_signal_edge_count"],
        "conservative_signal_segment_count":signal_model["segments_count"],
        "short_BCu_control_bridge_count":len(bridge_model["bridges"]),
        "short_BCu_control_via_count":sum(len(b["via_sites"]) for b in bridge_model["bridges"]),
        "auxiliary_pgnd_return_via_count":len(ground_model["auxiliary_pgnd_return_via_sites"]),
        "control_U1_VCC12_feed_via_count":len(ground_model["control_U1_VCC12_feed_via_sites"]),
        "U2_GD1_GD2_fine_escape_segments":sum(len(r["segments"]) for r in gd_model["routes"]),
        "U2_GD1_GD2_fine_escape_via_count":len(gd_model["via_sites"]),
        "local_primary_gate_route_count":len(gate_model["routes"]),
        "local_primary_gate_track_segments":sum(len(r["segments"]) for r in gate_model["routes"]),
        "native_extra_pgnd_stitches":extra_ground_sites,
        "critical_missing":[
           "FOUR 3:1:1 physical PCB winding footprints T1..T4, and CT winding",
           "OEM mechanical sizes and production pad map including DOT polarity",
           "actual 12L copper winding and unverified window thickness",
           "Real part library footprint / U2 irregular thermal polygon approximated by bbox",
           "Via-in-pad fill/cap process with 0.30mm trial mechanical drill (including short B.Cu signal bridges)",
           "U2 fine-pitch GD1/GD2 real escape requires signal-integrity, return loop and manufacturer review",
           "Primary GH_DRV and full VIN_P/SW/HB remain unclosed; no gate-loop inductance or EMC signoff",
           "Actual 100A external/embedded two-pole copper bar; original J_OUT inadequate",
           "Remaining circuitry nets and all P1 schematic parity",
           "Native board full DRC/EMI/thermal, import parity to EasyEDA"
        ],
        "real_fabrication_release":False
    }
    META.write_text(json.dumps(real,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return real

if __name__=="__main__":
    result=build()
    print(json.dumps({k:result[k] for k in (
        "status","kicad_version","native_actual_footprints",
        "native_actual_footprint_pads","native_actual_vias",
        "native_actual_copper_zones","native_actual_tracks",
        "native_edge_cut_shapes","saved_zones_filled",
        "native_extra_pgnd_via_candidate_count",
        "real_fabrication_release"
    )},ensure_ascii=True))
