"""Export V7 interlock native KiCad functional pin source, compare PCB pad-by-pad.

Independent vendor-indexed design of two NC emergency-stop contact loops, 48V
coil path and TI CD4081/CD4013 reset latch. This is NOT a PCB-reversed SCH,
not a certified safety relay and not an actual hardware acceptance.
"""
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys,zipfile,csv
from pathlib import Path
import pcbnew as pcb
import make_d0_protection_board as k
import d1_g0_estop_interlock_v7 as design
import d1_lane_c_g0_gate as parity
ROOT=design.ROOT
OUT=design.OUT
STEM=design.STEM
SCH=OUT/(STEM+".kicad_sch")
PRO=OUT/(STEM+".kicad_pro")
NET=OUT/(STEM+".net")
ERC=OUT/(STEM+"_native_erc.json")
SYMS=OUT/"G0V7Interlock.kicad_sym"
LIBTAB=OUT/"sym-lib-table"
BOM=OUT/"V7_27_PART_VENDOR_PIN_AND_WIRING_STOPLINE_BOM.csv"
REPORT=OUT/"V7_source_authored_real_pin_interlock_schematic_NOT_FOR_FAB.json"
LIB="G0V7Interlock"
PINNAME={
"cmos4081":{str(i):v for i,v in enumerate(("A1","B1","Y1","Y2","A2","B2","VSS","A3","B3","Y3","Y4","A4","B4","VDD"),1)},
"cmos4013":{"1":"Q1","2":"QBAR1","3":"CLOCK1","4":"RESET1","5":"D1","6":"SET1","7":"VSS","8":"SET2","9":"D2","10":"RESET2","11":"CLOCK2","12":"QBAR2","13":"Q2","14":"VDD"},
"terminal":{"1":"A","2":"B"},"hdr3":{"1":"P_OK","2":"S_OK","3":"PGND"},
"fuse":{"1":"IN","2":"OUT"},"nmos":{"1":"G","2":"D","3":"S"},
"npn":{"1":"B","2":"E","3":"C"},"res":{"1":"1","2":"2"},"cap":{"1":"1","2":"2"},
"zener":{"1":"K","2":"A"}}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def parts():
 parts=[];symbols={}
 for i,(ref,(kind,xy,val,connections)) in enumerate(design.PARTS.items()):
  typ=("cmos4081" if ref=="U_AND" else "cmos4013" if ref=="U_LATCH" else kind)
  names=PINNAME[typ]
  if set(names)!=set(connections):raise ValueError("vendor pin map changed "+ref)
  count=len(connections);half=(count+1)//2
  pins=[]
  for j,num in enumerate(sorted(connections,key=lambda n:int(n))):
   left=j<half;offset=j if left else j-half
   if offset>7:raise ValueError("V7 symbol envelope mismatch")
   pins.append(k.Pin(num,names[num],-13.97 if left else 13.97,
      10.16-2.54*offset,0 if left else 180,"passive"))
  lib=f"{LIB}:{ref}"
  symbols[lib]=k.custom_symbol(lib,pins,22.86,30.48,
    "U" if kind in ("cmos","npn") else "Q" if kind=="nmos" else "J" if kind in ("terminal","hdr3") else "R","")
  fp=":".join(design.F[kind])
  parts.append(k.snap(k.Part(ref,lib,val,fp,34+46*(i%7),43+30*(i//7),
   {n:(net if net else k.NC) for n,net in connections.items()},
   source="Independent TI CD4081/CD4013 + Infineon IRL540N + Sensata GX14FAC interlock pin contract",
   note="Not a certified safety relay; NC E-stop and HS monitor external and unqualified")))
 return parts,symbols
def authoritative():
 ps,sy=parts()
 k.validate(ps,sy)
 return ps,sy,k.schematic(sy,ps)
def pin_parity_source_board():
 board=pcb.LoadBoard(str(design.BOARD))
 mapping={}
 for fp in board.GetFootprints():
  nets={}
  for pd in fp.Pads():
   n=pd.GetNumber();net=pd.GetNetname()
   if n in nets and nets[n]!=net:raise ValueError("ambiguous duplicate physical pin")
   nets[n]=net
  mapping[fp.GetReference()]=nets
 want={ref:pinmap for ref,(_,xy,val,pinmap) in design.PARTS.items()}
 if mapping!=want:
  raise ValueError("independent V7 design source != actual PCB pads: "+
   str({x:(mapping.get(x),want.get(x)) for x in mapping.keys()|want.keys() if mapping.get(x)!=want.get(x)}))
 return mapping
def library(sy):
 texts=['(kicad_symbol_lib (version 20241209) (generator "G0V7ManuallyWiredNCStop")']
 for name,symbol in sy.items():
  if not name.startswith(LIB+":"):continue
  texts.append(symbol.replace(f'(symbol "{LIB}:','(symbol "',1))
 texts.append(")")
 SYMS.write_text("\n".join(texts)+"\n",encoding="utf-8")
 uri="$"+"{KIPRJMOD}"+"/"+SYMS.name
 LIBTAB.write_text('(sym_lib_table\n\t(version 7)\n\t(lib (name "'+LIB+
 '")(type "KiCad")(uri "'+uri+'")(options "")(descr ""))\n)\n',encoding="utf-8")
def bom(pins):
 with BOM.open("w",newline="",encoding="utf-8") as f:
  writer=csv.writer(f,lineterminator="\n")
  writer.writerow(("Ref","Intended_MPN_or_TBD","Native_footprint","Pad_Net","Assembly","Vendor_spec_verified","G0_fab_approved"))
  for ref,net in pins.items():
   kind,xy,val,p=design.PARTS[ref]
   writer.writerow((ref,val,":".join(design.F[kind]),
     ";".join(f"{n}={x}" for n,x in sorted(net.items())),
     "EXTERNAL_AND_UNBUILT" if ref.startswith("J_") else "CANDIDATE_NOT_BUILT",
     "YES_PIN_OR_SYMBOL_ONLY" if ref in ("U_AND","U_LATCH","Q_COIL") else "NO","NO"))
def receipt(ps):
 pmap=pin_parity_source_board()
 er=json.loads(ERC.read_text("utf-8"))
 ev=sum(len(x.get("violations",[])) for x in er.get("sheets",[]))
 count=parity.verify_exported_netlist(ps,{p.ref for p in ps},NET.read_text("utf-8"))
 expected=sum(len(x) for x in pmap.values())
 if ev or count!=expected:
  raise ValueError(f"V7 native ERC={ev} exported pins {count} != {expected}")
 return {
   "kind":"D1_G0_V7_INDEPENDENT_ESTOP_LATCH_NATIVE_SCH_NOT_APPROVED",
   "native_PCB_parts":len(pmap),
   "independent_ref_pin_net_parity":count,
   "native_KiCad_ERC_violations":ev,
   "independent_source_schematic_derived_from_PCB":False,
   "wiring_logic_vendor_topview_pins_explicit":True,
   "NC_ESTOP_Power_loop_in_series_without_software_bypass":True,
   "manual_rearm_FF_required_after_fault":True,
   "actual_float_HS_monitor_present":False,
   "safety_rated_contactor_coil_wiring_verified_in_hardware":False,
   "physical_48V_main_contact_assembled":False,
   "actual_coil_fuse_DC_rating_verified":False,
   "source_PCB_SHA256":sha(design.BOARD),
   "source_SCH_SHA256":sha(SCH),
   "source_netlist_SHA256":sha(NET),
   "source_lib_SHA256":sha(SYMS),
   "G0_approved":False,"energization_allowed":False,"fab_release":False,
 }
def write():
 OUT.mkdir(parents=True,exist_ok=True)
 ps,sy,sch=authoritative()
 pin_parity_source_board()
 SCH.write_text(sch,encoding="utf-8")
 PRO.write_text(k.project_file(),encoding="utf-8")
 library(sy)
 bom(pin_parity_source_board())
 cli=Path(sys.executable).with_name("kicad-cli.exe")
 for cmd in (
  [str(cli),"sch","export","netlist","-o",str(NET),str(SCH)],
  [str(cli),"sch","erc","--severity-all","--format","json","-o",str(ERC),str(SCH)]
 ):
  r=subprocess.run(cmd,capture_output=True,text=True,errors="replace")
  if r.returncode:raise ValueError("KiCad ERC/netlist failed "+str(cmd)+r.stderr)
 r=receipt(ps)
 REPORT.write_text(json.dumps(r,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
 return r
def check():
 ps,sy,sch=authoritative()
 if SCH.read_text("utf-8")!=sch:raise ValueError("V7 sch changed")
 rec=receipt(ps)
 if json.loads(REPORT.read_text("utf-8"))!=rec:raise ValueError("V7 receipt stale")
 return rec
if __name__=="__main__":
 p=argparse.ArgumentParser()
 g=p.add_mutually_exclusive_group(required=True)
 g.add_argument("--write",action="store_true");g.add_argument("--check",action="store_true")
 x=p.parse_args()
 rec=write() if x.write else check()
 print({k:rec[k] for k in ("native_PCB_parts","independent_ref_pin_net_parity","native_KiCad_ERC_violations")})
