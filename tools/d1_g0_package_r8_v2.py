"""G0 KiCad V2 packager: 155 devices, actual R8 DNP, no fab or energization."""
from __future__ import annotations
import argparse,csv,hashlib,json,shutil,subprocess,sys,zipfile
from pathlib import Path
import pcbnew as pcb
import d1_g0_r8_safe_enable_eco as r8
import d1_g0_native_schematic_projection as sch_source
import d1_g0_package_native_mainboard as legacy
import d1_g0_cross_domain_audit as domain
import d1_lane_c_g0_gate as pins
import main_board_schematic as golden
import check_main_board_netlist as independent

OUT=legacy.OUT.parent/"d1_g0_integrated_R8_DNP_V2_NOT_FOR_FAB"
STEM="d1_g0_integrated_mainboard_V2_R8_DNP_NOT_FOR_FAB"
BOARD=OUT/(STEM+".kicad_pcb")
SCH=OUT/(STEM+".kicad_sch")
PRO=OUT/(STEM+".kicad_pro")
NET=OUT/(STEM+".net")
DRC=OUT/(STEM+"_native_drc.json")
ERC=OUT/(STEM+"_native_erc.json")
BOM=OUT/"G0_V2_BOM_UNQUALIFIED_DNP.csv"
SYMLIB=OUT/"G0LogicalMainboard.kicad_sym"
LIBTABLE=OUT/"sym-lib-table"
REPORT=OUT/"G0_V2_Native_ERC_DRC_Golden_ECO_NotForFab.json"
README=OUT/"OPEN_FIRST_NOT_FOR_FAB.md"
ZIP=OUT/"G0_V2_155_COMPONENT_EDITABLE_KICAD_NOT_FOR_FAB.zip"
FILES=(BOARD,SCH,PRO,NET,DRC,ERC,BOM,SYMLIB,LIBTABLE,README)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def audited_source():
    assert r8.check()["r8_dnp"] is True
    board=pcb.LoadBoard(str(r8.BOARD))
    if len(board.GetFootprints())!=155:raise ValueError("R8 ECO missing")
    refs,_=domain.pinpassport(board)
    diff=independent.compare(golden.load_golden(),refs,golden.load_library())
    if diff["missing_or_wrong"] or diff["unexpected_nets"] or diff["not_placed"] or \
       set(diff["unexpected_refs"])!=domain.ALLOWED_EXTRA:
        raise ValueError("Independent source SPICE pin mismatch")
    current=domain.audited_domains(refs)
    if current["shared_primary_secondary_return_nets"]!=["PGND"]:
        raise ValueError("Isolation ground status must be reaudited")
    return board,refs,current

def schemparts():return sch_source.state_parts(source_board=r8.BOARD,expected_parts=155)

def write_sch(parts,symbols):
    SCH.write_text(sch_source.expected(parts,symbols),encoding="utf-8")
    lib=['(kicad_symbol_lib (version 20241209) (generator "d1_g0_package_r8_v2.py")']
    lib.extend(s.replace('(symbol "G0LogicalMainboard:','(symbol "',1) for s in symbols.values())
    lib.append(")")
    SYMLIB.write_text("\n".join(lib)+"\n",encoding="utf-8")
    uri="$"+"{KIPRJMOD}"+"/G0LogicalMainboard.kicad_sym"
    LIBTABLE.write_text('(sym_lib_table\n\t(version 7)\n\t(lib (name "G0LogicalMainboard")(type "KiCad")(uri "'+uri+'")(options "")(descr ""))\n)\n',encoding="utf-8")

def write_bom(board):
    names=legacy.known_mpns()
    with BOM.open("w",encoding="utf-8",newline="") as f:
        writer=csv.writer(f,lineterminator="\n")
        writer.writerow(("Ref","DesignMPN_UNQUALIFIED","NativeValue","DNP","PhysicalPads","RefPinNet","OEM_Qualified"))
        for fp in sorted(board.GetFootprints(),key=lambda x:x.GetReference()):
            ref=fp.GetReference()
            if ref not in names:raise ValueError("BOM ref unknown "+ref)
            if fp.IsDNP()!=(ref=="R8"):
                raise ValueError("Unintended DNP configuration "+ref)
            row={}
            for pad in fp.Pads():
                num=pad.GetNumber();net=pad.GetNetname()
                if num in row and row[num]!=net:raise ValueError("duplicate pin net "+ref)
                row[num]=net
            writer.writerow((ref,names[ref],fp.GetValue(),"yes" if fp.IsDNP() else "no",
                len(fp.Pads()),";".join(f"{k}={v}" for k,v in sorted(row.items())),"no"))

