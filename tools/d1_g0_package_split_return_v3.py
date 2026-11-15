"""Editable KiCad V3: 155-device R8 DNP and true split SR return copper trial.

Source is native KiCad saved CAD split-domain trial (not a word-only ECO).
Validates the sole intentional difference to independent source golden
netlist: 129 physical secondary ground landings move from PGND to SRET.
G0 and fabrication deliberately remain BLOCKED until full physical design.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,shutil,subprocess,sys,zipfile
from pathlib import Path
import pcbnew as pcb
import d1_g0_split_return_eco_trial as split
import d1_g0_native_schematic_projection as schematic
import d1_g0_package_r8_v2 as v2
import d1_g0_cross_domain_audit as domain
import d1_lane_c_g0_gate as parity
import main_board_schematic as golden
import check_main_board_netlist as compare

OUT=v2.OUT.parent/"d1_g0_integrated_SPLIT_RETURN_V3_NOT_FOR_FAB"
STEM="d1_g0_integrated_mainboard_V3_SPLIT_RETURN_NOT_FOR_FAB"
PCB=OUT/(STEM+".kicad_pcb")
SCH=OUT/(STEM+".kicad_sch")
PRO=OUT/(STEM+".kicad_pro")
NET=OUT/(STEM+".net")
DRC=OUT/(STEM+"_native_drc.json")
ERC=OUT/(STEM+"_native_erc.json")
BOM=OUT/"G0_V3_BOM_NativePadNet_DNP.csv"
SYMLIB=OUT/"G0LogicalMainboard.kicad_sym"
LIBTABLE=OUT/"sym-lib-table"
MIGRATION=OUT/"secondary_129_physical_pad_migration_FROM_PGND.csv"
ECOREPORT=OUT/"V3_native_split_return_ECO_receipt.json"
REPORT=OUT/"G0_V3_native_design_isolation_gate_NOT_FOR_FAB.json"
README=OUT/"OPEN_FIRST_NOT_FOR_FAB.md"
ZIP=OUT/"G0_V3_155_COMPONENT_SPLIT_RETURN_KICAD_NOT_FOR_FAB.zip"
PACKAGE=(PCB,SCH,PRO,NET,DRC,ERC,BOM,SYMLIB,LIBTABLE,MIGRATION,ECOREPORT,README)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def source():
    spr=split.check()
    if spr["native_DRC_violations"] or spr["native_DRC_unconnected"]:
        raise ValueError("split board source native DRC not clean")
    board=pcb.LoadBoard(str(split.BOARD))
    refs,pads=domain.pinpassport(board)
    dom=domain.audited_domains(refs)
    if not dom["isolation_domain_split_complete"] or len(refs)!=155 or \
       dom["shared_primary_secondary_return_nets"]:
        raise ValueError("G0 isolation domain nets not physically split")
    pairs=0
    normalized={k:dict(v) for k,v in refs.items()}
    for ref,netpins in domain.SECONDARY_RET_REFS.items():
        for pin in netpins:
            if refs[ref][pin]!=domain.SRET:raise ValueError("Secondary actual pad still PGND "+ref+"."+pin)
            normalized[ref][pin]="PGND"
            pairs+=1
    if pairs!=sum(len(p) for p in domain.SECONDARY_RET_REFS.values()):
        raise ValueError("Secondary normalized pin-pair count drift")
    independent=compare.compare(golden.load_golden(),normalized,golden.load_library())
    if independent["missing_or_wrong"] or independent["unexpected_nets"] or \
       independent["not_placed"] or set(independent["unexpected_refs"])!=domain.ALLOWED_EXTRA:
        raise ValueError("Unexpected golden net mismatch beyond intended SRET rename")
    dnp={f.GetReference() for f in board.GetFootprints() if f.IsDNP()}
    if dnp!={"R8"}:raise ValueError("R8 must be the only DNP")
    return board,refs,dom,pairs

def parts():return schematic.state_parts(source_board=split.BOARD,expected_parts=155)

def write_sch(pt,sy):
    SCH.write_text(schematic.expected(pt,sy),encoding="utf-8")
    output=['(kicad_symbol_lib (version 20241209) (generator "d1_g0_package_split_return_v3.py")']
    output.extend(s.replace('(symbol "G0LogicalMainboard:','(symbol "',1) for s in sy.values())
    output.append(")")
    SYMLIB.write_text("\n".join(output)+"\n",encoding="utf-8")
    uri="$"+"{KIPRJMOD}"+"/G0LogicalMainboard.kicad_sym"
    LIBTABLE.write_text('(sym_lib_table\n\t(version 7)\n\t(lib (name "G0LogicalMainboard")(type "KiCad")(uri "'+uri+'")(options "")(descr ""))\n)\n',encoding="utf-8")

def bom(board):
    names=v2.legacy.known_mpns()
    with BOM.open("w",newline="",encoding="utf-8") as fh:
        w=csv.writer(fh,lineterminator="\n")
        w.writerow(("Ref","DesignMPN_UNQUALIFIED","NativeValue","DNP","PhysicalPadObjects","RefPadNet","QualifiedForFab"))
        for f in sorted(board.GetFootprints(),key=lambda x:x.GetReference()):
            ref=f.GetReference()
            if ref not in names:raise ValueError("unknown BOM ref "+ref)
            dnp=f.IsDNP()
            if dnp!=(ref=="R8"):raise ValueError("DNP mismatch")
            phys=[(p.GetNumber(),p.GetNetname()) for p in f.Pads()]
            if len(set(x for x,y in phys))<1:raise ValueError("BOM missing pad")
            w.writerow((ref,names[ref],f.GetValue(),"yes" if dnp else "no",
                len(phys),";".join(a+"="+b for a,b in sorted(set(phys))),"no"))

def readme():
    return (
      "# G0 V3 155器件原生KiCad分域主板（严禁制造、上电）\n\n"
      "打开同名前缀 .kicad_pro。本次实际修改129个输出整流/去耦/端子焊盘、"
      "181个原PGND副边走线或过孔、6块副边地铜区；原横跨全板的"
      " In1.Cu PGND 改为原副边分割铜区，补 T4 初级 PGND 回流走廊。"
      " R8 启动电阻仅有真实焊盘与走线但为 DNP，禁止自动开机。\n\n"
      "原生 KiCad: PCB DRC规则违规0、未连接0、原理图ERC0，"
      "429个Ref/Pin/Net与可编辑schematic一致；"
      "与独立黄金电路引脚表仅有经明确签单的129个副边PGND->SRET ECO。\n\n"
      "目前不是已取得绝缘认证的隔离电源，理由：所有磁件和CT仍为"
      "缺厂家实体端子/DOT/匝数/绝缘/工艺的逻辑落点；所有磁芯安装"
      "跨层过孔/层压板爬电距离尚未审查；正式控制/保护原理图未独立签核；"
      "两路12V偏置、UVLO、48V硬件急停和高侧VGS监测没有实际装进这块主板；"
      "实测60组故障波形、限流启动、EMC、铜损、热与DFM缺失。"
      " R8不得焊接直至联锁保护实装并经G0实物签核；仍有5类忽略DRC检查。"
      " 现在 G0 BLOCKED / G1 PENDING / NOT_FOR_FAB。\n"
    )

def receipt(board,refs,dom,pairs):
    dr=json.loads(DRC.read_text("utf-8"))
    er=json.loads(ERC.read_text("utf-8"))
    dv=len(dr.get("violations",[]))
    gaps=len(dr.get("unconnected_items",[]))
    ev=sum(len(s.get("violations",[])) for s in er.get("sheets",[]))
    pt,_,_=parts()
    n=parity.verify_exported_netlist(pt,{x.ref for x in pt},NET.read_text("utf-8"))
    if dv or gaps or ev or n!=429 or pairs!=sum(len(p) for p in domain.SECONDARY_RET_REFS.values()):
        raise ValueError(f"Native V3 checks fail drc {dv} gaps {gaps} erc {ev} pins {n}")
    return {
      "kind":"D1_G0_V3_PHYSICAL_SPLIT_RETURN_NativeKiCad",
      "status":"G0_V3_155_PCB_129_SRET_DRC0_OPEN0_ERC0_STILL_NOT_FOR_FAB",
      "component_count":155,"unique_native_ref_pin_nets":n,
      "physical_pcb_pad_objects":sum(len(f.Pads()) for f in board.GetFootprints()),
      "changed_secondary_unique_pins":pairs,
      "changed_secondary_physical_pads":129,
      "changed_secondary_pgnd_tracks_and_vias":split.check()["converted_pgnd_secondary_tracks_or_vias"],
      "native_drc_rule_violations":dv,"native_pcb_unconnected":gaps,
      "native_schematic_erc_violations":ev,
      "ignored_native_drc_checks":[x.get("key") for x in dr.get("ignored_checks",[])],
      "independent_SPICE_golden_net_differences_after_intentional_ECO_normalization":0,
      "primary_secondary_pcb_net_names_separate":dom["isolation_domain_split_complete"],
      "SR_SOURCE_RETURN_connected_to_primary_PGND_in_netlist":False,
      "R8_DNP":True,"automatic_control_enable":False,
      "native_source_split_board_sha256":sha(split.BOARD),
      "files_sha256":{f.name:sha(f) for f in PACKAGE},
      "vendor_magnetics_24_terminal_DOT_qualified":False,
      "independent_functional_schematic_qualified":False,
      "safety_isolation_clearance_certified":False,
      "two_12v_isolated_bias_modules_integrated_in_mainboard":False,
      "hardwired_48v_power_ESTOP_integrated":False,
      "floating_high_side_vgs_monitor_integrated":False,
      "pcb_stackup_via_DFM_and_EMC_qualified":False,
      "hardware_gate_off_witnesses_completed":False,
      "g0_approved":False,"g1_approved":False,
      "manufacturing_approved":False,"energization_allowed":False
    }

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    board,refs,dom,n=source()
    shutil.copyfile(split.BOARD,PCB)
    shutil.copyfile(v2.PRO,PRO)
    shutil.copyfile(domain.MIGRATE,MIGRATION)
    shutil.copyfile(split.REPORT,ECOREPORT)
    pt,sy,_=parts()
    write_sch(pt,sy)
    bom(board)
    README.write_text(readme(),encoding="utf-8")
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    commands=(
      [str(cli),"sch","export","netlist","-o",str(NET),str(SCH)],
      [str(cli),"sch","erc","--severity-all","--format","json","-o",str(ERC),str(SCH)],
      [str(cli),"pcb","drc","--severity-all","--format","json","-o",str(DRC),str(PCB)]
    )
    for c in commands:
        r=subprocess.run(c,capture_output=True,text=True,errors="replace")
        if r.returncode:raise ValueError("KiCad V3 failed command "+str(c)+" "+r.stderr)
    data=receipt(board,refs,dom,n)
    REPORT.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with zipfile.ZipFile(ZIP,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for f in (*PACKAGE,REPORT):z.write(f,f.name)
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip() or len(z.infolist())!=len(PACKAGE)+1:
            raise ValueError("V3 archive verification failed")
    return data

def check():
    b,refs,dom,n=source()
    data=receipt(b,refs,dom,n)
    if data!=json.loads(REPORT.read_text("utf-8")):
        raise ValueError("V3 package evidence stale")
    pt,sy,_=parts()
    if SCH.read_text("utf-8")!=schematic.expected(pt,sy):
        raise ValueError("V3 editable schematic stale")
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip() or {i.filename for i in z.infolist()}!={f.name for f in (*PACKAGE,REPORT)}:
            raise ValueError("V3 zip missing or corrupt")
        for f in (*PACKAGE,REPORT):
            if z.read(f.name)!=f.read_bytes():
                raise ValueError("V3 zip member stale "+f.name)
    return data

def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    o=p.parse_args()
    result=build() if o.write else check()
    print(json.dumps({k:result[k] for k in (
      "status","component_count","unique_native_ref_pin_nets",
      "changed_secondary_physical_pads","changed_secondary_pgnd_tracks_and_vias",
      "native_drc_rule_violations","native_pcb_unconnected",
      "native_schematic_erc_violations")}))
if __name__=="__main__":main()
