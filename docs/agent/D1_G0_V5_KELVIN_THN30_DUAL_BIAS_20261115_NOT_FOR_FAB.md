# D1 G0 V5 — 四路 SR Kelvin 实体 PCB ECO + 两路 Traco 48V→12V 偏置子板

**主板仍以V5为最新；偏置子板已继续迭代至V6，加入两只TPS3710及隔离光耦健康信号和可编辑30器件原生KiCad。最新子板参考 docs/agent/D1_G0_V6_UVLO_GX14_CONTACTOR_HANDOFF_20261115_NOT_FOR_FAB.md。两版均为NOT_FOR_FAB且G0未获实体批准。**

日期：2026-11-15。**状态：G0 BLOCKED / G1 PENDING / NOT_FOR_FAB；不可直接制造或上 48V。**

## 推荐的两个 KiCad 10 可编辑交付包

**主板 V5：** hardware/dcx_main/g2/d1_g0_UCC24624_KELVIN_V5_INTEGRATED_MAINBOARD_NOT_FOR_FAB/G0_V5_161_PART_KELVIN_SOURCE_AUTHORED_EDITABLE_KICAD_NOT_FOR_FAB.zip

**两路隔离 12V 子板：** hardware/dcx_main/g2/d1_g0_dual_THN30_bias_carrier_NOT_FOR_FAB/G0_TWO_THN30_4812_REAL_BIAS_CARRIER_EDITABLE_KICAD_NOT_FOR_FAB.zip

均包含原生 KiCad PCB、原生 SCH、PRJ、完整本地符号库、独立网表、BOM、原生 ERC/DRC 与 SHA 签核阻断报告。各目录打开同名前缀的 .kicad_pro。保留 V1–V4 供比对。

## ① 主板 UCC24624 VSS / REG 数据手册修复

依据 Texas Instruments UCC24624 Rev C：
https://www.ti.com/lit/ds/symlink/ucc24624.pdf

- UCC24624 第2脚 PGND 是门驱峰值电流回路；第5脚 VSS 用于 SR MOSFET 压降检测，避免与大电流回路共走线；第3脚 REG 推荐就近 2.2µF 对 PGND。
- 在 V4 原有 157 器件 PCB 上，直接将 U3–U6 pin5 改为四路独立 SR_KELVIN_1..4，四条低电流检测网络通过 In9.Cu 连接至四个实际 0603 RK1–RK4 0Ω 焊盘，RK 各自另一端焊盘连接靠近 SR MOS Source 区域的本地 SR_SOURCE_RETURN 铜区，UCC pin2 PGND 留在门驱回流网络。
- 原 C7–C10 的 0603 实体封装将 Value 由占位件改为 Murata GRM188C71E225KE11：X7S、2.2µF 标称、25V、0603（Murata厂家资料：https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/GRM188C71E225KE11-01A.pdf）。在约11V REG 下**直流偏压降容未校核**；可能需要增大封装、并联或重新选择电容。
- 该方案在 SR Source 区域附近本地铜区形成 0Ω Kelvin 分界，**没有独立的至每只 MOSFET 源极端子的完整专用 Kelvin 导体、没有实测地弹跳和VSS偏移**。真实关断阈值与两只 SR 的布局权衡必须再确认。
- V5 PCB **161个原生封装、原生KiCad DRC=0、未连接=0；独立 SPICE 黄金电路+明确 Kelvin ECO 生成的 SCH 441组 Ref/Pin/Net 全部逐脚核对，原生 ERC=0**。
- 主副边仍维持独立 PGND / SR_SOURCE_RETURN 分区；原 V4 两个外部偏置12V接口继续保留；R8 使能电阻保持 DNP，不允许自动功率开机。

## ② 两路真 Traco THN 30-4812 隔离 12V 子板

厂家：https://www.tracopower.com/products/thn30.pdf （Traco 2024-02-07资料）。

THN 30-4812：36–75VDC输入、12V/2.5A/30W标称输出，典型效率90%，输入输出1600VDC功能绝缘测试规格；本项目并未通过完整 PCB 绝缘认证。

- 独立**2层PCB**，实例化本机 KiCad 官方 Converter_DCDC_TRACO_THN30-xxxx_THT 六引脚通孔封装，而不是仅把零件名称写进清单。核对孔位及引脚编号：1 +Vin，2 −Vin，3 +Vout，4 Trim，5 −Vout，6 Remote。
- 48V预急停输入同时供应 U1/U2，但经过各自独立的 F1/F2 2A慢断熔断器候选位与各自1µF/100V输入电容。必须取得实际2A慢断 DC分断能力、I²t及过流/浪涌认证，当前18xx封装仍未验证供应商型号。
- 每路输出两只22µF/25V 1210 X7R候选与一组2针5mm输出端子。U1输出12V-P/PGND；U2输出12V-S/SR_SOURCE_RETURN。输入地PGND与第二只模块输出地SR_SOURCE_RETURN 在原生PCB上**没有相连**，底层分为 L形 PGND 区与独立副边回流区，两块上层12V输出铜岛分别铺铜。
- 子板 J_P 接主板 J_BIAS_P（VCC12/PGND），J_S 接 J_BIAS_S（VCC12_S/SR_SOURCE_RETURN），实际端子MPN、线束耐压、连接极性与防反插未签核。子板并非已物理装配。
- **实际 KiCad**：13个真实封装、34个独立设计 Ref/Pin/Net，原生PCB DRC0、未连接0，SCH ERC0。

## 安全限制必须保留

Traco THN30 Remote Pin6 留NC，官方定义开路为默认 ON，因此这块子板不能充当紧急停机。它拟通过独立的限流48V偏置回路供电，必须在主功率48V硬件断能器之前取电，使主功率急停时仍保持门极关断所需偏置；该实物供电/掉电保持时间未签核。主板仍缺失经认证的48V物理断能急停、完整UVLO、真实高侧 GH−SW VGS检测、十路全故障门极强制下拉、厂商实体磁件T1–T4及CT的端子/DOT/绝缘签核。

此外：12层过孔塞孔/层压板绝缘、LLC高频功率铜损、开槽与母排DFM、EMC、散热、两只THN模块输入浪涌和厂家建议的220µF/100V附加抑制、输出电容电压降额、硬件安全/60组示波器数据均缺失。原主板5类 KiCad ignored DRC 保留待审查，**不允许软件置位硬件安全PASS**。

## 可重复验证

从仓库根目录使用 Windows KiCad10 bundled Python：
C:/Users/27792/AppData/Local/Programs/KiCad/10.0/bin/python.exe

每个脚本分别运行 --check：
tools/d1_g0_sr_kelvin_reg_eco_v5.py
tools/d1_g0_sr_kelvin_independent_sch_v5.py
tools/d1_g0_package_sr_kelvin_v5.py
tools/d1_g0_traco_dual_bias_daughterboard.py
tools/d1_g0_traco_dual_bias_sch_package.py

标准Python命令：
python -m pytest tools/d1_g0_test_sr_kelvin_v5.py tools/d1_g0_test_traco_bias_carrier.py tools/d1_lane_c_test_g0_acceptance.py -q

python tools/d1_lane_c_g0_acceptance.py --check

当前G0九项物理验收仍为 PENDING，6种故障×10路VGS共60条原始波形仍需要实物捕获；任何一项未签核应继续拒绝48V主功率级上电。
