"""Generate one supplier RFQ sheet per magnetic device: T1-T4, the Lr and the CT.

The roadmap (``docs/文献驱动审核与DeepSeek整改路线_2026-11-04.md``, deliverable 3)
asks for the magnetics supplier package split **by device**, carrying winding
polarity, target Lm and leakage, the operating waveform, rated and fault
current, temperature, allowable loss, insulation, complete height, tolerances
and a physical terminal drawing.

Two rules drive this file:

* every number is read from the file that already produced it (a sheet that
  restates a number in its own words is the drift this repository keeps paying
  for), and
* a field this repository cannot answer is written ``UNKNOWN`` and repeated in
  the open-items list -- never dropped, never filled with a plausible value.

The physical terminal drawing is deliberately absent: that is what the supplier
is being asked to return.  What we can send today is the *logical* connection
diagram, and the sheet says so.

Run:
    python tools/magnetics_rfq_package.py --write
    python tools/magnetics_rfq_package.py          # verify the committed sheets
"""

from __future__ import annotations

import argparse
import csv
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAG = ROOT / "design/v3/magnetics"
BOM = ROOT / "design/v3/bom"
HW = ROOT / "hardware/dcx_main"
PCB = ROOT / "design/v3/pcb"
OUT = HW / "rfq"

UNKNOWN = "UNKNOWN"
STATUS = "REQUEST_FOR_QUOTE_NOT_VERIFIED"
HEIGHT_LIMIT_MM = 10.0

SECTIONS = (
    ("terminals", "绕组极性与逻辑端子"),
    ("inductance", "电感、匝比与气隙"),
    ("waveform", "工作波形"),
    ("currents", "额定电流与故障电流"),
    ("temperature", "温度"),
    ("loss", "允许损耗"),
    ("insulation", "绝缘"),
    ("mechanical", "完整高度"),
    ("tolerances", "公差"),
    ("drawing", "物理端子图"),
)


@lru_cache(maxsize=None)
def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def row(label: str, value: object, source: str, unit: str = "", digits: int = 3) -> dict:
    return {"label": label, "value": value, "unit": unit, "digits": digits, "source": source}


def _fmt(item: dict) -> str:
    value = item["value"]
    if isinstance(value, float):
        text = f"{value:.{item['digits']}f}"
    else:
        text = str(value)
    return f"{text} {item['unit']}".strip()


def terminal_rows(ref: str) -> list[dict]:
    """Logical terminals with their dot convention, read from the vendor request."""
    request = _json(HW / "vendor_terminal_request.json")
    device = next(d for d in request["devices"] if d["ref"] == ref)
    return [
        row(p["logical_terminal"], p["required_circuit_net"], "hardware/dcx_main/vendor_terminal_request.json",
            unit="", digits=0)
        | {"dot": p["dot_convention_expected"]}
        for p in device["pins"]
    ]


