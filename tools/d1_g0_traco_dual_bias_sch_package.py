"""Generate independent functional KiCad schematic + packaged real THN30 bias carrier.

Two THN 30-4812 with manufacturer layout verified; two separately
fused 48V input feeds, 2x input caps, 4 output 22uF ceramics, three
2-pole connectors. This is a real native 2-layer PCB + independently
authored KiCad schematic, not a physical G0 hardware/fab approval.

Source: https://www.tracopower.com/products/thn30.pdf Rev 2024-02-07
"""
from __future__ import annotations
import argparse,csv,hashlib,json,shutil,subprocess,sys,zipfile
from pathlib import Path
import pcbnew as pcb
import make_d0_protection_board as k
import d1_lane_c_bias_supply_candidate as old
import d1_g0_traco_dual_bias_daughterboard as carrier
import d1_lane_c_g0_gate as parity

OUT=carrier.OUT
STEM=carrier.NAME
PCB=carrier.BOARD
SCH=OUT/(STEM+".kicad_sch")
PRO=OUT/(STEM+".kicad_pro")
NET=OUT/(STEM+".net")
ERC=OUT/(STEM+"_native_erc.json")
DRC=carrier.DRC
SYMLIB=OUT/"TracoTHN30.kicad_sym"
LIBTABLE=OUT/"sym-lib-table"
BOM=OUT/"G0_dual_30W_bias_carrier_vendor_MPN_UNQUALIFIED.csv"
REPORT=OUT/"G0_dual_30W_isolated_bias_CAD_acceptance_NOT_FOR_FAB.json"
README=OUT/"OPEN_FIRST_NOT_FOR_FAB.md"
ZIP=OUT/"G0_TWO_THN30_4812_REAL_BIAS_CARRIER_EDITABLE_KICAD_NOT_FOR_FAB.zip"
FILES=(PCB,SCH,PRO,NET,ERC,DRC,SYMLIB,LIBTABLE,BOM,carrier.REPORT,README)
FOOT={
 "module":"Converter_DCDC:Converter_DCDC_TRACO_THN30-xxxx_THT",
 "fuse":"Fuse:Fuse_1812_4532Metric",
 "input_cap":"Capacitor_SMD:C_1206_3216Metric",
 "output_cap":"Capacitor_SMD:C_1210_3225Metric",
 "connector":"TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm",
}
LIBNAME={
 "module":old.LIB,"fuse":"Device:Fuse","input_cap":"Device:C",
 "output_cap":"Device:C","connector":"Connector_Generic:Conn_01x02",
}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def source_parts():
    a=[]
    for n,(ref,d) in enumerate(carrier.PARTS.items()):
        x,y=d["position"]
        a.append(k.snap(k.Part(
           ref,LIBNAME[d["type"]],d["value"],FOOT[d["type"]],
           30+50*(n%5),50+25*(n//5),
           {pin:net if net else k.NC for pin,net in d["pins"].items()},
           source="vendor THN30 datasheet and independent G0 48V bias carrier 2-layer contract",
           note="Fuses/caps/connector MPN and isolation not factory qualified")))
    for i,net in enumerate((
        "VIN48_PRE","PGND","VIN48P_F","VIN48S_F",
        "VCC12","VCC12_S","SR_SOURCE_RETURN")):
        a.append(k.snap(k.Part(f"#PWR{i+1}","power:PWR_FLAG","PWR_FLAG","",
            25+i*20,160,{"1":net},
            note="schematic ERC logic power source marker, not hardware")))
    return a

def symbols(ps):
    return old.symbols(ps)

def authoritative():
    ps=source_parts()
    sy=symbols(ps)
    k.validate(ps,sy)
    sh=k.schematic(sy,ps)
    sh=sh.replace("D0 ten-gate protection logic bench board",
                   "Real two THN30 48V-12V split primary/secondary bias carrier - NOT FOR FAB")
    sh=sh.replace("Bench logic board. NOT for fabrication. Not a power stage, not thermal, not timing.",
                   "OEM KiCad THN30 footprint cross-checked; fuse DC breaking / 12V+ UVLO and G0 not certified")
    return ps,sy,sh

def write_symbols(sy):
    # THN module is a self-contained project-specific native library;
    # don't rely on global installed custom symbol stock.
    symbol=sy[old.LIB].replace('(symbol "'+old.LIB+'"',
                                '(symbol "THN_30_4812"',1)
    SYMLIB.write_text('(kicad_symbol_lib (version 20241209) (generator "d1_g0_traco_dual_bias_sch_package.py")\n'+symbol+'\n)\n',encoding="utf-8")
    uri="$"+"{KIPRJMOD}"+"/TracoTHN30.kicad_sym"
    LIBTABLE.write_text('(sym_lib_table\n\t(version 7)\n\t(lib (name "TracoTHN30")(type "KiCad")(uri "'+uri+'")(options "")(descr ""))\n)\n',encoding="utf-8")

def compare_source_to_board():
    native=pcb.LoadBoard(str(PCB))
    f={f.GetReference():f for f in native.GetFootprints()}
    if set(f)!=set(carrier.PARTS):raise ValueError("13 O(E)M native PCB package refs mismatch")
    for ref,design in carrier.PARTS.items():
        pads={}
        for p in f[ref].Pads():
            n=p.GetNumber();v=p.GetNetname()
            if n in pads and pads[n]!=v:raise ValueError("ambiguous native pin")
            pads[n]=v
        if pads!=design["pins"]:
            raise ValueError("independent source pin mismatch "+ref+str(pads))
    return native

def write_bom(native):
    with BOM.open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f,lineterminator="\n")
        w.writerow(["Ref","Intended_MPN","KiCad_OEM_Footprint","PinNet","Qualification"])
        footprints={i.GetReference():i for i in native.GetFootprints()}
        for ref,d in carrier.PARTS.items():
            fp=footprints[ref]
            w.writerow((ref,d["value"],FOOT[d["type"]],
             ";".join(f"{pin}={net}" for pin,net in sorted(d["pins"].items())),
             "UNQUALIFIED" if d["type"]!="module" else "OEM_PIN_FOOTPRINT_CHECKED_NOT_FAB_CERTIFIED"))

