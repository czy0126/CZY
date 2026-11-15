"""Place real KiCad R8 RUN-enable DNP pad pair on G0 motherboard trial.

R8 is independently required by the original control/peripheral connection
register but absent from the 154-device PCB. It is deliberately DO NOT POPULATE
and is not connected to a physical interlock. Default remains RUN pull-down;
do not bypass safety/UVLO to achieve turn-on. A native KiCad DRC is required
on the actual saved board, and the independent *golden* pad mapping is checked.
"""
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
import pcbnew as pcb
import d1_g0_package_native_mainboard as pkg
import d1_g0_cross_domain_audit as domain
import main_board_schematic as golden
import check_main_board_netlist as independent

OUT=pkg.OUT
STEM="d1_g0_R8_DNP_enable_site_ECO_NOT_FOR_FAB"
BOARD=OUT/(STEM+".kicad_pcb")
DRC=OUT/(STEM+"_native_drc.json")
REPORT=OUT/(STEM+"_receipt.json")
R8_CENTER=(66.0,22.0)
R8_PADS={"1":((65.245,22.0),"VCC12"),"2":((66.755,22.0),"RUN")}
DNP_VALUE="1k_DNP_UNTIL_EXTERNAL_PERMIT_TESTED"

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def at(p):return pcb.VECTOR2I(pcb.FromMM(p[0]),pcb.FromMM(p[1]))
def netobjs(board):return {x.GetNetname():x for x in board.GetNetInfo().NetsByNetcode().values()}
def add_pad(fp,num,point,net):
    pad=pcb.PAD(fp)
    pad.SetNumber(num)
    pad.SetPosition(at(point))
    pad.SetSize(at((.80772,.863599)))
    pad.SetShape(pcb.PAD_SHAPE_RECT)
    pad.SetAttribute(pcb.PAD_ATTRIB_SMD)
    layers=pcb.LSET()
    for l in (pcb.F_Cu,pcb.F_Mask,pcb.F_Paste):layers.AddLayer(l)
    pad.SetLayerSet(layers)
    pad.SetNet(net)
    fp.Add(pad)

def trace(board,n,a,b,width=.20):
    t=pcb.PCB_TRACK(board)
    t.SetNet(n);t.SetLayer(pcb.F_Cu);t.SetWidth(pcb.FromMM(width))
    t.SetStart(at(a));t.SetEnd(at(b));board.Add(t)

def install(board):
    if any(fp.GetReference()=="R8" for fp in board.GetFootprints()):
        raise ValueError("R8 would be duplicated")
    n=netobjs(board)
    fp=pcb.FOOTPRINT(board)
    fp.SetReference("R8")
    fp.SetValue(DNP_VALUE)
    fp.SetPosition(at(R8_CENTER))
    fp.SetLayer(pcb.F_Cu)
    fp.SetAttributes(pcb.FP_SMD|pcb.FP_DNP|pcb.FP_EXCLUDE_FROM_POS_FILES)
    fp.SetDNP(True)
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)
    for num,(point,net) in R8_PADS.items():add_pad(fp,num,point,n[net])
    # Courtyard only; datasheet land pattern and assembly require sign-off.
    outline=pcb.PCB_SHAPE(fp)
    outline.SetShape(pcb.SHAPE_T_RECT)
    outline.SetStart(at((64.45,21.05)))
    outline.SetEnd(at((67.55,22.95)))
    outline.SetLayer(pcb.F_CrtYd)
    outline.SetWidth(pcb.FromMM(.05))
    fp.Add(outline)
    board.Add(fp)
    # Left V12 pin uses an existing In4.Cu VCC12 plane through a local via;
    # do NOT claim the 12-layer via construction is vendor qualified.
    trace(board,n["VCC12"],R8_PADS["1"][0],(65.245,23.2))
    via=pcb.PCB_VIA(board)
    via.SetPosition(at((65.245,23.2)))
    via.SetNet(n["VCC12"])
    via.SetLayerPair(pcb.F_Cu,pcb.B_Cu)
    via.SetWidth(pcb.FromMM(.70))
    via.SetDrill(pcb.FromMM(.30))
    board.Add(via)
    # Right pin reaches existing R7 RUN pull-down; with R8 unassembled
    # the actual RUN enable node stays deliberately low and fail-off.
    trace(board,n["RUN"],R8_PADS["2"][0],(68.1,20.0))
    return fp