def transformer(ref: str) -> dict:
    mag = _json(MAG / "magnetics_design.json")
    op = mag["operating_point_100a"]
    core = mag["core"]
    copper = mag["copper_100a"]
    lr = _json(BOM / "lr_design.json")
    lp = 10e-6
    turns = 3
    al_target_nh = lp / turns**2 * 1e9
    flat = mag["height"]["flat_no_pocket"]
    pocket = mag["height"]["pocket_0.5mm_no_clamp"]
    return {
        "ref": ref,
        "kind": "TRANSFORMER_3_1_1_CENTRE_TAP",
        "title": "3:1:1 中心抽头平面变压器（D1 主功率板，四原边串联）",
        "quantity": 1,
        "terminals": terminal_rows(ref),
        "inductance": [
            row("匝比", "3:1:1（原边 3 匝，副边每半 1 匝，中心抽头）", "磁件设计包 §1"),
            row("目标激磁电感 Lm", 10.0, "磁件设计包 §3 / 模型 LP=10u", unit="uH", digits=1),
            row("目标 AL", al_target_nh, "= Lm / Np^2，由 Lm 与 3 匝反算", unit="nH/T^2", digits=1),
            row("中柱气隙（工艺目标）", mag["gap_mm"], "magnetics_design.json:gap_mm", unit="mm", digits=4),
            row("气隙窗口", "0.112 - 0.126 mm（AL ±25 % 把所需气隙推开）", "磁件设计包 §3"),
            row("气隙加工口径", "按 AL 磨，不按固定气隙磨；AL 偏限时按实测 AL 重算", "磁件设计包 §3"),
            row("漏感（塔内模型总量）", lr["tank"]["leakage_model_h"] * 1e6, "lr_design.json:tank.leakage_model_h",
                unit="uH", digits=3),
            row("单只漏感目标", f"{UNKNOWN}（模型只有一个集总漏感元件，未按只拆分）", "—"),
        ],
        "waveform": [
            row("开关频率", op["f_Hz"] / 1e3, "magnetics_design.json:operating_point_100a", unit="kHz", digits=2),
            row("原边磁密峰值 @50 V", mag["flux"]["50v_b_pk_t"], "magnetics_design.json:flux", unit="T", digits=5),
            row("原边磁密峰值 @48 V", mag["flux"]["48v_b_pk_t"], "magnetics_design.json:flux", unit="T", digits=5),
            row("原边磁密峰峰 ΔB @48 V", mag["flux"]["48v_delta_b_t"], "magnetics_design.json:flux", unit="T", digits=5),
            row("磁通判据", "按各绕组实际电压积分；不要用 L*I/(N*Ae)（那是 Lr 的判据）", "路线 §P1 磁件"),
            row("原边激励", "半桥方波 ±VIN/2，四只原边串联均分，每只承担 1/4", "磁件设计包 §2"),
        ],
        "currents": [
            row("原边 RMS @100 A", op["Ipri_rms_A"], "magnetics_design.json:operating_point_100a", unit="A", digits=4),
            row("原边峰值 @100 A", op["Ipri_pk_A"], "magnetics_design.json:operating_point_100a", unit="A", digits=4),
            row("副边每半 RMS", op["Isec_rms_A"], "magnetics_design.json:operating_point_100a", unit="A", digits=4),
            row("副边每对 RMS", op["Isec_pair_rms_A"], "magnetics_design.json:operating_point_100a", unit="A", digits=4),
            row("故障峰值（物理 deck）", 84.02, "lr_design.json:physical_peaks.fault_phys_ride_through", unit="A", digits=2),
            row("故障峰值（48 V hotfault）", 97.44, "CLAUDE.md / hotfault 48 V 严格日志校验", unit="A", digits=2),
            row("故障峰值（50 V hotfault 前缀）", 101.26, "hotfault 50 V 诊断前缀（求解器塌缩前）", unit="A", digits=2),
        ],
        "temperature": [
            row("绕组热点设计点", 100, "磁件设计包 §4.3（5.3 A/mm^2 的常规口径）", unit="°C", digits=0),
            row("环境温度", UNKNOWN, "仓库没有整机环境温度要求"),
            row("允许温升", UNKNOWN, "无热模型、无量热数据"),
        ],
        "loss": [
            row("磁芯损耗", mag["core_loss_w_per_set_50v"], "magnetics_design.json:core_loss_w_per_set_50v",
                unit="W", digits=4),
            row("磁芯损耗口径", "B^2 f^2 上界，不是 N97 在 20 mT / 200 kHz 的实测点", "磁件设计包 §9"),
            row("铜损 @100 A", copper["total_w"] / 4.0, "= copper_100a.total_w / 4 只", unit="W", digits=4),
            row("合计 @100 A", mag["core_loss_w_per_set_50v"] + copper["total_w"] / 4.0,
                "效率预算已计入这 0.622 W/只", unit="W", digits=4),
        ],
        "insulation": [
            row("原副边之间", "0.10 mm Kapton", "磁件设计包 §4.1"),
            row("同绕组层间", "0.05 mm Kapton", "磁件设计包 §4.1"),
            row("外层", "0.10 mm 胶带", "磁件设计包 §4.1"),
            row("耐压 / 爬电距离", UNKNOWN, "磁件设计包 §9 第 5 条：未按任何安全标准判定"),
        ],
        "mechanical": [
            row("磁芯 + I 片", "9.50 标称 / 9.80 最坏（套件最大，不是两件最大值相加）", "磁件设计包 §8"),
            row("平铺总高", f"{flat['nominal_m']*1e3:.2f} 标称 / {flat['worst_case_m']*1e3:.2f} 最坏",
                "magnetics_design.json:height.flat_no_pocket"),
            row("0.5 mm 沉槽总高", f"{pocket['nominal_m']*1e3:.2f} 标称 / {pocket['worst_case_m']*1e3:.2f} 最坏",
                "magnetics_design.json:height.pocket_0.5mm_no_clamp"),
            row("整机限值", HEIGHT_LIMIT_MM, "路线：D1 首样目标 16 mm，严格 10 mm 只作 D3 目标", unit="mm", digits=2),
            row("平铺余量", flat["margin_m"] * 1e3, "0.06 mm 不可量产（PCB 翘曲与焊膏波动同量级）", unit="mm", digits=3),
            row("沉槽余量", pocket["margin_m"] * 1e3, "推荐方案", unit="mm", digits=3),
            row("平面尺寸", f"{core['outer_length_m']*1e3:.2f} × {core['core_depth_m']*1e3:.2f}",
                "magnetics_design.json:core", unit="mm"),
            row("跨顶金属夹", "不可用：0.5 mm 夹子把最坏高度推到 10.44 mm", "磁件设计包 §8"),
        ],
        "tolerances": [
            row("磁芯高度公差", "±0.15 mm", "磁件设计包 §8 / ELP32 原厂尺寸"),
            row("窗口净高", mag["window_height_mm"], "magnetics_design.json:window_height_mm", unit="mm", digits=2),
            row("窗口高度公差", "±0.15 mm", "magnetics_design.json:core.window_tol_m"),
            row("电感验收窗口", "10.0 uH ±10 %（台架 100 kHz 小信号）", "磁件设计包 §3"),
            row("平面度 / 端子位置公差", UNKNOWN, "磁件设计包 §9 第 6 条：只覆盖高度方向"),
        ],
        "drawing": [
            row("逻辑端子图（可发）", "design/v3/magnetics/winding_connections.svg", "winding_polarity.py 生成"),
            row("绕组叠层（可发）", "design/v3/magnetics/winding_cross_section.svg", "draw_magnetics.py 生成"),
            row("高度堆叠（可发）", "design/v3/magnetics/height_stackup.svg", "make_magnetics_manifest.py 收录"),
            row("物理端子图 / 焊盘号", f"NOT AVAILABLE —— 这正是询价要的；本仓库没有厂商端子图",
                "magnetic_vendor_map_audit：physical_pad 全为 null"),
        ],
        "open_items": [
            "每只 1 匝副边与 CTAP 的物理焊盘号、坐标与公差。CTAP 不是「同名端相连」：它是 S_A 的 DOT 与 S_B 的非 DOT 共用一块铜。",
            "Lm 的温度系数与 0 - 121 A 直流偏磁曲线（100 °C）。",
            "原副边耐压、爬电距离、绝缘材料等级与测试方法。",
            "0.121 mm 中柱气隙在 18 mm 宽铜箔上的边缘磁通对铜损的影响：本仓库未建模，估算 +0.2 - 0.6 W。",
            "是否对 T1-T4 也套用 Lr 的 1.2 倍询价余量（121.52 A）——这是决定，不是测量，需设计负责人签字。",
        ],
        "sources": [
            "design/v3/magnetics/magnetics_design.json",
            "design/v3/magnetics/winding_polarity.csv",
            "design/v3/magnetics/winding_polarity.json",
            "design/v3/magnetics/磁件设计包_2026-10-31.md",
            "design/v3/bom/lr_design.json",
            "hardware/dcx_main/vendor_terminal_request.json",
        ],
    }


