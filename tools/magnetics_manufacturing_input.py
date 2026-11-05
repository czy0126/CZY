"""One manufacturing-input page per magnetic part: T1-T4, the Lr and the CT.

This is the sibling of ``magnetics_rfq_package.py`` and answers a different
question.  An RFQ asks a supplier what they can offer across several cores and
turn counts, so it carries candidate tables on purpose.  A manufacturing page
freezes one candidate, states what the winder is being asked to make, and lists
the measurements that decide acceptance when the first article comes back.

Three rules, all inherited from the 2026-11-05 review:

* The transformer and the Lr are separate decisions.  The Lr failed the
  L*I/(N*A) screen on ELP32 and moved to ELP38; the transformers are set by
  voltage integration and stay on ELP32.  One page each, one frozen core each.
* A flux number integrated from a deck's secondary voltage is a simulation.
  It is labelled 仿真波形积分 and never 实测.  The measurement column starts
  empty and is filled after the first article.
* A physical pad number is a requirement, not a value.  This repository holds
  no vendor terminal drawing, so every page asks for one and prints no number.

Run:
    python tools/magnetics_manufacturing_input.py --write
    python tools/magnetics_manufacturing_input.py --check
"""

from __future__ import annotations

import argparse
import csv
import json
from functools import lru_cache
from pathlib import Path

import magnetics_rfq_package as rfq
from magnetics_design import core_gap_m

ROOT = Path(__file__).resolve().parent.parent
MAG = ROOT / "design/v3/magnetics"
BOM = ROOT / "design/v3/bom"
POWER = ROOT / "design/v3/power_priority"
HW = ROOT / "hardware/dcx_main"
OUT = HW / "manufacturing"

STATUS = "MANUFACTURING_INPUT_DRAFT_NOT_RELEASED"
BLANK = "—"
D1 = rfq.D1
D3 = rfq.D3


@lru_cache(maxsize=None)
def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def row(label: str, value: object, source: str) -> dict:
    return {"label": label, "value": value, "source": source}