def receipt(ps):
    raw=carrier.check()
    if raw["native_KiCad_DRC_violations"] or raw["native_KiCad_unconnected"]:
        raise ValueError("physical 13 ref bias board native DRC not green")
    e=json.loads(ERC.read_text("utf-8"))
    ev=sum(len(x.get("violations",[])) for x in e.get("sheets",[]))
    c=parity.verify_exported_netlist(ps,{p.ref for p in ps if not p.ref.startswith("#")},NET.read_text("utf-8"))
    native=compare_source_to_board()
    if ev or c!=34:
        raise ValueError(f"2 module KiCad schematic ERC {ev} or independent pin-parity {c} failed")
    return {
      "kind":"D1_G0_DUAL_TRACO_30W_ISOLATED_BIAS_NATIVE_SCHEMATIC_AND_PCB",
      "status":"TWO_REAL_THN30_PHYSICAL_MODULES_NATIVE_PCB_SCH_ERC0_DRC0_OPEN0_NOT_FOR_FAB",
      "native_board_footprints":len(carrier.PARTS),
      "native_schematic_independent_pin_parity":c,
      "native_PCB_DRC_violations":raw["native_KiCad_DRC_violations"],
      "native_PCB_unconnected":raw["native_KiCad_unconnected"],
      "native_ERC_violations":ev,
      "module_input_count":2,
      "module_manufacturer":"Traco Power",
      "module_PN":"THN 30-4812",
      "module_6_PIN_pad_geometry_verified_against_installed_KiCad":True,
      "module_vendor_THN30_pdf_url":"https://www.tracopower.com/products/thn30.pdf",
      "THN30_P_plusV12_return":"PGND",
      "THN30_S_plusV12_return":"SR_SOURCE_RETURN",
      "module_input_2x_48V_fuses_present_as_natively_placed_devices":True,
      "fuses_recommended_2A_slow_but_MPN_breaking_inrush_QUALIFIED":False,
      "output_2x22uF_each_module_present_as_natively_placed_devices":True,
      "output_cap_effective_C_regulation_and_timing_qualified":False,
      "Traco_remote_NC_opencircuit_defaults_ON":True,
      "physical_48v_main_power_contact_ESTOP_present":False,
      "remote_power_fault_shutdown_and_UVLO_implemented":False,
      "G0_bias_verified_physical_30W_each_and_heat":False,
      "outer_1200V_isolation_creepage_EMC_and_input_surge_certified":False,
      "main_V5_bias_connector_mating_verified":False,
      "R8_mainboard_DNP_unaltered":True,
      "native_OEM_module_pad_map":carrier.PINS,
      "current_board_SHA256":sha(PCB),
      "source_native_CAD_report_SHA256":sha(carrier.REPORT),
      "native_data_SHA256":{p.name:sha(p) for p in FILES},
      "G0_approved":False,"fabrication_approved":False,"energization_allowed":False
    }