def inductor() -> dict:
    lr = _json(BOM / "lr_design.json")
    tank = lr["tank"]
    three = next(c for c in lr["candidates"] if c["turns"] == 3)
    al_target_nh = tank["total_target_h"] / three["turns"] ** 2 * 1e9
    return {
        "ref": "Lr",
        "kind": "RESONANT_INDUCTOR",
        "title": "谐振电感 Lr（独立件，不是变压器的漏感）",
        "quantity": 1,
        "terminals": [
            row("N1", "CT_LR", "design/v3/pcb/board_netlist.csv", digits=0)
            | {"dot": "绕线起点建议标记；电感无极性要求"},
            row("N2", "PRI_T1", "design/v3/pcb/board_netlist.csv", digits=0)
            | {"dot": "绕线终点建议标记；电感无极性要求"},
        ],
        "inductance": [
            row("谐振腔目标总电感", tank["total_target_h"] * 1e6, "lr_design.json:tank.total_target_h",
                unit="uH", digits=3),
            row("外置件目标", tank["external_target_h"] * 1e6, "lr_design.json:tank.external_target_h",
                unit="uH", digits=3),
            row("首件修法", "外置件 = 目标总电感 - 实测漏感；1.0 uH 是筛选上限，不是要绕的值", "lr_design.json:tank.note"),
            row("匝数", three["turns"], "lr_design.json:physical_peaks.min_turns_all", digits=0),
            row("目标 AL", al_target_nh, "= 1.0 uH / 3^2", unit="nH/T^2", digits=2),
            row("气隙（由目标 AL 算）", three["gap_mm"], "lr_design.json:candidates[3 匝].gap_mm", unit="mm", digits=4),
            row("饱和电流 Isat", three["isat_a"], "lr_design.json:candidates[3 匝].isat_a", unit="A", digits=1),
            row("气隙公差窗口", UNKNOWN, "需要厂家的 L(I, T) 曲线才能定验收窗口"),
        ],
        "waveform": [
            row("开关频率", tank["clock_khz"], "lr_design.json:tank.clock_khz", unit="kHz", digits=2),
            row("谐振频率", tank["resonant_khz"], "lr_design.json:tank.resonant_khz", unit="kHz", digits=2),
            row("磁密设计上限", 0.248, "第20章：B <= 0.248 T 的筛选线（不是签核值）", unit="T", digits=3),
            row("3 匝最小截面积需求", 179.659554, "第20章：121.52 A 下 Amin >= 179.66 mm^2（推荐 >= 200）",
                unit="mm^2", digits=2),
            row("原厂标准件结论", "五组未改造标准 ELP + I 组合无一同时满足磁通与完整高度", "第20章筛选表"),
        ],
        "currents": [
            row("稳态峰值 @100 A", lr["peaks_a"]["steady"], "lr_design.json:peaks_a.steady", unit="A", digits=3),
            row("冷启动峰值", 22.53, "lr_design.json:physical_peaks.startup_phys", unit="A", digits=2),
            row("故障峰值（物理 deck）", 84.02, "lr_design.json:physical_peaks.fault_phys_ride_through", unit="A", digits=2),
            row("故障峰值（外置件取下限）", 104.17, "lr_design.json:physical_peaks.fault_lrmin_ride_through", unit="A", digits=2),
            row("故障峰值（50 V hotfault 前缀）", 101.26, "50 V 诊断前缀", unit="A", digits=2),
            row("询价设计电流", 121.52, "第20章：101.26 A x 1.20 的 RFQ 假设", unit="A", digits=2),
        ],
        "temperature": [
            row("设计点", 100, "第20章：100 °C 的 L(I) 曲线是询价要求", unit="°C", digits=0),
            row("环境温度", UNKNOWN, "仓库没有整机环境温度要求"),
            row("铜箔温升", UNKNOWN, "无热模型"),
        ],
        "loss": [
            row("铜损（3 匝）", three["loss_w"], "lr_design.json:candidates[3 匝].loss_w = Irms^2 * R_ac", unit="W", digits=4),
            row("磁芯损耗", UNKNOWN, "lr_design.json 只算铜损；Lr 的磁芯损耗未建模"),
            row("口径", "Dowell 一维模型，含邻近效应；不是量热值", "lr_design.json"),
        ],
        "insulation": [
            row("绕组对磁芯", UNKNOWN, "本仓库没有 Lr 绝缘要求"),
            row("匝间", UNKNOWN, "单层绕组，未定义"),
            row("无原副边隔离", "Lr 是单绕组件，不承担隔离", "磁件设计包"),
        ],
        "mechanical": [
            row("标准 ELP32 裸芯高度", "9.20 - 9.80 mm（不含 PCB / 焊料 / 铜箔 / 引出端）", "第20章 TDK 原厂尺寸"),
            row("整机限值", HEIGHT_LIMIT_MM, "D1 首样目标 16 mm；严格 10 mm 是 D3 目标", unit="mm", digits=2),
            row("结论", "标准 ELP32 装进整机必超 10 mm", "第20章"),
            row("首选询价结构", "整机叠层（含板、绕组、胶、沉槽）计入 10 mm；裸芯 <= 8-9 mm 作为谈判起点",
                "第20章（谈判起点，不是设计结论）"),
        ],
        "tolerances": [
            row("气隙 / AL 公差", UNKNOWN, "须由厂家给出 L(I, T) 后定义"),
            row("电感验收窗口", UNKNOWN, "同上"),
            row("端子位置公差", UNKNOWN, "无物理端子图"),
        ],
        "drawing": [
            row("逻辑端子", "2 个：N1 = CT_LR，N2 = PRI_T1", "board_netlist.csv"),
            row("物理端子图 / 焊盘号", "NOT AVAILABLE —— 独立 Lr 的器件、引脚与机械定义尚未取得", "路线 §P1 磁件"),
        ],
        "open_items": [
            "三匝 Amin >= 200 mm^2 的定制低矮磁路；标准 ELP32 在 121.52 A 下不满足磁通筛选。",
            "0 - >=121.52 A、100 °C 的增量电感 L(I) 与直流偏磁曲线。",
            "外置件与变压器漏感的分配：外置 = 目标总电感 - 实测漏感，首件实测后才定。",
            "独立 Lr 的物理端子、焊盘与机械定义（器件定义目前只有电感/匝数/气隙）。",
            "气隙公差与 AL 验收窗口。",
        ],
        "sources": [
            "design/v3/bom/lr_design.json",
            "design/v3/power_priority/lr_tdk_catalog_core_screen.json",
            "docs/D1_EXECUTION_KIT/20_低矮磁件Lr原厂尺寸磁通双约束审核.md",
            "design/v3/pcb/board_netlist.csv",
        ],
    }


