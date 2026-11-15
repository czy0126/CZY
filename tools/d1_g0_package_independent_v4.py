"""Full independent-source KiCad V4: 157 devices, split ground and dual bench bias ports.

An improvement over V1-V3 reverse netlist diagrams: here SCH pad nets are
authored from independently existing SPICE golden design, measured library
pin maps, independently defined peripherals, explicit 129-pad SRET ECO and
2 named isolated 12V physical bench ports. Exact 433 Ref/Pin/Net are compared
with the separately saved native KiCad PCB, never generated from its pins.
No physical G0, isolation certification or manufacturing clearance is claimed.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,shutil,subprocess,sys,zipfile
from pathlib import Path
import pcbnew as pcb
import d1_g0_independent_design_source_schematic as source
import d1_g0_bias_ports_v4 as bias
import d1_g0_split_return_eco_trial as split
import d1_g0_package_r8_v2 as v2
import d1_lane_c_g0_gate as pin_parity

OUT=bias.OUT.parent/"d1_g0_INDEPENDENT_SOURCE_V4_MAINBOARD_NOT_FOR_FAB"
STEM="d1_g0_157_PART_INDEPENDENT_SOURCE_MAINBOARD_NOT_FOR_FAB"
PCB=OUT/(STEM+".kicad_pcb")
SCHEM=OUT/(STEM+".kicad_sch")
PROJECT=OUT/(STEM+".kicad_pro")
NET=OUT/(STEM+".net")
DRC=OUT/(STEM+"_native_drc.json")
ERC=OUT/(STEM+"_native_erc.json")
SYMLIB=OUT/"G0IndependentDesignSources.kicad_sym"
TABLE=OUT/"sym-lib-table"
BOM=OUT/"G0_V4_157_PART_MANUFACTURING_STOPLINE_BOM.csv"
INDEPENDENT_RECEIPT=OUT/"independent_design_to_native_433_pins_receipt.json"
SPLIT_RECEIPT=OUT/"actual_129_pads_181_tracks_return_split_receipt.json"
BIAS_RECEIPT=OUT/"physical_2_bias_port_native_evidence.json"
SECONDARY_ECO=OUT/"secondary_129_physical_pads_FROM_PGND.csv"
REPORT=OUT/"V4_mainboard_acceptance_NOT_FOR_FAB.json"
README=OUT/"OPEN_FIRST_NOT_FOR_FAB.md"
ZIP=OUT/"G0_V4_157_PART_INDEPENDENT_SCHEMATIC_EDITABLE_KICAD_NOT_FOR_FAB.zip"
FILES=(PCB,SCHEM,PROJECT,NET,DRC,ERC,SYMLIB,TABLE,BOM,
       INDEPENDENT_RECEIPT,SPLIT_RECEIPT,BIAS_RECEIPT,SECONDARY_ECO,README)

def sha(file):return hashlib.sha256(file.read_bytes()).hexdigest()

def check_source():
    s=source.check()
    b=bias.check()
    g=split.check()
    if s["independent_ref_pin_net_count"]!=433 or b["physical_board_footprints"]!=157 or \
       b["primary_secondary_return_nets_shared"] or g["converted_physical_pads"]!=129:
        raise ValueError("three separate source receipts are not aligned")
    return s,b,g

def write_bom(board):
    identities=v2.legacy.known_mpns()
    identities.update({name:f"PROVISIONAL_2x5mm_PTH_12V_EXTERNAL_{name}"
                       for name in bias.PORTS})
    with BOM.open("w",encoding="utf-8",newline="") as f:
        w=csv.writer(f,lineterminator="\n")
        w.writerow(["Designator","DesignIntentMPN_VENDOR_UNVERIFIED","DNP",
           "NativeTrialValue","NativePadObjects","NativeRefPinNet","QualifiedPCBFootprint",
           "RealMagneticPinDotSigned"])
        for part in sorted(board.GetFootprints(),key=lambda x:x.GetReference()):
            ref=part.GetReference()
            if ref not in identities:raise ValueError("missing design part identity "+ref)
            if part.IsDNP()!=(ref=="R8"):raise ValueError("R8 enable-DNP authority drift")
            pads={}
            for p in part.Pads():
                num=p.GetNumber();net=p.GetNetname()
                if num in pads and pads[num]!=net:raise ValueError("different nets on same design pin")
                pads[num]=net
            w.writerow([ref,identities[ref],"yes" if part.IsDNP() else "no",
                 part.GetValue(),len(part.Pads()),
                 ";".join(f"{k}={v}" for k,v in sorted(pads.items())),"no","no"])

def readme():
    return (
      "# D1 G0 V4 157器件：真实PCB + 独立黄金设计来源的KiCad原理图\n\n"
      "首选打开本目录同名前缀 kicad_pro 工程。ZIP同时包含 KiCad PCB、"
      "独立电气设计来源 SCH、本地符号库、原生网表、ERC/DRC、BOM、"
      "129物理焊盘迁移表、三段工程证据及 SHA 验收报告。\n\n"
      "PCB实际完成：129副边焊盘迁入 SR_SOURCE_RETURN，"
      "181条副边铜线/过孔重新分网，In1原副边地平面物理分割，"
      "T4初级回流经槽间走廊接原边；R8启动1k焊盘已接入但 DNP，不启动。"
      "新增独立原边 J_BIAS_P(VCC12,PGND) 与副边"
      "J_BIAS_S(VCC12_S,SR_SOURCE_RETURN) 实体2x5mm暂定PTH端子。"
      "PCB ERC/DRC及未连接均0（具体见报告）。\n\n"
      "SCH不是PCB反向投影；它独立来自 SPICE黄金netlist、真实库pin扩展、"
      "控制外围寄存器、72颗电容设计及公开的129pin SRET工程变更。"
      "157个Ref/Pin/Net逐项与PCB核验，总433个独立pin，SCH ERC0。"
      "但仍是**工程化简符号与逻辑连接**，并非真实电路安全功能签核，"
      "控制器物理接线和器件参数须进一步审查。\n\n"
      "严禁直接制板/通电：厂商磁件端子/DOT/匝比/耐压未验；"
      "没有板载双路隔离12V转换、UVLO、硬件独立48V急停、"
      "浮地VGS监测及十路门极实物故障验证；外部12V连接器MPN/熔断"
      "及12层Stackup/via/开槽、铜损、温升/EMC均未签核。"
      "五类KiCad ignored DRC仍存在。安全许可G0 BLOCKED/G1 PENDING。\n"
    )

def record():
    s,b,g=check_source()
    board=pcb.LoadBoard(str(PCB))
    er=json.loads(ERC.read_text("utf-8"))
    dr=json.loads(DRC.read_text("utf-8"))
    parts,_,model=source.parts()
    n=pin_parity.verify_exported_netlist(parts,{p.ref for p in parts},NET.read_text("utf-8"))
    if n!=433 or len(board.GetFootprints())!=157:
        raise ValueError("V4 PCB+SCH count mismatch")
    if er.get("sheets") is None:raise ValueError("Native KiCad ERC schema changed")
    ev=sum(len(x.get("violations",[])) for x in er["sheets"])
    dv=len(dr.get("violations",[]))
    nc=len(dr.get("unconnected_items",[]))
    if ev or dv or nc:raise ValueError(f"V4 still has EDA defects ERC={ev} DRC={dv} Opens={nc}")
    refmap={x.GetReference():x for x in board.GetFootprints()}
    if any(refmap[ref].IsDNP() != (ref=="R8") for ref in refmap):
        raise ValueError("R8 DNP not preserved in 157 PCB")
    if s["native_erc_violations"] or s["PCB_source_sha256"]!=sha(bias.BOARD):
        raise ValueError("Independent schematic source changed")
    return {
     "kind":"D1_G0_V4_157_NATIVE_KICAD_INDEPENDENT_SOURCE_MAINBOARD",
     "status":"157_NATIVE_PARTS_PCB_SOURCE_AUTHORED_SCH_ERC0_DRC0_OPEN0_NOT_FOR_FAB",
     "PCB_footprints":len(board.GetFootprints()),
     "independent_schematic_ref_pin_net_parity":n,
     "native_PCB_ERC_violations":ev,
     "native_PCB_DRC_violations":dv,
     "native_PCB_unconnected":nc,
     "secondary_physically_reassigned_pads":g["converted_physical_pads"],
     "secondary_pgnd_tracks_or_vias_reassigned":g["converted_pgnd_secondary_tracks_or_vias"],
     "external_isolated_12v_input_ports":2,
     "hardware_R8_is_DNP":True,
     "independent_SCH_generated_from_PCB":False,
     "independent_SCH_generated_from_SPICE_golden_and_peripherals":True,
     "independent_SCH_vendor_symbol_graphics_validated":False,
     "source_V4_bias_port_PCB_sha256":sha(bias.BOARD),
     "fabrication_drc_ignored_checks":[x.get("key") for x in dr.get("ignored_checks",[])],
     "manufacturing_magnetics_physical_pin_DOT_approved":False,
     "physical_isolation_clearance_and_dielectric_verified":False,
     "real_dual_12v_supply_and_uvlo_integrated":False,
     "hardware_48v_estop_and_hs_vgs_monitor_integrated":False,
     "high_current_copper_losses_EMC_thermal_verified":False,
     "60_gate_fault_witness_waveforms_measured":False,
     "G0_signed":False,"G1_signed":False,
     "fab_release":False,"energization_allowed":False,
     "package_sha256":{f.name:sha(f) for f in FILES},
    }

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    check_source()
    shutil.copyfile(bias.BOARD,PCB)
    shutil.copyfile(source.PRO,PROJECT)
    shutil.copyfile(source.SCH,SCHEM)
    shutil.copyfile(source.SYMLIB,SYMLIB)
    shutil.copyfile(source.TABLE,TABLE)
    shutil.copyfile(source.REPORT,INDEPENDENT_RECEIPT)
    shutil.copyfile(split.REPORT,SPLIT_RECEIPT)
    shutil.copyfile(bias.REPORT,BIAS_RECEIPT)
    shutil.copyfile(source.dom.MIGRATE,SECONDARY_ECO)
    write_bom(pcb.LoadBoard(str(PCB)))
    README.write_text(readme(),encoding="utf-8")
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    for cmd in (
       [str(cli),"sch","export","netlist","-o",str(NET),str(SCHEM)],
       [str(cli),"sch","erc","--severity-all","--format","json","-o",str(ERC),str(SCHEM)],
       [str(cli),"pcb","drc","--severity-all","--format","json","-o",str(DRC),str(PCB)]
    ):
        r=subprocess.run(cmd,capture_output=True,text=True,errors="replace")
        if r.returncode:raise ValueError("KiCad V4 CLI failed "+str(cmd)+r.stderr)
    data=record()
    REPORT.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with zipfile.ZipFile(ZIP,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for file in (*FILES,REPORT):z.write(file,file.name)
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip() or len(z.infolist())!=len(FILES)+1:
            raise ValueError("V4 ZIP integrity issue")
    return data

def check():
    result=record()
    if result!=json.loads(REPORT.read_text("utf-8")):
        raise ValueError("V4 source and release receipt stale")
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip() or {x.filename for x in z.infolist()}!={f.name for f in (*FILES,REPORT)}:
            raise ValueError("V4 ZIP missing/corrupt")
        for f in (*FILES,REPORT):
            if z.read(f.name)!=f.read_bytes():
                raise ValueError("V4 ZIP stale "+f.name)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    opt=parser.parse_args()
    r=build() if opt.write else check()
    print(json.dumps({k:r[k] for k in ("status","PCB_footprints",
     "independent_schematic_ref_pin_net_parity","native_PCB_DRC_violations",
     "native_PCB_unconnected","native_PCB_ERC_violations",
     "secondary_physically_reassigned_pads","external_isolated_12v_input_ports")}))
if __name__=="__main__":main()
