"""G0 candidate: separate 48V->12V primary/secondary domains, NOT FOR FAB.

Vendor pinout is for THN 30, NOT THN 30WIR. Two 30W modules are
power-budget candidates only; input fuses, remote behavior, PCB footprint,
creepage, EMI, power loss timing and physical isolation are NOT qualified.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import make_d0_protection_board as k
import d1_lane_c_g0_gate as gate
OUT=ROOT/"hardware/dcx_main/g2/d1_lane_c_dual_bias_NOT_FOR_FAB"
NAME="g0_dual_domain_48v_12v_bias_NOT_FOR_FAB"
SCH=OUT/(NAME+".kicad_sch")
PRO=OUT/(NAME+".kicad_pro")
NET=OUT/(NAME+".net")
ERC=OUT/(NAME+"_erc.json")
BOM=OUT/"BOM.csv"
REPORT=OUT/"g0_dual_domain_bias_contract_NOT_FOR_FAB.json"
LIB="TracoTHN30:THN_30_4812"
PINS={"1":"+Vin","2":"-Vin","3":"+Vout","4":"Trim","5":"-Vout","6":"Remote"}

def parts():
    connector="TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"
    return [
      k.Part("J1","Connector_Generic:Conn_01x02","48V_INPUT",connector,30,50,
          {"1":"VIN48_RAW","2":"PGND"},note="External current-limited 48V with physical E-stop disconnect REQUIRED"),
      k.Part("F1","Device:Fuse","DC_FUSE_TBD","Fuse:Fuse_1206_3216Metric",58,43,
          {"1":"VIN48_RAW","2":"VIN48P_F"},note="DC interrupt, I2t, inrush and temperature NOT qualified"),
      k.Part("F2","Device:Fuse","DC_FUSE_TBD","Fuse:Fuse_1206_3216Metric",58,68,
          {"1":"VIN48_RAW","2":"VIN48S_F"},note="Independent secondary module input fuse candidate"),
      k.Part("U1",LIB,"THN 30-4812","",100,48,
          {"1":"VIN48P_F","2":"PGND","3":"V12P_IN","4":k.NC,"5":"PGND","6":k.NC},
          note="Primary output return intentionally bonded to PGND; footprint/remote pin pending"),
      k.Part("U2",LIB,"THN 30-4812","",205,48,
          {"1":"VIN48S_F","2":"PGND","3":"V12S_IN","4":k.NC,"5":"SR_SOURCE_RETURN","6":k.NC},
          note="Isolated secondary return MUST stay separate from PGND; not the old shared-GND D0"),
      k.Part("J2","Connector_Generic:Conn_01x02","PRIMARY_12V",connector,151,95,
          {"1":"V12P_IN","2":"PGND"},note="Connect actual primary driver return"),
      k.Part("J3","Connector_Generic:Conn_01x02","SECONDARY_12V",connector,259,95,
          {"1":"V12S_IN","2":"SR_SOURCE_RETURN"},note="Secondary source-reference return; not PGND"),
      k.Part("C1","Device:C","1uF/100V","Capacitor_SMD:C_1206_3216Metric",74,97,
          {"1":"VIN48_RAW","2":"PGND"},note="Input bypass candidate, EMC unqualified"),
      k.Part("C2","Device:C","22uF/25V","Capacitor_SMD:C_1206_3216Metric",137,117,
          {"1":"V12P_IN","2":"PGND"},note="Output capacitance provisional"),
      k.Part("C3","Device:C","22uF/25V","Capacitor_SMD:C_1206_3216Metric",245,117,
          {"1":"V12S_IN","2":"SR_SOURCE_RETURN"},note="Isolated output capacitance provisional"),
      k.Part("#FLG1","power:PWR_FLAG","PWR_FLAG","",20,148,{"1":"VIN48_RAW"}),
      k.Part("#FLG2","power:PWR_FLAG","PWR_FLAG","",35,148,{"1":"PGND"}),
      k.Part("#FLG3","power:PWR_FLAG","PWR_FLAG","",50,148,{"1":"V12P_IN"}),
      k.Part("#FLG4","power:PWR_FLAG","PWR_FLAG","",65,148,{"1":"V12S_IN"}),
      k.Part("#FLG5","power:PWR_FLAG","PWR_FLAG","",80,148,{"1":"SR_SOURCE_RETURN"}),
    ]

def symbols(ps):
    base=k.build_symbols()
    selected={ref:base[ref] for ref in {p.lib for p in ps if p.lib!=LIB}}
    selected[LIB]=k.custom_symbol(LIB, [
      k.Pin("1","+VIN",-15.24,5.08,0),
      k.Pin("2","-VIN",-15.24,2.54,0),
      k.Pin("6","REMOTE",-15.24,-5.08,0),
      k.Pin("3","+VOUT",15.24,5.08,180),
      k.Pin("4","TRIM",15.24,0,180),
      k.Pin("5","-VOUT",15.24,-5.08,180),
    ],25.4,20.32,"U","")
    return selected

def expected():
    ps=[k.snap(p) for p in parts()]
    sy=symbols(ps)
    k.validate(ps,sy)
    text=k.schematic(sy,ps)
    text=text.replace("D0 ten-gate protection logic bench board",
      "G0 Dual 48V-12V isolated bias candidate - NOT FOR FAB")
    text=text.replace("Bench logic board. NOT for fabrication. Not a power stage, not thermal, not timing.",
      "Concept only. No qualified module footprint, safety power disconnect or validated isolation")
    return ps,sy,text

def verify(ps):
    by={p.ref:p for p in ps if not p.ref.startswith("#")}
    if any(set(by[ref].nets)!=set(PINS) for ref in ("U1","U2")):
        raise ValueError("THN 30 vendor pinout mismatch")
    if any(by[ref].value!="THN 30-4812" or by[ref].footprint for ref in ("U1","U2")):
        raise ValueError("module MPN/footprint release stopline broken")
    for ref in ("U1","U2"):
        if by[ref].nets["2"]!="PGND" or by[ref].nets["4"]!=k.NC or by[ref].nets["6"]!=k.NC:
            raise ValueError("module input ground/trim/remote changed")
    if by["U1"].nets["3"]!="V12P_IN" or by["U2"].nets["3"]!="V12S_IN":
        raise ValueError("primary and secondary supply outputs cross-connected")
    if by["U1"].nets["5"]!="PGND" or by["U2"].nets["5"]!="SR_SOURCE_RETURN":
        raise ValueError("two 12V domains have been shorted")
    if by["U2"].nets["5"]==by["U2"].nets["2"]:
        raise ValueError("secondary output shorted to 48V input ground")
    if by["J2"].nets!={"1":"V12P_IN","2":"PGND"} or \
       by["J3"].nets!={"1":"V12S_IN","2":"SR_SOURCE_RETURN"}:
        raise ValueError("output connector wrong reference")
    if by["C3"].nets!={"1":"V12S_IN","2":"SR_SOURCE_RETURN"}:
        raise ValueError("secondary capacitor shorted to primary ground")
    for ref,rail in (("U1","VIN48P_F"),("U2","VIN48S_F")):
        if by[ref].nets["1"]!=rail:
            raise ValueError("DC input fuse bypass")
    if by["F1"].nets!={"1":"VIN48_RAW","2":"VIN48P_F"} or \
       by["F2"].nets!={"1":"VIN48_RAW","2":"VIN48S_F"}:
        raise ValueError("independent input fuses missing")

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def report(ps,erc,pins):
    verify(ps)
    return {
      "kind":"D1_G0_TWO_DOMAIN_BIAS_KICAD_CONCEPT",
      "status":"ISOLATED_12V_DOMAINS_SKETCHED_NOT_FOR_FAB",
      "module":"Traco Power THN 30-4812 (not THN 30WIR)",
      "datasheet":"https://www.tracopower.com/overview/thn30",
      "vendor_pin_map":PINS,
      "input_range_v":[36,75],"nominal_12v_output_each_a":2.5,
      "nominal_12v_power_each_w":30,"module_count":2,
      "primary_output_return":"PGND","secondary_output_return":"SR_SOURCE_RETURN",
      "secondary_supply_ground_separate_in_native_netlist":True,
      "native_pin_parity":pins,
      "native_erc_violations":sum(len(x.get("violations",[])) for x in erc.get("sheets",[])),
      "native_erc_ignored":[x.get("key") for x in erc.get("ignored_checks",[])],
      "sch_sha256":sha(SCH),"net_sha256":sha(NET),"bom_sha256":sha(BOM),
      "module_footprint_qualified":False,"remote_pin_qualified":False,
      "power_vs_actual_gate_charge_and_frequency_qualified":False,
      "input_fuse_inrush_and_dc_interrupt_qualified":False,
      "isolation_creepage_and_clearance_qualified":False,
      "common_mode_emc_and_thermal_qualified":False,
      "48v_power_disconnect_integrated":False,
      "physical_bias_fault_test_completed":False,
      "g0_approved":False,"energization_allowed":False,"fabrication_approved":False,
    }

def write(ps,sy,text):
    OUT.mkdir(parents=True,exist_ok=True)
    SCH.write_text(text,encoding="utf-8")
    PRO.write_text(k.project_file().replace("d0_protection.kicad_pro",PRO.name),encoding="utf-8")
    embedded=sy[LIB].replace('(symbol "'+LIB+'"','(symbol "THN_30_4812"',1)
    (OUT/"TracoTHN30.kicad_sym").write_text(
      '(kicad_symbol_lib (version 20241209) (generator "d1_lane_c_bias_supply_candidate.py")\n'+embedded+'\n)\n',encoding="utf-8")
    uri="$"+"{KIPRJMOD}"+"/TracoTHN30.kicad_sym"
    (OUT/"sym-lib-table").write_text(
      '(sym_lib_table\n\t(version 7)\n\t(lib (name "TracoTHN30")(type "KiCad")(uri "'+uri+'")(options "")(descr ""))\n)\n',
      encoding="utf-8")
    old=k.OUT
    try:
        k.OUT=OUT;k.bom(ps)
    finally:k.OUT=old
    cli=k.kicad_cli()
    if not cli:raise ValueError("KiCad CLI not found")
    subprocess.run([str(cli),"sch","export","netlist","-o",str(NET),str(SCH)],check=True)
    subprocess.run([str(cli),"sch","erc","--severity-all","--format","json",
                    "-o",str(ERC),str(SCH)],check=True)
    e=json.loads(ERC.read_text("utf-8"))
    if any(x.get("violations") for x in e.get("sheets",[])):
        raise ValueError("native isolated bias ERC violations")
    pins=gate.verify_exported_netlist(ps,{p.ref for p in ps if not p.ref.startswith("#")},
                                      NET.read_text("utf-8"))
    REPORT.write_text(json.dumps(report(ps,e,pins),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def check(ps,text):
    verify(ps)
    if not all(f.is_file() for f in (SCH,PRO,NET,ERC,BOM,REPORT)):
        raise ValueError("missing native bias project files")
    if SCH.read_text("utf-8")!=text:raise ValueError("native bias schematic stale")
    e=json.loads(ERC.read_text("utf-8"))
    if any(x.get("violations") for x in e.get("sheets",[])):
        raise ValueError("bias KiCad ERC violation")
    pins=gate.verify_exported_netlist(ps,{p.ref for p in ps if not p.ref.startswith("#")},
                                      NET.read_text("utf-8"))
    result=report(ps,e,pins)
    if result!=json.loads(REPORT.read_text("utf-8")):
        raise ValueError("bias contract stale")
    with BOM.open(encoding="utf-8",newline="") as f:
        by={x["Reference"]:x for x in csv.DictReader(f)}
    if any(by[x]["Footprint"] or by[x]["Value"]!="THN 30-4812" for x in ("U1","U2")):
        raise ValueError("false production footprint assignment")
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    x=ap.add_mutually_exclusive_group(required=True)
    x.add_argument("--write",action="store_true")
    x.add_argument("--check",action="store_true")
    cmd=ap.parse_args()
    ps,sy,sch=expected()
    if cmd.write:write(ps,sy,sch)
    data=check(ps,sch)
    print(data["status"],"netlist_pins",data["native_pin_parity"],
          "erc",data["native_erc_violations"])
if __name__=="__main__":main()
