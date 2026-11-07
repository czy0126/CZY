# D1 | 15 V SR 偏置电源改版候选：TPS26630 + 外部反灌阻断

**状态：OEM_SOURCED_CONCEPT_NOT_FOR_FAB。** 本设计包为现有 pcb/bias_cut_eco 提供下一版原生 KiCad 图的真实厂家料号、引脚、计算和参考电路；它**不是**原生 KiCad 工程，也不是硬件、ERC 或投板批准。

## 1. 设计架构与决策

现有 Q50/Q51/Q55 的 P-MOS 尚未定型、反向截止取决于阈值协调：行为级 16 V 阈值失配示例有约 0.617 A 反灌；旧仿真约 169 A 理想浪涌模型没有对应器件 SOA。Q54+R57=47Ω/0.25W 在外源持续 18 V 时耗散约 6.315 W。现有逻辑测试成功不能抵销这些问题。

因此分三个功能设计：
- **电源通路**：TPS26630RGET 内置限流高边 FET + Q1 CSD19537Q3T 外部反灌阻断 N-FET + Q2 BSS138-7-F 栅极快速下拉 FET。
- **故障快速关断与锁存**：原 SR 板的 FAULT_G→Q41/R44→REG UVLO 保留；独立 5 V 故障锁存的 ENABLE_5V 接 U1.SH​​DN，控制掉电默认关断。TPS26630 MODE 引脚保持开路选择过载锁断，不取代外部故障锁存。
- **电容放电**：**未完成**。本方案绝不将持续通电的 Q54+47Ω/0.25W 搬到新板并声称通过。需要独立的逆流检测/能量受限放电设计，验证外部反灌与 H1/H5。

这是 UCC24624 的 **15 V SR 偏置域**，不是 48 V→2 V / 100 A 主电流路径。11.1 µF 是 SR 样板 C1+C2+C3 的名义等效值；实际有效值须计入直流偏置和容差。

## 2. 可编辑示意图及实际引脚

- [可编辑矢量电路示意](tps26630_reference_concept.svg)
- [U1/Q1/Q2 厂商逐脚连接表](tps26630_pinmap.csv) — **本包唯一 CAD 引脚映射输入**
- [器件与报价候选清单](component_candidates.csv)

~~~text
                 Q1 100V NFET (CSD19537Q3T)
VIN_SYS (15 V) ---- S(1,2,3) --- D(5,6,7,8) ---- EFUSE_IN ---- U1.IN(1,2)
                        G(4)                                       TPS26630RGET
                         |                                               |
U1.B_GATE(3) ------------+--- Q2.D(3)                                  +--- OUT(17,18) -- VDD_SR
VIN_SYS --------------------- Q2.S(2)                                                    |-- 11.1uF -- PGND
U1.DRV(4) ------------------- Q2.G(1)
 
VIN_SYS -- 909k -- UVLO(6) -- 35.7k -- OVP(7) -- 64.9k -- PGND
dVdT(9) -- 22nF -- PGND              ILIM(10) -- 30k -- PGND
GND(8), EP -- PGND                  MODE(11) = OPEN, overload latch-off
SHDN(12) <- 1k <- ENABLE_5V         SHDN(12) -- 100k -- PGND (fail-off)
FLT(14) optional open-drain monitor; IMON(13), PGOOD(16) unconnected
PGTH(15) -> PGND if PGOOD unused (must be checked); NC pins 19–24 open
~~~

**关键极性**：依据 TI Figure 8-7，外部 Q1 源极接 VIN_SYS、漏极接 U1.IN，G 由 B_GATE 驱动。Q2 的源极接 VIN_SYS、漏极接 B_GATE、栅极接 DRV。Q1 DQG8 实体脚 1–3=S、4=G、5–8=D；Q2 BSS138-7-F SOT23 1=G、2=S、3=D。TI TPS26630RGE 的 24 脚与 TPS26631PWP 20 脚**不能混用**；曝光焊盘 EP 的封装和热过孔尚需原生 CAD 校验。

## 3. 参数初稿与公式

命令：python tools/tps26630_bias_design.py --check；离线测试：python -m pytest -q tools/test_tps26630_bias_design.py。

| 参数 | 第一版设定 | 数据与解释 |
|---|---:|---|
| VIN_SYS | 15 V；工作区间设计示意 14.25–15.75 V | U1 允许 4.5–60 V；**绝不能直接采用默认内部 UVLO ≈15.6 V**，因为其值高于本项目标称 15 V |
| UVLO 分压：Rtop / Rmid / Rbottom | 909k / 35.7k / 64.9k，均 1% | TI Rev.G Eq9/10，按 1.2V 典型基准得到 UVLO ≈12.04V，OVP ≈18.67V |
| R_ILIM | 30.0 kΩ / 1% | Eq8：R_ILIM(kΩ)=18/I_lim(A)，名义限流约 0.6 A |
| C_dVdT | 22 nF / 16V X7R | Eq2：t=20.8×10³·VIN·C_dVdT≈6.864 ms |
| C_OUT | 11.1 µF 等效银行 | Eq1：Icharge≈C_OUT·VIN/t≈24.3 mA；½CV²≈1.25 mJ |
| 平均芯片内 FET 启动耗散 | ≈0.182 W | Eq3：0.5·VIN·Icharge；不是 SOA 或热通过 |
| 假设 15µF、CdVdT=19.8nF、额外 50mA 负载 | ≈86.4 mA 总平均 | 自定义偏差情景，不是全温保证 |