def instructions():
    return (
      "# D1 双路实际 OEM Traco THN30-4812 48V→两路隔离12V子板（NOT_FOR_FAB）\n\n"
      "本目录打开同名 kicad_pro，原生 2层 PCB 包含两只 KiCad官方"
      " Converter_DCDC_TRACO_THN30-xxxx_THT 6PIN 通孔封装，实测与"
      " Traco 官方2024数据手册针脚位置和功能对应。"
      "U1输出VCC12参考PGND，U2输出VCC12_S参考SR_SOURCE_RETURN；"
      "两路48V输入各自经过F1/F2预留2A慢断熔断器，"
      "含2个输入1uF 100V及每路2个22uF 25V输出电容候选，"
      "PCB原生DRC=0未连接=0，来自独立设计电路图的34 pin原生ERC=0。\n\n"
      "【重要】此处实际设计的是单独供电 *daughterboard*，不是给已存在"
      "的G0 V5主板强行塞入两块25.4x25.4模块；未来通过"
      " J_P→J_BIAS_P 和 J_S→J_BIAS_S 各2线连接，不允许交叉回流。"
      "实际系统连线/绝缘/接头极性和保持时间未签核。\n\n"
      "【电源与硬件安全】THN30 Remote引脚留NC，厂家定义"
      "开路=模块自动ON，故此电源子板不是安全关断装置；"
      "它须在主功率48V断能器前接入，以便急停时保留门极关断偏置。"
      "即使子板本身有熔断器，也没有真实48V主功率急停断能器、"
      "硬件失偏置/UVLO和高侧VGS监测。不能因为子板可实现"
      "隔离12V而允许主48V功率回路上电。\n\n"
      "F1/F2只是1812封装的2A slow临时选择，额定DC分断能力、"
      "I²t与输入上电涌流没有OEM签核；MaiXu 5mm端子真实型号、"
      "两个12V输出的接线方向与防反插尚未证实。"
      "输出22uF/25V X7R 的实际直流偏压有效电容、"
      "输入浪涌（官方建议220uF 100V方案）、EMC滤波、"
      "器件发热和机械隔离/爬电仍须验证，**禁止制造或直接上电**。\n"
    )

def write():
    carrier.check()
    ps,sy,text=authoritative()
    OUT.mkdir(parents=True,exist_ok=True)
    SCH.write_text(text,encoding="utf-8")
    PRO.write_text(k.project_file(),encoding="utf-8")
    write_symbols(sy)
    native=compare_source_to_board()
    write_bom(native)
    README.write_text(instructions(),encoding="utf-8")
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    for cmd in (
       [str(cli),"sch","export","netlist","-o",str(NET),str(SCH)],
       [str(cli),"sch","erc","--severity-all","--format","json","-o",str(ERC),str(SCH)]
    ):
        r=subprocess.run(cmd,capture_output=True,text=True,errors="replace")
        if r.returncode:raise ValueError("THN30 native schematic failed "+str(cmd)+r.stderr)
    r=receipt(ps)
    REPORT.write_text(json.dumps(r,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with zipfile.ZipFile(ZIP,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for f in (*FILES,REPORT):z.write(f,f.name)
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip() or len(z.namelist())!=len(FILES)+1:
            raise ValueError("THN30 bias carrier ZIP failed")
    return r

def check():
    ps,sy,text=authoritative()
    if SCH.read_text("utf-8")!=text:
        raise ValueError("Traco independent functional schematic drift")
    r=receipt(ps)
    if r!=json.loads(REPORT.read_text("utf-8")):
        raise ValueError("Traco carrier receipt stale")
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip() or {i.filename for i in z.infolist()}!={f.name for f in (*FILES,REPORT)}:
            raise ValueError("Traco carrier ZIP member missing/corrupted")
        for f in (*FILES,REPORT):
            if z.read(f.name)!=f.read_bytes():
                raise ValueError("Traco carrier ZIP member stale "+f.name)
    return r

def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    a=p.parse_args()
    rec=write() if a.write else check()
    print(json.dumps({k:rec[k] for k in (
      "status","native_board_footprints","native_schematic_independent_pin_parity",
      "native_PCB_DRC_violations","native_PCB_unconnected","native_ERC_violations")}))
if __name__=="__main__":main()
