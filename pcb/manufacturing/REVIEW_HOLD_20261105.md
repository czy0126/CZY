# 2026-11-05 制造及集成状态（接口ECO后）

FAB_PACKAGE_PRESENT只表示文件存在，不表示装配或硬件保护已签核。

数字极性P0已实施并通过原生网表集成检查：快OC J1.4为低有效FAST_EXT_N，仅连接D0 J10.4；U11F反相为FAST_EXT_H，经新增U19与旧高有效FAST_TRIP做OR，再送U6。两条故障来源互不压制。旧版接到TP8/FAST_TRIP的说明永久作废。

D0原理图/网表、快OC原理图/网表/PCB及13件制造文件已重生成，ERC和快板DRC均0。D0只有原理图，没有可投板PCB。

仍待关闭：模块电源断线时OCD/D2反灌的**台架验证**（设计已改：D3 BAT54W隔离连接器与模块轨、R7改挂连接器侧，结构上J1.1失电必为低；BF-01…BF-08八例全部`executed:false`，反灌电流0.40 mA对静态5 mA、撑到2.7 V需原边1593 A，残余为D3开路或电源脚开路时上拉看不见负载消失）；整域掉电/UVLO；R44厂家脉冲曲线与MPN（现为TO_SELECT，单次122.7 µJ/峰25.23 W/等效4.87 µs待查表）；Q41开通过渡SOA与自热（AO3400A已选型但qualified=false）；真实REG/门极关断波形。断信号线的数字逻辑通过，不等于掉电故障硬件通过。

新增反相与OR的延迟已按厂表定价：CD4069UB §6.5 与 CD4071B 动态表在 VDD=5 V 给 **55/110 ns** 与 **125/250 ns**（typ/max），合计 **0.36 µs max、0.18 µs typ**（`design/v3/stage_f/d0_response_budget.json:stages.external_fast_logic`，两份数据手册已入 `references/datasheets/`）。两条都是 **TA=25 °C 的 max，不是全温区 max**；引用条件为 TA=25 °C / CL=50 pF / RL=200 k / 输入沿 20 ns——实际负载只有一只 CD4071B 输入（≤7.5 pF），条件偏重、方向保守；20 ns 沿由 Q1 拉低满足，释放沿经 R7 10k 更慢，慢释放会让 FAST_COMBINED 停在故障电平，不是保护漏洞。**该数不并入旧 LM393 路径的总数**（起点不同且含 127.6 µs 滤波），状态为 `PARTIALLY_PRICED_NOT_INCLUDED_IN_TOTALS`；仍未定价的是 Q1 边沿与布线电容、UCC24624 REG 放电与最末一路门极关断，以及 **U6.4 的 max**。**FAST_COMBINED 之后的解码已定价**（2026-11-05）：三只 CD4071B OR（U10.1–3）按 250 ns max 逐通道计入（硬 0.75 µs、快 1.00 µs、外部 1.11 µs），U10.4 的 ACK 清除另计 0.25 µs 但不在跳闸通路上；U6.4 是 CD4081B，厂表没有动态电气表，按 0 计入并列入 `unpriced_gates`，快通道总数仍是地板。

采购缺口第1项已关闭一半：D1/D2为Vishay BAT54W-E3-08（SOD-123，MPN与焊盘对应已写回BOM/生成器，仓库land与厂家推荐差0.05 mm中心距，判"兼容但非厂家land"）；Q41为AO3400A（3.63 V门限下12.11 µs，旧1.5 Ω占位15.81 µs不得再引用）。选中不等于合格，两块板的qualified仍为false、hardware_built/fabrication_approved不变。见 docs/2026-11-05_实验板采购缺口与应力复核.md。

见 docs/2026-11-05_快OC接口ECO实施记录.md。实验板制造就绪与整机100A运行资格分别验收；本记录不批准主板制造或高能量运行。
