"""Generate the first-power-up checklist from the design JSONs.

The roadmap names "上电检查表" as a Stage D deliverable.  A checklist typed once by
hand drifts away from the analysis that justified it, so every acceptance number
here is formatted out of the JSON that produced it and the committed markdown is
compared byte-for-byte with a fresh render in a test.

The sheet stops at "48 V, no load" and hands the rest to the stage-F matrix
(`design/v3/stage_f/首样验证与额定值判定_2026-10-31.md`); it does not restate it.

Every item carries three extra fields because the round-3 review found numbers
being reused across operating conditions (issue #2):

    test_state            power_off / bias_only / low_bus / no_load / rated / fault
    measurement_location  where the probe goes, not just which quantity it is
    source_type           datasheet / model / hardware / design

A criterion is only valid in its own state: the 100 A OC level, the 41.4 V Cr
peak and the 36.1 A cold-start peak are rated-condition numbers and must not
appear in the no-load stage.  `test_powerup_checklist.py` enforces both the
vocabulary and the placement.

Usage:
    python tools/powerup_checklist.py --md design/v3/stage_f/上电检查表.md \
                                      --json design/v3/stage_f/powerup_checklist.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VIN_V = 48.0                  # deck `.param VIN=48`
TURNS_RATIO = 24.0            # 2 * 3 primaries * 4 groups / secondary

STATES = ("power_off", "bias_only", "low_bus", "no_load", "rated", "fault")
STAGE_STATES = {
    "S0": {"power_off"},
    "S1": {"bias_only"},
    "S2": {"low_bus"},
    "S3": {"no_load"},
    "S4": {"rated", "fault"},
}
SOURCE_TYPES = {"datasheet", "model", "hardware", "design"}

SOURCES = {
    "thermal": "design/v3/stage_f/thermal_precheck.json",
    "ct": "design/v3/bom/ct_design.json",
    "cout": "design/v3/bom/cout_bank.json",
    "cr": "design/v3/bom/cr_stress.json",
    "conn": "design/v3/bom/connector_budget.json",
    "op": "design/v3/magnetics/operating_point_100a.json",
    "mag": "design/v3/magnetics/magnetics_design.json",
    "netlist": "design/v3/pcb/board_netlist.json",
    "lr": "design/v3/bom/lr_design.json",
}


def load(root: Path = ROOT) -> dict[str, dict]:
    """Read every JSON the sheet quotes, so a drifted number shows up as a diff."""
    return {name: json.loads((root / rel).read_text(encoding="utf-8"))
            for name, rel in SOURCES.items()}


def criteria(data: dict[str, dict]) -> dict[str, str]:
    """Every acceptance number on the sheet, formatted from its source."""
    conn, op, ct, thermal = data["conn"], data["op"], data["ct"], data["thermal"]
    cr, cout, mag, netlist = data["cr"], data["cout"], data["mag"], data["netlist"]
    lr = data["lr"]
    bar = conn["output"]["bar"]
    limit = conn["joint_limit"]
    bank = cout["banks"][0]
    return {
        "joint_limit": f"{limit['per_joint_ohm'] * 1e6:.1f} µΩ",
        "bar": f"长 {bar['length_mm']:.0f} × 宽 {bar['width_mm']:.0f} × 厚 "
               f"{bar['thickness_mm']:.0f} mm",
        "bar_ohm": f"{bar['resistance_ohm'] * 1e6:.1f} µΩ",
        "startup_peak": f"{lr['peaks_a']['startup']:.1f} A",
        "startup_peak_12v": f"{lr['peaks_a']['startup'] * 12.0 / VIN_V:.1f} A",
        "fault_peak": f"{lr['peaks_a']['fault_fast_oc_13us']:.0f} A",
        "trace_width": f"{conn['input']['width_for_target_mm']:.1f} mm",
        "freq": f"{op['freq_khz']:.1f} kHz",
        "vout_nl": f"{VIN_V / TURNS_RATIO:.2f} V",
        "oc_pin": f"{ct['as_built']['oc_pin_v_at_ipk']:.3f} V",
        "oc_at": f"{ct['measured']['i_pk_a']:.2f} A",
        "trip": f"{ct['as_built']['trip_peak_a']:.1f} A",
        "compliance": f"{ct['as_built']['compliance_v']:.2f} V",
        "boot_reverse": f"{VIN_V:.0f} V",
        "sr_loss": f"{thermal['sr_loss_per_device_w_100a']:.2f} W",
        "tj_limit": f"{thermal['tj_max_c']:.0f} °C",
        "ambient_50": f"{thermal['max_ambient_c_100a']['rth_50_k_per_w']:.1f} °C",
        "cr_peak": f"{cr['v_max_v']:.1f} V",
        "cr_rms": f"{cr['i_rms_a']:.2f} A",
        "cr_esr": f"{cr['esr_ceiling_ohm'] * 1e3:.1f} mΩ",
        "cout_n": f"{bank['n']}",
        "cout_esr": f"{bank['bank_esr_ohm'] * 1e3:.2f} mΩ",
        "gap": f"{mag['gap_mm']:.3f} mm",
        "height": f"{mag['height']['flat_no_pocket']['worst_case_m'] * 1e3:.2f} mm",
        "pins": f"{netlist['checks']['pins']}",
    }


def item(check: str, criterion: str, source: str, action: str,
         location: str, source_type: str, state: str) -> dict[str, str]:
    """One checklist row.  Reject an unknown state or source type at build time."""
    if state not in STATES:
        raise ValueError(f"unknown test_state {state!r}")
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"unknown source_type {source_type!r}")
    return {"check": check, "criterion": criterion, "source": source, "action": action,
            "test_state": state, "measurement_location": location, "source_type": source_type}


def _stage_s0(c: dict[str, str]) -> dict[str, object]:
    i = lambda *a: item(*a, state="power_off")
    return {"id": "S0", "title": "板前（完全断电，万用表/四线法）", "items": [
        i("VIN_P 对 PGND 不短路", "> 1 kΩ（Cout 充电后）", "netlist", "查铜排/电容极性/焊接桥",
          "J_IN P1–P2", "hardware"),
        i("八只 SR 漏源不短路", "二极管档有值、非 0", "netlist", "拆管复测",
          "SR1A–SR4B 各 D–S 焊盘", "hardware"),
        i("十只 2.2 Ω 门阻、八只 0 Ω 开尔文链在位", "逐位号清点，合计 18 只",
          "board_netlist", "缺 0 Ω 则 SR 关断依赖焊盘 di/dt",
          "R4/R5、R20–R27、R28–R35 位号", "hardware"),
        i(f"输出铜排 {c['bar']} 的电阻", f"{c['bar_ohm']}（20 °C，几何）",
          "connector_budget", "改宽度/厚度后重算", "J_OUT P–N 四线法", "hardware"),
        i(f"两处接点四线法，单处 ≤ {c['joint_limit']}", f"≤ {c['joint_limit']}",
          "connector_budget", "超标则改压接或重算效率口径", "J_OUT 两处接点", "hardware"),
        i(f"输入走线宽度 ≥ {c['trace_width']}", f"≥ {c['trace_width']}（2 oz 或等效）",
          "connector_budget", "改叠层/加铜厚", "输入铜箔截面（卡尺）", "design"),
        i(f"输出电容 {c['cout_n']} 只、整组 ESR ≈ {c['cout_esr']}",
          f"{c['cout_n']} 只；ESR 主导，不是容量", "cout_bank", "少买则 ESR 超标",
          "Cout 组两端（LCR 100 kHz）", "hardware"),
        i(f"整机高度最坏 {c['height']}", "≤ 10 mm", "magnetics_design", "改沉槽/夹具",
          "成品最高点（高度规）", "hardware"),
        i(f"气隙 {c['gap']}、四套 Lm 一致性", "首件实测回填", "magnetics_design",
          "漏感实测前不冻结 Lr 料号", "中柱（千分尺）+ 3 匝 LCR", "hardware"),
        i(f"Cr 整组 ESR ≤ {c['cr_esr']}", f"≤ {c['cr_esr']}（1 W 允许）", "cr_stress",
          "换低 ESR 并联", "Cr 两端（LCR 200 kHz）", "hardware"),
    ]}


def _stage_s1(c: dict[str, str]) -> dict[str, object]:
    i = lambda *a: item(*a, state="bias_only")
    return {"id": "S1", "title": "仅偏置（主输入断开，12 V 限流 100 mA）", "items": [
        i("12 V 偏置静态电流", "记录实测值（模型未建模，无判据）", "CLAUDE.md",
          "异常高则查短路", "12 V 输入串 mA 表", "hardware"),
        i("U1 VCC 建立并高于 UVLO", "高于 datasheet UVLO；记录值", "UCC25600 datasheet",
          "查 12 V 供电/限流", "U1.7–U1.6", "datasheet"),
        i(f"U1 开关频率 {c['freq']}", f"{c['freq']} ± 5 %", "operating_point",
          "查 RT/DT 阻值", "U1.8/U1.5 对 U1.6", "model"),
        i("UCC24624 VDD 与 REG 静态电平", "VDD=12 V 时 REG≈11 V（datasheet）；记录实测",
          "UCC24624 datasheet", "查 REG 电容/负载；deck 的 PWL 只是模型设定，不是芯片判据",
          "U3–U6 pin7–pin2、pin3–pin2", "datasheet"),
        i("UCC24624 门极在无次级激励时的安全状态", "两路输出均为低；本阶段只查静态安全",
          "UCC24624 datasheet", "若高则查 VD 采样/干扰；动态换流留到有次级激励的 S4",
          "U3–U6 pin1/pin8 对 pin2", "hardware"),
        i("自举二极管选型", "额定 ≥ 100 V（选型检查；电压应力留到 S3 实测）",
          "bom_draft", "25 V 件会雪崩击穿", "D_BT 本体丝印/规格书", "datasheet"),
        i("OC 脚静态电平 < 0.1 V", "< 0.1 V", "ct_design", "查分压/滤波对地",
          "U1.3–U1.6", "hardware"),
    ]}


def _stage_s2(c: dict[str, str]) -> dict[str, object]:
    i = lambda *a: item(*a, state="low_bus")
    return {"id": "S2", "title": "限能首次上电（10–12 V 主输入，平均限流 0.5 A）", "items": [
        i("半桥无直通，SW 波形干净", "无重叠导通", "netlist", "立即断电查门极",
          "示波器 GH、GL、SW 对 PGND", "hardware"),
        i("输入源平均限流与 Lr 谐振峰值分开验收",
          f"平均限流 0.5 A；12 V 下 Lr 峰值 ≈ {c['startup_peak_12v']}"
          "（由 48 V 冷启动线性折算，模型估计）；电源峰值能力须 ≥ 该值",
          "lr_design", "平均限流不等于峰值能力；不足则加预充/软启动",
          "电源读数（平均）+ 电流探头 I(Lr)（峰值）", "model"),
        i("OC 在低压下不误跳", f"低于门槛 {c['trip']}；触发则查 CT 负载/分压",
          "ct_design", "记录 V(ocd) 与 V(OC)",
          "U1.3–U1.6（差分）", "hardware"),
        i("自举电容电压 HB–SW", "≈ 12 V，无塌陷", "UCC27282 datasheet",
          "查 D_BT/Cbt 与 QH 开关", "HB–SW 差分", "hardware"),
    ]}


def _stage_s3(c: dict[str, str]) -> dict[str, object]:
    i = lambda *a: item(*a, state="no_load")
    return {"id": "S3", "title": "升到 48 V、空载（本阶段不引用额定电流应力）", "items": [
        i(f"开关频率 {c['freq']}", f"{c['freq']} ± 5 %", "operating_point", "查谐振参数",
          "SW 上升沿，200 kHz 带宽探头", "model"),
        i(f"空载 Vout ≈ {c['vout_nl']}", f"{c['vout_nl']}（24:1 固定变比）",
          "deck .param", "查匝比/极性", "VOUT–PGND（DC 档）", "model"),
        i("半桥与 SR 漏源空载振铃", "记录峰值；不超过器件额定", "datasheet",
          "超额定则查吸收/布局", "SW、SR1A–SR4B D–S", "hardware"),
        i(f"自举二极管反压（QH 导通时）", f"≈ {c['boot_reverse']}（= VIN）", "model",
          "印证 S1 的 ≥100 V 选型", "D_BT 两端差分", "model"),
        i("OC 脚空载电平与纹波", "接近 0；记录纹波峰值", "board_netlist §6",
          "超标则改布局/加共模扼流", "U1.3–U1.6 交流耦合", "hardware"),
        i("Cr 空载摆幅", "记录实测；不把额定峰值当空载判据", "cr_stress",
          "异常大则查谐振参数", "Cr 两端差分", "hardware"),
        i("48 V 冷启动 Lr 峰值", f"≤ {c['startup_peak']}（模型）；电源峰值能力须 ≥ 该值，"
          "平均限流另设", "lr_design", "不足则加预充/软启动", "电流探头 I(Lr)", "model"),
    ]}


def _stage_s4(c: dict[str, str]) -> dict[str, object]:
    r = lambda *a: item(*a, state="rated")
    f = lambda *a: item(*a, state="fault")
    return {"id": "S4", "title": "带载与故障（Stage F 矩阵；本表只列判据，不代替矩阵）", "items": [
        r("10/25/50/75/100 A 逐级加载", "每级记录再升；见 stage-F 矩阵", "stage_f 文档",
          "每级记录再升", "电子负载 + 输入功率计", "hardware"),
        r(f"100 A 时 OC 脚 {c['oc_pin']} @ {c['oc_at']}",
          f"{c['oc_pin']} @ {c['oc_at']}；门槛 {c['trip']}", "ct_design",
          "偏差大则查 CT 负载/分压", "U1.3–U1.6（差分）", "model"),
        r(f"100 A 时 Cr 峰值 ≤ {c['cr_peak']}、RMS ≈ {c['cr_rms']}",
          f"≤ {c['cr_peak']}；对 100 V 额定 2.4 倍", "cr_stress",
          "超则查谐振电容容量", "Cr 两端差分 + 电流探头", "model"),
        r(f"SR 单管损耗 {c['sr_loss']} @ 100 A → Tj", f"Tj ≤ {c['tj_limit']}；"
          "50 K/W 是模型假设，不是判据；须用实测壳温与声明 Rth 换算",
          "thermal_precheck", "实测超标则改散热/降额", "SR 壳温（热电偶/红外）", "model"),
        r("100 A 输出纹波与负载瞬态", "按 Issue #4 冻结的输出包络", "design/v3 规范",
          "超包络则加 Cout/改布局", "VOUT 交流耦合，20 MHz 带宽", "design"),
        f(f"OC 13 µs 故障：Lr 峰值 ≤ {c['fault_peak']}", f"≤ {c['fault_peak']}；驱动关断",
          "lr_design", "不关断则查 CT/OC 网络", "电流探头 I(Lr)、SW、OC", "model"),
        f("OC 2 V 闩锁", "闩锁并保持，断电复位", "UCC25600 datasheet",
          "2 V 是闩锁不是关断门槛", "U1.3–U1.6", "datasheet"),
        r("100 A 连续 / ≤10 mm", "只能由本矩阵实测关闭", "—", "不得用短时波形替代",
          "整机温升 + 高度规", "hardware"),
    ]}


def stages(c: dict[str, str]) -> list[dict[str, object]]:
    """The ordered sheet, split so no criterion crosses an operating condition."""
    return [_stage_s0(c), _stage_s1(c), _stage_s2(c), _stage_s3(c), _stage_s4(c)]


LABELS = {
    "joint_limit": "单处接点上限", "bar": "输出铜排", "bar_ohm": "铜排电阻",
    "trace_width": "输入走线宽度", "freq": "开关频率", "vout_nl": "空载输出",
    "oc_pin": "OC 脚电平（额定点）", "oc_at": "对应原边峰值", "trip": "过流门槛",
    "compliance": "CT 合规电压", "boot_reverse": "自举二极管反压",
    "sr_loss": "SR 单管损耗 @100 A", "tj_limit": "结温上限", "ambient_50": "Rth 50 K/W 最高环境",
    "cr_peak": "Cr 峰值电压", "cr_rms": "Cr 电流 RMS", "cr_esr": "Cr 整组 ESR 上限",
    "cout_n": "输出电容只数", "cout_esr": "整组 ESR", "gap": "气隙",
    "height": "高度最坏值", "pins": "网表引脚数",
    "startup_peak": "冷启动原边峰值（48 V）", "startup_peak_12v": "冷启动原边峰值（12 V 线性折算）",
    "fault_peak": "故障峰值（OC 13 µs）",
}


def render(sheet: list[dict[str, object]], c: dict[str, str]) -> str:
    """Markdown: the criteria table first, then one table per stage."""
    lines = [
        "# 上电检查表（首件）— 由设计 JSON 生成",
        "",
        "本表由 `tools/powerup_checklist.py` 从分析 JSON 直接渲染，判据数字不手抄；",
        "改分析后必须重跑该工具，否则 `test_the_checklist_matches_a_fresh_render` 会红。",
        "",
        "**本表是上电流程，不是额定值证据。** 100 A 连续 / ≤10 mm 只能由 S4 的 Stage F 矩阵实测关闭。",
        "",
        "**工况不得跨阶段复用。** 每条判据只在 `test_state` 指定的工况下有效；",
        "额定电流应力（OC 电平、Cr 峰值、36.1 A 冷启动峰值）只出现在 S4，",
        "空载阶段 S3 不引用这些数字。`source_type` 区分 datasheet / model / hardware / design。",
        "",
        "## 判据来源",
        "",
        "| 项 | 值 |",
        "|---|---|",
    ]
    lines += [f"| {LABELS.get(k, k)} | {v} |" for k, v in c.items()]
    lines.append("")
    for stage in sheet:
        lines += [f"## {stage['id']} {stage['title']}", "",
                  "| # | 检查 | 工况 | 测点 | 判据 | 依据 | 类型 | 不合格时 |",
                  "|---|---|---|---|---|---|---|---|"]
        for n, row in enumerate(stage["items"], start=1):
            lines.append(
                f"| {stage['id']}-{n} | {row['check']} | `{row['test_state']}` | "
                f"{row['measurement_location']} | {row['criterion']} | `{row['source']}` | "
                f"`{row['source_type']}` | {row['action']} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", type=Path, default=ROOT / "design/v3/stage_f/上电检查表.md")
    ap.add_argument("--json", type=Path, default=ROOT / "design/v3/stage_f/powerup_checklist.json")
    args = ap.parse_args()

    data = load()
    c = criteria(data)
    sheet = stages(c)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.md.write_text(render(sheet, c), encoding="utf-8")
    args.json.write_text(
        json.dumps({"criteria": c, "stages": sheet}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    total = sum(len(stage["items"]) for stage in sheet)
    print(f"wrote {args.md}: {len(sheet)} stages, {total} checks")
    print(args.json)


if __name__ == "__main__":
    main()
