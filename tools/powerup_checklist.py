"""Generate the first-power-up checklist from the design JSONs.

The roadmap names "上电检查表" as a Stage D deliverable.  A checklist typed once by
hand drifts away from the analysis that justified it, so every acceptance number
here is formatted out of the JSON that produced it and the committed markdown is
compared byte-for-byte with a fresh render in a test.

The sheet stops at "48 V, no load" and hands the rest to the stage-F matrix
(`design/v3/stage_f/首样验证与额定值判定_2026-10-31.md`); it does not restate it.

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


def stages(c: dict[str, str]) -> list[dict[str, object]]:
    """The ordered sheet.  Each item is (check, criterion, source, if it fails)."""
    return [
        {"id": "S0", "title": "板前（完全断电，万用表/四线法）", "items": [
            ("VIN_P 对 PGND 不短路", "> 1 kΩ（Cout 充电后）", "netlist", "查铜排/电容极性/焊接桥"),
            ("八只 SR 漏源不短路", "二极管档有值、非 0", "netlist", "拆管复测"),
            ("十只 2.2 Ω 门阻、八只 0 Ω 开尔文链在位", "逐位号清点，合计 18 只",
             "board_netlist", "缺 0 Ω 则 SR 关断依赖焊盘 di/dt"),
            (f"输出铜排 {c['bar']} 的电阻", f"{c['bar_ohm']}（20 °C，几何）",
             "connector_budget", "改宽度/厚度后重算"),
            (f"两处接点四线法，单处 ≤ {c['joint_limit']}", f"≤ {c['joint_limit']}",
             "connector_budget", "超标则改压接或重算效率口径"),
            (f"输入走线宽度 ≥ {c['trace_width']}", f"≥ {c['trace_width']}（2 oz 或等效）",
             "connector_budget", "改叠层/加铜厚"),
            (f"输出电容 {c['cout_n']} 只、整组 ESR ≈ {c['cout_esr']}",
             f"{c['cout_n']} 只；ESR 主导，不是容量", "cout_bank", "少买则 ESR 超标"),
            (f"整机高度最坏 {c['height']}", "≤ 10 mm", "magnetics_design", "改沉槽/夹具"),
            (f"气隙 {c['gap']}、四套 Lm 一致性", "首件实测回填", "magnetics_design",
             "漏感实测前不冻结 Lr 料号"),
        ]},
        {"id": "S1", "title": "仅偏置（主输入断开，12 V 限流 100 mA）", "items": [
            ("12 V 偏置静态电流", "记录实测值（模型未建模，无判据）", "CLAUDE.md", "异常高则查短路"),
            (f"U1 开关频率 {c['freq']}", f"{c['freq']} ± 5 %", "operating_point", "查 RT/DT 阻值"),
            ("U1 两路门极交替、死区可见", "无重叠", "ct_design", "查 UCC27282 输入"),
            ("REG 建立到 11 V（150 µs PWL）", "≈ 11 V", "deck PWL", "查 REG 电容/负载"),
            ("四组 UCC24624 门极有驱动、经 2.2 Ω", "逐组可见", "board_netlist", "查 REG/VD 采样"),
            (f"自举二极管反压 {c['boot_reverse']}", "选型 ≥ 100 V（实测反压 = VIN）",
             "bom_draft", "25 V 件会雪崩击穿"),
            ("OC 脚静态电平 < 0.1 V", "< 0.1 V", "ct_design", "查分压/滤波对地"),
        ]},
        {"id": "S2", "title": "限能首次上电（10–12 V 主输入，限流 0.5 A）", "items": [
            ("半桥无直通，SW 波形干净", "无重叠导通", "netlist", "立即断电查门极"),
            ("Lr 启动峰值可被电源吸收", f"限流 ≥ {c['startup_peak']}（48 V 冷启动）",
             "lr_design", "电源必须先限流再升压"),
            ("OC 无跳闸；确认保护仍有效", f"故障峰值可达 {c['fault_peak']}（OC 13 µs），"
             f"门槛 {c['trip']}", "lr_design", "门槛偏离则查 CT 负载/分压"),
        ]},
        {"id": "S3", "title": "升到 48 V、空载", "items": [
            (f"开关频率 {c['freq']}", f"{c['freq']} ± 5 %", "operating_point", "查谐振参数"),
            (f"空载 Vout ≈ {c['vout_nl']}", f"{c['vout_nl']}（24:1 固定变比）",
             "deck .param", "查匝比/极性"),
            (f"额定点 OC 脚 {c['oc_pin']} @ {c['oc_at']}", f"按负载比例外推；门槛 {c['trip']}",
             "ct_design", "偏差大则查 CT 负载/分压"),
            (f"Cr 峰值 ≤ {c['cr_peak']}（额定点）", f"≤ {c['cr_peak']}；对 100 V 额定 2.4 倍",
             "cr_stress", "超则查谐振电容容量"),
            (f"Cr 整组 ESR ≤ {c['cr_esr']}", f"≤ {c['cr_esr']}（1 W 允许）", "cr_stress",
             "换低 ESR 并联"),
            ("OC 网络共模注入", "记录 OC 脚纹波；设计未建模", "board_netlist §6",
             "超标则改布局/加共模扼流"),
        ]},
        {"id": "S4", "title": "交接 Stage F 矩阵（本表不再展开）", "items": [
            ("10/25/50/75/100 A 逐级加载", "见 stage-F 矩阵", "stage_f 文档", "每级记录再升"),
            (f"SR 单管 {c['sr_loss']} @ 100 A → Tj", f"Tj ≤ {c['tj_limit']}；40 °C 环境需 Rth ≤ 50 K/W",
             "thermal_precheck", "50 K/W 时最高环境 79.1 °C"),
            ("100 A 连续 / ≤10 mm", "只能由本矩阵实测关闭", "—", "不得用短时波形替代"),
        ]},
    ]


LABELS = {
    "joint_limit": "单处接点上限", "bar": "输出铜排", "bar_ohm": "铜排电阻",
    "trace_width": "输入走线宽度", "freq": "开关频率", "vout_nl": "空载输出",
    "oc_pin": "OC 脚电平（额定点）", "oc_at": "对应原边峰值", "trip": "过流门槛",
    "compliance": "CT 合规电压", "boot_reverse": "自举二极管反压",
    "sr_loss": "SR 单管损耗 @100 A", "tj_limit": "结温上限", "ambient_50": "Rth 50 K/W 最高环境",
    "cr_peak": "Cr 峰值电压", "cr_rms": "Cr 电流 RMS", "cr_esr": "Cr 整组 ESR 上限",
    "cout_n": "输出电容只数", "cout_esr": "整组 ESR", "gap": "气隙",
    "height": "高度最坏值", "pins": "网表引脚数",
    "startup_peak": "冷启动原边峰值", "fault_peak": "故障峰值（OC 13 µs）",
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
        "## 判据来源",
        "",
        "| 项 | 值 |",
        "|---|---|",
    ]
    lines += [f"| {LABELS.get(k, k)} | {v} |" for k, v in c.items()]
    lines.append("")
    for stage in sheet:
        lines += [f"## {stage['id']} {stage['title']}", "",
                  "| # | 检查 | 判据 | 依据 | 不合格时 |", "|---|---|---|---|---|"]
        for n, (check, crit, src, action) in enumerate(stage["items"], start=1):
            lines.append(f"| {stage['id']}-{n} | {check} | {crit} | `{src}` | {action} |")
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
