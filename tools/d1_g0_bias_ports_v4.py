"""True KiCad PCB isolated primary/secondary bias power INPUT connector ECO.

Two separate physical 2-pin through-hole PORTS, each referenced to the
correct return. The external regulated isolated 12V sources are NOT included.
Fuse, current limit, connector MPN, qualification and hardware UVLO not done.
Keep RUN DNP, do not use this trial to energize the 48V power stage.
"""
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
import pcbnew as pcb
import d1_g0_split_return_eco_trial as parent
import d1_g0_cross_domain_audit as domains
import d1_g0_package_r8_v2 as v2

OUT=v2.OUT.parent/"d1_g0_integrated_BIAS_PORTS_V4_NOT_FOR_FAB"
STEM="d1_g0_dual_isolated_external_12v_bias_ports_NOT_FOR_FAB"
BOARD=OUT/(STEM+".kicad_pcb")
DRC=OUT/(STEM+"_native_drc.json")
REPORT=OUT/(STEM+"_evidence.json")
PORTS={
    "J_BIAS_P":{"pads":{"1":("VCC12",(7.,7.)),
                        "2":("PGND",(7.,12.))},
                "label":"PRIMARY_EXTERNAL_12V_NOT_BUILT"},
    "J_BIAS_S":{"pads":{"1":("VCC12_S",(7.,55.)),
                        "2":(domains.SRET,(7.,60.))},
                "label":"SECONDARY_ISOLATED_EXTERNAL_12V_NOT_BUILT"},
}
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def at(xy):return pcb.VECTOR2I(pcb.FromMM(xy[0]),pcb.FromMM(xy[1]))
def construct():
    p=parent.check()
    if p["native_DRC_violations"] or p["native_DRC_unconnected"]:
        raise ValueError("source isolated return copper not DRC clean")
    board=pcb.LoadBoard(str(parent.BOARD))
    nets={x.GetNetname():x for x in board.GetNetInfo().NetsByNetcode().values()}
    refs={f.GetReference() for f in board.GetFootprints()}
    for ref,row in PORTS.items():
        if ref in refs:raise ValueError("duplicate port "+ref)
        fp=pcb.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetValue(row["label"])
        fp.SetPosition(at(row["pads"]["1"][1]))
        fp.SetLayer(pcb.F_Cu)
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        for pin,(net,xy) in row["pads"].items():
            pd=pcb.PAD(fp)
            pd.SetNumber(pin)
            pd.SetShape(pcb.PAD_SHAPE_CIRCLE)
            pd.SetAttribute(pcb.PAD_ATTRIB_PTH)
            pd.SetPosition(at(xy))
            pd.SetSize(at((2.4,2.4)))
            pd.SetDrillSize(at((1.0,1.0)))
            layer=pcb.LSET.AllCuMask()
            layer.AddLayer(pcb.F_Mask)
            layer.AddLayer(pcb.B_Mask)
            pd.SetLayerSet(layer)
            pd.SetNet(nets[net])
            fp.Add(pd)
        fp.SetAttributes(pcb.FP_THROUGH_HOLE if hasattr(pcb,"FP_THROUGH_HOLE") else 0)
        # Provisional 2x5mm PTH connector outline; vendor model not qualified.
        shape=pcb.PCB_SHAPE(fp)
        shape.SetShape(pcb.SHAPE_T_RECT)
        x=row["pads"]["1"][1][0];y=row["pads"]["1"][1][1]
        shape.SetStart(at((x-2.0,y-2.0)))
        shape.SetEnd(at((x+2.0,y+7.0)))
        shape.SetLayer(pcb.F_CrtYd)
        shape.SetWidth(pcb.FromMM(.05))
        fp.Add(shape)
        board.Add(fp)
    pcb.ZONE_FILLER(board).Fill(board.Zones())
    return board

def audit(board,d):
    refs,pads=domains.pinpassport(board)
    if len(refs)!=157:raise ValueError("expect 157 footprints")
    if {r:refs[r] for r in PORTS}!={r:{pin:net for pin,(net,xy) in P["pads"].items()} for r,P in PORTS.items()}:
        raise ValueError("bias port nets swapped or bridged")
    b=domains.audited_domains(refs)
    if not b["isolation_domain_split_complete"]:
        raise ValueError("bias ports refuse merged returns")
    if len(d.get("violations",[])) or len(d.get("unconnected_items",[])):
        raise ValueError("KiCad native DRC defects on added PTH input ports")
    return {
       "kind":"D1_G0_NATIVE_EXTERNAL_TWO_12V_PORTS_CANDIDATE",
       "status":"PRIMARY_SECONDARY_BIAS_CONNECTORS_PINNED_DRC0_UNCONNECTED0_NOT_FOR_FAB",
       "source_split_board_sha256":sha(parent.BOARD),
       "candidate_board_sha256":sha(BOARD),
       "native_drc_sha256":sha(DRC),
       "physical_board_footprints":len(refs),
       "port_ref_pad_net":{r:refs[r] for r in PORTS},
       "primary_12v_return":"PGND",
       "secondary_12v_return":domains.SRET,
       "source_12v_supply_modules_integrated":False,
       "independent_12v_supplies_present_for_actual_bench":False,
       "primary_secondary_return_nets_shared":False,
       "native_rule_violations":len(d["violations"]),
       "native_unconnected":len(d["unconnected_items"]),
       "port_vendor_qualified":False,
       "input_fuses_and_UVLO_implemented":False,
       "hardware_ESTOP_and_HS_gate_monitor_implemented":False,
       "physical_power_48v_energization_allowed":False,
       "fab_release":False,
    }

def write():
    OUT.mkdir(parents=True,exist_ok=True)
    b=construct()
    pcb.SaveBoard(str(BOARD),b)
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    args=[str(cli),"pcb","drc","--severity-all","--format","json",
          "-o",str(DRC),str(BOARD)]
    p=subprocess.run(args,capture_output=True,text=True,errors="replace")
    if p.returncode or not DRC.is_file():raise ValueError("Native KiCad bias DRC failed "+p.stderr)
    d=json.loads(DRC.read_text("utf-8"))
    report=audit(pcb.LoadBoard(str(BOARD)),d)
    REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return report

def check():
    data=json.loads(REPORT.read_text("utf-8"))
    r=audit(pcb.LoadBoard(str(BOARD)),json.loads(DRC.read_text("utf-8")))
    if r!=data:raise ValueError("12V PTH input ports evidence stale")
    return r

def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--write",action="store_true")
    group.add_argument("--check",action="store_true")
    a=p.parse_args()
    data=write() if a.write else check()
    print(json.dumps({k:data[k] for k in ("status","physical_board_footprints",
        "native_rule_violations","native_unconnected",
        "primary_secondary_return_nets_shared")},ensure_ascii=False))
if __name__=="__main__":main()
