# D1 V15：优先嘉立创元器件库的电容选型（NOT_FOR_FAB）

目的：优先选 JLCPCB/立创商城有正式料号、EasyEDA Pro 可检索**完整器件（符号+封装）**的电容，减少手工建库。该表仅为候选审核，不等于已经修改原生 PCB 的 MPN、封装或已备齐库存。

> **已发现关键工程错误**：原生项目多颗0603电容的显示值虽然是 1µF/2.2µF，实际旧器件号却统一保留 `CL10B104KB8NNNC`（100nF）、旧立创号 C1591。不能把“修改显示值”当成真正换料。必须通过 EasyEDA 器件替换完成关联、核对PCB焊盘，并在独立CAD版本复检。

## 立创库中可检索的候选

| 对应原件 | 设计需求 | 立创料号 / 官方型号 | 封装、额定电压与状态 |
|---|---|---|---|
| C7, C8, C9, C10 | 2.2uF | [C415535 / GRM188Z71E225KE43D](https://jlcpcb.com/partdetail/408029-GRM188Z71E225KE43D/C415535) | 0603, 25V X7R; PREFERRED_WITH_DC_BIAS_CHECK |
| C101, C103, C105, C107, C109, C111 | 1uF | [C92827 / TMK107B7105KA-T](https://jlcpcb.com/partdetail/TaiyoYuden-TMK107B7105KAT/C92827) | 0603, 25V X7R; PREFERRED_WITH_DC_BIAS_CHECK |
| C102, C104, C106, C108, C110, C112 | 100nF | [C282519 / TCC0603X7R104K500CT](https://jlcpcb.com/partdetail/TCC0603X7R104K500CT/C282519) | 0603, 50V X7R; PREFERRED |
| C11 | 47nF | [C5360859 / TCC0603X7R473J500CT](https://jlcpcb.com/partdetail/CCTC-TCC0603X7R473J500CT/C5360859) | 0603, 50V X7R; PREFERRED |
| C12, C6 | 10nF | [C3870462 / GMC10X7R103K50NT](https://jlcpcb.com/partdetail/4438956-GMC10X7R103K50NT/C3870462) | 0603, 50V X7R; PREFERRED |
| C13 | 1nF | [C126544 / GCM1885C1H102JA16D](https://jlcpcb.com/partdetail/137824-GCM1885C1H102JA16D/C126544) | 0603, 50V C0G; PREFERRED |
| C5 | 220nF | [C2760544 / TCC0805X7R224M500DT](https://jlcpcb.com/partdetail/CCTC-TCC0805X7R224M500DT/C2760544) | 0805, 50V X7R; PACKAGE_SWAP_REQUIRED |

## 输出72颗大容量电容：保留低ESR、优先现有真实料号

| 来源 | 电气规格 | 已检索可用信息及结论 |
|---|---|---|
| [C2158170 / T530X477M006ATE004](https://www.lcsc.com/zh-CN/product-detail/C2158170.html) | 470µF/6.3V/4mΩ | LCSC page showed 1 unit at lookup; NOT enough for 72 PCB output capacitors；HOLD_QTY72_STOCK_AND_RIPPLE_DERATING |
| [C2158667 / T530X477M006ATE005](https://www.lcsc.com/zh-CN/product-detail/C2158667.html) | 470µF/6.3V/5mΩ | LCSC page showed 5 units, still fewer than 72; no approved substitution until manufacturer footprint & ripple checks；HOLD_TECHNICAL_AND_STOCK_APPROVAL |
| [C4952536 / T530X477M006ATE010](https://www.lcsc.com/zh-TW/product-detail/C4952536.html) | 470µF/6.3V/10mΩ | ESR 2.5x original; no direct blanket substitution allowed；NOT_AUTOMATICALLY_EQUIVALENT |

**优先选择原来指定的 C2158170：** 虽然立创商城可找到原厂料号，但是检索页面显示库存不足以组装72颗。C2158667 仅作 5mΩ 备选；C4952536 是10mΩ，绝不可直接作为4mΩ等价替代。需要按实际输出纹波电流和100°C下ESR/损耗重新评估，再核厂家库存/PCBA选配。

## 暂不能简单从立创库替换的器件

- **Cin**：Real 48V input HF bypass + bulk, not the 100nF placeholder。Choose 100V X7R/film/hybrid with ripple/height and reconstruct true layout; 100nF 100V JLC C344180 may serve as auxiliary HF bypass only, not whole bank。
- **Cr**：Resonant Cr required film-rated I_RMS, dV/dt, dissipation, 200kHz。Do not replace resonant film with commodity MLCC even if a JLC symbol exists。
- **Cout**：Legacy output bank schematic symbol (CHB01..CHB72 real discrete output capacitors)。Maintain correct 72 physical CHB device ownership; do not duplicate Cout or replace all without ESR/thermal/size review。

## 自动化替换顺序与制造门禁

1. 在现有嘉立创窗口 `Shift+F` 选择**LCSC商城/立创商城**搜索引擎，按表中C料号找**器件**，而非只有独立符号或独立封装；确认器件库显示正确的制造商MPN、封装、管脚、温度及额定电压。
2. 优先修复**6颗1µF C101–C111，4颗2.2µF C7–C10，6颗100nF C102–C112**的真实器件引用：PCB封装0603在几何上可能相同，但要依照原理图→PCB更新流程替换并核实pad和BOM，不能直接改`Ref Value`。
3. C5从0603 100nF换到0805 220nF属于**真实封装和布局变更**，必须重新DRC。47nF/10nF/1nF等测量/滤波电容按各自值替换。
4. 72个CHB不得以“有EasyEDA封装”为理由直接更换全体，需先确定72颗数量能否由嘉立创实际SMT备料；若缺货可考虑预订，或重新评价5mΩ等效方案，并核PTH/焊盘空间。
5. 所有选择仅标记为**供应商名录已检索**，仍需实体EasyEDA原生 `device ID → schematic symbol → PCB footprint` 现场绑定验证，且原生PCB重开/DCR/生产BOM一致，才可认定成功。
6. 不改用户已有 `placeholder_eco.csv` / `.json` 未提交的手工资料；这份单独登记是设计决策基线。

参考：嘉立创EDA Pro官方[器件库说明](https://prodocs.lceda.cn/en/faq/library/)；[BOM器件标准化](https://prodocs.easyeda.com/en/pcb/order-order-parts/)。