def examine(board,drc):
    refs,native=domain.pinpassport(board)
    if len(refs)!=155 or "R8" not in refs or refs["R8"]!={"1":"VCC12","2":"RUN"}:
        raise ValueError("R8 new physical pad/net parity wrong")
    fp=next(x for x in board.GetFootprints() if x.GetReference()=="R8")
    if not fp.IsDNP():raise ValueError("unsafe auto-enable: R8 populated")
    result=independent.compare(golden.load_golden(),refs,golden.load_library())
    if result["missing_or_wrong"] or result["unexpected_nets"] or result["not_placed"] or \
       set(result["unexpected_refs"])!=domain.ALLOWED_EXTRA:
        raise ValueError("Independent SPICE design pin net mismatch after R8 ECO")
    if drc.get("violations") or drc.get("unconnected_items"):
        raise ValueError("native R8 ECO introduces KiCad shorts/clearance/unconnected")
    return {
       "kind":"G0_PHYSICAL_R8_DNP_ENABLE_ECO",
       "status":"R8_KICAD_POPULATED_AS_DNP_ONLY_NOT_FOR_FAB",
       "parent_board_sha256":sha(pkg.PCB),
       "native_board_sha256":sha(BOARD),
       "native_drc_sha256":sha(DRC),
       "pcb_device_count":len(refs),
       "r8_native_pads":refs["R8"],
       "r8_dnp":fp.IsDNP(),
       "actual_schematic_design_pin_differences":len(result["missing_or_wrong"]),
       "expected_unverified_72_COUT_footprints":len(result["unexpected_refs"]),
       "native_kicad_drc_violations":len(drc["violations"]),
       "native_kicad_unconnected":len(drc["unconnected_items"]),
       "native_drc_ignored":[x.get("key") for x in drc.get("ignored_checks",[])],
       "external_enable_permit_integrated":False,
       "isolated_SR_RETURN_integrated":False,
       "board_fab_release":False,"hardware_powerup_allowed":False,
    }

def write():
    if not pkg.RECEIPT.is_file():raise ValueError("G0 parent receipt missing")
    upstream=pkg.check()
    if upstream["pcb_device_count"]!=154:raise ValueError("G0 parent not expected revision")
    board=pcb.LoadBoard(str(pkg.PCB))
    install(board)
    pcb.ZONE_FILLER(board).Fill(board.Zones())
    pcb.SaveBoard(str(BOARD),board)
    cmd=[str(Path(sys.executable).with_name("kicad-cli.exe")),"pcb","drc",
        "--severity-all","--format","json","-o",str(DRC),str(BOARD)]
    result=subprocess.run(cmd,capture_output=True,text=True,errors="replace")
    if result.returncode!=0 or not DRC.is_file():
        raise ValueError("KiCad R8 candidate DRC command failed "+result.stderr)
    report=examine(pcb.LoadBoard(str(BOARD)),json.loads(DRC.read_text("utf-8")))
    REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return report

def check():
    if not all(x.is_file() for x in (BOARD,DRC,REPORT)):
        raise ValueError("R8 ECO native files missing")
    report=examine(pcb.LoadBoard(str(BOARD)),json.loads(DRC.read_text("utf-8")))
    if report!=json.loads(REPORT.read_text("utf-8")):
        raise ValueError("R8 ECO receipt stale")
    return report

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    opts=ap.parse_args()
    record=write() if opts.write else check()
    print(json.dumps({k:record[k] for k in ("status","pcb_device_count","r8_dnp",
        "actual_schematic_design_pin_differences","native_kicad_drc_violations","native_kicad_unconnected")}))
if __name__=="__main__":main()