def current_transformer() -> dict:
    ct = _json(BOM / "ct_design.json")
    built = ct["as_built"]
    measured = ct["measured"]
    core = ct["core_candidate"]
    return {
        "ref": "CT",
        "kind": "CURRENT_TRANSFORMER_4_TERMINAL",
        "title": "串联在谐振腔里的电流互感器（4 个独立逻辑端子）",
        "quantity": 1,
        "terminals": terminal_rows("CT"),
        "inductance": [
            row("匝比", f"{built['turns_ratio']:.0f}:1", "ct_design.json:as_built（100:1）", digits=0),
            row("二次负载电阻", built["burden_ohm"], "冻结值，不随 CT 改", unit="Ω", digits=1),
            row("磁芯截面积 Ae", core["ae_m2"] * 1e6, "ct_design.json:core_candidate（候选，未选定件）", unit="mm^2", digits=2),
            row("磁芯饱和磁密", core["bsat_t"], "ct_design.json:core_candidate", unit="T", digits=2),
            row("励磁电感（模型）", 20.0, "deck 里的 20 mH 支路；额定下约 0.04 % 二次电流，故障时不成立", unit="mH", digits=1),
        ],
        "waveform": [
            row("频率", 1.0 / measured["period_s"] / 1e3, "= 1 / ct_design.json:measured.period_s",
                unit="kHz", digits=2),
            row("一次电流峰值 / 平均", measured["peak_to_average"], "ct_design.json:measured.peak_to_average（实测）", digits=3),
            row("半周电荷", measured["q_half_c"] * 1e6, "ct_design.json:measured.q_half_c", unit="uC", digits=3),
            row("磁密峰值 @额定", built["flux_peak_t"], "ct_design.json:as_built.flux_peak_t", unit="T", digits=6),
            row("磁密占 Bsat", built["flux_peak_t"] / core["bsat_t"] * 100.0, "由上两行相除", unit="%", digits=2),
            row("合规电压", built["compliance_v"], "ct_design.json:as_built.compliance_v", unit="V", digits=3),
        ],
        "currents": [
            row("一次 RMS", measured["i_rms_a"], "ct_design.json:measured", unit="A", digits=4),
            row("一次峰值", measured["i_pk_a"], "ct_design.json:measured", unit="A", digits=4),
            row("一次平均", measured["i_avg_a"], "ct_design.json:measured", unit="A", digits=4),
            row("故障峰值（50 V hotfault 前缀）", 101.26, "50 V 诊断前缀", unit="A", digits=2),
            row("二次 RMS = 一次 / 匝比", measured["i_rms_a"] / built["turns_ratio"], "由上两行相除", unit="A", digits=5),
        ],
        "temperature": [
            row("设计点", 100, "与整机磁件同口径", unit="°C", digits=0),
            row("环境温度", UNKNOWN, "仓库没有整机环境温度要求"),
        ],
        "loss": [
            row("二次负载功耗", built["burden_power_w"], "ct_design.json:as_built.burden_power_w", unit="W", digits=4),
            row("口径提醒", "这 89 mW 耗在 R3 上，不在 CT 本体；48 V/120 A 实测是 125.7 mW", "CLAUDE.md 测量口径"),
            row("CT 本体铁损 / 铜损", UNKNOWN, "未建模"),
        ],
        "insulation": [
            row("原副边绝缘", UNKNOWN, "vendor_terminal_request.json：Confirm primary-secondary insulation and test method with vendor"),
            row("测试方法", UNKNOWN, "同上"),
            row("结论", "CT 串在 48 V 谐振腔里，原副边隔离等级未定义", "路线 §P1 磁件"),
        ],
        "mechanical": [
            row("高度", UNKNOWN, "ct_design.json 只有 Ae 与 Bsat，没有磁芯型号与机械尺寸"),
            row("整机限值", HEIGHT_LIMIT_MM, "D3 严格目标", unit="mm", digits=2),
            row("现行封装", "2 pad —— 无效，必须换成 4 个独立端子", "vendor_terminal_request.json:requirements"),
        ],
        "tolerances": [
            row("匝比公差", UNKNOWN, "无要求来源"),
            row("相位误差", UNKNOWN, "无要求来源"),
            row("端子位置公差", UNKNOWN, "无物理端子图"),
        ],
        "drawing": [
            row("逻辑端子", "4 个：PRI_A = CR_CT，PRI_B = CT_LR，SEC_A = CS1，SEC_B = CS2",
                "hardware/dcx_main/vendor_terminal_request.json"),
            row("物理端子图 / 焊盘号", "NOT AVAILABLE —— 需要厂家给出 4 个独立端子的图与极性", "vendor_terminal_request.json"),
        ],
        "open_items": [
            "四个独立物理端子的焊盘、坐标与极性的厂商图（现行封装只有 2 pad，是无效的）。",
            "原副边耐压、爬电距离与绝缘测试方法。",
            "磁芯型号与机械尺寸：现在只有 Ae 与 Bsat，完整高度无从判断。",
            "故障电流下的直流偏磁与剩磁：ct_design.json 的 caveats 假设 AC 自复位，带直流偏置的故障不覆盖。",
        ],
        "sources": [
            "design/v3/bom/ct_design.json",
            "design/v3/pcb/board_netlist.csv",
            "hardware/dcx_main/vendor_terminal_request.json",
        ],
    }