def evidence(board,refs,domains):
    e=json.loads(ERC.read_text("utf-8"))
    d=json.loads(DRC.read_text("utf-8"))
    er=sum(len(s.get("violations",[])) for s in e.get("sheets",[]))
    dv=len(d.get("violations",[]))
    op=len(d.get("unconnected_items",[]))
    parts,_,_=schemparts()
    n=pins.verify_exported_netlist(parts,{p.ref for p in parts},NET.read_text("utf-8"))
    if er or dv or op or n!=429 or len(refs)!=155:
        raise ValueError(f"V2 native evidence fail ERC={er} DRC={dv} open={op} pins={n}")
    return {
      "kind":"G0_155_DEVICE_KICAD_EDITABLE_NATIVE_R8_DNP_V2",
      "status":"R8_DNP_INDEPENDENT_GOLDEN0_KICAD_ERC0_DRC0_OPEN0_STILL_NOT_FOR_FAB",
      "source_154_board_sha256":sha(legacy.PCB),
      "R8_ECO_board_sha256":sha(r8.BOARD),
      "component_count":155,
      "physical_pcb_pad_objects":sum(len(f.Pads()) for f in board.GetFootprints()),
      "schematic_ref_pin_net_count":n,
      "independent_golden_mismatch_count":0,
      "native_pcb_drc_violations":dv,
      "native_pcb_unconnected":op,
      "native_schematic_erc_violations":er,
      "ignored_drc_checks":[x.get("key") for x in d.get("ignored_checks",[])],
      "R8_do_not_populate":True,
      "secondary_primary_ground_shared":domains["shared_primary_secondary_return_nets"]==["PGND"],
      "secondary_ground_reassign_pad_objects":129,
      "independent_functional_schematic_signed":False,
      "magnetics_24_vendor_pins_and_dot_verified":False,
      "isolated_bias_actual_product_board_completed":False,
      "independent_48v_ESTOP_and_HS_VGS_monitor_integrated":False,
      "12_layer_via_DFM_verified":False,
      "full_current_copper_EMC_thermal_measured":False,
      "physical_60_fault_waveforms_captured":False,
      "g0_approved":False,"g1_approved":False,
      "manufacturing_approved":False,"energization_allowed":False,
      "sha256":{f.name:sha(f) for f in FILES}
    }

def readme():
    return (
      "# KiCad 10 G0 V2 155器件整合板 (NOT_FOR_FAB)\n\n"
      "打开同名前缀 kicad_pro 工程。主板是真实 KiCad PCB 原生铜路，"
      "包含已经放置的 R8 1k 启动使能元件物理焊盘，但 R8 **DNP 未装配**，"
      "RUN 保持受 R7 下拉的关闭状态。\n\n"
      "已验证源独立 SPICE 控制/功率引脚映射差异为0；KiCad PCB DRC=0，"
      "unconnected=0，schematic ERC=0，429个唯一 Ref/Pin/net 核对。\n\n"
      "禁止制造和直接上电：PCB 的主副边 PGND 仍共用，四个 U3-U6 和八个SR"
      "和 72 个输出电容均在该公共网；In1.Cu 大平面跨两域。必须在"
      " d1_g0_secondary_return_eco_pin_table_NOT_FOR_FAB.csv 约束下重分"
      " 129 个实体焊盘并完整修改zone/trace/via，重新检查隔离。"
      "真实隔离12V、UVLO、物理48V急停和高侧VGS监测均未装入主板。"
      "T1..T4/CT 仅逻辑端子，厂家PIN/DOT/绝缘及真实绕组未验。"
      "原理图是从PCB Pad/Net反向导出的校对图，不是独立正式功能原理图。"
      "当前 G0 BLOCKED, G1 PENDING, NOT_FOR_FAB。\n"
    )

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    board,refs,domains=audited_source()
    shutil.copyfile(r8.BOARD,BOARD)
    shutil.copyfile(legacy.PRO,PRO)
    p,s,_=schemparts()
    write_sch(p,s)
    write_bom(board)
    README.write_text(readme(),encoding="utf-8")
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    cmds=[
       [str(cli),"sch","export","netlist","-o",str(NET),str(SCH)],
       [str(cli),"sch","erc","--severity-all","--format","json","-o",str(ERC),str(SCH)],
       [str(cli),"pcb","drc","--severity-all","--format","json","-o",str(DRC),str(BOARD)]
    ]
    for c in cmds:
        result=subprocess.run(c,capture_output=True,text=True,errors="replace")
        if result.returncode:raise ValueError("KiCad command fail "+str(c)+": "+result.stderr)
    result=evidence(board,refs,domains)
    REPORT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with zipfile.ZipFile(ZIP,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for f in (*FILES,REPORT):z.write(f,arcname=f.name)
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip() or len(z.namelist())!=len(FILES)+1:
            raise ValueError("ZIP archive integrity failed")
    return result

def check():
    board,refs,domains=audited_source()
    data=evidence(board,refs,domains)
    if data!=json.loads(REPORT.read_text("utf-8")):
        raise ValueError("V2 receipt stale")
    parts,syms,_=schemparts()
    if SCH.read_text("utf-8")!=sch_source.expected(parts,syms):
        raise ValueError("V2 native schematic edited without revalidation")
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip() or {x.filename for x in z.infolist()} != {f.name for f in (*FILES,REPORT)}:
            raise ValueError("V2 zip corrupted")
        for f in (*FILES,REPORT):
            if z.read(f.name)!=f.read_bytes():raise ValueError("V2 zip member stale "+f.name)
    return data

def main():
    a=argparse.ArgumentParser(description=__doc__)
    g=a.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    t=a.parse_args()
    result=build() if t.write else check()
    print(json.dumps({k:result[k] for k in
      ("status","component_count","schematic_ref_pin_net_count","native_pcb_drc_violations",
       "native_pcb_unconnected","native_schematic_erc_violations","R8_do_not_populate",
       "secondary_primary_ground_shared")}))
if __name__=="__main__":main()
