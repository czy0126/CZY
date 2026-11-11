## 审核结论

**代码缺陷（P0）：`_verified_cout()` 把 nominal screen 当成 operating gate。** `supplier_rfq_low_esr_target_met = esr_mohm/n <= 0.07` 直接拿室温 100 kHz 单体 MAX 值除 n，未乘 EOL/热态倍数、未用实际频率 ESR，`n` 增大即可“通过”——这是以未知（热态/200 kHz/DC-bias/EOL）当通过，与 P0 热态 `<=0.07 mΩ` 冲突。同函数 `supplier_rfq_high_voltage_target_met = v >= 4` 只查单体额定电压，未查整组（串联/均压/瞬态），也是名义通过。

### 最小修复（仅改该函数 + 调用处）

```python
def _cout_gates(dossier: dict) -> dict:
    main = dossier["main_energy_storage"]; r = main["rated"]
    n = main["preliminary_parallel_bank"]["quantity"]
    esr25 = r["esr_mohm_at_100khz_25c_MAX"]
    lim = main["series_datasheet_esr_limits"]
    eol = lim["endurance_105c_rated_voltage_2000h_esr_max_multiple_of_initial"]
    hot_esr = r.get("esr_mohm_hot_at_actual_freq_MAX")   # 未知则为 None
    hot_bank = None if hot_esr is None else hot_esr / n
    return {
      # nominal screen —— 只作筛选，不作放行
      "nominal_screen_esr_pass": esr25 / n <= COUT_ESR_RFQ_TARGET_MOHM,
      # verified operating-condition gate —— 未知即 FAIL
      "verified_operating_esr_meas_mohm": hot_bank,
      "verified_operating_esr_pass": (hot_bank is not None
          and hot_bank * eol <= COUT_ESR_RFQ_TARGET_MOHM),
      "verified_operating_voltage_pass": r["rated_voltage_v"] >= COUT_VRATED_MIN,
      "gate_basis": "hot/EOL/actual-frequency; UNKNOWN != PASS",
    }

# 调用处替换两个 bool：
g = _cout_gates(dossier)
extra["supplier_rfq_low_esr_target_met"]   = g["verified_operating_esr_pass"]
extra["supplier_rfq_high_voltage_target_met"] = g["verified_operating_voltage_pass"]
extra["nominal_screen_only"] = not g["verified_operating_esr_pass"]
extra["status"] = ("PENDING_HOT_ESR_UNKNOWN" if g["verified_operating_esr_meas_mohm"] is None
                   else extra["status"])
```

要点：`None`/缺失 → `False`；`eol` 必须参与门；nominal 结果单列，禁止驱动 `confirmed_met`。`g2` 的 `next_actual_eda_action` 文案改为“**重新按整组 15x→N 由容量容差/纹波ΔV/ESR(热态·实际f)/互连电阻反算，不沿用 15 颗**”，并附公式输入栏，不做新报告文件。

### 有验收标准的优先任务

- **T1（P0）**：`_cout_gates` 单测——给 `hot_esr=None`、`n=15/30`、`eol=2` 三组，断言 `verified_operating_esr_pass is False` 且 `nominal_screen_esr_pass` 不影响放行；`v=2.5` 时 `high_voltage_pass is False`。验收：`pytest` 全绿，register 中 Cout 项 `verified_operating_esr_pass=false`。
- **T2（P0）**：`qty` 重算函数 `size_cout_bank()`，输入待填（Vripple、Irip、Tmax、f、ESR_hot、R_interconnect），输出 N 与失败原因；缺任一输入 → `PENDING`。验收：缺输入不产出数字。
- **T3（P1）**：从 Yaleo A700-A720 **2026-04-01 版** datasheet 逐型号摘录 ≥4 V 候选的 ESR@实际 f/温度、EOL 倍数、纹波电流；**未读不填**。验收：`source_version=="2026-04-01"` 且每字段有页码/表号，否则 `UNKNOWN`。
- **T4（P1）**：CAD 只承认 `107 线/199 错误` 可复核父板；132 线/回执缺失项标 `UNVERIFIABLE`，**不重复路由**。验收：register 中 132 线引用数为 0。

未做 EDA、未做实测、未读新 datasheet，以上不含任何实测或放行声明。