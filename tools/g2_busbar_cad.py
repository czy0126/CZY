"""Physical G2 output-bar trial from the real reopened G1 source rows.

Unlike the 100A arithmetic screen, generates *two metal bodies* with explicit
lug geometry and trial M3 holes, plus a PCB/TDK core clearance assembly STEP.
This does NOT connect copper to the native PCB's 12 source lands. Previous
trial M3 drill locations collide with real J_IN/QL copper; this exporter now
creates SOLID UNDRILLED bars. Alternate screw coordinates are only saved to
an audit report for a later real mechanical/electrical redesign. Manufacturer
DFM, attachments, insulation, cold plate/TIM and Kelvin remain unqualified.
Never export these trial outlines as production Gerbers or drilled fabrication.

python tools/g2_busbar_cad.py --check
python tools/g2_busbar_cad.py --export /tmp/g2-cad
# --export requires cadquery and ezdxf; --check needs only stdlib
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import g2_board_keepout as keepout

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"hardware/dcx_main/g1/g1_100a_output_interface.json"
MAG=ROOT/"design/v3/maxwell/diy_magnetics_concept.json"
BOARD_SHA="17fbae57bebdab6e0e18b6e4ddd177da98e25ca646bcb71d5e482a3b8db7b37e"
LIMIT_MM=16.0
PCB_THICKNESS_MM=1.6           # ASSUMED, not stackup DFM
BOTTOM_INSULATION_MM=0.3       # ASSUMED, not dielectric qualification
ELP38_I38_MAX_MM=8.25+.15+3.80+.15  # TDK ELP38/I38 catalogue max
ELP32_I32_PROXY_MM=6.35+.15+3.15+.15
# NO M3 drill is exported: native J_IN and QL keepouts are violated.
HOLE_DIAMETER_MM=3.4           # previous trial only; audit without cutting
THICKNESSES_MM=(1.2,5.0)

TDK="https://www.tdk-electronics.tdk.com/inf/80/db/fer/elp_38_8_25.pdf"


def load() -> dict:
    r=json.loads(SOURCE.read_text(encoding="utf-8"))
    m=json.loads(MAG.read_text(encoding="utf-8"))
    if r["schema"]!="g1_100a_output_interface/3" or r["candidate"]["sha256"]!=BOARD_SHA:
        raise ValueError("G1 source CAD identity/schema changed; do not reuse this trial")
    if r["fabrication_approved"] is not False or m["maxwell_solved"] or m["fabrication_approved"]:
        raise ValueError("No physical or Maxwell release is evidenced")
    g=r["geometry"]
    if g["bar_width_mm"]!=39 or g["board_mm"]!=[155,131]:
        raise ValueError("Board/collector profile changed")
    if len([x for x in m["cases"] if x["type"]=="LR_ELP38" and x["core_body_height_mm"]==8.25])!=4:
        raise ValueError("Concept Lr core height changed")
    if r["conclusion"]["reference_configuration"]["bar_thickness_mm"]!=5:
        raise ValueError("G1 reference conductor changed")
    return r


def outlines(r:dict) -> dict[str,list[tuple[float,float]]]:
    geo=r["geometry"]
    feed=r["topologies"]["central_two_pole_bar"]["feeds"]["widest_equal_loss"]
    xv=float(feed["vout_x_mm"]);xp=float(feed["pgnd_x_mm"])
    v=geo["vout_bar_rect_mm"];g=geo["pgnd_bar_rect_mm"]
    vx0,vx1=v["x"];vy0,vy1=v["y"]
    gx0,gx1=g["x"];gy0,gy1=g["y"]
    half=19.5
    # The trial lug extends beyond the electrical centreline to accommodate a
    # hole: the unmodelled terminal/cold-plate mounting height is NOT included.
    return {
      "VOUT":[(vx0,vy0),(vx1,vy0),(vx1,vy1),(xv+half,vy1),
              (xv+half,55.5),(xv-half,55.5),(xv-half,vy1),(vx0,vy1)],
      "PGND":[(gx0,gy1),(gx1,gy1),(gx1,gy0),(xp+half,gy0),
              (xp+half,49.5),(xp-half,49.5),(xp-half,gy0),(gx0,gy0)]
    }


def centres(r:dict) -> dict[str,tuple[float,float]]:
    f=r["topologies"]["central_two_pole_bar"]["feeds"]["widest_equal_loss"]
    y=float(r["geometry"]["terminal_y_mm"])
    return {"VOUT":(float(f["vout_x_mm"]),y),
            "PGND":(float(f["pgnd_x_mm"]),y)}


def is_inside(pt,poly) -> bool:
    x,y=pt;cross=0
    for (a,b),(c,d) in zip(poly,poly[1:]+poly[:1]):
        if (b>y)!=(d>y) and x<(c-a)*(y-b)/(d-b)+a:cross+=1
    return bool(cross%2)


def bbox(poly):
    return (min(x for x,y in poly),min(y for x,y in poly),
            max(x for x,y in poly),max(y for x,y in poly))


def overlap(a,b):
    return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])


def screen(t:float,joint_uohm_each:float=20) -> dict:
    if t<=0 or joint_uohm_each<0:raise ValueError("Nonphysical bar/joint scenario")
    r=load();o=outlines(r);c=centres(r)
    hole_audit=keepout.report()
    if hole_audit["prior_unsafe_m3_trial_centres"]["VOUT"]["passes_visible_native_copper_clearance_only"]:
        raise ValueError("Old J_IN M3 hole collision not detected; do not export")
    if any(not (0<=a<155 and 0<=b<131 and x<=155 and y<=131)
           for a,b,x,y in map(bbox,o.values())):
        raise ValueError("Bar footprint outside assumed board outline")
    f=r["topologies"]["central_two_pole_bar"]["feeds"]["widest_equal_loss"]
    vbar=r["geometry"]["vout_bar_rect_mm"];gbar=r["geometry"]["pgnd_bar_rect_mm"]
    vx,vp=float(f["vout_x_mm"]),float(f["pgnd_x_mm"])
    vparts=[(vbar["x"][0],vbar["y"][0],vbar["x"][1],vbar["y"][1]),
            (vx-19.5,vbar["y"][1],vx+19.5,55.5)]
    gparts=[(gbar["x"][0],gbar["y"][0],gbar["x"][1],gbar["y"][1]),
            (vp-19.5,49.5,vp+19.5,gbar["y"][0])]
    if any(overlap(a,b) for a in vparts for b in gparts):
        raise ValueError("VOUT/PGND copper intersects, unsafe")
    if (vp+19.5+2>vx-19.5):
        raise ValueError("VOUT/PGND trial mounting lugs too close")
    # Source model is the bar/terminal *screen*, not a measured or FEA result.
    b=r["conclusion"]["reference_configuration"]
    b_res=float(b["bar_uohm"])*float(b["bar_thickness_mm"])/t
    resistance=(b_res+float(r["design_basis"]["transition_allowance_uohm"])
                +float(r["design_basis"]["external_link_uohm"])+2*joint_uohm_each)
    height=ELP38_I38_MAX_MM+PCB_THICKNESS_MM+BOTTOM_INSULATION_MM+t
    return {
       "status":"DESIGN_OWNED_BUSBAR_GEOMETRY_NOT_FOR_FAB",
       "source_cad_sha256":BOARD_SHA,"native_cad_modified":False,
       "bar_thickness_mm":t,"assumed_joint_per_pole_uohm":joint_uohm_each,
       "assumed_pcb_thickness_mm":PCB_THICKNESS_MM,
       "assumed_bottom_dielectric_mm":BOTTOM_INSULATION_MM,
       "TDK_core_height_max_mm":ELP38_I38_MAX_MM,
       "height_without_TIM_clamp_holes_mm":round(height,3),
       "height_margin_without_TIM_clamp_mm":round(LIMIT_MM-height,3),
       "height_arithmetic_only_pass":height<=LIMIT_MM,
       "calculated_both_pole_uohm":round(resistance,3),
       "calculated_100A_loss_w":round(resistance/100,3),
       "resistance_margin_uohm":round(150-resistance,3),
       "resistance_arithmetic_only_pass":resistance<=150,
       "metal_outline_mm":{n:[[round(x,4),round(y,4)] for x,y in poly]
                           for n,poly in o.items()},
       "electrical_feed_reference_centres_mm":{n:[round(x,4),round(y,4)]
                                                for n,(x,y) in c.items()},
       "known_old_m3_drill_conflict":hole_audit["prior_unsafe_m3_trial_centres"],
       "mechanical_alternate_drill_locations_not_approved":
           hole_audit["alternate_positions_for_further_engineering_ONLY"],
       "no_m3_holes_exported":True,
       "all_299_native_pads_and_107_traces_18_vias_looked_up":True,
       "bottom_copper_over_other_nets_requires_certified_insulation":True,
       "no_source_land_to_bar_interconnect_model":True,
       "Cout_and_mating_terminal_unplaced":True,
       "TIM_and_clamp_and_standoff_tolerances_excluded":True,
       "no_fe_current_spreading_or_manufacturer_DFM":True,
       "fab_approved":False,
       "source_TDK_ELP38_I38_dimensions":TDK,
    }


def export(folder:Path,thickness:float) -> None:
    """Emit undrilled copper blank DXF and 3D mechanical assembly *trials*.

    Never emit unsafe M3 drill instructions over the J_IN and QL regions.
    A separate source-locked keepout report flags the known collisions.
    """
    import cadquery as cq
    import ezdxf
    folder.mkdir(parents=True,exist_ok=True)
    r=load();o=outlines(r);c=centres(r)
    drawing=ezdxf.new("R2010")
    msp=drawing.modelspace()
    for n in ("VOUT","PGND"):
        drawing.layers.new(n+"_COPPER_TRIAL")
        msp.add_lwpolyline(o[n],close=True,dxfattribs={"layer":n+"_COPPER_TRIAL"})
        # Deliberately NO CIRCLE: prior VOUT trial M3 hole intersects
        # J_IN PGND copper on the actual reopened native G1 board.
    stem=f"G2_{thickness:g}mm_NOT_FOR_FAB"
    drawing.saveas(folder/(stem+".dxf"))
    assy=cq.Assembly(name="G2_NONFAB_MECHANICAL_PROPOSAL")
    z=-BOTTOM_INSULATION_MM-thickness
    for n,color in (("VOUT",cq.Color(.92,.47,.18)),("PGND",cq.Color(.60,.23,.15))):
        p=cq.Workplane("XY").polyline(o[n]).close().extrude(thickness).translate((0,0,z))
        # Keep copper a single UNDRILLED solid; any future bolt-through-hole
        # needs inner-layer, pad, connector body, insulation and CAD DRC checks.
        if len(p.solids().vals())!=1:raise ValueError("Invalid copperbar solid")
        assy.add(p,name=n+"_COPPER_TRIAL",color=color)
    pcb=cq.Workplane("XY").box(155,131,PCB_THICKNESS_MM,centered=(False,False,False))
    assy.add(pcb,name="PCB_1p6mm_ASSUMED",color=cq.Color(.15,.50,.24,.40))
    dielectric=(cq.Workplane("XY")
                .box(155,131,BOTTOM_INSULATION_MM,centered=(False,False,False))
                .translate((0,0,-BOTTOM_INSULATION_MM)))
    assy.add(dielectric,name="BOTTOM_INSULATION_0p3mm_ASSUMED_NOT_QUALIFIED",
             color=cq.Color(.83,.85,.93,.55))
    lr=(cq.Workplane("XY").box(38,25.4,ELP38_I38_MAX_MM,centered=(True,True,False))
        .translate((26,49,PCB_THICKNESS_MM)))
    assy.add(lr,name="LR_ELP38_I38_CATALOGUE_ENVELOPE",color=cq.Color(.15,.17,.19,.55))
    for i,x in enumerate((20,58,96,134),1):
        t=(cq.Workplane("XY").box(31.75,25.4,ELP32_I32_PROXY_MM,
                                centered=(True,True,False))
           .translate((x,20,PCB_THICKNESS_MM)))
        assy.add(t,name=f"T{i}_ELP32_UNVERIFIED_PROXY",color=cq.Color(.35,.36,.37,.50))
    assy.save(str(folder/(stem+".step")))
    (folder/(stem+".json")).write_text(json.dumps({
        "low_joint_scenario":screen(thickness,20),
        "high_joint_scenario":screen(thickness,50),
        "no_drill_reason": keepout.report(),
    },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--check",action="store_true")
    group.add_argument("--export",type=Path)
    args=ap.parse_args()
    cases=[screen(t,j) for t in THICKNESSES_MM for j in (20,50)]
    if not cases[0]["height_arithmetic_only_pass"] or cases[2]["height_arithmetic_only_pass"]:
        raise SystemExit("Mechanical pass/fail gates have unexpectedly changed")
    if not cases[0]["resistance_arithmetic_only_pass"] or cases[1]["resistance_arithmetic_only_pass"]:
        raise SystemExit("Separable contact assumptions no longer separate outcomes")
    if args.export:
        for t in THICKNESSES_MM:export(args.export,t)
    print(json.dumps([{
        "bar_mm":c["bar_thickness_mm"],"joint_uohm":c["assumed_joint_per_pole_uohm"],
        "height_margin_mm":c["height_margin_without_TIM_clamp_mm"],
        "resistance_uohm":c["calculated_both_pole_uohm"],
        "resistance_arithmetic_only_pass":c["resistance_arithmetic_only_pass"],
        "fab_approved":False
    } for c in cases],indent=2))


if __name__=="__main__":
    main()