这些结果来自厂家典型公式和示意条件，**不保证 TPS26630 真正瞬态电流峰值永远 ≤0.6 A**。芯片存在传播延迟和快速故障响应；实际尖峰、FET SOA、温升必须用 OEM 模型和真实样板验证。上面所谓 1% 电阻、2% 比较基准的 Python 敏感性筛选同样只是设计情景，并非所有极限值均已被厂家保证。

## 4. 已检索到的准确器件

| 参考 | 真实候选 MPN | 原厂核对内容与使用状态 |
|---|---|---|
| U1 | **TPS26630RGET** | TI active，RGE 24 pin VQFN；非 RGE 24 的型号不能用同一引脚表 |
| Q1 | **CSD19537Q3T** | TI EVM Q1 参考型号的小卷带后缀，100V、10V 栅压下 Rds(on) max 14.5mΩ；DQG8 封装 |
| Q2 | **BSS138-7-F** | Diodes Inc BSS138，SOT23，50V、Vgs±20V、Ciss **最大 50pF**（仅 VDS=10V、25°C、1MHz；设计保证，非逐颗测试）；超出该测试条件仍需验证 |
| CIN | **C3216X7R2A105K160AA** | TDK 1µF/100V X7R 1206，TI EVM 物料表 |
| CdVdT | **C0603C223K4RACTU** | KEMET 22nF/16V X7R，TI EVM 物料表；直流偏压有效容值待查 |
| RILIM | **CRCW060330K0FKEA** | Vishay Dale 30kΩ±1% 0603，可采购料号，但本板热/焊盘尚未验证 |
| 909k、35.7k、64.9k、SHDN串联及下拉 | **已核实准确料号** | Rtop CRCW0603909KFKEA、Rmid CRCW060335K7FKEA、Rbot CRCW060364K9FKEA、SHDN R_EN_SER CRCW06031K00FKEA、SHDN R_EN_PD CRCW0603100KFKEA，均 Vishay Dale 0603 1%；仍需统一原生 PCB 焊盘和厂商公差验证 |
| C_OUT 银行、反灌受限放电器件 | **TO_SELECT / EXISTING** | 不自动当作一颗 11.1µF 电容或一个已经验证的放电回路 |

**优先购真实厂商评估板**：TI [TPS26630-33EVM](https://www.ti.com/tool/TPS26630-33EVM)，说明书 [SLVUBI8A](https://www.ti.com/lit/ug/slvubi8a/slvubi8a.pdf) 含原理图、布局、BOM、测试方法。该 EVM 默认 24 V 工业条件，**在 15 V 使用前必须调整 UVLO/OVP/限流/启动设定**，避免照抄原跳线。

## 5. 串并行工作与可验收出口

| 工序 | 下一项实际交付 | 验收边界 |
|---|---|---|
| A 原生 CAD | 用本包引脚表画 TPS26630 RGE24、CSD19537Q3、Diodes BSS138-7-F、分压、CdVdT、ILIM、SHDN，完成原生 ERC/网表/封装检查 | 原生网表脚号与 CSV 一致、ERC 问题解决、曝光焊盘实际映射正确；当前尚未完成 |
| B 器件模型 | 选用 TI/TINA 或 PSpice 模型，逐个跑 14.25/15/15.75V、16/18V 外灌、输入丢失、故障/复位/5V掉电、15µF容差与温度 | 证明限流、反灌、Vgs和SOA，并记录仿真 hash；当前不冒充已跑 |
| C 放电拓扑 | 采用 reverse-aware 或单次能量受限放电，不长期让 47Ω承受18V外灌 | 明确 Rdis 脉冲功率/脉宽/重复率与后续 VDD_SR 是否仍被强制抬高；反例先于布板 |
| D 实物验证 | EVM 或工程样板、同步获取 H1/H5 真实原始示波器数据及偏置电流 | 证明 REG、VGS、VDD 和反馈在真实门极受激励后保持正确；无实测则不通过 |
| 并行主板 | T1–T4/Lr真实端子 DOT、48V→2V/100A 铜路、主板可检查封装/布局 | 与辅助板并行，而非反复等待偏置模型；不改变 D1≤16mm 首样的独立出图流程 |

### 原厂与权威参考
1. TI TPS2663x datasheet Rev.G SLVSE94G (2024-06) Figure5-1/Table5-1/Figure8-7/Eq1–3/8–10：https://www.ti.com/lit/ds/symlink/tps2663.pdf
2. TI TPS26630-33EVM User's Guide Rev.A SLVUBI8A (2019-03) Figure11 / Table12：https://www.ti.com/lit/ug/slvubi8a/slvubi8a.pdf
3. TI CSD19537Q3 100V MOSFET Rev.B SLPS549B Figure3-1：https://www.ti.com/lit/ds/symlink/csd19537q3.pdf
4. Diodes Inc BSS138 Rev.25-2 (2024-06), pin 1 Gate / 2 Source / 3 Drain; Ciss MAX 50pF at VDS=10V, 25C, 1MHz, guaranteed by design but not production tested：https://www.diodes.com/datasheet/download/BSS138.pdf
5. 对照备选 TI LM7480（反灌阻断，但不等于 eFuse 有限流）：https://www.ti.com/product/LM7480

**任何源文件中出现的“能画图/料号已知”都不等于 SOA、热、磁件或 PCB 制造已批准。**
