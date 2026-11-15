"""Build source-locked actual KiCad E1 four-cell (200 A *design intent*) electrical
output collection test coupon from the existing V17 SR footprint objects.

EXPLICITLY NOT a working converter, transformer winding, current-qualified
busbar or a candidate for power-on. The artifact tests: geometric placement,
8 real inherited SR pin/net mappings, source-to-PGND top collector, backside
4 CTAP stand-in contacts and VOUT backside collector, closely overlapping
positive/negative planes, independent secondary source pads, and 2.5 mm
coldplate envelope recorded as a mechanical advisory (without coolant).
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import pcbnew as k

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"hardware/dcx_main/g2/d1_lane_a_connectivity/six_net_trial_04_NOT_FOR_FAB.kicad_pcb"
PREV_WINDING=ROOT/"hardware/dcx_main/pcb_winding/ELP38_Lr_3turn_PCB_EMBEDDED_ROUNDED_SLOTS_4VIAS_DFM_NOT_FOR_FAB.kicad_pcb"
OUT_DIR=ROOT/"hardware/dcx_main/g2/d1_lane_a_e1_reuse_coupon"
BOARD_PATH=OUT_DIR/"e1_4cell_200A_pair_collector_copper_coldplate_interface_NOT_FOR_FAB.kicad_pcb"
REPORT_PATH=OUT_DIR/"e1_4cell_200A_pair_collector_reuse_source_locked_NOT_FOR_FAB.json"
SRC_SHA="85fff295c2c8bd594266881b711584be02b40b2158e266e8df4a2ba77d6bb76c"
OLD_WINDING_SHA="00f930a8ece84ac43e3661b47d82853fc8d219d34787cabd126a3463e5bef9a2"
SIDE=102.
HEIGHT=50.
ROW_Y=22.5
SOURCE_PGND_Y=25.32
CU_COUPON=12
LAYER_COPPER_TARGET_UM=70
COLDPLATE_ASSUMPTION_MM=2.5
CELLS=[
 ("1", 16.,24.),
 ("2", 36.,44.),
 ("3", 56.,64.),
 ("4", 76.,84.),
]
def mm(x):return k.FromMM(x)
def vec(x,y):return k.VECTOR2I(mm(x),mm(y))
def pos(obj):p=obj.GetPosition();return (round(k.ToMM(p.x),3),round(k.ToMM(p.y),3))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ensure_sources():
    if sha(SRC)!=SRC_SHA:
        raise ValueError("V17 chosen PCB drift: source-lock invalid")
    if sha(PREV_WINDING)!=OLD_WINDING_SHA:
        raise ValueError("ELP38 4-via board changed: reuse audit needs refresh")
    return k.LoadBoard(str(SRC))
def net(b,name):
    n=k.NETINFO_ITEM(b,name)
    b.Add(n)
    return n
def strip_line(b,n,layer,xy1,xy2,width):
    t=k.PCB_TRACK(b)
    t.SetStart(vec(*xy1));t.SetEnd(vec(*xy2))
    t.SetWidth(mm(width));t.SetLayer(layer);t.SetNet(n)
    b.Add(t)
    return t
def power_footprint(b,ref,net_,xy,layer,size=(4.,3.)):
    f=k.FOOTPRINT(b)
    f.SetReference(ref)
    f.SetValue("E1_POWER_LAND_UNRATED_COUPON_NO_ACTIVE_WINDING")
    f.SetPosition(vec(*xy))
    # No unreadable value/ref text under a solderable power surface.
    # Names remain intact in CAD properties and the generated receipt.
    f.Reference().SetVisible(False)
    f.Value().SetVisible(False)
    pad=k.PAD(f)
    pad.SetNumber("1")
    pad.SetAttribute(k.PAD_ATTRIB_SMD)
    pad.SetShape(k.PAD_SHAPE_RECT)
    pad.SetSize(vec(*size))
    pad.SetPosition(vec(*xy))
    if layer==k.F_Cu:
        pad.SetLayerSet(k.LSET.FrontMask())
    elif layer==k.B_Cu:
        pad.SetLayerSet(k.LSET.BackMask())
    else:raise ValueError("only F/B solderable landing pads")
    pad.SetNet(net_)
    f.Add(pad);b.Add(f)
    return f
def zone(b,n,layer,x0,y0,x1,y1):
    z=k.ZONE(b)
    z.SetLayer(layer);z.SetNet(n)
    z.SetLocalClearance(mm(.25))
    z.SetThermalReliefGap(mm(.25))
    z.SetThermalReliefSpokeWidth(mm(.35))
    q=z.Outline();q.NewOutline()
    for xy in ((x0,y0),(x1,y0),(x1,y1),(x0,y1)):q.Append(mm(xy[0]),mm(xy[1]))
    b.Add(z)
    return z
def segment(b,layer,a,c,width=.05):
    s=k.PCB_SHAPE(b)
    s.SetShape(k.SHAPE_T_SEGMENT)
    s.SetStart(vec(*a));s.SetEnd(vec(*c))
    s.SetLayer(layer);s.SetWidth(mm(width))
    b.Add(s)
def rect(b,layer,x0,y0,x1,y1,width=.05):
    for a,c in [((x0,y0),(x1,y0)),((x1,y0),(x1,y1)),((x1,y1),(x0,y1)),((x0,y1),(x0,y0))]:
        segment(b,layer,a,c,width)
def build():
    source=ensure_sources()
    sf={f.GetReference():f for f in source.GetFootprints()}
    b=k.BOARD()
    b.SetCopperLayerCount(CU_COUPON)
    names=["PGND","VOUT"]
    for cell,_,_ in CELLS:names+=["GA"+cell,"GB"+cell,"SEC"+cell+"_A","SEC"+cell+"_B"]
    nets={n:net(b,n) for n in names}
    orig_pins={}
    for cell,x_a,x_b in CELLS:
        for suffix,x in (("A",x_a),("B",x_b)):
            ref="SR"+cell+suffix
            old=sf[ref]
            # Reuse *actual V17 KiCad footprint instance* and its pad positions.
            old_pad_map=sorted((pad.GetNumber(),pad.GetNetname()) for pad in old.Pads())
            assert len(old_pad_map)==10,ref
            cloned=k.Cast_to_FOOTPRINT(old.Duplicate(False))
            cloned.SetPosition(vec(x,ROW_Y))
            for pad in cloned.Pads():
                name=pad.GetNetname()
                if name not in nets:
                    raise ValueError(f"source pad unmapped {ref}.{pad.GetNumber()}={name}")
                pad.SetNet(nets[name])
            cloned.SetValue("V17_SR_FOOTPRINT_REUSED_UNRATED_NOT_FOR_FAB")
            b.Add(cloned)
            new_pin_map=sorted((pad.GetNumber(),pad.GetNetname()) for pad in cloned.Pads())
            if new_pin_map!=old_pad_map:
                raise ValueError(f"physical V17 SR pin/net mismatch on {ref}")
            orig_pins[ref]=old_pad_map
            sec="SEC"+cell+"_"+suffix
            power_footprint(b,"IN_"+cell+suffix,nets[sec],(x,10.),k.F_Cu,(5.5,3.))
            strip_line(b,nets[sec],k.F_Cu,(x,11.6),(x,19.5),1.25)
            strip_line(b,nets["PGND"],k.F_Cu,(x-1.9,SOURCE_PGND_Y),(x-1.9,32.),.8)
        # Each paired winding's positive center tap is represented only
        # by a B.Cu injection test landing, NOT a physical transformer.
        power_footprint(b,"CTAP_"+cell,nets["VOUT"],((x_a+x_b)/2,37.),k.B_Cu,(6.,7.))
    # The two same-XY output contacts intentionally use opposite *surface*
    # layers with no through-hole. They are explicit separate current rails.
    power_footprint(b,"OUT_POS",nets["VOUT"],(95.,36.),k.B_Cu,(6.,9.))
    power_footprint(b,"OUT_NEG",nets["PGND"],(95.,36.),k.F_Cu,(6.,9.))
    zone(b,nets["PGND"],k.F_Cu,4.,29.3,98.,43.)
    zone(b,nets["VOUT"],k.B_Cu,4.,29.3,98.,43.)
    rect(b,k.Edge_Cuts,0.,0.,SIDE,HEIGHT,.05)
    # Draw only on reference user-layer; NOT a mechanical recess/coldplate
    # physical model. No fluid channel is manufactured in this coupon.
    rect(b,k.Dwgs_User,4.,30.,98.,45.,.12)
    try:
        k.ZONE_FILLER(b).Fill(b.Zones())
    except Exception as exc:
        # Native CLI DRC checks actual filled geometry on saved file.
        raise RuntimeError("native KiCad zone fill failed") from exc
    OUT_DIR.mkdir(parents=True,exist_ok=True)
    k.SaveBoard(str(BOARD_PATH),b)
    reopen=k.LoadBoard(str(BOARD_PATH))
    if len(reopen.GetFootprints())!=8+8+4+2:raise ValueError("New coupon missing pads")
    if reopen.GetCopperLayerCount()!=12:raise ValueError("12Cu layer reset")
    return {
      "schema":"d1_e1_reuse_copper_coupon/1",
      "status":"REAL_NATIVE_KICAD_COPPER_COUPON_NOT_FOR_FAB_NOT_FULL_CONVERTER",
      "source_reusable_V17_sha256":SRC_SHA,
      "source_reusable_ELP38_4via_sha256":OLD_WINDING_SHA,
      "output_native_pcb":str(BOARD_PATH.relative_to(ROOT)).replace("\\","/"),
      "output_native_pcb_sha256":sha(BOARD_PATH),
      "copper_layers":12,
      "footprints":len(reopen.GetFootprints()),
      "primitive_tracks":len(reopen.GetTracks()),
      "filled_copper_zones":len(list(reopen.Zones())),
      "board_mm":[SIDE,HEIGHT],
      "physical_SR_source_pin_maps":orig_pins,
      "cell_count":len(CELLS),
      "rectifiers_per_cell":2,
      "output_target_total_a":200,
      "per_cell_output_design_intent_a":50,
      "SR_footprint_vendor_part_and_current_rating_verified":False,
      "magnetic_24to1_really_implemented":False,
      "current_carrying_200A_copper_full_stack_and_pth_manufacturer_qualified":False,
      "coldplate_contact_sketch_on_Dwgs_User_x_mm":[4,98],
      "coldplate_contact_sketch_on_Dwgs_User_y_mm":[30,45],
      "coldplate_assumed_mm":COLDPLATE_ASSUMPTION_MM,
      "coldplate_actual_geometry_machined":False,
      "hot_I2R_and_200A_continuous_proven":False,
      "sch_erc_or_drivers_included":False,
      "fixture_current_path":"front PGND collector and backside VOUT collector for geometric/4-terminal resistance comparison; separate polarity clamp fixtures must be supplier designed",
      "input_pads":"eight distinct secondary-lead PROXY injection lands; NOT real 4-transformer center tap or a signed 24:1 physical winding",
      "fabrication_approved":False,
      "power_on_approved":False,
      "intent":"Reuse V17 physical SR footprints, preserve per-pin nets, validate four-cell placement and opposing F/B collectors, then hand to B magnetic and C output/thermal teams for complete schematic and metal contact DFM."
    }
def main(argv=None):
    p=argparse.ArgumentParser()
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--write",action="store_true")
    group.add_argument("--check",action="store_true")
    args=p.parse_args(argv)
    if args.write:
        report=build()
        REPORT_PATH.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n","utf8")
    else:
        prev=json.loads(REPORT_PATH.read_text("utf8"))
        if sha(SRC)!=SRC_SHA or sha(PREV_WINDING)!=OLD_WINDING_SHA:
            raise ValueError("reused engineering sources changed")
        if sha(BOARD_PATH)!=prev["output_native_pcb_sha256"]:
            raise ValueError("saved coupon CAD changed without fresh DRC/report")
        board=k.LoadBoard(str(BOARD_PATH))
        if len(board.GetFootprints())!=prev["footprints"] or board.GetCopperLayerCount()!=12:
            raise ValueError("reopen regression")
        report=prev
    print(json.dumps({"status":report["status"],"board":report["output_native_pcb"],
                      "sha256":report["output_native_pcb_sha256"],"footprints":report["footprints"],
                      "tracks":report["primitive_tracks"],"zones":report["filled_copper_zones"],
                      "release":report["fabrication_approved"]}))
if __name__=="__main__":
    main()
