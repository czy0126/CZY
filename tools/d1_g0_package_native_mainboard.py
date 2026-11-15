"""Package source-locked 154-component KiCad motherboard trial (never fab)."""
from __future__ import annotations
import argparse,csv,hashlib,json,shutil,subprocess,sys
from pathlib import Path
import pcbnew as pcb
import d1_g0_integrated_native_board as raw
import d1_g0_router_trial as route
import d1_g0_native_schematic_projection as schematic
import d1_lane_c_g0_gate as parity
import main_board_schematic as mpn

OUT=raw.OUT
STEM=schematic.FINAL_STEM
PCB=OUT/(STEM+".kicad_pcb")
SCH=schematic.SCHEM
PRO=OUT/(STEM+".kicad_pro")
NET=OUT/(STEM+".net")
DRC=OUT/(STEM+"_native_drc.json")
ERC=OUT/(STEM+"_native_erc.json")
BOM=OUT/"d1_g0_integrated_trial_bom_UNQUALIFIED.csv"
RECEIPT=OUT/"d1_g0_integrated_trial_package_NOT_FOR_FAB.json"
FILES=(PCB,SCH,PRO,NET,DRC,ERC,BOM,schematic.SYMLIB,schematic.LIBTABLE)

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def known_mpns():
    result={}
    for refs,name in mpn.GROUPS:
        for ref in refs:result[ref]=name
    for ref,record in mpn.PERIPHERALS.items():
        result[ref]=record["part"]+" (design value from peripheral register; OEM not qualified)"
    for i in range(1,73):result[f"CHB{i:02d}"]="T530 OEM tentative, MPN and derating require signoff"
    return result

def write_bom(b):
    identities=known_mpns()
    with BOM.open("w",encoding="utf-8",newline="") as f:
        w=csv.writer(f,lineterminator="\n")
        w.writerow(["Ref","DesignIntentMPN_UNVERIFIED","ValueAsKiCadTrial","PhysicalPadCount","PinNetPassport","VendorQualified"])
        for component in sorted(b.GetFootprints(),key=lambda x:x.GetReference()):
            ref=component.GetReference()
            if ref not in identities:raise ValueError("Missing ref identity: "+ref)
            pins={}
            for pad in component.Pads():
                num=pad.GetNumber();net=pad.GetNetname()
                if num in pins and pins[num]!=net:
                    raise ValueError("Physical duplicate pin on conflicting nets: "+ref)
                pins[num]=net
            w.writerow([ref,identities[ref],component.GetValue(),len(component.Pads()),
                        ";".join(f"{k}={v}" for k,v in sorted(pins.items())),"NO"])

def artifact_evidence():
    if any(not p.is_file() for p in FILES):raise ValueError("Incomplete native package")
    board=pcb.LoadBoard(str(PCB))
    erc=json.loads(ERC.read_text("utf-8"))
    drc=json.loads(DRC.read_text("utf-8"))
    parts,_,pin_map=schematic.state_parts()
    pin_count=parity.verify_exported_netlist(parts,{p.ref for p in parts},NET.read_text("utf-8"))
    rv=sum(len(s.get("violations",[])) for s in erc.get("sheets",[]))
    dv=len(drc.get("violations",[]));open_net=len(drc.get("unconnected_items",[]))
    if rv or dv or open_net or len(board.GetFootprints())!=154 or pin_count!=427:
        raise ValueError(f"Bad native artifact: ERC {rv} DRC {dv} open {open_net} pins {pin_count}")
    if set(pin_map)!={f.GetReference() for f in board.GetFootprints()}:
        raise ValueError("PCB and schematic reference mismatch")
    return {
      "kind":"D1_G0_NATIVE_EDITABLE_INTEGRATED_MAINBOARD_TRIAL",
      "status":"154_DEVICE_PCB_DRC0_UNCONNECTED0_SCH_ERC0_NOT_FOR_FAB",
      "pcb_device_count":154,
      "pcb_physical_pad_objects":sum(len(f.Pads()) for f in board.GetFootprints()),
      "schematic_unique_ref_pin_net_checked":pin_count,
      "pcb_unconnected":open_net,"pcb_drc_violations":dv,
      "schematic_erc_violations":rv,
      "ignored_native_drc_checks":[x.get("key") for x in drc.get("ignored_checks",[])],
      "source_v17_sha256":sha(raw.SRC),
      "native_route_trial_sha256":sha(route.BOARD),
      "project_file_sha256":{p.name:sha(p) for p in FILES},
      "logical_magnetics":["T1","T2","T3","T4","CT"],
      "magnetics_vendor_pinout_and_DOT_verified":False,
      "magnetics_footprints_manufacturing_approved":False,
      "schematic_independently_authored":False,
      "scheme_uses_pcb_native_pad_mirror_not_vendor_symbols":True,
      "real_12v_isolated_bias_uvlo_integrated":False,
      "real_independent_48v_estop_and_hs_monitor_integrated":False,
      "via_in_pad_12layer_filled_capped_vendor_signed":False,
      "traces_current_density_emc_thermal_verified":False,
      "real_48v_coldstart_and_fault_waveforms_verified":False,
      "g0_approved":False,"g1_approved":False,
      "fabrication_approved":False,"energization_allowed":False
    }

def run():
    evidence=route.check()
    if evidence["violations"]!=0 or evidence["unconnected"]!=0:
        raise ValueError("Only zero rule/zero open routed candidate can be packaged")
    shutil.copyfile(route.BOARD,PCB)
    shutil.copyfile(raw.PROJECT,PRO)
    schematic.write()
    write_bom(pcb.LoadBoard(str(PCB)))
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    commands=[
      [str(cli),"sch","export","netlist","-o",str(NET),str(SCH)],
      [str(cli),"sch","erc","--severity-all","--format","json","-o",str(ERC),str(SCH)],
      [str(cli),"pcb","drc","--severity-all","--format","json","-o",str(DRC),str(PCB)],
    ]
    for command in commands:
        proc=subprocess.run(command,capture_output=True,text=True,errors="replace")
        if proc.returncode!=0:
            raise ValueError("KiCad tool failed "+str(command)+" "+proc.stderr)
    report=artifact_evidence()
    RECEIPT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return report

def check():
    info=json.loads(RECEIPT.read_text("utf-8"))
    r=artifact_evidence()
    if info!=r:raise ValueError("Package evidence drift")
    if sha(route.BOARD)!=info["native_route_trial_sha256"]:
        raise ValueError("Routed source changed")
    return info

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    x=parser.add_mutually_exclusive_group(required=True)
    x.add_argument("--write",action="store_true")
    x.add_argument("--check",action="store_true")
    arg=parser.parse_args()
    result=run() if arg.write else check()
    print(json.dumps({k:result[k] for k in ("status","pcb_device_count",
      "schematic_unique_ref_pin_net_checked","pcb_unconnected",
      "pcb_drc_violations","schematic_erc_violations")}))
if __name__=="__main__":main()
