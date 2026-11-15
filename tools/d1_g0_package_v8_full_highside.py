"""Independent source-authored full V8 58-part KiCad schematic and net parity.

The schematic is generated from V7 safety-control source and V8 isolated
high-side analog front-end source, NEVER from a PCB exported netlist. Verify
each footprint pad and each exported schematic pin. This alone is NOT
functional safety, a validated 48V power disconnect, or a fab-ready design.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,subprocess,sys,shutil,zipfile
from pathlib import Path
import pcbnew as pcb
import make_d0_protection_board as k
import d1_g0_estop_interlock_v7 as v7
import d1_g0_estop_interlock_v7_schematic as v7sch
import d1_g0_v8_highside_monitor as hs
import d1_g0_v8_route_highside_monitor as routing
import d1_lane_c_g0_gate as g0

OUT=hs.OUT
STEM="d1_g0_V8_NC_ESTOP_GH_HB_AMC1311_INDEPENDENT_SOURCE_NOT_FOR_FAB"
PCB=OUT/(STEM+".kicad_pcb")
NATIVE_DRC=OUT/(STEM+"_native_drc.json")
SCH=OUT/(STEM+".kicad_sch")
PRO=OUT/(STEM+".kicad_pro")
NET=OUT/(STEM+".net")
ERC=OUT/(STEM+"_native_erc.json")
RPT=OUT/"V8_58part_source_authored_schematic_native_KiCad_receipt_NOT_FOR_FAB.json"
SYMLIB=OUT/"G0V8Source.kicad_sym"
V7LIB=OUT/"G0V7Interlock.kicad_sym"
LIBTABLE=OUT/"sym-lib-table"
BOM=OUT/"V8_58part_independent_source_BOM_NOT_FOR_FAB.csv"
README=OUT/"OPEN_FIRST_V8_NOT_FOR_FAB.md"
ZIP=OUT/"G0_V8_58PART_GH_HB_MONITORED_INTERLOCK_NATIVE_KICAD_NOT_FOR_FAB.zip"
FILES=(PCB,SCH,PRO,NET,ERC,NATIVE_DRC,routing.BOARD,routing.DRC,hs.BOARD,hs.DRC,routing.REPORT,hs.REPORT,SYMLIB,V7LIB,LIBTABLE,BOM,README)
LIB="G0V8Source"
PINS={
"traco":{"1":"+VIN","2":"-VIN","3":"+VOUT","4":"TRIM","5":"-VOUT","6":"REMOTE"},
"l7805":{"1":"VIN","2":"GND","3":"VOUT"},
"amc":{"1":"VDD1","2":"VIN","3":"SHTDN","4":"GND1","5":"GND2","6":"OUTN","7":"OUTP","8":"VDD2"},
"comp":{"1":"OUT1","2":"IN1-","3":"IN1+","4":"GND","5":"IN2+","6":"IN2-","7":"OUT2","8":"VCC"},
"res":{"1":"A","2":"B"},
"cap":{"1":"A","2":"B"},
"capin":{"1":"A","2":"B"},
"capout":{"1":"A","2":"B"},
"fuse":{"1":"VIN","2":"VOUT"},
"terminal":{"1":"A","2":"B"},
"terminal3":{"1":"GH","2":"HB","3":"SW"},
"hdr3":{"1":"HB_VALID","2":"GH_OFF","3":"PGND"},
"hdr4":{"1":"GH_OUTP","2":"GH_OUTN","3":"HB_OUTP","4":"HB_OUTN"},
}
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
def authoritative():
  parts,sy=v7sch.parts()
  for i,(ref,(typ,xy,value,pinmap)) in enumerate(hs.P.items()):
    lib=f"{LIB}:{ref}"
    names=PINS[typ]
    if set(names)!=set(pinmap):raise ValueError("V8 vendor pin assignment incomplete "+ref)
    half=(len(pinmap)+1)//2
    pins=[]
    for j,pin in enumerate(sorted(pinmap,key=int)):
      left=j<half
      offset=j if left else j-half
      pins.append(k.Pin(pin,names[pin],-13.97 if left else 13.97,
           10.16-2.54*offset,0 if left else 180,"passive"))
    prefix=("U" if typ in ("traco","l7805","amc","comp") else
            "J" if typ in ("terminal","terminal3","hdr3","hdr4") else
            "F" if typ=="fuse" else
            "C" if typ.startswith("cap") else "R")
    sy[lib]=k.custom_symbol(lib,pins,22.86,30.48,prefix,"")
    fp=":".join(hs.F[typ])
    parts.append(k.snap(k.Part(ref,lib,value,fp,
                34+46*(i%7),225+30*(i//7),
                {n:(net if net else k.NC) for n,net in pinmap.items()},
                source="Vendor-indexed TI AMC1311B/LM393B, Traco THN30, onsemi MC7805 front-end",
                note="Actual galvanic isolation PCB, tolerances and G0 functional safety NOT signed")))
  k.validate(parts,sy)
  return parts,sy,k.schematic(sy,parts)
def check_actual_pin_parity(parts):
  expected={p.ref:{pin:("" if net==k.NC else net) for pin,net in p.nets.items()}
        for p in parts if not p.ref.startswith("#")}
  b=pcb.LoadBoard(str(PCB))
  physical_release=next((f for f in b.GetFootprints() if f.GetReference()=="R_HS_RELEASE"),None)
  if physical_release is None or not physical_release.IsDNP():
    raise ValueError("danger: final native PCB HS 0R diagnostic-to-permit link not marked DNP")
  got={}
  for fp in b.GetFootprints():
    ps={}
    for pad in fp.Pads():
      no=pad.GetNumber();net=pad.GetNetname()
      if no in ps and ps[no]!=net:raise ValueError("duplicate pad/net collision "+fp.GetReference())
      ps[no]=net
    got[fp.GetReference()]=ps
  if expected!=got:
    mismatch={name:{"from_independent_source":expected.get(name),
                    "native_pad_net":got.get(name)}
              for name in expected.keys()|got.keys() if expected.get(name)!=got.get(name)}
    raise ValueError("V8 vendor real pin parity FAILED "+str(mismatch)[:3500])
  return got
def write_symbols(sy):
  lines=['(kicad_symbol_lib (version 20241209) (generator "V8HSIndependentSource")']
  lines.extend(symbol.replace(f'(symbol "{LIB}:','(symbol "',1)
        for name,symbol in sy.items() if name.startswith(LIB+":"))
  lines.append(")")
  SYMLIB.write_text("\n".join(lines)+"\n",encoding="utf8")
  shutil.copyfile(v7sch.SYMS,V7LIB)
  src="$"+"{KIPRJMOD}"
  LIBTABLE.write_text('(sym_lib_table\n\t(version 7)\n'
     '\t(lib (name "'+LIB+'")(type "KiCad")(uri "'+src+
     '/G0V8Source.kicad_sym")(options "")(descr ""))\n'
     '\t(lib (name "G0V7Interlock")(type "KiCad")(uri "'+src+
     '/G0V7Interlock.kicad_sym")(options "")(descr ""))\n)\n',encoding="utf8")
def bom(pins):
  with BOM.open("w",newline="",encoding="utf8") as handle:
    writer=csv.writer(handle,lineterminator="\n")
    writer.writerow(("Reference","VendorOrCandidateValue","KiCadNativeFootprint",
          "IndependentPadNetContract","NativeKiCad_DNP","AssemblyQualified","G0FabApproved"))
    for ref,pm in sorted(pins.items()):
      if ref in hs.P:typ,xy,val,net=hs.P[ref];fp=":".join(hs.F[typ])
      else:typ,xy,val,net=v7.PARTS[ref];fp=":".join(v7.F[typ])
      writer.writerow((ref,val,fp,
       ";".join(f"{no}={name}" for no,name in sorted(pm.items(),key=lambda x:int(x[0]))),
       "YES" if ref=="R_HS_RELEASE" else "NO","NO","NO"))
def readme():
  return ("# V8 Native KiCad -- G0 BLOCKED / NOT FOR FAB\n\n"
  "Open the .kicad_pro of the same stem with KiCad 10. Dual AMC1311B"
  " monitored analog GH-SW and HB-SW, one independent THN30 floating 12V,"
  " dual 5V MC7805 regulators, LM393B diagnostics and real 6-layer"
  " NC EStop/relay-control interlock. PCB contains 58 physical footprints."
  " Gate highside PWM is NOT permanently OFF so GH_GATE_OFF is diagnostic"
  " only; HB_VALID static alone cannot authorize startup or run."
  " Dangerous R_HS_RELEASE 0R to V7 HS_OK_IN is DNP ALWAYS and must remain"
  " unpopulated until independent phase-aware hardwired watchdog exists."
  " Other open risks: original V5 halfbridge bootstrap integration,"
  " Traco 12V trim/remote, AMC1311B real isolation/creepage, comparator"
  " threshold and effective 5V supply, physical e-stop/welded pole tests,"
  " vendor BOM and actual magnetics."
  " This delivery has NO physical gate G0 signoff. Never issue Gerber or"
  " enable main 48V based on native DRC/ERC results.\n")
def receipt(parts):
  pinmap=check_actual_pin_parity(parts)
  er=json.loads(ERC.read_text("utf8"))
  dr=json.loads(NATIVE_DRC.read_text("utf8"))
  errs=sum(len(sh.get("violations",[])) for sh in er.get("sheets",[]))
  count=g0.verify_exported_netlist(parts,{p.ref for p in parts if not p.ref.startswith("#")},
                                  NET.read_text("utf8"))
  expected=sum(len(v) for v in pinmap.values())
  if len(pinmap)!=58 or errs or count!=expected or dr.get("violations") or dr.get("unconnected_items"):
    raise ValueError(f"V8 independent source native ERC={errs} DRC={len(dr.get('violations',[]))} "
                      f"Open={len(dr.get('unconnected_items',[]))} parts={len(pinmap)} netpin={count}/{expected}")
  return {
    "kind":"D1_G0_V8_ISOLATED_GH_HB_NATIVE_SOURCE_AUTHORED_SCHEMATIC_AND_PCB",
    "native_footprints":len(pinmap),"independent_ref_pin_net_parity":count,
    "native_ERC_errors":errs,
    "native_DRC_errors":len(dr.get("violations",[])),
    "native_unconnected":len(dr.get("unconnected_items",[])),
    "V7_original_control_connections_physically_routed":24,
    "extra_float_isolated_analog_frontend_footprints":len(hs.P),
    "true_AMC1311B_highside_analog_measurement_connected_in_native_CAD":True,
    "HS_OK_gate_connection_is_DNP_and_NOT_power_permission":True,
    "GH_gateoff_is_diagnostic_only_not_runtime_safety_permission":True,
    "isolated_physical_creepage_stress_and_CTR_qualified":False,
    "real_high_side_drive_VB_SW_and_GH_SW_loom_verified":False,
    "independent_phase_aware_HS_watchdog_present":False,
    "hardware_installed_and_witnessed":False,
    "g0_physical_signoff":False,"fabrication_approved":False,
    "energization_allowed":False,
    "source_HS_analog_native_board_sha256":sha(PCB),
    "source_independent_schematic_sha256":sha(SCH),
    "source_native_DRC_sha256":sha(NATIVE_DRC),
    "source_native_ERC_sha256":sha(ERC),
    "data_files_sha256":{file.name:sha(file) for file in FILES if file!=README},
  }
def write():
  parts,sy,sch=authoritative()
  # Native KiCad project requires .pcb, .sch and .pro to share one stem.
  # Preserve the independently routed physical PCB as source evidence.
  shutil.copyfile(routing.BOARD,PCB)
  check_actual_pin_parity(parts)
  SCH.write_text(sch,encoding="utf8")
  PRO.write_text(k.project_file(),encoding="utf8")
  write_symbols(sy)
  bom(check_actual_pin_parity(parts))
  README.write_text(readme(),encoding="utf8")
  cli=Path(sys.executable).with_name("kicad-cli.exe")
  for cmd in (
    [str(cli),"pcb","drc","--severity-all","--format","json","-o",str(NATIVE_DRC),str(PCB)],
    [str(cli),"sch","export","netlist","-o",str(NET),str(SCH)],
    [str(cli),"sch","erc","--severity-all","--format","json","-o",str(ERC),str(SCH)]
  ):
    proc=subprocess.run(cmd,capture_output=True,text=True,errors="replace")
    if proc.returncode:raise ValueError("KiCad SCH CLI failed: "+proc.stderr)
  r=receipt(parts)
  RPT.write_text(json.dumps(r,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
  with zipfile.ZipFile(ZIP,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as z:
    for f in (*FILES,RPT):z.write(f,f.name)
  with zipfile.ZipFile(ZIP) as z:
    if z.testzip() or len(z.namelist())!=len(FILES)+1:
      raise ValueError("V8 KiCad archive CRC or file count invalid")
  return r
def check():
  parts,sy,sch=authoritative()
  if PCB.read_bytes()!=routing.BOARD.read_bytes():
    raise ValueError("V8 native project PCB diverged from fully routed physical CAD")
  if SCH.read_text("utf8")!=sch:raise ValueError("V8 independent source changed")
  r=receipt(parts)
  if r!=json.loads(RPT.read_text("utf8")):raise ValueError("V8 receipt stale")
  with zipfile.ZipFile(ZIP) as z:
    if z.testzip() or set(z.namelist())!={f.name for f in (*FILES,RPT)}:
      raise ValueError("V8 ZIP corrupt or incomplete")
    for f in (*FILES,RPT):
      if z.read(f.name)!=f.read_bytes():raise ValueError("V8 ZIP member drift "+f.name)
  return r
if __name__=="__main__":
  parser=argparse.ArgumentParser()
  group=parser.add_mutually_exclusive_group(required=True)
  group.add_argument("--write",action="store_true")
  group.add_argument("--check",action="store_true")
  a=parser.parse_args()
  x=write() if a.write else check()
  print({k:x[k] for k in ("native_footprints","independent_ref_pin_net_parity",
        "native_ERC_errors","native_DRC_errors","native_unconnected")})
