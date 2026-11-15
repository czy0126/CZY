"""V17 KiCad G0 whole-board integration, source-locked independent candidate.

Uses installed KiCad 10 Python pcbnew. Does NOT alter the V17 original.
Five magnetic footprints carry *logical* landing pads from independently
audited native EasyEDA P1, NOT supplier-certified package or winding DOT.
All temporary routes require native KiCad DRC plus later physical review.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pcbnew as pcb

ROOT=Path(__file__).resolve().parents[1]
G2=ROOT/"hardware/dcx_main/g2"
SRC=G2/"dcx_main_board_g2_V17_OEM_T530_72_VIN_SW_CANDIDATE_NOT_FOR_FAB.kicad_pcb"
PINS=G2/"g2_five_magnetics_24_logical_pin_native_parity_NOT_FOR_FAB.json"
OUT=G2/"d1_g0_integrated_mainboard_NOT_FOR_FAB"
STEM="d1_g0_complete_logical_board_CANDIDATE_NOT_FOR_FAB"
BOARD=OUT/(STEM+".kicad_pcb")
PROJECT=OUT/(STEM+".kicad_pro")
DRC=OUT/(STEM+"_native_drc.json")
RECEIPT=OUT/"d1_g0_mainboard_net_and_magnetics_audit_NOT_FOR_FAB.json"
SOURCE_SHA="4bdb3492959aa08e70716a0f6ca020fe8cf98da66f08c795b72f8172b5ab50f9"
MAGNETS=("T1","T2","T3","T4","CT")

# A first, intentionally testable route hypothesis. Widths are *not*
# automatically current-qualified: all candidate power copper must be reviewed
# with geometry, pad escape, losses, and manufacturing context.
# Each new segment may be rejected by KiCad DRC. Never claim it succeeds
# until the saved native report actually shows physical+connection=0.
ALL_LEGACY_ROUTE_TRIALS = (
    ("HB",.20,((44.299620,17.999880),(52.499258,18.000000))),
    ("GH_DRV",.20,((46.246889,14.000507),(52.499258,18.500000))),
    ("GH",.20,((42.247298,12.001160),(47.753109,14.000507))),
    ("SW",.20,((43.753518,12.001160),(52.499258,19.000000))),
    ("SW",.65,((47.363374,9.750718),(55.097692,4.249078))),
    ("VIN_P",.65,((50.799086,13.499659),(48.000914,6.354738))),
    ("OC",.20,((76.633755,13.706281),(134.247880,17.000180))),
)
# Do not short nets just to make ratsnest disappear: first relocate actual
# magnetics landing pads out of the occupied controller/half-bridge footprint.
ROUTES = ()
# Above and within y22..44 the board has twelve *actual* Edge.Cuts slots!
# It is invalid to put copper in them. Trial landing pads sit 2.75mm below
# slot edges; terminal placement/physical core structure remains unqualified.
# Grouped by transformer, NOT manufacturer pad numbers.
TRIAL_MAG_PAD_SITES = {
    **{name: {
        "PRI_A":(3.0+38*i,46.75), "PRI_B":(6.0+38*i,46.75),
        "SEC_A":(31.0+38*i,46.75),"CTAP":(34.0+38*i,46.75),
        "SEC_B":(37.0+38*i,46.75),
    } for i,name in enumerate(("T1","T2","T3","T4"))},
    "CT":{"PRI_A":(87.0,33.0),"PRI_B":(87.0,37.0),
          "SEC_A":(103.0,33.0),"SEC_B":(103.0,37.0)},
}
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def at(x,y):return pcb.VECTOR2I(pcb.FromMM(x),pcb.FromMM(y))
def xy(pos):return [round(pcb.ToMM(pos.x),6),round(pcb.ToMM(pos.y),6)]

def add_magnets(board):
    rows=json.loads(PINS.read_text("utf-8"))
    if rows["real_electrical_pin_count"]!=24 or rows["vendor_mechanical_pin_numbers_confirmed"]!=0:
        raise ValueError("Magnetics pin data authority changed")
    pmap=rows["devices"]
    nets={obj.GetNetname():obj for obj in board.GetNetInfo().NetsByNetcode().values()}
    # Original V17 PCB omitted the five magnetic devices, so series-primary
    # inter-winding nodes existed on its schematic but not in PCB net table.
    for group in pmap.values():
        for rec in group["design_logical_pins"]:
            name=rec["native_schematic_net"]
            if name not in nets:
                ni=pcb.NETINFO_ITEM(board,name)
                board.Add(ni)
                nets[name]=ni
    by={}
    for ref in MAGNETS:
        origin=pmap[ref]["footprint_origin_mm"]
        fp=pcb.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetValue("LOGICAL_5LAND_NOT_VENDOR_PINOUT_NOT_FOR_FAB" if ref!="CT" else "LOGICAL_4LAND_CT_NOT_VENDOR_PINOUT")
        fp.SetPosition(at(*origin))
        fp.SetLayer(pcb.F_Cu)
        # A vendor unqualified magnetic label belongs on F.Fab documentation,
        # not as floating silkscreen over the neighboring controller pads.
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        for rec in pmap[ref]["design_logical_pins"]:
            net=rec["native_schematic_net"]
            if net not in nets:raise ValueError(ref+" missing native net "+net)
            pad=pcb.PAD(fp)
            pad.SetNumber(rec["logical_terminal"])
            pad.SetAttribute(pcb.PAD_ATTRIB_SMD)
            pad.SetShape(pcb.PAD_SHAPE_CIRCLE)
            center=TRIAL_MAG_PAD_SITES[ref][rec["logical_terminal"]]
            pad.SetPosition(at(*center))
            diameter=rec["trial_pad_diameter_mm"]
            pad.SetSize(at(diameter,diameter))
            ls=pcb.LSET()
            for layer in (pcb.F_Cu,pcb.F_Mask,pcb.F_Paste):ls.AddLayer(layer)
            pad.SetLayerSet(ls)
            pad.SetNet(nets[net])
            fp.Add(pad)
        board.Add(fp)
        by[ref]={"position_mm":origin,"pin_count":len(pmap[ref]["design_logical_pins"])}
    if sum(x["pin_count"] for x in by.values())!=24:
        raise ValueError("missing trial magnetic pad")
    return by

def add_routes(board):
    nets={obj.GetNetname():obj for obj in board.GetNetInfo().NetsByNetcode().values()}
    records=[]
    for net,width,poly in ROUTES:
        if net not in nets:raise ValueError("missing net "+net)
        for a,b in zip(poly,poly[1:]):
            t=pcb.PCB_TRACK(board)
            t.SetNet(nets[net])
            t.SetLayer(pcb.F_Cu)
            t.SetWidth(pcb.FromMM(width))
            t.SetStart(at(*a))
            t.SetEnd(at(*b))
            board.Add(t)
            records.append({"net":net,"layer":"F.Cu","start_mm":list(a),
                            "end_mm":list(b),"width_mm":width})
    return records

def load_board():
    if sha(SRC)!=SOURCE_SHA:raise ValueError("V17 source sha drift, require new engineering review")
    b=pcb.LoadBoard(str(SRC))
    if len(b.GetFootprints())!=149:raise ValueError("Expected 149 frozen native V17 footprints")
    return b

def drc_report():
    cli=ROOT/"_NO_KICAD_CLI"
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    if not cli.is_file():raise ValueError("KiCad CLI unavailable next to bundled Python")
    cmd=[str(cli),"pcb","drc","--format","json","--severity-all",
         "-o",str(DRC),str(BOARD)]
    run=subprocess.run(cmd,capture_output=True,text=True,errors="replace")
    if not DRC.is_file():raise ValueError("Native KiCad DRC tool did not create report "+run.stderr)
    obj=json.loads(DRC.read_text("utf-8"))
    return obj,run.returncode

def counts(obj):
    return {"physical_rule_violations":len(obj.get("violations",[])),
            "unconnected_items":len(obj.get("unconnected_items",[])),
            "ignored_check_keys":[x.get("key") for x in obj.get("ignored_checks",[])]}

def build_report(mag, routes, drc, code, board):
    return {
      "kind":"D1_G0_NATIVE_INTEGRATED_149_TO_154_PCB_CANDIDATE",
      "status":"NATIVE_TRIAL_FULL_BOARD_NOT_FOR_FAB",
      "source_board_sha256":sha(SRC),
      "new_board_sha256":sha(BOARD),
      "source_pcb_footprints":149,
      "candidate_footprints":len(board.GetFootprints()),
      "source_magnetics_manifest_sha256":sha(PINS),
      "engineering_trial_magnetics":mag,
      "trial_magnetics_logical_landings":sum(x["pin_count"] for x in mag.values()),
      "engineering_trial_pad_sites_mm":TRIAL_MAG_PAD_SITES,
      "trial_landing_positions_are_NOT_original_native_pad_positions":True,
      "trial_landing_sites_are_vendor_qualified":False,
      "manufacturer_magnetics_terminal_pinout_verified":False,
      "manufacturer_magnetics_footprints_validated":False,
      "resonant_transformer_ratio_dot_physically_verified":False,
      "new_routes":routes,
      "new_route_geometry_manufacturing_rated":False,
      "native_drc":counts(drc),
      "native_drc_report_sha256":sha(DRC),
      "native_drc_exit_code":code,
      "integrated_schematic_independently_verified":False,
      "native_erc_full_board_verified":False,
      "isolated_12v_bias_integrated":False,
      "physical_estop_and_hs_monitors_integrated":False,
      "cold_start_closed_loop_llc_tested":False,
      "gate0_approved":False,
      "fabrication_approved":False,
      "energization_allowed":False
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write",action="store_true")
    mode.add_argument("--check",action="store_true")
    args=ap.parse_args()
    if args.write:
        OUT.mkdir(parents=True,exist_ok=True)
        b=load_board()
        mag=add_magnets(b)
        routes=add_routes(b)
        pcb.ZONE_FILLER(b).Fill(b.Zones())
        pcb.SaveBoard(str(BOARD),b)
        PROJECT.write_text((SRC.with_suffix(".kicad_pro")).read_text("utf-8"),encoding="utf-8")
        drc,code=drc_report()
        reopened=pcb.LoadBoard(str(BOARD))
        if len(reopened.GetFootprints())!=154:raise ValueError("Magnetics not actually saved as five real KiCad footprint objects")
        report=build_report(mag,routes,drc,code,reopened)
        RECEIPT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    elif args.check:
        if not all(f.is_file() for f in (BOARD,PROJECT,DRC,RECEIPT)):raise ValueError("Integrated files missing")
        report=json.loads(RECEIPT.read_text("utf-8"))
        b=pcb.LoadBoard(str(BOARD))
        if len(b.GetFootprints())!=154 or sha(SRC)!=report["source_board_sha256"]:
            raise ValueError("PCB inventory/source changed")
        if report["new_board_sha256"]!=sha(BOARD) or report["native_drc_report_sha256"]!=sha(DRC):
            raise ValueError("PCB or native DRC evidence hash stale")
        drc=json.loads(DRC.read_text("utf-8"))
        if report["native_drc"]!=counts(drc):raise ValueError("DRC counts changed")
    print(json.dumps({"status":report["status"],"footprints":report["candidate_footprints"],
        "landings":report["trial_magnetics_logical_landings"],**report["native_drc"]},ensure_ascii=False))

if __name__=="__main__":main()
