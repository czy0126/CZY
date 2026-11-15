"""Ship native 161-device KiCad V5, independently authored UCC24624 Kelvin SCH.

Includes from V4: split SR/primary returns and 2 external 12V ports.
New: U3-U6 VSS true separate net until local reference 0R, C7-C10
nominal 2.2uF 25V 0603. Physical bias modules and E-stop NOT implemented.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,shutil,subprocess,sys,zipfile
from pathlib import Path
import pcbnew as pcb
import d1_g0_sr_kelvin_reg_eco_v5 as copper
import d1_g0_sr_kelvin_independent_sch_v5 as schematic
import d1_g0_package_independent_v4 as old
import d1_g0_cross_domain_audit as domain
import d1_lane_c_g0_gate as parity
import d1_g0_package_r8_v2 as inventory

OUT=old.OUT.parent/"d1_g0_UCC24624_KELVIN_V5_INTEGRATED_MAINBOARD_NOT_FOR_FAB"
STEM="d1_g0_161_PART_SR_KELVIN_SOURCE_AUTHORED_NOT_FOR_FAB"
PCB=OUT/(STEM+".kicad_pcb")
SCH=OUT/(STEM+".kicad_sch")
PRO=OUT/(STEM+".kicad_pro")
NET=OUT/(STEM+".net")
DRC=OUT/(STEM+"_native_drc.json")
ERC=OUT/(STEM+"_native_erc.json")
SYMLIB=OUT/"G0SRKelvinSource.kicad_sym"
TABLE=OUT/"sym-lib-table"
BOM=OUT/"G0_V5_161_NATIVE_PINNET_BOM_UNQUALIFIED.csv"
KELVIN=OUT/"V5_source_kelvin_physical_ECO_receipt.json"
SCH_RECEIPT=OUT/"V5_source_authored_441_PIN_SCH_receipt.json"
REPORT=OUT/"V5_integrated_KiCad_ERC_DRC_isolation_gate_NOT_FOR_FAB.json"
README=OUT/"OPEN_FIRST_NOT_FOR_FAB.md"
ZIP=OUT/"G0_V5_161_PART_KELVIN_SOURCE_AUTHORED_EDITABLE_KICAD_NOT_FOR_FAB.zip"
FILES=(PCB,SCH,PRO,NET,DRC,ERC,SYMLIB,TABLE,BOM,KELVIN,SCH_RECEIPT,README)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def source_receipts():
    physical=copper.check()
    independent=schematic.check()
    if physical["KiCad_native_DRC_violations"] or physical["KiCad_native_unconnected"]:
        raise ValueError("V5 native SRAM Kelvin ECO bad DRC/open")
    if independent["independent_native_schematic_pin_parity"]!=441:
        raise ValueError("V5 independent schematic pin count wrong")
    return physical,independent

def write_bom(board):
    x=inventory.legacy.known_mpns()
    x.update({n:f"EXT_PTH_NOT_QUALIFIED_{n}" for n in old.bias.PORTS})
    x.update({f"RK{i}":"Yageo RC0603JR-070RL 0R" for i in range(1,5)})
    for i in range(7,11):x[f"C{i}"]=copper.MURATA
    with BOM.open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f,lineterminator="\n")
        w.writerow(["Ref","Design_MPN_NOT_FOR_FAB","Value","DNP",
                    "UniquePadPins","PhysicalPadObjects","Pad_NetPassport","OEM_Qualified"])
        for fp in sorted(board.GetFootprints(),key=lambda x:x.GetReference()):
            ref=fp.GetReference()
            if ref not in x:raise ValueError("Unknown native MPN"+ref)
            if fp.IsDNP()!=(ref=="R8"):raise ValueError("R8 start enable no longer DNP")
            pinmap={}
            for p in fp.Pads():
                k=p.GetNumber();v=p.GetNetname()
                if k in pinmap and pinmap[k]!=v:raise ValueError("ambiguous duplicate physical pin")
                pinmap[k]=v
            w.writerow((ref,x[ref],fp.GetValue(),"yes" if fp.IsDNP() else "no",
              len(pinmap),len(fp.Pads()),
              ";".join(f"{pn}={net}" for pn,net in sorted(pinmap.items())),"no"))

def instructions():
    return (
      "# D1 G0 V5 161器件原生KiCad整合主板（禁止制板/上电）\n\n"
      "打开同名前缀的 .kicad_pro。该工程可编辑 PCB/SCH、项目内符号库、"
      "真实 KiCad ERC/DRC、netlist、逐脚BOM、V4→V5工程收据及 SHA ZIP。"
      "原副边回流仍维持 PGND 和 SR_SOURCE_RETURN 分离，偏置 J_BIAS_P/S 分开。"
      "实测的 T1-T4/CT 等实体磁件/安全电源系统并未完成。\n\n"
      "新增4个UCC24624同步整流控制器 U3-U6 pin5 VSS 独立 SR_KELVIN_1..4"
      "检测线，使用四个 RK1-4 0603 0R 连接至对应SR MOS区域的本地"
      " SR_SOURCE_RETURN；U3-U6 pin2 PGND维持独立门驱电流回流网。"
      "感测回路走 In9.Cu，部分过孔是普通12层贯通via，并非工艺验证的"
      "专用埋孔或低噪声Kelvin终极布线。真实SR负压关断偏移和噪声实测缺失。\n\n"
      "实际C7-C10的REG去耦仍保留原0603焊盘，设计标记 Murata"
      " GRM188C71E225KE11, 2.2uF 25V X7S。**11V DC bias时有效电容量"
      "可能小于标称2.2uF，尚未完成厂家C(V)曲线与关断验证，不能以"
      "标称容值代替实际有效容值**；可以按测量适当并联/改大封装。\n\n"
      "原生KiCad PCB DRC=0, unconnected=0; SCH ERC=0, 441个独立"
      " SPICE +外设+可追踪Kelvin ECO Ref-Pin-Net一一匹配。"
      " **仍无 板载48→12V隔离模块/熔断/完整UVLO/独立48V急停/HS差分VGS"
      "监控/可认证磁件封装。**不可制造不可直接上48V。"
      " 需先把G0的9项实体见证与60组故障波形补齐，并对所有忽略的"
      " KiCad DRC 重新审查。R8启动路径始终DNP，不得自行上件。\n"
    )

def record():
    physical,independent=source_receipts()
    board=pcb.LoadBoard(str(PCB))
    original={fp.GetReference():fp for fp in board.GetFootprints()}
    if len(original)!=161 or {r for r in original if r.startswith("RK")}!={"RK1","RK2","RK3","RK4"}:
        raise ValueError("Kelvin 0R pads missing")
    er=json.loads(ERC.read_text("utf-8"))
    dr=json.loads(DRC.read_text("utf-8"))
    ev=sum(len(s.get("violations",[])) for s in er.get("sheets",[]))
    dv=len(dr.get("violations",[]))
    nc=len(dr.get("unconnected_items",[]))
    pts,_,mapping=schematic.parts()
    pins=parity.verify_exported_netlist(pts,{p.ref for p in pts},NET.read_text("utf-8"))
    if ev or dv or nc or pins!=441:raise ValueError(f"V5 native integrity fails ERC{ev}/DRC{dv}/open{nc}/pins{pins}")
    return {
      "kind":"D1_G0_V5_KICAD_INDEPENDENT_KELVIN_REG_MAINBOARD",
      "status":"161_NATIVE_PARTS_KELVIN_SEPARATE_ERC0_DRC0_OPEN0_G0_BLOCKED",
      "PCB_footprints":len(original),
      "schematic_independent_ref_pin_net_parity":pins,
      "native_pcb_DRC_violations":dv,
      "native_pcb_unconnected":nc,
      "native_schematic_ERC_violations":ev,
      "primary_secondary_copper_returns_separate":True,
      "four_controller_VSS_kelvin_separate_from_gate_current_return":True,
      "four_0R_source_near_SR_reference_footprints":True,
      "four_C_REG_assigned_Murata_2u2_25V_X7S":True,
      "REG_2u2_effective_at_11v_and_kelvin_switching_noise_verified":False,
      "V4_12v_two_external_input_ports_present":True,
      "input_48v_to_12v_isolated_modules_built_in":False,
      "physical_power_estop_and_high_side_monitor_present":False,
      "12_layer_stackup_and_via_DFM_qualified":False,
      "vendor_magnetics_pin_DOT_and_insulation_qualified":False,
      "60_actual_fault_waveforms_measured":False,
      "ignored_KiCad_DRC_categories":[x.get("key") for x in dr.get("ignored_checks",[])],
      "R8_default_DNP":original["R8"].IsDNP(),
      "energization_allowed":False,"G0_approved":False,"fabrication_approved":False,
      "source_V4_PCB_SHA":sha(old.PCB),
      "source_V5_copper_ECO_SHA":sha(copper.BOARD),
      "sha256":{f.name:sha(f) for f in FILES}
    }

def write():
    OUT.mkdir(parents=True,exist_ok=True)
    physical,independent=source_receipts()
    for src,dst in (
      (copper.BOARD,PCB),(schematic.SCH,SCH),(schematic.PRO,PRO),
      (schematic.SYMLIB,SYMLIB),(schematic.LIBTABLE,TABLE),
      (copper.REPORT,KELVIN),(schematic.REPORT,SCH_RECEIPT)
    ):
        shutil.copyfile(src,dst)
    write_bom(pcb.LoadBoard(str(PCB)))
    README.write_text(instructions(),encoding="utf-8")
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    for cmd in (
       [str(cli),"sch","export","netlist","-o",str(NET),str(SCH)],
       [str(cli),"sch","erc","--severity-all","--format","json","-o",str(ERC),str(SCH)],
       [str(cli),"pcb","drc","--severity-all","--format","json","-o",str(DRC),str(PCB)]
    ):
        run=subprocess.run(cmd,capture_output=True,text=True,errors="replace")
        if run.returncode:raise ValueError("KiCad V5 CLI failed: "+str(cmd)+run.stderr)
    r=record()
    REPORT.write_text(json.dumps(r,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with zipfile.ZipFile(ZIP,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for f in (*FILES,REPORT):z.write(f,f.name)
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip() or len(z.namelist())!=len(FILES)+1:
            raise ValueError("V5 ZIP corruption")
    return r

def check():
    r=record()
    if r!=json.loads(REPORT.read_text("utf-8")):
        raise ValueError("V5 receipt stale")
    pt,sym,model=schematic.parts()
    if SCH.read_text("utf-8")!=schematic.expected_sch(pt,sym):
        raise ValueError("V5 schematic drift")
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip() or {i.filename for i in z.infolist()}!={f.name for f in (*FILES,REPORT)}:
            raise ValueError("V5 ZIP corruption")
        for f in (*FILES,REPORT):
            if z.read(f.name)!=f.read_bytes():raise ValueError("V5 ZIP stale member "+f.name)
    return r

def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    a=p.parse_args()
    data=write() if a.write else check()
    print(json.dumps({k:data[k] for k in
      ("status","PCB_footprints","schematic_independent_ref_pin_net_parity",
       "native_pcb_DRC_violations","native_pcb_unconnected","native_schematic_ERC_violations")}))
if __name__=="__main__":main()