def _num(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


def gap_window_mm(l_nom_h: float, tolerance: float, turns: int, ae_m2: float,
                  al_ungapped_nh: float) -> tuple[float, float]:
    """Grinding window that keeps the finished part inside ``l_nom`` +- ``tolerance``.

    The page used to carry the RFQ's literal "0.112 - 0.126 mm".  That pair came
    from nobody: it is not in any JSON.  Solving the same reluctance relation the
    design used gives a window that moves when the acceptance window or the core
    constants move.
    """
    # A wider gap means less inductance, so the low end of the acceptance window
    # is the widest gap.  Returning them in the other order prints "0.1374 -
    # 0.1077 mm", which is a window a machinist cannot grind to.
    narrow = core_gap_m(l_nom_h * (1.0 + tolerance), turns, ae_m2, al_ungapped_nh) * 1e3
    wide = core_gap_m(l_nom_h * (1.0 - tolerance), turns, ae_m2, al_ungapped_nh) * 1e3
    return narrow, wide


def terminals(ref: str) -> list[dict]:
    """Logical terminals plus the physical-pad requirement.

    T1-T4 and the CT come from the vendor request, which lists every terminal
    with a null physical id.  The Lr is not in that file -- it is a two-terminal
    part the board netlist already names -- so its requirement is read from
    there.  Neither source has a pad number, so both print 待商家提供.
    """
    if ref == "Lr":
        path = ROOT / "design/v3/pcb/board_netlist.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            pins = [r for r in csv.DictReader(handle) if r["ref"] == "Lr"]
        return [{"logical": r["pin"], "net": r["net"], "dot": "无极性要求（两端可互换）",
                 "physical": "待商家提供"} for r in pins]
    request = _json(HW / "vendor_terminal_request.json")
    device = next(d for d in request["devices"] if d["ref"] == ref)
    return [{
        "logical": pin["logical_terminal"],
        "net": pin["required_circuit_net"],
        "dot": pin["dot_convention_expected"],
        "physical": pin["vendor_physical_terminal_id"] or "待商家提供",
    } for pin in device["pins"]]


def backfill(fields: tuple[str, ...]) -> list[dict]:
    return [row(field, BLANK, "首件实测后回填") for field in fields]


def transformer(ref: str) -> dict:
    mag = _json(MAG / "magnetics_design.json")
    core = mag["core"]
    copper = mag["copper_100a"]
    lr = _json(BOM / "lr_design.json")
    flux = _json(MAG / "transformer_flux_100a.json")["results"]
    turns, l_nom, tol = 3, 10e-6, 0.10
    al_nh = l_nom / turns**2 * 1e9
    low, high = gap_window_mm(l_nom, tol, turns, core["Ae_m2"], core["AL_ungapped_nH"])
    flat, pocket = mag["height"]["flat_no_pocket"], mag["height"]["pocket_0.5mm_no_clamp"]
    measured = ref in ("T1", "T4")
    return {
        "ref": ref,
        "title": "3:1:1 中心抽头平面变压器（D1 主功率板，四原边串联）",
        "quantity": 1,
        "note": ("磁通由副边电压积分得到的是仿真波形积分；T1/T4 存了副边电压，T2/T3 未存，"
                 "四只磁芯常数逐项相同，按同型代表。" if not measured else
                 "磁通由副边电压积分得到的是仿真波形积分，不是实物测量；实物值留空在回填栏。"),
        "candidate": [
            row("磁芯套件", f"ELP32（{core['name']}）", "magnetics_design.json:core.name"),
            row("材料 / Bsat", f"N97 / {core['Bsat_T']:.3f} T @100 °C", "magnetics_design.json:core.Bsat_T"),
            row("匝比", "3:1:1（原边 3 匝，副边每半 1 匝，中心抽头）", "磁件设计包 §1"),
            row("目标 Lm", f"{_num(l_nom * 1e6, 1)} uH ±{tol * 100:.0f} %", "磁件设计包 §3 / 模型 LP=10u"),
            row("目标 AL", f"{_num(al_nh, 1)} nH/T^2", "= Lm / Np^2"),
            row("中柱气隙（工艺目标）", f"{_num(mag['gap_mm'], 4)} mm", "magnetics_design.json:gap_mm"),
            row("气隙窗口", f"{_num(low, 4)} - {_num(high, 4)} mm",
                "由 Lm ±10 % 用 core_gap_m() 反算（不再是询价单里的字面值）"),
            row("磨削口径", "按 AL 磨，不按固定气隙磨；AL 偏限时按实测 AL 重算", "磁件设计包 §3"),
        ],
        "winding": [
            row(f"{layer['layer']}", f"{_num(layer['thickness_mm'], 3)} mm", "magnetics_design.json:winding_stack")
            for layer in mag["winding_stack"]
        ] + [
            row("叠层总厚", f"{_num(mag['winding_stack_mm'], 2)} mm", "magnetics_design.json:winding_stack_mm"),
            row("窗口净高 / 可绕宽度", f"{_num(mag['window_height_mm'], 2)} mm / "
                                      f"{_num(mag['window_width_mm'], 2)} mm", "magnetics_design.json"),
            row("最大铜箔宽", f"{_num(mag['copper_width_max_mm'], 2)} mm", "magnetics_design.json:copper_width_max_mm"),
            row("原边", "3 匝，每匝一层 0.1 mm Cu，四只原边串联", "磁件设计包 §2"),
            row("副边 A / B", "各 1 匝，2 × 0.1 mm Cu；共用中心抽头", "磁件设计包 §1"),
        ],
        "dimensions": [
            row("磁芯 + I 片高", f"{_num(core['height_nominal_m'] * 1e3, 2)} 标称 / "
                                 f"{_num(core['height_max_m'] * 1e3, 2)} 最坏", "magnetics_design.json:core"),
            row("外形长 × 深", f"{_num(core['outer_length_m'] * 1e3, 2)} × "
                               f"{_num(core['core_depth_m'] * 1e3, 2)} mm", "magnetics_design.json:core"),
            row("中柱宽 / 窗口高", f"{_num(core['centre_leg_width_m'] * 1e3, 2)} mm / "
                                   f"{_num(core['window_height_m'] * 1e3, 2)} ±"
                                   f"{_num(core['window_tol_m'] * 1e3, 2)} mm", "magnetics_design.json:core"),
            row("全叠层（平铺）", f"{_num(flat['nominal_m'] * 1e3, 2)} 标称 / "
                                  f"{_num(flat['worst_case_m'] * 1e3, 2)} 最坏", "magnetics_design.json:height"),
            row("全叠层（0.5 mm 沉槽）", f"{_num(pocket['nominal_m'] * 1e3, 2)} 标称 / "
                                         f"{_num(pocket['worst_case_m'] * 1e3, 2)} 最坏",
                "magnetics_design.json:height.pocket_0.5mm_no_clamp"),
            row("整机限值 D1 / D3", f"{_num(rfq.height_limit_mm(D1), 1)} / "
                                    f"{_num(rfq.height_limit_mm(D3), 1)} mm", "d1_staged_target_policy.json"),
            row("平铺余量（对 D3）", f"{_num(flat['margin_m'] * 1e3, 3)} mm",
                "magnetics_design.json:height.flat_no_pocket.margin_m（余量很小，见未决项）"),
        ],
        "tests": [
            ("Lm", "100 kHz，0.1 V，25 °C，小信号", f"{_num(l_nom * 1e6, 1)} uH ±{tol * 100:.0f} %",
             "磁件设计包 §3"),
            ("漏感（副边短路）", "100 kHz，原边测量，四只串联各测一次",
             "单只不设上界；实测值用于把外置 Lr 修到 1.00 uH（见 Lr 页 L_external）",
             "lr_design.json:tank.note"),
            ("匝比", "1 kHz 小信号，逐绕组", "3:1:1，整数匝，偏差 0 匝", "磁件设计包 §1"),
            ("极性", "按 winding_polarity.json 的 DOT 逐个通断", "与 DOT 表逐端一致", "tools/winding_polarity.py"),
            ("直流电阻", "20 °C，四线法",
             f"原边 ≤ {_num(copper['primary_unit_ohm'] * 1e3, 3)} mΩ，"
             f"副边半 ≤ {_num(copper['secondary_half_ohm'] * 1e3, 3)} mΩ",
             "magnetics_design.json:copper_100a"),
            ("L 随直流偏磁", "0 - 121 A，100 °C，按厂家 L(I, T) 曲线",
             f"不小于 25 °C 值的 90 %；仿真磁密峰峰 "
             f"{_num(flux['peak_to_peak_t'] * 1e3, 2)} mT（仿真波形积分）", "磁件设计包 §3 / 路线 §P1"),
            ("全叠层高度", "千分尺，最大处，含胶与标签",
             f"≤ {_num(flat['worst_case_m'] * 1e3, 2)} mm；超过即与 D3 余量冲突", "magnetics_design.json:height"),
            ("耐压 / 爬电", "待厂家给出绝缘材料等级后确定",
             "待厂家（本仓库未按任何安全标准判定，不写数值）", "磁件设计包 §9 第 5 条"),
            ("温升", "满 100 A 连续 30 min；环境温度待定",
             "绕组热点 ≤ 100 °C 设计点", "磁件设计包 §4.3"),
        ],
        "backfill": backfill(("件号", "日期", "仪器 / 夹具", "Lm (uH)", "漏感 (uH)", "原边 DCR (mΩ)",
                              "副边 DCR (mΩ)", "L @121 A (uH)", "全叠层高 (mm)", "耐压", "温升 (K)",
                              "结论")),
        "open_items": [
            "环境温度与允许温升：仓库没有整机温度要求，所以温升判据只有设计点，不是额定。",
            "原副边耐压、爬电距离与绝缘等级：磁件设计包 §9 明确未按任何标准判定。",
            f"平铺余量只剩 {_num(flat['margin_m'] * 1e3, 3)} mm——TIM、冷板与紧固件的数据本仓库没有。",
            "单只漏感：模型只有一个集总漏感，没有按只拆分，所以单只不设上界。",
            "T2/T3 没有副边电压探针，故障窗磁通按 T1 代表，不能写成实测。",
        ],
        "sources": [
            "design/v3/magnetics/magnetics_design.json",
            "design/v3/magnetics/transformer_flux_100a.json",
            "design/v3/bom/lr_design.json",
            "hardware/dcx_main/vendor_terminal_request.json",
        ],
    }


def inductor() -> dict:
    lr = _json(BOM / "lr_design.json")
    tank = lr["tank"]
    candidates = rfq.lr_core_candidates()
    preferred = candidates["preferred"]
    design = next(c for c in lr["catalogue_cores"]["cores"] if c["id"] == preferred)
    usable = [t for t in design["turns"]
              if t["passes_margin_at_paired_peaks"] and t["gap_inside_published_validity"]]
    if not usable:
        raise SystemExit(f"{preferred}: no turn count both fits the grinding range "
                         f"and holds 0.9*Bsat at the measured peaks")
    turn = usable[0]
    turns = turn["turns"]
    external = tank["external_target_h"]
    al_nh = tank["total_target_h"] / turns**2 * 1e9
    low, high = gap_window_mm(external, 0.10, turns, design["ae_mm2"] * 1e-6, design["al_ungapped_nh"])
    core_row = next(r for r in candidates["rows"] if r["id"] == preferred)
    return {
        "ref": "Lr",
        "title": "谐振电感 Lr（独立件，不是变压器的漏感）",
        "quantity": 1,
        "note": ("Lr 与变压器是两个决定：Lr 按电感保持率、气隙与故障电流选套件，变压器按电压积分选。"
                 "本页冻结 Lr 的一个候选，变压器的候选见 T1-T4 各页。"),
        "candidate": [
            row("磁芯套件", f"TDK ELP 38/8/25 + I 38/4/25（{design['ordering']}，N97）", "references/datasheets/elp38.pdf"),
            row("匝数", f"{turns} 匝", "lr_design.json:catalogue_cores（气隙工艺范围与 0.9*Bsat 同时卡出）"),
            row("目标电感（外置件）",
                f"L_external = L_tank_target − L_leak_measured = {_num(tank['total_target_h'] * 1e6, 3)} − "
                f"实测漏感（模型值 {_num(tank['leakage_model_h'] * 1e6, 3)} ⇒ "
                f"{_num(external * 1e6, 3)} uH）", "lr_design.json:tank"),
            row("筛选上限", f"{_num(tank['total_target_h'] * 1e6, 3)} uH——这是筛选上限，不是要绕的值",
                "lr_design.json:tank.note"),
            row("目标 AL", f"{_num(al_nh, 1)} nH/T^2", f"= {_num(tank['total_target_h'] * 1e6, 3)} uH / {turns}^2"),
            row("气隙（按 AL 算）", f"{_num(turn['gap_mm'], 4)} mm",
                "lr_design.json:catalogue_cores（ELP38 自己的 AL，不是 ELP32 的 1.4443 mm）"),
            row("气隙窗口", f"{_num(low, 4)} - {_num(high, 4)} mm",
                "由外置件 ±10 % 用 core_gap_m() 反算"),
            row("厂家气隙有效区间", f"{_num(design['gapping_validity_s_mm'][0], 2)} - "
                                    f"{_num(design['gapping_validity_s_mm'][1], 2)} mm",
                "elp38.pdf；N97 的气隙常数 TDK 未公布，所以落区间仍是解析值"),
            row("饱和电流（Amin）", f"{_num(turn['isat_a_amin'], 1)} A",
                "isat_a_amin = Bs·N·Amin/L"),
            row("最坏配对磁密", f"{_num(turn['worst_paired_flux_t'], 4)} T = "
                                f"{_num(turn['worst_paired_frac_bsat'] * 100, 1)} % Bsat",
                "每个实测峰值用自己的电感，不是把电流套到目标 L 上"),
        ],
        "winding": [
            row("匝数 / 层数", f"{turns} 匝，单层", "本页冻结候选"),
            row("端子", "2 个：N1 = CT_LR，N2 = PRI_T1", "design/v3/pcb/board_netlist.csv"),
            row("绕向", "无极性要求；两端做标记以便首件复现", "磁件设计包"),
        ],
        "dimensions": [
            row("整机限值 D1 / D3", f"{_num(rfq.height_limit_mm(D1), 1)} / "
                                    f"{_num(rfq.height_limit_mm(D3), 1)} mm", "d1_staged_target_policy.json"),
            row("首选套件全叠层最坏高", f"{_num(core_row['stack_worst_mm'], 2)} mm",
                "magnetics_design.json:catalogue_core_stack（含胶/标签/沉槽，不含夹子）"),
            row("留给 TIM / 冷板 / 紧固件", f"{_num(core_row['left_mm'], 2)} mm",
                "magnetics_design.json:catalogue_core_stack"),
            row("窗口净高 / 单侧宽", f"{_num(design['window_height_mm'], 2)} ±"
                                     f"{_num(design['window_height_tolerance_mm'], 2)} mm / "
                                     f"{_num(design['window_width_per_side_mm'], 2)} mm",
                "references/datasheets/elp38.pdf 第 7 页"),
            row("对 D3 的余量", f"{_num(rfq.height_limit_mm(D3) - core_row['stack_worst_mm'], 2)} mm"
                               f"（负值 = 本候选只能用 D1；D3 需换更矮的套件）",
                "= D3 限值 − 本套件全叠层最坏高"),
        ],
        "tests": [
            ("电感（小信号）", "100 kHz，0.1 V，25 °C", f"{_num(external * 1e6, 3)} uH ±10 %",
             "由 L_external 与自选验收窗口"),
            ("L 随直流偏磁", "0 - 121.5 A，100 °C，按厂家 L(I, T) 曲线",
             f"不得跌破 {_num(external * 1e6 * 0.9, 3)} uH（外置件的 0.9 倍）", "第 20 章询价假设"),
            ("气隙 / AL", "按 AL 磨；实测 AL 反算气隙",
             "落在厂家公布的有效区间内；N97 常数未公布，验收按 AL 而不是按气隙",
             "lr_tdk_catalog_core_screen.json"),
            ("直流电阻", "20 °C，四线法",
             "待厂家给出绕组尺寸后由铜损预算反算（本仓库只算了 Irms²·R_ac 的铜损）", "lr_design.json:candidates"),
            ("全叠层高度", "千分尺，最大处", f"≤ {_num(core_row['stack_worst_mm'], 2)} mm", "magnetics_design.json"),
            ("耐压", "单绕组件，不做原副边耐压；绕组对磁芯按整机绝缘要求另定",
             "待整机绝缘等级确定", "磁件设计包 §4.1"),
            ("温升", "满 100 A 连续 30 min；环境温度待定", "绕组热点 ≤ 100 °C 设计点", "第 20 章"),
        ],
        "backfill": backfill(("件号", "日期", "仪器 / 夹具", "L 小信号 (uH)", "L @121.5 A (uH)",
                              "AL (nH/T^2)", "DCR (mΩ)", "全叠层高 (mm)", "温升 (K)", "结论")),
        "open_items": [
            "ELP38 上 N97 的气隙计算常数 TDK 未公布，所以气隙仍是解析值，需厂家按 AL 公差确认。",
            "0 - 121.5 A、100 °C 的增量电感 L(I)：验收窗口沿用外置件 ±10 %。",
            "外置件与变压器漏感的分配：首件实测漏感后才定，0.920 uH 只是按模型漏感的预估值。",
            "独立 Lr 的物理端子、焊盘与机械定义：现在只有电感、匝数与气隙。",
        ],
        "sources": [
            "design/v3/bom/lr_design.json",
            "references/datasheets/elp38.pdf",
            "design/v3/magnetics/magnetics_design.json (catalogue_core_stack)",
            "design/v3/power_priority/lr_tdk_catalog_core_screen.json",
            "hardware/dcx_main/vendor_terminal_request.json",
        ],
    }


def current_transformer() -> dict:
    ct = _json(BOM / "ct_design.json")
    built, core = ct["as_built"], ct["core_candidate"]
    return {
        "ref": "CT",
        "title": "串联在谐振腔里的电流互感器（4 个独立逻辑端子）",
        "quantity": 1,
        "frozen": False,
        "note": ("CT 按带宽、负载与复位决定，与前两类都不同；二次负载 10 Ω 已冻结，不随 CT 改。"
                 "现行 2 pad 封装是无效的：四个逻辑端子必须各有独立物理端子。"),
        "candidate": [
            row("磁芯套件", "未选定：只有 Ae = "
                            f"{_num(core['ae_m2'] * 1e6, 2)} mm^2 与 Bsat = {_num(core['bsat_t'], 2)} T",
                "ct_design.json:core_candidate（没有型号与机械尺寸）"),
            row("匝比", f"{_num(built['turns_ratio'], 0)}:1", "ct_design.json:as_built"),
            row("二次负载", f"{_num(built['burden_ohm'], 1)} Ω（冻结，不随 CT 改）", "ct_design.json:as_built"),
            row("分压增益", f"{_num(built['divider_gain'], 4)}", "ct_design.json:as_built.divider_gain"),
            row("磁密峰值 @额定", f"{_num(built['flux_peak_t'] * 1e3, 3)} mT = "
                                  f"{_num(built['flux_peak_t'] / core['bsat_t'] * 100, 2)} % Bsat",
                "ct_design.json:as_built"),
            row("合规电压", f"{_num(built['compliance_v'], 3)} V", "ct_design.json:as_built.compliance_v"),
        ],
        "winding": [
            row("一次", "1 匝，串在谐振腔里（CR_CT → CT_LR）", "vendor_terminal_request.json"),
            row("二次", f"{_num(built['turns_ratio'], 0)} 匝，接 10 Ω 负载后整流", "ct_design.json:as_built"),
        ],
        "dimensions": [
            row("整机限值 D1", f"{_num(rfq.height_limit_mm(D1), 1)} mm（要同时供 D3 则收紧到 "
                               f"{_num(rfq.height_limit_mm(D3), 1)} mm）", "d1_staged_target_policy.json"),
            row("完整高度", "待厂家给出磁芯型号后填", "ct_design.json 只有 Ae 与 Bsat"),
            row("现行封装", "2 pad —— 无效，必须换成 4 个独立端子", "vendor_terminal_request.json:requirements"),
        ],
        "tests": [
            ("匝比与相位", "一次注入 20 A / 200 kHz 方波，二次接 10 Ω",
             "匝比 100:1；相位误差待定义（本仓库没有要求来源）", "ct_design.json"),
            ("传输比", "一次 20 A，R_b = 10 Ω",
             "0.100 V/A ±5 %；实测中位 0.0997355 V/A，标称 0.1", "hotfault srprobe 标定"),
            ("直流偏磁", "故障脉冲下的一次电流波形", "故障下 AC 自复位假设不成立，量测值只作记录", "ct_design.json:caveats"),
            ("耐压 / 爬电", "待厂家给出绝缘等级后确定",
             "待厂家（CT 串在 48 V 谐振腔里，原副边隔离等级未定义）", "vendor_terminal_request.json"),
            ("外形高度", "千分尺", f"≤ {_num(rfq.height_limit_mm(D3), 1)} mm 才能同时供 D3",
             "d1_staged_target_policy.json"),
            ("极性", "按 4 个逻辑端子的 DOT 逐个通断", "与 vendor_terminal_request.json 逐端一致",
             "tools/winding_polarity.py"),
        ],
        "backfill": backfill(("件号", "日期", "仪器 / 夹具", "匝比", "传输比 (V/A)", "励磁电感 L (uH)",
                              "二次 DCR (mΩ)", "外形高 (mm)", "耐压", "结论")),
        "open_items": [
            "四个独立物理端子的焊盘、坐标与极性的厂商图（现行封装只有 2 pad，是无效的）。",
            "原副边耐压、爬电距离与绝缘测试方法。",
            "磁芯型号与机械尺寸：现在只有 Ae 与 Bsat，完整高度无从判断。",
            "故障电流下的直流偏磁与剩磁：ct_design.json 的 caveats 假设 AC 自复位。",
        ],
        "sources": [
            "design/v3/bom/ct_design.json",
            "design/v3/pcb/board_netlist.csv",
            "hardware/dcx_main/vendor_terminal_request.json",
        ],
    }


def devices() -> list[dict]:
    return [transformer(f"T{i}") for i in range(1, 5)] + [inductor(), current_transformer()]


SECTIONS = (
    ("candidate", "冻结候选"),
    ("winding", "绕组与叠层"),
    ("terminals", "端子需求"),
    ("dimensions", "尺寸与限值"),
    ("tests", "首件试验条件"),
    ("backfill", "实测回填"),
)


def render(dev: dict) -> str:
    lines = [
        f"# 加工输入 {dev['ref']} —— {dev['title']}",
        "",
        f"状态：**{STATUS}**（加工输入草稿：未放行，不是采购结论）。数量：{dev['quantity']} 只。",
        "",
        f"本页只保留一个冻结候选。询价用的多候选表在 `hardware/dcx_main/rfq/`，两者不混用："
        f"询价问厂家能给什么，本页写我们要做什么、回来量什么。",
        "",
        dev["note"],
        "",
    ]
    if not dev.get("frozen", True):
        lines += ["**注意**：本页的磁芯套件尚未选定，因此这一页还不是一份可下单的加工输入。", ""]
    for index, (key, title) in enumerate(SECTIONS, start=1):
        lines += [f"## {index}. {title}", ""]
        if key == "terminals":
            lines += ["| 逻辑端子 | 电路网络 | 设计 DOT | 物理端子 |", "|---|---|---|---|"]
            for item in terminals(dev["ref"]):
                lines.append(f"| {item['logical']} | {item['net']} | {item['dot']} | {item['physical']} |")
            lines += ["", "物理端子号必须来自厂家端子图；本仓库没有，所以写「待商家提供」，不编焊盘号。", ""]
        elif key == "tests":
            lines += ["| 试验 | 条件 | 判据 | 出处 |", "|---|---|---|---|"]
            for name, condition, acceptance, source in dev["tests"]:
                lines.append(f"| {name} | {condition} | {acceptance} | {source} |")
            lines += ["", "判据是首件的接受/拒收线；没有判据就没有拒收依据，所以不接受只写「按厂家标准」。", ""]
        elif key == "backfill":
            lines += ["| 字段 | 回填值 |", "|---|---|"]
            for item in dev["backfill"]:
                lines.append(f"| {item['label']} | {item['value']} |")
            lines += ["", "本栏由首件实测填写，草稿里一律为空。本页的磁密来自仿真波形积分或解析计算，"
                          "气隙与 AL 是解析值——都不是这里的测量值。", ""]
        else:
            lines += ["| 项目 | 值 | 出处 |", "|---|---|---|"]
            for item in dev[key]:
                lines.append(f"| {item['label']} | {item['value']} | {item['source']} |")
            lines.append("")
    lines += ["## 7. 未决项", ""]
    lines += [f"{i}. {item}" for i, item in enumerate(dev["open_items"], start=1)]
    lines += ["", "## 8. 出处", ""]
    lines += [f"- `{s}`" for s in dev["sources"]]
    lines += [
        "",
        "**跨件提醒**：变压器的磁通按各绕组实际电压积分核算；`L*I/(N*A)` 是 Lr 的电感筛查判据，"
        "不能拿来判断变压器励磁饱和。变压器在 ELP32、Lr 在 ELP38，这是分用途的两个决定。",
        "",
    ]
    return "\n".join(lines)


def index(devs: list[dict]) -> dict:
    return {
        "kind": "D1_MAGNETICS_MANUFACTURING_INPUT_DRAFT",
        "status": STATUS,
        "rule": "one frozen candidate per page; physical pads are requirements; measurements start empty",
        "devices": [
            {
                "ref": d["ref"],
                "page": f"{OUT.name}/{d['ref']}.md",
                "terminal_count": len(terminals(d["ref"])),
                "test_count": len(d["tests"]),
                "open_item_count": len(d["open_items"]),
            }
            for d in devs
        ],
        "not": [
            "not a released drawing: no vendor terminal drawing exists in this repository",
            "not an approval: nothing here has been measured on a first article",
            "not the RFQ: the candidate menus live in hardware/dcx_main/rfq/",
        ],
    }


def write(devs: list[dict]) -> list[tuple[Path, str]]:
    OUT.mkdir(parents=True, exist_ok=True)
    files = [(OUT / f"{d['ref']}.md", render(d)) for d in devs]
    files.append((OUT / "index.json", json.dumps(index(devs), ensure_ascii=False, indent=1) + "\n"))
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    devs = devices()
    stale = []
    for path, text in write(devs):
        if args.write:
            path.write_text(text, encoding="utf-8", newline="\n")
        elif not path.is_file() or path.read_text(encoding="utf-8") != text:
            stale.append(path.name)
    if stale:
        raise SystemExit(f"stale manufacturing pages: {', '.join(stale)}; rerun with --write")
    print(f"manufacturing input: {len(devs)} pages (T1-T4, Lr, CT)"
          + (" written" if args.write else " current"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
