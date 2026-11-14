"""Lane C independently generated KiCad HS-referenced D0 *interface candidate*.

This is a non-energizable engineering model, not the full D0 protection board
for the real 48V LLC: the SR algorithm remains a non-equivalent TTL replacement,
the high-side VGS detector is DNP, and external 12V rails/relay are not closed.
The generator changes no common D0 source artifact or A/B lane file.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import make_d0_protection_board as d0
import d1_lane_c_g0_gate as audit

DEST=ROOT/"hardware/dcx_main/g2/d1_lane_c_hs_reference_NOT_FOR_FAB"
STEM="d0_lane_c_hs_reference_NOT_FOR_FAB"
SCH=DEST/(STEM+".kicad_sch")
PRO=DEST/(STEM+".kicad_pro")
NET=DEST/(STEM+".net")
ERC=DEST/(STEM+"_erc.json")
BOM=DEST/"BOM.csv"
REPORT=DEST/"hs_interface_contract_NOT_FOR_FAB.json"

# This table is a *delta* on the separately locked reference D0; never mask a
# future source drift. The physical UCC27282 DRC pin 5 is HS, not ground.
REWIRE={
    ("U18","5"):("PGND","SW"),
    ("C29","2"):("PGND","SW"),
    ("R64","2"):("PGND","SW"),
    ("C40","2"):("PGND","SW"),
    ("R20","1"):("V12P","V12P_F"),
    ("R22","1"):("V12S","V12S_F"),
    # U8 internal request must not drive the permit transistor directly.
    ("U8","10"):("PERMIT","PERMIT_INTERNAL"),
}
# Ground-referenced detector is invalid for a 48V floating high-side gate.
# Keep the pads in the engineering schematic, but never populate that path.
DO_NOT_POPULATE={"R74","D17"}
REFERENCE_SHA=audit.BASELINE_SHA

def sha(raw:bytes)->str:
    return hashlib.sha256(raw).hexdigest()

def candidate_parts(base=None):
    parts=list(d0.parts() if base is None else base)
    seen=set()
    result=[]
    for part in parts:
        net=dict(part.nets)
        for (ref,pin),(prior,after) in REWIRE.items():
            if ref!=part.ref or pin not in net:
                continue
            if net.get(pin)!=prior:
                raise ValueError(f"source pin shifted {ref}.{pin}: {net.get(pin)}")
            net[pin]=after
            seen.add((ref,pin))
        if part.ref in DO_NOT_POPULATE:
            if part.dnp:
                raise ValueError(f"source DNP state shifted {part.ref}")
            result.append(replace(part,nets=net,dnp=True,
                note="DNP: floating HS VGS cannot be sensed relative to PGND"))
        elif part.ref=="C29":
            if part.value!="100nF/25V":
                raise ValueError("source bootstrap value unexpectedly changed")
            result.append(replace(part,nets=net,value="220nF/25V",
                note="Cboot between HB and HS(SW), conceptual 220n candidate; MLCC bias/ESR unqualified"))
        elif part.ref in ("R21","R23"):
            if part.value!="14.7k":
                raise ValueError(f"{part.ref} source UVLO bottom resistor drifted")
            result.append(replace(part,nets=net,value="10k",
                note="UVLO source input: 11.1V rising, 10.6V falling with 1M feedback nominal"))
        elif part.ref in ("C14","C15"):
            if part.value!="100nF/16V":
                raise ValueError(f"{part.ref} source UVLO filtering drifted")
            result.append(replace(part,nets=net,value="1nF/50V",
                note="UVLO raw-rail RC filter, nominal ~9.1us before hysteresis; real timing pending"))
        else:
            result.append(replace(part,nets=net))
    if seen!=set(REWIRE):
        raise ValueError("missing required HS rewiring")
    # Separate 12V post-ORing hold-up from pre-diode rail-loss sensing.
    # These are prototype values, NOT component or hold-up qualifications.
    for i,(net,sense,ok) in enumerate((
            ("V12P","V12P_SNS","V12P_OK"),
            ("V12S","V12S_SNS","V12S_OK"))):
        result.append(d0.Part(f"C{114+i}","Device:C","22uF/25V",
            "Capacitor_SMD:C_1210_3225Metric",512,230+16*i,
            {"1":net,"2":"PGND"},rating="25V nominal, DC derating not qualified",
            note="Post-diode hold-up capacitor for driver shutdown, transient validation pending"))
        result.append(d0.Part(f"R{110+i}","Device:R","1M",
            "Resistor_SMD:R_0603_1608Metric",510,310+14*i,
            {"1":ok,"2":sense},
            note="Comparator positive feedback for 11.1/10.6V nominal UVLO"))
    # U20 AND interlock is in the hardware enable path, after the latch/
    # operator/fault logic. The external loops are normally open by default:
    # an absent cable, broken NC emergency-stop chain or missing HS monitor
    # means no PERMIT, independent of any software/MCU command.
    # This is only a bench inhibit: a certified independent input-energy
    # disconnect, a real HS monitor and safe gate turn-off remain required.
    logic="Package_DIP:DIP-14_W7.62mm"
    result += [
        d0.Part("J11","Connector_Generic:Conn_01x02","EXT_ESTOP_NC_LOOP",
            "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
            515,180,{"1":"V5","2":"ESTOP_OK"},
            note="External series NC emergency stop contacts; open line forces OFF; not the required power disconnect"),
        d0.Part("J12","Connector_Generic:Conn_01x02","EXT_HS_DIAG_CONTACT",
            "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
            535,180,{"1":"V5","2":"HS_MON_OK"},
            note="Qualified externally isolated high-side monitor contact; absent sensor forces OFF"),
        d0.Part("R112","Device:R","10k",
            "Resistor_SMD:R_0603_1608Metric",515,202,
            {"1":"ESTOP_OK","2":"PGND"},
            note="External E-stop contact/open wire default-off pulldown"),
        d0.Part("R113","Device:R","10k",
            "Resistor_SMD:R_0603_1608Metric",535,202,
            {"1":"HS_MON_OK","2":"PGND"},
            note="Missing floating gate monitor defaults permit low"),
        d0.Part("R114","Device:R","10k",
            "Resistor_SMD:R_0603_1608Metric",555,202,
            {"1":"PERMIT","2":"PGND"},note="Final output inhibit default low"),
        d0.Part("U20","4xxx:4081","CD4081BE",logic,530,250,
            {"1":"PERMIT_INTERNAL","2":"ESTOP_OK","3":"PERMIT_ESTOP"},unit=1),
        d0.Part("U20","4xxx:4081","CD4081BE",logic,530,250,
            {"4":"PERMIT","5":"PERMIT_ESTOP","6":"HS_MON_OK"},unit=2),
        d0.Part("U20","4xxx:4081","CD4081BE",logic,530,250,
            {"8":"PGND","9":"PGND","10":d0.NC},unit=3),
        d0.Part("U20","4xxx:4081","CD4081BE",logic,530,250,
            {"11":d0.NC,"12":"PGND","13":"PGND"},unit=4),
        d0.Part("U20","4xxx:4081","CD4081BE",logic,530,250,
            {"7":"PGND","14":"V5"},unit=5),
    ]
    tp="TestPoint:TestPoint_Pad_D1.0mm"
    for i,net in enumerate(("SW","GH1","HB","ESTOP_OK","HS_MON_OK")):
        result.append(d0.Part(f"TP{20+i}","Connector:TestPoint",
            f"DIFF_PROBE_{net}",tp,540,345+i*12,{"1":net},
            note="Measure high-side VGS: GH1-SW; bootstrap voltage HB-SW"))
    return result

def expected_text():
    if audit.sha(audit.BASELINE)!=REFERENCE_SHA:
        raise ValueError("shared V17 baseline SHA changed")
    parts=[d0.snap(p) for p in candidate_parts()]
    symbols=d0.build_symbols()
    d0.validate(parts,symbols)
    text=d0.schematic(symbols,parts)
    text=text.replace('D0 ten-gate protection logic bench board',
                      'Lane C HS-referenced D0 interface NOT FOR FAB')
    text=text.replace('Generated by tools/make_d0_protection_board.py; the part table is the source of truth.',
                      'HS delta generated by tools/d1_lane_c_hs_candidate.py; input D0 is read-only.')
    text=text.replace('Bench logic board. NOT for fabrication. Not a power stage, not thermal, not timing.',
                      'HS SW corrected; floating GH1 gate-sense DNP. Not a complete protection circuit.')
    return parts,symbols,text

def verify_candidate(part_instances):
    parts={p.ref:p for p in part_instances}
    if parts["U18"].nets["5"]!="SW":
        raise ValueError("floating HS is not SW")
    for ref in ("C29","R64","C40"):
        if parts[ref].nets["2"]!="SW":
            raise ValueError(ref+" gate reference is not SW")
    if not all(parts[r].dnp for r in DO_NOT_POPULATE):
        raise ValueError("floating gate absolute-V sensing wrongly fitted")
    if any(parts[r].nets["1"]!="GH1" for r in ("R64","C40","R74")):
        raise ValueError("high-side gate source mismatch")
    if parts["U18"].nets["9"]!="PGND" or parts["U18"].nets["11"]!="PGND":
        raise ValueError("U18 VSS/thermal pad ground missing")
    if parts["C29"].nets["1"]!="HB":
        raise ValueError("HB bootstrap high terminal missing")
    if parts["R45"].dnp is not True:
        raise ValueError("unsafe unconditional permit installed")
    # Do not permit bypassing this last, physical enable stage with a jumper
    # or a software flag. This is an *interface* contract, NOT validation of
    # the external contacts, an isolated HS monitor, or the 48V disconnect.
    u8_permit=[p.nets["10"] for p in part_instances if p.ref=="U8" and "10" in p.nets]
    if u8_permit!=["PERMIT_INTERNAL"]:
        raise ValueError("internal permit bypasses external safety gate")
    u20={p.unit:p.nets for p in part_instances if p.ref=="U20"}
    expected={
        1:{"1":"PERMIT_INTERNAL","2":"ESTOP_OK","3":"PERMIT_ESTOP"},
        2:{"4":"PERMIT","5":"PERMIT_ESTOP","6":"HS_MON_OK"},
        3:{"8":"PGND","9":"PGND","10":d0.NC},
        4:{"11":d0.NC,"12":"PGND","13":"PGND"},
        5:{"7":"PGND","14":"V5"},
    }
    if u20!=expected:
        raise ValueError("final two-condition permit gate disconnected")
    for ref,signal in (("J11","ESTOP_OK"),("J12","HS_MON_OK")):
        if parts[ref].nets!={"1":"V5","2":signal} or parts[ref].dnp:
            raise ValueError("external permit loop missing: "+ref)
    for ref,signal in (("R112","ESTOP_OK"),("R113","HS_MON_OK"),("R114","PERMIT")):
        if parts[ref].nets!={"1":signal,"2":"PGND"} or parts[ref].value!="10k" or parts[ref].dnp:
            raise ValueError("external permit default low missing: "+ref)
    for i,net in enumerate(("ESTOP_OK","HS_MON_OK"),start=23):
        if parts[f"TP{i}"].nets!={"1":net}:
            raise ValueError("missing safety test point: TP"+str(i))
    if parts["R33"].nets["1"]!="PERMIT":
        raise ValueError("final enable gate bypassed on Q1 base")
    for i,up in enumerate(("P","S")):
        top=parts[f"R{20+2*i}"]
        bottom=parts[f"R{21+2*i}"]
        rc=parts[f"C{14+i}"]
        feedback=parts[f"R{110+i}"]
        hold=parts[f"C{114+i}"]
        if top.nets["1"]!=f"V12{up}_F" or top.nets["2"]!=f"V12{up}_SNS":
            raise ValueError("raw rail must be UVLO monitored ahead of hold-up diode")
        if bottom.nets!={"1":f"V12{up}_SNS","2":"PGND"} or bottom.value!="10k":
            raise ValueError("UVLO threshold drift")
        if rc.nets!={"1":f"V12{up}_SNS","2":"PGND"} or rc.value!="1nF/50V":
            raise ValueError("UVLO filter not isolated")
        if feedback.nets!={"1":f"V12{up}_OK","2":f"V12{up}_SNS"} or feedback.value!="1M":
            raise ValueError("hysteresis feedback misconnected")
        if hold.nets!={"1":f"V12{up}","2":"PGND"} or hold.value!="22uF/25V":
            raise ValueError("driver shutdown hold-up capacitor missing")

def build_report(parts, erc_json=None, native_pins=0):
    verify_candidate(parts)
    # Multiple KiCad units share a reference: compare every (ref,pin), not
    # a last-unit-only dictionary that silently drops U8.10.
    orig={(p.ref,pin):net for p in d0.parts() for pin,net in p.nets.items()}
    new={(p.ref,pin):net for p in parts for pin,net in p.nets.items()}
    changed=[]
    for (ref,pin),(old,net) in REWIRE.items():
        assert orig[(ref,pin)]==old and new[(ref,pin)]==net
        changed.append({"ref":ref,"pin":pin,"from":old,"to":net})
    if erc_json is None:
        erc_json={}
    sheets=erc_json.get("sheets",[])
    bad=sum(len(s.get("violations",[])) for s in sheets)
    return {
        "kind":"D1_LANE_C_HS_KICAD_ELECTRICAL_CANDIDATE",
        "status":"HS_NET_REFERENCE_REPAIRED_BUT_PROTECTION_INCOMPLETE_NOT_FOR_FAB",
        "base_commit":"27b101c1e7e4135f0fd6e2f016ca5a4ae32dc018",
        "input_pcb_sha256":REFERENCE_SHA,
        "input_d0_schematic_sha256":audit.sha(audit.D0_SCH),
        "changed_nets":changed,
        "dnp":sorted(DO_NOT_POPULATE|{"R45"}),
        "uvlo_nominal":{"raw_sense_before_or_diodes":True,
                        "divider_top_ohm":100000,"divider_bottom_ohm":10000,
                        "hysteresis_feedback_ohm":1000000,
                        "comparator_reference_v":1.0,
                        "comparator_pullup_v":5.0,
                        "rising_threshold_v":11.1,"falling_threshold_v":10.6,
                        "filter_nominal_tau_us":9.00900900900901,
                        "post_diode_hold_up_each_f":22e-6,
                        "hold_up_dc_bias_and_esr_verified":False,
                        "actual_max_fault_shutdown_delay_proven":False},
        "gate_diff_probe_pairs":{"high_side_VGS":["GH1","SW"],"boot":["HB","SW"],
                                "low_side_VGS":["GL1","PGND"]},
        "final_hardware_permit_interlock":{
            "logic":"PERMIT=PERMIT_INTERNAL & ESTOP_OK & HS_MON_OK",
            "input_default_off_resistors":{"ESTOP_OK":"R112 10k to PGND",
                "HS_MON_OK":"R113 10k to PGND","PERMIT":"R114 10k to PGND"},
            "external_interfaces":{"J11":"V5-ESTOP_OK series NC emergency-stop contact",
                "J12":"V5-HS_MON_OK qualified floating-gate monitor contact"},
            "interlock_stage":"U20 CD4081BE AND logic, independent of MCU",
            "open_wire_must_disable":True,
            "external_estop_contact_physically_tested":False,
            "external_hs_monitor_physically_tested":False,
            "power_stage_hardware_disconnect_verified":False,
            "off_time_and_cmos_power_down_proven":False,
            "warning":"This interface is not an external safety relay, not a verified floating VGS monitor, and not proof of power disconnection"
        },
        "ucc27282_drc_pin_map":{"1":"V12P","3":"HB","4":"HO","5":"SW","6":"PERMIT_RAIL",
                                 "7":"TG_HI","8":"TG_LO","9":"PGND","10":"LO","11":"PGND"},
        "not_proven":["External NC E-stop contact and 48V physical disconnect action (not fitted or measured)",
                      "External isolated floating HS monitor validity and fault detection (not fitted or measured)",
                      "Real primary high-side VGS threshold via source-referenced comparator",
                      "Actual switching source SW injection, boot diode qualification and 220n MLCC tolerance",
                      "External V12P/V12S isolated sources, hardware UVLO and fast E-stop disconnect",
                      "Eight real UCC24624 SR gate dynamics vs candidate TTL substitute",
                      "Thermal SOA, ESD/surge, 100A PCB and independent physical fault capture"],
        "native_erc_violations":bad if erc_json else None,
        "native_erc_ignored_checks":[k.get("key") for k in erc_json.get("ignored_checks",[])],
        "netlist_pins_checked":native_pins,
        "output_schematic_sha256":audit.sha(SCH) if SCH.exists() else None,
        "output_netlist_sha256":audit.sha(NET) if NET.exists() else None,
        "output_bom_sha256":audit.sha(BOM) if BOM.exists() else None,
        "bench_primary_secondary_bias_ground_tied":True,
        "isolated_production_bias_power_verified":False,
        "output_pcb_sha256":None,
        "hardware_built":False,"g0_approved":False,"g1_approved":False,
        "energization_allowed":False,"fabrication_approved":False,
        "integration_handoff_only":True,
    }

def refresh_kicad(parts, symbols, text):
    DEST.mkdir(parents=True,exist_ok=True)
    SCH.write_text(text,encoding="utf-8")
    PRO.write_text(d0.project_file().replace('d0_protection.kicad_pro',PRO.name),encoding="utf-8")
    # Reuse original library symbol content, but emit exclusively under private dir.
    old=d0.OUT
    try:
        d0.OUT=DEST
        d0.write_libs(symbols)
        d0.bom(parts)
    finally:
        d0.OUT=old
    cli=d0.kicad_cli()
    if cli is None:
        raise RuntimeError("KiCad 10 CLI missing")
    subprocess.run([str(cli),"sch","export","netlist","-o",str(NET),str(SCH)],check=True)
    subprocess.run([str(cli),"sch","erc","--severity-all","--format","json",
                    "-o",str(ERC),str(SCH)],check=True)
    return json.loads(ERC.read_text("utf-8"))

def check_native(parts, text):
    if not all(p.is_file() for p in (SCH,PRO,NET,ERC,REPORT,BOM)):
        raise ValueError("native candidate output files missing")
    if SCH.read_text("utf-8")!=text:
        raise ValueError("saved KiCad candidate schematic stale")
    erc=json.loads(ERC.read_text("utf-8"))
    if any(s.get("violations") for s in erc.get("sheets",[])):
        raise ValueError("native KiCad candidate ERC has violations")
    refs={"U18","C29","R64","C40","R74","D17","R45","TP20","TP21","TP22","TP23","TP24","J11","J12","U20","R112","R113","R114","R20","R22","R110","R111","C114","C115"}
    pins=audit.verify_exported_netlist(parts,refs,NET.read_text("utf-8"))
    # All candidate connections must be checked against the native exported netlist.
    allrefs={part.ref for part in parts if not part.ref.startswith("#")}
    pins=audit.verify_exported_netlist(parts,allrefs,NET.read_text("utf-8"))
    # Physical assembly export, not just the drawn schematic, must preserve DNP.
    with BOM.open(newline="",encoding="utf-8") as f:
        rows={row["Reference"]:row for row in csv.DictReader(f)}
    for ref in DO_NOT_POPULATE|{"R45"}:
        if rows.get(ref,{}).get("DNP")!="yes":
            raise ValueError(f"critical DNP missing from assembly BOM: {ref}")
    for ref in ("R21","R23","C14","C15","R110","R111","R112","R113","R114","C114","C115"):
        if rows.get(ref,{}).get("Value")!={p.ref:p.value for p in parts}[ref]:
            raise ValueError(f"UVLO/hold-up BOM value incorrect: {ref}")
    rep=build_report(parts,erc,pins)
    if json.loads(REPORT.read_text("utf-8"))!=rep:
        raise ValueError("native candidate contract stale")
    return rep

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    args=ap.parse_args()
    parts,symbols,text=expected_text()
    verify_candidate(parts)
    if args.write:
        erc=refresh_kicad(parts,symbols,text)
        allrefs={part.ref for part in parts if not part.ref.startswith("#")}
        pins=audit.verify_exported_netlist(parts,allrefs,NET.read_text("utf-8"))
        if any(s.get("violations") for s in erc.get("sheets",[])):
            raise ValueError("generated KiCad candidate ERC violations")
        REPORT.write_text(json.dumps(build_report(parts,erc,pins),indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    result=check_native(parts,text)
    print(result["status"],"netlist_pins_checked",result["netlist_pins_checked"],
          "native_erc_violations",result["native_erc_violations"])
if __name__=="__main__":
    main()
