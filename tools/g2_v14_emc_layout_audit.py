"""D1 V14 native PCB placement/EMC audit: source-locked and read-only.

Usage:
 python tools/g2_v14_emc_layout_audit.py --write
 python tools/g2_v14_emc_layout_audit.py --check

This is an engineering geometry audit, NOT EMI qualification or fab approval.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
NATIVE=G/"dcx_main_board_g2_V14_EILP32_12NPTH_OC_OCM_OCD_REG4_BOTTOM_WIP_NOT_FOR_FAB.eprj2"
READ=G/"g2_v14_after_REG4_native_full_copper_readback_NOT_FOR_FAB.json"
DRC=G/"g2_v14_after_REG4_independent_second_native_DRC_bottom_four_NOT_FOR_FAB.json"
POUR=G/"g2_v14_emc_native_copper_pour_and_stack_live_evidence_NOT_FOR_FAB.json"
DFM=G/"g2_v14_through_board_three_leg_slot_DFM_screen_NOT_FOR_FAB.json"
OUTPUT=G/"g2_v14_EMC_compactness_placement_native_quantified_NOT_FOR_FAB.json"
REPORT=ROOT/"hardware/dcx_main/manufacturing/V14_EMC_COMPACTNESS_LAYOUT_AUDIT_NOT_FOR_FAB.md"
EXPECTED_SHA="7dd77910bcf7ff3fd0e2be1e4194439a22189aaf353f105bbe1280c104e4f6fc"
MM=.0254

def load(p):
    return json.loads(p.read_text(encoding="utf8"))

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def pos(p):
    return (p["X"]*MM,-p["Y"]*MM)

def dist(a,b):
    return round(math.dist(a,b),3)

def build():
    if sha(NATIVE)!=EXPECTED_SHA:
        raise ValueError("Real V14 native binary changed since source lock")
    j=load(READ)
    if j["board_uuid"]!="8c496410b2877d3c":
        raise ValueError("Wrong copied PCB target UUID")
    b=j["native"]
    if tuple(len(b[k]) for k in ("components","pads","lines","vias"))!=(149,423,484,104):
        raise ValueError("Wrong native component/track/via count")
    d=load(DRC)["native"]["value"]
    if d["cat"]!={"Connection Error":111}:
        raise ValueError("Cannot claim 111 connection baseline without native DRC")
    live=load(POUR)["native"]
    if tuple(live[k] for k in ("pours","poured","regions","fills"))!=(0,0,0,0):
        raise ValueError("New native copper planes require fresh EMC review")
    if live["active"]!=[1,2,*range(15,25)] or live["rule"]!="JLCPCB Capability(Two Layers Board)":
        raise ValueError("Native active layers or DRC rule changed")
    if load(DFM)["board_dimensions_mm"]!=[155.0,131.0]:
        raise ValueError("Board dimensions changed")
    cs={x["ref"]:x for x in b["components"]}
    if len(cs)!=149:
        raise ValueError("Duplicated native reference designators")
    if {"T1","T2","T3","T4","CT"}&set(cs):
        raise ValueError("Magnetic native devices added: regenerate full review")
    free=[x for x in b["pads"] if x.get("ref") is None]
    if len(free)!=4 or {x["Net"] for x in free}!={"CR_CT","CT_LR","CS1","CS2"}:
        raise ValueError("CT four anonymous pads drifted")
    def cp(r):return pos(cs[r])
    def pin(r,p):
        xs=[x for x in b["pads"] if x.get("ref")==r and x["PadNumber"]==p]
        if len(xs)!=1:raise ValueError("Missing unique pad "+r+"."+p)
        return pos(xs[0])
    def gap_net(a,c,n):
        x=[pos(q) for q in b["pads"] if q.get("ref")==a and q["Net"]==n]
        y=[pos(q) for q in b["pads"] if q.get("ref")==c and q["Net"]==n]
        if not x or not y:raise ValueError("Missing same-net pad "+n)
        return round(min(math.dist(i,k) for i in x for k in y),3)
    def total_copper_length(net):
        return round(sum(math.hypot((q["x1"]-q["x2"])*MM,(q["y1"]-q["y2"])*MM)
            for q in b["lines"] if q["net"]==net),3)
    lines=collections.Counter(x["net"] for x in b["lines"])
    vias=collections.Counter(x["net"] for x in b["vias"])
    layers=collections.Counter(x["layer"] for x in b["lines"])
    groups=next(z for z in d["raw"] if z["name"]=="Connection Error")
    open_by_net={z["name"]:len(z["list"]) for z in groups["list"]}
    if open_by_net.get("PGND")!=42 or open_by_net.get("VIN_P")!=3:
        raise ValueError("Power return and supply DRC scope changed")
    reg=[]
    core_to_sr=[]
    for i in range(1,5):
        c="C"+str(i+6)
        drv="U"+str(i+2)
        q=[x for x in b["pads"] if x.get("ref")==c]
        if len(q)!=2 or {x["PadNumber"]:x["Net"] for x in q}!={"1":"REG"+str(i),"2":"PGND"}:
            raise ValueError("Wrong native REGx/PGND cap pin map")
        if {x["Layer"] for x in q}!={2} or cs[c]["Rotation"]!=180:
            raise ValueError("REG cap must actually be bottom-side 180 degrees")
        reg.append({"cap":c,"driver":drv,"REG_pin_projected_gap_mm":dist(pin(c,"1"),pin(drv,"3"))})
        sr="SR"+str(i)+"A"
        sec=[pos(q) for q in b["pads"] if q.get("ref")==sr and q["Net"]=="SEC"+str(i)+"_A"]
        if not sec:raise ValueError("SR secondary power pad absent")
        core_to_sr.append({"core":"T"+str(i),"sr":sr,
            "min_vertical_core_slot_end_y31_to_SR_power_pad_mm":round(min(y-31 for x,y in sec),3),
            "core_center_to_SR_center_mm":dist((20+38*(i-1),20),cp(sr)),
            "driver_center_to_SR_center_mm":dist(cp(drv),cp(sr))})
    chbs=[x for x in b["components"] if x["ref"].startswith("CHB")]
    if len(chbs)!=72:raise ValueError("72 CHB outputs changed")
    chbx=[pos(x)[0] for x in chbs]
    chby=[pos(x)[1] for x in chbs]
    volume_L=155*131*16/1_000_000
    data={
      "source_real_native_eprj2":NATIVE.name,
      "source_sha256":EXPECTED_SHA,
      "source_readback_sha256":sha(READ),
      "source_DRC_sha256":sha(DRC),
      "source_live_pour_sha256":sha(POUR),
      "status":"EMC_NOT_DEMONSTRATED_NOT_COMPACT_NOT_FOR_FAB",
      "PCB_count":{"components":149,"pads":423,"lines":484,"vias":104},
      "PCB_XY_mm":[155.0,131.0],"area_mm2":155*131,
      "envelope_max_z_mm":16,
      "200W_envelope_volume_L":round(volume_L,5),
      "200W_envelope_density_kW_per_L":round(200/volume_L/1000,3),
      "QH_QL_centers_mm":dist(cp("QH"),cp("QL")),
      "input_Cin_VIN_to_QH_VIN_nearest_pads_mm":gap_net("Cin","QH","VIN_P"),
      "input_Cin_PGND_to_QL_PGND_nearest_pads_mm":gap_net("Cin","QL","PGND"),
      "Lr_to_Cr_centers_mm":dist(cp("Lr"),cp("Cr")),
      "Lr_to_CT_LR_anonymous_pad_mm":round(min(math.dist(pin("Lr","1"),pos(x))
                             for x in free if x["Net"]=="CT_LR"),3),
      "controller_U1_to_gate_driver_U2_centers_mm":dist(cp("U1"),cp("U2")),
      "driver_U2_to_QH_centers_mm":dist(cp("U2"),cp("QH")),
      "driver_U2_to_QL_centers_mm":dist(cp("U2"),cp("QL")),
      "Cout_to_J_OUT_centers_mm":dist(cp("Cout"),cp("J_OUT")),
      "CHB_output_cap_count":len(chbs),
      "CHB_cap_center_x_range_mm":[round(min(chbx),3),round(max(chbx),3)],
      "CHB_cap_center_y_range_mm":[round(min(chby),3),round(max(chby),3)],
      "native_12_layer_enables":live["active"],
      "trace_counts_by_active_layer":{str(n):count for n,count in sorted(layers.items())},
      "active_inner_layers_without_winding_tracks":[x for x in live["active"] if x not in layers],
      "native_copper_Pour_Poured_Region_Fill":
           {k:live[k] for k in ("pours","poured","regions","fills")},
      "native_DRC_rule_name":live["rule"],
      "native_DRC_Connection_Error_count":111,
      "native_DRC_Netlist_Error_count":0,
      "native_DRC_Physical_Error_reported_count_on_two_layer_rule":0,
      "open_connections_per_net":dict(sorted(open_by_net.items(),key=lambda x:(-x[1],x[0]))),
      "VIN_P_top_and_bottom_track_count":lines["VIN_P"],
      "VIN_P_via_count":vias["VIN_P"],
      "PGND_track_count":lines["PGND"],"PGND_via_count":vias["PGND"],
      "VOUT_track_count":lines["VOUT"],"VOUT_via_count":vias["VOUT"],
      "total_net_track_lengths_mm":{
        n:total_copper_length(n) for n in ("PGND","VOUT","SW","VCC12_S","OC","OCD","OCM","VIN_P")},
      "core_to_SR_spacing":core_to_sr,
      "actual_four_bottom_REG_caps":reg,
      "native_T1_to_T4_and_CT_actual_device_count":0,
      "native_anonymous_CT_pads":len(free),
      "routing_complete":False,"EMC_measured_and_passed":False,
      "vendor_12layer_3oz_DFM_approved":False,"manufacturing_release":False
    }
    return data


def render(d):
    val=lambda k:d[k]
    lines=[
      "# V14 元件布局、EMC 和功率密度：实际原生PCB检查",
      "",
      "结论：不具备宣称优秀EMC的依据，功率密度布局还不够紧凑；当前仍为NOT_FOR_FAB。",
      "本审核使用真实嘉立创原生PCB二进制SHA、独立DRC、149组件/423Pad/484线/104Via回读、12层与铜面实时查询；不代替样机EMI测试。",
      "",
      "## 定量结果",
      "",
      f"- 几何：155x131mm，16mm高度包络0.32488 L；输出2V x100A=200W时几何功率密度约{val('200W_envelope_density_kW_per_L')}kW/L；不包括外部水管和加工公差。",
      f"- 高频输入：Cin.VIN_P到QH.VIN_P最近同网焊盘直距{val('input_Cin_VIN_to_QH_VIN_nearest_pads_mm')}mm；Cin.PGND到QL.PGND {val('input_Cin_PGND_to_QL_PGND_nearest_pads_mm')}mm；VIN_P当前实际走线0条，开路3项。",
      f"- 谐振：Lr与Cr中心距{val('Lr_to_Cr_centers_mm')}mm；Lr.1到CT候选CT_LR裸焊盘直距{val('Lr_to_CT_LR_anonymous_pad_mm')}mm。",
      f"- 控制：U1到U2中心距{val('controller_U1_to_gate_driver_U2_centers_mm')}mm；U2到QH/QL为{val('driver_U2_to_QH_centers_mm')}/{val('driver_U2_to_QL_centers_mm')}mm，GD1和GD2均3项开路。",
      f"- EI变压器：磁窗下缘y=31mm，SR功率SEC焊盘顶部约y=79.18mm，即至少48.18mm竖直间隔；四只3:1:1变压器尚无真实原生绕组元件。",
      f"- 电流回流：PGND 42项开路、{val('PGND_via_count')}过孔、{val('PGND_track_count')}走线；VOUT有{val('VOUT_via_count')}过孔和{val('VOUT_track_count')}走线；不是已经证实100A连续低感回流的层面。",
      f"- 铜层：启用12铜层，但仅Top/Bottom分别有{val('trace_counts_by_active_layer')['1']}/{val('trace_counts_by_active_layer')['2']}条真实线，其他10层无任何绕组走线；Pour/Poured/Region/Fill对象全部0。",
      f"- 检测模拟量：OCM全网累计走线{val('total_net_track_lengths_mm')['OCM']}mm，OCD全网{val('total_net_track_lengths_mm')['OCD']}mm（是全网总长度，不是单条信号端到端长度）。之前修通不代表已经优化电磁耦合。",
      f"- 输出：72颗CHB并联器件中心分布在x={val('CHB_cap_center_x_range_mm')}mm、y={val('CHB_cap_center_y_range_mm')}mm；Cout到J_OUT中心距{val('Cout_to_J_OUT_centers_mm')}mm。输出需要新的对称电源/地汇流与高频旁路分区。",
      "- 改善：C7–C10真实放在U3–U6背面，L2/180度，REGx管脚与驱动器的平面投影约0.9mm，已有8个过孔及16条新线；但厚PCB跨层过孔寄生、底面冷板间隙未验证。",
      "",
      "## 设计整改优先级",
      "",
      "P0-1：重新分配输入高速环路，将真正的高频Cin与QH/QL形成紧邻回路，缩短VIN/PGND的正向加回流路径；优先完整布通VIN_P，避免通过狭窄长线给大电流通道供电。",
      "P0-2：按四个磁芯+同步整流+本地输出旁路设计四单元布局，缩短磁窗到SR的48mm间隔。先取得3:1:1绕组真实电气拓扑及厂商DOT，不能为了压低DRC直接短接不同副边。",
      "P0-3：优化主QH/QL-Cr-Lr-CT谐振流路，考虑磁耦合以及CT本体位置。当前Lr/Cr远离、CT仅四自由Pad，保护磁件尚非签核原生器件。",
      "P0-4：和板厂确定真实12L厚铜叠层、主地/功率平面和磁芯禁铜开槽策略，重构100A VOUT及PGND等阻抗回路，并通过热/直流压降/高频寄生提取。",
      "P1-1：U1与U2距离超过60mm且GD1/GD2均开路，布局要规划有返回路径的驱动控制线；QH/QL驱动环路应更靠近MOSFET。",
      "P1-2：保护OCD/OCM/OC线虽已实际布通，但走线过长，应在磁芯、QH/QL SW和大电流返回环路之外，配套近CT的整流、连续安静参考地和故障时序验证。",
      "P1-3：四路VCC12_S局部C105–108位置较近，但C109–112全部聚集在半桥上方，不是围绕四SR驱动器分布；重新规划电源分配与去耦。",
      "P2：目前四个ELP32沿宽度单排放置，必然大致占满155mm宽度；若要明显提高整机体积功率密度，需要评估2x2磁芯、四个一体化功率单元和更高密度输出电容组，而不是先盲目缩小板框。",
      "",
      "## 工程限制",
      "",
      f"- 当前真实DRC为111 Connection、0 Netlist，原生规则名仍是 {val('native_DRC_rule_name')}，与12铜层设计不匹配，不能以零Physical宣称12层制造可行。",
      "- 没有完整功率回路、12层量产叠层、非线性电磁仿真、热验证、过流保护延迟/噪声记录，亦没有实物传导/辐射测试，因此不可声称能实现很好的EMC。",
      "- 当前无需只为减少111个开路而执行全网自动布线；要先从高di/dt正向及回流路径，磁件-整流回路、信号参考地三方面重构。",
      "",
      "参考：TI SNVA810（高di/dt面积与布局）；TI SSZT090（缩小开关节点面积）；Analog Devices RAQ-207（热环路ESR/ESL）；Analog Devices AN-139（高频平面回流与EMI）。",
      ""]
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    args=p.parse_args()
    data=build()
    encoded=json.dumps(data,ensure_ascii=False,indent=2)+"\n"
    md=render(data)
    if args.write:
        for path,content in ((OUTPUT,encoded),(REPORT,md)):
            if path.exists():
                raise FileExistsError("Do not overwrite previous reviewed audit: "+str(path))
            path.write_text(content,encoding="utf8",newline="\n")
        print("WROTE",OUTPUT.name,REPORT.name)
    else:
        if OUTPUT.read_text("utf8")!=encoded or REPORT.read_text("utf8")!=md:
            raise ValueError("EMC audit stale or modified: inspect before release")
        print("V14 EMC/compactness audit source-locked and reproducible")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