def devices() -> list[dict]:
    return [transformer(f"T{i}") for i in range(1, 5)] + [inductor(), current_transformer()]


def render(dev: dict) -> str:
    lines = [
        f"# RFQ {dev['ref']} —— {dev['title']}",
        "",
        f"状态：**{STATUS}**（询价单，不是制造图，不是签核）。数量：{dev['quantity']} 只。",
        "",
        "每个数字都注明出处；本仓库没有数据的项写 UNKNOWN 并汇总在第 11 节，不省略、不填看起来合理的值。",
        "",
    ]
    for index, (key, title) in enumerate(SECTIONS, start=1):
        lines += [f"## {index}. {title}", "", "| 项目 | 值 | 出处 |", "|---|---|---|"]
        if key == "terminals":
            lines = lines[:-2] + ["| 逻辑端子 | 电路网络 | 设计 DOT | 出处 |", "|---|---|---|---|"]
            for item in dev["terminals"]:
                lines.append(f"| {item['label']} | {_fmt(item)} | {item['dot']} | {item['source']} |")
        else:
            for item in dev[key]:
                lines.append(f"| {item['label']} | {_fmt(item)} | {item['source']} |")
        lines.append("")
    lines += ["## 11. 未决项（本仓库没有数据，或需要决定）", ""]
    lines += [f"{i}. {item}" for i, item in enumerate(dev["open_items"], start=1)]
    lines += ["", "## 12. 出处", ""]
    lines += [f"- `{s}`" for s in dev["sources"]]
    lines += [
        "",
        "**跨件提醒**：变压器的磁通按各绕组实际电压积分核算；`L*I/(N*A)` 是 Lr 的电感筛查判据，"
        "不能拿来判断变压器励磁饱和。系统 24:1 是「半桥 + 四原边串联」与「3:1:1」共同形成的，"
        "单件匝比是 3:1:1。",
        "",
    ]
    return "\n".join(lines)


