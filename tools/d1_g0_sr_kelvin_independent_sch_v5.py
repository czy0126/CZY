"""KiCad-independent design source for real four-channel VSS Kelvin ECO (V5).

Starts from separately preserved source: SPICE golden and hardware periphery,
not from new PCB pad nets. Only explicit design modifications:
 * U3-U6 VSS pin5 -> four distinct SR_KELVIN_i
 * RK1-4 populated 0-ohm 0603 tie to local SR_SOURCE_RETURN plane
 * four existing C7-C10 REG bypass parts assigned Murata 2.2uF/25V X7S
These are not a complete chip-vendor, safety, or fab approved schematic.
"""
from __future__ import annotations
import argparse,hashlib,json,shutil,subprocess,sys
from pathlib import Path
import pcbnew as pcb
import d1_g0_independent_design_source_schematic as prior
import d1_g0_sr_kelvin_reg_eco_v5 as pcb_eco
import d1_g0_native_schematic_projection as neutral
import d1_lane_c_g0_gate as parity
import make_d0_protection_board as k
import d1_g0_cross_domain_audit as ground

OUT=pcb_eco.OUT
STEM="d1_g0_INDEPENDENT_SR_KELVIN_DESIGN_NOT_FOR_FAB"
SCH=OUT/(STEM+".kicad_sch")
PRO=OUT/(STEM+".kicad_pro")
NET=OUT/(STEM+".net")
ERC=OUT/(STEM+"_native_erc.json")
SYMLIB=OUT/"G0SRKelvinSource.kicad_sym"
LIBTABLE=OUT/"sym-lib-table"
REPORT=OUT/"independent_source_441_pin_Kelvin_ECO_passport_NOT_FOR_FAB.json"
LIB="G0SRKelvinSource"

def sha(file):return hashlib.sha256(file.read_bytes()).hexdigest()
def design_data():
    expected,ids=prior.sources()
    for i in range(1,5):
        u=f"U{i+2}";cap=f"C{i+6}";rk=f"RK{i}"
        if expected[u]["5"]!=ground.SRET or expected[cap]!={"1":f"REG{i}","2":ground.SRET}:
            raise ValueError("independent source V4 authority changed")
        expected[u]["5"]=f"SR_KELVIN_{i}"
        expected[rk]={"1":ground.SRET,"2":f"SR_KELVIN_{i}"}
        ids[rk]={"design_part":"0603_0R_reference_resistor",
                 "intended_mpn":"RC0603JR-070RL (0 ohm 0603)",
                 "signal_origin":"TI UCC24624 VSS separate from PGND: source-local-net-tie_candidate"}
        ids[cap]={"design_part":"Murata_0603_2u2_25V_REG_cap",
                 "intended_mpn":pcb_eco.MURATA,
                 "signal_origin":"TI UCC24624 REG nominal bypass 2.2uF; actual DC-bias derating pending"}
    if len(expected)!=161:raise ValueError("expected 4 new resistors")
    return expected,ids

