"""V9-real-native source-bound 100A bipolar bar mechanical & current bottleneck gate.

A conservative geometric overlay and resistive/height sensitivity screen, NOT
a manufactured copper or FEM/temperature result. It rejects fabrication.
All copper refs and vias come from a live native EasyEDA readback of saved V9.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G2 = ROOT / "hardware/dcx_main/g2"
sys.path[:0] = [str(ROOT / "tools"), str(G2)]
import g2_busbar_cad as BUS
import g2_board_keepout as KEEP
import g2_v9_real_t530_components as V9

READBACK = G2 / "g2_v9_live_native_full_readback_20261112_NOT_FOR_FAB.json"
NATIVE_RECEIPT = G2 / "g2_v9_vout_source_bottom_feeder_verified_NOT_FOR_FAB.json"
REPORT = G2 / "g2_v9_100a_bipolar_physical_screen_NOT_FOR_FAB.json"
SVG = G2 / "g2_v9_bipolar_native_busbar_overlay_NOT_FOR_FAB.svg"
LIMIT = 16.
RHO_20 = 1.724e-8   # copper assumed, ohm*m at 20 C
ALPHA = .00393      # first-order copper temperature coefficient
BOARD_MM = 1.6      # not a manufacturer-signed stackup
PLATING_MM = .025   # trial assumption, not measured
DRILL_MM = .4       # existing actual VOUT feeder hole
FEEDER_WIDTH_MM = 1.6
FEEDER_LENGTH_MM = 74.
FEEDER_COUNT = 3
CUPPER_TRACK_THICK_MM = .07  # 2 oz nominal copper, not confirmed PCB stack
BAR_THICKNESS_MM = 1.2
CONTACT_UOHM = (20., 50.)
# These extras are explicit sensitivity cases, not product specifications.
ASSEMBLY_EXTRAS = {"none": (0., 0., 0.),
                   "trial_TIM_clamp_tolerance": (.3, .4, .3)}


def source():
    frozen = json.loads(NATIVE_RECEIPT.read_text("utf8"))
    if V9.sha(V9.V9) != frozen["source_sha256"]:
        raise ValueError("V9 native source changed; no physical results can be reused")
    r = json.loads(READBACK.read_text("utf8"))
    if r.get("source_sha256") != frozen["source_sha256"] or r.get("native_counts") != frozen["native_counts"]:
        raise ValueError("Missing matching real native saved readback")
    if (r.get("physical_islands") or {}) != {"VOUT": 1, "PGND": 39}:
        raise ValueError("Power pole island structure changed")
    if V9.sha(V9.V8) != V9.EXPECTED_V8_SHA:
        raise ValueError("Historical V8 modified")
    if r.get("fabrication_approved") is not False:
        raise ValueError("Source manufacturing release state corrupted")
    return r["value"], frozen


def point_polygon_distance(pt, poly):
    if BUS.is_inside(pt, poly):
        return 0.
    return min(KEEP.segment_distance(pt, a, b)
               for a,b in zip(poly,poly[1:]+poly[:1]))


def centre_native_pad(p):
    box=KEEP.pad_bbox(p)
    return ((box[0]+box[2])/2, (box[1]+box[3])/2)


def via_ohm(n, rho=RHO_20, drill_mm=DRILL_MM, plating_mm=PLATING_MM,
            board_mm=BOARD_MM):
    if n<1 or min(rho, drill_mm, plating_mm, board_mm)<=0:
        raise ValueError("nonphysical via barrel model")
    # Thin-walled plated cylinder, conservative no via-pad barrel bypass.
    return rho*(board_mm*1e-3)/(n*math.pi*(drill_mm*1e-3)*(plating_mm*1e-3))


def feeder_ohm(count=FEEDER_COUNT, rho=RHO_20, width_mm=FEEDER_WIDTH_MM,
               thickness_mm=CUPPER_TRACK_THICK_MM, length_mm=FEEDER_LENGTH_MM):
    if count<1 or min(rho,width_mm,thickness_mm,length_mm)<=0:
        raise ValueError("nonphysical narrow native feeder model")
    return rho*(length_mm*1e-3)/(count*(width_mm*1e-3)*(thickness_mm*1e-3))


def bar_screen(tim=0.,clamp=0.,tolerance=0.):
    if min(tim,clamp,tolerance)<0: raise ValueError("negative mechanical allowance")
    scenarios=[]
    for joint in CONTACT_UOHM:
        b=BUS.screen(BAR_THICKNESS_MM,joint)
        height=b["height_without_TIM_clamp_holes_mm"]+tim+clamp+tolerance
        scenarios.append({"thickness_mm":BAR_THICKNESS_MM,
            "assumed_contact_each_pole_uohm":joint,
            "model_resistance_uohm":b["calculated_both_pole_uohm"],
            "model_loss_100a_w":b["calculated_100A_loss_w"],
            "assembled_envelope_mm":round(height,3),
            "remaining_16mm_allowance_mm":round(LIMIT-height,3),
            "screen_both_pole_150uohm":b["resistance_arithmetic_only_pass"],
            "screen_full_height":height<=LIMIT,
            "contacts_and_real_temperature_measured":False,
            "manufacturer_approved":False})
    first=BUS.screen(BAR_THICKNESS_MM,CONTACT_UOHM[0])
    bare=first["calculated_both_pole_uohm"]-2*CONTACT_UOHM[0]
    return {"cases":scenarios,
            "maximum_contact_uohm_each_if_other_assumptions_hold":round((150-bare)/2,4),
            "no_bolt_holes_or_actual_pcb_bar_connection":True}


def report():
    native,src=source()
    bars=BUS.outlines(BUS.load())
    mismatched={}
    for pole,poly in bars.items():
        hits=[]
        for v in native["vias"]:
            if v["net"]==pole: continue
            p=(v["x"]*.0254,-v["y"]*.0254)
            dr=v["diameter"]*.0254/2
            if point_polygon_distance(p,poly)<dr+.3:
                hits.append({"other_net":v["net"],
                             "at_mm":[round(p[0],3),round(p[1],3)],
                             "via_outer_diameter_mm":round(dr*2,3)})
        mismatched[pole]=hits

    # The bar outlines come from an older G1 source. Map the actual V9 power
    # terminal pads before treating them as usable contact placements.
    source_pads=[p for p in native["pads"] if p["Net"]=="VOUT" and
                 p.get("ref") is None and p.get("PadNumber")=="CTAP"]
    sr_pads=[p for p in native["pads"] if p["Net"]=="PGND" and
             str(p.get("ref") or "").startswith("SR") and p.get("PadNumber")=="3"]
    if len(source_pads)!=4 or len(sr_pads)<8:
        raise ValueError(f"Unexpected power pads CTAP={len(source_pads)} SR={len(sr_pads)}")
    sources={}
    for label,rows,pole in (("CTAP",source_pads,"VOUT"),("SR_SOURCE",sr_pads,"PGND")):
        sources[label]=[{"pad":(p.get("ref") or "RAW")+"."+str(p["PadNumber"]),
                "xy_mm":[round(x,3) for x in centre_native_pad(p)],
                "inside_legacy_bar":BUS.is_inside(centre_native_pad(p),bars[pole])}
                for p in rows]
    feeders=[v for v in native["vias"] if v["net"]=="VOUT" and
             abs(v["y"]*.0254+20)<.3]
    if len(feeders)!=3:
        raise ValueError("The actual saved V9 has no exactly-three source VOUT via bottleneck")
    cross={}
    for temp in (20,100):
        rho=RHO_20*(1+ALPHA*(temp-20))
        rv=via_ohm(3,rho)
        rt=feeder_ohm(3,rho)
        cross[str(temp)]={"rho_ohm_m":rho,
                          "three_via_total_resistance_uohm":round(rv*1e6,3),
                          "three_via_only_if_100a_loss_w":round(100**2*rv,3),
                          "three_74mm_1p6mm_feeder_scenario_uohm":round(rt*1e6,3),
                          "three_feeder_only_if_100a_loss_w":round(100**2*rt,3),
                          "note":"hypothetical three equal full-length paths, NOT a validated current flow solution"}
    cases={n:bar_screen(*args) for n,args in ASSEMBLY_EXTRAS.items()}
    return {"schema":"G2_V9_ACTUAL_NATIVE_BIPOLAR_AND_MECHANICAL_SCREEN_V1",
        "status":"NOT_FOR_FAB_NO_100A_AMPACITY_OR_ACTUAL_CONTACTS",
        "source_native_sha256":src["source_sha256"],
        "native_count":src["native_counts"],
        "native_islands":{"VOUT":1,"PGND":39},
        "main_power_poles_physically_connected_at_graph_level":True,
        "native_drc_open_connections":src["native_drc"]["Connection Error"],
        "native_drc_netlist_errors":src["native_drc"]["Netlist Error"],
        "feeder_via_diameter_mm":1.,"feeder_via_drill_mm":DRILL_MM,
        "assumed_plating_thickness_mm":PLATING_MM,
        "assumed_copper_foil_mm":CUPPER_TRACK_THICK_MM,
        "feeder_via_count":len(feeders),
        "cross_section_scenarios":cross,
        "contact_anchors":sources,
        "legacy_bar_polygons_mm":bars,
        "opposite_net_native_vias_needing_bottom_bar_insulation":mismatched,
        "test_assembly_height_scenarios":cases,
        "actual_dual_busbar_contact_created_on_v9":False,
        "actual_terminal_drilled_and_copper_bar_fabricated":False,
        "TIM_clamp_stackup_manufacturer_signed":False,
        "battery_of_thermal_and_100A_measurements_passed":False,
        "magnetics_and_D0_qualified":False,
        "fabrication_approved":False}


def svg_body(r):
    W,H=930,786
    def xy(x,y):return f"{25+x*5.6:.2f},{20+y*5.6:.2f}"
    def shape(poly,clr):
        return f'<polygon points="{" ".join(xy(*p) for p in poly)}" fill="{clr}" fill-opacity=".21" stroke="{clr}" stroke-width="2"/>'
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
      '<rect width="100%" height="100%" fill="white"/>',
      '<rect x="25" y="20" width="868" height="734" fill="#f8fafb" stroke="#364454" stroke-width="3"/>',
      shape(r["legacy_bar_polygons_mm"]["VOUT"],"#be4d20"),
      shape(r["legacy_bar_polygons_mm"]["PGND"],"#236baa")]
    for items in r["contact_anchors"].values():
        for o in items:
            x,y=o["xy_mm"]; col="#12a679" if o["inside_legacy_bar"] else "#d7263d"
            lines.append(f'<circle cx="{25+x*5.6:.2f}" cy="{20+y*5.6:.2f}" r="3.1" fill="{col}"/>')
    for pole,items in r["opposite_net_native_vias_needing_bottom_bar_insulation"].items():
        for v in items:
            x,y=v["at_mm"]
            lines.append(f'<circle cx="{25+x*5.6:.2f}" cy="{20+y*5.6:.2f}" r="5.3" fill="none" stroke="#d52032" stroke-width="1.2"/>')
    lines += [
      '<text x="40" y="42" font-family="Arial" font-size="19" fill="#24354a">D1 native V9 / metal bar XY screening — NOT FOR FAB</text>',
      '<text x="40" y="775" font-family="Arial" font-size="13" fill="#24354a">orange: VOUT bar    blue: PGND bar    green: pad under bar    red: missed pad / unlike-net via proximity</text>',
      '</svg>']
    return "\n".join(lines)+"\n"


def main():
    p=argparse.ArgumentParser()
    a=p.add_mutually_exclusive_group(required=True)
    a.add_argument("--write",action="store_true");a.add_argument("--check",action="store_true")
    o=p.parse_args()
    r=report()
    body=json.dumps(r,ensure_ascii=False,indent=2)+"\n"
    drawing=svg_body(r)
    if o.write:
        REPORT.write_text(body,encoding="utf-8",newline="\n")
        SVG.write_text(drawing,encoding="utf-8",newline="\n")
    elif not REPORT.exists() or not SVG.exists() or (REPORT.read_text("utf-8")!=body or SVG.read_text("utf-8")!=drawing):
        raise ValueError("Native V9 mechanical screen/source/plot stale or missing")
    print(json.dumps({"status":r["status"],"native_sha256":r["source_native_sha256"],
       "opposite_net_vias_under_legacy_bars":{k:len(v) for k,v in
          r["opposite_net_native_vias_needing_bottom_bar_insulation"].items()},
       "contact_anchor_inside_legacy_bar":{k:sum(x["inside_legacy_bar"] for x in rows)
          for k,rows in r["contact_anchors"].items()},
       "via_3barrel_20C_uohm":r["cross_section_scenarios"]["20"]["three_via_total_resistance_uohm"],
       "height_trial":r["test_assembly_height_scenarios"]["trial_TIM_clamp_tolerance"]["cases"]},
       ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