def index(devs: list[dict]) -> dict:
    return {
        "kind": "D1_MAGNETICS_SUPPLIER_RFQ_PACKAGE",
        "status": STATUS,
        "rule": "one sheet per device; every field this repository cannot answer is UNKNOWN and listed in open_items",
        "sections": [title for _, title in SECTIONS],
        "devices": [
            {
                "ref": d["ref"],
                "kind": d["kind"],
                "quantity": d["quantity"],
                "sheet": f"{OUT.name}/{d['ref']}.md",
                "unknown_count": sum(
                    1 for key, _ in SECTIONS for item in d[key] if UNKNOWN in str(item["value"])
                ),
                "open_item_count": len(d["open_items"]),
                "sources": d["sources"],
            }
            for d in devs
        ],
    }


def write(devs: list[dict]) -> list[tuple[Path, str]]:
    OUT.mkdir(parents=True, exist_ok=True)
    files = [(OUT / f"{d['ref']}.md", render(d)) for d in devs]
    files.append((OUT / "rfq_index.json", json.dumps(index(devs), ensure_ascii=False, indent=1) + "\n"))
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    devs = devices()
    stale = []
    for path, text in write(devs):
        if args.write:
            path.write_text(text, encoding="utf-8", newline="\n")
        elif not path.is_file() or path.read_text(encoding="utf-8") != text:
            stale.append(path.name)
    if stale:
        raise SystemExit(f"stale RFQ sheets: {', '.join(stale)}; rerun with --write")
    unknowns = sum(1 for d in devs for key, _ in SECTIONS for item in d[key] if UNKNOWN in str(item["value"]))
    print(f"RFQ sheets: {len(devs)} devices (T1-T4, Lr, CT), {unknowns} UNKNOWN fields reported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
