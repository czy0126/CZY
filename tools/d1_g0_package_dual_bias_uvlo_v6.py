"""Package a source-authored KiCad schematic for the THN30+TPS3710 opto UVLO V6 PCB.

The 13 existing THN30 carrier devices are preserved unchanged, while 17
new physical TPS3710 voltage-supervisor, divider, optical-barrier, inverter
and status interface devices are emitted from the V6 explicit pin/net
contract. Pin map crosschecks native PCB; independent kicad-cli ERC/netlist
checks use source pin ids, not the PCB's exported netlist.

UVLO status output is deliberately NOT a safety-rated relay drive or power
stage permit: actual E-stop/HS watchdog must be integrated separately.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,shutil,subprocess,sys,zipfile
from pathlib import Path
import pcbnew as pcb
import d1_g0_dual_bias_uvlo_v6 as physical
import d1_g0_traco_dual_bias_sch_package as oldsch
import make_d0_protection_board as k
import d1_lane_c_g0_gate as parity

OUT=physical.OUT
STEM=physical.STEM
PCB=physical.BOARD
SCH=OUT/(STEM+".kicad_sch")
PRO=OUT/(STEM+".kicad_pro")
NET=OUT/(STEM+".net")
ERC=OUT/(STEM+"_native_erc.json")
DRC=physical.DRC
RPT=OUT/"V6_30part_native_UVLO_iso_schematic_receipt_NOT_FOR_FAB.json"
SYMLIB=OUT/"G0UVLOSource.kicad_sym"
TABLE=OUT/"sym-lib-table"
THN=OUT/"TracoTHN30.kicad_sym"
BOM=OUT/"G0_V6_UVLO_isolated_12v_30part_BOM.csv"
ZIP=OUT/"G0_V6_TWO_THN30_UVLO_OPTO_KICAD_NOT_FOR_FAB.zip"
README=OUT/"OPEN_FIRST_NOT_FOR_FAB.md"
FILES=(PCB,SCH,PRO,NET,ERC,DRC,RPT,physical.REPORT,SYMLIB,TABLE,THN,BOM,README)
LIB="G0UVLOSource"
NAMES={
"super":{"1":"OUT","2":"GND","3":"SENSE","4":"GND","5":"VDD","6":"GND"},
"opto":{"1":"ANODE","2":"CATHODE","3":"EMITTER","4":"COLLECTOR"},
"npn":{"1":"BASE","2":"EMITTER","3":"COLLECTOR"},
"res":{"1":"A","2":"B"},"cap":{"1":"A","2":"B"},
"header":{"1":"P_UV_OK","2":"S_UV_OK","3":"PRIMARY_GND"}
}
FOOTPRINTS={typ:f"{a}:{b}" for typ,(a,b) in physical.FOOT.items()}
DATASHEET={
"UP":physical.TI,"US":physical.TI,
"ISO1":physical.VISHAY,"QINV":physical.ON,
}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def source():
    p,sy,sch=oldsch.authoritative()
    for i,(ref,raw) in enumerate(physical.PARTS.items()):
        typ,origin,val,net=raw
        lib=f"{LIB}:{ref}"
        pinnames=NAMES[typ]
        if set(pinnames)!=set(net):raise ValueError("V6 candidate part pinmap missing "+ref)
        half=(len(net)+1)//2
        native_pins=[]
        for j,n in enumerate(sorted(net)):
            left=j<half
            offset=j if left else j-half
            native_pins.append(k.Pin(n,pinnames[n],-13.97 if left else 13.97,
                   7.62-offset*2.54,0 if left else 180,"passive"))
        sy[lib]=k.custom_symbol(lib,native_pins,22.86,25.4,
                  "U" if typ in ("super","opto") else
                  "Q" if typ=="npn" else "J" if typ=="header" else
                  "C" if typ=="cap" else "R","")
        p.append(k.snap(k.Part(
             ref,lib,val,FOOTPRINTS[typ],
             28+46*(i%6),230+27*(i//6),net,
             source="Independent vendor TPS3710+VO617A+MMBT3904 12V-UVLO circuit contract",
             note="Not a physical power-stage interlock; thresholds/CTR/creepage unverified")))
    k.validate(p,sy)
    sh=k.schematic(sy,p)
    sh=sh.replace("D0 ten-gate protection logic bench board",
                 "G0 V6 real THN30 12V dual-domain TPS3710 UVLO opto, NOT FOR FAB")
    sh=sh.replace("Bench logic board. NOT for fabrication. Not a power stage, not thermal, not timing.",
                 "SOT6 DDC original pins from TI; opto / threshold schematic but NOT an E-stop/power-stage permit")
    return p,sy,sh

def native_ppar(ps):
    want={p.ref:{pin:("" if net==k.NC else net) for pin,net in p.nets.items()}
        for p in ps if not p.ref.startswith("#")}
    board=pcb.LoadBoard(str(PCB))
    got={}
    for fp in board.GetFootprints():
        pins={}
        for pd in fp.Pads():
            name=pd.GetNumber();net=pd.GetNetname()
            if name in pins and pins[name]!=net:
                raise ValueError("native duplicate pin with different nets")
            pins[name]=net
        got[fp.GetReference()]=pins
    if got!=want:
        raise ValueError("source designed TPS3710 / 13 old power supply pins differ from native PCB: "+str({
            x:{"want":want.get(x),"got":got.get(x)} for x in set(want)|set(got) if want.get(x)!=got.get(x)}))
    return want

def write_library(sy):
    blocks=['(kicad_symbol_lib (version 20241209) (generator "g0_v6_uvlo_vendor_pinmap")']
    blocks.extend(s.replace(f'(symbol "{LIB}:','(symbol "',1)
                  for name,s in sy.items() if name.startswith(LIB+":"))
    blocks.append(")")
    SYMLIB.write_text("\n".join(blocks)+"\n",encoding="utf-8")
    shutil.copyfile(oldsch.SYMLIB,THN)
    source="$"+"{KIPRJMOD}"
    TABLE.write_text('(sym_lib_table\n\t(version 7)\n'+
      '\t(lib (name "TracoTHN30")(type "KiCad")(uri "'+source+'/TracoTHN30.kicad_sym")(options "")(descr ""))\n'+
      '\t(lib (name "'+LIB+'")(type "KiCad")(uri "'+source+'/G0UVLOSource.kicad_sym")(options "")(descr ""))\n)\n',
      encoding="utf-8")

def bom(pp):
    with BOM.open("w",newline="",encoding="utf-8") as f:
        csvw=csv.writer(f,lineterminator="\n")
        csvw.writerow(("Reference","Native_KiCad_Footprint","Design_MPN","PinNet","Source","OEM_qualified"))
        for ref,net in sorted(pp.items()):
            if ref in physical.PARTS:
                typ,xy,value,loc=physical.PARTS[ref]
                footprint=FOOTPRINTS[typ]
                vendor="TI" if typ=="super" else "Vishay" if typ=="opto" else "onsemi" if typ=="npn" else "TBD"
            else:
                d=oldsch.carrier.PARTS[ref]
                typ=d["type"];value=d["value"]
                footprint=oldsch.FOOT[typ]
                vendor="Traco Power" if typ=="module" else "TBD"
            csvw.writerow((ref,footprint,value,
               ";".join(f"{n}={v}" for n,v in sorted(net.items())),
               vendor,"NO"))

def readme():
    return (
     "# 双路12V隔离偏置 V6 UVLO/光耦健康信号子板 (NOT_FOR_FAB)\n\n"
     "从 V5 双 THN 30-4812 偏置电源2层原生板扩展至115x115mm，"
     "放置两只TPS3710DDCR，分别测量 VCC12/PGND 和"
     " VCC12_S/SR_SOURCE_RETURN，两个261k/10k分压在"
     " Ti 400mV上升阈值对应10.84V、下降394.5mV对应10.69V，"
     "需要以器件准确度、R温漂和真实噪声进行最坏值复核。"
     "每颗有100nF旁路、OUT开漏上拉；副边OUT通过VO617A-3"
     " LED及光晶体管回到原边，原边再经MMBT3904LT1G"
     " 反相输出UVLO_S_PRIMARY_OK，与本地UVLO_P_OK"
     " 一起提供在J_HEALTH的3针端口上（pin1 P_OK、pin2 S_OK、pin3 PGND）。\n\n"
     "该板仅检测两个12V的电压，**没有连到主功率48V急停"
     "接触器、真正的UCC栅驱使能RUN或高侧HS监视**，"
     "所以不得误认作已实现安全许可。VO617A-3的光耦CTR依赖"
     "输入电流、温度/老化，当前约4mA并未签核充足裕量；"
     " 光耦只有器件额定耐压，不等于本PCB已通过爬电/灌封/耐压认证。"
     " 同时VDD低于POR时TPS3710输出不定；必须由物理"
     " 外部默认OFF联锁防止低压假高。\n\n"
     " PCB KiCad10 原生DRC0/unconnected0；由独立"
     " pin/net合同生成的可编辑原生 SCH与PCB 80 pins"
     "对齐并执行ERC。输出BOM和 SHA/ZIP完整，不允许上电或送厂。"
    )

def report(pp,ps):
    q=json.loads(physical.REPORT.read_text("utf-8"))
    dr=json.loads(DRC.read_text("utf-8"))
    er=json.loads(ERC.read_text("utf-8"))
    n=parity.verify_exported_netlist(ps,{p.ref for p in ps if not p.ref.startswith("#")},NET.read_text("utf-8"))
    ev=sum(len(sh.get("violations",[])) for sh in er.get("sheets",[]))
    if len(pp)!=30 or n!=80 or ev or dr.get("violations") or dr.get("unconnected_items"):
        raise ValueError(f"native G0 V6 ERC={ev} pins={n} drc={len(dr['violations'])} open={len(dr['unconnected_items'])}")
    return {
      "kind":"G0_BIAS_V6_DUAL_TPS3710_UVLO_OPTO_PIN_SOURCED_NATIVE_KICAD",
      "status":"TWO_THN30_2x_TPS3710_OPTO_UVLO_KICAD_ERC0_DRC0_OPEN0_NOT_FOR_FAB",
      "device_count":len(pp),"unique_ref_pin_net_parity":n,
      "native_KiCad_ERC_violations":ev,
      "native_KiCad_DRC_violations":len(dr.get("violations",[])),
      "native_KiCad_unconnected":len(dr.get("unconnected_items",[])),
      "12v_uvlo_primary_plus_secondary_hardware_layout_present":True,
      "secondary_to_primary_status_opto_isolated":True,
      "primary_status_pin1":"UVLO_P_OK",
      "primary_status_pin2":"UVLO_S_PRIMARY_OK",
      "primary_status_pin3":"PGND",
      "12v_rising_threshold_typical":physical.TRIP_UP_V,
      "12v_falling_threshold_typical":physical.TRIP_DOWN_V,
      "vendor_tps3710_pinmap_verified":True,
      "vendor_opto_4pin_map_verified":True,
      "vendor_npn_3pin_map_verified":True,
      "status_3pin_is_a_power_stage_enable":False,
      "contactor_DC_breaking_wiring_and_feedback_qualified":False,
      "UVLO_status_to_physical_ESTOP_and_RUN_closed_loop":False,
      "opto_ctr_and_uvlo_dynamic_times_proven":False,
      "C_hold_up_minimum_and_surge_tested":False,
      "creepage_clearance_isolation_certified":False,
      "hardware_first_power_test_completed":False,
      "old_13part_bias_carrier_source_sha":sha(oldsch.PCB),
      "source_v6_pcb_sha256":sha(PCB),
      "sha256":{file.name:sha(file) for file in FILES if file!=RPT},
      "energization_allowed":False,"g0_approved":False,"fabrication_approved":False
    }

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    a=physical.check()
    if a["native_drc_rules"] or a["native_unconnected"]:
        raise ValueError("actual V6 PCB still has DRC/open")
    parts,sy,sch=source()
    native=native_ppar(parts)
    SCH.write_text(sch,encoding="utf-8")
    shutil.copyfile(oldsch.PRO,PRO)
    write_library(sy)
    bom(native)
    README.write_text(readme(),encoding="utf-8")
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    for c in (
        [str(cli),"sch","export","netlist","-o",str(NET),str(SCH)],
        [str(cli),"sch","erc","--severity-all","--format","json","-o",str(ERC),str(SCH)],
    ):
        r=subprocess.run(c,capture_output=True,text=True,errors="replace")
        if r.returncode:raise ValueError("V6 native SCH CLI failure "+r.stderr)
    data=report(native,parts)
    RPT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with zipfile.ZipFile(ZIP,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for f in FILES:z.write(f,f.name)
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip() or len(z.namelist())!=len(FILES):
            raise ValueError("UVLO V6 native ZIP invalid")
    return data

def check():
    a=physical.check()
    ps,sy,sch=source()
    if SCH.read_text("utf-8")!=sch:raise ValueError("V6 source schematic changed")
    pp=native_ppar(ps)
    data=report(pp,ps)
    if data!=json.loads(RPT.read_text("utf-8")):
        raise ValueError("UVLO V6 independent CAD receipt drift")
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip() or {i.filename for i in z.infolist()}!={f.name for f in FILES}:
            raise ValueError("UVLO V6 ZIP stale")
        for f in FILES:
            if z.read(f.name)!=f.read_bytes():raise ValueError("UVLO V6 ZIP member changed "+f.name)
    return data

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true");g.add_argument("--check",action="store_true")
    a=parser.parse_args()
    d=build() if a.write else check()
    print(json.dumps({x:d[x] for x in ("status","device_count","unique_ref_pin_net_parity",
        "native_KiCad_ERC_violations","native_KiCad_DRC_violations","native_KiCad_unconnected")}))
if __name__=="__main__":main()