def parts():
    nets,ids=design_data()
    names=sorted(nets,key=lambda ref:(
       0 if ref.startswith(("U3","U4","U5","U6","RK")) else
       (3 if ref.startswith("CHB") else 1),ref))
    result=[];syms={}
    for i,ref in enumerate(names):
        mapping=nets[ref]
        half=(len(mapping)+1)//2
        pins=[]
        for j,num in enumerate(sorted(mapping)):
            left=j<half;offset=j if left else j-half
            if offset>6:raise ValueError("cannot fit neutral symbol 8-pin envelope "+ref)
            pins.append(k.Pin(num,num,-13.97 if left else 13.97,
                       7.62-2.54*offset,0 if left else 180,"passive"))
        lib=f"{LIB}:{ref}"
        syms[lib]=k.custom_symbol(lib,pins,22.86,25.4,
            "U" if ref.startswith("U") else "J" if ref.startswith("J")
            else "T" if ref.startswith(("T","CT")) else "R","")
        note=ids[ref]["signal_origin"]+"; NOT_FOR_FAB / NOT_G0"
        result.append(k.snap(k.Part(ref,lib,ids[ref]["intended_mpn"],"",
                25+46*(i%12),35+27*(i//12),mapping,
                source=ids[ref]["signal_origin"],note=note)))
    return result,syms,nets

def expected_sch(parts,syms):
    data=neutral.expected(parts,syms)
    data=data.replace("G0 154-package netlist projection NOT FOR FAB",
                      "G0 Independent SPICE plus TI UCC24624 VSS Kelvin ECO V5")
    data=data.replace("DERIVED FROM PCB ONLY; no independent circuit authority or magnetics OEM footprint",
                      "INDEPENDENT V4 SOURCE+explicit TI SR sense ECO, not PCB-derived or fab-approved")
    return data

def validate_circuit(schparts,model):
    board=pcb.LoadBoard(str(pcb_eco.BOARD))
    pads,raw=ground.pinpassport(board)
    if set(pads)!=set(model):raise ValueError("independent V5 design Ref inventory differs from PCB")
    mismatch=[]
    for ref,want in model.items():
        net={key:("" if value==k.NC else value) for key,value in want.items()}
        if net!=pads[ref]:mismatch.append({"ref":ref,"want":net,"got":pads[ref]})
    if mismatch:raise ValueError("V5 independent circuit-to-PCB pin mismatch "+str(mismatch[:4]))
    return board,raw

def library(syms):
    out=['(kicad_symbol_lib (version 20241209) (generator "g0_v5_independent_source")']
    out.extend(v.replace(f'(symbol "{LIB}:','(symbol "',1) for v in syms.values())
    out.append(")")
    SYMLIB.write_text("\n".join(out)+"\n",encoding="utf-8")
    u="$"+"{KIPRJMOD}"+"/G0SRKelvinSource.kicad_sym"
    LIBTABLE.write_text('(sym_lib_table\n\t(version 7)\n\t(lib (name "'+LIB+'")(type "KiCad")(uri "'+u+'")(options "")(descr ""))\n)\n',
                        encoding="utf-8")

def receipt(ps,sy,model):
    er=json.loads(ERC.read_text("utf-8"))
    faults=sum(len(s.get("violations",[])) for s in er.get("sheets",[]))
    pins=parity.verify_exported_netlist(ps,{p.ref for p in ps},NET.read_text("utf-8"))
    if pins!=441 or faults:raise ValueError("native design-source parity/ERC not clean")
    board,_=validate_circuit(ps,model)
    return {
      "kind":"D1_G0_V5_INDEPENDENT_SPICE_PLUS_TI_SR_KELVIN_SOURCE",
      "status":"161_PART_441_PIN_INDEPENDENT_SCH_ERC0_NOT_FOR_FAB",
      "independent_device_count":len(model),
      "independent_native_schematic_pin_parity":pins,
      "physical_native_board_ref_pin_net_equal_to_design":True,
      "native_KiCad_ERC_violations":faults,
      "original_SPICE_golden_sha256":sha(prior.design.GOLDEN),
      "SR_Kelvin_ECO_source_sha256":sha(Path(pcb_eco.__file__)),
      "UCC24624_pin5_VSS_separate_from_pin2_PGND":True,
      "four_0R_source_reference_parts":True,
      "REG_C7_C10_2u2_Murata_MPN":pcb_eco.MURATA,
      "REG_actual_effective_cap_at_11V_verified":False,
      "board_source_sha256":sha(pcb_eco.BOARD),
      "sch_sha256":sha(SCH),
      "net_sha256":sha(NET),
      "sym_sha256":sha(SYMLIB),
      "safety_protection_full_schematic_qualified":False,
      "magnetics_24_real_vendor_DOT_qualified":False,
      "g0_hardware_signed":False,
      "energization_allowed":False,
      "fabrication_approved":False
    }

def write():
    pcb_eco.check()
    OUT.mkdir(parents=True,exist_ok=True)
    ps,sy,model=parts()
    validate_circuit(ps,model)
    SCH.write_text(expected_sch(ps,sy),encoding="utf-8")
    shutil.copyfile(prior.PRO,PRO)
    library(sy)
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    for args in (
      [str(cli),"sch","export","netlist","-o",str(NET),str(SCH)],
      [str(cli),"sch","erc","--severity-all","--format","json","-o",str(ERC),str(SCH)]
    ):
        p=subprocess.run(args,capture_output=True,text=True,errors="replace")
        if p.returncode:raise ValueError("KiCad V5 independent source failed "+p.stderr)
    r=receipt(ps,sy,model)
    REPORT.write_text(json.dumps(r,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return r

def check():
    ps,sy,model=parts()
    if SCH.read_text("utf-8")!=expected_sch(ps,sy):
        raise ValueError("V5 native schematic content changed")
    r=receipt(ps,sy,model)
    if r!=json.loads(REPORT.read_text("utf-8")):
        raise ValueError("V5 independent schematic receipt stale")
    return r

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    a=parser.parse_args()
    r=write() if a.write else check()
    print(json.dumps({k:r[k] for k in
     ("status","independent_device_count","independent_native_schematic_pin_parity",
      "native_KiCad_ERC_violations")}))
if __name__=="__main__":main()
