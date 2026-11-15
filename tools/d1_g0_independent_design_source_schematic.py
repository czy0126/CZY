"""Design-source-authored G0 functional net topology, NOT reverse PCB pads.

Electrical nets originate exclusively from independently authored:
design/v3/pcb/board_netlist.csv (SPICE authority),
tools/main_board_schematic.py (measured library pin expansion,
extra package pin bonds and bias peripheral design),
the physically explicit secondary-ground ECO, source-registered 72x T530,
and the two separated G0 external 12V input port design contracts.

KiCad still uses *simplified* non-vendor symbols, unqualified footprints and
prototype magnetics. No protection, real Lr/T1 winding, bias/UVLO signoff.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,shutil,subprocess,sys
from pathlib import Path
import pcbnew as pcb
import make_d0_protection_board as k
import main_board_schematic as design
import d1_g0_cross_domain_audit as dom
import d1_g0_bias_ports_v4 as ports
import d1_g0_native_schematic_projection as render
import d1_lane_c_g0_gate as parity
import d1_lane_c_g0_gate as parity

ROOT=Path(__file__).resolve().parents[1]
OUT=ports.OUT
STEM="d1_g0_INDEPENDENT_SOURCE_DESIGN_SCHEMATIC_NOT_FOR_FAB"
SCH=OUT/(STEM+".kicad_sch")
PRO=OUT/(STEM+".kicad_pro")
NET=OUT/(STEM+".net")
ERC=OUT/(STEM+"_native_erc.json")
SYMLIB=OUT/"G0IndependentDesignSources.kicad_sym"
TABLE=OUT/"sym-lib-table"
REPORT=OUT/"source_design_to_native_pad_verification_NOT_FOR_FAB.json"
VENDOR="G0IndependentDesignSources"
EXT_PORTS={
  "J_BIAS_P":{"1":"VCC12","2":"PGND"},
  "J_BIAS_S":{"1":"VCC12_S","2":dom.SRET}
}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def sources():
    libs=design.load_library()
    gold=design.load_golden()
    results={}
    identity={}
    for ref,goldpins in gold.items():
        part=design.device_of(ref)
        if not part or part not in libs:raise ValueError("independent device model absent "+ref)
        entry=libs[part]
        package_pins={str(p["num"]) for p in entry["pins"]}
        nets={}
        for logical,net in goldpins.items():
            for physical in design.pads_for(part,logical,package_pins):
                if physical in nets and nets[physical]!=net:
                    raise ValueError("SPICE pin maps to multiple physical nets "+ref)
                nets[physical]=net
        for pad,net in design.BONDED_PADS.get(part,{}).items():
            if pad in nets and nets[pad]!=net:raise ValueError("package pad bond conflict")
            nets[pad]=net
            package_pins.add(pad)
        for pad in package_pins:
            nets.setdefault(pad,k.NC)
        results[ref]=nets
        identity[ref]={"design_part":part,"intended_mpn":entry.get("mpn",part),
            "signal_origin":"independent_SPICE_golden_and_measured_system_library"}
    for ref,block in design.PERIPHERALS.items():
        if ref in results:raise ValueError("peripheral already in golden "+ref)
        results[ref]=dict(block["pads"])
        identity[ref]={"design_part":block["part"],"intended_mpn":block["value"],
          "signal_origin":"independent_control_peripheral_register"}
    for i in range(1,73):
        ref=f"CHB{i:02d}"
        if ref in results:raise ValueError("bulk capacitor ID duplicate")
        results[ref]={"1":"VOUT","2":dom.SRET}
        identity[ref]={"design_part":"KEMET_T530_OEM_trial",
          "intended_mpn":"T530X OEM pad orientation qualified only at source-review stage",
          "signal_origin":"independently_specified_72x_output_cap_bank"}
    for ref,netpins in EXT_PORTS.items():
        if ref in results:raise ValueError("external bias connector duplicate")
        results[ref]=dict(netpins)
        identity[ref]={"design_part":"UNQUALIFIED_2X5MM_PTH",
          "intended_mpn":"EXTERNAL_PRIMARY_12V" if ref=="J_BIAS_P" else "EXTERNAL_ISOLATED_SECONDARY_12V",
          "signal_origin":"explicit_separate_primary_secondary_port_plan"}
    for ref,pins in dom.SECONDARY_RET_REFS.items():
        if ref.startswith("CHB"):continue  # already generated with SRET.
        for pad in pins:
            if results[ref][pad]!="PGND":
                raise ValueError("secondary ECO requires PGND at "+ref+"."+pad)
            results[ref][pad]=dom.SRET
    if len(results)!=157 or len(set(results))!=157:
        raise ValueError("157 independent design-authority parts expected")
    return results,identity

def parts():
    model,identity=sources()
    ordered=sorted(model,key=lambda ref:(
        0 if ref in ("J_IN","Cin","QH","QL","Lr","Cr","CT","T1","T2","T3","T4",
                      "U1","U2","U3","U4","U5","U6","R8","J_BIAS_P","J_BIAS_S")
          else (3 if ref.startswith("CHB") else 1),ref))
    result=[];symbols={}
    for i,ref in enumerate(ordered):
        pinmap=model[ref]
        pins=[]
        half=(len(pinmap)+1)//2
        for j,pin in enumerate(sorted(pinmap)):
            left=j<half
            offset=j if left else j-half
            if offset>6:raise ValueError("pin count exceeds neutral symbol envelope "+ref)
            pins.append(k.Pin(pin,pin,-13.97 if left else 13.97,
                   7.62-offset*2.54,0 if left else 180,"passive"))
        lib=f"{VENDOR}:{ref}"
        symbols[lib]=k.custom_symbol(lib,pins,22.86,25.4,
            "U" if ref.startswith("U") else "T" if ref.startswith(("T","CT")) else
            "J" if ref.startswith("J") else "R","")
        src=identity[ref]
        label=src["intended_mpn"]
        info=src["signal_origin"]+"; UNQUALIFIED FOR FAB"
        result.append(k.snap(k.Part(ref,lib,label,"",
           25+46*(i%12),35+27*(i//12),pinmap,source=info,note=info)))
    return result,symbols,model

def source_schematic(parts,syms):
    s=render.expected(parts,syms)
    s=s.replace("G0 154-package netlist projection NOT FOR FAB",
                "G0 source-authored SPICE and peripheral topology NOT FOR FAB")
    s=s.replace("DERIVED FROM PCB ONLY; no independent circuit authority or magnetics OEM footprint",
                "DERIVED FROM independent golden SPICE+peripheral source, NOT a manufacturer functional signoff")
    return s

def write_symbol_library(syms):
    out=['(kicad_symbol_lib (version 20241209) (generator "G0 independent design source")']
    out.extend(v.replace(f'(symbol "{VENDOR}:','(symbol "',1) for v in syms.values())
    out.append(")")
    SYMLIB.write_text("\n".join(out)+"\n",encoding="utf-8")
    uri="$"+"{KIPRJMOD}"+"/G0IndependentDesignSources.kicad_sym"
    TABLE.write_text('(sym_lib_table\n\t(version 7)\n\t(lib (name "'+VENDOR+'")(type "KiCad")(uri "'+uri+'")(options "")(descr ""))\n)\n',encoding="utf-8")

def actual_board_guard(model):
    original=pcb.LoadBoard(str(ports.BOARD))
    got,raw=dom.pinpassport(original)
    if set(model)!=set(got):
        raise ValueError("independent golden refs do not equal physical board refs")
    errors=[]
    for ref,expected in sorted(model.items()):
        observed=got[ref]
        want={pin:("" if net==k.NC else net) for pin,net in expected.items()}
        if observed!=want:
            errors.append({"ref":ref,"expected":want,"native":observed})
    if errors:
        raise ValueError("independently authored KiCad PCB/SCHEMATIC mismatches "+str(errors[:4]))
    return got,raw

def report(parts,model,erc,pin_count):
    diff=sum(len(s.get("violations",[])) for s in erc.get("sheets",[]))
    if pin_count!=433 or diff or len(parts)!=157:
        raise ValueError("source-derived schematic net parity/ERC fails")
    return {
       "kind":"G0_INDEPENDENT_SPICE_AND_PERIPHERAL_NATIVE_SCHEMATIC",
       "status":"INDEPENDENTLY_AUTHORED_LOGICAL_NET_SOURCE_MATCHES_NATIVE_157_PART_PCB_NOT_FOR_FAB",
       "independent_data_sources":{
           "spice_golden_sha256":sha(design.GOLDEN),
           "measured_library_pins_sha256":sha(design.PINS),
           "source_peripheral_mapping_module_sha256":sha(Path(design.__file__)),
           "secondary_ground_ECO_module_sha256":sha(Path(dom.__file__)),
           "external_bias_port_source_module_sha256":sha(Path(ports.__file__))
       },
       "device_count":len(parts),
       "independent_ref_pin_net_count":pin_count,
       "native_erc_violations":diff,
       "PCB_source_sha256":sha(ports.BOARD),
       "sch_sha256":sha(SCH),"net_sha256":sha(NET),"sym_sha256":sha(SYMLIB),
       "has_independent_electrical_net_basis_NOT_mirrored_from_PCB":True,
       "uses_neutral_not_vendor_approved_symbols":True,
       "real_functional_schematic_hardware_signed_off":False,
       "SR_source_referenced_to_isolated_return":True,
       "R8_DNP_to_avoid_auto_enable":True,
       "vendor_magnetic_pins_and_DOT_qualified":False,
       "UVLO_interlock_emergency_disconnect_realized":False,
       "manufacturing_approved":False,"energization_allowed":False
    }

def run_cli():
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    for cmd in (
      [str(cli),"sch","export","netlist","-o",str(NET),str(SCH)],
      [str(cli),"sch","erc","--severity-all","--format","json","-o",str(ERC),str(SCH)]
    ):
        p=subprocess.run(cmd,capture_output=True,text=True,errors="replace")
        if p.returncode:raise ValueError("Native design-source KiCad CLI failed "+str(cmd)+p.stderr)

def write():
    OUT.mkdir(parents=True,exist_ok=True)
    pt,sy,model=parts()
    actual_board_guard(model)
    SCH.write_text(source_schematic(pt,sy),encoding="utf-8")
    shutil.copyfile(ports.OUT/(ports.STEM+".kicad_pro"),PRO)
    write_symbol_library(sy)
    run_cli()
    count=parity.verify_exported_netlist(pt,{p.ref for p in pt},NET.read_text("utf-8"))
    result=report(pt,model,json.loads(ERC.read_text("utf-8")),count)
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result

def check():
    pt,sy,model=parts()
    actual_board_guard(model)
    if SCH.read_text("utf-8")!=source_schematic(pt,sy):raise ValueError("Independently authored KiCad source drift")
    count=parity.verify_exported_netlist(pt,{p.ref for p in pt},NET.read_text("utf-8"))
    result=report(pt,model,json.loads(ERC.read_text("utf-8")),count)
    if result!=json.loads(REPORT.read_text("utf-8")):raise ValueError("design source receipt stale")
    return result

def main():
    a=argparse.ArgumentParser()
    g=a.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    x=a.parse_args()
    r=write() if x.write else check()
    print(json.dumps({k:r[k] for k in ("status","device_count",
       "independent_ref_pin_net_count","native_erc_violations")}))
if __name__=="__main__":main()
